/* OmniLink Arduino 0.3 - ESP8266 / NodeMCU with phone provisioning and OTA,
   for OmniLink Server v0.6 over MQTT TLS (port 8883).

   - First boot opens the Wi-Fi hotspot "OmniLink-Setup" (http://192.168.4.1):
     choose Wi-Fi and enter server host, port, device ID and secret.
   - Settings are kept in LittleFS /config.json. Hold FLASH (D3) while booting
     to wipe them and reopen the hotspot.
   - Optional OTA (Arduino IDE network port and http://<board-ip>/update) is
     enabled only after you set OTA_PASSWORD below.
   - The OmniLink web client's "Download sketch" button pre-fills server_host,
     device_id and device_secret in this file.

   Pins match the server's demo device (python -m examples.create_demo):
     V0 Power BOOL, V1 Output selection UINT8 0..1, V2 Setpoint UINT32 1..300 s
     (measurement interval), V3 Measurement FLOAT32 read-only (A0, 0..100 %).
   Libraries: WiFiManager (tzapu) 2.0.16+, ArduinoJson 7, PubSubClient, OmniLink 0.3. */
#include <FS.h>
#include <LittleFS.h>
#include <ESP8266WiFi.h>
#include <DNSServer.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPUpdateServer.h>
#include <ArduinoOTA.h>
#include <WiFiManager.h>
#include <ArduinoJson.h>
#include <WiFiClientSecureBearSSL.h>
#include <PubSubClient.h>
#include <OmniLink.h>
#include <time.h>

// ===================== [CHANGE] 1. Hardware =====================
const uint8_t STATUS_LED = D4;   // built-in LED, active LOW: blinks while offline
const uint8_t RESET_PIN = D3;    // FLASH button, hold during boot to wipe settings
const uint8_t OUTPUT_A = D1, OUTPUT_B = D2;   // relay/LED GPIOs
const bool OUTPUT_ACTIVE_LOW = true;
const bool MEASUREMENT_ENABLED = true;        // false if nothing is wired to A0
const uint16_t PIN_POWER = 0, PIN_OUTPUT = 1, PIN_SETPOINT = 2, PIN_MEASUREMENT = 3;

// ===================== [CHANGE] 2. Security =====================
// TLS verification uses the server's private device CA (data/certs/ca.crt) and
// checks that server_host is in the certificate. If devices connect by LAN IP,
// add it when generating certificates:  python -m omnilink.certificates --host 192.168.1.50
// ALLOW_UNVERIFIED_TLS=true keeps encryption but skips identity checks; use it
// only on a private test network you control.
const bool ALLOW_UNVERIFIED_TLS = false;
// OTA stays off until this has at least 8 characters. Anyone on your network
// who knows it can replace the firmware.
const char *OTA_PASSWORD = "";

// ===================== [CHANGE] 3. Optional fixed Wi-Fi =====================
const char *SSID = "";      // leave empty to use the OmniLink-Setup hotspot
const char *PASSWORD = "";

// Saved in /config.json; pre-filled by the web client download.
char server_host[64]   = "iot.example.com";
char server_port[8]    = "8883";
char device_id[40]     = "";
char device_secret[70] = "";

static const char ROOT_CA[] PROGMEM = R"CERT(-----BEGIN CERTIFICATE-----
PASTE_data/certs/ca.crt_CONTENT_HERE
-----END CERTIFICATE-----
)CERT";

BearSSL::WiFiClientSecure network;
BearSSL::X509List trustedCa(ROOT_CA);
PubSubClient mqtt(network);
OmniLink omniLink(mqtt);
ESP8266WebServer otaWebServer(80);
ESP8266HTTPUpdateServer otaUpdater;

bool power = false, shouldSaveConfig = false, omniLinkStarted = false, otaEnabled = false;
uint32_t outputSel = 0, intervalS = 10, lastSample = 0;

// ===================== [CHANGE] 4. Pin handlers =====================
void applyOutputs() {
  digitalWrite(OUTPUT_A, ((power && outputSel == 0) ^ OUTPUT_ACTIVE_LOW) ? HIGH : LOW);
  digitalWrite(OUTPUT_B, ((power && outputSel == 1) ^ OUTPUT_ACTIVE_LOW) ? HIGH : LOW);
}
bool setPower(bool on) { power = on; applyOutputs(); Serial.printf("[OmniLink] V%u Power -> %s\n", PIN_POWER, on ? "ON" : "OFF"); return true; }
bool setOutput(uint32_t v) { if (v > 1) return false; outputSel = v; applyOutputs(); return true; }
bool setInterval(uint32_t s) { if (s < 1 || s > 300) return false; intervalS = s; return true; }

void sampleMeasurement() {
  if (!MEASUREMENT_ENABLED) return;
  float percent = analogRead(A0) * 100.0f / 1023.0f;
  omniLink.reportFloat(PIN_MEASUREMENT, percent);
  omniLink.telemetryFloat("measurement", percent);
}
void reportState() {   // after every (re)connect
  Serial.println(F("[OmniLink] Connected; reporting state."));
  omniLink.reportBool(PIN_POWER, power);
  omniLink.reportUInt(PIN_OUTPUT, omnilink::T_UINT8, outputSel);
  omniLink.reportUInt(PIN_SETPOINT, omnilink::T_UINT32, intervalS);
  sampleMeasurement();
}

// ===================== Configuration storage =====================
void loadConfig() {
  if (!LittleFS.begin()) { LittleFS.format(); LittleFS.begin(); return; }
  File f = LittleFS.open("/config.json", "r");
  if (!f) return;
  JsonDocument doc;
  if (!deserializeJson(doc, f)) {
    strlcpy(server_host, doc["server_host"] | server_host, sizeof(server_host));
    strlcpy(server_port, doc["server_port"] | server_port, sizeof(server_port));
    if (!device_id[0]) strlcpy(device_id, doc["device_id"] | "", sizeof(device_id));
    if (!device_secret[0]) strlcpy(device_secret, doc["device_secret"] | "", sizeof(device_secret));
    Serial.println(F("[FS] Loaded saved configuration."));
  }
  f.close();
}
void saveConfig() {
  JsonDocument doc;
  doc["server_host"] = server_host; doc["server_port"] = server_port;
  doc["device_id"] = device_id; doc["device_secret"] = device_secret;
  File f = LittleFS.open("/config.json", "w");
  if (f) { serializeJson(doc, f); f.close(); Serial.println(F("[FS] Configuration saved.")); }
}
bool credentialsLookValid() { return strncmp(device_id, "dev_", 4) == 0 && strlen(device_secret) == 64; }

void connectWifi() {
  if (SSID[0]) {
    WiFi.mode(WIFI_STA); WiFi.begin(SSID, PASSWORD);
    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
    if (WiFi.status() == WL_CONNECTED && credentialsLookValid()) return;
  }
  WiFiManager wm;
  wm.setSaveConfigCallback([]() { shouldSaveConfig = true; });
  WiFiManagerParameter host("host", "OmniLink server host (DNS name or IP in the certificate)", server_host, sizeof(server_host));
  WiFiManagerParameter port("port", "MQTT TLS port", server_port, sizeof(server_port));
  WiFiManagerParameter id("dev_id", "Device ID (dev_...)", device_id, sizeof(device_id));
  WiFiManagerParameter secret("dev_sec", "Device secret (64 hex characters)", device_secret, sizeof(device_secret));
  wm.addParameter(&host); wm.addParameter(&port); wm.addParameter(&id); wm.addParameter(&secret);
  wm.setConfigPortalTimeout(300);
  if (!credentialsLookValid()) wm.startConfigPortal("OmniLink-Setup");
  else if (!wm.autoConnect("OmniLink-Setup")) { delay(1000); ESP.restart(); }
  strlcpy(server_host, host.getValue(), sizeof(server_host));
  strlcpy(server_port, port.getValue(), sizeof(server_port));
  strlcpy(device_id, id.getValue(), sizeof(device_id));
  strlcpy(device_secret, secret.getValue(), sizeof(device_secret));
  if (WiFi.status() != WL_CONNECTED) { Serial.println(F("[Wi-Fi] Not connected; restarting.")); delay(1000); ESP.restart(); }
}

void startOta() {
  if (strlen(OTA_PASSWORD) < 8) { Serial.println(F("[OTA] Disabled (set OTA_PASSWORD to enable).")); return; }
  ArduinoOTA.setHostname("omnilink-esp8266");
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.begin();
  otaUpdater.setup(&otaWebServer, "/update", "admin", OTA_PASSWORD);
  otaWebServer.begin();
  otaEnabled = true;
  Serial.print(F("[OTA] Ready: http://")); Serial.print(WiFi.localIP()); Serial.println(F("/update (user admin)"));
}

// Start OmniLink once the clock is valid (needed to verify certificate dates).
void startOmniLinkWhenReady() {
  if (omniLinkStarted) return;
  bool clockOk = time(nullptr) >= 1700000000;
  if (!ALLOW_UNVERIFIED_TLS && !clockOk) return;
  network.setBufferSizes(1024, 512);   // keeps BearSSL within ESP8266 RAM
  if (ALLOW_UNVERIFIED_TLS) network.setInsecure();
  else { network.setTrustAnchors(&trustedCa); network.setX509Time(time(nullptr)); }
  uint16_t port = atoi(server_port); if (!port) port = 8883;
  omniLink.begin(server_host, port, device_id, device_secret);
  omniLinkStarted = true;
  Serial.printf("[OmniLink] Connecting to %s:%u as %s\n", server_host, port, device_id);
}

void setup() {
  Serial.begin(115200); delay(200);
  pinMode(STATUS_LED, OUTPUT); digitalWrite(STATUS_LED, HIGH);
  pinMode(OUTPUT_A, OUTPUT); pinMode(OUTPUT_B, OUTPUT); applyOutputs();
  pinMode(RESET_PIN, INPUT_PULLUP);
  loadConfig();
  if (digitalRead(RESET_PIN) == LOW) {
    Serial.println(F("[RESET] FLASH held: wiping Wi-Fi and OmniLink settings."));
    WiFiManager wm; wm.resetSettings(); LittleFS.remove("/config.json");
    device_id[0] = device_secret[0] = 0;
  }
  connectWifi();
  if (credentialsLookValid() && (shouldSaveConfig || !LittleFS.exists("/config.json"))) saveConfig();
  if (!credentialsLookValid()) Serial.println(F("[OmniLink] Device ID/secret missing; hold FLASH on boot to reconfigure."));
  Serial.print(F("[Wi-Fi] IP ")); Serial.println(WiFi.localIP());
  startOta();
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  omniLink.onBool(PIN_POWER, setPower);
  omniLink.onUInt(PIN_OUTPUT, setOutput);
  omniLink.onUInt(PIN_SETPOINT, setInterval);
  omniLink.onConnect(reportState);
}

void loop() {
  if (otaEnabled) { ArduinoOTA.handle(); otaWebServer.handleClient(); }
  if (credentialsLookValid()) startOmniLinkWhenReady();
  omniLink.loop();
  static uint32_t lastBlink = 0, lastLog = 0;
  if (omniLink.connected()) {
    digitalWrite(STATUS_LED, LOW);   // steady on = online
    if (millis() - lastSample >= intervalS * 1000UL) { lastSample = millis(); sampleMeasurement(); }
  } else {
    if (millis() - lastBlink >= 500) { lastBlink = millis(); digitalWrite(STATUS_LED, !digitalRead(STATUS_LED)); }
    if (omniLinkStarted && millis() - lastLog >= 5000) {
      lastLog = millis();
      char ssl[64] = ""; network.getLastSSLError(ssl, sizeof(ssl));
      // 4 = wrong secret, 5 = unknown/unprovisioned device, -2 = network/TLS
      Serial.printf("[MQTT] Connecting... state %d %s\n", omniLink.state(), ssl);
    } else if (!omniLinkStarted && millis() - lastLog >= 5000) {
      lastLog = millis(); Serial.println(F("[NTP] Waiting for time before verified TLS..."));
    }
  }
  // Keep this loop non-blocking (no long delay()) so MQTT and OTA keep running.
}

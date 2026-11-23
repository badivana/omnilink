#include <FS.h>
#include <LittleFS.h>
#include <ESP8266WiFi.h>
#include <DNSServer.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPUpdateServer.h> // Web-based OTA (.bin upload)
#include <ArduinoOTA.h>               // Arduino IDE wireless upload
#include <WiFiManager.h>             // WiFiManager by tzapu (v2.0.16+)
#include <ArduinoJson.h>              // ArduinoJson v6 or v7
#include <WiFiClientSecureBearSSL.h>
#include <PubSubClient.h>
#include <OmniLink.h>
#include <time.h>
#include <sys/time.h>

// =====================================================================
// [USER CHANGEABLE] 1. HARDWARE PINS & CONFIGURATION
// ---------------------------------------------------------------------
// Customize the physical GPIO pins for your board.
// NodeMCU: D4 = GPIO2 (Built-in LED, Active LOW), D3 = GPIO0 (Flash button)
// =====================================================================
const uint8_t LED_PIN   = D4;  // Built-in LED (GPIO2, Active LOW: LOW = ON)
const uint8_t RESET_PIN = D3;  // FLASH Button (GPIO0, Active LOW) - Hold on boot to re-open AP

// =====================================================================
// [USER CHANGEABLE] 2. OPTIONAL DIRECT WI-FI CREDENTIALS
// ---------------------------------------------------------------------
// Leave SSID blank ("") to use the captive portal hotspot ("OmniLink-Setup").
// Or enter your Wi-Fi name & password here to connect directly:
// =====================================================================
const char *SSID     = "";
const char *PASSWORD = "";

// =====================================================================
// [USER CHANGEABLE] 3. TLS / SSL VERIFICATION SETTING
// ---------------------------------------------------------------------
// Set USE_INSECURE_TLS to true for local development / private IP (e.g. 10.30.203.36)
// where NTP UDP port 123 may be blocked or connecting via raw IP address.
// NOTE: Port 8883 communication is still 100% encrypted via TLS 1.2!
// Set to false only when using a public domain with valid NTP clock sync.
// =====================================================================
const bool USE_INSECURE_TLS = true;

// ======================================================
// CONFIGURABLE PARAMETERS (Saved in LittleFS /config.json)
// Pre-filled automatically when downloaded from dashboard,
// or configurable via Access Point ("OmniLink-Setup")
// ======================================================
char server_host[64]   = "10.30.203.36";
char server_port[8]    = "8883";
char device_id[40]     = ""; // Paste new Device ID here (or leave blank to configure via hotspot)
char device_secret[70] = ""; // Paste new Device Secret here (or leave blank to configure via hotspot)

bool shouldSaveConfig = false;

void saveConfigCallback() {
  Serial.println(F("[Portal] User saved new configuration."));
  shouldSaveConfig = true;
}

// ======================================================
// OTA WEB SERVER (Port 80)
// ======================================================
ESP8266WebServer otaWebServer(80);
ESP8266HTTPUpdateServer otaUpdater;

// ======================================================
// CLIENTS & ROOT CA
// ======================================================
// Trusted OmniLink Root CA (from data/certs/ca.crt)
static const char ROOT_CA[] PROGMEM = R"CERT(-----BEGIN CERTIFICATE-----
MIIEHTCCAoWgAwIBAgIUSDoUDhruX5Wb+h42Uvl+dShlAA0wDQYJKoZIhvcNAQEL
BQAwJTEjMCEGA1UEAwwaT21uaUxpbmsgcHJpdmF0ZSBkZXZpY2UgQ0EwHhcNMjYx
MDA1MTQzNjMyWhcNMzYxMDAyMTQ0MTMyWjAlMSMwIQYDVQQDDBpPbW5pTGluayBw
cml2YXRlIGRldmljZSBDQTCCAaIwDQYJKoZIhvcNAQEBBQADggGPADCCAYoCggGB
AJaumJaKl0uAt8YAETeq+KETYEClx2Zrz8oie95D+eZc16j5DVbJ54qgv0xTDwYs
RGDduk1GvQoeiDjbY9BFeoLrOLmfB55XtbsajaXbPDGP7H4w2gt3OEaZktw71vi0
U3BSd1aezb8GneIjDXPI/s0670Ity+jTP1zK/AfI47b4d7iRhY4FFF8nJ1J9PkX2
0IzHQSiaP2c766WosoPSwJfQU6civ5yKDpnYh/lnHF51fJb4Av3VOl+nCyRKuptB
GJaICLF5w9FJnK07BEKZUc82vY5CpHSmNJn5/tNaCb8m8j4z2IvoRqNlIx79iCN5
EhSh5BeCAdGT3x3KEyAGaD/NsExevkcjGhsMu4bRtHd2L5JbnwDYsgRA79rlwYSp
kfghmxKbbxNmHCmaP6AvMNwnYeS0LaDN7MEkEytdyl4nz+D/374DPtK1Wl0xNzF4
OqxIxX+BiFN18WYbXZf+fq4VzG3wVHgDRAAtnf50eCoEtEjmRW/TvhH09FWCu8g1
OQIDAQABo0UwQzASBgNVHRMBAf8ECDAGAQH/AgEAMA4GA1UdDwEB/wQEAwIBhjAd
BgNVHQ4EFgQUDKSRs0LD3/2LYQo0K0okcu0RFaswDQYJKoZIhvcNAQELBQADggGB
ADjdbJUavKISN+aydKPu7NZ87Sqr2uJhbATeUZQr/jpAt/nAT0x//pdnlDlDKezW
lM8zIb6nX77nFq7ijQh/nH74r/mdDfDTLlvwLZ5qVV+/oNprc+q3qyMIz2hhj+Lr
3smIgzURiWZGCa9k1DFW2V7eLy0w5YDC4Gtsc+qHkJJhAlmlI4t7IIRfeRuWLidB
fBZQRmQNRt5Rd61LJvq1XjgaT5Dqg2TFBTLjfX7EwgHd9MZ28oyx0D2TA8X38ceB
ISlGz3mqWlzNzK5nM/VKtj2aeP7bce9b8OI25cghuTCf+9+Z31t6wi+ZmD8Z53hp
8XKhrXawYZfJ3p+NjjyMUkJk4T+HkLrivAz/zKfgppZ4s3OvYEWyLQ/hoVM4xNqL
7eCYmwdOeodQe2IvHkV4Yms53aak8h5oTpmhTpTmC+IrY+tOgNW8ah/7aGMEIeTf
EfPaXGJVFIDyFqqhJjzaWnILqmu5pWv6q+fbh/Kv1KytVdqUHwh34rC7GJuacyHW
Nw==
-----END CERTIFICATE-----
)CERT";

BearSSL::WiFiClientSecure network;
static BearSSL::X509List trustedCert(ROOT_CA);
PubSubClient mqtt(network);
OmniLink omniLink(mqtt);

bool reported = false;
bool ledState = false;
unsigned long lastDiagTime = 0;

// ======================================================
// FAST BLINK TEST FUNCTION
// ======================================================
void blinkFast(int count = 6, int delayMs = 60)
{
  for (int i = 0; i < count; i++)
  {
    digitalWrite(LED_PIN, LOW);  // Active LOW = ON
    delay(delayMs);
    digitalWrite(LED_PIN, HIGH); // OFF
    delay(delayMs);
  }
  digitalWrite(LED_PIN, ledState ? LOW : HIGH);
}

// =====================================================================
// [USER CHANGEABLE] 4. VIRTUAL CHANNEL CALLBACK FUNCTIONS
// ---------------------------------------------------------------------
// These functions run whenever a control is toggled on your dashboard.
// Modify these or add new callback functions for other virtual channels.
// =====================================================================
bool setLED(bool on)
{
  ledState = on;
  digitalWrite(LED_PIN, on ? LOW : HIGH);
  Serial.print(F("[OmniLink] Dashboard Switch -> "));
  Serial.println(on ? F("ON") : F("OFF"));
  return true; // Return true to confirm the command was applied
}

// >>> ADD YOUR OWN CUSTOM ACTION FUNCTIONS HERE <<<
// Example: control an external relay module on pin D1:
// bool setRelay(bool on) {
//   digitalWrite(D1, on ? HIGH : LOW);
//   return true;
// }

// #####################################################################
// #####################################################################
// ##                                                                 ##
// ##   [USER CHANGEABLE] 5. YOUR MAIN CODE  ->  userLoop()           ##
// ##                                                                 ##
// ##   REPLACE THE BLINK EXAMPLE BELOW WITH YOUR OWN CODE.            ##
// ##   loop() calls this function over and over, after Wi-Fi, OTA    ##
// ##   and OmniLink have done their work. You do not need to edit    ##
// ##   loop() or setup() for normal projects.                        ##
// ##                                                                 ##
// ##   RULE: never use a long delay() here. It blocks Wi-Fi and MQTT  ##
// ##   and the device goes offline. Use millis() timers, as below.   ##
// ##                                                                 ##
// #####################################################################
// #####################################################################
void userLoop() {
  // ------------------- START OF EXAMPLE: BLINK (replace me) -------------------
  // Toggles the onboard LED once per second.
  // Note: this overrides the dashboard switch on V0. Delete this example if you
  // want the LED to follow the dashboard instead.
  static unsigned long lastUserBlink = 0;
  static bool userBlink = false;

  if (millis() - lastUserBlink >= 1000) {  // runs every 1000 ms
    lastUserBlink = millis();
    userBlink = !userBlink;
    digitalWrite(LED_PIN, userBlink ? LOW : HIGH);  // Active LOW: LOW = ON
  }
  // -------------------- END OF EXAMPLE: BLINK (replace me) --------------------

  // >>> YOUR OWN CODE / SENSORS GO HERE <<<
  // Example: send a sensor reading every 5 seconds
  // static unsigned long lastRead = 0;
  // if (millis() - lastRead >= 5000) {
  //   lastRead = millis();
  //   int analogVal = analogRead(A0);
  //   omniLink.telemetryInt("sensor_raw", analogVal);
  // }
}
// #####################################################################
// ##                     END OF YOUR MAIN CODE                       ##
// #####################################################################

// ======================================================
// LITTLEFS CONFIGURATION STORAGE
// ======================================================
void loadConfig() {
  if (!LittleFS.begin()) {
    LittleFS.format();
    LittleFS.begin();
    return;
  }
  if (LittleFS.exists("/config.json")) {
    File configFile = LittleFS.open("/config.json", "r");
    if (configFile) {
      StaticJsonDocument<512> doc;
      DeserializationError err = deserializeJson(doc, configFile);
      if (!err) {
        if (strlen(server_host) == 0) strlcpy(server_host, doc["server_host"] | "10.30.203.36", sizeof(server_host));
        strlcpy(server_port, doc["server_port"] | server_port, sizeof(server_port));
        // If device credentials were not set in the sketch code, load from flash
        if (strlen(device_id) == 0) {
          strlcpy(device_id, doc["device_id"] | "", sizeof(device_id));
        }
        if (strlen(device_secret) == 0) {
          strlcpy(device_secret, doc["device_secret"] | "", sizeof(device_secret));
        }
        Serial.println(F("[FS] Loaded saved configuration."));
      }
      configFile.close();
    }
  }
}

void saveConfig() {
  StaticJsonDocument<512> doc;
  doc["server_host"]   = server_host;
  doc["server_port"]   = server_port;
  doc["device_id"]     = device_id;
  doc["device_secret"] = device_secret;

  File configFile = LittleFS.open("/config.json", "w");
  if (configFile) {
    serializeJson(doc, configFile);
    configFile.close();
    Serial.println(F("[FS] Configuration saved to flash memory."));
  }
}

// ======================================================
// SETUP
// ======================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(LED_PIN, OUTPUT);
  pinMode(RESET_PIN, INPUT_PULLUP);

  blinkFast(6, 60);
  setLED(false);

  Serial.println();
  Serial.println(F("===================================="));
  Serial.println(F("   OmniLink ESP8266 Setup & OTA     "));
  Serial.println(F("===================================="));

  loadConfig();

  // Hold FLASH button (D3) during boot to erase and force AP hotspot
  if (digitalRead(RESET_PIN) == LOW) {
    Serial.println(F("\n[RESET] FLASH button (D3) held! Wiping settings..."));
    blinkFast(10, 40);
    WiFiManager wm;
    wm.resetSettings();
    LittleFS.remove("/config.json");
    device_id[0] = '\0';
    device_secret[0] = '\0';
    delay(1000);
    Serial.println(F("[RESET] Settings wiped. Starting Access Point."));
  }

  // ----------------------------------------------------
  // Connect to Wi-Fi: Direct or Captive Portal AP
  // ----------------------------------------------------
  bool connected = false;

  // 1. If user entered SSID manually in sketch, try direct connection first
  if (strlen(SSID) > 0) {
    Serial.print(F("[Wi-Fi] Connecting directly to SSID: "));
    Serial.println(SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(SSID, PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 25) {
      delay(500);
      Serial.print(F("."));
      attempts++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println(F("[Wi-Fi] Connected directly!"));
      connected = true;
    } else {
      Serial.println(F("[Wi-Fi] Direct connection failed! Falling back to Access Point..."));
    }
  }

  // 2. If SSID was left blank ("") or direct connection failed, open Access Point
  if (!connected) {
    WiFiManager wm;
    wm.setSaveConfigCallback(saveConfigCallback);

    // Custom UI Input fields in the configuration window
    WiFiManagerParameter custom_server_host("host", "OmniLink Server Host", server_host, sizeof(server_host));
    WiFiManagerParameter custom_server_port("port", "Port (8883)", server_port, sizeof(server_port));
    WiFiManagerParameter custom_device_id("dev_id", "Device ID (dev_...)", device_id, sizeof(device_id));
    WiFiManagerParameter custom_device_secret("dev_sec", "Device Secret (64 chars)", device_secret, sizeof(device_secret));

    wm.addParameter(&custom_server_host);
    wm.addParameter(&custom_server_port);
    wm.addParameter(&custom_device_id);
    wm.addParameter(&custom_device_secret);

    Serial.println(F("[AP Mode] Starting Access Point: 'OmniLink-Setup'"));
    Serial.println(F("[AP Mode] Connect phone/PC to 'OmniLink-Setup' to configure Wi-Fi and Device ID."));

    if (!wm.autoConnect("OmniLink-Setup")) {
      Serial.println(F("[AP Mode] Timeout. Rebooting..."));
      delay(2000);
      ESP.restart();
    }

    // Read the values typed in the portal
    strlcpy(server_host, custom_server_host.getValue(), sizeof(server_host));
    strlcpy(server_port, custom_server_port.getValue(), sizeof(server_port));
    strlcpy(device_id, custom_device_id.getValue(), sizeof(device_id));
    strlcpy(device_secret, custom_device_secret.getValue(), sizeof(device_secret));

    if (shouldSaveConfig) {
      saveConfig();
    }
  }

  // Ensure config is persisted if provided in sketch
  if (strlen(device_id) > 0 && strlen(device_secret) > 0) {
    saveConfig();
  }

  Serial.println(F("\n[OK] Configuration complete and Wi-Fi Connected!"));
  Serial.print(F("Device IP:   ")); Serial.println(WiFi.localIP());
  Serial.print(F("Device ID:   ")); Serial.println(device_id);

  // ----------------------------------------------------
  // Setup Wireless OTA Updates (.bin Upload)
  // ----------------------------------------------------
  ArduinoOTA.setHostname("omnilink-nodemcu");
  ArduinoOTA.setPassword("omnilink123");
  ArduinoOTA.begin();

  otaUpdater.setup(&otaWebServer, "/update", "admin", "omnilink123");
  otaWebServer.on("/", []() {
    otaWebServer.send(200, "text/html",
      "<body style='font-family:sans-serif;text-align:center;padding:50px;background:#0f172a;color:#fff;'>"
      "<h2>OmniLink Device</h2><p>Status: <span style='color:#4ade80;'>Online</span></p>"
      "<p><a href='/update' style='background:#0284c7;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;'>Upload Firmware (.bin)</a></p>"
      "</body>");
  });
  otaWebServer.begin();

  // ----------------------------------------------------
  // Sync Time & Connect to OmniLink Broker
  // ----------------------------------------------------
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  int ntpTimeout = 0;
  while (time(nullptr) < 1700000000 && ntpTimeout < 12) {
    delay(500);
    Serial.print(F("."));
    ntpTimeout++;
  }
  if (time(nullptr) >= 1700000000) {
    Serial.println(F("\n[OK] Time synchronized via NTP!"));
  } else {
    Serial.println(F("\n[WARN] NTP time sync timed out, using fallback timestamp..."));
    // Set fallback time so commands and TLS don't fail with year 1970
    timeval tv = { 1795000000, 0 };
    settimeofday(&tv, nullptr);
    Serial.println(F("[OK] Fallback timestamp set."));
  }

  // Restrict TLS buffer sizes to prevent ESP8266 RAM exhaustion (32KB default crashes the board)
  network.setBufferSizes(1024, 512);

  if (USE_INSECURE_TLS) {
    // Allows TLS 1.2 encrypted connection on port 8883 over local IP (10.30.203.36)
    // without failing on IP hostname mismatches or unblocked NTP clock sync.
    network.setInsecure();
  } else {
    // Enforce TLS X.509 certificate validation with trusted OmniLink Root CA
    network.setTrustAnchors(&trustedCert);
    network.setX509Time(time(nullptr));
  }

  // =====================================================================
  // [USER CHANGEABLE] 6. BIND VIRTUAL CHANNELS TO DASHBOARD
  // ---------------------------------------------------------------------
  // Map virtual channels (V0, V1, etc.) to your custom callback functions.
  // By default, channels V0 through V7 toggle the onboard LED.
  // =====================================================================
  for (uint16_t ch = 0; ch <= 7; ch++) {
    omniLink.onBool(ch, setLED);
  }

  // >>> BIND ADDITIONAL CHANNELS HERE <<<
  // Example: omniLink.onBool(1, setRelay);
  // Example: omniLink.onInt(2, setSpeed);
  // =====================================================================

  uint16_t port = atoi(server_port);
  if (port == 0) port = 8883;

  omniLink.begin(server_host, port, device_id, device_secret);
}

// ======================================================
// LOOP
// ======================================================
void loop() {
  ArduinoOTA.handle();
  otaWebServer.handleClient();
  omniLink.loop();

  if (omniLink.connected()) {
    if (!reported) {
      Serial.println(F("\n>>> [SUCCESS] Connected to OmniLink Broker! <<<"));
      blinkFast(4, 50);

      // Report initial state on channels V0 through V7
      for (uint16_t ch = 0; ch <= 7; ch++) {
        omniLink.reportBool(ch, ledState);
      }
      reported = true;
      Serial.println(F("[OmniLink] Initial state synchronized with dashboard."));
    }
  } else {
    reported = false;

    if (millis() - lastDiagTime > 3000) {
      lastDiagTime = millis();
      int s = mqtt.state();
      Serial.print(F("[MQTT] Connecting... State: "));
      Serial.print(s);
      switch (s) {
        case -4: Serial.print(F(" (Timeout)")); break;
        case -3: Serial.print(F(" (Connection Lost)")); break;
        case -2: Serial.print(F(" (Connect Failed - Check IP/Port/TLS)")); break;
        case -1: Serial.print(F(" (Disconnected)")); break;
        case 1:  Serial.print(F(" (Bad Protocol)")); break;
        case 2:  Serial.print(F(" (Bad Client ID)")); break;
        case 3:  Serial.print(F(" (Unavailable)")); break;
        case 4:  Serial.print(F(" (Bad Credentials - Secret Mismatch)")); break;
        case 5:  Serial.print(F(" (Unauthorized - Device ID Not Registered)")); break;
      }
      char errBuf[64];
      network.getLastSSLError(errBuf, sizeof(errBuf));
      if (strlen(errBuf) > 0) {
        Serial.print(F(" | BearSSL: "));
        Serial.print(errBuf);
      }
      Serial.println();
    }
  }

  userLoop();  // YOUR MAIN CODE: edit userLoop() in section 5 above
}

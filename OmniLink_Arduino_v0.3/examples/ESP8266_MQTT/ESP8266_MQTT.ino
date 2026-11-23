/* OmniLink Arduino 0.3 - ESP8266 / NodeMCU over MQTT TLS (Mosquitto, port 8883), for OmniLink Server v0.6.

   Matches the demo device made by the server:  python -m examples.create_demo
   (in a fresh account it allocates the pins below; otherwise copy the numbers
   shown under Devices & pins):
     V0 Power            BOOL    writable   switches the selected output
     V1 Output selection UINT8   writable   0 = output A, 1 = output B
     V2 Setpoint         UINT32  writable   measurement interval, 1..300 s
     V3 Measurement      FLOAT32 read-only  A0 input, 0..100 %
   MQTT login is created by the server: username = device ID, password = secret.
   Allow a few seconds after creating the device for broker provisioning.
   For Wi-Fi/credential setup from a phone and OTA updates see ESP8266_Provisioning. */
#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>
#include <PubSubClient.h>
#include <OmniLink.h>
#include <time.h>

// Set to 0 only for a private test broker (setup -EnablePlain / --plain). Plain MQTT exposes the secret.
#define OMNILINK_MQTT_TLS 1
const char *SSID = "YOUR_WIFI", *PASSWORD = "YOUR_WIFI_PASSWORD";
const char *HOST = "iot.example.com";   // the DNS name/IP passed to setup (--domain/--host); never localhost
const char *DEVICE_ID = "dev_COPY_FROM_OMNILINK";
const char *DEVICE_SECRET = "COPY_THE_64_CHARACTER_SECRET_ONCE";
#if OMNILINK_MQTT_TLS
static const char ROOT_CA[] PROGMEM = R"CERT(-----BEGIN CERTIFICATE-----
PASTE_data/certs/ca.crt_CONTENT_HERE
-----END CERTIFICATE-----
)CERT";
BearSSL::WiFiClientSecure network;
const uint16_t MQTT_PORT = 8883;
#else
WiFiClient network;
const uint16_t MQTT_PORT = 1883;
#endif
PubSubClient mqtt(network);
OmniLink omniLink(mqtt);

// ---- Virtual pins (server) -> this board's hardware ----
const uint16_t PIN_POWER = 0, PIN_OUTPUT = 1, PIN_SETPOINT = 2, PIN_MEASUREMENT = 3;
const uint8_t OUTPUT_A = D1, OUTPUT_B = D2;   // relay/LED GPIOs (GPIO5, GPIO4)
const bool OUTPUT_ACTIVE_LOW = true;          // most relay modules
const bool MEASUREMENT_ENABLED = true;        // false if nothing is wired to A0

bool power = false; uint32_t outputSel = 0, intervalS = 10; uint32_t lastSample = 0;

void applyOutputs() {
  digitalWrite(OUTPUT_A, ((power && outputSel == 0) ^ OUTPUT_ACTIVE_LOW) ? HIGH : LOW);
  digitalWrite(OUTPUT_B, ((power && outputSel == 1) ^ OUTPUT_ACTIVE_LOW) ? HIGH : LOW);
}
bool setPower(bool on) { power = on; applyOutputs(); return true; }
bool setOutput(uint32_t v) { if (v > 1) return false; outputSel = v; applyOutputs(); return true; }
bool setInterval(uint32_t s) { if (s < 1 || s > 300) return false; intervalS = s; return true; }

void sampleMeasurement() {
  if (!MEASUREMENT_ENABLED) return;
  float percent = analogRead(A0) * 100.0f / 1023.0f;
  omniLink.reportFloat(PIN_MEASUREMENT, percent);   // latest value for value/gauge widgets
  omniLink.telemetryFloat("measurement", percent);  // history for chart widgets
}
// Runs after every (re)connect so the dashboard shows the board's real state.
void reportState() {
  omniLink.reportBool(PIN_POWER, power);
  omniLink.reportUInt(PIN_OUTPUT, omnilink::T_UINT8, outputSel);
  omniLink.reportUInt(PIN_SETPOINT, omnilink::T_UINT32, intervalS);
  sampleMeasurement();
}

void setup() {
  Serial.begin(115200);
  pinMode(OUTPUT_A, OUTPUT); pinMode(OUTPUT_B, OUTPUT); applyOutputs();
  WiFi.mode(WIFI_STA); WiFi.begin(SSID, PASSWORD);
  while (WiFi.status() != WL_CONNECTED) delay(250);
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // TLS certificate dates need a clock
  while (time(nullptr) < 1700000000) delay(100);
#if OMNILINK_MQTT_TLS
  static BearSSL::X509List ca(ROOT_CA);
  network.setTrustAnchors(&ca);       // verifies the private device CA and the hostname
  network.setBufferSizes(1024, 512);  // keeps BearSSL within ESP8266 RAM
#endif
  omniLink.onBool(PIN_POWER, setPower);
  omniLink.onUInt(PIN_OUTPUT, setOutput);
  omniLink.onUInt(PIN_SETPOINT, setInterval);
  omniLink.onConnect(reportState);
  omniLink.begin(HOST, MQTT_PORT, DEVICE_ID, DEVICE_SECRET);
}

void loop() {
  omniLink.loop();
  static uint32_t lastLog = 0;
  if (!omniLink.connected() && millis() - lastLog > 5000) {
    lastLog = millis();
    // 4 = wrong secret, 5 = unknown device or broker not provisioned yet, -2 = TLS/network
    Serial.printf("OmniLink MQTT: connecting (state %d)\n", omniLink.state());
  }
  if (omniLink.connected() && millis() - lastSample >= intervalS * 1000UL) { lastSample = millis(); sampleMeasurement(); }
}

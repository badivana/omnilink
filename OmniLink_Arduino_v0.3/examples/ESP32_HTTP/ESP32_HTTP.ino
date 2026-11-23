/* OmniLink Arduino 0.3 - ESP32 over HTTP(S), for OmniLink Server v0.6.

   Matches the demo device made by the server:  python -m examples.create_demo
   (in a fresh account it allocates the pins below; otherwise copy the numbers
   shown under Devices & pins):
     V0 Power            BOOL    writable   switches the selected output
     V1 Output selection UINT8   writable   0 = output A, 1 = output B
     V2 Setpoint         UINT32  writable   measurement interval, 1..300 s
     V3 Measurement      FLOAT32 read-only  analog input, 0..100 %
   Paste the "id" and "secret" from device-credentials.json below. */
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <OmniLinkHttp.h>
#include <time.h>

// Native Run/Install: https://host:8000 + data/certs/ca.crt. Docker/Caddy: https://host + Caddy's public CA.
// Set to 0 only on a trusted private network: plain HTTP exposes the device secret.
#define OMNILINK_HTTP_TLS 1
const char *SSID = "YOUR_WIFI", *PASSWORD = "YOUR_WIFI_PASSWORD";
#if OMNILINK_HTTP_TLS
const char *BASE_URL = "https://iot.example.com:8000";
#else
const char *BASE_URL = "http://192.168.1.50:8000";
#endif
const char *DEVICE_ID = "dev_COPY_FROM_OMNILINK";
const char *DEVICE_SECRET = "COPY_THE_64_CHARACTER_SECRET_ONCE";

#if OMNILINK_HTTP_TLS
const char ROOT_CA[] PROGMEM = R"CERT(-----BEGIN CERTIFICATE-----
PASTE_THE_CA_CERTIFICATE_TRUSTED_BY_YOUR_HTTPS_HOST_HERE
-----END CERTIFICATE-----
)CERT";
WiFiClientSecure network;
#else
WiFiClient network;
#endif
OmniLinkHttp<decltype(network)> omniLink(network);

// ---- Virtual pins (server) -> this board's hardware ----
const uint16_t PIN_POWER = 0, PIN_OUTPUT = 1, PIN_SETPOINT = 2, PIN_MEASUREMENT = 3;
const uint8_t OUTPUT_A = 17, OUTPUT_B = 16;   // relay/LED GPIOs
const bool OUTPUT_ACTIVE_LOW = true;          // most relay modules
const uint8_t SENSOR_PIN = 34;                // ADC1 input; wire a sensor or potentiometer
const bool MEASUREMENT_ENABLED = true;        // false if nothing is wired to SENSOR_PIN

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
  float percent = analogRead(SENSOR_PIN) * 100.0f / 4095.0f;
  omniLink.reportFloat(PIN_MEASUREMENT, percent);   // latest value for value/gauge widgets
  omniLink.telemetryFloat("measurement", percent);  // history for chart widgets
}
// Runs after every (re)connect so the dashboard shows the board's real state.
void reportState() {
  omniLink.reportBool(PIN_POWER, power);
  omniLink.reportUInt(PIN_OUTPUT, omnilink::T_UINT8, outputSel);
  omniLink.reportUInt(PIN_SETPOINT, omnilink::T_UINT32, intervalS);
  sampleMeasurement();
  if (omniLink.unconfiguredBindings())
    Serial.println("Warning: a bound pin is missing on the server or has another type/writable setting.");
}

void setup() {
  Serial.begin(115200);
  pinMode(OUTPUT_A, OUTPUT); pinMode(OUTPUT_B, OUTPUT); applyOutputs();
  WiFi.begin(SSID, PASSWORD);
  while (WiFi.status() != WL_CONNECTED) delay(250);
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // TLS certificate dates need a clock
  while (time(nullptr) < 1700000000) delay(100);
#if OMNILINK_HTTP_TLS
  network.setCACert(ROOT_CA);   // verifies the CA and the server hostname
#endif
  omniLink.onBool(PIN_POWER, setPower);
  omniLink.onUInt(PIN_OUTPUT, setOutput);
  omniLink.onUInt(PIN_SETPOINT, setInterval);
  omniLink.onConnect(reportState);
  omniLink.begin(BASE_URL, DEVICE_ID, DEVICE_SECRET);
}

void loop() {
  omniLink.loop();
  static bool wasConnected = false; static uint32_t lastLog = 0;
  if (!omniLink.connected() && millis() - lastLog > 5000) {
    lastLog = millis(); Serial.printf("OmniLink: not connected (HTTP %d)\n", omniLink.lastStatus());
  }
  if (omniLink.connected() != wasConnected) { wasConnected = omniLink.connected(); Serial.println(wasConnected ? "OmniLink: online" : "OmniLink: offline"); }
  if (omniLink.connected() && millis() - lastSample >= intervalS * 1000UL) { lastSample = millis(); sampleMeasurement(); }
  delay(2);
}

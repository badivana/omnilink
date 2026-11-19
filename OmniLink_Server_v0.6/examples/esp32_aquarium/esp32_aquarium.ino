/* OmniLink aquarium MQTT device. Arduino ESP32 + PubSubClient + ArduinoJson 7.
 * Relay 1 selects FILTER (0) or AIR (1); relay 2 is the master power gate.
 * Adapt GPIOs and relay polarity to your board. Never bypass certificate checks.
 */
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <time.h>
#include <esp_system.h>

const char *WIFI_SSID = "YOUR_WIFI";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char *MQTT_HOST = "your-server.example.com";
const char *DEVICE_ID = "dev_REPLACE_FROM_DASHBOARD";
const char *DEVICE_SECRET = "REPLACE_WITH_64_HEX_CHARACTERS";
const char ROOT_CA[] PROGMEM = R"CERT(
-----BEGIN CERTIFICATE-----
PASTE_THE_CONTENTS_OF_data/certs/ca.crt_HERE
-----END CERTIFICATE-----
)CERT";
const int SELECT_PIN = 16;
const int MASTER_PIN = 17;
const bool RELAY_ACTIVE_LOW = true;

WiFiClientSecure tls;
PubSubClient mqtt(tls);
Preferences prefs;
String root, bootID;
bool master = false;
uint8_t selected = 0, mode = 1, actual = 0;
uint32_t filterSeconds = 60, airSeconds = 30;
uint32_t reportSeq = 0, telemetrySeq = 0, eventSeq = 0;
uint32_t phaseStarted = 0, lastStatus = 0, lastReconnect = 0;
uint32_t revisions[5] = {0};
String lastKeys[5];

void relay(int pin, bool energized) {
  digitalWrite(pin, RELAY_ACTIVE_LOW ? !energized : energized);
}
void actuate() {
  // Gate power off while changing the selector, then restore the requested gate.
  relay(MASTER_PIN, false);
  actual = 0;
  relay(SELECT_PIN, selected == 1);
  delay(250);
  relay(MASTER_PIN, master);
  actual = master ? (selected == 1 ? 2 : 1) : 0;
}
void publish(const char *suffix, JsonDocument &doc) {
  char payload[1024];
  size_t n = serializeJson(doc, payload, sizeof(payload));
  if (n < sizeof(payload)) mqtt.publish((root + suffix).c_str(), payload, false);
}
uint64_t epochMs() { return uint64_t(time(nullptr)) * 1000ULL; }
void report(uint16_t channel, const String &key = "00000000000000000000000000000000", uint32_t revision = 0) {
  JsonDocument d;
  d["boot_id"] = bootID; d["sequence"] = ++reportSeq;
  d["channel"] = channel; d["observed_at_ms"] = String(epochMs());
  d["applied_command_key"] = key; d["desired_revision"] = revision;
  if (channel == 0) { d["type"] = 1; d["value"] = master; }
  else if (channel == 1) { d["type"] = 3; d["value"] = selected; }
  else if (channel == 2) { d["type"] = 3; d["value"] = mode; }
  else if (channel == 3) { d["type"] = 7; d["value"] = filterSeconds; }
  else if (channel == 4) { d["type"] = 7; d["value"] = airSeconds; }
  else if (channel == 5) { d["type"] = 3; d["value"] = actual; }
  else return;
  publish("state", d);
}
void ack(const String &key, uint32_t revision, const char *status, uint16_t error = 0) {
  JsonDocument d;
  d["command_key"] = key; d["desired_revision"] = revision;
  d["status"] = status; d["error_code"] = error;
  publish("ack", d);
}
void status() {
  JsonDocument d;
  d["online"] = true; d["boot_id"] = bootID; d["firmware"] = "aquarium-0.2";
  publish("status", d);
}
void callback(char *topic, byte *payload, unsigned int length) {
  if (String(topic) != root + "cmd" || length > 1024) return;
  JsonDocument d;
  if (deserializeJson(d, payload, length)) return;
  String key = d["command_key"].as<String>();
  uint32_t revision = d["desired_revision"] | 0U;
  int channel = d["channel"] | -1;
  if (key.length() != 32 || !revision || channel < 0 || channel > 4) return;
  if (key == lastKeys[channel] && revision == revisions[channel]) {
    ack(key, revision, "applied"); report(channel); report(5); return;
  }
  const char *expiryText = d["expires_at_ms"] | "0";
  uint64_t expiry = strtoull(expiryText, nullptr, 10);
  if (!expiry || epochMs() >= expiry) { ack(key, revision, "rejected", 408); return; }
  if (revision <= revisions[channel]) { ack(key, revision, "rejected", 409); return; }
  int expectedType = channel == 0 ? 1 : channel < 3 ? 3 : 7;
  if ((d["type"] | 0) != expectedType) { ack(key, revision, "rejected", 400); return; }
  if (channel == 0 && !d["value"].is<bool>()) { ack(key, revision, "rejected", 400); return; }
  uint32_t v = d["value"].as<uint32_t>();
  if (channel > 0 && (!d["value"].is<uint32_t>() || (channel < 3 && v > 1) || (channel >= 3 && (v < 1 || v > 86400)))) {
    ack(key, revision, "rejected", 400); return;
  }
  if (channel == 0) master = d["value"].as<bool>();
  if (channel == 1) selected = uint8_t(v);
  if (channel == 2) mode = uint8_t(v);
  if (channel == 3) filterSeconds = v;
  if (channel == 4) airSeconds = v;
  phaseStarted = millis();
  actuate();
  // Persist the applied revision and value before confirming the operation.
  prefs.putBool("master", master); prefs.putUChar("select", selected); prefs.putUChar("mode", mode);
  prefs.putUInt("filter", filterSeconds); prefs.putUInt("air", airSeconds);
  revisions[channel] = revision; lastKeys[channel] = key;
  prefs.putUInt(("r" + String(channel)).c_str(), revision);
  prefs.putString(("k" + String(channel)).c_str(), key);
  ack(key, revision, "applied"); report(channel, key, revision); report(5);
}
void setup() {
  Serial.begin(115200);
  // Set inactive output levels before enabling GPIO output drivers.
  digitalWrite(MASTER_PIN, RELAY_ACTIVE_LOW ? HIGH : LOW); pinMode(MASTER_PIN, OUTPUT);
  digitalWrite(SELECT_PIN, RELAY_ACTIVE_LOW ? HIGH : LOW); pinMode(SELECT_PIN, OUTPUT);
  uint8_t bytes[16]; esp_fill_random(bytes, sizeof(bytes));
  char hex[33]; for (int i = 0; i < 16; i++) snprintf(hex + i*2, 3, "%02x", bytes[i]);
  bootID = hex; root = String("omnilink/v1/dev/") + DEVICE_ID + "/";
  prefs.begin("omnilink", false);
  master = prefs.getBool("master", false); selected = prefs.getUChar("select", 0); mode = prefs.getUChar("mode", 1);
  filterSeconds = prefs.getUInt("filter", 60); airSeconds = prefs.getUInt("air", 30);
  for (int i = 0; i < 5; i++) {
    revisions[i] = prefs.getUInt(("r" + String(i)).c_str(), 0);
    lastKeys[i] = prefs.getString(("k" + String(i)).c_str(), "");
  }
  actuate(); phaseStarted = millis();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  tls.setCACert(ROOT_CA); mqtt.setServer(MQTT_HOST, 8883); mqtt.setCallback(callback); mqtt.setBufferSize(2048);
}
void loop() {
  // Unsigned millis subtraction tolerates rollover. No RTC is needed for this interval cycle.
  if (master && mode == 0 && uint32_t(millis() - phaseStarted) >= (selected == 0 ? filterSeconds : airSeconds)*1000UL) {
    selected = 1 - selected; phaseStarted = millis(); actuate();
    if (mqtt.connected()) { report(1); report(5); }
  }
  if (WiFi.status() != WL_CONNECTED || time(nullptr) < 1700000000) { delay(10); return; }
  if (!mqtt.connected()) {
    if (uint32_t(millis() - lastReconnect) < 5000) return;
    lastReconnect = millis();
    String will = root + "status";
    if (mqtt.connect(DEVICE_ID, DEVICE_ID, DEVICE_SECRET, will.c_str(), 1, false, "{\"online\":false}")) {
      mqtt.subscribe((root + "cmd").c_str(), 1); status();
      for (int i = 0; i < 6; i++) report(i);
      JsonDocument e; e["boot_id"] = bootID; e["sequence"] = ++eventSeq; e["severity"] = 1;
      e["code"] = "CONNECTED"; e["detail"] = "Aquarium controller connected"; publish("event", e);
    }
  }
  mqtt.loop();
  if (mqtt.connected() && uint32_t(millis() - lastStatus) > 10000) {
    lastStatus = millis(); status(); report(5);
    JsonDocument t; t["boot_id"] = bootID; t["sequence"] = ++telemetrySeq;
    JsonObject m = t["metrics"].to<JsonArray>().add<JsonObject>();
    m["name"] = "uptime_seconds"; m["type"] = 7; m["value"] = millis()/1000UL;
    publish("telemetry", t);
  }
  delay(2);
}

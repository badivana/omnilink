#include "OmniLinkMqtt.h"
#include <time.h>
#include <stdlib.h>
#if defined(ESP8266)
#include <user_interface.h>
#elif defined(ESP32)
#include <esp_system.h>
#endif
#if defined(ESP32) || defined(ESP8266)

#ifndef OMNILINK_ARDUINO_VERSION
#define OMNILINK_ARDUINO_VERSION "0.3.0"
#endif

using namespace omnilink;
OmniLinkMqtt *OmniLinkMqtt::_active = nullptr;

// Wall clock in ms, or 0 when NTP has not synchronized yet.
static uint64_t clockMs() {
  time_t now = time(nullptr);
  return now >= 1700000000 ? uint64_t(now) * 1000ULL : 0;
}

OmniLinkMqtt::OmniLinkMqtt(PubSubClient &client) : _mqtt(client), _reportSequence(0),
  _telemetrySequence(0), _eventSequence(0), _lastStatus(0), _lastReconnect(0),
  _configured(false), _onConnect(nullptr) {
  _id[0] = _secret[0] = _firmware[0] = _boot[0] = _root[0] = 0;
}

void OmniLinkMqtt::begin(const char *host, uint16_t port, const char *deviceId,
                         const char *deviceSecret, const char *firmware) {
  snprintf(_id, sizeof(_id), "%s", deviceId);
  snprintf(_secret, sizeof(_secret), "%s", deviceSecret);
  snprintf(_firmware, sizeof(_firmware), "%s",
           firmware && *firmware ? firmware : "omnilink-arduino-mqtt/" OMNILINK_ARDUINO_VERSION);
  snprintf(_root, sizeof(_root), "omnilink/v1/dev/%s/", _id);
  uint8_t bytes[16];
#if defined(ESP8266)
  for (uint8_t i = 0; i < 16; i++) bytes[i] = uint8_t(os_random());
#else
  esp_fill_random(bytes, sizeof(bytes));
#endif
  for (uint8_t i = 0; i < 16; i++) snprintf(_boot + i * 2, 3, "%02x", bytes[i]);
  if (strcmp(_boot, NO_COMMAND) == 0) _boot[31] = '1';
  _mqtt.setServer(host, port);
  _mqtt.setCallback(receive);
  _mqtt.setBufferSize(1024);
  _active = this;
  _configured = true;
  _lastReconnect = 0;
}

void OmniLinkMqtt::receive(char *topic, byte *payload, unsigned int length) {
  if (_active) _active->handle(topic, payload, length);
}

void OmniLinkMqtt::handle(char *topic, byte *payload, unsigned int length) {
  if (String(topic) != String(_root) + "cmd" || length > 768) return;
  JsonDocument d;
  if (deserializeJson(d, payload, length)) return;
  const char *key = d["command_key"] | "";
  uint32_t rev = d["desired_revision"] | 0U;
  int channel = d["channel"] | -1;
  int type = d["type"] | 0;
  if (!validCommand(key, rev, channel)) return;
  // The server expires commands itself; the device adds a second check only
  // when its clock is synchronized, so boards without NTP still work.
  uint64_t expiry = strtoull(d["expires_at_ms"] | "0", nullptr, 10), now = clockMs();
  if (now && expiry && now >= expiry) { ack(key, rev, "rejected", 408); return; }
  JsonVariantConst v = d["value"];
  Outcome o = _bindings.apply(channel, type, key, rev, v);
  if (o == APPLIED || o == DUPLICATE) {
    if (ack(key, rev, "applied", 0)) report(channel, uint8_t(type), v, key, rev);
  } else ack(key, rev, "rejected", errorCode(o));
}

bool OmniLinkMqtt::publish(const char *leaf, JsonDocument &doc, size_t limit) {
  if (!_mqtt.connected()) return false;
  char payload[512];
  if (limit > sizeof(payload)) limit = sizeof(payload);
  size_t n = serializeJson(doc, payload, limit);
  return n > 0 && n < limit && _mqtt.publish((String(_root) + leaf).c_str(), payload, false);
}

bool OmniLinkMqtt::ack(const char *key, uint32_t revision, const char *result, uint16_t error) {
  JsonDocument d;
  d["command_key"] = key; d["desired_revision"] = revision; d["status"] = result; d["error_code"] = error;
  return publish("ack", d, 192);
}

bool OmniLinkMqtt::report(uint16_t channel, uint8_t type, JsonVariantConst value, const char *key, uint32_t revision) {
  JsonDocument d;
  d["boot_id"] = _boot; d["sequence"] = ++_reportSequence; d["channel"] = channel; d["type"] = type;
  d["value"] = value; d["observed_at_ms"] = String(clockMs()); d["applied_command_key"] = key;
  d["desired_revision"] = revision;
  return publish("state", d, 512);
}

bool OmniLinkMqtt::reportBool(uint16_t c, bool v) { JsonDocument d; d.set(v); return report(c, T_BOOL, d.as<JsonVariantConst>(), NO_COMMAND, 0); }
bool OmniLinkMqtt::reportInt(uint16_t c, int32_t v) { return reportInt(c, T_INT32, v); }
bool OmniLinkMqtt::reportInt(uint16_t c, uint8_t t, int32_t v) { if (!intType(t) || !intFits(t, v)) return false; JsonDocument d; d.set(v); return report(c, t, d.as<JsonVariantConst>(), NO_COMMAND, 0); }
bool OmniLinkMqtt::reportUInt(uint16_t c, uint8_t t, uint32_t v) { if (!uintType(t) || !uintFits(t, v)) return false; JsonDocument d; d.set(v); return report(c, t, d.as<JsonVariantConst>(), NO_COMMAND, 0); }
bool OmniLinkMqtt::reportFloat(uint16_t c, float v) { if (isnan(v) || isinf(v)) return false; JsonDocument d; d.set(v); return report(c, T_FLOAT32, d.as<JsonVariantConst>(), NO_COMMAND, 0); }
bool OmniLinkMqtt::reportString(uint16_t c, const char *v) { JsonDocument d; d.set(v); return report(c, T_STRING, d.as<JsonVariantConst>(), NO_COMMAND, 0); }

bool OmniLinkMqtt::metric(const char *name, uint8_t type, JsonVariantConst value) {
  JsonDocument d;
  d["boot_id"] = _boot; d["sequence"] = ++_telemetrySequence; d["observed_at_ms"] = String(clockMs()); d["quality"] = 0;
  JsonObject m = d["metrics"].to<JsonArray>().add<JsonObject>();
  m["name"] = name; m["type"] = type; m["value"] = value;
  return publish("telemetry", d, 384);
}
bool OmniLinkMqtt::telemetryFloat(const char *name, float v) { if (isnan(v) || isinf(v)) return false; JsonDocument d; d.set(v); return metric(name, T_FLOAT32, d.as<JsonVariantConst>()); }
bool OmniLinkMqtt::telemetryInt(const char *name, int32_t v) { JsonDocument d; d.set(v); return metric(name, T_INT32, d.as<JsonVariantConst>()); }
bool OmniLinkMqtt::telemetryUInt(const char *name, uint32_t v) { JsonDocument d; d.set(v); return metric(name, T_UINT32, d.as<JsonVariantConst>()); }

bool OmniLinkMqtt::event(uint8_t severity, const char *code, const char *detail) {
  JsonDocument d;
  d["boot_id"] = _boot; d["sequence"] = ++_eventSequence; d["observed_at_ms"] = String(clockMs());
  d["severity"] = severity; d["code"] = code; d["detail"] = detail;
  return publish("event", d, 512);
}

// The server uses this to bind the boot ID and mark the device online (<90 s).
void OmniLinkMqtt::status() {
  JsonDocument d;
  d["online"] = true; d["boot_id"] = _boot; d["firmware"] = _firmware;
  publish("status", d, 192);
}

void OmniLinkMqtt::loop() {
  if (!_configured) return;
  uint32_t now = millis();
  if (!_mqtt.connected()) {
    if (_lastReconnect && now - _lastReconnect < 3000) return;
    _lastReconnect = now ? now : 1;
    if (_mqtt.connect(_id, _id, _secret, (String(_root) + "status").c_str(), 1, false, "{\"online\":false}")) {
      _mqtt.subscribe((String(_root) + "cmd").c_str(), 1);
      status();
      _lastStatus = now;
      if (_onConnect) _onConnect();
    }
    return;
  }
  _mqtt.loop();
  if (now - _lastStatus > 10000) { _lastStatus = now; status(); }
}

bool OmniLinkMqtt::connected() const { return _mqtt.connected(); }
int OmniLinkMqtt::state() const { return const_cast<PubSubClient &>(_mqtt).state(); }
#endif

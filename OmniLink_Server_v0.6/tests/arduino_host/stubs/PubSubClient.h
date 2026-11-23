#pragma once
#include <Arduino.h>
#include <WiFi.h>
/* MQTT client stub: the harness plays the Mosquitto broker. */
class PubSubClient {
  typedef void (*Callback)(char *, uint8_t *, unsigned int);
  Callback cb = nullptr; bool conn = false; int st = -1; uint32_t lastLoop = 0;
public:
  explicit PubSubClient(Client &) {}
  PubSubClient &setServer(const char *, uint16_t) { return *this; }
  PubSubClient &setCallback(Callback c) { cb = c; return *this; }
  bool setBufferSize(uint16_t) { return true; }
  bool connect(const char *id, const char *user, const char *pass, const char *willTopic, uint8_t, bool, const char *willMessage) {
    JsonDocument r; r["h"] = "mqtt_connect"; r["id"] = id; r["user"] = user; r["pass"] = pass; r["will_topic"] = willTopic; r["will"] = willMessage;
    JsonDocument a = hostExchange(r); conn = a["ok"] | false; st = conn ? 0 : (a["state"] | -2); return conn;
  }
  bool connected() { return conn; }
  int state() { return st; }
  bool publish(const char *topic, const char *payload, bool retained) {
    if (!conn) return false;
    JsonDocument r; r["h"] = "mqtt_pub"; r["topic"] = topic; r["payload"] = payload; r["retain"] = retained;
    return hostExchange(r)["ok"] | false;
  }
  bool subscribe(const char *topic, uint8_t qos) { JsonDocument r; r["h"] = "mqtt_sub"; r["topic"] = topic; r["qos"] = qos; return hostExchange(r)["ok"] | false; }
  bool loop() {
    if (!conn) return false;
    if (millis() - lastLoop < 30) return true;
    lastLoop = millis();
    JsonDocument r; r["h"] = "mqtt_loop"; JsonDocument a = hostExchange(r);
    if (a["disconnect"] | false) { conn = false; st = -3; return false; }
    for (JsonObject m : a["msgs"].as<JsonArray>()) {
      std::string topic = m["topic"] | "", payload = m["payload"] | "";
      if (cb) cb(&topic[0], (uint8_t *)&payload[0], unsigned(payload.size()));
    }
    return true;
  }
};

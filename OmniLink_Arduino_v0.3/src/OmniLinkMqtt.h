#pragma once
#include <Arduino.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "OmniLinkBindings.h"

/* MQTT transport for ESP32 / ESP8266 against OmniLink Server v0.6 + Mosquitto.
   Username and client ID = device ID, password = 64-hex device secret.
   Topic root omnilink/v1/dev/<id>/: publishes state, telemetry, event, ack,
   status; subscribes to cmd. Configure TLS on the Client passed to
   PubSubClient before calling begin(). */
class OmniLinkMqtt {
public:
  OMNILINK_HANDLER_API(_bindings)

  explicit OmniLinkMqtt(PubSubClient &client);
  void begin(const char *host, uint16_t port, const char *deviceId,
             const char *deviceSecret, const char *firmware = nullptr);
  // Called after every (re)connection: report the board's real state here.
  void onConnect(ConnectHandler handler) { _onConnect = handler; }
  void loop();
  bool connected() const;
  // PubSubClient state: 4 = wrong secret, 5 = device unknown/not yet provisioned.
  int state() const;
  bool reportBool(uint16_t channel, bool value);
  bool reportInt(uint16_t channel, int32_t value);
  bool reportInt(uint16_t channel, uint8_t type, int32_t value);
  bool reportUInt(uint16_t channel, uint8_t type, uint32_t value);
  bool reportFloat(uint16_t channel, float value);
  bool reportString(uint16_t channel, const char *value);
  bool telemetryFloat(const char *metric, float value);
  bool telemetryInt(const char *metric, int32_t value);
  bool telemetryUInt(const char *metric, uint32_t value);
  bool event(uint8_t severity, const char *code, const char *detail);

private:
  omnilink::Bindings<16> _bindings;
  PubSubClient &_mqtt;
  char _id[65], _secret[65], _firmware[33], _boot[33], _root[112];
  uint32_t _reportSequence, _telemetrySequence, _eventSequence, _lastStatus, _lastReconnect;
  bool _configured;
  ConnectHandler _onConnect;
  static OmniLinkMqtt *_active;
  static void receive(char *topic, byte *payload, unsigned int length);
  void handle(char *topic, byte *payload, unsigned int length);
  bool publish(const char *leaf, JsonDocument &doc, size_t limit);
  bool report(uint16_t channel, uint8_t type, JsonVariantConst value,
              const char *key, uint32_t revision);
  bool metric(const char *name, uint8_t type, JsonVariantConst value);
  bool ack(const char *key, uint32_t revision, const char *status, uint16_t error);
  void status();
};

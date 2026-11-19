#pragma once
#include <Arduino.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

/* MQTT transport for ESP32 / ESP8266. Configure TLS on the Client passed to
   PubSubClient before calling begin(). Channel definitions live in the server;
   this class routes typed commands to callbacks in your sketch. */
class OmniLinkMqtt {
public:
  typedef bool (*BoolHandler)(bool value);
  typedef bool (*IntHandler)(int32_t value);
  typedef bool (*UIntHandler)(uint32_t value);
  typedef bool (*FloatHandler)(float value);
  typedef bool (*StringHandler)(const char *value);

  explicit OmniLinkMqtt(PubSubClient &client);
  void begin(const char *host, uint16_t port, const char *deviceId,
             const char *deviceSecret, const char *firmware = nullptr);
  void onBool(uint16_t channel, BoolHandler handler);
  void onInt(uint16_t channel, IntHandler handler);
  void onUInt(uint16_t channel, UIntHandler handler);
  void onFloat(uint16_t channel, FloatHandler handler);
  void onString(uint16_t channel, StringHandler handler);
  void loop();
  bool connected() const;
  bool reportBool(uint16_t channel, bool value);
  bool reportInt(uint16_t channel, int32_t value);
  bool reportInt(uint16_t channel, uint8_t type, int32_t value);
  bool reportUInt(uint16_t channel, uint8_t type, uint32_t value);
  bool reportFloat(uint16_t channel, float value);
  bool reportString(uint16_t channel, const char *value);
  bool telemetryFloat(const char *metric, float value);
  bool telemetryUInt(const char *metric, uint32_t value);
  bool event(uint8_t severity, const char *code, const char *detail);

private:
  enum ValueKind : uint8_t { K_BOOL=1, K_INT=2, K_UINT=3, K_FLOAT=4, K_STRING=5 };
  union Handler { BoolHandler boolean; IntHandler integer; UIntHandler unsignedInteger; FloatHandler real; StringHandler string; };
  struct Binding { uint16_t channel; ValueKind kind; Handler handler; uint32_t revision; char key[33]; };
  static const uint8_t MAX_BINDINGS = 16;
  PubSubClient &_mqtt;
  Binding _bindings[MAX_BINDINGS];
  uint8_t _bindingCount;
  char _id[65], _secret[65], _firmware[33], _boot[33], _root[112];
  uint32_t _reportSequence, _telemetrySequence, _eventSequence, _lastStatus;
  uint32_t _lastReconnect;
  bool _configured;
  static OmniLinkMqtt *_active;
  static void receive(char *topic, byte *payload, unsigned int length);
  void handle(char *topic, byte *payload, unsigned int length);
  void bind(uint16_t channel, ValueKind kind, Handler handler);
  bool report(uint16_t channel, uint8_t type, JsonVariantConst value,
              const char *key, uint32_t revision);
  void ack(const char *key, uint32_t revision, const char *status, uint16_t error);
  void status();
};

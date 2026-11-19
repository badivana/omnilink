#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

/* Low-memory serial transport for AVR boards. The USB host runs
   examples/arduino_uno_serial_gateway.py, which owns network credentials and
   forwards commands/reports to the server using its HTTP device API. */
class OmniLinkSerial {
public:
  typedef bool (*BoolHandler)(bool value);
  typedef bool (*IntHandler)(int32_t value);
  typedef bool (*UIntHandler)(uint32_t value);
  typedef bool (*FloatHandler)(float value);
  typedef bool (*StringHandler)(const char *value);
  explicit OmniLinkSerial(Stream &port);
  void begin() {} // Serial port is supplied to the constructor; network work is done by the USB host gateway.
  void onBool(uint16_t channel,BoolHandler handler);
  void onInt(uint16_t channel,IntHandler handler);
  void onUInt(uint16_t channel,UIntHandler handler);
  void onFloat(uint16_t channel,FloatHandler handler);
  void onString(uint16_t channel,StringHandler handler);
  void loop();
  bool reportBool(uint16_t channel,bool value);
  bool reportInt(uint16_t channel,int32_t value);
  bool reportInt(uint16_t channel,uint8_t type,int32_t value);
  bool reportUInt(uint16_t channel,uint8_t type,uint32_t value);
  bool reportFloat(uint16_t channel,float value);
  bool reportString(uint16_t channel,const char *value);
  bool telemetryFloat(const char *metric,float value);
  bool telemetryUInt(const char *metric,uint32_t value);
  bool event(uint8_t severity,const char *code,const char *detail);
private:
  enum Kind:uint8_t { K_BOOL=1,K_INT=2,K_UINT=3,K_FLOAT=4,K_STRING=5 };
  union Handler {BoolHandler boolean;IntHandler integer;UIntHandler unsignedInteger;FloatHandler real;StringHandler string;};
  struct Binding {uint16_t channel;Kind kind;Handler fn;uint32_t revision;char key[33];};
  static const uint8_t MAX_BINDINGS=8;
  static const uint16_t LINE_SIZE=224;
  Stream &_port; Binding _bindings[MAX_BINDINGS]; uint8_t _count;
  char _line[LINE_SIZE]; uint16_t _length; bool _overflow;
  void bind(uint16_t channel,Kind kind,Handler fn);
  void handle(const char *line);
  bool sendReport(uint16_t channel,uint8_t type,JsonVariantConst value);
};

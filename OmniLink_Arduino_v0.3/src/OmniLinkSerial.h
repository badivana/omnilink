#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "OmniLinkBindings.h"

/* Low-memory USB-serial transport for AVR boards (Uno/Nano). The USB host runs
   the server's examples/arduino_uno_serial_gateway.py, which talks to the
   OmniLink Server v0.6 HTTP device API. The device ID and secret are stored in
   the sketch; the gateway asks for them with "identify" when it starts.

   Line protocol (one JSON object per line, at most 223 bytes):
     host -> board  {"op":"identify"}   {"op":"command",...}   {"op":"sync"}
     board -> host  {"op":"identity","id":...,"secret":...}
                    {"op":"ack",...} {"op":"report",...} {"op":"telemetry",...} {"op":"event",...} */
class OmniLinkSerial {
public:
  OMNILINK_HANDLER_API(_bindings)

  explicit OmniLinkSerial(Stream &port);
  // The Serial port is supplied to the constructor. Pass the device ID/secret
  // so the gateway can read them; both strings must stay valid (use globals).
  void begin(const char *deviceId=nullptr,const char *deviceSecret=nullptr){_id=deviceId;_secret=deviceSecret;}
  // Called when the gateway (re)connects to the server: report real state here.
  void onSync(ConnectHandler handler) { _onSync = handler; }
  void onConnect(ConnectHandler handler) { _onSync = handler; }
  void loop();
  bool reportBool(uint16_t channel,bool value);
  bool reportInt(uint16_t channel,int32_t value);
  bool reportInt(uint16_t channel,uint8_t type,int32_t value);
  bool reportUInt(uint16_t channel,uint8_t type,uint32_t value);
  bool reportFloat(uint16_t channel,float value);
  bool reportString(uint16_t channel,const char *value);
  bool telemetryFloat(const char *metric,float value);
  bool telemetryInt(const char *metric,int32_t value);
  bool telemetryUInt(const char *metric,uint32_t value);
  bool event(uint8_t severity,const char *code,const char *detail);
private:
  static const uint16_t LINE_SIZE=224;
  omnilink::Bindings<8> _bindings;
  Stream &_port; char _line[LINE_SIZE]; uint16_t _length; bool _overflow;
  ConnectHandler _onSync; const char *_id; const char *_secret;
  void handle(const char *line);
  bool send(JsonDocument &doc);
  bool sendReport(uint16_t channel,uint8_t type,JsonVariantConst value);
  bool sendMetric(const char *name,uint8_t type,JsonVariantConst value);
};

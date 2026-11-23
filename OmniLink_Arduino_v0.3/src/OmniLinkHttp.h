#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#if defined(ESP8266)
  #include <ESP8266HTTPClient.h>
  #include <user_interface.h>
#elif defined(ESP32)
  #include <HTTPClient.h>
  #include <esp_system.h>
#else
  #error "OmniLinkHttp supports ESP32 and ESP8266. Uno/Nano use OmniLinkSerial."
#endif
#include "OmniLinkBindings.h"

#ifndef OMNILINK_ARDUINO_VERSION
#define OMNILINK_ARDUINO_VERSION "0.3.0"
#endif

/* HTTP(S) transport for the OmniLink Server v0.6 device API:
     POST /device/{id}/connect    GET /device/{id}/commands
     POST /device/{id}/report     POST /device/{id}/ack
     POST /device/{id}/telemetry  POST /device/{id}/event
   Pass a WiFiClient for HTTP or a certificate-verified WiFiClientSecure for HTTPS. */
template<class NetworkClient>
class OmniLinkHttp {
public:
  OMNILINK_HANDLER_API(_bindings)

  explicit OmniLinkHttp(NetworkClient &network) : _network(network), _sequence(0), _lastPoll(0),
    _lastConnect(0), _retryDelay(0), _pollInterval(1000), _status(0), _unconfigured(0),
    _configured(false), _isConnected(false), _onConnect(nullptr) {
    _id[0]=_secret[0]=_firmware[0]=_boot[0]=_base[0]=0;
  }

  void begin(const char *baseUrl,const char *deviceId,const char *deviceSecret,const char *firmware=nullptr) {
    snprintf(_base,sizeof(_base),"%s",baseUrl); trimSlash(_base);
    snprintf(_id,sizeof(_id),"%s",deviceId); snprintf(_secret,sizeof(_secret),"%s",deviceSecret);
    snprintf(_firmware,sizeof(_firmware),"%s",firmware&&*firmware?firmware:"omnilink-arduino-http/" OMNILINK_ARDUINO_VERSION);
    makeBoot(); _sequence=0;_lastConnect=0;_retryDelay=0;_isConnected=false;_configured=true;
  }
  // Called after every (re)connection: report the board's real state here.
  void onConnect(ConnectHandler f){_onConnect=f;}
  void setPollInterval(uint32_t ms){_pollInterval=ms<500?500:ms;}
  bool connected() const { return _isConnected; }
  // Last HTTP status (negative = network/parse error). 401: wrong secret, 403: disabled, 404: unknown device.
  int lastStatus() const { return _status; }
  // Handlers whose pin is missing on the server or has a different type (checked at connect).
  uint8_t unconfiguredBindings() const { return _unconfigured; }

  void loop() {
    if(!_configured)return;
    uint32_t now=millis();
    if(!_isConnected){
      if(_lastConnect&&now-_lastConnect<_retryDelay)return;
      _lastConnect=now?now:1;
      if(!connectDevice()){_retryDelay=backoff(_status);return;}
      _isConnected=true;_lastPoll=0;
      if(_onConnect)_onConnect();
    }
    if(_lastPoll&&now-_lastPoll<_pollInterval)return;
    _lastPoll=now?now:1;
    JsonDocument commands;
    _status=request("GET",root()+"/commands",nullptr,&commands);
    if(_status<200||_status>=300){_isConnected=false;_retryDelay=backoff(_status);return;}
    if(!commands.is<JsonArray>())return;
    for(JsonObject cmd:commands.as<JsonArray>()){applyCommand(cmd);if(!_isConnected)return;}
  }

  bool reportBool(uint16_t c,bool v){JsonDocument x;x.set(v);return report(c,omnilink::T_BOOL,x.as<JsonVariantConst>(),omnilink::NO_COMMAND,0);}
  bool reportInt(uint16_t c,int32_t v){return reportInt(c,omnilink::T_INT32,v);}
  bool reportInt(uint16_t c,uint8_t t,int32_t v){if(!omnilink::intType(t)||!omnilink::intFits(t,v))return false;JsonDocument x;x.set(v);return report(c,t,x.as<JsonVariantConst>(),omnilink::NO_COMMAND,0);}
  bool reportUInt(uint16_t c,uint8_t t,uint32_t v){if(!omnilink::uintType(t)||!omnilink::uintFits(t,v))return false;JsonDocument x;x.set(v);return report(c,t,x.as<JsonVariantConst>(),omnilink::NO_COMMAND,0);}
  bool reportFloat(uint16_t c,float v){if(isnan(v)||isinf(v))return false;JsonDocument x;x.set(v);return report(c,omnilink::T_FLOAT32,x.as<JsonVariantConst>(),omnilink::NO_COMMAND,0);}
  bool reportString(uint16_t c,const char *v){JsonDocument x;x.set(v);return report(c,omnilink::T_STRING,x.as<JsonVariantConst>(),omnilink::NO_COMMAND,0);}
  bool telemetryFloat(const char *name,float v){if(isnan(v)||isinf(v))return false;JsonDocument d;JsonObject m=metric(d,name,omnilink::T_FLOAT32);m["value"]=v;return post("/telemetry",d);}
  bool telemetryInt(const char *name,int32_t v){JsonDocument d;JsonObject m=metric(d,name,omnilink::T_INT32);m["value"]=v;return post("/telemetry",d);}
  bool telemetryUInt(const char *name,uint32_t v){JsonDocument d;JsonObject m=metric(d,name,omnilink::T_UINT32);m["value"]=v;return post("/telemetry",d);}
  bool event(uint8_t severity,const char *code,const char *detail){
    if(!_isConnected)return false;
    JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_sequence;d["observed_at_ms"]=0;d["severity"]=severity;d["code"]=code;d["detail"]=detail;return post("/event",d);
  }

private:
  omnilink::Bindings<16> _bindings;
  NetworkClient &_network;
  uint32_t _sequence,_lastPoll,_lastConnect,_retryDelay,_pollInterval;int _status;uint8_t _unconfigured;
  bool _configured,_isConnected;ConnectHandler _onConnect;
  char _base[192],_id[65],_secret[65],_firmware[33],_boot[33];

  static void trimSlash(char *s){size_t n=strlen(s);while(n&&s[n-1]=='/')s[--n]=0;}
  // Credentials/account problems will not fix themselves quickly: retry slowly.
  static uint32_t backoff(int status){return (status==401||status==403||status==404)?30000:3000;}
  String root()const{return String("/device/")+_id;}
  void makeBoot(){
    for(uint8_t i=0;i<4;i++){
      #if defined(ESP8266)
        uint32_t r=os_random();
      #else
        uint32_t r=esp_random();
      #endif
      snprintf(_boot+i*8,9,"%08lx",(unsigned long)r);
    }
    if(strcmp(_boot,omnilink::NO_COMMAND)==0)_boot[31]='1';
  }
  JsonObject metric(JsonDocument &d,const char *name,uint8_t type){
    d["boot_id"]=_boot;d["sequence"]=++_sequence;d["observed_at_ms"]=0;d["quality"]=0;
    JsonObject m=d["metrics"].to<JsonArray>().add<JsonObject>();m["name"]=name;m["type"]=type;return m;
  }
  int request(const char *method,const String &path,JsonDocument *body,JsonDocument *response){
    HTTPClient http;String url=String(_base)+path;
    if(!http.begin(_network,url))return -1;
    http.addHeader("Authorization",String("Device ")+_secret);
    if(body)http.addHeader("Content-Type","application/json");
    int code;
    if(body){String payload;serializeJson(*body,payload);code=http.POST(payload);}
    else code=http.GET();
    if(code>=200&&code<300&&response){String payload=http.getString();if(deserializeJson(*response,payload))code=-2;}
    http.end();return code;
  }
  bool post(const String &path,JsonDocument &body){
    if(!_isConnected)return false;
    _status=request("POST",root()+path,&body,nullptr);
    if(_status==401||_status==403||_status==404||_status<0)_isConnected=false; // credentials, account or network changed
    return _status>=200&&_status<300;
  }
  bool connectDevice(){
    JsonDocument body;body["boot_id"]=_boot;body["firmware"]=_firmware;JsonDocument response;
    _status=request("POST",root()+"/connect",&body,&response);
    if(_status<200||_status>=300)return false;
    // Compare sketch handlers with the server's pin schema for diagnostics.
    _unconfigured=0;
    for(uint8_t i=0;i<_bindings.count();i++){
      const omnilink::Binding &b=_bindings.at(i);bool found=false;
      for(JsonObjectConst ch:response["channels"].as<JsonArrayConst>())
        if((ch["number"]|-1)==int(b.channel)){found=omnilink::compatible(b.kind,ch["type"]|0)&&(ch["writable"]|false);break;}
      if(!found)_unconfigured++;
    }
    return true;
  }
  bool report(uint16_t c,uint8_t type,JsonVariantConst value,const char *key,uint32_t revision){
    if(!_isConnected)return false;
    JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_sequence;d["channel"]=c;d["type"]=type;d["value"]=value;
    d["observed_at_ms"]=0;d["applied_command_key"]=key;d["desired_revision"]=revision;return post("/report",d);
  }
  bool acknowledge(const char *key,uint32_t revision,const char *status,uint16_t error){
    JsonDocument d;d["command_key"]=key;d["desired_revision"]=revision;d["status"]=status;d["error_code"]=error;return post("/ack",d);
  }
  void applyCommand(JsonObject cmd){
    const char *key=cmd["command_key"]|"";uint32_t revision=cmd["desired_revision"]|0U;int channel=cmd["channel"]|-1;int type=cmd["type"]|0;
    if(!omnilink::validCommand(key,revision,channel))return;
    JsonVariantConst v=cmd["value"];
    omnilink::Outcome o=_bindings.apply(channel,type,key,revision,v);
    if(o==omnilink::APPLIED||o==omnilink::DUPLICATE){
      // ACK first, then report the applied value so the dashboard shows confirmed state.
      if(acknowledge(key,revision,"applied",0))report(channel,uint8_t(type),v,key,revision);
    } else acknowledge(key,revision,"rejected",omnilink::errorCode(o));
  }
};

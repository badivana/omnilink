#include "OmniLinkMqtt.h"
#include <time.h>
#include <stdlib.h>
#if defined(ESP8266)
#include <user_interface.h>
#include <ESP8266WiFi.h>
#elif defined(ESP32)
#include <esp_system.h>
#include <WiFi.h>
#endif
#if defined(ESP32) || defined(ESP8266)

OmniLinkMqtt *OmniLinkMqtt::_active = nullptr;

OmniLinkMqtt::OmniLinkMqtt(PubSubClient &client) : _mqtt(client), _bindingCount(0),
  _reportSequence(0), _telemetrySequence(0), _eventSequence(0), _lastStatus(0),
  _lastReconnect(0), _configured(false) {
  memset(_id,0,sizeof(_id)); memset(_secret,0,sizeof(_secret));
  memset(_firmware,0,sizeof(_firmware)); memset(_boot,0,sizeof(_boot));
  memset(_root,0,sizeof(_root));
}

void OmniLinkMqtt::begin(const char *host,uint16_t port,const char *deviceId,
                         const char *deviceSecret,const char *firmware) {
  snprintf(_id,sizeof(_id),"%s",deviceId); snprintf(_secret,sizeof(_secret),"%s",deviceSecret);
#if defined(ESP8266) || defined(ESP32)
  IPAddress ip = WiFi.localIP();
  if (ip != IPAddress(0, 0, 0, 0)) {
    snprintf(_firmware, sizeof(_firmware), "ota@%s", ip.toString().c_str());
  } else if (firmware && strlen(firmware) > 0) {
    snprintf(_firmware, sizeof(_firmware), "%s", firmware);
  } else {
    snprintf(_firmware, sizeof(_firmware), "ota@pending");
  }
#else
  snprintf(_firmware, sizeof(_firmware), "%s", firmware ? firmware : "omnilink-dev");
#endif
  snprintf(_root,sizeof(_root),"omnilink/v1/dev/%s/",_id);
  uint8_t bytes[16];
  #if defined(ESP8266)
    for(uint8_t i=0;i<16;i++) bytes[i]=uint8_t(os_random());
  #else
    esp_fill_random(bytes,sizeof(bytes));
  #endif
  for(uint8_t i=0;i<16;i++) snprintf(_boot+i*2,3,"%02x",bytes[i]);
  _mqtt.setServer(host,port); _mqtt.setCallback(receive); _mqtt.setBufferSize(1024); _active=this; _configured=true;
}

void OmniLinkMqtt::bind(uint16_t channel,ValueKind kind,Handler handler) {
  for(uint8_t i=0;i<_bindingCount;i++) if(_bindings[i].channel==channel) {
    _bindings[i].kind=kind; _bindings[i].handler=handler; return;
  }
  if(_bindingCount<MAX_BINDINGS) { Binding &b=_bindings[_bindingCount++];b.channel=channel;b.kind=kind;b.handler=handler;b.revision=0;b.key[0]=0; }
}
void OmniLinkMqtt::onBool(uint16_t c,BoolHandler h){Handler f;f.boolean=h;bind(c,K_BOOL,f);}
void OmniLinkMqtt::onInt(uint16_t c,IntHandler h){Handler f;f.integer=h;bind(c,K_INT,f);}
void OmniLinkMqtt::onUInt(uint16_t c,UIntHandler h){Handler f;f.unsignedInteger=h;bind(c,K_UINT,f);}
void OmniLinkMqtt::onFloat(uint16_t c,FloatHandler h){Handler f;f.real=h;bind(c,K_FLOAT,f);}
void OmniLinkMqtt::onString(uint16_t c,StringHandler h){Handler f;f.string=h;bind(c,K_STRING,f);}
void OmniLinkMqtt::receive(char *topic,byte *payload,unsigned int length){if(_active)_active->handle(topic,payload,length);}

void OmniLinkMqtt::handle(char *topic,byte *payload,unsigned int length) {
  if(String(topic)!=String(_root)+"cmd" || length>768) return;
  JsonDocument d; if(deserializeJson(d,payload,length)) return;
  const char *key=d["command_key"]|""; uint32_t rev=d["desired_revision"]|0U;
  int channel=d["channel"]|-1; int type=d["type"]|0;
  if(strlen(key)!=32||rev==0||channel<0||channel>1023) return;
  const char *expiryText=d["expires_at_ms"]|"0"; uint64_t expiry=strtoull(expiryText,nullptr,10); uint64_t now=uint64_t(time(nullptr))*1000ULL;
  if(!expiry||now<1700000000000ULL||now>=expiry){ack(key,rev,"rejected",408);return;}
  Binding *b=nullptr; for(uint8_t i=0;i<_bindingCount;i++)if(_bindings[i].channel==channel){b=&_bindings[i];break;}
  if(!b){ack(key,rev,"rejected",404);return;}
  if(strcmp(b->key,key)==0&&b->revision==rev){ack(key,rev,"applied",0);report(channel,uint8_t(type),d["value"].as<JsonVariantConst>(),key,rev);return;}
  if(rev<=b->revision){ack(key,rev,"rejected",409);return;}
  JsonVariantConst v=d["value"];
  bool ok=false,typeValid=false;
  switch(b->kind){
    case K_BOOL: if(type==1&&v.is<bool>()){typeValid=true;ok=b->handler.boolean(v.as<bool>());} break;
    case K_INT: if((type==2||type==4||type==6)&&v.is<int32_t>()){typeValid=true;ok=b->handler.integer(v.as<int32_t>());} break;
    case K_UINT: if((type==3||type==5||type==7)&&v.is<uint32_t>()){typeValid=true;ok=b->handler.unsignedInteger(v.as<uint32_t>());} break;
    case K_FLOAT: if(type==10&&v.is<float>()){typeValid=true;ok=b->handler.real(v.as<float>());} break;
    case K_STRING: if(type==12&&v.is<const char*>()){typeValid=true;ok=b->handler.string(v.as<const char*>());} break;
  }
  if(!ok){ack(key,rev,"rejected",typeValid?500:400);return;}
  b->revision=rev;snprintf(b->key,sizeof(b->key),"%s",key);
  ack(key,rev,"applied",0);
  report(channel,uint8_t(type),v,key,rev);
}

void OmniLinkMqtt::ack(const char *key,uint32_t revision,const char *result,uint16_t error){
  JsonDocument d; d["command_key"]=key;d["desired_revision"]=revision;d["status"]=result;d["error_code"]=error;
  char payload[192];size_t n=serializeJson(d,payload,sizeof(payload));if(n<sizeof(payload))_mqtt.publish((String(_root)+"ack").c_str(),payload,false);
}
bool OmniLinkMqtt::report(uint16_t channel,uint8_t type,JsonVariantConst value,const char *key,uint32_t revision){
  if(!_mqtt.connected())return false;
  JsonDocument d; d["boot_id"]=_boot;d["sequence"]=++_reportSequence;d["channel"]=channel;d["type"]=type;d["value"]=value;
  d["observed_at_ms"]=String(uint64_t(time(nullptr))*1000ULL);d["applied_command_key"]=key;d["desired_revision"]=revision;
  char payload[512];size_t n=serializeJson(d,payload,sizeof(payload));return n<sizeof(payload)&&_mqtt.publish((String(_root)+"state").c_str(),payload,false);
}
bool OmniLinkMqtt::reportBool(uint16_t c,bool v){JsonDocument d;d.set(v);return report(c,1,d.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
bool OmniLinkMqtt::reportInt(uint16_t c,int32_t v){return reportInt(c,6,v);}
bool OmniLinkMqtt::reportInt(uint16_t c,uint8_t t,int32_t v){if(t!=2&&t!=4&&t!=6)return false;JsonDocument d;d.set(v);return report(c,t,d.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
bool OmniLinkMqtt::reportUInt(uint16_t c,uint8_t t,uint32_t v){if(t!=3&&t!=5&&t!=7)return false;JsonDocument d;d.set(v);return report(c,t,d.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
bool OmniLinkMqtt::reportFloat(uint16_t c,float v){JsonDocument d;d.set(v);return report(c,10,d.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
bool OmniLinkMqtt::reportString(uint16_t c,const char *v){JsonDocument d;d.set(v);return report(c,12,d.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
bool OmniLinkMqtt::telemetryFloat(const char *name,float value){if(!_mqtt.connected())return false;JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_telemetrySequence;d["observed_at_ms"]=String(uint64_t(time(nullptr))*1000ULL);d["quality"]=0;JsonObject m=d["metrics"].to<JsonArray>().add<JsonObject>();m["name"]=name;m["type"]=10;m["value"]=value;char p[384];size_t n=serializeJson(d,p,sizeof(p));return n<sizeof(p)&&_mqtt.publish((String(_root)+"telemetry").c_str(),p,false);}
bool OmniLinkMqtt::telemetryUInt(const char *name,uint32_t value){if(!_mqtt.connected())return false;JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_telemetrySequence;d["observed_at_ms"]=String(uint64_t(time(nullptr))*1000ULL);d["quality"]=0;JsonObject m=d["metrics"].to<JsonArray>().add<JsonObject>();m["name"]=name;m["type"]=7;m["value"]=value;char p[384];size_t n=serializeJson(d,p,sizeof(p));return n<sizeof(p)&&_mqtt.publish((String(_root)+"telemetry").c_str(),p,false);}
bool OmniLinkMqtt::event(uint8_t severity,const char *code,const char *detail){if(!_mqtt.connected())return false;JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_eventSequence;d["observed_at_ms"]=String(uint64_t(time(nullptr))*1000ULL);d["severity"]=severity;d["code"]=code;d["detail"]=detail;char p[512];size_t n=serializeJson(d,p,sizeof(p));return n<sizeof(p)&&_mqtt.publish((String(_root)+"event").c_str(),p,false);}
void OmniLinkMqtt::status(){
#if defined(ESP8266) || defined(ESP32)
  IPAddress ip = WiFi.localIP();
  if (ip != IPAddress(0, 0, 0, 0)) {
    snprintf(_firmware, sizeof(_firmware), "ota@%s", ip.toString().c_str());
  }
#endif
  JsonDocument d;d["online"]=true;d["boot_id"]=_boot;d["firmware"]=_firmware;char p[192];size_t n=serializeJson(d,p,sizeof(p));if(n<sizeof(p))_mqtt.publish((String(_root)+"status").c_str(),p,false);
}
void OmniLinkMqtt::loop(){if(!_configured)return;uint32_t now=millis();if(!_mqtt.connected()){if(now-_lastReconnect<3000)return;_lastReconnect=now;if(_mqtt.connect(_id,_id,_secret,(String(_root)+"status").c_str(),1,false,"{\"online\":false}")){_mqtt.subscribe((String(_root)+"cmd").c_str(),1);status();}}else{_mqtt.loop();if(now-_lastStatus>10000){_lastStatus=now;status();}}}
bool OmniLinkMqtt::connected()const{return _mqtt.connected();}
#endif

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

/* HTTP transport matching OmniLinkMqtt's virtual-pin API. Pass a WiFiClient
   for HTTP or a certificate-verified WiFiClientSecure for HTTPS. */
template<class NetworkClient>
class OmniLinkHttp {
public:
  typedef bool (*BoolHandler)(bool);
  typedef bool (*IntHandler)(int32_t);
  typedef bool (*UIntHandler)(uint32_t);
  typedef bool (*FloatHandler)(float);
  typedef bool (*StringHandler)(const char*);

  explicit OmniLinkHttp(NetworkClient &network) : _network(network), _count(0),
    _sequence(0), _lastPoll(0), _lastConnect(0), _configured(false), _isConnected(false) {
    memset(_id,0,sizeof(_id)); memset(_secret,0,sizeof(_secret));
    memset(_firmware,0,sizeof(_firmware)); memset(_boot,0,sizeof(_boot)); _base[0]=0;
  }

  void begin(const char *baseUrl,const char *deviceId,const char *deviceSecret,const char *firmware) {
    snprintf(_base,sizeof(_base),"%s",baseUrl); trimSlash(_base);
    snprintf(_id,sizeof(_id),"%s",deviceId); snprintf(_secret,sizeof(_secret),"%s",deviceSecret);
    snprintf(_firmware,sizeof(_firmware),"%s",firmware); makeBoot();
    _sequence=0;_lastConnect=0;_isConnected=false;_configured=true;
  }
  void onBool(uint16_t c,BoolHandler f){Binding b{};b.channel=c;b.kind=K_BOOL;b.fn.boolean=f;bind(b);}
  void onInt(uint16_t c,IntHandler f){Binding b{};b.channel=c;b.kind=K_INT;b.fn.integer=f;bind(b);}
  void onUInt(uint16_t c,UIntHandler f){Binding b{};b.channel=c;b.kind=K_UINT;b.fn.unsignedInteger=f;bind(b);}
  void onFloat(uint16_t c,FloatHandler f){Binding b{};b.channel=c;b.kind=K_FLOAT;b.fn.real=f;bind(b);}
  void onString(uint16_t c,StringHandler f){Binding b{};b.channel=c;b.kind=K_STRING;b.fn.string=f;bind(b);}
  bool connected() const { return _isConnected; }

  void loop() {
    if(!_configured)return;
    uint32_t now=millis();
    if(!_isConnected){if(now-_lastConnect<3000)return;_lastConnect=now;if(!connectDevice()){_isConnected=false;return;} _isConnected=true;_lastPoll=0;}
    if(now-_lastPoll<1000)return;_lastPoll=now;
    JsonDocument commands;
    int code=request("GET",root()+"/commands",nullptr,&commands);
    if(code<200||code>=300){_isConnected=false;return;}
    if(!commands.is<JsonArray>())return;
    for(JsonObject cmd:commands.as<JsonArray>())applyCommand(cmd);
  }

  bool reportBool(uint16_t c,bool v){JsonDocument x;x.set(v);return report(c,1,x.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
  bool reportInt(uint16_t c,int32_t v){return reportInt(c,6,v);}
  bool reportInt(uint16_t c,uint8_t t,int32_t v){if(t!=2&&t!=4&&t!=6)return false;JsonDocument x;x.set(v);return report(c,t,x.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
  bool reportUInt(uint16_t c,uint8_t t,uint32_t v){if(t!=3&&t!=5&&t!=7)return false;JsonDocument x;x.set(v);return report(c,t,x.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
  bool reportFloat(uint16_t c,float v){JsonDocument x;x.set(v);return report(c,10,x.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
  bool reportString(uint16_t c,const char *v){JsonDocument x;x.set(v);return report(c,12,x.as<JsonVariantConst>(),"00000000000000000000000000000000",0);}
  bool telemetryFloat(const char *name,float v){JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_sequence;d["observed_at_ms"]=0;d["quality"]=0;JsonObject m=d["metrics"].to<JsonArray>().add<JsonObject>();m["name"]=name;m["type"]=10;m["value"]=v;return post("/telemetry",d);}
  bool telemetryUInt(const char *name,uint32_t v){JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_sequence;d["observed_at_ms"]=0;d["quality"]=0;JsonObject m=d["metrics"].to<JsonArray>().add<JsonObject>();m["name"]=name;m["type"]=7;m["value"]=v;return post("/telemetry",d);}
  bool event(uint8_t severity,const char *code,const char *detail){JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_sequence;d["observed_at_ms"]=0;d["severity"]=severity;d["code"]=code;d["detail"]=detail;return post("/event",d);}

private:
  enum Kind:uint8_t {K_BOOL=1,K_INT=2,K_UINT=3,K_FLOAT=4,K_STRING=5};
  union Handler {BoolHandler boolean;IntHandler integer;UIntHandler unsignedInteger;FloatHandler real;StringHandler string;};
  struct Binding {uint16_t channel;Kind kind;Handler fn;uint32_t revision;char key[33];};
  static const uint8_t MAX_BINDINGS=16;
  NetworkClient &_network;Binding _bindings[MAX_BINDINGS];uint8_t _count;
  uint32_t _sequence,_lastPoll,_lastConnect;bool _configured,_isConnected;
  char _base[192],_id[65],_secret[65],_firmware[33],_boot[33];

  static void trimSlash(char *s){size_t n=strlen(s);while(n&&s[n-1]=='/')s[--n]=0;}
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
    if(strcmp(_boot,"00000000000000000000000000000000")==0)_boot[31]='1';
  }
  void bind(Binding &b){for(uint8_t i=0;i<_count;i++)if(_bindings[i].channel==b.channel){_bindings[i].kind=b.kind;_bindings[i].fn=b.fn;return;}if(_count<MAX_BINDINGS){b.revision=0;b.key[0]=0;_bindings[_count++]=b;}}
  int request(const char *method,const String &path,JsonDocument *body,JsonDocument *response){
    HTTPClient http;String url=String(_base)+path;
    if(!http.begin(_network,url))return -1;
    http.addHeader("Authorization",String("Device ")+_secret);
    if(body)http.addHeader("Content-Type","application/json");
    int code;
    if(body){String payload;serializeJson(*body,payload);code=http.POST(payload);}
    else code=http.GET();
    if(code>0&&response){String payload=http.getString();if(deserializeJson(*response,payload))code=-2;}
    http.end();return code;
  }
  bool post(const String &path,JsonDocument &body){int code=request("POST",root()+path,&body,nullptr);return code>=200&&code<300;}
  bool connectDevice(){JsonDocument body;body["boot_id"]=_boot;body["firmware"]=_firmware;JsonDocument response;int code=request("POST",root()+"/connect",&body,&response);return code>=200&&code<300;}
  bool report(uint16_t c,uint8_t type,JsonVariantConst value,const char *key,uint32_t revision){
    JsonDocument d;d["boot_id"]=_boot;d["sequence"]=++_sequence;d["channel"]=c;d["type"]=type;d["value"]=value;d["observed_at_ms"]=0;d["applied_command_key"]=key;d["desired_revision"]=revision;return post("/report",d);
  }
  bool acknowledge(const char *key,uint32_t revision,const char *status,uint16_t error){JsonDocument d;d["command_key"]=key;d["desired_revision"]=revision;d["status"]=status;d["error_code"]=error;return post("/ack",d);}
  void applyCommand(JsonObject cmd){
    const char *key=cmd["command_key"]|"";uint32_t revision=cmd["desired_revision"]|0U;int channel=cmd["channel"]|-1;int type=cmd["type"]|0;
    if(strlen(key)!=32||!revision||channel<0||channel>1023)return;
    Binding *b=nullptr;for(uint8_t i=0;i<_count;i++)if(_bindings[i].channel==channel){b=&_bindings[i];break;}
    if(!b){acknowledge(key,revision,"rejected",404);return;}
    if(strcmp(b->key,key)==0&&b->revision==revision){acknowledge(key,revision,"applied",0);report(channel,type,cmd["value"].as<JsonVariantConst>(),key,revision);return;}
    if(revision<=b->revision){acknowledge(key,revision,"rejected",409);return;}
    JsonVariantConst v=cmd["value"];bool ok=false,valid=false;
    switch(b->kind){
      case K_BOOL:if(type==1&&v.is<bool>()){valid=true;ok=b->fn.boolean(v.as<bool>());}break;
      case K_INT:if((type==2||type==4||type==6)&&v.is<int32_t>()){valid=true;ok=b->fn.integer(v.as<int32_t>());}break;
      case K_UINT:if((type==3||type==5||type==7)&&v.is<uint32_t>()){valid=true;ok=b->fn.unsignedInteger(v.as<uint32_t>());}break;
      case K_FLOAT:if(type==10&&v.is<float>()){valid=true;ok=b->fn.real(v.as<float>());}break;
      case K_STRING:if(type==12&&v.is<const char*>()){valid=true;ok=b->fn.string(v.as<const char*>());}break;
    }
    if(!ok){acknowledge(key,revision,"rejected",valid?500:400);return;}
    b->revision=revision;snprintf(b->key,sizeof(b->key),"%s",key);
    if(acknowledge(key,revision,"applied",0))report(channel,uint8_t(type),v,key,revision);
  }
};

#include "OmniLinkSerial.h"
using namespace omnilink;

OmniLinkSerial::OmniLinkSerial(Stream &port):_port(port),_length(0),_overflow(false),_onSync(nullptr),_id(nullptr),_secret(nullptr){}

void OmniLinkSerial::loop(){
  while(_port.available()){
    char c=char(_port.read());
    if(c=='\n'){if(!_overflow){_line[_length]=0;handle(_line);}_length=0;_overflow=false;}
    else if(c!='\r'){if(_length+1<LINE_SIZE&&!_overflow)_line[_length++]=c;else _overflow=true;}
  }
}

void OmniLinkSerial::handle(const char *line){
  JsonDocument d;if(deserializeJson(d,line))return;
  const char *op=d["op"]|"";
  if(strcmp(op,"sync")==0){if(_onSync)_onSync();return;}
  if(strcmp(op,"identify")==0){JsonDocument a;a["op"]="identity";a["id"]=_id?_id:"";a["secret"]=_secret?_secret:"";send(a);return;}
  if(strcmp(op,"command")!=0)return;
  int ch=d["channel"]|-1;uint32_t rev=d["desired_revision"]|0U;const char *key=d["command_key"]|"";int type=d["type"]|0;
  if(!validCommand(key,rev,ch))return;
  JsonVariantConst v=d["value"];
  Outcome o=_bindings.apply(ch,type,key,rev,v);
  bool ok=o==APPLIED||o==DUPLICATE;
  // The gateway forwards the ACK and, when applied, the confirming report.
  JsonDocument a;a["op"]="ack";a["command_key"]=key;a["desired_revision"]=rev;a["status"]=ok?"applied":"rejected";
  a["error_code"]=ok?0:errorCode(o);a["channel"]=ch;a["type"]=type;a["value"]=v;
  send(a);
}

bool OmniLinkSerial::send(JsonDocument &doc){
  if(measureJson(doc)+1>=LINE_SIZE)return false;
  serializeJson(doc,_port);_port.write('\n');return true;
}
bool OmniLinkSerial::sendReport(uint16_t c,uint8_t t,JsonVariantConst v){JsonDocument d;d["op"]="report";d["channel"]=c;d["type"]=t;d["value"]=v;return send(d);}
bool OmniLinkSerial::sendMetric(const char *name,uint8_t t,JsonVariantConst v){JsonDocument d;d["op"]="telemetry";d["metric"]=name;d["type"]=t;d["value"]=v;return send(d);}

bool OmniLinkSerial::reportBool(uint16_t c,bool v){JsonDocument d;d.set(v);return sendReport(c,T_BOOL,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportInt(uint16_t c,int32_t v){return reportInt(c,T_INT32,v);}
bool OmniLinkSerial::reportInt(uint16_t c,uint8_t t,int32_t v){if(!intType(t)||!intFits(t,v))return false;JsonDocument d;d.set(v);return sendReport(c,t,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportUInt(uint16_t c,uint8_t t,uint32_t v){if(!uintType(t)||!uintFits(t,v))return false;JsonDocument d;d.set(v);return sendReport(c,t,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportFloat(uint16_t c,float v){if(isnan(v)||isinf(v))return false;JsonDocument d;d.set(v);return sendReport(c,T_FLOAT32,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportString(uint16_t c,const char *v){JsonDocument d;d.set(v);return sendReport(c,T_STRING,d.as<JsonVariantConst>());}
bool OmniLinkSerial::telemetryFloat(const char *name,float v){if(isnan(v)||isinf(v))return false;JsonDocument d;d.set(v);return sendMetric(name,T_FLOAT32,d.as<JsonVariantConst>());}
bool OmniLinkSerial::telemetryInt(const char *name,int32_t v){JsonDocument d;d.set(v);return sendMetric(name,T_INT32,d.as<JsonVariantConst>());}
bool OmniLinkSerial::telemetryUInt(const char *name,uint32_t v){JsonDocument d;d.set(v);return sendMetric(name,T_UINT32,d.as<JsonVariantConst>());}
bool OmniLinkSerial::event(uint8_t severity,const char *code,const char *detail){JsonDocument d;d["op"]="event";d["severity"]=severity;d["code"]=code;d["detail"]=detail;return send(d);}

#include "OmniLinkSerial.h"

OmniLinkSerial::OmniLinkSerial(Stream &port):_port(port),_count(0),_length(0),_overflow(false){}
void OmniLinkSerial::bind(uint16_t c,Kind k,Handler fn){for(uint8_t i=0;i<_count;i++)if(_bindings[i].channel==c){_bindings[i].kind=k;_bindings[i].fn=fn;return;}if(_count<MAX_BINDINGS){Binding &b=_bindings[_count++];b.channel=c;b.kind=k;b.fn=fn;b.revision=0;b.key[0]=0;}}
void OmniLinkSerial::onBool(uint16_t c,BoolHandler f){Handler h;h.boolean=f;bind(c,K_BOOL,h);}
void OmniLinkSerial::onInt(uint16_t c,IntHandler f){Handler h;h.integer=f;bind(c,K_INT,h);}
void OmniLinkSerial::onUInt(uint16_t c,UIntHandler f){Handler h;h.unsignedInteger=f;bind(c,K_UINT,h);}
void OmniLinkSerial::onFloat(uint16_t c,FloatHandler f){Handler h;h.real=f;bind(c,K_FLOAT,h);}
void OmniLinkSerial::onString(uint16_t c,StringHandler f){Handler h;h.string=f;bind(c,K_STRING,h);}
void OmniLinkSerial::loop(){while(_port.available()){char c=char(_port.read());if(c=='\n'){if(!_overflow){_line[_length]=0;handle(_line);}_length=0;_overflow=false;}else if(c!='\r'){if(_length+1<LINE_SIZE&&!_overflow)_line[_length++]=c;else _overflow=true;}}}
void OmniLinkSerial::handle(const char *line){
  JsonDocument d;if(deserializeJson(d,line))return;
  if(strcmp(d["op"]|"","command")!=0)return;
  uint16_t ch=d["channel"]|65535;uint32_t rev=d["desired_revision"]|0U;const char *key=d["command_key"]|"";int type=d["type"]|0;
  if(ch==65535||!rev||strlen(key)!=32)return;
  JsonVariantConst v=d["value"];bool ok=false;uint16_t error=404;
  for(uint8_t i=0;i<_count;i++)if(_bindings[i].channel==ch){Binding &b=_bindings[i];error=400;
    if(strcmp(b.key,key)==0&&b.revision==rev){JsonDocument a;a["op"]="ack";a["command_key"]=key;a["desired_revision"]=rev;a["status"]="applied";a["error_code"]=0;a["channel"]=ch;a["type"]=type;a["value"]=v;serializeJson(a,_port);_port.write('\n');return;}
    if(rev<=b.revision){error=409;break;}
    if(b.kind==K_BOOL&&type==1&&v.is<bool>())ok=b.fn.boolean(v.as<bool>());
    else if(b.kind==K_INT&&(type==2||type==4||type==6)&&v.is<int32_t>())ok=b.fn.integer(v.as<int32_t>());
    else if(b.kind==K_UINT&&(type==3||type==5||type==7)&&v.is<uint32_t>())ok=b.fn.unsignedInteger(v.as<uint32_t>());
    else if(b.kind==K_FLOAT&&type==10&&v.is<float>())ok=b.fn.real(v.as<float>());
    else if(b.kind==K_STRING&&type==12&&v.is<const char*>())ok=b.fn.string(v.as<const char*>());
    if(!ok&&error==400)error=500;
    if(ok){b.revision=rev;snprintf(b.key,sizeof(b.key),"%s",key);}
    break;
  }
  JsonDocument a;a["op"]="ack";a["command_key"]=key;a["desired_revision"]=rev;a["status"]=ok?"applied":"rejected";a["error_code"]=ok?0:error;a["channel"]=ch;a["type"]=type;a["value"]=v;
  serializeJson(a,_port);_port.write('\n');
}
bool OmniLinkSerial::sendReport(uint16_t c,uint8_t t,JsonVariantConst v){JsonDocument d;d["op"]="report";d["channel"]=c;d["type"]=t;d["value"]=v;size_t n=measureJson(d);if(n+1>=LINE_SIZE)return false;serializeJson(d,_port);_port.write('\n');return true;}
bool OmniLinkSerial::reportBool(uint16_t c,bool v){JsonDocument d;d.set(v);return sendReport(c,1,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportInt(uint16_t c,int32_t v){return reportInt(c,6,v);}
bool OmniLinkSerial::reportInt(uint16_t c,uint8_t t,int32_t v){if(t!=2&&t!=4&&t!=6)return false;JsonDocument d;d.set(v);return sendReport(c,t,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportUInt(uint16_t c,uint8_t t,uint32_t v){if(t!=3&&t!=5&&t!=7)return false;JsonDocument d;d.set(v);return sendReport(c,t,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportFloat(uint16_t c,float v){JsonDocument d;d.set(v);return sendReport(c,10,d.as<JsonVariantConst>());}
bool OmniLinkSerial::reportString(uint16_t c,const char *v){JsonDocument d;d.set(v);return sendReport(c,12,d.as<JsonVariantConst>());}
bool OmniLinkSerial::telemetryFloat(const char *name,float value){JsonDocument d;d["op"]="telemetry";d["metric"]=name;d["type"]=10;d["value"]=value;size_t n=measureJson(d);if(n+1>=LINE_SIZE)return false;serializeJson(d,_port);_port.write('\n');return true;}
bool OmniLinkSerial::telemetryUInt(const char *name,uint32_t value){JsonDocument d;d["op"]="telemetry";d["metric"]=name;d["type"]=7;d["value"]=value;size_t n=measureJson(d);if(n+1>=LINE_SIZE)return false;serializeJson(d,_port);_port.write('\n');return true;}
bool OmniLinkSerial::event(uint8_t severity,const char *code,const char *detail){JsonDocument d;d["op"]="event";d["severity"]=severity;d["code"]=code;d["detail"]=detail;size_t n=measureJson(d);if(n+1>=LINE_SIZE)return false;serializeJson(d,_port);_port.write('\n');return true;}

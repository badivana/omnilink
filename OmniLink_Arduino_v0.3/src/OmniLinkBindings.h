#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

/* Shared by the HTTP, MQTT and Serial transports: one table of virtual-pin
   handlers and one set of command rules, so every transport accepts, rejects
   and de-duplicates commands exactly the same way.

   Type codes are the OmniLink Server v0.6 channel types (omnilink/onp.py). */
namespace omnilink {

enum Type : uint8_t {
  T_BOOL=1, T_INT8=2, T_UINT8=3, T_INT16=4, T_UINT16=5, T_INT32=6, T_UINT32=7,
  T_FLOAT32=10, T_STRING=12
};

typedef bool (*BoolHandler)(bool value);
typedef bool (*IntHandler)(int32_t value);
typedef bool (*UIntHandler)(uint32_t value);
typedef bool (*FloatHandler)(float value);
typedef bool (*StringHandler)(const char *value);
typedef void (*ConnectHandler)();

enum Kind : uint8_t { K_BOOL=1, K_INT=2, K_UINT=3, K_FLOAT=4, K_STRING=5 };
union Handler { BoolHandler boolean; IntHandler integer; UIntHandler unsignedInteger; FloatHandler real; StringHandler string; };
struct Binding { uint16_t channel; Kind kind; Handler fn; uint32_t revision; char key[33]; };

// Result of applying one server command. Error codes are sent in the ACK.
enum Outcome : uint8_t { APPLIED, DUPLICATE, UNBOUND, STALE, BAD_TYPE, HANDLER_FAILED };
inline uint16_t errorCode(Outcome o) {
  switch(o){case UNBOUND:return 404;case STALE:return 409;case BAD_TYPE:return 400;case HANDLER_FAILED:return 500;default:return 0;}
}

static const char NO_COMMAND[] = "00000000000000000000000000000000";

inline bool intType(uint8_t t){return t==T_INT8||t==T_INT16||t==T_INT32;}
inline bool uintType(uint8_t t){return t==T_UINT8||t==T_UINT16||t==T_UINT32;}

// Does a sketch handler kind accept this server channel type?
inline bool compatible(Kind k,uint8_t t){
  switch(k){case K_BOOL:return t==T_BOOL;case K_INT:return intType(t);case K_UINT:return uintType(t);
            case K_FLOAT:return t==T_FLOAT32;case K_STRING:return t==T_STRING;}
  return false;
}

// Value fits the declared wire type (the server also enforces channel bounds).
inline bool fits(uint8_t t,JsonVariantConst v){
  switch(t){
    case T_BOOL:return v.is<bool>();
    case T_INT8:return v.is<int8_t>();   case T_UINT8:return v.is<uint8_t>();
    case T_INT16:return v.is<int16_t>(); case T_UINT16:return v.is<uint16_t>();
    case T_INT32:return v.is<int32_t>(); case T_UINT32:return v.is<uint32_t>();
    case T_FLOAT32:return v.is<float>(); case T_STRING:return v.is<const char*>();
  }
  return false;
}
inline bool intFits(uint8_t t,int32_t v){return (t==T_INT8&&v>=-128&&v<=127)||(t==T_INT16&&v>=-32768&&v<=32767)||t==T_INT32;}
inline bool uintFits(uint8_t t,uint32_t v){return (t==T_UINT8&&v<=255)||(t==T_UINT16&&v<=65535)||t==T_UINT32;}

template<uint8_t N>
class Bindings {
public:
  Bindings():_count(0){}
  bool add(uint16_t channel,Kind kind,Handler fn){
    if(channel>1023)return false;
    for(uint8_t i=0;i<_count;i++)if(_b[i].channel==channel){_b[i].kind=kind;_b[i].fn=fn;return true;}
    if(_count>=N)return false;
    Binding &b=_b[_count++];b.channel=channel;b.kind=kind;b.fn=fn;b.revision=0;b.key[0]=0;return true;
  }
  const Binding *find(uint16_t channel)const{for(uint8_t i=0;i<_count;i++)if(_b[i].channel==channel)return &_b[i];return nullptr;}
  uint8_t count()const{return _count;}
  const Binding &at(uint8_t i)const{return _b[i];}

  /* Applies a command. A repeated key/revision (a server retry after a lost
     ACK) is DUPLICATE: acknowledge it again without re-running the handler. */
  Outcome apply(uint16_t channel,uint8_t type,const char *key,uint32_t revision,JsonVariantConst value){
    Binding *b=nullptr;for(uint8_t i=0;i<_count;i++)if(_b[i].channel==channel){b=&_b[i];break;}
    if(!b)return UNBOUND;
    if(b->revision==revision&&strcmp(b->key,key)==0)return DUPLICATE;
    if(revision<=b->revision)return STALE;
    if(!compatible(b->kind,type)||!fits(type,value))return BAD_TYPE;
    bool ok=false;
    switch(b->kind){
      case K_BOOL:ok=b->fn.boolean(value.as<bool>());break;
      case K_INT:ok=b->fn.integer(value.as<int32_t>());break;
      case K_UINT:ok=b->fn.unsignedInteger(value.as<uint32_t>());break;
      case K_FLOAT:ok=b->fn.real(value.as<float>());break;
      case K_STRING:ok=b->fn.string(value.as<const char*>());break;
    }
    if(!ok)return HANDLER_FAILED;
    b->revision=revision;snprintf(b->key,sizeof(b->key),"%s",key);
    return APPLIED;
  }
private:
  Binding _b[N];uint8_t _count;
};

// Basic command shape checks shared by all transports.
inline bool validCommand(const char *key,uint32_t revision,int channel){
  if(!key||strlen(key)!=32||!revision||channel<0||channel>1023)return false;
  for(uint8_t i=0;i<32;i++){char c=key[i];if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;}
  return true;
}

} // namespace omnilink

/* Sketch-facing macro so each transport declares the same handler API. */
#define OMNILINK_HANDLER_API(table) \
  typedef omnilink::BoolHandler BoolHandler; typedef omnilink::IntHandler IntHandler; \
  typedef omnilink::UIntHandler UIntHandler; typedef omnilink::FloatHandler FloatHandler; \
  typedef omnilink::StringHandler StringHandler; typedef omnilink::ConnectHandler ConnectHandler; \
  bool onBool(uint16_t c,BoolHandler f){omnilink::Handler h;h.boolean=f;return table.add(c,omnilink::K_BOOL,h);} \
  bool onInt(uint16_t c,IntHandler f){omnilink::Handler h;h.integer=f;return table.add(c,omnilink::K_INT,h);} \
  bool onUInt(uint16_t c,UIntHandler f){omnilink::Handler h;h.unsignedInteger=f;return table.add(c,omnilink::K_UINT,h);} \
  bool onFloat(uint16_t c,FloatHandler f){omnilink::Handler h;h.real=f;return table.add(c,omnilink::K_FLOAT,h);} \
  bool onString(uint16_t c,StringHandler f){omnilink::Handler h;h.string=f;return table.add(c,omnilink::K_STRING,h);}

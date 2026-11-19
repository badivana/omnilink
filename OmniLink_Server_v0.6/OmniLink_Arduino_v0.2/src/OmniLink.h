#pragma once
/* One include for the MQTT and USB Serial transports. HTTP sketches include
   OmniLinkHttp.h directly. */
#if defined(ESP32) || defined(ESP8266)
  #include "OmniLinkMqtt.h"
  typedef OmniLinkMqtt OmniLink;
#elif defined(__AVR__)
  #include "OmniLinkSerial.h"
  typedef OmniLinkSerial OmniLink;
#else
  #error "OmniLink Arduino v0.2 supports ESP32, ESP8266, and AVR Uno/Nano serial."
#endif

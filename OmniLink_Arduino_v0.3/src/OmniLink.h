#pragma once
/* OmniLink Arduino library 0.3 for OmniLink Server v0.6.
   One include for the MQTT (ESP32/ESP8266) and USB Serial (AVR) transports.
   HTTP sketches include OmniLinkHttp.h directly. */
#define OMNILINK_ARDUINO_VERSION "0.3.0"
#if defined(ESP32) || defined(ESP8266)
  #include "OmniLinkMqtt.h"
  typedef OmniLinkMqtt OmniLink;
#elif defined(__AVR__) || defined(OMNILINK_SERIAL_TRANSPORT)
  #include "OmniLinkSerial.h"
  typedef OmniLinkSerial OmniLink;
#else
  #error "OmniLink Arduino 0.3 supports ESP32, ESP8266 (HTTP/MQTT) and AVR Uno/Nano (USB Serial)."
#endif

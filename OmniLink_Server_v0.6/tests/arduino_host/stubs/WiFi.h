#pragma once
#include <Arduino.h>
#define WL_CONNECTED 3
#define WIFI_STA 1
class Client { public: virtual ~Client() {} };
class WiFiClient : public Client {};
struct WiFiClass {
  void begin(const char *, const char *) {}
  int status() { return WL_CONNECTED; }
  IPAddress localIP() { return IPAddress(127, 0, 0, 1); }
  void mode(int) {}
};
inline WiFiClass WiFi;
inline void configTime(long, int, const char *, const char * = nullptr, const char * = nullptr) {}

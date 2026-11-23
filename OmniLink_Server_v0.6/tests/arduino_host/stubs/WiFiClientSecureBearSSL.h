#pragma once
#include <ESP8266WiFi.h>
namespace BearSSL {
class X509List { public: explicit X509List(const char *) {} };
class WiFiClientSecure : public WiFiClient {
public:
  void setTrustAnchors(const X509List *) {}
  void setBufferSizes(int, int) {}
  void setInsecure() {}
  void setX509Time(time_t) {}
  int getLastSSLError(char *dest = nullptr, size_t len = 0) { if (dest && len) dest[0] = 0; return 0; }
};
}

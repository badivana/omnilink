#pragma once
#include <Arduino.h>
#include <WiFi.h>
/* Forwards each request to the harness, which performs it against the server. */
class HTTPClient {
  std::string url, auth, body;
  int send(const char *method, const String *payload) {
    JsonDocument r; r["h"] = "http"; r["method"] = method; r["url"] = url; r["auth"] = auth;
    if (payload) r["body"] = payload->c_str();
    JsonDocument a = hostExchange(r);
    body = std::string(a["body"] | "");
    return a["code"] | -1;
  }
public:
  template <class C> bool begin(C &, const String &u) { url = u.c_str(); auth.clear(); return true; }
  void addHeader(const String &k, const String &v) { if (k == "Authorization") auth = v.c_str(); }
  int GET() { return send("GET", nullptr); }
  int POST(const String &payload) { return send("POST", &payload); }
  String getString() { return String(body); }
  void end() {}
};

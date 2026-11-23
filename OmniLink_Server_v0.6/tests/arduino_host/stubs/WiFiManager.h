#pragma once
#include <Arduino.h>
class WiFiManagerParameter {
  std::string value;
public:
  WiFiManagerParameter(const char *, const char *, const char *v, int) : value(v ? v : "") {}
  const char *getValue() { return value.c_str(); }
};
class WiFiManager {
public:
  void setSaveConfigCallback(std::function<void()>) {}
  void addParameter(WiFiManagerParameter *) {}
  void setConfigPortalTimeout(unsigned long) {}
  bool startConfigPortal(const char *) { return true; }
  bool autoConnect(const char *) { return true; }
  void resetSettings() {}
};

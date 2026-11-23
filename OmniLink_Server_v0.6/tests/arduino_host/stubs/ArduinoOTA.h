#pragma once
struct ArduinoOTAClass { void setHostname(const char *) {} void setPassword(const char *) {} void begin() {} void handle() {} };
inline ArduinoOTAClass ArduinoOTA;

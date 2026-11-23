#pragma once
#include <WiFi.h>
struct EspClass { void restart() { std::exit(0); } };
inline EspClass ESP;

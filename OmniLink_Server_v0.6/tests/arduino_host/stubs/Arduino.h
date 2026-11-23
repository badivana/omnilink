#pragma once
/* Minimal host-side Arduino core used only by tests/test_arduino_library.py.
   It lets the OmniLink Arduino library and its example sketches compile with a
   desktop g++ and exchange lockstep JSON lines with the Python test harness. */
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <math.h>
#include <string>
#include <ctime>
#include <chrono>
#include <thread>
#include <random>
#include <functional>
#include <iostream>

typedef uint8_t byte;
typedef bool boolean;
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define PROGMEM
#define F(s) (s)
#define A0 100
#define D1 5
#define D2 4
#define D3 0
#define D4 2
#ifndef HOST_ANALOG
#define HOST_ANALOG 512
#endif

inline uint32_t millis() {
  static const auto start = std::chrono::steady_clock::now();
  return uint32_t(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count());
}
inline void delay(uint32_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
inline int *hostPins() { static int pins[256]; return pins; }
inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int value) { hostPins()[pin & 255] = value; }
inline int digitalRead(int pin) { return hostPins()[pin & 255]; }
inline int analogRead(int) { return HOST_ANALOG; }
inline size_t strlcpy(char *d, const char *s, size_t n) { size_t l = strlen(s); if (n) { size_t c = l < n - 1 ? l : n - 1; memcpy(d, s, c); d[c] = 0; } return l; }

class String {
  std::string s;
public:
  String() {}
  String(const char *c) { if (c) s = c; }
  String(const std::string &v) : s(v) {}
  explicit String(int v) : s(std::to_string(v)) {}
  explicit String(unsigned v) : s(std::to_string(v)) {}
  explicit String(long v) : s(std::to_string(v)) {}
  explicit String(unsigned long v) : s(std::to_string(v)) {}
  explicit String(long long v) : s(std::to_string(v)) {}
  explicit String(unsigned long long v) : s(std::to_string(v)) {}
  String &operator=(const char *c) { s = c ? c : ""; return *this; }
  const char *c_str() const { return s.c_str(); }
  unsigned length() const { return unsigned(s.size()); }
  bool concat(const char *c) { if (c) s += c; return true; }
  String &operator+=(const String &o) { s += o.s; return *this; }
  friend String operator+(const String &a, const String &b) { return String(a.s + b.s); }
  friend String operator+(const String &a, const char *b) { return String(a.s + (b ? b : "")); }
  bool operator==(const String &o) const { return s == o.s; }
  bool operator!=(const String &o) const { return s != o.s; }
  bool operator==(const char *c) const { return s == (c ? c : ""); }
  bool operator!=(const char *c) const { return !(*this == c); }
};

class IPAddress {
public:
  IPAddress(int = 0, int = 0, int = 0, int = 0) {}
  String toString() const { return String("127.0.0.1"); }
  bool operator!=(const IPAddress &) const { return false; }
};

class Print {
public:
  virtual ~Print() {}
  virtual size_t write(uint8_t c) = 0;
  virtual size_t write(const uint8_t *b, size_t n) { for (size_t i = 0; i < n; i++) write(b[i]); return n; }
  size_t write(const char *s) { return write((const uint8_t *)s, strlen(s)); }
  size_t print(const char *s) { return write(s); }
  size_t print(const String &s) { return write(s.c_str()); }
  size_t print(const IPAddress &a) { return print(a.toString()); }
  size_t print(long v) { return print(String(v)); }
  size_t println() { return write("\n"); }
  template <class T> size_t println(const T &v) { size_t n = print(v); return n + println(); }
  int printf(const char *fmt, ...) { char b[512]; va_list a; va_start(a, fmt); int n = vsnprintf(b, sizeof b, fmt, a); va_end(a); write(b); return n; }
};
class Printable { public: virtual ~Printable() {} virtual size_t printTo(Print &p) const = 0; };
class Stream : public Print {
public:
  using Print::write;
  virtual int available() = 0;
  virtual int read() = 0;
  virtual int peek() { return -1; }
  size_t readBytes(char *b, size_t n) { size_t i = 0; while (i < n) { int c = read(); if (c < 0) break; b[i++] = char(c); } return i; }
};

#include "host_harness.h"

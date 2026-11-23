#pragma once
#include <Arduino.h>
class File : public Stream {
public:
  using Print::write;
  explicit operator bool() const { return false; }
  void close() {}
  int available() override { return 0; }
  int read() override { return -1; }
  size_t write(uint8_t) override { return 0; }
};

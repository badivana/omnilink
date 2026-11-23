#pragma once
#include <FS.h>
struct LittleFSClass {
  bool begin() { return true; } bool format() { return true; }
  File open(const char *, const char *) { return File(); }
  bool exists(const char *) { return false; } bool remove(const char *) { return true; }
};
inline LittleFSClass LittleFS;

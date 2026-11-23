#pragma once
/* Lockstep channel to the Python harness: one JSON request line on stdout,
   one JSON reply line on stdin. EOF ends the program. */
#include <ArduinoJson.h>

inline JsonDocument hostExchange(JsonDocument &request) {
  std::string line;
  serializeJson(request, line);
  fputs(line.c_str(), stdout); fputc('\n', stdout); fflush(stdout);
  std::string reply;
  if (!std::getline(std::cin, reply)) std::exit(0);
  JsonDocument doc;
  if (deserializeJson(doc, reply)) std::exit(3);
  return doc;
}

/* Serial: debug text goes to stderr, except in Uno protocol builds where it is
   the OmniLinkSerial link to the gateway under test. */
class HostSerial : public Stream {
  std::string in, out; uint32_t last = 0;
public:
  using Print::write;
  void begin(unsigned long) {}
  size_t write(uint8_t c) override {
#ifdef HOST_SERIAL_PROTOCOL
    out.push_back(char(c));
#else
    fputc(c, stderr);
#endif
    return 1;
  }
  int available() override {
#ifdef HOST_SERIAL_PROTOCOL
    if (in.empty() && millis() - last >= 20) {
      last = millis();
      JsonDocument r; r["h"] = "serial"; r["out"] = out; out.clear();
      JsonDocument a = hostExchange(r);
      in = std::string(a["in"] | "");
    }
#endif
    return int(in.size());
  }
  int read() override { if (in.empty()) return -1; int c = (unsigned char)in[0]; in.erase(0, 1); return c; }
  explicit operator bool() const { return true; }
};
inline HostSerial Serial;

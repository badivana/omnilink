# OmniLink Arduino library 0.3 validation

Checked on 2026-11-23 on Windows with Python 3.12, g++ (MSYS2 UCRT64) and ArduinoJson 7.4.3, against OmniLink Server v0.6.

## Run here

`tests/test_arduino_library.py` in the server package: **8 tests passed.**

- **ESP32_HTTP.** The unmodified example sketch was compiled for the host and run against a temporary server through the real `/device/{id}` HTTP API. Checked:
  - connect, then the initial state reports for V0–V3 and the telemetry history;
  - dashboard writes to V0, V1 and V2, each reaching `applied` with the confirmed reported revision;
  - a server-side bound rejection, and the device showing as online.
- **ESP32_MQTT.** Same checks. The harness plays Mosquitto: it requires the device ID / secret / client ID login and the status will topic, and passes every publish to the server's own `MQTTAdapter.message`. The server logged no rejected MQTT messages.
- **ArduinoUno_Serial.** The sketch was compiled as OmniLinkSerial and connected to the real `examples/arduino_uno_serial_gateway.py`, with the same checks, including the `sync` → state-report path.
- **Gateway resilience.** A server 400, stray debug text, a report for a pin that isn't configured, and a malformed board line are each logged, and the gateway stays connected.
- **ESP8266_HTTP, ESP8266_MQTT and ESP8266_Provisioning** compile against host stubs (`-Wall -Werror`).
- **Mutation check.** Removing the confirming report from the HTTP transport makes the ESP32 HTTP test fail.

## Not checked here

- The real ESP32/ESP8266/AVR toolchains, PubSubClient and WiFiManager are not installed. The board-specific APIs are stubbed (`tests/arduino_host/stubs`), so compiling for and flashing real boards still needs checking, and so does AVR RAM headroom.
- TLS was not exercised by the host runs: the ESP32 runs use the sketches' plain switches, and only the ESP8266 compile checks build the TLS branches. Certificate and hostname verification, BearSSL buffer sizes and NTP need a real board and server.
- No physical relays, sensors, USB serial port or Mosquitto broker were used.

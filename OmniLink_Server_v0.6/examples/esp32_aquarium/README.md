# Optional aquarium example

This is an explicit domain example; the server has no aquarium-specific channel creation or default hardware mode. Register it with `python -m examples.create_demo --aquarium`, then run `python -m examples.aquarium_simulator`, or adapt the supplied ESP32 sketch.

## Aquarium channels

| Channel | Type | Meaning |
|---|---|---|
| V0 | BOOL | Requested master power |
| V1 | UINT8 | Selector: 0 FILTER, 1 AIR |
| V2 | UINT8 | Device mode: 0 AUTO, 1 MANUAL |
| V3 | UINT32 | Filter duration, seconds |
| V4 | UINT32 | Air duration, seconds |
| V5 | UINT8, read-only | Actual output: 0 OFF, 1 FILTER, 2 AIR |
| V6 | FLOAT32, read-only | Water temperature; publish only if a sensor is installed |

`examples/esp32_aquarium/esp32_aquarium.ino` provides a hardware starting point. In Arduino IDE install ESP32 board support, PubSubClient, and ArduinoJson 7. Fill in Wi-Fi, hostname, credentials, and the CA certificate; adapt GPIOs and relay polarity. The example uses GPIO 16 for selector and GPIO 17 for master power, turns power off during selector changes, and confirms commands after applying outputs. It publishes uptime; it does not invent temperature readings.

AUTO interval cycling uses `millis()` and continues without a server connection. NTP is used for TLS certificate checks and command expiry. Server daily schedules require the server to be running. Choose device AUTO cycling or server selector schedules for a given controller to avoid competing control sources. The dashboard's **manual override** pauses *server* rules and schedules; write V2 = 1 to stop the ESP32's local AUTO cycle as well.

The ESP32 example restores saved output settings at boot and uses ESP32 Preferences for applied revisions. It is an example, not a transactional embedded SDK: Preferences writes span multiple keys, so a power cut during those writes can leave a partial ledger. Review that recovery behavior for your hardware application.


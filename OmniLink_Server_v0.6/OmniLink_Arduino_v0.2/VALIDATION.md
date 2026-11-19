# OmniLink Arduino library v0.2 validation

## Checked in this workspace

- Python syntax compilation passed for the Arduino Uno HTTPS gateway.
- JavaScript syntax checks passed for the expanded widget help in `OmniLink_WebClient_v0.6/assets/widgets.js` and the existing dashboard script.
- ESP HTTP/MQTT payload layouts were checked against the v0.6 `/device/{id}/connect`, command polling, ACK, state report, telemetry, and event endpoints.
- The release archive should contain only source, examples, and documentation; credentials are excluded by the server release builder.

## Not checked here

- The Arduino CLI, ESP32/ESP8266 board packages, ArduinoJson, and PubSubClient are not installed in this workspace, so sketches were not compiled or flashed.
- No physical ESP32, ESP8266, Uno, relay, sensor, MQTT broker, or USB serial port was available for an end-to-end run.
- Board-specific behavior such as PWM API, GPIO selection, relay polarity, Wi-Fi/TLS certificates, AVR RAM headroom, and USB reset timing must be verified with the actual board and wiring.

This package was source-checked only. Keep command handlers idempotent across device restarts, especially for one-shot actions, because the per-channel applied-command record is in memory and is not persisted by these sketches.

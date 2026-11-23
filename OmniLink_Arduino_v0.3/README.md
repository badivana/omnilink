# OmniLink Arduino library 0.3

The device side of **OmniLink Server v0.6**. Boards bind the server's typed virtual pins to their own GPIOs and actions:

| Board | Connection | On the board | On a computer |
|---|---|---|---|
| ESP32 | HTTPS (443 Caddy / 8000 native) or MQTT TLS 8883 | `OmniLinkHttp.h` or `OmniLink.h` | nothing |
| ESP8266 / NodeMCU | HTTPS or MQTT TLS 8883 | `OmniLinkHttp.h` or `OmniLink.h` | nothing |
| Uno / Nano (AVR) | USB serial JSON lines | `OmniLink.h` (OmniLinkSerial) | the server's `examples/arduino_uno_serial_gateway.py` |

## What changed from 0.2

- **The examples match the server's demo device.** `python -m examples.create_demo` creates the same pins every sketch uses, so you can create the device and flash a board without editing any channel numbers.
- **`onConnect()` / `onSync()` callbacks.** The board reports its real state after every reconnect. Before, sketches had to track a `reported` flag, and the Uno's first report could be lost while the gateway was still starting.
- **One command core for all three transports** (`OmniLinkBindings.h`). It handles type checks for each width, rejects out-of-range values, and recognizes retried duplicates the same way on every transport.
- **`telemetryInt()`**, plus `report*()`/`telemetry*()` now refuse values that don't fit the declared type, including NaN and infinity.
- **Diagnostics.** HTTP adds `lastStatus()` and `unconfiguredBindings()`, which compares your handlers with the server's pin schema. MQTT adds `state()`.
- **Clock handling.** The board checks a command's expiry time only when NTP has synchronized. The server always expires commands, so a board without NTP still works, with no fake timestamps needed.
- **HTTP backoff.** After 401/403/404 (wrong secret, disabled, unknown device) the HTTP transport waits 30 s before retrying, instead of retrying every 3 s.
- **`ESP8266_Provisioning`** replaces the old captive-portal sketch:
  - certificate verification is on by default;
  - OTA is off until you choose a password (the old one was hard-coded as `omnilink123`);
  - the fake clock fallback is gone;
  - it follows the demo pin layout and uses ArduinoJson 7.
  It still accepts the web client's "Download sketch" pre-fill.
- **A gateway that keeps running.** The Uno gateway reconnects with backoff, prints the server's reason when it rejects something, and shows the board's `Serial.print` text instead of crashing.

If you used 0.2: remove the old `OmniLink` folder from `Documents/Arduino/libraries` before installing 0.3. Handler and report calls are unchanged. `onX()` now returns `false` when the 16-pin (8 on AVR) limit is reached.

## Install

1. In the Arduino IDE choose **Sketch → Include Library → Add .ZIP Library** and select this folder (Arduino IDE 1.8). Arduino IDE 2.x accepts only ZIP files: run `python tools/build_arduino_library.py` in the server folder and select the `OmniLink_Arduino_v0.3.zip` it writes next to it. Remove any older copy from `Documents/Arduino/libraries` first.
2. In Library Manager install **ArduinoJson 7** and **PubSubClient** (Nick O'Leary). For provisioning, also install **WiFiManager** (tzapu).
3. Install the board package: **esp32 by Espressif Systems** or **esp8266 by ESP8266 Community**.

## Quick start with the demo device

From the server folder, while the server is running:

```powershell
.venv\Scripts\python -m examples.create_demo --url http://localhost:8000
```

This signs in, creates **Demo device** and writes `device-credentials.json`. In a fresh account it allocates:

| Pin | Name | Type | In the example sketches |
|---|---|---|---|
| V0 | Power | BOOL, writable | turns the selected output on/off |
| V1 | Output selection | UINT8 0..1, writable | 0 = output A, 1 = output B |
| V2 | Setpoint | UINT32 1..300, writable | how often the Measurement is sampled, in seconds |
| V3 | Measurement | FLOAT32 0..100, read-only | analog input in percent, also sent as telemetry `measurement` for charts |

If the account already used some pins, `create_demo` picks the next free ones. In that case copy the numbers from **Devices & pins** into `PIN_POWER` … `PIN_MEASUREMENT`.

Open an example, paste `id` and `secret` from `device-credentials.json`, set Wi-Fi and the server address, and upload. On the dashboard, add:
- a Switch on V0;
- a Selector on V1 (`0 = A`, `1 = B`);
- a Slider or Stepper on V2 (1–300);
- a Gauge on V3 and a Chart on the metric `measurement`.

| Example | Transport | Outputs A / B | Sensor |
|---|---|---|---|
| `ESP32_HTTP`, `ESP32_MQTT` | HTTPS / MQTT TLS | GPIO 17 / 16 | GPIO 34 (ADC1) |
| `ESP8266_HTTP`, `ESP8266_MQTT` | HTTPS / MQTT TLS | D1 / D2 | A0 |
| `ESP8266_Provisioning` | MQTT TLS, set up from a phone, optional OTA | D1 / D2 (D4 LED = status) | A0 |
| `ArduinoUno_Serial` | USB → gateway → HTTPS | 7 / 8 | A0 |

The outputs are active-LOW by default, which suits most relay modules (`OUTPUT_ACTIVE_LOW`). Set `MEASUREMENT_ENABLED = false` if nothing is wired to the analog pin. A floating input only produces noise.

## Server address and certificates

| Server setup | HTTP sketch `BASE_URL` | HTTP CA | MQTT `HOST`, port 8883 |
|---|---|---|---|
| Native Run/Install (`setup --domain`) | `https://your-domain:8000` | `data/certs/ca.crt` | your domain + `data/certs/ca.crt` |
| Docker + Caddy | `https://your-domain` | Caddy's public CA (e.g. ISRG Root X1) | your domain + `data/certs/ca.crt` |
| Local test, plain (`*_TLS 0`) | `http://SERVER_LAN_IP:8000` | – | needs `-EnablePlain` / `--plain`, port 1883 |

- Never use `localhost` on a board: it means the board itself.
- The certificate must contain the name or IP the board connects to. To add a LAN IP, run `python -m omnilink.certificates --host 192.168.1.50`, then restart the server and Mosquitto.
- The MQTT login (username and client ID = device ID, password = secret) is provisioned by the server automatically. Allow a few seconds after you create the device.
- Plain HTTP/MQTT sends the device secret unencrypted. Use it only on a private test network.

## Sketch pattern

```cpp
bool setPower(bool on) { digitalWrite(RELAY, on ? LOW : HIGH); return true; } // false = reject
void reportState() { omniLink.reportBool(0, relayOn); }                         // after every reconnect

void setup() {
  // Wi-Fi, NTP, TLS CA first
  omniLink.onBool(0, setPower);
  omniLink.onConnect(reportState);       // Uno: link.onSync(reportState)
  omniLink.begin(HOST, 8883, DEVICE_ID, DEVICE_SECRET);
}
void loop() { omniLink.loop(); }         // keep loop() non-blocking
```

- Handlers return `true` only after the action has been applied. The library then acknowledges the command and reports the applied value.
- Use `reportBool/Int/UInt/Float/String` for actual state. For a specific width, pass the type: `reportUInt(pin, omnilink::T_UINT8, v)`.
- Use `telemetryFloat/Int/UInt("metric", v)` for chart history, and `event(severity, "CODE", "detail")` for events.
- Report only values the hardware actually measured.

## Uno / Nano

1. Open `examples/ArduinoUno_Serial`, paste the device ID and secret into `DEVICE_ID` and `DEVICE_SECRET` at the top, and upload it. Don't use `Serial.print` for debugging: the USB port carries the protocol. The gateway does show any stray text it receives.
2. Close Arduino Serial Monitor, then run the gateway from the server folder. It reads the ID and secret from the board over USB:

```powershell
.venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM4 --url https://iot.example.com
```

- Anyone with USB access to the board can read its secret. To keep it off the board, leave both fields empty and add `--credentials device-credentials.json`.

- For a private HTTPS CA, add `--ca data/certs/ca.crt`.
- For a local plain server, use `--url http://localhost:8000`.
- On Linux, use `.venv/bin/python` and `/dev/ttyACM0`.
- The computer must stay on for the Uno to stay online.

## Scope and limits

- **Types:** BOOL, INT8/16/32, UINT8/16/32, FLOAT32 and STRING. 64-bit integers, FLOAT64, BYTES, JSON and TIMESTAMP pins are not supported.
- **Bindings:** up to 16 per ESP board and 8 per AVR board.
- **Restarts:** the duplicate-command record lives in RAM. After a board restarts, a command that was still pending can run again, so write handlers that set state rather than toggle or pulse it.
- **Not included:** channel creation (do that in the client), OTA distribution from the server, and native ONP.

Host tests: `pytest tests/test_arduino_library.py` in the server folder. They compile these sketches with g++ against stub Arduino headers and run them against a temporary server. See `VALIDATION.md`.

# OmniLink Arduino library 0.2

Install this folder as an Arduino library (ZIP: **Sketch → Include Library → Add .ZIP Library**). If upgrading from 0.1, remove the older `OmniLink` folder from your Arduino libraries directory before installing the 0.2 ZIP, so the IDE does not select duplicate copies. It provides one typed virtual-pin workflow for ESP32, ESP8266, and Arduino Uno-class boards.

## Supported connection paths

| Board | Connection | What runs on the board | What runs on the computer |
|---|---|---|---|
| ESP32 | HTTP/HTTPS or MQTT with TLS, default ports 443 / 8883 | OmniLink HTTP or MQTT library | Nothing |
| ESP8266 / NodeMCU ESP-12E | HTTP/HTTPS or MQTT with TLS, default ports 443 / 8883 | OmniLink HTTP or MQTT library | Nothing |
| Uno / Nano AVR | USB Serial JSON lines | Small OmniLinkSerial library | `arduino_uno_serial_gateway.py` uses HTTPS to reach the server |

The server stores virtual pins and values. Firmware maps a virtual pin to the physical GPIO or action for its particular board. The Uno path uses a USB-connected computer as its secure network gateway; the gateway holds the device credential, because the Uno has no network/TLS hardware.

## Install dependencies

The MQTT API uses `<OmniLink.h>` and `PubSubClient`. The HTTP API uses `<OmniLinkHttp.h>` and has matching typed pin callbacks and reports. AVR builds construct `OmniLink` with `Serial` and run the gateway on the connected computer.

In Arduino IDE Library Manager install:

1. **PubSubClient** by Nick O'Leary (ESP32 and ESP8266 MQTT).
2. **ArduinoJson 7** (MQTT JSON and Uno serial line parsing).
3. Install board support for **esp32 by Espressif Systems** or **esp8266 by ESP8266 Community** as appropriate.

The Arduino Uno serial transport does not use PubSubClient. Its PC gateway needs Python packages already listed in the OmniLink Server requirements: `httpx` and `pyserial`.

## Common setup

1. In the OmniLink client, create a device and allocate its channels under **Devices & pins**. Choose each channel's type and whether it is writable.
2. Copy the device ID and 64-character secret when OmniLink shows them. The secret is displayed once; keep it private.
3. Use the server's public DNS hostname on real hardware. `localhost` means the board itself.
4. Keep TLS enabled on public networks. For MQTT, paste the OmniLink device CA from `data/certs/ca.crt`. For HTTPS, trust the CA that issued the public HTTPS certificate (for a VPS, this is normally the public CA used by Caddy; it is not the private MQTT device CA). Keep certificate and hostname verification enabled.
5. Match the virtual channel number and data type in your sketch to the channel created on the server.

## ESP32 / ESP8266

Choose an MQTT sketch or HTTP sketch under `examples/ESP32_*` or `examples/ESP8266_*`. Set Wi-Fi, VPS hostname/URL, Device ID, secret, and the appropriate CA certificate. TLS is enabled by default. Each sketch has an explicit `*_TLS` switch; setting it to 0 selects plain transport for private-network testing only. The examples demonstrate V0 (boolean) controlling a master relay. The ESP32 example uses GPIO 17; the NodeMCU example uses D1/GPIO5. Adapt the pin and active level to your board and relay module.

For a public VPS using the native Run/Install setup:

- HTTP: use `BASE_URL="https://iot.your-domain.com:8000"` and paste `data/certs/ca.crt` into `ROOT_CA`.
- MQTT: use `HOST="iot.your-domain.com"`, port 8883, and the PEM contents of `data/certs/ca.crt`.
- Never set either host to `localhost`; the device would connect back to itself.
- Set the plain mode switch to 0 only when the selected service listener is deliberately exposed on a private network. Never send the device secret over public plain HTTP/MQTT.

If the server is behind the supplied Docker/Caddy deployment, use `https://iot.your-domain.com` (port 443) for HTTP and trust the public CA issuing Caddy's certificate. The MQTT endpoint and private MQTT CA remain the same.

The MQTT service may take a few seconds to provision a newly created device. Once connected, it publishes an initial state report and a status heartbeat. Configure NTP before connecting because command expiry is checked against server time and TLS needs a valid clock.

Typical sketch pattern:

```cpp
bool setRelay(bool on) {
  digitalWrite(RELAY_PIN, on ? RELAY_ON_LEVEL : RELAY_OFF_LEVEL);
  return true; // return false if this command could not be applied
}

void setup() {
  // Set Wi-Fi, NTP, and verified TLS CA first.
  omniLink.onBool(0, setRelay); // dashboard V0 -> this board's relay action
  omniLink.begin(HOST, 8883, DEVICE_ID, DEVICE_SECRET, "my-firmware-1");
}

void loop() {
  omniLink.loop(); // MQTT reconnect, commands, acknowledgments and heartbeats
}
```

Write handlers return `true` only after applying a command; return `false` to reject an action. Use `reportBool`, `reportInt`, `reportUInt`, `reportFloat`, and `reportString` for actual device state. Use `telemetryFloat("temperature", celsius)` for a historical metric that charts can display. Do not fabricate sensor readings; report only measurements the hardware actually supplies.

## Arduino Uno / Nano over USB Serial

The Uno sketch uses `OmniLinkSerial` to exchange short JSON lines over USB. A computer running the gateway performs the HTTPS/TLS connection and command polling. This works with a Uno or Nano without an Ethernet/Wi-Fi shield.

1. Upload `examples/ArduinoUno_Serial/ArduinoUno_Serial.ino` after setting the physical relay GPIO.
2. On the computer, save `device-credentials.json` outside the server source folder (for example in your user Documents folder) with the values copied from OmniLink:

```json
{"id":"dev_YOUR_DEVICE_ID","secret":"64_CHARACTER_DEVICE_SECRET"}
```

3. From the server project folder, run the gateway using its virtual environment (Windows example):

```powershell
.venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM4 --url https://iot.example.com --credentials "C:\Users\YOUR_NAME\Documents\device-credentials.json"
```

For a public VPS use `--url https://iot.your-domain.com`. For a local/private HTTP server use `--url http://SERVER_LAN_IP:8000`; for HTTPS with a private CA add `--ca path/to/https-ca.crt`. On Linux use `.venv/bin/python` and a port such as `/dev/ttyACM0`. Use the port shown in Device Manager. Close Arduino Serial Monitor before starting the gateway, because only one program can own the COM port. The Uno code runs at 115200 baud.

The gateway validates reports against the device's server-side channel schema. Its computer must remain powered and connected for the Uno to remain online and receive dashboard commands.

## Current scope

Supported channel data types are BOOL, INT8/16/32, UINT8/16/32, FLOAT32, and STRING. FLOAT64, 64-bit integers, BYTES, JSON, and TIMESTAMP are not supported. The ESP HTTP and MQTT transports implement commands, scalar reports, telemetry, and events. The Uno gateway forwards scalar reports, telemetry, and events over HTTPS. Each bound channel keeps an in-memory last-command record (up to 16 ESP or 8 AVR bindings), which protects retries during a boot. The record is not persisted across device restarts, so use idempotent set-state handlers. The library does not perform channel creation, OTA firmware updates, server-side pin-to-GPIO assignment, or automatic sensor discovery. Add or edit channel definitions in the OmniLink client; bind them to GPIOs and hardware in the sketch.

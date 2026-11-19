# ESP devices on a VPS

## Native Run/Install deployment (no Docker)

Point a DNS name (for example `iot.example.com`) at the VPS. On Debian/Ubuntu install Python 3.12 and run from the extracted server folder:

```sh
sh setup.sh --domain iot.example.com
sudo sh tools/setup_mosquitto_vps.sh
sh run.sh
```

The app serves HTTPS on port 8000 and ONP TLS on 7443. Mosquitto runs as a system service with MQTT TLS on 8883 and its server/control port 1884 bound to loopback. Open inbound TCP 8000, 7443, and 8883 in the VPS firewall/security group. The setup generates a private CA, so install `data/certs/ca.crt` in the browser/client trust store or embed it in the device sketch. Keep `.env`, the database, `ca.key`, and `server.key` private. `sh run.sh` keeps the app in the foreground; use your normal process supervisor when you want it to start after reboot.

For Windows Run/Install, initialize with `setup.bat --domain iot.example.com`, then in Administrator PowerShell run `tools\setup_mosquitto_windows.ps1`; start the broker in a second window with `tools\run_mosquitto_windows.ps1`, and start the app with `run.bat`. Open inbound TCP 8000, 7443, and 8883 as needed.

## Optional Docker deployment

Point a DNS name (for example `iot.example.com`) at the VPS. Install Docker Engine and Docker Compose, then run from the extracted server folder:

```sh
./deploy-vps.sh iot.example.com
```

The command initializes a new server if `.env` is missing, builds the app, and starts PostgreSQL, Mosquitto, OmniLink, and Caddy. Caddy obtains the public HTTPS certificate. The deployment exposes web HTTPS on 443, ONP TLS on 7443, and MQTT TLS on 8883. Mosquitto is installed from its official container image by Compose. On a firewall/security group allow inbound TCP 80, 443, 7443, and 8883. Do not publish PostgreSQL or the broker's internal service/control listener.

Keep the server's `.env`, database volume, and `data/` directory backed up and private. Device code receives only a device ID, its device secret, and the relevant trust certificate. Do not copy `.env`, `ca.key`, or `server.key` to a device.

## Optional plain MQTT for private testing

```sh
./deploy-vps.sh iot.example.com --plain-mqtt
```

This opens TCP 1883 without transport encryption. It is suitable only for an isolated/private network. The device secret is visible to anyone who can observe that traffic. Do not use this flag on a public VPS. Default deployment has MQTT TLS on 8883 and omits the host port mapping for 1883.

## ESP32 and ESP8266 transports

Install the OmniLink Arduino library and its dependencies (`PubSubClient` and `ArduinoJson`). Select the HTTP or MQTT example folder for the board. The examples default to verified TLS. Set `HOST` or `BASE_URL` to the public DNS name, never `localhost`.

| Sketch | VPS endpoint | TLS trust file |
|---|---|---|
| `ESP32_HTTP` / `ESP8266_HTTP` native Run/Install | `https://iot.example.com:8000` | `data/certs/ca.crt` |
| `ESP32_MQTT` / `ESP8266_MQTT` | `iot.example.com:8883` | `data/certs/ca.crt` from the server package |

For native HTTPS and MQTT, the generated `data/certs/ca.crt` signs both device server certificates. If using Docker/Caddy, HTTP is instead `https://iot.example.com` on port 443 and the HTTPS certificate uses a public CA; keep the private CA for MQTT. In all cases certificate checks validate the server name. Synchronize device time with NTP before the TLS handshake.

To select plain protocol for a private test, set `OMNILINK_HTTP_TLS=false` in `.env` and restart the app, then set `OMNILINK_HTTP_TLS` to `0` in the HTTP sketch. For MQTT, rerun the native Mosquitto setup with `--plain` (Linux) or `-EnablePlain` (Windows), and set `OMNILINK_MQTT_TLS` to `0` in the sketch. Never use plain mode on the public Internet.

## HTTP API configuration

With the native VPS setup using `--domain`, the HTTP server binds to `0.0.0.0:8000` and speaks HTTPS using the generated certificate. Without `--domain`, it stays on loopback and plain HTTP for local development. With the optional Compose deployment, Caddy handles browser/device HTTPS on port 443 and proxies over the private Compose network. Do not bind plain HTTP directly to a public interface.

## Uno and Nano

Bare Uno/Nano boards do not have Wi-Fi or Ethernet. Connect over USB to a computer or gateway that has Internet access and run `examples/arduino_uno_serial_gateway.py` using the VPS HTTPS URL. Add a compatible network shield or use an ESP board for a direct connection.

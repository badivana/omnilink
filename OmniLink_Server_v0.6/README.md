# OmniLink Server v0.6

A general-purpose IoT server with authentication, typed virtual channels, durable commands, telemetry, automation, HTTP, ONP TLS, binary WebSocket devices, MQTT, and a Serial bridge. Server administration is at `/`. The widget dashboard is a **separate package**, OmniLink Web Client v0.6, mounted optionally at `/client/`. A native app can be built later using the same API.

No aquarium channels, manual/AUTO hardware modes, units, or actuator relationships are built into device creation. Existing configured devices and saved layouts are preserved. Optional domain examples live under `examples/`.

## Arduino devices

The **OmniLink Arduino library 0.3** is a separate package, like the web client. Keep its folder next to the server folder:

```
OmniLink_Server_v0.6/
OmniLink_WebClient_v0.6/
OmniLink_Arduino_v0.3/     <- import this folder in the Arduino IDE
```

It supports:

| Board | How it connects | Example sketch |
|---|---|---|
| ESP32 / ESP8266 | Wi-Fi, directly to the server over HTTP(S) or MQTT TLS | `ESP32_HTTP`, `ESP32_MQTT`, `ESP8266_HTTP`, `ESP8266_MQTT` |
| ESP8266 (NodeMCU) | Wi-Fi set up from a phone hotspot, optional OTA updates, MQTT TLS | `ESP8266_Provisioning` |
| Arduino Uno / Nano | USB cable to a PC that runs the OmniLink **serial gateway** | `ArduinoUno_Serial` |

ESP boards talk to the server themselves. An Uno or Nano has no network hardware, so it cannot use Wi-Fi or MQTT; it needs the gateway program running on a PC it is plugged into (see [Uno / Nano over USB](#uno--nano-over-usb)). MQTT devices also need the Mosquitto broker running (see [Native Mosquitto setup](#native-mosquitto-setup-runinstall-no-docker)).

### Virtual pins

The server stores **virtual pins** (V0, V1, …); each sketch maps them to the board's real GPIOs. Two rules matter:

- **Pin numbers are unique per account.** If V0 belongs to one device, no other device in that account can use V0. Give every board its own numbers (for example V0–V7 for an ESP8266, V10–V13 for a Nano).
- **The pin type on the server must match the sketch.** A sketch handler `onBool` needs a BOOL pin, `onUInt` an unsigned integer pin (UINT8/16/32), `onInt` a signed one, `onFloat` FLOAT32. A mismatch makes the board reject commands with error 400. A pin's type cannot change after it has been used; delete it and add it again instead.

The examples use these pins, which `python -m examples.create_demo` creates in a fresh account:

| Pin | Name | Type | Writable | Range |
|---|---|---|---|---|
| V0 | Power | BOOL | yes | |
| V1 | Output selection | UINT8 | yes | 0–1 |
| V2 | Setpoint (measurement interval, seconds) | UINT32 | yes | 1–300 |
| V3 | Measurement | FLOAT32 | no | 0–100 |

If you use other numbers, change the `PIN_...` constants at the top of the sketch to match **Devices & pins**.

### Install the library in the Arduino IDE

The sketches start with `#include <OmniLink.h>`, so the library must be installed or compiling fails with `OmniLink.h: No such file or directory`.

1. Close **every** Arduino IDE window. Delete any older copy in `Documents\Arduino\libraries` (a folder named `OmniLink` or `OmniLink_Arduino_v0.3`); two copies conflict.
2. Open the IDE and choose **Sketch → Include Library → Add .ZIP Library…**.
   - **Arduino IDE 1.8:** select the `OmniLink_Arduino_v0.3` **folder** next to the server folder. No ZIP needed.
   - **Arduino IDE 2.x** (only accepts ZIP files): first build the ZIP in the server folder, then select it. It is written next to the server folder as `OmniLink_Arduino_v0.3.zip`:

     ```bat
     .venv\Scripts\python tools\build_arduino_library.py
     ```

   Do not just copy a ZIP into the `libraries` folder; the IDE ignores it there.
3. Open the example under **File → Examples → Examples from Custom Libraries → OmniLink**.

Also install **ArduinoJson 7** (and **PubSubClient** and **WiFiManager** for the MQTT/ESP8266 sketches) from **Tools → Manage Libraries**. Repeat steps 1–2 whenever the library is updated, then restart the IDE: it only rescans libraries when it starts.

### Uno / Nano over USB

How it works:

```
Nano (sketch with DEVICE_ID / DEVICE_SECRET) --USB--> serial gateway on the PC --HTTP(S)--> OmniLink server
```

The device ID and secret are stored in the sketch. When the gateway starts it asks the board for them over USB, signs in to the server as that device, and then passes commands to the board and readings back. The PC must stay on with the gateway running.

**First-time setup**

1. In the web client, open **Devices & pins → + Device**, create the device and copy its **ID** and **secret**.
2. Use **+ Pin** on that device to add the pins the sketch uses, with matching types (see [Virtual pins](#virtual-pins)).
3. Open **File → Examples → OmniLink → ArduinoUno_Serial** and fill in the `[CHANGE]` block at the top:

   ```cpp
   const char DEVICE_ID[]     = "dev_...";     // from Devices & pins
   const char DEVICE_SECRET[] = "...";         // 64 hex characters
   ```

   Set the `PIN_...` constants to your pin numbers. Physical wiring: an LED/relay on **D7** (output A) and **D8** (output B), a sensor on **A0**. Outputs are active LOW by default (`OUTPUT_ACTIVE_LOW = true`, LED from D7 through a resistor to 5V); set it to `false` if the LED goes from D7 to GND.
4. Select **Tools → Board → Arduino Nano** (most clones also need **Processor → ATmega328P (Old Bootloader)**) and the board's COM port from Device Manager, then upload.
5. Close the Serial Monitor and start the gateway (below).

**Run the gateway** (recommended: in its own window, so the server never has to stop). Open a second terminal in the server folder and run, replacing `COM7` with your port:

```bat
.venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM7 --url http://127.0.0.1:8000
```

Keep that window open. It prints `Connected; N configured pins: …` when the board is online. Start it again by hand after closing the window or restarting the PC. For a server on another machine, use that server's URL (HTTPS for anything outside a private test network).

**Upload new code without stopping the server.** Only one program can hold a COM port, so the gateway must let go of it during an upload:

1. Press **Ctrl+C** in the gateway window.
2. Upload from the Arduino IDE.
3. Press **↑** then **Enter** in the gateway window to start it again.

The board resets when the gateway connects, so its outputs briefly return to their power-on state.

**One command for everything (Windows).** Add `OMNILINK_SERIAL_GATEWAY=COM7` (your board's port) to `.env`. `run.bat` then opens Mosquitto and the gateway in their own windows ("Mosquitto", "OmniLink gateway COM7") and starts the server in its window. Windows that are already open are reused, so running `run.bat` again is safe. Uploading works as above: Ctrl+C in the gateway window, upload, then ↑ Enter in that window. It supports one board; start more gateways by hand. Leave the setting empty to start the gateway yourself.

**Keeping the secret off the board.** Leave `DEVICE_ID` and `DEVICE_SECRET` empty in the sketch and pass a credentials file to the gateway instead: `--credentials "C:\Users\YOUR_NAME\Documents\device-credentials.json"` containing `{"id":"dev_...","secret":"..."}`. Otherwise anyone with USB access to the board can read its secret.

### Arduino troubleshooting

| Symptom | Cause and fix |
|---|---|
| `OmniLink.h: No such file or directory` | The library is not installed, or is nested one folder too deep (`libraries\OmniLink\OmniLink_Arduino_v0.3\src`). Reinstall it as described above. |
| OmniLink is missing from **File → Examples** | The IDE was open during installation; close all IDE windows and reopen. Arduino IDE 1.8 also skips libraries without a `url=` line in `library.properties` (fixed in the current ZIP). |
| You still see the old sketch without `DEVICE_ID` | An older library copy is installed. Delete it from `Documents\Arduino\libraries` and add the current library again. |
| `ser_open(): can't open device "\\.\COM6"` on upload | Wrong port: the board is on another COM port. Check Device Manager (a Nano clone usually shows as `USB-SERIAL CH340 (COMx)`). |
| Upload or gateway says `Access is denied` for the COM port | Another program holds the port: Serial Monitor/Plotter, the gateway, or the server's auto-started gateway. Close it, then retry. |
| Gateway says the board has no device ID/secret | Fill in `DEVICE_ID` and `DEVICE_SECRET` in the sketch and upload again. |
| Gateway says the board did not answer with its device ID | The board runs an older sketch or library. Install the current library ZIP, then upload `ArduinoUno_Serial` again. |
| Commands show **rejected** with error 400 | The server pin's type does not match the sketch handler (for example a BOOL pin where the sketch expects UINT8). |
| Commands show **rejected** with error 404 | The sketch has no handler for that pin number. Match the `PIN_...` constants to the server pins. |
| Gateway prints `Ignoring report for Vn: not configured` | That pin does not exist on this device (or belongs to another device). Add it under **Devices & pins**, or change the sketch's pin numbers. |
| Pin cannot be added: already allocated | Another device in the account owns that number. Choose a free number. |

## New in v0.6

The server manager can remove an account user and revoke their sessions. The active manager and an account's last enabled administrator are protected; the user's devices, pins, dashboards and flows stay with the account. The client also includes a 27-widget usage guide. Flow editors now save a verified mxGraphModel visual document separately from the v0.5-compatible executable graph, so saved flows remain readable if the server is rolled back to v0.5.

## New installation on Windows

Install Python 3.12 with the Windows `py` launcher. Extract the ZIP, open Command Prompt in `OmniLink_Server_v0.6`, then run:

```bat
setup.bat
run.bat
```

Setup asks you to create your own OmniLink administrator email/password (at least 12 characters). Open **http://localhost:8000/** and sign in. The server window stays open; Ctrl+C stops it.

**"Origin rejected" when signing in:** the browser must open exactly the address in `OMNILINK_PUBLIC_URL` in `.env`. `localhost`, `127.0.0.1` and the PC's LAN IP all count as different addresses. To use the dashboard from other devices on your network, set `OMNILINK_PUBLIC_URL=http://<this PC's LAN IP>:8000` and `OMNILINK_HTTP_HOST=0.0.0.0`, then restart `run.bat` (the server reads `.env` only at start). If your router gives the PC a new IP address, update the setting and restart again; reserving the address in the router avoids this.

For a native public VPS, initialize with a DNS name instead: `setup.bat --domain iot.your-domain.com` (Windows) or `sh setup.sh --domain iot.your-domain.com` (Debian/Ubuntu). This enables HTTPS directly on port 8000 using the generated private device CA. Keep the generated `data/certs/ca.crt` and install it in devices and browsers that need to trust the server.

Attach the client below, open `/client/`, and choose **Create an account**. Each new account owns its devices, dashboards, flows and one virtual-pin pool. Under **Devices & pins → + Device**, create a device and copy its ID/secret. Then use **+ Pin** to allocate a free pin and choose its type, bounds and writable setting. The default pool is V0–V254; the same number cannot belong to two devices in one account. Different accounts have independent pools. Channel numbers have no aquarium-specific meaning.

## Upgrade an existing installation

Follow [docs/UPGRADE_v0.6.md](docs/UPGRADE_v0.6.md). Stop the server, back up `.env` and the database/data, then replace the source and update dependencies. **Do not run setup again.** Keep the existing encryption key and certificates. The first startup detects duplicate v0.4 pin assignments and shows them in the client without renumbering firmware mappings. Update both server and client together.

## Attach the separately packaged web client

Extract `OmniLink_WebClient_v0.6.zip` next to your server. From the client folder run:

```bat
py -3 install.py --server-dir "D:\Projects\OmniLink_Server_v0.4"
```

Restart the server. Open **http://localhost:8000/client/** for widgets, and **http://localhost:8000/** for administration. The installer sets `OMNILINK_CLIENT_DIR` to the external client folder in the existing `.env`; no client files are bundled into the server. New users self-register in the client. Account owners create devices and pins and manage dashboards/flows. Existing shared-workspace roles remain: operators can control and edit layouts/flows; viewers are read-only. The bootstrap manager at `/` controls signups, account enablement, limits and named integrations. Existing v0.4 workspace users continue sharing their original account.

For Docker, put the client assets in this server's `web-client/`, set `OMNILINK_CLIENT_DIR=/web-client` in `.env`, and rebuild the application service. The supplied Compose mount serves that directory read-only. See the client README for details. The native app is not implemented in this release.

## Connect your existing device on the same computer

The **web client** is the user's control interface. The **device client** is firmware or a simulator that applies commands and reports state. For local testing, keep the server running and open a second Command Prompt in its existing folder. Save your existing device's credentials as `device-credentials.json`:

```json
{"id":"dev_YOUR_DEVICE_ID","secret":"YOUR_64_CHARACTER_HEX_SECRET"}
```

Then run:

```bat
.venv\Scripts\python -m examples.simulator --transport http --url http://localhost:8000 --credentials device-credentials.json
```

This general simulator discovers the device's configured channels, reports valid neutral initial values, polls commands, applies them in simulated state, and confirms them. It does not control physical hardware or generate sensor readings by default. A channel-less device stays online without invalid reports. Add its channels and restart the simulator before testing controls. Reuse your existing device; creating another device is unnecessary.

The simulator uses a per-device ledger under `data/`; it ignores an older shared ledger or a ledger with a different device/schema. Neutral startup values do not pretend that queued desired commands were already applied. Read-only simulation values remain fixed unless you explicitly extend the example.

The old aquarium-only simulator could return 400 when reporting V0–V6 to a general device. The new client prints the server's actual rejection detail and offending channel, rather than only `raise_for_status()`. Authentication, channel types, and range validation remain enforced.

For a newly registered generic demo with Power/Output selection/Setpoint/Measurement channels:

```bat
.venv\Scripts\python -m examples.create_demo
.venv\Scripts\python -m examples.simulator
```

For ONP TLS or MQTT TLS, pass `--transport onp` or `--transport mqtt`, `--host`, `--port`, and `--ca`. The CLI discovers the schema via the HTTP(S) server specified by `--url` before connecting; alternatively supply `--schema channels.json`. Use `--http-ca` for a private HTTPS CA. Default transport is now HTTP. Direct Python use of `Simulator.native()` or `.mqtt()` requires a configured schema. Aquarium simulation is explicitly available through `examples.create_demo --aquarium` and `examples.aquarium_simulator`; see its example README.

## Start on Linux or macOS

Install Python 3.12 and venv support, extract the package, and enter its folder:

```sh
sh setup.sh
sh run.sh
```

To register and run a simulator in a second terminal:

```sh
.venv/bin/python -m examples.create_demo
.venv/bin/python -m examples.simulator
```

## Deploy with Docker

Install Docker Engine with the Compose plugin, or Docker Desktop on Windows. For a local Docker installation, initialize an extracted copy without an existing `.env`:

```bat
setup.bat --docker
docker compose up -d --build
```

Open **http://localhost**. The stack runs OmniLink, PostgreSQL, Mosquitto, and Caddy. For Linux use `sh setup.sh --docker` instead of `setup.bat --docker`.

For a public VPS, point a DNS name at the VPS and copy the package onto it. Install Docker Engine and its Compose plugin, then run:

```sh
./deploy-vps.sh iot.your-domain.com
```

Open **https://iot.your-domain.com**. Caddy obtains and renews the web certificate. Allow inbound TCP 80 and 443 for the web console, 7443 for ONP devices, and 8883 for MQTT devices. PostgreSQL and the internal MQTT control port are not published to the host. Docker Compose downloads and runs Mosquitto as part of this setup. MQTT TLS is enabled by default.

The plain MQTT option is available for isolated testing:

```sh
./deploy-vps.sh iot.your-domain.com --plain-mqtt
```

This additionally publishes TCP 1883 without TLS. It exposes each device secret on the network, so do not enable it on an Internet-facing VPS. For normal deployment leave that flag off and use port 8883 with certificate verification.

To redeploy after editing an existing installation, preserve its `.env` and `data/` directory and run `docker compose up -d --build`; do not run setup again. The HTTP Arduino examples use the Caddy HTTPS URL on port 443. The MQTT Arduino examples use the MQTT TLS listener on port 8883. Both use the public DNS hostname, never `localhost`.

ONP and MQTT use the separate private device CA generated by setup. Install `data/certs/ca.crt` in your client, or paste it into the ESP32 example. Connect using the hostname passed to setup. Device clients verify both the CA and the hostname. Never distribute `ca.key`, `server.key`, or `.env` to devices.

Run a local simulator against the deployed server:

```sh
.venv/bin/python -m examples.create_demo --url https://iot.your-domain.com
.venv/bin/python -m examples.simulator --host iot.your-domain.com --ca path/to/copied-ca.crt
```

For MQTT:

```sh
.venv/bin/python -m examples.simulator --transport mqtt --host iot.your-domain.com --ca path/to/copied-ca.crt
```

## Native Mosquitto setup (Run/Install, no Docker)

Run the server setup with the public DNS name first. On Windows, open an Administrator PowerShell in the server folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_mosquitto_windows.ps1
```

After that, `run.bat` starts the broker for you: it opens Mosquitto in its own window when it is set up and not already running, then starts the server. To start the broker by hand instead:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_mosquitto_windows.ps1
```

Restart `run.bat` after enabling MQTT. For Debian/Ubuntu VPS, run:

```sh
sh setup.sh --domain iot.your-domain.com
sudo sh tools/setup_mosquitto_vps.sh
sh run.sh
```

The native setup binds the app's HTTPS API to TCP 8000, ONP TLS to 7443, MQTT TLS to 8883, and keeps Mosquitto's internal server/control connection on loopback port 1884. Open only the needed public ports in the VPS firewall/security group. Native Mosquitto starts as a system service on Linux; on Windows, keep its "Mosquitto" window (opened by `run.bat`) open. For a no-TLS MQTT test on a private network only, add `-EnablePlain` on Windows or `--plain` on Linux. That exposes port 1883 and device secrets, so never enable it on a public VPS.

Use a VPS or another host that supports persistent processes and raw TCP ports. Static hosting alone cannot run this server. The provided Compose configuration is for **one OmniLink application instance**; do not increase Uvicorn workers or scale the application service horizontally.

## Included functionality

| Area | Implemented behavior |
|---|---|
| Accounts | Administrator, operator, and viewer roles; tenant-scoped device access; Argon2 passwords; hashed, expiring sessions; CSRF protection |
| Device identity | Unique IDs, one-time 32-byte secrets, encrypted secret storage, disabling, secret rotation |
| State | Account-wide unique pins, default V0–V254 (manager configurable up to 1024); separate desired/reported values and revisions; read-only channels and numeric limits |
| Commands | Desired state and command outbox committed together; stable command keys; retries; TTL expiry; supersession; accepted/applied/rejected outcomes |
| Ingestion | Typed telemetry, events, per-boot sequence deduplication, stale-boot and out-of-order report protection |
| Automation | Edge-triggered threshold rules, cooldowns, interval schedules, alternating cycles, timezone-aware daily schedules, timed manual override |
| Transports | Compact ONP over TLS and binary WebSocket, HTTP polling, MQTT through Mosquitto Dynamic Security, COBS/CRC Serial bridge |
| Server administration | Signup policy, account enablement, pin/device/dashboard/flow limits and integrations |
| Client API | Saved dashboard layouts and typed commands for the separately packaged web client and future app |
| Web client (separate ZIP) | 27 widgets, multi-device dashboards, device/pin management, history, alerts, maps, floor plans, process views and visual flows |
| Client installation | Optional external static client at `/client/`, with its own PWA assets |
| Deployment | SQLite local mode; PostgreSQL/Mosquitto/Caddy Docker stack; persistent database/broker volumes; health endpoints |

This release does not implement OTA distribution, RPC extensions, local schedule downloads, a separately packaged native mobile app, or old Blynk app/firmware compatibility. ONP negotiates **compact codec 0**; MQTT and HTTP use JSON. CBOR and ONP JSON frames are not negotiated. No Blynk server source is included in this implementation.

## Automation behavior

The visual flow editor supports triggers, conditions, branches, commands, waits, calculations, variables, alerts, named integrations and nested flows. See [docs/FLOWS.md](docs/FLOWS.md) for execution semantics, tests and limits. Saved/published flow references protect pins from deletion.

Rules fire on a false-to-true threshold crossing and then respect their cooldown. Duplicated structured telemetry does not trigger a rule twice. Writes keep automation active by default (`manual_s=0`); an optional positive duration pauses configured rules/schedules. Entering manual mode supersedes queued automation commands. Resuming automation allows future crossings and schedule occurrences; it does not immediately replay skipped actions.

Interval schedules first fire after their interval. A cycle first sends its first value, holds it for `interval_s`, sends the alternate value, then holds it for `alternate_interval_s`. Schedules preserve their phase in the database. After downtime the scheduler skips occurrences more than 30 seconds late and avoids a catch-up burst. Daily schedules use IANA timezones and Monday=0 through Sunday=6. A nonexistent daylight-saving time is skipped; a repeated hour fires once.

An acknowledgment of **applied** changes the command outcome. The channel's reported value changes only on a device report. This distinction is intentional: a command confirmation and a fresh measurement are separate evidence.

## API and MQTT

Interactive API documentation is at `/docs`; the JSON schema is at `/openapi.json`. See [docs/API.md](docs/API.md) for authentication and transport payloads. Native ONP wire details are in [docs/ONP.md](docs/ONP.md).

MQTT credentials: username = device ID, password = its 64-character hex secret, **client ID = device ID**. The service provisions exact permissions automatically; allow a few seconds after creating, disabling, or rotating a device. The dashboard shows whether MQTT provisioning has completed through the device-list API.

Device topic root: `omnilink/v1/dev/DEVICE_ID/`. Devices may publish to `telemetry`, `state`, `event`, `ack`, and `status`, and subscribe only to `cmd` and `config`. Devices cannot publish commands, subscribe to other devices, use wildcard subscriptions, or access broker administration. Commands use QoS 1 and are never retained. Retained inbound application packets are ignored to avoid replaying state or automation on service restart.

SDK-free sensors can publish flat telemetry such as `{"temperature":26.5,"humidity":58}`. This format has no boot ID or sequence, so no packet deduplication is claimed. Use the structured form for deduplication and typed values. A broker status packet is advisory; the console considers a device online if an accepted message arrived within 90 seconds.

## Serial bridge

Each bridge maps one serial child to one ONP TLS connection. The child owns its device secret and performs the handshake; the bridge holds no credentials. For Windows:

```bat
.venv\Scripts\python -m examples.serial_bridge --serial COM3 --host localhost --ca data/certs/ca.crt
```

For Linux use `.venv/bin/python` and `--serial /dev/ttyUSB0`. The default serial receive limit is 256 decoded bytes. The child must advertise a matching or smaller frame limit. Bad COBS/CRC packets are discarded at the next delimiter. Restart the bridge after a serial or upstream disconnect. This release does not multiplex multiple children over a single serial bus.

## Operations and recovery

```sh
docker compose logs --tail=100 omnilink mosquitto
docker compose restart omnilink
docker compose down
```

`down` preserves named data volumes. Keep `.env`, the device CA files, and the database backup together. Device secrets cannot be decrypted without `OMNILINK_ENCRYPTION_KEY`. Telemetry, events, and sequence receipts are kept for 30 days by default; completed flows and acknowledged alerts use the same retention window. Commands and desired/reported state are retained until a pin is released/moved or its device deleted. Sequence deduplication is bounded by that receipt retention window.

After the first successful administrator login, you can clear `OMNILINK_BOOTSTRAP_PASSWORD` in `.env`; the existing account remains in the database. To reset a password locally:

```sh
.venv/bin/python -m omnilink.admin reset-password --email you@example.com
```

For Docker use `docker compose exec -it omnilink python -m omnilink.admin reset-password --email you@example.com`. To create another isolated workspace, replace `reset-password` with `create-tenant` and optionally add `--name`.

Back up PostgreSQL from the Docker stack:

```sh
mkdir -p backups
docker compose exec -T postgres pg_dump -U omnilink omnilink > backups/omnilink.sql
```

Restore into an empty installation with the same encryption key:

```sh
docker compose stop omnilink
docker compose exec -T postgres psql -U omnilink -d omnilink < backups/omnilink.sql
docker compose start omnilink
```

For a local SQLite installation, stop the server before copying `data/omnilink.db`. The service will reconstruct the Mosquitto device accounts from its database on restart. Preserve the original MQTT admin password with the broker volume.

Device leaf certificates last one year. Renew them while preserving the CA:

```sh
.venv/bin/python -m omnilink.certificates --host iot.your-domain.com
docker compose restart omnilink mosquitto
```

For native local mode, restart `run.bat`/`run.sh` after renewal. Add `--host` for every hostname or IP devices will connect to. Caddy renews the public web certificate independently.

## Tests and release limits

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

Use `.venv/bin/python` on Linux. MQTT integration tests require installed `mosquitto`, `mosquitto_ctrl`, and the Dynamic Security plugin. You can set `MOSQUITTO_BIN`, `MOSQUITTO_CTRL`, and `MOSQUITTO_PLUGIN` if they are outside normal paths. The Serial integration test uses a POSIX pseudo-terminal and skips on Windows.

Optional browser verification (requires Node.js and Playwright):

```sh
npm install --no-save playwright
npx playwright install chromium
.venv/bin/python tools/browser_qa.py
```

On Windows use `.venv\Scripts\python tools\browser_qa.py`. This starts a temporary server/database and simulator, exercises the actual dashboard, and writes screenshots in the system temporary folder. It does not use your deployed server or database. `--output PATH` selects the screenshot directory. The v0.6 browser test covers management, multi-device widgets, deletion/release, location permissions, flow editing/execution and alerts. Physical browser peripherals require device-specific testing.

Read [VALIDATION.md](VALIDATION.md) for the tests actually run and the remaining deployment/hardware checks. This runnable release is suitable for pilot use after testing your devices. New tables are initialized automatically; changes to existing columns or stored data need an explicit migration. It has not been capacity-tested or assessed as a safety-critical control system.

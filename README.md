# OmniLink — Private, Self-Hosted IoT Platform

OmniLink is a complete, self-hosted, private Internet of Things (IoT) ecosystem engineered for speed, privacy, and full hardware ownership. It operates entirely on your local network (LAN) or private virtual server (VPS) without reliance on external cloud services or subscriptions.

The platform provides a **Python backend**, an **Eclipse Mosquitto MQTT broker** with automated dynamic role-based security, a **responsive Web dashboard** featuring real-time WebSockets and 27 modular widgets, a **visual automation flow editor**, and **C++ Arduino firmware** with Captive Portal Wi-Fi configuration and browser-based Over-The-Air (OTA) `.bin` firmware updates.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Project Directory Structure](#project-directory-structure)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
  - [Step 1: Setup OmniLink Server](#step-1-setup-omnilink-server)
  - [Step 2: Setup Mosquitto MQTT Broker](#step-2-setup-mosquitto-mqtt-broker)
  - [Step 3: Attach the Web Client](#step-3-attach-the-web-client)
  - [Step 4: Trust the Local Root CA](#step-4-trust-the-local-root-ca)
  - [Step 5: Run the Services](#step-5-run-the-services)
- [Hardware Quickstart (ESP8266 / NodeMCU)](#hardware-quickstart-esp8266--nodemcu)
  - [1. Register Device in Dashboard](#1-register-device-in-dashboard)
  - [2. Allocate Virtual Pins](#2-allocate-virtual-pins)
  - [3. Download & Flash the Sketch](#3-download--flash-the-sketch)
  - [4. Wi-Fi Setup (Direct or Captive Portal)](#4-wi-fi-setup-direct-or-captive-portal)
  - [5. Over-The-Air (OTA) Wireless Updates](#5-over-the-air-ota-wireless-updates)
- [Hardware Quickstart (Arduino Nano / Uno over USB)](#hardware-quickstart-arduino-nano--uno-over-usb)
- [Network IP Change Workflow](#network-ip-change-workflow)
- [Virtual Pin Schema](#virtual-pin-schema)
- [Troubleshooting & Diagnostics](#troubleshooting--diagnostics)
- [Security Guidelines](#security-guidelines)

---

## System Architecture

```
+-------------------------------------------------------------------------+
|                              USER DEVICES                               |
|   Desktop Browser / Mobile Phone (Web Client: https://<HOST>:8000/client) |
+------------------------------------+------------------------------------+
                                     |
                                     | HTTPS (Port 8000) & WSS (/ws/live)
                                     v
+-------------------------------------------------------------------------+
|                         OMNILINK BACKEND SERVER                         |
|  - FastAPI / Starlette ASGI Engine (Uvicorn)                            |
|  - Local Private Root CA Certificate Authority                          |
|  - Authentication, User Sessions, Device Ledgers & Flow Automations    |
|  - SQLite (WAL Mode) / PostgreSQL Database                              |
+-------------------+--------------------------------+--------------------+
                    |                                |                  ^
                    | Internal Sync (Port 1884)      | ONP TLS (7443)   | HTTP(S) device API (Port 8000)
                    v                                v                  |
+------------------------------------+   +-------------------+  +-------+----------------+
|      ECLIPSE MOSQUITTO BROKER      |   | NATIVE TLS (ONP)  |  | SERIAL GATEWAY (on PC) |
|  - Dynamic Security Plugin (RBAC)  |   |    (optional)     |  | arduino_uno_serial_    |
|  - MQTTS TLS 1.2/1.3 (Port 8883)   |   +-------------------+  | gateway.py             |
|  - Per-device ACLs & isolated roots|                          +-------+----------------+
+-------------------+----------------+                                  | USB serial
                    |                                                   |
                    | MQTTS over TLS (Port 8883)                        |
                    v                                                   v
+--------------------------------------------+   +------------------------------------+
|        Wi-Fi BOARDS (ESP8266 / ESP32)      |   |      USB BOARDS (Arduino Nano/Uno) |
|  - BearSSL Secure Client + PubSubClient    |   |  - No network hardware             |
|  - WiFiManager Captive Portal              |   |  - Device ID/secret in the sketch, |
|    (`OmniLink-Setup` AP)                   |   |    read by the gateway over USB    |
|  - LittleFS Flash Storage (/config.json)   |   |  - JSON lines over USB serial      |
|  - Web OTA (http://<ESP_IP>/update)        |   |                                    |
+--------------------------------------------+   +------------------------------------+
```

---

## Technology Stack

### 1. Backend Server (`OmniLink_Server_v0.6`)
- **Runtime**: Python 3.12+ (asynchronous event loop via `asyncio`).
- **Web Framework**: Starlette / FastAPI architecture served via Uvicorn.
- **Database**: SQLite in Write-Ahead-Logging (`WAL`) mode with persistent ledger queues (PostgreSQL supported out of the box for scale).
- **Security & Cryptography**:
  - `cryptography` Python library: Self-signed X.509 Private Root CA generation and dynamic leaf certificate provisioning with Subject Alternative Name (SAN) validation.
  - Fernet symmetric key encryption (AES-128 in CBC mode with HMAC-SHA256) for device secrets and sensitive tokens at rest.
  - CSRF double-submit protection, HTTP-only secure session cookies, and strict Origin verification.
- **Protocol Support**:
  - REST API & WebSockets for client dashboards.
  - Mosquitto Dynamic Security management (automatic MQTT user and ACL provisioning).
  - OmniLink Native Protocol (ONP TLS) binary stream on port 7443.
  - Serial gateway for Arduino Uno / Nano over USB (`examples/arduino_uno_serial_gateway.py`): reads the board's device ID/secret over USB and talks to the HTTP device API. Run it in its own window, or let the server start it via `OMNILINK_SERIAL_GATEWAY` in `.env`.

### 2. Message Broker (Eclipse Mosquitto)
- **Engine**: Eclipse Mosquitto 2.x.
- **Access Control**: Mosquitto Dynamic Security Plugin (`mosquitto_dynamic_security.dll` / `.so`).
  - Strict isolation: Each registered device receives unique random credentials and an access control list (ACL) allowing publish/subscribe only under its own topic namespace: `omnilink/v1/dev/{device_id}/#`.
- **Encryption**: TLS 1.2 / 1.3 listener on port `8883` using OmniLink's private device CA certificates; plaintext/authenticated loopback listener on port `1884` for internal server coordination.

### 3. Frontend Web Client (`OmniLink_WebClient_v0.6`)
- **Architecture**: Vanilla ES6+ Single Page Application (SPA). **Zero build steps, zero node_modules, zero external CDNs.**
- **Real-Time Data**: Persistent WebSocket connection (`/ws/live`) with heartbeat detection and automatic polling fallback.
- **Widgets**: 27 modular widgets including toggle switches, sliders, gauges, step controllers, real-time line charts, RGB colour pickers, and raw terminal monitors.
- **Flow Automation**: Embedded visual graph designer (mxGraphModel compatible SVG engine) for event-driven automation rules.
- **Provisioning System**: Dynamic sketch compilation generator that downloads ready-to-flash `.ino` files pre-populated with device keys and broker hostnames.

### 4. Embedded Firmware Layer (`OmniLink_Arduino_v0.3`)
- **Package**: A separate folder next to the server, imported into the Arduino IDE with **Sketch → Include Library → Add .ZIP Library** (IDE 1.8 accepts the folder; IDE 2.x needs the ZIP from `tools\build_arduino_library.py`).
- **Framework**: C++ for Arduino ESP32, ESP8266 (HTTP(S) or MQTT TLS) and Uno/Nano (USB serial through the server's gateway). Requires **ArduinoJson 7**.
- **Examples**: The library examples use the demo pins from `python -m examples.create_demo`: V0 Power, V1 Output selection, V2 Setpoint (sample interval), V3 Measurement. Change the `PIN_...` constants to match your own pins.
- **Uno / Nano**: `ArduinoUno_Serial` holds `DEVICE_ID` / `DEVICE_SECRET` in the sketch; the gateway reads them over USB at startup.
- **Network & TLS**: Certificate- and hostname-verified TLS by default. The private device CA is `data/certs/ca.crt`. An explicit unverified switch exists for private LANs only.
- **MQTT Engine**: `PubSubClient` with one shared command core for all transports, `onConnect` state re-reporting and reconnect backoff.
- **Wi-Fi Provisioning**: `WiFiManager` with fallback to a Captive Portal Access Point (`OmniLink-Setup`) on first boot or when the physical FLASH button (`D3`) is held.
- **Storage**: `LittleFS` flash memory saving `/config.json` across power cycles.
- **OTA Updates** (`ESP8266_Provisioning` example, off until you set `OTA_PASSWORD`): Dual Over-The-Air update engines:
  - `ESP8266HTTPUpdateServer`: Browser-based web portal (`http://<ESP_IP>/update`) for flashing compiled `.bin` binaries from any phone or PC.
  - `ArduinoOTA`: Wireless flashing directly from the Arduino IDE.

---

## Project Directory Structure

```
OmniLink/
├── .gitignore                          # Master git ignore for secrets, databases, certs
├── README.md                           # Main documentation & handover guide (this file)
├── Start.md                            # Quick reference terminal commands
│
├── OmniLink_Server_v0.6/               # Core Python IoT Backend Server
│   ├── .env.example                    # Template environment variables
│   ├── run.bat / run.sh                # Server launch scripts
│   ├── setup.bat / setup.sh            # First-time installation & CA generator
│   ├── requirements.txt                # Python dependencies
│   ├── data/                           # Server state (gitignored: db, certs, logs)
│   │   ├── certs/                      # Generated private CA and server TLS certificates
│   │   └── mosquitto/                  # Mosquitto runtime configs & ACL storage
│   ├── omnilink/                       # Backend Python application package
│   ├── examples/                       # Simulators, demo device creator, Uno serial gateway
│   └── tools/                          # Administrative tools & Mosquitto scripts
│       ├── run_mosquitto_windows.ps1   # Runs Mosquitto with dynamic security
│       └── setup_mosquitto_windows.ps1 # Configures Mosquitto credentials & paths
│
├── OmniLink_Arduino_v0.3/              # Arduino library: import this folder in Arduino IDE
│   ├── src/                            # OmniLink.h and transports (HTTP, MQTT, USB serial)
│   └── examples/                       # ESP32/ESP8266 HTTP+MQTT, ESP8266_Provisioning, ArduinoUno_Serial
│
└── OmniLink_WebClient_v0.6/            # Single Page Dashboard & UI
    ├── index.html                      # Main dashboard layout
    ├── install.py / install.bat        # Mounts client to OmniLink server
    ├── trust_ca.bat                    # One-click Windows Root CA trust installer
    ├── OmniLink_ESP8266_Setup.ino      # Master downloadable setup sketch template
    └── assets/                         # CSS stylesheets, UI icons, and app.js logic
```

---

## Prerequisites

Before setting up OmniLink, make sure your machine has:

1. **Python 3.12+**: Download from [python.org](https://www.python.org/). Check *"Add python.exe to PATH"* during Windows installation.
2. **Eclipse Mosquitto 2.x**: Download the 64-bit installer from [mosquitto.org](https://mosquitto.org/download/). Install to default path `C:\Program Files\mosquitto\`.
3. **Arduino IDE** (1.8 or 2.x): Download from [arduino.cc](https://www.arduino.cc/en/software) for uploading firmware to hardware.
   - Install **ESP8266 Board Package**: Open *Preferences* in Arduino IDE, add `http://arduino.esp8266.com/stable/package_esp8266com_index.json` to Additional Boards Manager URLs, then install `esp8266` in Boards Manager. (Arduino Nano/Uno support is built in.)
   - Install Required Arduino Libraries (**Tools → Manage Libraries**):
     - `ArduinoJson` (**v7**)
     - `PubSubClient` (by Nick O'Leary) and `WiFiManager` (by tzapu, v2.0.16+) for ESP boards
   - Install the **OmniLink library** from the `OmniLink_Arduino_v0.3` folder: close all IDE windows, delete any older copy in `Documents\Arduino\libraries` (`OmniLink` or `OmniLink_Arduino_v0.3`), reopen the IDE and use **Sketch → Include Library → Add .ZIP Library…**. Restart the IDE after every library update.

---

## Installation and Setup

### Step 1: Setup OmniLink Server

1. Open a terminal or Command Prompt in `OmniLink_Server_v0.6`:
   ```bat
   cd OmniLink_Server_v0.6
   setup.bat
   ```
   *(On Linux/macOS: `sh setup.sh`)*

2. `setup.bat` will automatically:
   - Create a Python virtual environment (`.venv`).
   - Install all Python dependencies from `requirements.txt`.
   - Prompt you for an **Administrator email** and a secure **password** (at least 12 characters).
   - Generate your private local Certificate Authority (`ca.key`, `ca.crt`) and server certificate (`server.crt`, `server.key`) under `data/certs/`.
   - Create your `.env` configuration file with generated encryption keys.

---

### Step 2: Setup Mosquitto MQTT Broker

1. Open **PowerShell as Administrator**.
2. Navigate to `OmniLink_Server_v0.6` and execute the setup script:
   ```powershell
   cd D:\OmniLink\OmniLink_Server_v0.6
   .\tools\setup_mosquitto_windows.ps1
   ```
3. This script links Mosquitto to `data/mosquitto/mosquitto.conf`, initializes the `mosquitto_dynamic_security` plugin, and synchronizes the administrative user credentials with `.env`.

---

### Step 3: Attach the Web Client

Mount the web client into the server configuration:
```bat
cd D:\OmniLink\OmniLink_WebClient_v0.6
py install.py --server-dir "..\OmniLink_Server_v0.6"
```
This updates `OMNILINK_CLIENT_DIR` in `.env` so the dashboard is served at `https://<YOUR_IP>:8000/client/`.

---

### Step 4: Trust the Local Root CA

Because OmniLink uses a private, self-hosted Certificate Authority for end-to-end TLS encryption:
- **Windows (Automatic)**: Right-click `OmniLink_WebClient_v0.6\trust_ca.bat` and select **Run as administrator**. This installs `data/certs/ca.crt` into the Windows Trusted Root Store.
- **Mobile / Android / iOS**: Download `ca.crt` from `https://<YOUR_IP>:8000/client/ca.crt` and install it as a Trusted CA in your device's security settings.

---

### Step 5: Run the Services

Start the services in two separate terminals:

**Terminal 1 — Mosquitto Broker:**
```powershell
cd D:\OmniLink\OmniLink_Server_v0.6
.\tools\run_mosquitto_windows.ps1
```

**Terminal 2 — OmniLink Server:**
```bat
cd D:\OmniLink\OmniLink_Server_v0.6
.\run.bat
```

Now open your browser and go to:
- **Dashboard**: `https://localhost:8000/client/` (or `https://<YOUR_LAN_IP>:8000/client/`)
- **System Administration**: `https://localhost:8000/`

---

## Hardware Quickstart (ESP8266 / NodeMCU)

### 1. Register Device in Dashboard
1. Open the Web Dashboard at `https://<YOUR_IP>:8000/client/`.
2. Under **Devices & Pins**, click **+ Device**.
3. Enter a friendly name (e.g. `hostel` or `nodemcu_livingroom`).
4. The system will generate a unique `Device ID` (e.g. `dev_b8a68b7e441d072bb9ef`) and a 64-character secret.

### 2. Allocate Virtual Pins
1. Click **+ Pin**.
2. Select your device, choose a free pin (e.g. `V7`), set type to `BOOL`, check `Writable`, and save.
3. Switch to the **Overview / Dashboard** tab, add a **Switch Widget**, and bind it to `V7`.

### 3. Download & Flash the Sketch
1. Under your device's settings in the dashboard, click **📥 Download Setup Sketch**.
2. The browser downloads `OmniLink_<DeviceName>_Setup.ino` with the server host and credentials pre-filled.
3. Make sure the OmniLink library is installed (see [Prerequisites](#prerequisites)).
4. Open the downloaded `.ino` file in the Arduino IDE, select your NodeMCU board and its COM port (a NodeMCU usually shows as `Silicon Labs CP210x` or `CH340` in Device Manager), and click **Upload**.
5. Make sure Mosquitto is running (Terminal 1 in [Step 5](#step-5-run-the-services)); ESP boards connect through it.

**Customizing the sketch:** your own logic goes in `userLoop()` (section **5. YOUR MAIN CODE**), which replaces the blink example. Map dashboard pins to your own functions in section **6. BIND VIRTUAL CHANNELS**. Never use a long `delay()`; use `millis()` timers so Wi-Fi and MQTT keep running.

### 4. Wi-Fi Setup (Direct or Captive Portal)
The sketch supports two connection options:
- **Direct Mode**: Enter your Wi-Fi name and password at the top of the sketch:
  ```cpp
  const char *SSID     = "MyHomeWiFi";
  const char *PASSWORD = "SecretPassword";
  ```
- **Captive Portal Mode (Default)**: Leave `SSID = ""` blank.
  1. The ESP8266 will broadcast an open Wi-Fi network called **`OmniLink-Setup`**.
  2. Connect your phone or laptop to `OmniLink-Setup`. The setup window will pop up automatically.
  3. Select your home Wi-Fi network, enter the password, and click **Save**.
  4. The ESP will restart, connect to your router, sync its time via NTP, and connect to OmniLink via encrypted MQTTS.
  *(Tip: To reset Wi-Fi settings at any time, hold the FLASH button `D3` on the NodeMCU during boot).*

### 5. Over-The-Air (OTA) Wireless Updates
Once the initial sketch is flashed over USB, **you never need a USB cable again**:
1. When connected, the ESP automatically publishes its IP address to OmniLink.
2. The dashboard displays a **⚡ Upload Firmware (OTA)** button next to the device.
3. When you make changes in Arduino IDE, click **Sketch → Export Compiled Binary** to produce a `.bin` file.
4. Click **⚡ Upload Firmware (OTA)** in the dashboard to open `http://<ESP_IP>/update`.
5. Log in with `admin` / `omnilink123`, choose the exported `.bin` file, and click **Update**. The device updates and restarts in seconds.

*Security: `omnilink123` is the same for every downloaded sketch. Change both `"omnilink123"` occurrences in the sketch before flashing, or anyone on your network can replace the firmware.*

---

## Hardware Quickstart (Arduino Nano / Uno over USB)

A Nano or Uno has no Wi-Fi, so it cannot use MQTT. It connects through a USB cable to a PC that runs the OmniLink **serial gateway**:

```
Nano (DEVICE_ID / DEVICE_SECRET in sketch) --USB--> serial gateway on the PC --HTTP--> OmniLink server
```

### 1. Create the device and pins
1. In the dashboard, **Devices & Pins → + Device**, and copy the **Device ID** and **secret**.
2. Add pins to that device with **+ Pin**. Pin numbers are unique per account, so pick numbers no other device uses (for example `V10`–`V13`). The types must match the sketch:

| Pin | Purpose | Type | Writable |
|---|---|---|---|
| `V10` | Power (output on D7, or D8 when output selection = 1) | `BOOL` | yes |
| `V11` | Output selection (0–1) | `UINT8` | yes |
| `V12` | Measurement interval (1–300 s) | `UINT32` | yes |
| `V13` | A0 measurement (0–100 %) | `FLOAT32` | no |

You can create only the pins you need; the sketch ignores the rest.

### 2. Flash the sketch
1. Install the OmniLink library (see [Prerequisites](#prerequisites)).
2. Open **File → Examples → Examples from Custom Libraries → OmniLink → ArduinoUno_Serial**.
3. Fill in the `[CHANGE]` block and the pin numbers:
   ```cpp
   const char DEVICE_ID[]     = "dev_...";   // from the dashboard
   const char DEVICE_SECRET[] = "...";       // 64 hex characters
   const uint16_t PIN_POWER = 10, PIN_OUTPUT = 11, PIN_SETPOINT = 12, PIN_MEASUREMENT = 13;
   ```
   Outputs are active LOW by default (LED from D7 through a resistor to 5V). Set `OUTPUT_ACTIVE_LOW = false` if your LED goes from D7 to GND.
4. Select **Tools → Board → Arduino Nano** (most clones also need **Processor → ATmega328P (Old Bootloader)**) and the Nano's port (usually `USB-SERIAL CH340 (COMx)` in Device Manager), then **Upload**.
5. Close the Serial Monitor: the gateway needs the COM port.

### 3. Run the serial gateway

The gateway is a small Python program in the server folder (`examples\arduino_uno_serial_gateway.py`). It owns the board's COM port, reads the device ID/secret from the board, signs in to OmniLink as that device, sends dashboard commands to the board and passes its readings back. One gateway serves one board.

**Before you start**
- The OmniLink server is running (`run.bat`).
- The Nano has the `ArduinoUno_Serial` sketch with your `DEVICE_ID` / `DEVICE_SECRET`, and the device's pins exist under **Devices & Pins**.
- The Arduino **Serial Monitor and Serial Plotter are closed** (only one program can open a COM port).
- You know the board's port: **Device Manager → Ports (COM & LPT)**, usually `USB-SERIAL CH340 (COMx)` for a Nano clone. It can change when you use another USB socket.

**Start it.** Open a second terminal (keep the server's window open), go to the server folder and run the command for your setup:

```bat
cd C:\path\to\OmniLink_Server_v0.6
```

| Where is the server? | Command |
|---|---|
| Same PC as the Nano (usual) | `.venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM7 --url http://127.0.0.1:8000` |
| Another PC on the LAN (plain HTTP) | `.venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM7 --url http://192.168.1.50:8000` |
| HTTPS server with the private OmniLink CA | `.venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM7 --url https://iot.example.com:8000 --ca data\certs\ca.crt` |
| HTTPS server with a public certificate (VPS) | `.venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM7 --url https://iot.example.com` |

Replace `COM7` with your port. On Linux/macOS use `.venv/bin/python` and a port such as `/dev/ttyUSB0` or `/dev/ttyACM0`. The gateway PC needs the server folder with its `.venv` (run `setup.bat` there once if it is a different PC).

**What you should see**

```
Gateway for dev_0123456789abcdef0123 on COM7. Ctrl+C stops it.
Connected; 4 configured pins: V10 Power, V11 Output selection, V12 Setpoint, V13 Measurement
```

The device then shows **online** in the dashboard, and switching a widget reaches the board. Keep this window open: when it closes, or the PC sleeps or restarts, the Nano goes offline. If the server restarts or the network drops, the gateway reconnects by itself (`Server unavailable (…); retrying in Ns`).

**Stop it:** press **Ctrl+C** in the gateway window.

**Upload new code later (the server keeps running)**
1. Press **Ctrl+C** in the gateway window (frees the COM port).
2. Upload from the Arduino IDE.
3. Press **↑** then **Enter** in the gateway window to start it again.

The board resets whenever the gateway opens the port, so its outputs briefly return to their power-on state.

**Gateway options**

| Option | Meaning |
|---|---|
| `--serial COM7` | The board's port (required). |
| `--url URL` | The OmniLink server address (required). |
| `--ca FILE` | CA certificate for an HTTPS server with a private certificate (`data\certs\ca.crt`). |
| `--credentials FILE` | Read the device ID/secret from a JSON file `{"id":"dev_...","secret":"..."}` instead of the board. Use this to keep the secret off the board (leave `DEVICE_ID`/`DEVICE_SECRET` empty in the sketch). |
| `--baud 115200` | Serial speed; must match `Serial.begin()` in the sketch. |

**Messages and what to do**

| Message | Meaning / fix |
|---|---|
| `could not open port 'COM7': … Access is denied` | Another program holds the port (Serial Monitor/Plotter, an upload, another gateway, or the server's auto-started gateway). Close it and start again. |
| `could not open port 'COM7': … cannot find the file` | Wrong port or board unplugged. Check Device Manager. |
| `The board has no device ID/secret` | Fill in `DEVICE_ID` / `DEVICE_SECRET` in the sketch and upload again. |
| `The board did not answer with its device ID` | The board runs an older sketch or library, or the baud rate differs. Install the current library and upload `ArduinoUno_Serial` again. |
| `Server unavailable (… 401 …)` | Wrong device secret, or the device was deleted. Copy the ID/secret again from **Devices & Pins**. |
| `Server unavailable (… 403 …)` | The device or account is disabled. |
| `Server unavailable (ConnectError …)` | The server is not running or the `--url` is wrong; the gateway keeps retrying. |
| `Ignoring report for Vn: not configured` | Pin `Vn` is missing on this device or has another type. Add it under **Devices & Pins** or change the sketch's pin numbers. |
| `Board rejected Vn command (error 400/404)` | 400: pin type on the server does not match the sketch. 404: the sketch has no handler for that pin. |
| `Warning: plain HTTP sends the device secret unencrypted` | Shown for `http://` addresses other than `127.0.0.1`/`localhost`. Fine on a private LAN; use HTTPS otherwise. |
| `Board: …` | Text the sketch printed with `Serial.print`. Remove debug prints: the USB line carries the OmniLink protocol. |

**More than one board:** run one gateway per board, each in its own window with its own `--serial` port. Each board needs its own device (ID/secret) and its own pin numbers.

**Optional: start the gateway together with the server.** Add `OMNILINK_SERIAL_GATEWAY=COM7` to `OmniLink_Server_v0.6\.env` and restart `run.bat`. The server then runs the gateway for one board on `127.0.0.1` and restarts it 5 s after it stops (for example when the board is unplugged). Because the server then holds the port, uploading needs the gateway stopped first; see the server README. Remove the line to go back to running the gateway by hand.

Full details and troubleshooting: [`OmniLink_Server_v0.6/README.md` → Arduino devices](OmniLink_Server_v0.6/README.md#arduino-devices).

---

## Network IP Change Workflow

When switching to a different Wi-Fi network (or if your host computer's local IP changes):

1. Find your new IPv4 address using `ipconfig` (Windows) or `ifconfig` (Linux).
2. Renew the server's TLS certificates with the new IP (retaining the existing root CA):
   ```bat
   cd D:\OmniLink\OmniLink_Server_v0.6
   .\.venv\Scripts\python.exe -m omnilink.certificates --host <NEW_IP> --folder data/certs
   ```
3. Update `OMNILINK_PUBLIC_URL` and `OMNILINK_SITE_ADDRESS` in `OmniLink_Server_v0.6\.env` to the new IP.
4. Restart the server with `run.bat`. The server reads `.env` only when it starts, so until then the browser gets `Origin rejected`.
5. Re-flash ESP boards whose sketch contains the old server IP (or reconfigure them through the `OmniLink-Setup` hotspot). A Nano needs no change: its gateway runs on the same PC and uses `127.0.0.1`.

*Tip: reserve the PC's IP address in your router (DHCP reservation) so it stops changing.*

---

## Virtual Pin Schema

Virtual pins isolate hardware specifics from the dashboard interface:

| Pin Type | Code | Description | Example Widgets |
|:---|:---:|:---|:---|
| `BOOL` | `1` | Boolean state (`true` / `false`) | Toggle Switch, Push Button, LED Status |
| `INT8` / `INT16` / `INT32` | `2` / `4` / `6` | Signed integers | Step Slider, Counter |
| `UINT8` / `UINT16` / `UINT32` | `3` / `5` / `7` | Unsigned integers | Selector, Setpoint, Relay Channels |
| `FLOAT32` / `FLOAT64` | `10` / `11` | Floating-point real numbers | Gauge, Line Chart, Temperature, Voltage |
| `STRING` | `12` | UTF-8 text string | Terminal, Status Display, LCD line |
| `JSON` | `14` | Structured object payload | Multi-sensor packets, GPS coordinates |

Rules:
- **One owner per pin number.** The account-wide pool is `V0`–`V254`. If `V0` belongs to one device, no other device in that account can use `V0`. Multiple widgets can still show the same pin.
- **Types must match the sketch.** `onBool` needs `BOOL`, `onUInt` needs `UINT8/16/32`, `onInt` needs `INT8/16/32`, `onFloat` needs `FLOAT32`. A mismatch makes the board reject commands (error 400).
- **A used pin's type cannot change.** Delete the pin and add it again with the new type.

---

## Troubleshooting & Diagnostics

- **Browser displays `Origin rejected` (HTTP 403)**:
  The URL in your browser must match `OMNILINK_PUBLIC_URL` in `.env` exactly (protocol, address and port; `localhost`, `127.0.0.1` and the LAN IP are different). After editing `.env`, restart `run.bat`. If the PC's IP changed, follow the [Network IP Change Workflow](#network-ip-change-workflow).
- **Arduino IDE: `OmniLink.h: No such file or directory`, or OmniLink missing under File → Examples**:
  The library is not installed, is nested one folder too deep, or the IDE was open during installation. Reinstall it as described in [Prerequisites](#prerequisites) and restart the IDE.
- **Upload fails: `can't open device "\\.\COMx"`** — wrong port; check Device Manager. **`Access is denied`** — another program holds the port (Serial Monitor, or the Nano gateway); close it first.
- **Nano commands show `rejected` (error 400 / 404)**:
  400 = the pin type on the server does not match the sketch; 404 = the sketch has no handler for that pin number. Match the `PIN_...` constants and types to **Devices & Pins**.
- **ESP8266 Serial Monitor shows `[MQTT] Connecting... State: 5`**:
  Error 5 indicates unauthorized credentials. Ensure the `Device ID` and `Device Secret` in the sketch or captive portal match the dashboard exactly.
- **ESP8266 Serial Monitor shows `[MQTT] Connecting... State: -2`**:
  The ESP cannot reach the broker. Confirm that the computer running Mosquitto is on the same Wi-Fi subnet, and that Windows Firewall is not blocking port `8883`.
- **Dashboard switch does not toggle the physical LED**:
  Check that the switch widget is assigned to the matching pin (the sketch listens on `V0` through `V7`), and verify that the onboard LED pin is set to `D4` (`GPIO2`, active LOW).
- **Resetting stored Wi-Fi and device credentials**:
  Hold down the `FLASH` button (`D3` on NodeMCU) while powering on or resetting the board. The LED will flash rapidly 10 times and reboot into `OmniLink-Setup` Access Point mode.

---

## Security Guidelines

- **Never commit `.env` or files under `data/certs/` to Git.** These files contain master encryption keys and server private keys.
- **Keep device credentials private.** Each device secret authorizes full control over that device's virtual pins.
- **Production Deployments**: When hosting over public networks, place the server behind a reverse proxy (e.g. Caddy, Nginx, or Cloudflare) with a valid public domain name and commercial SSL certificates.

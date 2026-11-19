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
                    |                                |
                    | Internal Sync (Port 1884)      | ONP TLS (Port 7443)
                    v                                v
+------------------------------------+   +--------------------------------+
|      ECLIPSE MOSQUITTO BROKER      |   | NATIVE TLS PROTOCOL (OPTIONAL) |
|  - Dynamic Security Plugin (RBAC)  |   +--------------------------------+
|  - MQTTS TLS 1.2/1.3 (Port 8883)   |
|  - Per-device ACLs & isolated roots|
+-------------------+----------------+
                    |
                    | MQTTS over TLS (Port 8883)
                    v
+-------------------------------------------------------------------------+
|                        EMBEDDED HARDWARE CLIENTS                        |
|  - NodeMCU ESP8266 / ESP32 / Arduino Uno (via Serial Gateway)          |
|  - BearSSL Secure Client + PubSubClient                                 |
|  - WiFiManager Captive Portal (`OmniLink-Setup` AP)                     |
|  - LittleFS Flash Storage (/config.json)                                |
|  - Built-in Web OTA Server (http://<ESP_IP>/update)                     |
+-------------------------------------------------------------------------+
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
  - Serial bridge gateway for Arduino Uno / Nano over USB.

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

### 4. Embedded Firmware Layer (`OmniLink_Arduino_v0.2`)
- **Framework**: C++ for Arduino / ESP8266 / ESP32.
- **Network & TLS**: `ESP8266WiFi` with BearSSL `WiFiClientSecure` using fingerprint/insecure trust modes suitable for private LANs.
- **MQTT Engine**: `PubSubClient` customized for packet buffer handling with automatic reconnect backoff.
- **Wi-Fi Provisioning**: `WiFiManager` with fallback to a Captive Portal Access Point (`OmniLink-Setup`) on first boot or when the physical FLASH button (`D3`) is held.
- **Storage**: `LittleFS` flash memory saving `/config.json` across power cycles.
- **OTA Updates**: Dual Over-The-Air update engines:
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
│   ├── examples/                       # Simulators & hardware reference sketches
│   │   └── esp8266_captive_portal/     # Captive portal ESP8266 example
│   ├── OmniLink_Arduino_v0.2/          # Bundled Arduino C++ Library
│   └── tools/                          # Administrative tools & Mosquitto scripts
│       ├── run_mosquitto_windows.ps1   # Runs Mosquitto with dynamic security
│       └── setup_mosquitto_windows.ps1 # Configures Mosquitto credentials & paths
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
3. **Arduino IDE 2.x**: Download from [arduino.cc](https://www.arduino.cc/en/software) for uploading initial firmware to hardware.
   - Install **ESP8266 Board Package**: Open *Preferences* in Arduino IDE, add `http://arduino.esp8266.com/stable/package_esp8266com_index.json` to Additional Boards Manager URLs, then install `esp8266` in Boards Manager.
   - Install Required Arduino Libraries:
     - `WiFiManager` (by tzapu, v2.0.16+)
     - `PubSubClient` (by Nick O'Leary)
     - `ArduinoJson` (v6 or v7)

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
3. Copy the bundled library folder `OmniLink_Server_v0.6\OmniLink_Arduino_v0.2` into your `Documents\Arduino\libraries\OmniLink`.
4. Open the downloaded `.ino` file in Arduino IDE 2.x, select your NodeMCU board and COM port, and click **Upload**.

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
4. Restart the server with `run.bat`.

---

## Virtual Pin Schema

Virtual pins isolate hardware specifics from the dashboard interface:

| Pin Type | Code | Description | Example Widgets |
|:---|:---:|:---|:---|
| `BOOL` | `1` | Boolean state (`true` / `false` or `0` / `1`) | Toggle Switch, Push Button, LED Status |
| `INT32` / `INT16` | `6` / `4` | Signed integers | Step Slider, Counter, Relay Channels |
| `FLOAT32` / `FLOAT64` | `10` / `11` | Floating-point real numbers | Gauge, Line Chart, Temperature, Voltage |
| `STRING` | `12` | UTF-8 text string (up to 256 bytes) | Terminal, Status Display, LCD line |
| `JSON` | `14` | Structured object payload | Multi-sensor packets, GPS coordinates |

*Note: The account-wide virtual pin pool allocates `V0` through `V254`. Multiple widgets can read from the same pin, but a single pin cannot be owned by conflicting physical actuators.*

---

## Troubleshooting & Diagnostics

- **Browser displays `Origin rejected` (HTTP 403)**:
  Ensure the URL in your browser matches `OMNILINK_PUBLIC_URL` in `.env` (including protocol and port).
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

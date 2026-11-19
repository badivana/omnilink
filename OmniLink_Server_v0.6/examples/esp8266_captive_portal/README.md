# OmniLink ESP8266 Captive Portal Provisioning & OTA Updates

This example implements **zero-hardcoding Wi-Fi provisioning**, **Dynamic Device Secrets**, and **Over-the-Air (OTA) wireless updates** for the ESP8266 (NodeMCU / D1 mini).

---

## Features

- **No Hardcoded Credentials:** Neither Wi-Fi credentials nor OmniLink Device Secret are stored in the sketch.
- **Auto Captive Portal:** If not connected to Wi-Fi, the board launches an open hotspot named `OmniLink-Setup`.
- **Custom Parameter Inputs:** Students configure:
  - Wi-Fi SSID & Password (with live Wi-Fi network scanner)
  - OmniLink Server Host / IP (default: `10.247.246.36`)
  - OmniLink MQTTS Port (default: `8883`)
  - Device ID (`dev_...`)
  - Device Secret (64-character token from the web dashboard)
- **Flash Storage (`LittleFS`):** Configuration is saved across reboots in `/config.json`.
- **Hardware Reset Button:** Hold down the **FLASH button (Pin D3 / GPIO0)** while booting or resetting to wipe saved Wi-Fi & settings and restart the setup hotspot.
- **Over-The-Air (OTA) Wireless Updates:** Flash new code without plugging in a USB cable!
  - **Method 1:** Directly from Arduino IDE via Network Port (`ArduinoOTA`).
  - **Method 2:** Using any web browser at `http://<ESP_IP>/update` by uploading a compiled `.bin` file.
- **Dual Pin Support:** Pre-configured for both **V0** and **V6** switches controlling the onboard LED (Pin D4).

---

## Required Arduino Libraries

Install these from the Arduino IDE Library Manager (**Tools → Manage Libraries...**):
1. **WiFiManager** (by tzapu, v2.0.16+)
2. **ArduinoJson** (by Benoît Blanchon, v6 or v7)
3. **PubSubClient** (by Nick O'Leary)
4. **OmniLink** (included in this repository)

*(Note: `ArduinoOTA` and `ESP8266HTTPUpdateServer` are built directly into the ESP8266 board core.)*

---

## First-Time Setup (Over USB)

1. Connect your NodeMCU via USB and upload `ESP8266_CaptivePortal.ino`.
2. Connect your phone or laptop to the **`OmniLink-Setup`** Wi-Fi hotspot.
3. Open `http://192.168.4.1`, choose your Wi-Fi, paste your Device ID & Secret, and tap **Save**.
4. The board reboots and connects to OmniLink MQTTS!

---

## How to Flash Future Updates Wirelessly (OTA)

Once this sketch is flashed onto your board, you **never need the USB cable again**. You can push updates wirelessly using either method:

### Method 1: Web Browser (.bin File Upload) — Easiest for Students
1. In Arduino IDE, edit your sketch, then click:
   **Sketch → Export Compiled Binary** (`Ctrl + Alt + S`).
2. Arduino IDE will create a `.bin` file in your sketch folder (e.g. `ESP8266_CaptivePortal.ino.bin`).
3. Find your ESP8266's IP address (printed on Serial monitor, or visible on your Wi-Fi router / OmniLink dashboard).
4. In any web browser on the same Wi-Fi, go to:
   ```
   http://<ESP_IP>/update
   ```
5. Log in:
   - **Username:** `admin`
   - **Password:** `omnilink123`
6. Click **Choose File**, select your `.bin` file, and click **Update**.
7. The ESP8266 will flash itself, reboot, and run your new code in ~10 seconds!

---

### Method 2: Arduino IDE Wireless Upload (`ArduinoOTA`)
1. Make sure your laptop and the NodeMCU are on the same Wi-Fi network.
2. In Arduino IDE, open **Tools → Port**.
3. Under **Network Ports**, you will see:
   ```
   omnilink-nodemcu at <ESP_IP>
   ```
4. Select that network port.
5. Click **Upload** (`Ctrl + U`).
6. When prompted for password, enter: `omnilink123`.
7. Arduino IDE uploads the code wirelessly over Wi-Fi!

---

## Changing Wi-Fi or Resetting

To change Wi-Fi networks or clear the Device Secret:
- Hold down the **FLASH button (Pin D3)** on the NodeMCU.
- Press and release the **RST** button (keep holding FLASH for ~2 seconds).
- The LED will flash rapidly, the configuration will be erased, and the `OmniLink-Setup` hotspot will reopen.

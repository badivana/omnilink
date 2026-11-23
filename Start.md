# OmniLink quick commands

Paths and addresses below match this PC:
- server folder: `C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6`
- server address: `http://10.100.88.185:8000` (plain HTTP on the LAN, from `OMNILINK_PUBLIC_URL` in `.env`)

If the PC's IP address changes, see "IP address changed" at the bottom.

## 1. Start Mosquitto (needed for ESP8266/ESP32 over MQTT)

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\tools\run_mosquitto_windows.ps1
```

## 2. Start the server

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\run.bat
```

Open in the browser (use exactly this address, or you get "Origin rejected"):
- dashboard: http://10.100.88.185:8000/client/
- administration: http://10.100.88.185:8000/

Health check: http://10.100.88.185:8000/health/ready (`"mqtt":true` means Mosquitto is connected)

## 3. Start the Nano gateway (Arduino Nano/Uno over USB)

Close the Arduino Serial Monitor first. Replace `COM7` with the Nano's port (Device Manager, `USB-SERIAL CH340`).

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\.venv\Scripts\python.exe examples\arduino_uno_serial_gateway.py --serial COM7 --url http://127.0.0.1:8000
```

Upload new Nano code: press **Ctrl+C** here, upload from the Arduino IDE, then run the gateway line again (**↑** then **Enter**). The server keeps running.

## Arduino library

- Arduino IDE 1.8: **Sketch → Include Library → Add .ZIP Library…** and select the folder
  `C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Arduino_v0.3`
- Arduino IDE 2.x (ZIP only): build the ZIP, then select
  `C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Arduino_v0.3.zip`

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\.venv\Scripts\python.exe tools\build_arduino_library.py
```

Before importing, close all IDE windows and delete the old copy in `Documents\Arduino\libraries` (`OmniLink` or `OmniLink_Arduino_v0.3`). Restart the IDE afterwards.

## Simulated device (testing without hardware)

Save the device ID/secret as `device-credentials.json` in the server folder:

```json
{"id":"dev_...","secret":"..."}
```

Then pick one transport:

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\.venv\Scripts\python.exe -m examples.simulator --transport http --url http://127.0.0.1:8000 --credentials .\device-credentials.json
```

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\.venv\Scripts\python.exe -m examples.simulator --transport mqtt --url http://127.0.0.1:8000 --host 127.0.0.1 --port 8883 --ca data\certs\ca.crt --credentials .\device-credentials.json
```

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\.venv\Scripts\python.exe -m examples.simulator --transport onp --url http://127.0.0.1:8000 --host 127.0.0.1 --port 7443 --ca data\certs\ca.crt --credentials .\device-credentials.json
```

Run these on this PC: the device certificate currently covers only `localhost` and `127.0.0.1`, and ONP listens only on `127.0.0.1`.

## IP address changed

1. Find the new address: `ipconfig` (Wi-Fi adapter, IPv4 address).
2. In `.env`, set `OMNILINK_PUBLIC_URL=http://<NEW_IP>:8000`.
3. Restart the server (Ctrl+C, then `.\run.bat`).
4. ESP boards with the old IP in their sketch: re-flash, or reconfigure through the `OmniLink-Setup` hotspot (hold FLASH/D3 while booting). The Nano needs no change.

For ESP boards with verified TLS (`USE_INSECURE_TLS = false`), add the LAN IP to the device certificate once, then restart Mosquitto and the server:

```powershell
cd C:\Users\ASUS\Downloads\omnilink-main\omnilink-main\OmniLink_Server_v0.6
.\.venv\Scripts\python.exe -m omnilink.certificates --host 10.100.88.185
```

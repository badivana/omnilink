@echo off
cd /d "%~dp0"
rem One command: Mosquitto (own window), Nano/Uno serial gateway (own window), then the server here.

rem Settings from .env: gateway port (empty = no gateway), HTTP port and TLS for the gateway's URL.
set "GW_PORT=" & set "HTTP_PORT=8000" & set "HTTP_TLS=false"
if exist .env for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
  if /i "%%a"=="OMNILINK_SERIAL_GATEWAY" set "GW_PORT=%%b"
  if /i "%%a"=="OMNILINK_HTTP_PORT" set "HTTP_PORT=%%b"
  if /i "%%a"=="OMNILINK_HTTP_TLS" set "HTTP_TLS=%%b"
)

rem 1. Mosquitto, if it is set up here and not already running (ESP boards need it).
if exist data\mosquitto\mosquitto.conf (
  tasklist /FI "IMAGENAME eq mosquitto.exe" | find /I "mosquitto.exe" >nul || (
    echo Starting Mosquitto in a new window...
    start "Mosquitto" powershell -NoExit -ExecutionPolicy Bypass -File tools\run_mosquitto_windows.ps1
    timeout /t 2 /nobreak >nul
  )
)

rem 2. Serial gateway, if OMNILINK_SERIAL_GATEWAY=COMx is set and its window is not open yet.
rem    To upload new board code: Ctrl+C in that window, upload, then Up-arrow + Enter there.
if defined GW_PORT (
  tasklist /V /FI "WINDOWTITLE eq OmniLink gateway*" | find /I "OmniLink gateway" >nul || (
    set "GW_URL=http://127.0.0.1:%HTTP_PORT%" & set "GW_CA="
    if /i "%HTTP_TLS%"=="true" set "GW_URL=https://127.0.0.1:%HTTP_PORT%" & set "GW_CA=--ca data\certs\ca.crt"
    call :gateway
  )
)

rem 3. The server, in this window (Ctrl+C stops it; the other windows keep running).
.venv\Scripts\python -m omnilink
goto :eof

:gateway
echo Starting the serial gateway on %GW_PORT% in a new window...
start "OmniLink gateway %GW_PORT%" cmd /k .venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial %GW_PORT% --url %GW_URL% %GW_CA%
goto :eof

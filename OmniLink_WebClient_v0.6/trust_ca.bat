@echo off
set "CERT_URL=https://10.30.203.36:8000/client/ca.crt"
set "CERT_FILE=%TEMP%\omnilink_ca.crt"

echo ====================================================
echo        OmniLink Automatic CA Trust Installer
echo ====================================================
echo.
echo Downloading Root CA certificate from server...
powershell -Command "[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}; (New-Object System.Net.WebClient).DownloadFile('%CERT_URL%', '%CERT_FILE%')"

if not exist "%CERT_FILE%" (
    echo [ERROR] Failed to download certificate. Make sure you are connected to the same Wi-Fi.
    pause
    exit /b 1
)

echo Installing certificate into Windows Trusted Root store...
certutil -addstore -f Root "%CERT_FILE%"

if %ERRORLEVEL% equ 0 (
    echo.
    echo ====================================================
    echo [SUCCESS] OmniLink TLS Certificate successfully trusted!
    echo You can now open: https://10.30.203.36:8000/client/
    echo ====================================================
) else (
    echo.
    echo [FAILED] Administrator permission required.
    echo Right-click this file and select "Run as administrator".
)

del "%CERT_FILE%" 2>nul
pause

mosquitto start
cd D:\OmniLink\OmniLink_Server_v0.6
.\tools\run_mosquitto_windows.ps1

server start
cd D:\OmniLink\OmniLink_Server_v0.6
.\run.bat

https://10.30.203.36:8000/client/

demo (HTTPS)
cd "D:\OmniLink\OmniLink_Server_v0.6"
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m examples.simulator --transport http --url https://10.30.203.36:8000 --http-ca data/certs/ca.crt --credentials .\device-credentials.json

demo (Native ONP TLS)
cd "D:\OmniLink\OmniLink_Server_v0.6"
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m examples.simulator --transport onp --host 10.30.203.36 --port 7443 --ca data/certs/ca.crt --credentials .\device-credentials.json

demo (MQTT TLS)
cd "D:\OmniLink\OmniLink_Server_v0.6"
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m examples.simulator --transport mqtt --host 10.30.203.36 --port 8883 --ca data/certs/ca.crt --credentials .\device-credentials.json
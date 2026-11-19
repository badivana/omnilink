$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config = Join-Path $root 'data\mosquitto\mosquitto.conf'
$exe = (Get-Command mosquitto.exe -ErrorAction SilentlyContinue).Source
if (-not $exe) { $exe = 'C:\Program Files\mosquitto\mosquitto.exe' }
if (-not (Test-Path $exe)) { $exe = 'C:\Program Files (x86)\mosquitto\mosquitto.exe' }
if (-not (Test-Path $config)) { throw 'Run tools\setup_mosquitto_windows.ps1 first.' }
if (-not (Test-Path $exe)) { throw 'Mosquitto executable not found. Install Mosquitto first.' }
& $exe -c $config -v

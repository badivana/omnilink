param([switch]$EnablePlain)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

if (-not (Test-Path '.env')) { throw 'Run setup.bat first so .env and device TLS certificates exist.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Open PowerShell as Administrator, then run this script again.'
}

$exe = (Get-Command mosquitto.exe -ErrorAction SilentlyContinue).Source
if (-not $exe) {
  if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'Install Mosquitto from https://mosquitto.org/download/ or install winget, then rerun.' }
  winget install --id EclipseFoundation.Mosquitto --exact --accept-package-agreements --accept-source-agreements
  $exe = (Get-Command mosquitto.exe -ErrorAction SilentlyContinue).Source
}
if (-not $exe) {
  $exe = 'C:\Program Files\mosquitto\mosquitto.exe'
  if (-not (Test-Path $exe)) { $exe = 'C:\Program Files (x86)\mosquitto\mosquitto.exe' }
}
$bin = Split-Path $exe
$ctrl = Join-Path $bin 'mosquitto_ctrl.exe'
$plugin = Join-Path $bin 'mosquitto_dynamic_security.dll'
if (-not (Test-Path $ctrl)) { throw "Mosquitto control utility not found: $ctrl" }
if (-not (Test-Path $plugin)) { throw "Dynamic Security plugin not found: $plugin. Reinstall the official Mosquitto package." }

$lines = [Collections.Generic.List[string]]::new()
$lines.AddRange([string[]](Get-Content '.env' -Encoding UTF8))
function Get-EnvValue([string]$Name) {
  $line = $lines | Where-Object { $_.StartsWith("$Name=") } | Select-Object -Last 1
  if (-not $line) { return $null }
  return $line.Substring($Name.Length + 1)
}
function Set-EnvValue([string]$Name, [string]$Value) {
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].StartsWith("$Name=")) { $lines[$i] = "$Name=$Value"; return }
  }
  $lines.Add("$Name=$Value")
}
$adminPassword = Get-EnvValue 'OMNILINK_MQTT_ADMIN_PASSWORD'
if (-not $adminPassword) { throw 'OMNILINK_MQTT_ADMIN_PASSWORD is missing from .env.' }
$adminUser = Get-EnvValue 'OMNILINK_MQTT_ADMIN_USER'
if (-not $adminUser) { $adminUser = 'omnilink-admin' }

$state = Join-Path $root 'data\mosquitto'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$dynsec = Join-Path $state 'dynamic-security.json'
if (-not (Test-Path $dynsec)) { & $ctrl dynsec init $dynsec $adminUser $adminPassword; if ($LASTEXITCODE -ne 0) { throw 'Mosquitto Dynamic Security initialization failed.' } }
$config = Join-Path $state 'mosquitto.conf'
$configLines = @(
  'per_listener_settings false'
  'allow_anonymous false'
  'persistence true'
  "persistence_location `"$($state.Replace('\','/'))/`""
  "plugin `"$($plugin.Replace('\','/'))`""
  "plugin_opt_config_file `"$($dynsec.Replace('\','/'))`""
  'max_packet_size 16384'
  'message_size_limit 8192'
  'listener 1884 127.0.0.1'
)
if ($EnablePlain) { $configLines += 'listener 1883 0.0.0.0' }
$configLines += @(
  'listener 8883 0.0.0.0'
  "certfile `"$($root.Replace('\','/'))/data/certs/server.crt`""
  "keyfile `"$($root.Replace('\','/'))/data/certs/server.key`""
  'tls_version tlsv1.2'
)
[IO.File]::WriteAllLines($config, $configLines, [Text.UTF8Encoding]::new($false))
Set-EnvValue 'OMNILINK_MQTT_ENABLED' 'true'
Set-EnvValue 'OMNILINK_MQTT_HOST' '127.0.0.1'
Set-EnvValue 'OMNILINK_MQTT_PORT' '1884'
Set-EnvValue 'OMNILINK_MQTT_ADMIN_USER' $adminUser
[IO.File]::WriteAllText((Join-Path $root '.env'), (($lines -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))

$service = Get-Service -Name 'mosquitto' -ErrorAction SilentlyContinue
if ($service) { if ($service.Status -ne 'Stopped') { Stop-Service -Name 'mosquitto' }; Set-Service -Name 'mosquitto' -StartupType Manual }
Write-Host 'Mosquitto is configured. In a second PowerShell window, run:'
Write-Host '  powershell -ExecutionPolicy Bypass -File tools\run_mosquitto_windows.ps1'
Write-Host 'Device MQTT TLS endpoint: this server hostname, port 8883.'
if ($EnablePlain) { Write-Warning 'Port 1883 is exposed without TLS. Keep it on an isolated/private network; it exposes device secrets.' }

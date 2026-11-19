#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
plain=false
if [[ ${1:-} == "--plain" && $# -eq 1 ]]; then plain=true
elif [[ $# -gt 0 ]]; then echo "Usage: sudo sh tools/setup_mosquitto_vps.sh [--plain]" >&2; exit 2; fi
if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo sh tools/setup_mosquitto_vps.sh" >&2; exit 1; fi
if [[ ! -f "$root/.env" || ! -f "$root/data/certs/server.crt" || ! -f "$root/data/certs/server.key" ]]; then
  echo "Run sh setup.sh --domain iot.example.com first." >&2; exit 1
fi
command -v apt-get >/dev/null || { echo 'This installer supports Debian/Ubuntu VPS hosts.' >&2; exit 1; }
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y mosquitto mosquitto-clients
plugin="$(find /usr/lib -type f -name 'mosquitto_dynamic_security.so' -print -quit)"
if [[ -z "$plugin" ]]; then echo 'Mosquitto Dynamic Security plugin is missing from this package. Install the matching Mosquitto Dynamic Security plugin, then rerun.' >&2; exit 1; fi

value() { sed -n "s/^$1=//p" "$root/.env" | tail -n 1; }
admin_user="$(value OMNILINK_MQTT_ADMIN_USER)"; admin_user="${admin_user:-omnilink-admin}"
admin_password="$(value OMNILINK_MQTT_ADMIN_PASSWORD)"
[[ -n "$admin_password" ]] || { echo 'OMNILINK_MQTT_ADMIN_PASSWORD is missing from .env.' >&2; exit 1; }
mkdir -p /etc/mosquitto/certs /var/lib/mosquitto/omnilink
chown mosquitto:mosquitto /var/lib/mosquitto/omnilink
chmod 0750 /var/lib/mosquitto/omnilink
install -o mosquitto -g mosquitto -m 0644 "$root/data/certs/server.crt" /etc/mosquitto/certs/omnilink.crt
install -o mosquitto -g mosquitto -m 0640 "$root/data/certs/server.key" /etc/mosquitto/certs/omnilink.key
dynsec=/var/lib/mosquitto/omnilink/dynamic-security.json
if [[ ! -f "$dynsec" ]]; then
  mosquitto_ctrl dynsec init "$dynsec" "$admin_user" "$admin_password"
  chown mosquitto:mosquitto "$dynsec"; chmod 0600 "$dynsec"
fi
config=/etc/mosquitto/conf.d/omnilink.conf
cat > "$config" <<EOF
per_listener_settings false
allow_anonymous false
plugin $plugin
plugin_opt_config_file $dynsec
max_packet_size 16384
message_size_limit 8192
listener 1884 127.0.0.1
EOF
if $plain; then printf 'listener 1883 0.0.0.0\n' >> "$config"; fi
cat >> "$config" <<EOF
listener 8883 0.0.0.0
certfile /etc/mosquitto/certs/omnilink.crt
keyfile /etc/mosquitto/certs/omnilink.key
tls_version tlsv1.2
EOF
chmod 0644 "$config"

python3 - "$root/.env" "$admin_user" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text(encoding='utf-8').splitlines(); updates={
 'OMNILINK_MQTT_ENABLED':'true','OMNILINK_MQTT_HOST':'127.0.0.1',
 'OMNILINK_MQTT_PORT':'1884','OMNILINK_MQTT_ADMIN_USER':sys.argv[2]}
for key,value in updates.items():
    line=key+'='+value
    for i,old in enumerate(lines):
        if old.startswith(key+'='): lines[i]=line; break
    else: lines.append(line)
p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
p.chmod(0o600)
PY
systemctl enable mosquitto
systemctl restart mosquitto
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
  ufw allow 8000/tcp; ufw allow 7443/tcp; ufw allow 8883/tcp
  if $plain; then ufw allow 1883/tcp; fi
fi
echo 'Mosquitto is installed and running. Expose TCP 8883 for MQTT TLS.'
echo 'Keep TCP 1884 loopback-only; OmniLink uses it to manage devices and broker ACLs.'
if $plain; then echo 'WARNING: TCP 1883 is exposed without TLS and reveals device secrets. Use only on an isolated/private network.'; fi

#!/bin/sh
set -eu
mkdir -p /mosquitto/data/certs
cp /certs-ro/server.crt /mosquitto/data/certs/server.crt
cp /certs-ro/server.key /mosquitto/data/certs/server.key
chmod 600 /mosquitto/data/certs/server.key
if [ ! -f /mosquitto/data/dynamic-security.json ]; then
  printf '%s\n%s\n' "$OMNILINK_MQTT_ADMIN_PASSWORD" "$OMNILINK_MQTT_ADMIN_PASSWORD" | mosquitto_ctrl dynsec init /mosquitto/data/dynamic-security.json omnilink-admin >/dev/null
fi
chown -R mosquitto:mosquitto /mosquitto/data
exec mosquitto -c /mosquitto/config/mosquitto.conf

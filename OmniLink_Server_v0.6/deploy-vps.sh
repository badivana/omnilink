#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
Usage: ./deploy-vps.sh <domain> [--plain-mqtt]

Deploys OmniLink, PostgreSQL, Mosquitto, and Caddy with Docker Compose.
The normal deployment exposes HTTPS on 443, ONP TLS on 7443, and MQTT TLS on
8883. --plain-mqtt additionally exposes unauthenticated-in-transit MQTT on
1883; use it only on an isolated/private network.
EOF
}

if [[ $# -lt 1 || $# -gt 2 ]]; then usage; exit 2; fi
domain="$1"
plain=false
if [[ ${2:-} == "--plain-mqtt" ]]; then plain=true
elif [[ $# -eq 2 ]]; then usage; exit 2
fi

if [[ "$domain" == *://* || "$domain" == */* || "$domain" == *:* ]]; then
  echo "Pass a DNS hostname only, for example iot.example.com." >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Install Docker Engine and the Docker Compose plugin, then rerun this script." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  sh ./setup.sh --docker --domain "$domain"
else
  echo "Existing .env found; preserving it. Confirm OMNILINK_PUBLIC_URL and the certificate SAN contain $domain."
fi

compose=(docker compose -f compose.yaml)
if $plain; then compose+=(-f compose.mqtt-plain.yaml); fi
"${compose[@]}" up -d --build
"${compose[@]}" ps
echo "OmniLink is starting at https://$domain. Copy data/certs/ca.crt for MQTT TLS devices."
if $plain; then
  echo "WARNING: MQTT port 1883 is exposed without TLS. Do not use it over the public Internet."
fi

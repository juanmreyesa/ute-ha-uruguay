#!/bin/bash
# Captura tráfico de la app UTE en el OnePlus 12.
# Uso: ./run-mitm.sh [nombre-de-flow]
#   El OnePlus debe tener proxy WiFi → 192.168.2.10:8080
#   y el cert mitm-ca/mitmproxy-ca-cert.crt instalado como user-CA.

set -euo pipefail

cd "$(dirname "$0")"
NAME="${1:-ute-$(date +%Y%m%d-%H%M%S)}"
OUT="../captures/flows/${NAME}.mitm"
mkdir -p "$(dirname "$OUT")"

echo ">> mitmdump escuchando en 0.0.0.0:8080 (IPv4 only)"
echo ">> guardando flow en: $OUT"
echo ">> Ctrl-C para terminar"
echo

# IPv4-only: el AVD se configura con ipv6=off (ver run-avd.sh) para evitar
# que netsimd genere conexiones IPv6 que crashean al recibir 502 del proxy.
exec uvx --from mitmproxy mitmdump \
  --set confdir="$PWD/mitm-ca" \
  --listen-host 0.0.0.0 \
  --listen-port 8080 \
  -s "$PWD/security_bypass_addon.py" \
  -w "$OUT" \
  --set termlog_verbosity=info \
  --set console_eventlog_verbosity=info

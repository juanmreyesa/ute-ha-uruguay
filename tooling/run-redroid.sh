#!/usr/bin/env bash
# Lanzar Android-in-Docker (redroid) como alternativa al AVD oficial.
# Redroid corre Android nativo en un container; sin Qt, sin Netsim,
# sin los crashes recurrentes del emulator 36.5.11. Pero la app UTE
# aún detecta root (test-keys + /system/xbin/su + ro.debuggable=1) y
# aborta pre-bootstrap, así que para capturar tráfico real hace falta
# además parchear el Dart con Frida o ocultar root con Magisk.
#
# Pre-req: docker, kernel module binder_linux.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
HASH=c8750f0d
CERT="$THIS_DIR/mitm-ca/mitmproxy-ca-cert.pem"
DATA_DIR="${REDROID_DATA:-$HOME/redroid-data}"
mkdir -p "$DATA_DIR"

# 1. Cargar binder con multi-instance support si hace falta
if [ ! -e /dev/binder ]; then
  echo ">> cargando binder_linux..."
  sudo modprobe binder_linux num_devices=1 devices=binder,hwbinder,vndbinder
  sudo chmod 666 /dev/binder /dev/hwbinder /dev/vndbinder
fi

# 2. Detener container previo
sudo docker stop redroid 2>/dev/null || true
sleep 1

# 3. Pre-poblar cacerts overlay (system + apex) con el cert mitm
mkdir -p /tmp/redroid-cacerts/system /tmp/redroid-cacerts/apex

if [ ! -e /tmp/redroid-cacerts/system/01419da9.0 ]; then
  echo ">> extrayendo cacerts del image base..."
  TMPID=$(sudo docker create --rm redroid/redroid:14.0.0_64only-latest)
  sudo docker cp "$TMPID:/system/etc/security/cacerts/." /tmp/redroid-cacerts/system/
  sudo docker cp "$TMPID:/apex/com.android.conscrypt/cacerts/." /tmp/redroid-cacerts/apex/
  sudo docker rm "$TMPID" >/dev/null
  sudo chown -R "$USER:$USER" /tmp/redroid-cacerts
fi

cp "$CERT" "/tmp/redroid-cacerts/system/${HASH}.0"
cp "$CERT" "/tmp/redroid-cacerts/apex/${HASH}.0"

# 4. Lanzar
echo ">> launching redroid container..."
sudo docker run -d --rm --name redroid \
  --privileged \
  --security-opt apparmor=unconfined \
  --security-opt seccomp=unconfined \
  -v "$DATA_DIR":/data \
  -v /tmp/redroid-cacerts/system:/system/etc/security/cacerts:ro \
  -v "$CERT":/data/local/tmp/${HASH}.0:ro \
  -p 5555:5555 \
  redroid/redroid:14.0.0_64only-latest

echo ">> conectando adb..."
sleep 3
adb=$THIS_DIR/android-sdk/platform-tools/adb
until "$adb" connect localhost:5555 2>&1 | grep -q connected; do sleep 2; done
until "$adb" -s localhost:5555 shell 'getprop sys.boot_completed' 2>/dev/null | grep -q '^1'; do sleep 3; done

# 5. Bind-mount apex cacerts post-boot (apexd lo overlea, hay que esperar)
"$adb" -s localhost:5555 root >/dev/null
sleep 2
"$adb" -s localhost:5555 shell "
  toybox mount --bind /tmp/redroid-cacerts/apex /apex/com.android.conscrypt/cacerts 2>&1 || true
  settings put global http_proxy 192.168.2.10:8080
"

echo ">> redroid listo en localhost:5555"
echo ">>"
echo ">> BLOCKER conocido: la app UTE detecta root (test-keys, /system/xbin/su,"
echo ">> ro.debuggable=1) y aborta antes del primer request al backend. Para"
echo ">> capturar tráfico real hace falta Magisk Hide o Frida hook de la función"
echo ">> Dart 'is compromised'."

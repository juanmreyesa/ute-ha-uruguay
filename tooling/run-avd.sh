#!/bin/bash
# Bootea el AVD con proxy hardcoded a mitmproxy y system writable
# (para poder instalar el cert mitm como system CA).
#
# Pre-req:
#   - $ANDROID_HOME apuntando a tooling/android-sdk
#   - AVD `ute_capture` ya creado (run create-avd.sh primero)
#   - mitmdump corriendo en 192.168.2.10:8080 (run-mitm.sh)
set -euo pipefail

THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
export ANDROID_HOME="$THIS_DIR/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

PROXY_HOST="${PROXY_HOST:-192.168.2.10}"
PROXY_PORT="${PROXY_PORT:-8080}"
AVD_NAME="${AVD_NAME:-ute_capture}"
HEADLESS="${HEADLESS:-1}"

WINDOW_FLAG=()
if [ "$HEADLESS" = "1" ]; then
  WINDOW_FLAG=(-no-window)
fi

echo ">> launching $AVD_NAME with HTTP proxy $PROXY_HOST:$PROXY_PORT (headless=$HEADLESS)"

# -no-snapshot-load: arranque limpio cada vez
# -no-snapshot-save: no guardar state al cerrar (evita corrupción cross-run)
# -writable-system: /system rw para sideloadear cert mitm
# -http-proxy: qemu enforces el proxy a TODO TCP (Flutter no lo puede esquivar)
# -no-boot-anim / -no-audio: arranque más rápido, sin ruido
# -idle-grpc-timeout 0: CRITICAL — sin este flag, el watchdog interno mata
#    qemu-system-x86_64 si no hay actividad gRPC en ~60s. La señal de muerte
#    es "Netsim Wifi ipv6:[::1]:N is gone due to Socket closed" seguido de
#    "bad_function_call was thrown in -fno-exceptions mode" y abort. Pasa
#    durante captura cuando entre `adb shell input` consecutivos hay sleeps.
# -feature -Wifi -feature -VirtioWifi: CRITICAL — bypassea netsimd, que tiene
#    un bug de SIGSEGV en libslirp-rs/src/libslirp.rs:338 al procesar 502 desde
#    el http-proxy. Sin Wifi, el guest queda con eth0 sobre slirp interno de
#    qemu (modelo legacy pre-36.x) y el http-proxy se aplica ahí — ni netsimd
#    ni mac80211_hwsim se involucran. Internet sigue funcionando vía Ethernet
#    y la app no distingue (no chequea ConnectivityManager.TYPE_WIFI).
exec emulator \
  -avd "$AVD_NAME" \
  -wipe-data \
  -no-snapshot \
  -writable-system \
  -http-proxy "http://$PROXY_HOST:$PROXY_PORT" \
  -no-boot-anim \
  -no-audio \
  -gpu swiftshader_indirect \
  -accel on \
  -idle-grpc-timeout 0 \
  "${WINDOW_FLAG[@]}" \
  -feature -Wifi \
  -feature -VirtioWifi \
  -network-user-mode-options "ipv6=off"

#!/bin/bash
# Crea un AVD x86_64 Android 14 con Google APIs (no Play, así root es trivial).
set -euo pipefail

THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
export ANDROID_HOME="$THIS_DIR/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

AVD_NAME="${AVD_NAME:-ute_capture}"
SYS_IMAGE="${SYS_IMAGE:-system-images;android-34;google_apis;x86_64}"

if avdmanager list avd | grep -q "Name: $AVD_NAME"; then
  echo "AVD $AVD_NAME ya existe — borralo primero con: avdmanager delete avd -n $AVD_NAME"
  exit 0
fi

echo "no" | avdmanager create avd \
  -n "$AVD_NAME" \
  -k "$SYS_IMAGE" \
  -d "pixel_5"

# tunear config para 4GB RAM y display razonable
AVD_DIR="$HOME/.android/avd/$AVD_NAME.avd"
cat >> "$AVD_DIR/config.ini" <<'EOF'
hw.ramSize=4096
hw.cpu.ncore=4
hw.lcd.density=420
hw.lcd.height=2400
hw.lcd.width=1080
disk.dataPartition.size=8192M
EOF

echo "✓ AVD $AVD_NAME creado"

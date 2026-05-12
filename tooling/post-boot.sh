#!/bin/bash
# Post-boot setup del AVD: bind-mount cert mitm en system+APEX y reinstala
# la app UTE oficial. Idempotente: corre cada vez que el AVD arranca con
# -wipe-data (que es siempre, para evitar corrupción de snapshot).
set -euo pipefail

THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
ADB="$THIS_DIR/android-sdk/platform-tools/adb"
CERT="$THIS_DIR/mitm-ca/mitmproxy-ca-cert.pem"
APK_DIR="$THIS_DIR/../captures/apk/v1.0.40"
HASH=c8750f0d

echo ">> waiting for boot_completed..."
"$ADB" wait-for-device
until [ "$("$ADB" shell 'getprop sys.boot_completed' 2>/dev/null | tr -d '\r')" = "1" ]; do
  sleep 2
done

echo ">> root + remount"
"$ADB" root >/dev/null
"$ADB" wait-for-device
"$ADB" remount >/dev/null 2>&1 || true

echo ">> push cert + bind-mount system+APEX cacerts"
"$ADB" push "$CERT" "/data/local/tmp/${HASH}.0" >/dev/null
"$ADB" shell "
mkdir -p /data/local/tmp/cacerts-system /data/local/tmp/cacerts-apex
cp /system/etc/security/cacerts/* /data/local/tmp/cacerts-system/ 2>/dev/null || true
cp /apex/com.android.conscrypt/cacerts/* /data/local/tmp/cacerts-apex/ 2>/dev/null || true
cp /data/local/tmp/${HASH}.0 /data/local/tmp/cacerts-system/${HASH}.0
cp /data/local/tmp/${HASH}.0 /data/local/tmp/cacerts-apex/${HASH}.0
mount --bind /data/local/tmp/cacerts-system /system/etc/security/cacerts
mount --bind /data/local/tmp/cacerts-apex /apex/com.android.conscrypt/cacerts
" >/dev/null

if "$ADB" shell 'pm list packages' | grep -q uy.com.ute.customers; then
  echo ">> UTE app already installed"
else
  echo ">> installing UTE app multi-split..."
  "$ADB" install-multiple -r \
    "$APK_DIR/base.apk" \
    "$APK_DIR/split_config.arm64_v8a.apk" \
    "$APK_DIR/split_config.es.apk" \
    "$APK_DIR/split_config.xxxhdpi.apk" >/dev/null
fi

echo ">> launching app"
"$ADB" shell 'monkey -p uy.com.ute.customers -c android.intent.category.LAUNCHER 1' >/dev/null 2>&1
echo ">> ready: AVD up, cert installed, UTE app launched"

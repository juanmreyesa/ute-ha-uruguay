# Captura del tráfico UTE — guía operativa

Reproducir esta captura te permite refrescar `PROTOCOL.md` cuando UTE actualiza la app móvil. Pensado para Linux + OnePlus 12 (sin root) en Android 16, pero el procedimiento es general para cualquier Android 7+.

## 0. Pre-requisitos

- `adb` (paquete `android-sdk-platform-tools`).
- `uvx` (`pipx install uv` o instalador oficial).
- `node` + `npx` para `apk-mitm`.
- `java 11+` (para `apktool`/`uber-apk-signer` que `apk-mitm` baja).
- OnePlus (o cualquier Android) con depuración USB habilitada y autorizada para esta máquina.
- WiFi compartida entre el host (proxy) y el device.

## 1. Pull de la app desde el device

```bash
PKG=uy.com.ute.customers
adb shell pm path $PKG | sed 's/^package://' | xargs -I{} adb pull {} captures/apk/v1.0.40/
```

(Versión actual a la fecha del último captura: `1.0.40` / versionCode `1000040`, targetSdk 35.)

## 2. Empaquetar splits → `.apks` plano

`apk-mitm` espera un zip plano con los splits, **sin** prefijo `splits/`:

```bash
cd captures/apk/v1.0.40
zip -j ute_v1.0.40.apks base.apk split_config.arm64_v8a.apk split_config.es.apk split_config.xxxhdpi.apk
```

## 3. Patchear el bundle

```bash
npx --yes apk-mitm@latest ute_v1.0.40.apks
```

Lo que hace:

- Decodifica cada split con `apktool`.
- Inserta un `network_security_config.xml` que confía user-CAs por encima de las pinning declarations originales.
- Reescribe el manifest para apuntar a la nueva config.
- Re-empaqueta y firma con `uber-apk-signer` (cert debug autogenerado).

Salida: `ute_v1.0.40-patched.apks` (ahora con `*.apk` + `*.idsig`).

## 4. Reinstalar en el device

```bash
adb uninstall uy.com.ute.customers   # destructivo: pierde login guardado
mkdir patched && cd patched && unzip -o ../ute_v1.0.40-patched.apks "*.apk"
adb install-multiple -r base.apk split_config.arm64_v8a.apk split_config.es.apk split_config.xxxhdpi.apk
```

> ⚠️ Android 14+ y muchas ROMs (OxygenOS/ColorOS incluidos) bloquean instalaciones debug-signed con un diálogo de Play Protect: hay que tocar **"Detalles" → "Instalar de todos modos"** en la pantalla del device antes de que `adb install-multiple` retorne.

## 5. Instalar el CA de mitmproxy en el device como user-CA

mitmproxy genera el CA la primera vez que corre. Si ya lo corriste:

```bash
ls tooling/mitm-ca/mitmproxy-ca-cert.crt   # cert para Android (mismo PEM con extensión .crt)
adb push tooling/mitm-ca/mitmproxy-ca-cert.crt /sdcard/Download/
```

En el OnePlus:

1. **Settings → Security & privacy → More security & privacy → Encryption & credentials → Install a certificate → CA certificate**.
2. Aceptás el warning ("vas a perder garantías de privacidad…").
3. Seleccionás `mitmproxy-ca-cert.crt` desde Downloads.
4. Verificás en **Trusted credentials → User**: debe aparecer `mitmproxy / mitmproxy`.

Como la app fue patcheada con `network_security_config` permisivo, va a confiar en este user-CA.

## 6. Configurar el proxy en el WiFi del device

En el OnePlus 12:

1. **Settings → WiFi → (red conectada) → ⚙️ → Proxy → Manual**.
2. Hostname: IP del host (en este host: `192.168.2.10`).
3. Port: `8080`.
4. Sin bypass.

> Test rápido: abrí el navegador del device y andá a `http://mitm.it`. Si está bien proxeado, verás la página de instalación de certs de mitmproxy.

## 7. Levantar mitmdump y capturar

```bash
./tooling/run-mitm.sh login-flow
```

Eso abre `mitmdump` en `0.0.0.0:8080` y guarda el flow en `captures/flows/login-flow.mitm`.

Recorrido recomendado en la app, paso a paso:

1. Abrir la app — registración / login con email + teléfono.
2. Ingresar OTP del SMS.
3. Aterrizar en el dashboard — listar cuentas (suministros).
4. Tocar una cuenta → ver agreement, peak, último consumo, factura.
5. Si aplica: pedir lectura del medidor inteligente y esperar a que muestre voltaje/corriente.
6. Tocar "Pagos" / "Facturas" / "Recargas" / "Notificaciones" / "Mensajería" — flujos que el upstream-2023 nunca documentó.
7. Cerrar sesión (si la app lo permite) para capturar el flow de logout.

`Ctrl-C` para cerrar el dump. El `.mitm` queda en `captures/flows/`.

## 8. Inspeccionar la captura

```bash
uvx --from mitmproxy mitmweb -r captures/flows/login-flow.mitm --set listen_port=8081
```

Abre una UI en `http://localhost:8081` con todos los requests, headers, bodies y respuestas decodificadas.

## 9. Limpieza

- `adb uninstall uy.com.ute.customers` y reinstalar el APK oficial desde Play Store cuando ya no necesites capturar.
- Eliminar el user-CA: **Settings → Security → Trusted credentials → User → mitmproxy → Remove**.
- Quitar el proxy del WiFi.

## Troubleshooting

- **`SSL: certificate verify failed` en la app pese al user-CA**: el `network_security_config` no se aplicó (apk-mitm puede fallar silenciosamente en apps muy nuevas). Verificá decodificando con `apktool d base.apk` y mirando `res/xml/network_security_config.xml`.
- **App detecta root/Frida y se cierra**: improbable acá (apk-mitm no inyecta Frida). Si pasara, descomentar el rule de `<trust-anchors>` y revisar si la app implementa Play Integrity.
- **mitmdump no ve nada pero sí el navegador**: la app está bypasseando el proxy del sistema (algunas usan socket directo). Solución: redirigir tráfico con `iptables`/`pcap` (ver mitmproxy `--mode transparent`).
- **Diálogo "Detalles" en el device no aparece** y `adb install-multiple` queda colgado para siempre: matar el adb, volver a habilitar "Install via USB" en Developer options.

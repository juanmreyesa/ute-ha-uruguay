# UTE Uruguay

Lee tu consumo, importe del período, deuda y estado del suministro **directo de la API de la app móvil oficial de UTE**.

Soporta tarifas Simple, Doble Horario y Triple Horario — los buckets se autodetectan según tu plan tarifario.

Si tenés un **Shelly UTE** (Calefón, A/C, plan "Descubre tu consumo"), aparece como dispositivo separado con sensores de potencia, voltaje, estado del relé y porcentaje del consumo total.

## Configuración

Settings → Devices & Services → Add Integration → "UTE Uruguay" → documento (CI/RUT/BPS) + contraseña de la app móvil.

## Notas

- **Cero secrets hardcodeados**: el `client_id`/`client_secret` se obtienen en runtime del propio backend de UTE, igual que la app.
- La contraseña queda guardada en `.storage/core.config_entries` de Home Assistant en texto plano (estándar para integraciones cloud).
- Update interval: 30 minutos. Suficiente para consumo (datos del medidor llegan al backend con latencia de ~horas) y respeta el rate limiting de UTE.
- No oficial, no afiliado. UTE puede cambiar la API y romper la integración.

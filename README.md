# UTE Uruguay — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5)](https://hacs.xyz/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Integración no oficial para [UTE](https://www.ute.com.uy/) (Administración Nacional de Usinas y Trasmisiones Eléctricas, Uruguay) en Home Assistant. Lee tu consumo eléctrico, importe estimado del período, deuda, estado del suministro y los Shellys vinculados a tu cuenta — usando la misma API privada que la app móvil oficial.

> **Cero secrets hardcodeados**: el plugin obtiene `client_id`/`client_secret` en runtime desde el endpoint `/customers/setup` de UTE, igual que hace la app. Si UTE rota credenciales, se actualizan solas. Ver [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Sensores creados

Por **suministro**:
- `sensor.<dir>_consumo_punta` / `_fuera_de_punta` / `_llano` / `_valle` (kWh, según tarifa)
- `sensor.<dir>_consumo_total` (kWh)
- `sensor.<dir>_consumo_del_periodo` (kWh facturados desde inicio del ciclo)
- `sensor.<dir>_importe_estimado_del_periodo` (UYU del ciclo, +atributos `period_start/end`)
- `sensor.<dir>_estado_del_suministro` (`OK` / `INTERRUMPIDO`)

Por **cuenta**:
- `sensor.<dir>_deuda_total` (UYU)
- `sensor.<dir>_facturas_impagas` (count)

Por **Shelly UTE** (Calefón, A/C, etc.):
- `sensor.<nombre>_potencia_instantanea` (W)
- `sensor.<nombre>_voltaje` (V)
- `sensor.<nombre>_porcentaje_del_consumo_total` (%)
- `sensor.<nombre>_rssi` (dBm, deshabilitado por defecto)
- `binary_sensor.<nombre>_encendido` (relé on/off, `device_class: power`)
- `binary_sensor.<nombre>_programacion_activa` (schedule activo)
- `binary_sensor.<nombre>_bypass` (deshabilitado por defecto)

Compatible con el [Energy Dashboard](https://www.home-assistant.io/docs/energy/) — agregá los sensores `consumo_total` y `consumo_del_periodo` como medidores de red, y `potencia_instantanea` del Shelly como consumo individual.

## Instalación

### HACS (recomendado)
1. HACS → ⋮ → Custom repositories → `https://github.com/juanmreyesa/ute-ha-uruguay` (Type: Integration).
2. Buscá "UTE Uruguay" en HACS → Install.
3. Reiniciá HA.
4. Settings → Devices & Services → Add Integration → "UTE Uruguay" → ingresá tu documento (CI/RUT/BPS) y la contraseña que usás en la app móvil de UTE.

### Manual
Copiá `ha-integration/custom_components/ute_energy/` a `<config>/custom_components/ute_energy/` y reiniciá HA.

## Estructura del repo

```
ute-ha-uruguay/
├── ha-integration/
│   └── custom_components/ute_energy/   # custom component HA (instalable)
├── client-py/                          # cliente Python standalone (PyPI-ready)
│   ├── ute_client/                     #   async, httpx
│   └── demo.py                         #   CLI demo (getpass, env UTE_PASSWORD)
├── client-ts/                          # cliente TS para Node 20+ / Edge
│   ├── src/index.ts                    #   ESM, fetch global
│   └── demo.ts                         #   CLI demo
├── docs/
│   ├── PROTOCOL.md                     # spec del API privado (resp/req shapes)
│   └── CAPTURE.md                      # cómo reproducir la captura mitm con AVD
├── tooling/                            # scripts de RE / mitmproxy
└── scripts/sync-vendor.sh              # mantener client-py y ha-integration en sync
```

## Cliente standalone (Python)

```python
from ute_client import UteClient

async with UteClient() as c:
    await c.bootstrap()                     # zero-secret
    await c.login(documento, password)
    for acc in await c.accounts():
        bp = await c.billing_period_summary(acc.account_id)
        print(f"{bp.current_consumption_kwh} kWh / ${bp.current_spending_uyu}")
        for svc in await c.services(acc.account_id):
            tous = await c.consumption_by_tou(svc.service_point_id, plan=svc.tariff)
            ...
```

CLI demo:
```bash
cd client-py && uv venv && uv pip install -e . && python demo.py
```

## Cliente standalone (TypeScript)

Pensado para reuso en proyectos web/Node (p. ej. dashboards, bots) sin tocar HA.

```ts
import { UteClient } from "@caudata/ute-client";

const c = new UteClient();
await c.bootstrap();
await c.login(doc, pwd);
const accounts = await c.accounts();
```

```bash
cd client-ts && npm install && npx tsx demo.ts
```

## Disclaimer

Esta integración no es oficial ni está afiliada con UTE. Usa la API privada de la app móvil; UTE puede cambiarla y romper la integración sin aviso. Bajo MIT, sin garantía.

La contraseña queda guardada en `.storage/core.config_entries` de Home Assistant en texto plano (estándar para integraciones cloud HA).

## Contribuir

Issues, PRs y captures de nuevos endpoints son bienvenidos. Si capturás flows que descubren endpoints que faltan, abrí un issue con el `mitmdump` flow (sin tokens) y los agregamos al `PROTOCOL.md` + cliente.

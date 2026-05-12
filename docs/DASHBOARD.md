# Tarjeta del dashboard

Pegá esta tarjeta en tu dashboard principal: **Settings → Dashboards → tu dashboard → ⋮ → Edit dashboard → ➕ Add card → Manual** (al pie de la lista).

Reemplazá los IDs de las entidades por los tuyos (los ves en *Developer Tools → States*).

```yaml
type: vertical-stack
cards:
  - type: heading
    heading: UTE Uruguay
    icon: mdi:flash
  - type: glance
    show_state: true
    columns: 3
    entities:
      - entity: sensor.ute_uruguay_consumo_del_periodo
        name: Consumo período
      - entity: sensor.ute_uruguay_importe_estimado_del_periodo
        name: Importe estimado
      - entity: sensor.ute_uruguay_deuda_total
        name: Deuda
      - entity: sensor.ute_uruguay_consumo_punta_mes
        name: Punta (mes)
      - entity: sensor.ute_uruguay_consumo_fuera_de_punta_mes
        name: Fuera de punta (mes)
      - entity: sensor.ute_uruguay_consumo_total_mes
        name: Total (mes)
  - type: entities
    title: Calefón (Shelly UTE)
    entities:
      - entity: binary_sensor.ute_uruguay_encendido
        name: Estado del relé
      - entity: sensor.ute_uruguay_potencia_instantanea
        name: Potencia
      - entity: sensor.ute_uruguay_voltaje
        name: Voltaje
      - entity: sensor.ute_uruguay_porcentaje_del_consumo_total
        name: % del consumo total
      - entity: binary_sensor.ute_uruguay_programacion_activa
        name: Schedule activo
```

Para Energy Dashboard: **Settings → Dashboards → Energy → Electricity grid → Add consumption** y elegí `sensor.ute_uruguay_consumo_total_mes` (kWh, `state_class: total_increasing`). Para gasto: agregá `sensor.ute_uruguay_importe_estimado_del_periodo` (UYU).

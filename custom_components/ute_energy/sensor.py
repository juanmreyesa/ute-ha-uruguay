"""Sensores expuestos por la integración UTE Uruguay."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import UteCoordinator, _DeviceData, _ServiceData


# Etiquetas TOU canónicas de UTE → nombre legible para HA.
_TOU_LABELS: dict[str, str] = {
    "PUNTA": "punta",
    "F_PUNTA": "fuera de punta",
    "LLANO": "llano",
    "VALLE": "valle",
    "TRS": "consumo",  # tarifa simple (1 sólo bucket)
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: UteCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for account_id, services in coordinator.data.services_by_account.items():
        for sd in services:
            # Un sensor por bucket TOU presente en la respuesta del plan
            for tou_key in sd.consumption_by_tou_kwh:
                entities.append(_TouConsumptionSensor(coordinator, account_id, sd, tou_key))
            # Total del mes
            entities.append(_TotalConsumptionSensor(coordinator, account_id, sd))
            # Estado del suministro (texto, no on/off)
            entities.append(_StatusSensor(coordinator, account_id, sd))
            # Horario pico (solo si hay datos: TRD/TRT)
            if sd.peak_window:
                entities.append(_PeakWindowSensor(coordinator, account_id, sd))
            # Calidad y status admin son por servicio (varían con el depto).
            entities.append(_QualityDepartmentSensor(coordinator, account_id, sd))
            entities.append(_AdminStatusSensor(coordinator, account_id, sd))
        entities.append(_DebtSensor(coordinator, account_id))
        entities.append(_BillingSpendingSensor(coordinator, account_id))
        entities.append(_BillingConsumptionSensor(coordinator, account_id))
        entities.append(_UnpaidCountSensor(coordinator, account_id))
        # Métricas nacionales (% renovable, calidad país): 1 sensor por cuenta.
        entities.append(_RenewableSensor(coordinator, account_id))
        entities.append(_QualityGlobalSensor(coordinator, account_id))
        if account_id in coordinator.data.last_invoice_by_account:
            entities.append(_LastInvoiceSensor(coordinator, account_id))
        for sd in services:
            for dev in sd.devices:
                for desc in _DEVICE_SENSORS:
                    entities.append(
                        _DeviceSensor(coordinator, account_id, sd, dev, desc)
                    )
    async_add_entities(entities)


def _parse_pct(s: str | None) -> float | None:
    """Convierte '99,5 %' / '22%' / '22 %' → float. None si no parsea.

    UTE mezcla formatos: porcentajes de calidad usan coma decimal y sufijo
    " %" (ej. "99,5 %"); porcentajes de share usan punto sin espacio
    (ej. "22%"). Esta función absorbe ambos.
    """
    if not s:
        return None
    cleaned = s.replace("%", "").replace(",", ".").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────────
# Consumo TOU (dinámico según plan tarifario del cliente).
# ──────────────────────────────────────────────────────────────────────────
class _TouConsumptionSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """kWh consumidos en un bucket TOU del plan corriente."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: UteCoordinator,
        account_id: str,
        sd: _ServiceData,
        tou_key: str,
    ) -> None:
        super().__init__(coordinator)
        label = _TOU_LABELS.get(tou_key, tou_key.lower())
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._tou_key = tou_key
        self._attr_name = f"Consumo {label} (mes)"
        self._attr_translation_key = f"consumption_{tou_key.lower()}"
        self._attr_unique_id = f"{account_id}_{sd.service.service_point_id}_consumption_{tou_key.lower()}"
        self._attr_device_info = _device_info(account_id, sd)

    def _current_sd(self) -> _ServiceData | None:
        for sd in self.coordinator.data.services_by_account.get(self._account_id, []):
            if sd.service.service_point_id == self._service_point_id:
                return sd
        return None

    @property
    def native_value(self) -> Any:
        sd = self._current_sd()
        if not sd:
            return None
        return sd.consumption_by_tou_kwh.get(self._tou_key)


class _TotalConsumptionSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """Suma de todos los buckets TOU."""

    _attr_has_entity_name = True
    _attr_translation_key = "consumption_total"
    _attr_name = "Consumo total (mes)"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self, coordinator: UteCoordinator, account_id: str, sd: _ServiceData
    ) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._attr_unique_id = f"{account_id}_{sd.service.service_point_id}_consumption_total"
        self._attr_device_info = _device_info(account_id, sd)

    @property
    def native_value(self) -> Any:
        for sd in self.coordinator.data.services_by_account.get(self._account_id, []):
            if sd.service.service_point_id == self._service_point_id:
                return sd.total_consumption_kwh
        return None


# ──────────────────────────────────────────────────────────────────────────
# Estado, deuda, factura.
# ──────────────────────────────────────────────────────────────────────────
class _StatusSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "supply_status"
    _attr_name = "Estado del suministro"

    def __init__(
        self, coordinator: UteCoordinator, account_id: str, sd: _ServiceData
    ) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._attr_unique_id = f"{account_id}_{sd.service.service_point_id}_status"
        self._attr_device_info = _device_info(account_id, sd)

    @property
    def native_value(self) -> Any:
        for sd in self.coordinator.data.services_by_account.get(self._account_id, []):
            if sd.service.service_point_id == self._service_point_id:
                return "INTERRUMPIDO" if sd.is_interrupted else "OK"
        return None


class _PeakWindowSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """Ventana de horario pico (ej. '17:00 a 21:00') del suministro."""

    _attr_has_entity_name = True
    _attr_translation_key = "peak_window"
    _attr_name = "Horario pico"
    _attr_icon = "mdi:clock-alert"

    def __init__(
        self, coordinator: UteCoordinator, account_id: str, sd: _ServiceData
    ) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._attr_unique_id = f"{account_id}_{sd.service.service_point_id}_peak_window"
        self._attr_device_info = _device_info(account_id, sd)

    @property
    def native_value(self) -> Any:
        for sd in self.coordinator.data.services_by_account.get(self._account_id, []):
            if sd.service.service_point_id == self._service_point_id:
                return sd.peak_window or None
        return None


class _DebtSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "total_debt"
    _attr_name = "Deuda total"
    _attr_native_unit_of_measurement = "UYU"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: UteCoordinator, account_id: str) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{account_id}_total_debt"
        sd_first = next(
            iter(coordinator.data.services_by_account.get(account_id, [])), None
        )
        self._attr_device_info = (
            _device_info(account_id, sd_first) if sd_first else None
        )

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.total_debt_by_account.get(self._account_id)


class _BillingSpendingSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "billing_spending"
    _attr_name = "Importe estimado del período"
    _attr_native_unit_of_measurement = "UYU"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: UteCoordinator, account_id: str) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{account_id}_billing_spending"
        sd_first = next(
            iter(coordinator.data.services_by_account.get(account_id, [])), None
        )
        self._attr_device_info = (
            _device_info(account_id, sd_first) if sd_first else None
        )

    @property
    def native_value(self) -> Any:
        bp = self.coordinator.data.billing_period_by_account.get(self._account_id)
        return round(bp.spending_uyu, 2) if bp else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bp = self.coordinator.data.billing_period_by_account.get(self._account_id)
        if not bp:
            return {}
        return {"period_start": bp.initial_date, "period_end": bp.final_date}


class _BillingConsumptionSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "billing_consumption"
    _attr_name = "Consumo del período"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator: UteCoordinator, account_id: str) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{account_id}_billing_consumption"
        sd_first = next(
            iter(coordinator.data.services_by_account.get(account_id, [])), None
        )
        self._attr_device_info = (
            _device_info(account_id, sd_first) if sd_first else None
        )

    @property
    def native_value(self) -> Any:
        bp = self.coordinator.data.billing_period_by_account.get(self._account_id)
        return round(bp.consumption_kwh, 2) if bp else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bp = self.coordinator.data.billing_period_by_account.get(self._account_id)
        if not bp:
            return {}
        return {"period_start": bp.initial_date, "period_end": bp.final_date}


class _LastInvoiceSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """Importe de la última factura (UYU); doc + vencimiento como atributos."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_invoice"
    _attr_name = "Última factura"
    _attr_native_unit_of_measurement = "UYU"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:receipt"

    def __init__(self, coordinator: UteCoordinator, account_id: str) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{account_id}_last_invoice"
        sd_first = next(
            iter(coordinator.data.services_by_account.get(account_id, [])), None
        )
        self._attr_device_info = (
            _device_info(account_id, sd_first) if sd_first else None
        )

    @property
    def native_value(self) -> Any:
        inv = self.coordinator.data.last_invoice_by_account.get(self._account_id)
        return round(inv.total_amount, 2) if inv else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        inv = self.coordinator.data.last_invoice_by_account.get(self._account_id)
        if not inv:
            return {}
        return {
            "doc_number": inv.doc_number,
            "expiration_date": inv.expiration_date,
            "has_debt": inv.has_debt,
        }


class _RenewableSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """% de generación nacional desde fuentes renovables (último mes).

    Es info nacional: 1 sensor por cuenta, no por servicio.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "renewable_sources"
    _attr_name = "% renovable (UTE nacional)"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:leaf"
    _attr_entity_registry_enabled_default = False  # info-only, opt-in

    def __init__(self, coordinator: UteCoordinator, account_id: str) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{account_id}_renewable"
        sd_first = next(
            iter(coordinator.data.services_by_account.get(account_id, [])), None
        )
        self._attr_device_info = (
            _device_info(account_id, sd_first) if sd_first else None
        )

    @property
    def native_value(self) -> Any:
        return _parse_pct(
            self.coordinator.data.renewable_by_account.get(self._account_id, "")
        )


class _QualityGlobalSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """Calidad global del servicio UTE (%).

    Es info nacional: 1 sensor por cuenta, no por servicio.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "quality_global"
    _attr_name = "Calidad servicio (país)"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UteCoordinator, account_id: str) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{account_id}_quality_global"
        sd_first = next(
            iter(coordinator.data.services_by_account.get(account_id, [])), None
        )
        self._attr_device_info = (
            _device_info(account_id, sd_first) if sd_first else None
        )

    @property
    def native_value(self) -> Any:
        return _parse_pct(
            self.coordinator.data.quality_global_by_account.get(self._account_id, "")
        )


class _QualityDepartmentSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """Calidad del servicio en el departamento del suministro (%)."""

    _attr_has_entity_name = True
    _attr_translation_key = "quality_department"
    _attr_name = "Calidad servicio (depto)"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(
        self, coordinator: UteCoordinator, account_id: str, sd: _ServiceData
    ) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._attr_unique_id = f"{account_id}_{sd.service.service_point_id}_quality_dept"
        self._attr_device_info = _device_info(account_id, sd)

    def _current_sd(self) -> _ServiceData | None:
        for sd in self.coordinator.data.services_by_account.get(self._account_id, []):
            if sd.service.service_point_id == self._service_point_id:
                return sd
        return None

    @property
    def native_value(self) -> Any:
        sd = self._current_sd()
        return _parse_pct(sd.quality_department) if sd else None


class _AdminStatusSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    """Status admin del servicio: code "0" = OK, ≠"0" = aviso/incidencia."""

    _attr_has_entity_name = True
    _attr_translation_key = "admin_status"
    _attr_name = "Estado del servicio"
    _attr_icon = "mdi:information"

    def __init__(
        self, coordinator: UteCoordinator, account_id: str, sd: _ServiceData
    ) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._attr_unique_id = f"{account_id}_{sd.service.service_point_id}_admin_status"
        self._attr_device_info = _device_info(account_id, sd)

    def _current_sd(self) -> _ServiceData | None:
        for sd in self.coordinator.data.services_by_account.get(self._account_id, []):
            if sd.service.service_point_id == self._service_point_id:
                return sd
        return None

    @property
    def native_value(self) -> Any:
        sd = self._current_sd()
        if not sd:
            return None
        return "OK" if sd.status_code == "0" else (sd.status_description or sd.status_code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sd = self._current_sd()
        if not sd:
            return {}
        return {"code": sd.status_code, "description": sd.status_description}


class _UnpaidCountSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "unpaid_invoices"
    _attr_name = "Facturas impagas"
    _attr_icon = "mdi:file-document-alert"

    def __init__(self, coordinator: UteCoordinator, account_id: str) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._attr_unique_id = f"{account_id}_unpaid_count"
        sd_first = next(
            iter(coordinator.data.services_by_account.get(account_id, [])), None
        )
        self._attr_device_info = (
            _device_info(account_id, sd_first) if sd_first else None
        )

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.unpaid_count_by_account.get(self._account_id, 0)


# ──────────────────────────────────────────────────────────────────────────
# Sensores del Shelly UTE.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, kw_only=True)
class _DeviceSensorDesc(SensorEntityDescription):
    value_fn: Callable[[_DeviceData], Any] = lambda d: None


_DEVICE_SENSORS: tuple[_DeviceSensorDesc, ...] = (
    _DeviceSensorDesc(
        key="device_power",
        translation_key="device_power",
        name="Potencia instantánea",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.instant_consumption_w,
    ),
    _DeviceSensorDesc(
        key="device_voltage",
        translation_key="device_voltage",
        name="Voltaje",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda d: d.voltage_v,
    ),
    _DeviceSensorDesc(
        key="device_rssi",
        translation_key="device_rssi",
        name="RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        value_fn=lambda d: d.rssi_dbm,
        entity_registry_enabled_default=False,
    ),
    _DeviceSensorDesc(
        key="device_consumption_share",
        translation_key="device_consumption_share",
        name="Porcentaje del consumo total",
        icon="mdi:chart-pie",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _parse_pct(d.percentage_of_total_consumption),
        native_unit_of_measurement="%",
    ),
)


class _DeviceSensor(CoordinatorEntity[UteCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: _DeviceSensorDesc

    def __init__(
        self,
        coordinator: UteCoordinator,
        account_id: str,
        sd: _ServiceData,
        dev: _DeviceData,
        desc: _DeviceSensorDesc,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._device_id = dev.device_id
        self._attr_unique_id = f"{account_id}_{dev.device_id}_{desc.key}"
        self._attr_device_info = _shelly_device_info(coordinator, account_id, sd, dev)

    def _current_dev(self) -> _DeviceData | None:
        for sd in self.coordinator.data.services_by_account.get(self._account_id, []):
            if sd.service.service_point_id != self._service_point_id:
                continue
            for d in sd.devices:
                if d.device_id == self._device_id:
                    return d
        return None

    @property
    def available(self) -> bool:
        d = self._current_dev()
        return super().available and d is not None and d.online

    @property
    def native_value(self) -> Any:
        d = self._current_dev()
        return self.entity_description.value_fn(d) if d else None


# ──────────────────────────────────────────────────────────────────────────
# Helpers.
# ──────────────────────────────────────────────────────────────────────────
def _device_info(account_id: str, sd: _ServiceData) -> DeviceInfo:
    s = sd.service
    return DeviceInfo(
        identifiers={(DOMAIN, f"{account_id}:{s.service_point_id}")},
        name=s.short_address or f"Suministro {s.service_point_id}",
        manufacturer=MANUFACTURER,
        model=s.tariff_description,
        sw_version=s.ami_type,
        hw_version=s.meter_id,
        configuration_url="https://rocme.ute.com.uy/customersapp",
    )


def _shelly_device_info(
    coordinator: UteCoordinator,
    account_id: str,
    sd: _ServiceData,
    dev: _DeviceData,
) -> DeviceInfo:
    label = coordinator.data.device_category_labels.get(str(dev.category_id))
    model = label or f"Categoría {dev.category_id}"
    return DeviceInfo(
        # account_id en el identifier evita colisión cross-account dentro de
        # un mismo HA con dos suministros UTE distintos.
        identifiers={(DOMAIN, f"shelly:{account_id}:{dev.device_id}")},
        name=dev.name,
        manufacturer="Shelly (vía UTE)",
        model=model,
        via_device=(DOMAIN, f"{account_id}:{sd.service.service_point_id}"),
        configuration_url="https://rocme.ute.com.uy/customersapp",
    )

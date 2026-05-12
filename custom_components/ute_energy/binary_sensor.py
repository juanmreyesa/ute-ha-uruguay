"""Binary sensors expuestos por la integración UTE Uruguay.

Estado de los Shelly UTE como `binary_sensor.power` (on/off real).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UteCoordinator, _DeviceData, _ServiceData
from .sensor import _shelly_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: UteCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    for account_id, services in coordinator.data.services_by_account.items():
        for sd in services:
            for dev in sd.devices:
                entities.append(_DeviceOnBinarySensor(coordinator, account_id, sd, dev))
                entities.append(_DeviceBypassBinarySensor(coordinator, account_id, sd, dev))
                entities.append(_DeviceScheduleBinarySensor(coordinator, account_id, sd, dev))
    async_add_entities(entities)


class _DeviceBinaryBase(CoordinatorEntity[UteCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UteCoordinator,
        account_id: str,
        sd: _ServiceData,
        dev: _DeviceData,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._account_id = account_id
        self._service_point_id = sd.service.service_point_id
        self._device_id = dev.device_id
        self._attr_unique_id = f"{account_id}_{dev.device_id}_{unique_suffix}"
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


class _DeviceOnBinarySensor(_DeviceBinaryBase):
    """Indica si el aparato está consumiendo en este momento.

    UTE expone `isDeviceOn` (comando que UTE le manda al Shelly) y
    `instantConsumption` (medición real del consumo). Como la app no
    controla el Shelly, `isDeviceOn` es siempre `false` aunque el aparato
    esté efectivamente prendido. La señal fiable es el consumo > umbral.

    Atributo extra `ute_command_on` deja visible la otra señal por si UTE
    cambia su semántica en el futuro.
    """

    _attr_translation_key = "device_on"
    _attr_name = "Consumiendo"
    _attr_device_class = BinarySensorDeviceClass.POWER

    # Umbral para distinguir consumo real de standby/ruido de medición.
    _CONSUMPTION_THRESHOLD_W = 5.0

    def __init__(
        self,
        coordinator: UteCoordinator,
        account_id: str,
        sd: _ServiceData,
        dev: _DeviceData,
    ) -> None:
        super().__init__(coordinator, account_id, sd, dev, "is_on")

    @property
    def is_on(self) -> bool | None:
        d = self._current_dev()
        if not d:
            return None
        return (
            d.instant_consumption_w > self._CONSUMPTION_THRESHOLD_W
            or d.is_device_on
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._current_dev()
        if not d:
            return {}
        return {
            "ute_command_on": d.is_device_on,
            "instant_consumption_w": d.instant_consumption_w,
        }


class _DeviceBypassBinarySensor(_DeviceBinaryBase):
    """Indica si el device está en modo bypass (control manual sobre el schedule)."""

    _attr_translation_key = "device_bypass"
    _attr_name = "Bypass"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: UteCoordinator,
        account_id: str,
        sd: _ServiceData,
        dev: _DeviceData,
    ) -> None:
        super().__init__(coordinator, account_id, sd, dev, "is_bypass")

    @property
    def is_on(self) -> bool | None:
        d = self._current_dev()
        return d.is_in_bypass if d else None


class _DeviceScheduleBinarySensor(_DeviceBinaryBase):
    """Indica si hay un schedule (programación) activo controlando este device."""

    _attr_translation_key = "device_schedule_active"
    _attr_name = "Programación activa"

    def __init__(
        self,
        coordinator: UteCoordinator,
        account_id: str,
        sd: _ServiceData,
        dev: _DeviceData,
    ) -> None:
        super().__init__(coordinator, account_id, sd, dev, "schedule_active")

    @property
    def is_on(self) -> bool | None:
        d = self._current_dev()
        return d.is_schedule_active if d else None

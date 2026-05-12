"""Integración UTE Uruguay para Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import CONF_DOCUMENT, CONF_PASSWORD, DOMAIN
from .coordinator import UteCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurar entry de UTE Uruguay."""
    coordinator = UteCoordinator(
        hass,
        entry.data[CONF_DOCUMENT],
        entry.data[CONF_PASSWORD],
    )
    try:
        await coordinator.async_login()
    except Exception as e:
        from .api import UteAuthError

        if isinstance(e, UteAuthError):
            raise ConfigEntryAuthFailed(str(e)) from e
        raise ConfigEntryNotReady(str(e)) from e

    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Limpieza al remover el entry."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coord: UteCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coord.async_close()
        return True
    return False

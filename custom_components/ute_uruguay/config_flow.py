"""ConfigFlow: documento + contraseña, con reauth."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult

from .const import CONF_DOCUMENT, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DOCUMENT): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _mask_doc(doc: str) -> str:
    """Mostrar 47****63 en lugar de la cédula completa."""
    s = (doc or "").strip()
    if len(s) <= 4:
        return "****"
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"


async def _try_login(doc: str, password: str) -> str | None:
    """Devuelve `None` si OK, un error key (`invalid_auth`/`cannot_connect`)
    en caso contrario. Centralizada para no duplicar entre user y reauth.
    """
    from .api import UteApiError, UteAuthError, UteClient

    client = UteClient()
    try:
        await client.bootstrap()
        await client.login(doc, password)
        return None
    except UteAuthError:
        return "invalid_auth"
    except (UteApiError, httpx.HTTPError) as e:
        _LOGGER.warning("UTE bootstrap/login network error: %s", e)
        return "cannot_connect"
    finally:
        await client.aclose()


class UteUruguayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Flow para autenticar usuario."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            doc = user_input[CONF_DOCUMENT].strip()
            err = await _try_login(doc, user_input[CONF_PASSWORD])
            if err is None:
                # unique_id es el hash del documento — no leak de la cédula
                # en logs/storage de HA. Un único entry por documento.
                uid = hashlib.sha256(doc.encode("utf-8")).hexdigest()[:16]
                await self.async_set_unique_id(uid)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"UTE Uruguay ({_mask_doc(doc)})",
                    data={CONF_DOCUMENT: doc, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = err

        return self.async_show_form(
            step_id="user", data_schema=_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Re-auth disparado por el coordinator (ConfigEntryAuthFailed).

        Típicamente pasa cuando UTE invalida la sesión single-tenant (otro
        login con la misma cédula desde la app oficial o un segundo HA).
        """
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._reauth_entry is not None
        errors: dict[str, str] = {}
        doc = self._reauth_entry.data[CONF_DOCUMENT]
        if user_input is not None:
            err = await _try_login(doc, user_input[CONF_PASSWORD])
            if err is None:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={**self._reauth_entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            errors["base"] = err

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_REAUTH_SCHEMA,
            description_placeholders={"document": _mask_doc(doc)},
            errors=errors,
        )

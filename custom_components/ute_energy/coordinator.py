"""DataUpdateCoordinator que envuelve UteClient."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_PLAN, DEFAULT_SCAN_INTERVAL_MIN, DOMAIN, PLAN_BY_TARIFF

_LOGGER = logging.getLogger(__name__)


@dataclass
class _DeviceData:
    """Shelly UTE asociado al suministro."""

    device_id: int
    name: str
    provider: str  # SHELLY
    online: bool  # status == "online"
    category_id: str
    instant_consumption_w: float = 0.0
    voltage_v: float = 0.0
    rssi_dbm: int = 0
    is_device_on: bool = False
    is_in_bypass: bool = False
    is_schedule_active: bool = False
    percentage_of_total_consumption: str = ""


@dataclass
class _ServiceData:
    service: Any  # ute_client.Service
    # buckets devueltos por la API según el plan tarifario:
    # TRT → {"PUNTA","LLANO","VALLE"}; TRD → {"PUNTA","F_PUNTA"}; TRS → {"TRS"}
    consumption_by_tou_kwh: dict[str, float] = field(default_factory=dict)
    is_interrupted: bool = False
    peak_window: str = ""  # ej. "17:00 a 21:00"
    devices: list[_DeviceData] = field(default_factory=list)
    # Calidad de servicio del departamento (varía por servicePoint).
    # Viene como string "99,9 %"; conversión a float en el sensor.
    quality_department: str = ""
    # Status admin del servicio: "0" cuando todo OK; description suele ser null.
    status_code: str = ""
    status_description: str | None = None

    @property
    def plan_code(self) -> str:
        return PLAN_BY_TARIFF.get(self.service.tariff, DEFAULT_PLAN)

    @property
    def total_consumption_kwh(self) -> float:
        return sum(self.consumption_by_tou_kwh.values())


@dataclass
class _BillingPeriod:
    initial_date: str
    final_date: str
    spending_uyu: float
    consumption_kwh: float


@dataclass
class _LastInvoice:
    doc_number: str  # "T 7507283"
    expiration_date: str  # YYYY-MM-DD
    total_amount: float  # UYU
    has_debt: bool


@dataclass
class UteData:
    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    services_by_account: dict[str, list[_ServiceData]] = field(default_factory=dict)
    total_debt_by_account: dict[str, float] = field(default_factory=dict)
    unpaid_count_by_account: dict[str, int] = field(default_factory=dict)
    billing_period_by_account: dict[str, _BillingPeriod] = field(default_factory=dict)
    last_invoice_by_account: dict[str, _LastInvoice] = field(default_factory=dict)
    # Métricas nacionales devueltas por la API quality. Las agrupamos por
    # cuenta (no por servicio) porque su valor no depende del servicePoint
    # — UTE las repite igual en cada llamada. Strings tipo "99,5 %".
    renewable_by_account: dict[str, str] = field(default_factory=dict)
    quality_global_by_account: dict[str, str] = field(default_factory=dict)
    # categoryId → label legible (ej. "1" → "Termotanque"). Cache static
    # del catálogo UTE; se refresca con `device_categories_fetched=False`.
    device_category_labels: dict[str, str] = field(default_factory=dict)
    device_categories_fetched: bool = False


class UteCoordinator(DataUpdateCoordinator[UteData]):
    """Coordinator: llama al cliente UTE en intervalos y expone datos a sensores."""

    def __init__(self, hass: HomeAssistant, document: str, password: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL_MIN),
        )
        self._document = document
        self._password = password
        self._client = None

    async def async_login(self) -> None:
        # Importación tardía para que `requirements` se haya instalado.
        from .api import UteClient

        self._client = UteClient()
        await self._client.bootstrap()
        await self._client.login(self._document, self._password)

    async def async_close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _async_update_data(self) -> UteData:
        from .api import UteAuthError

        if self._client is None:
            await self.async_login()

        data = UteData()
        # Cache del scan previo para no perder labels si la llamada falla.
        prev = self.data
        if prev:
            data.device_category_labels = dict(prev.device_category_labels)
            data.device_categories_fetched = prev.device_categories_fetched
        try:
            today = date.today()
            start = today.replace(day=1).isoformat()
            end = today.isoformat()

            # Catálogo de categorías: cargar una vez por sesión. Es estático
            # (no cambia entre cuentas). El flag `device_categories_fetched`
            # evita re-llamar si UTE devolvió `[]` legítimamente (cliente sin
            # categorías habilitadas) — sin él, sería un GET extra cada poll.
            if not data.device_categories_fetched:
                try:
                    cats = await self._client.device_categories()
                    data.device_category_labels = {
                        str(c.get("categoryId")): str(c.get("description") or "")
                        for c in cats
                    }
                    data.device_categories_fetched = True
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning("device_categories failed: %s", e)

            for acc in await self._client.accounts():
                data.accounts[acc.account_id] = {
                    "alias": acc.alias,
                    "address": acc.address,
                }
                # /invoices/unpaids es el endpoint canónico — devuelve totalDebt
                # y la lista de facturas. Reemplaza el legacy /invoices/totalDebt.
                try:
                    unpaid = await self._client.unpaid_invoices(acc.account_id)
                except Exception as e:  # noqa: BLE001 — log y fallback
                    _LOGGER.warning(
                        "unpaid_invoices failed for account %s: %s", acc.account_id, e
                    )
                    unpaid = {"totalDebt": 0, "billsUnpaid": []}
                data.total_debt_by_account[acc.account_id] = float(
                    unpaid.get("totalDebt") or 0
                )
                data.unpaid_count_by_account[acc.account_id] = len(
                    unpaid.get("billsUnpaid") or []
                )
                # Última factura emitida (la más reciente del histórico).
                try:
                    invoices = await self._client.invoices_history(
                        acc.account_id, count=1
                    )
                    if invoices:
                        inv = invoices[0]
                        data.last_invoice_by_account[acc.account_id] = _LastInvoice(
                            doc_number=str(inv.get("docNumber") or ""),
                            expiration_date=str(inv.get("expirationDate") or "")[:10],
                            total_amount=float(inv.get("totalAmount") or 0),
                            has_debt=bool(inv.get("hasDebt")),
                        )
                    elif prev and acc.account_id in prev.last_invoice_by_account:
                        # Cache del scan previo si la API devolvió lista vacía.
                        data.last_invoice_by_account[acc.account_id] = (
                            prev.last_invoice_by_account[acc.account_id]
                        )
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning(
                        "invoices_history failed for account %s: %s",
                        acc.account_id,
                        e,
                    )
                    if prev and acc.account_id in prev.last_invoice_by_account:
                        data.last_invoice_by_account[acc.account_id] = (
                            prev.last_invoice_by_account[acc.account_id]
                        )
                # billing_period: si UTE devuelve 204/vacío para clientes nuevos
                # o falla transitoriamente, mantener el valor anterior en lugar
                # de tirar UpdateFailed (que marca TODO unavailable).
                try:
                    summary = await self._client.billing_period_summary(acc.account_id)
                    data.billing_period_by_account[acc.account_id] = _BillingPeriod(
                        initial_date=summary.initial_date,
                        final_date=summary.final_date,
                        spending_uyu=summary.current_spending_uyu,
                        consumption_kwh=summary.current_consumption_kwh,
                    )
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning(
                        "billing_period_summary failed for account %s: %s",
                        acc.account_id,
                        e,
                    )
                    if prev and acc.account_id in prev.billing_period_by_account:
                        data.billing_period_by_account[acc.account_id] = (
                            prev.billing_period_by_account[acc.account_id]
                        )
                services: list[_ServiceData] = []
                # Helper para buscar el _ServiceData homólogo del scan previo.
                # Lo usamos como fallback cuando un endpoint puntual falla.
                def _prev_sd(sp_id: str) -> _ServiceData | None:
                    if not prev:
                        return None
                    for old in prev.services_by_account.get(acc.account_id, []):
                        if old.service.service_point_id == sp_id:
                            return old
                    return None

                for svc in await self._client.services(acc.account_id):
                    sd = _ServiceData(service=svc)
                    old_sd = _prev_sd(svc.service_point_id)
                    try:
                        tous = await self._client.consumption_by_tou(
                            svc.service_point_id,
                            plan=sd.plan_code,
                            date_from=start,
                            date_to=end,
                        )
                        sd.consumption_by_tou_kwh = {
                            t.tou: t.consumption for t in tous
                        }
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning(
                            "consumption_by_tou failed for sp=%s: %s",
                            svc.service_point_id,
                            e,
                        )
                        if old_sd:
                            sd.consumption_by_tou_kwh = dict(
                                old_sd.consumption_by_tou_kwh
                            )
                    # Horario pico (sólo aplica TRD/TRT — TRS no tiene punta).
                    if svc.tariff in ("TRD", "TRT"):
                        try:
                            peak = await self._client.peak_window(
                                acc.account_id, svc.service_agreement_id
                            )
                            sd.peak_window = (
                                peak.get("selectedPeakStartDescription")
                                or peak.get("meterPeakStartDescription")
                                or ""
                            )
                        except Exception as e:  # noqa: BLE001
                            _LOGGER.warning(
                                "peak_window failed for sa=%s: %s",
                                svc.service_agreement_id,
                                e,
                            )
                            if old_sd:
                                sd.peak_window = old_sd.peak_window
                    try:
                        status = await self._client.supply_status(
                            acc.account_id,
                            svc.service_agreement_id,
                            svc.service_point_id,
                        )
                        sd.is_interrupted = bool(status.get("isInterrupted"))
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning(
                            "supply_status failed for sp=%s: %s",
                            svc.service_point_id,
                            e,
                        )
                        if old_sd:
                            sd.is_interrupted = old_sd.is_interrupted
                    # Calidad de servicio + % renovable.
                    # globalServiceQuality y renewableSources son nacionales:
                    # los guardamos a nivel cuenta (basta con el primer
                    # servicio que responda). departmentServiceQuality varía
                    # por depto → se queda en el _ServiceData.
                    try:
                        quality = await self._client.service_quality(
                            acc.account_id, svc.service_agreement_id
                        )
                        sd.quality_department = str(
                            quality.get("departmentServiceQuality") or ""
                        )
                        if not data.renewable_by_account.get(acc.account_id):
                            data.renewable_by_account[acc.account_id] = str(
                                (quality.get("demand") or {}).get("renewableSources") or ""
                            )
                        if not data.quality_global_by_account.get(acc.account_id):
                            data.quality_global_by_account[acc.account_id] = str(
                                quality.get("globalServiceQuality") or ""
                            )
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning(
                            "service_quality failed for sa=%s: %s",
                            svc.service_agreement_id,
                            e,
                        )
                    try:
                        status_short = await self._client.service_status_short(
                            acc.account_id, svc.service_agreement_id
                        )
                        sd.status_code = str(status_short.get("code") or "")
                        sd.status_description = status_short.get("description")
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning(
                            "service_status_short failed for sa=%s: %s",
                            svc.service_agreement_id,
                            e,
                        )
                    # Listar Shellys del servicePoint y obtener status en vivo
                    try:
                        dev_resp = await self._client.devices(svc.service_point_id)
                        for dev in dev_resp.get("devices") or []:
                            dd = _DeviceData(
                                device_id=dev.device_id,
                                name=dev.name,
                                provider=dev.provider,
                                online=dev.status == "online",
                                category_id=dev.category_id,
                            )
                            try:
                                ds = await self._client.device_status(dev.device_id)
                                dd.instant_consumption_w = ds.instant_consumption_w
                                dd.voltage_v = ds.voltage_v
                                dd.rssi_dbm = ds.rssi_dbm
                                dd.is_device_on = ds.is_device_on
                                dd.is_in_bypass = ds.is_in_bypass
                                dd.is_schedule_active = ds.is_schedule_active
                                dd.percentage_of_total_consumption = (
                                    ds.percentage_of_total_consumption
                                )
                            except Exception as e:  # noqa: BLE001
                                _LOGGER.warning(
                                    "device_status failed for device=%s: %s",
                                    dev.device_id,
                                    e,
                                )
                            sd.devices.append(dd)
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning(
                            "devices list failed for sp=%s: %s",
                            svc.service_point_id,
                            e,
                        )
                    services.append(sd)
                data.services_by_account[acc.account_id] = services
                # Si service_quality falló en todos los services de la cuenta,
                # renewable/quality_global account-level quedan sin entry. Usar
                # el valor del scan previo en vez de mostrar "None" en sensores.
                if prev and acc.account_id not in data.renewable_by_account:
                    if acc.account_id in prev.renewable_by_account:
                        data.renewable_by_account[acc.account_id] = (
                            prev.renewable_by_account[acc.account_id]
                        )
                if prev and acc.account_id not in data.quality_global_by_account:
                    if acc.account_id in prev.quality_global_by_account:
                        data.quality_global_by_account[acc.account_id] = (
                            prev.quality_global_by_account[acc.account_id]
                        )
        except UteAuthError as e:
            # Refresh token muerto: forzar reauth ConfigFlow.
            await self.async_close()
            raise ConfigEntryAuthFailed(str(e)) from e
        except Exception as e:  # noqa: BLE001 — HA pide UpdateFailed para errores transitorios
            raise UpdateFailed(str(e)) from e
        return data

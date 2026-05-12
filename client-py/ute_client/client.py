"""Cliente HTTP async para la API móvil UTE.

Implementa el flujo completo capturado de la app v1.0.40:
1. Bootstrap zero-secret via /customersapp/customers/setup.
2. Login ROPC (resource owner password) contra identityserver.ute.com.uy.
3. Refresh token automático con lock para evitar carrera.
4. Endpoints: accounts, services, consumption-by-TOU, status, deuda,
   facturas impagas, devices Shelly UTE + status en vivo.

Este cliente NO inyecta secrets ni telemetría falsa; usa exactamente lo que
la app móvil hace.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ute_client.models import (
    Account,
    BillingPeriodSummary,
    ConsumptionTOU,
    Device,
    DeviceStatus,
    Service,
)

_LOG = logging.getLogger(__name__)

API_BASE = "https://rocme.ute.com.uy/customersapp"
USER_AGENT = "Dart/3.7 (dart:io)"
APP_VERSION_CODE = 1000040  # versionCode de v1.0.40 (aparece en /overview/{}/version/{})


class UteAuthError(Exception):
    """Login inválido o token expirado e irrenovable."""


class UteApiError(Exception):
    """Error de API distinto a auth (4xx/5xx con cuerpo)."""


@dataclass
class _Token:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    scope: str

    @property
    def is_valid(self) -> bool:
        return time.time() < self.expires_at - 30  # 30s margen


@dataclass
class _OAuthConfig:
    authority: str  # identityserver.ute.com.uy
    client: str  # customers_mobile_app
    secret: str  # rotado por server
    scope: str  # customers.accounts
    # los campos gubUy* solo se usan si el usuario eligiera login federado
    # contra id.gub.uy; ROPC directo no los necesita y no los guardamos para
    # no mantener un secret extra en memoria.


class UteClient:
    """Cliente async. Uso:

        async with UteClient() as c:
            await c.bootstrap()
            await c.login("<documento>", "<password>")
            for acc in await c.accounts():
                ...
    """

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        # `httpx.AsyncClient(...)` carga el cert bundle de forma síncrona —
        # bloquea el event loop si se construye dentro de él. Aceptamos un
        # AsyncClient ya construido (ideal: en HA, pasarle
        # `homeassistant.helpers.httpx_client.get_async_client(hass)`) o lo
        # construimos lazy en un executor en el primer await.
        self._http_provided: httpx.AsyncClient | None = http
        self._http_lazy: httpx.AsyncClient | None = None
        self._oauth: _OAuthConfig | None = None
        self._unique_id: str | None = None
        self._token: _Token | None = None
        self._refresh_lock = asyncio.Lock()

    @property
    def _http(self) -> httpx.AsyncClient:
        c = self._http_provided or self._http_lazy
        if c is None:
            raise RuntimeError(
                "internal: _http accedido antes de _ensure_http(); "
                "llamar bootstrap() o usar `async with UteClient(...)` primero"
            )
        return c

    async def _ensure_http(self) -> None:
        if self._http_provided is not None or self._http_lazy is not None:
            return
        loop = asyncio.get_running_loop()
        self._http_lazy = await loop.run_in_executor(None, _make_default_http_client)

    async def __aenter__(self) -> "UteClient":
        await self._ensure_http()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Cerrar el HTTP client subyacente. Idempotente.

        Sólo cerramos el client que NOSOTROS creamos. Si alguien externo nos
        pasó uno (HA via get_async_client), su lifecycle no nos pertenece.
        """
        if self._http_lazy is not None:
            await self._http_lazy.aclose()
            self._http_lazy = None

    # ------------------------------------------------------------------
    # 1. Bootstrap (zero-secret): obtener oAuthConfiguration del server.
    # ------------------------------------------------------------------
    async def bootstrap(self, registration_id: str = "", device_info: list | None = None) -> None:
        """Llamar UNA VEZ antes de login. Obtiene client_id/secret y unique_id."""
        await self._ensure_http()
        # GET flag de bypass — si está activo, la app salta integrity check.
        # No es estrictamente necesario para nosotros, pero seguimos el patrón
        # de la app y un fallo acá es informativo, no bloquea login.
        try:
            await self._http.get(f"{API_BASE}/flags/SecurityChecksBypass")
        except httpx.HTTPError as e:
            _LOG.debug("flag fetch failed (non-fatal): %s", e)

        r = await self._http.post(
            f"{API_BASE}/customers/setup",
            json={"registrationId": registration_id, "deviceInfo": device_info or []},
            headers={"content-type": "application/json; charset=utf-8"},
        )
        if r.status_code >= 400:
            raise UteApiError(f"setup → {r.status_code}: {r.text[:200]}")
        try:
            body = r.json()
            cfg = body["oAuthConfiguration"]
            self._oauth = _OAuthConfig(
                authority=cfg["authority"],
                client=cfg["client"],
                secret=cfg["secret"],
                scope=cfg["scope"],
            )
            self._unique_id = body["uniqueId"]
        except (KeyError, TypeError, ValueError) as e:
            raise UteApiError(
                f"unexpected /customers/setup shape: {r.text[:200]}"
            ) from e
        _LOG.info("bootstrap OK, client=%s scope=%s", cfg["client"], cfg["scope"])

    # ------------------------------------------------------------------
    # 2. Login ROPC.
    # ------------------------------------------------------------------
    async def login(self, username: str, password: str) -> None:
        """Autenticar con CI/RUT/BPS + password de UTE (no es id.gub.uy)."""
        if not self._oauth:
            raise RuntimeError("Llamar bootstrap() antes de login()")
        await self._oauth_token(
            grant_type="password",
            extra={"username": username, "password": password},
        )
        # Notificar al backend que el usuario se logueó (telemetría).
        await self._post(
            f"{API_BASE}/customers/loggedin",
            json={"uniqueId": self._unique_id},
        )

    async def _oauth_token(self, *, grant_type: str, extra: dict[str, str]) -> None:
        if self._oauth is None:
            raise RuntimeError("Llamar bootstrap() antes de pedir token")
        basic = base64.b64encode(
            f"{self._oauth.client}:{self._oauth.secret}".encode()
        ).decode()
        body = {"grant_type": grant_type, **extra}
        r = await self._http.post(
            f"{self._oauth.authority}/connect/token",
            data=body,
            headers={
                "authorization": f"Basic {basic}",
                "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            },
        )
        if r.status_code in (400, 401):
            try:
                err = r.json()
            except Exception:
                err = {"error_description": r.text[:200]}
            raise UteAuthError(
                f"{err.get('error') or r.status_code}: {err.get('error_description') or ''}"
            )
        if r.status_code >= 400:
            # No incluyo body acá porque el cuerpo de error puede contener
            # tokens parcialmente formados o headers reflejados.
            raise UteApiError(f"/connect/token → {r.status_code}")
        try:
            tok = r.json()
            self._token = _Token(
                access_token=tok["access_token"],
                refresh_token=tok.get("refresh_token", ""),
                expires_at=time.time() + int(tok["expires_in"]),
                scope=tok.get("scope", ""),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise UteApiError("unexpected /connect/token response shape") from e

    async def _refresh_if_needed(self) -> None:
        # Lock para evitar que múltiples requests concurrentes hagan token refresh
        # en paralelo (algunos IdP rotan refresh_token y solo el primero queda válido).
        async with self._refresh_lock:
            if self._token and self._token.is_valid:
                return
            if self._token and self._token.refresh_token:
                try:
                    await self._oauth_token(
                        grant_type="refresh_token",
                        extra={"refresh_token": self._token.refresh_token},
                    )
                    return
                except UteAuthError:
                    self._token = None  # refresh definitivamente inválido
            raise UteAuthError("Token expirado y refresh inválido — re-login")

    # ------------------------------------------------------------------
    # 3. HTTP helper authenticated.
    # ------------------------------------------------------------------
    def _bearer(self) -> dict[str, str]:
        if self._token is None:
            raise RuntimeError("Llamar login() antes de hacer requests autenticados")
        return {"authorization": f"Bearer {self._token.access_token}"}

    async def _get(self, url: str) -> httpx.Response:
        await self._refresh_if_needed()
        r = await self._http.get(url, headers=self._bearer())
        if r.status_code == 401 and self._token is not None:
            # Token rechazado; forzar refresh sin descartar el refresh_token.
            self._token.expires_at = 0
            await self._refresh_if_needed()
            r = await self._http.get(url, headers=self._bearer())
        if r.status_code >= 400:
            raise UteApiError(f"GET {url} → {r.status_code}: {r.text[:200]}")
        return r

    async def _post(self, url: str, *, json: dict[str, Any] | None = None) -> httpx.Response:
        await self._refresh_if_needed()
        r = await self._http.post(
            url,
            json=json,
            headers={
                **self._bearer(),
                "content-type": "application/json; charset=utf-8",
            },
        )
        if r.status_code == 401 and self._token is not None:
            self._token.expires_at = 0
            await self._refresh_if_needed()
            r = await self._http.post(
                url,
                json=json,
                headers={
                    **self._bearer(),
                    "content-type": "application/json; charset=utf-8",
                },
            )
        if r.status_code >= 400:
            raise UteApiError(f"POST {url} → {r.status_code}: {r.text[:200]}")
        return r

    # ------------------------------------------------------------------
    # 4. Endpoints públicos del cliente.
    # ------------------------------------------------------------------
    async def accounts(self) -> list[Account]:
        r = await self._get(f"{API_BASE}/accounts")
        return [Account.from_json(x) for x in r.json()]

    async def services(self, account_id: str) -> list[Service]:
        r = await self._get(f"{API_BASE}/accounts/{account_id}/services")
        return [Service.from_json(x) for x in r.json()]

    async def consumption_by_tou(
        self,
        service_point_id: str,
        plan: str = "TRD",
        date_from: str = "",
        date_to: str = "",
    ) -> list[ConsumptionTOU]:
        """Consumo por horario (TOU) para un período.

        `plan` es el código tarifario UTE. Los modernos son `TRS`/`TRD`/`TRT`
        (simple/doble/triple horario residencial) — el coordinator usa éstos
        vía `PLAN_BY_TARIFF`. Las variantes legacy `TRIPLERES17/18/19` siguen
        aceptadas por el upstream pero ya no son la API canónica.
        """
        url = f"{API_BASE}/accounts/{service_point_id}/calculateConsumptionForPlan/{plan}/{date_from}/{date_to}"
        r = await self._get(url)
        return [ConsumptionTOU.from_json(x) for x in r.json()]

    async def billing_period_summary(self, account_id: str) -> BillingPeriodSummary:
        """Resumen del período de facturación corriente: kWh + UYU.

        Es el endpoint que alimenta el header de la home de la app
        ("315 kWh - $2.622 desde 16/04").
        """
        r = await self._post(
            f"{API_BASE}/accounts/consumption/simulation",
            json={"accountId": account_id},
        )
        return BillingPeriodSummary.from_json(r.json())

    async def total_debt(self, account_id: str) -> float:
        r = await self._get(f"{API_BASE}/invoices/totalDebt/{account_id}")
        return _parse_number(r.text)

    async def unpaid_invoices(self, account_id: str) -> dict[str, Any]:
        """Resumen canónico de facturas impagas. Reemplaza al legacy
        `/invoices/totalDebt/{id}` (que sólo devolvía el monto plano).

        → {"billsUnpaid": [{"invoiceId":..., "docNumber":..., "expirationDate":...,
                            "totalAmount":..., "monthCharges":..., "totalDebt":...,
                            "hasDebt": bool, ...}, ...],
           "totalDebt": float,
           "messageCode": str|None,
           "messageDesc": str|None}
        """
        r = await self._get(f"{API_BASE}/invoices/unpaids/{account_id}")
        if r.status_code == 204 or not r.text.strip():
            return {"billsUnpaid": [], "totalDebt": 0, "messageCode": None, "messageDesc": None}
        return r.json()

    async def invoice_pdf(self, invoice_id: str, doc_number: str) -> bytes:
        """Descarga el PDF de una factura concreta.

        `doc_number` viene de `invoices_history()` ítem (ej. "T 7507283").
        Algunas variantes esperan url-encoded; pasar el string raw funciona en
        la captura mitm de la app oficial.
        """
        r = await self._get(f"{API_BASE}/invoices/file/{invoice_id}/{doc_number}")
        return r.content

    async def invoices_history(
        self, account_id: str, count: int = 36
    ) -> list[dict[str, Any]]:
        """Histórico de las últimas N facturas (default 36 ≈ 3 años).

        → [{"invoiceId":"029360441551", "docNumber":"T 7507283",
            "expirationDate":"2026-05-04T00:00:00", "totalAmount":4225,
            "previousDebt":0, "monthCharges":4225, "totalDebt":0,
            "hasDebt":false, "month":0, "year":0}, ...]
        """
        r = await self._get(f"{API_BASE}/invoices/{account_id}/{count}")
        return r.json() if r.text.strip() else []

    async def consumption_chart(
        self, account_id: str, service_agreement_id: str, kind: str = "activeconsumption"
    ) -> dict[str, Any]:
        """Curva mensual histórica de consumo.

        `kind` ∈ {activeconsumption, consumptionevolution, powerconsumption,
        reactiveconsumption}. Retorna 204 No Content cuando UTE no tiene esa
        serie para el cliente (powerconsumption sólo aplica a clientes
        industriales, p.ej.).
        """
        r = await self._get(
            f"{API_BASE}/invoices/charts/{account_id}/{kind}/{service_agreement_id}"
        )
        if r.status_code == 204 or not r.text.strip():
            return {"series": [], "averageConsumption": 0.0}
        return r.json()

    async def supply_status(
        self, account_id: str, service_agreement_id: str, service_point_id: str
    ) -> dict[str, Any]:
        r = await self._get(
            f"{API_BASE}/accounts/{account_id}/services/{service_agreement_id}/{service_point_id}/status"
        )
        return r.json()

    async def peak_window(
        self, account_id: str, service_agreement_id: str
    ) -> dict[str, Any]:
        """Horario pico configurado (TRD/TRT): ventana de tarifa más cara.

        → {"meterPeakStart": int, "selectedPeakStartDescription": "17:00 a 21:00",
           "meterPeakStartDescription": "17:00 a 21:00", "selectedPeakStartDate": "...",
           "meterPeakStartDate": "...", "meterId": "...", "servicePointId": "...",
           "processPending": bool, ...}
        """
        r = await self._get(
            f"{API_BASE}/accounts/{account_id}/services/{service_agreement_id}/peak"
        )
        return r.json()

    async def devices(self, service_point_id: str) -> dict[str, Any]:
        """Lista de devices smart (Shelly UTE) vinculados al servicePoint.

        → {"allowEnrollNewDevice": bool,
           "devices": [Device, ...],
           "plans": [{applicationId, status, name, maxDevices, allowEnroll}, ...]}
        """
        r = await self._get(f"{API_BASE}/device/{service_point_id}")
        body = r.json()
        body["devices"] = [Device.from_json(d) for d in body.get("devices") or []]
        return body

    async def device_status(self, device_id: int) -> DeviceStatus:
        """Lectura instantánea del Shelly UTE: V, W, RSSI, on/off, schedule."""
        r = await self._get(f"{API_BASE}/device/{device_id}/status")
        return DeviceStatus.from_json(r.json())

    async def consumption_breakdown(
        self, service_point_id: str, device_id: int, date: str
    ) -> dict[str, Any]:
        """Desglose de consumo por categoría (refrigerador, A/C, calefón, otros).

        `date` en formato YYYY-MM-DD (la API la usa para escoger período).
        """
        # API espera el date como query param (?date=YYYY-MM-DD); probar.
        r = await self._get(
            f"{API_BASE}/device/consumptionBreakdown/{service_point_id}/{device_id}?date={date}"
        )
        return r.json()

    async def messages_unread(self) -> int:
        r = await self._get(f"{API_BASE}/messages/unread")
        return int(_parse_number(r.text))

    async def service_quality(
        self, account_id: str, service_agreement_id: str
    ) -> dict[str, Any]:
        """Calidad de servicio + % renovable de la matriz UTE.

        → {"demand": {"renewableSources": "99,5 %"},
           "globalServiceQuality": "99,9 %",
           "departmentServiceQuality": "99,9 %"}

        Los porcentajes vienen como string con coma decimal y sufijo " %".
        Útil para sensores: % renovable nacional, calidad país, calidad depto.
        """
        r = await self._get(
            f"{API_BASE}/accounts/{account_id}/services/{service_agreement_id}/quality"
        )
        return r.json()

    async def service_status_short(
        self, account_id: str, service_agreement_id: str
    ) -> dict[str, Any]:
        """Status corto del servicio (≠ supply_status, que requiere servicePointId).

        → {"code": "0", "description": null}  cuando todo OK.
        Code distinto de "0" indica novedades administrativas o de suministro.
        """
        r = await self._get(
            f"{API_BASE}/accounts/{account_id}/services/{service_agreement_id}/status"
        )
        return r.json()

    async def device_categories(self) -> list[dict[str, str]]:
        """Catálogo estático de categorías de electrodomésticos.

        → [{"categoryId":"6","description":"Aire acondicionado"}, ...]
        El servicePointId del path da igual: la respuesta es la misma para
        toda la base. Útil para resolver `categoryId` → label en UI.
        """
        r = await self._get(f"{API_BASE}/device/0/category")
        body = r.json()
        return body.get("categories", [])

    async def device_check(self, device_id: int) -> bool:
        """Health check binario del device. Devuelve `true` cuando UTE puede
        contactar el Shelly y leer su estado, `false` durante reconexiones.
        """
        r = await self._get(f"{API_BASE}/device/{device_id}/check")
        return r.text.strip().lower() == "true"

    async def device_online_status(self, device_id: int) -> str:
        """Estado online/offline del device → {"status":"online"|"offline"}.

        Endpoint barato (mucho más liviano que `device_status`), pensado para
        polling de presencia.
        """
        r = await self._get(f"{API_BASE}/device/{device_id}/status/check")
        return str(r.json().get("status", "unknown"))

    async def home_overview(
        self, account_id: str, version: int = 1
    ) -> dict[str, Any]:
        """Discovery de zonas/widgets habilitados para esta cuenta.

        → {"suppliesCount": int,
           "zones": [{"zoneId":"OV01","widgetId":"AccountTotalDebtWidget"}, ...],
           "shortcuts": [{"id":int,"leadingIcon":str,"title":str,...}, ...]}

        La integración HA puede usar `zones` para decidir qué sensores
        instanciar dinámicamente (no todos los servicios tienen TimeBand).
        """
        r = await self._get(
            f"{API_BASE}/overview/{account_id}/version/{version}"
        )
        return r.json()

    async def mark_logged_in(self, unique_id: str) -> dict[str, Any]:
        """Notifica al backend que la sesión está activa y recibe behaviours
        (banners/promos a mostrar). La app la llama después de cada login;
        el backend devuelve `{"behaviours": [...]}` con flags de UI.
        """
        r = await self._post(
            f"{API_BASE}/customers/loggedin",
            json={"uniqueId": unique_id},
        )
        return r.json()


def _parse_number(text: str) -> float:
    """Body plano `0` / `1234.50` / `1234,50` o vacío.

    Acepta ambos separadores decimales — UTE devuelve punto en la mayoría
    de los endpoints pero algunos campos legacy usan coma uruguaya.
    """
    s = (text or "").strip()
    if not s:
        return 0.0
    # JSON strings vienen entre comillas (`"0"`); las pelamos defensivamente.
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    # Solo reemplazamos coma por punto si NO hay punto ya (evita romper
    # formatos europeos `1.234,50` — improbable acá, pero defensivo).
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError as e:
        raise UteApiError(f"esperaba número plano, recibí: {s[:80]!r}") from e


def _make_default_http_client() -> httpx.AsyncClient:
    """Constructor sync — pensado para invocarse en executor para no
    bloquear el event loop con la inicialización del SSL context."""
    return httpx.AsyncClient(
        timeout=30.0,
        headers={
            "user-agent": USER_AGENT,
            "accept-encoding": "gzip",
        },
    )

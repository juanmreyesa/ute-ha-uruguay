"""Modelos de datos para responses del API UTE."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Account:
    """Cuenta de cliente UTE (un titular puede tener varios accounts)."""

    account_id: str
    alias: str
    address: str
    icon: str
    is_authorized: bool
    third_party: bool

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Account":
        return cls(
            account_id=data["accountId"],
            alias=data.get("alias") or "",
            address=data.get("address") or "",
            icon=data.get("icon") or "home",
            is_authorized=bool(data.get("isAuthorized")),
            third_party=bool(data.get("thirdParty")),
        )


@dataclass
class Service:
    """Suministro eléctrico (servicePoint) bajo una cuenta."""

    service_agreement_id: str
    service_point_id: str
    service_agreement_type: str
    service_agreement_status: int
    address: str
    short_address: str
    city: str
    department: str
    zip_code: str
    tariff: str  # TRS|TRD|TRT
    tariff_description: str
    contracted_power_on_peak: float | None
    contracted_power_on_valley: float | None
    contracted_power_on_flat: float | None
    voltage: str
    service_type: str  # MONOFASICO|TRIFASICO|...
    meter_id: str | None
    ami_present: bool
    ami_type: str | None  # KAIFA, ...

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Service":
        return cls(
            service_agreement_id=data["serviceAgreementId"],
            service_point_id=data["servicePointId"],
            service_agreement_type=data.get("serviceAgreementType") or "",
            service_agreement_status=int(data.get("serviceAgreementStatus") or 0),
            address=data.get("address") or "",
            short_address=data.get("shortAddress") or "",
            city=data.get("city") or "",
            department=data.get("department") or "",
            zip_code=data.get("zipCode") or "",
            tariff=data.get("tariff") or "",
            tariff_description=data.get("tariffDescription") or "",
            contracted_power_on_peak=data.get("contractedPowerOnPeak"),
            contracted_power_on_valley=data.get("contractedPowerOnValley"),
            contracted_power_on_flat=data.get("contractedPowerOnFlat"),
            voltage=data.get("voltage") or "",
            service_type=data.get("serviceType") or "",
            meter_id=data.get("meterId"),
            ami_present=bool(data.get("amiPresent")),
            ami_type=data.get("amiType"),
        )


@dataclass
class BillingPeriodSummary:
    """Resumen de consumo + importe estimado del período de facturación corriente.
    Lo expone /customersapp/accounts/consumption/simulation."""

    initial_date: str  # YYYY-MM-DD
    final_date: str  # YYYY-MM-DD
    current_spending_uyu: float
    current_consumption_kwh: float
    error_message: str | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "BillingPeriodSummary":
        # initialDate/finalDate pueden venir `null` para clientes recién dados
        # de alta (UTE aún no liquidó un período). En ese caso devolvemos
        # strings vacíos en lugar de explotar con TypeError en slice de None.
        ini = data.get("initialDate") or ""
        fin = data.get("finalDate") or ""
        return cls(
            initial_date=str(ini)[:10],
            final_date=str(fin)[:10],
            current_spending_uyu=float(data.get("currentSpending") or 0),
            current_consumption_kwh=float(data.get("currentConsumption") or 0),
            error_message=data.get("errorMessage"),
        )


@dataclass
class Device:
    """Dispositivo smart vinculado al servicePoint (típicamente Shelly UTE)."""

    device_id: int
    name: str
    provider: str  # "SHELLY"
    status: str  # "online" | "offline"
    category_id: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Device":
        return cls(
            device_id=int(data["deviceId"]),
            name=data.get("name") or "",
            provider=data.get("provider") or "",
            status=data.get("status") or "",
            category_id=data.get("categoryId") or "",
        )


@dataclass
class DeviceStatus:
    """Lectura instantánea del device (Shelly UTE) — V, W, RSSI, on/off."""

    device_id: int
    instant_consumption_w: float  # potencia instantánea (W)
    voltage_v: float
    rssi_dbm: int
    is_device_on: bool
    is_in_bypass: bool
    is_schedule_on: bool
    is_schedule_active: bool
    percentage_of_total_consumption: str  # ej "22%"

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DeviceStatus":
        return cls(
            device_id=int(data["deviceId"]),
            instant_consumption_w=float(data.get("instantConsumption") or 0),
            voltage_v=float(data.get("voltage") or 0),
            rssi_dbm=int(data.get("rssi") or 0),
            is_device_on=bool(data.get("isDeviceOn")),
            is_in_bypass=bool(data.get("isInBypass")),
            is_schedule_on=bool(data.get("isScheduleOn")),
            is_schedule_active=bool(data.get("isScheduleActive")),
            percentage_of_total_consumption=str(
                data.get("percentageOfTotalConsumption") or ""
            ),
        )


@dataclass
class ConsumptionTOU:
    """Consumo agrupado por horario (Time-Of-Use): PUNTA / LLANO / VALLE."""

    tou: str  # PUNTA | LLANO | VALLE
    consumption: float
    uom: str  # kWh
    plan: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ConsumptionTOU":
        return cls(
            tou=data["tou"],
            consumption=float(data["consumption"]),
            uom=data.get("uom") or "kWh",
            plan=data.get("plan") or "",
        )

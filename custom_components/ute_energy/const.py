"""Constantes para la integración UTE Uruguay."""
from __future__ import annotations

DOMAIN = "ute_energy"
MANUFACTURER = "UTE"
MODEL_ATTR = "amiType"

CONF_DOCUMENT = "document"  # CI / RUT / BPS
CONF_PASSWORD = "password"

DEFAULT_SCAN_INTERVAL_MIN = 30  # consumption changes slowly
# Mapeo tariff → plan code que el endpoint
# /accounts/{sp}/calculateConsumptionForPlan/{plan}/{from}/{to} acepta para
# devolver TOU buckets coherentes con la facturación real del cliente.
PLAN_BY_TARIFF = {
    "TRS": "TRS",  # simple → 1 sólo bucket (uniforme)
    "TRD": "TRD",  # doble horario → PUNTA + F_PUNTA
    "TRT": "TRT",  # triple horario → PUNTA + LLANO + VALLE
}
DEFAULT_PLAN = "TRD"

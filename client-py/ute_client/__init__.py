"""Cliente Python para la API privada de la app móvil UTE.

Patrón "zero-secret": las credenciales OAuth (client_id/secret y endpoints
gub.uy) no están hardcoded en el código. Se obtienen en runtime con
`POST /customersapp/customers/setup`, igual que hace la app oficial. Si UTE
las rota, el cliente las recoge automáticamente al próximo bootstrap.

Ver `docs/PROTOCOL.md` para la spec completa.
"""

from ute_client.client import UteClient, UteAuthError, UteApiError
from ute_client.models import (
    Account,
    BillingPeriodSummary,
    ConsumptionTOU,
    Device,
    DeviceStatus,
    Service,
)

__all__ = [
    "UteClient",
    "UteAuthError",
    "UteApiError",
    "Account",
    "BillingPeriodSummary",
    "ConsumptionTOU",
    "Device",
    "DeviceStatus",
    "Service",
]

"""mitmproxy addon con dos responsabilidades:

1) Bypass del integrity check de la app UTE: interceptar
   GET /customersapp/flags/SecurityChecksBypass y devolver
   {"active": true} sin tocar el server real. Esto evita el abort
   Dart-side cuando se detecta emulator/compromised/tampered.

2) **Workaround para netsimd SIGSEGV (Android Emulator 36.5.11)**:
   evitar que mitmproxy responda `502 Bad Gateway` a los CONNECT que
   netsim genera contra IPs internas del SLIRP del emulador
   (10.0.2.3:853 — SLIRP DNS-over-TLS forwarder — y otros puertos del
   bloque 10.0.2.0/24). El bug de libslirp-rs en netsim crashea con
   SIGSEGV cuando recibe 502 y arrastra a qemu-system con él. La
   solución acá es responder 200 No Content sin abrir TLS, lo que
   netsim trata como conexión cerrada limpia.

Uso:
  ./tooling/run-mitm.sh ute-bypass
"""
import json

from mitmproxy import http

# ---------------------------------------------------------------------------
# 1. SecurityChecksBypass flag — schema {"active": <bool>}
# ---------------------------------------------------------------------------
_TRUTHY = {"active": True}


def _is_security_flag(flow: http.HTTPFlow) -> bool:
    host = flow.request.pretty_host or flow.request.host
    if "rocme.ute.com.uy" not in host:
        return False
    return "/flags/SecurityChecksBypass" in flow.request.path


# ---------------------------------------------------------------------------
# 2. Hosts/ports que NO debemos intentar proxy. Para estos respondemos un 200
#    vacío en vez de 502, evitando el SIGSEGV de netsimd.
# ---------------------------------------------------------------------------
def _is_slirp_internal(flow: http.HTTPFlow) -> bool:
    host = flow.request.pretty_host or flow.request.host or ""
    # AVD SLIRP virtual addresses: 10.0.2.{2,3,15} (gateway, DNS, host)
    if host.startswith("10.0.2."):
        return True
    # IPv6 outbound — el AVD a veces los redirige al proxy aunque tenga
    # ipv6=off; respondemos vacío en vez de 502.
    if host.startswith("2") and ":" in host and "." not in host:
        return True
    return False


class SecurityChecksBypass:
    """Pone {"active":true} al flag de bypass para que la app no aborte
    por emulator/tampered/compromised."""

    def request(self, flow: http.HTTPFlow) -> None:
        if _is_slirp_internal(flow):
            # Cerrar limpio antes de que mitm intente proxy y responda 502.
            flow.response = http.Response.make(
                200,
                b"",
                {"content-type": "application/octet-stream"},
            )
            return
        if _is_security_flag(flow):
            flow.response = http.Response.make(
                200,
                json.dumps(_TRUTHY).encode("utf-8"),
                {"content-type": "application/json; charset=utf-8"},
            )

    def response(self, flow: http.HTTPFlow) -> None:
        # Sólo aplicamos override si el flag llegó al server (en teoría
        # request() ya cortó, pero por defensiveness).
        if _is_security_flag(flow):
            flow.response.status_code = 200
            flow.response.headers["content-type"] = (
                "application/json; charset=utf-8"
            )
            flow.response.set_text(json.dumps(_TRUTHY))


addons = [SecurityChecksBypass()]

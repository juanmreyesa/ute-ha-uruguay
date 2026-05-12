"""Dump a single matching flow from a .mitm file."""
import sys
from mitmproxy.io import FlowReader

needle = sys.argv[2]
target_host = sys.argv[3] if len(sys.argv) > 3 else None

with open(sys.argv[1], "rb") as f:
    for flow in FlowReader(f).stream():
        if not hasattr(flow, "request"):
            continue
        req = flow.request
        host = req.pretty_host
        if target_host and target_host not in host:
            continue
        if needle not in req.path:
            continue
        print("=" * 80)
        print(f"{req.method} https://{host}{req.path}")
        print("--- request headers ---")
        for k, v in req.headers.items():
            print(f"{k}: {v}")
        if req.content:
            print("--- request body ---")
            try:
                print(req.get_text() or "<binary>")
            except Exception:
                print("<binary>")
        if flow.response:
            r = flow.response
            print(f"--- response {r.status_code} ---")
            for k, v in r.headers.items():
                print(f"{k}: {v}")
            try:
                body = r.get_text() or ""
                if len(body) > 4000:
                    body = body[:4000] + f"\n... [truncated, total {len(r.content)} bytes]"
                print(body)
            except Exception:
                print("<binary>")
        print()

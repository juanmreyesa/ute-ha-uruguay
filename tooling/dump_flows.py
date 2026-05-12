"""Dump UTE-related flows from a .mitm file as readable text."""
import sys
from mitmproxy.io import FlowReader

with open(sys.argv[1], "rb") as f:
    for flow in FlowReader(f).stream():
        if not hasattr(flow, "request"):
            continue
        req = flow.request
        host = req.pretty_host or req.host
        if not any(h in host for h in ("ute", "iduruguay", "200.40.12")):
            continue
        print("=" * 80)
        print(f"{req.method} https://{host}{req.path}")
        print("--- request headers ---")
        for k, v in req.headers.items():
            print(f"{k}: {v}")
        if req.content:
            try:
                print("--- request body ---")
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
                if len(body) > 2000:
                    body = body[:2000] + f"\n... [truncated, total {len(r.content)} bytes]"
                print(body)
            except Exception:
                print("<binary>")
        print()

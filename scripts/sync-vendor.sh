#!/usr/bin/env bash
# Sync el cliente Python (`client-py/ute_client/`) al vendor del custom_component
# (`ha-integration/custom_components/ute_energy/api.py + models.py`).
#
# Por qué: HA load custom_components no resuelve packages externos sin pip dep.
# Para evitar publicar `ute-client` a PyPI mantenemos las dos copias en sync
# vía este script. Corré antes de cada commit que toque el cliente.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/client-py/ute_client"
DST="$ROOT/ha-integration/custom_components/ute_energy"

cp "$SRC/models.py"  "$DST/models.py"
cp "$SRC/client.py"  "$DST/api.py"
sed -i 's|from ute_client.models import|from .models import|g' "$DST/api.py"

echo "✓ vendored client → $DST/{api,models}.py"

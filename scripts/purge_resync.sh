#!/usr/bin/env bash
# purge_resync.sh — this node ABANDONS ITS CHAIN and re-syncs from the network (doc/updates-and-rerolls.md).
# Use when the node is stranded on a dead fork (e.g. it ran old rules while the network moved on).
# Wipes chain-derived data ONLY (blocks/index/peers/snapshots/exec state+DA) — NEVER private/ (keys, config).
# Stops the services first so nothing holds the files, restamps the chain generation, restarts.
set -euo pipefail
REPO_DIR="${1:-/root/nado}"
PY="$REPO_DIR/nado_venv/bin/python"; [ -x "$PY" ] || PY=python3

echo "[purge-resync] stopping node services"
for svc in nado nado-exec; do systemctl stop "$svc" 2>/dev/null || true; done

echo "[purge-resync] wiping chain-derived data (private/ untouched)"
"$PY" - <<PYEOF
import sys
sys.path.insert(0, "$REPO_DIR")
from ops.data_ops import purge_chain_data, stamp_chain_generation
purge_chain_data()
stamp_chain_generation()
PYEOF

echo "[purge-resync] restarting"
for svc in nado nado-exec; do systemctl start "$svc" 2>/dev/null || true; done
echo "[purge-resync] done — the node will regenesis/resync (snapshot bootstrap where full sync is refused)"

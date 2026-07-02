#!/usr/bin/env bash
#
# NADO node installer — sets up a Python venv, installs dependencies, and (optionally) installs a
# systemd service so the node mines UNATTENDED: starts on boot, restarts on crash, no terminal needed.
#
# Usage (run from anywhere; the script locates the repo it lives in):
#
#   scripts/install.sh                 # create venv + install node deps (no GUI/wallet packages)
#   scripts/install.sh --wallet        # also install the desktop-wallet deps (PySide6) for this machine
#   sudo scripts/install.sh --service  # + install & enable a systemd service (unattended, boots on start)
#
# COMPLETE PACKAGE (L1 + shielded pool). --exec also runs the execution / shielded-pool node on :9273, which
# powers private deposits/withdrawals + shielded transfers and the on-device (in-browser) zk-STARK prover:
#
#   scripts/install.sh --exec                    # run the L1 node AND the shielded-pool node
#   sudo scripts/install.sh --service --exec     # both, unattended, as boot-on-start systemd services
#   sudo scripts/install.sh --service --exec-settle  # + anchor the shielded state-root to L1 (uses this node's keys)
#
# Unattended auto-bond: pass a percentage to auto-compound mined rewards into bonded stake. Works with
# or without --service (it sets NADO_AUTO_BOND_PERCENT for the service, or prints it for manual runs):
#
#   sudo scripts/install.sh --service --auto-bond 25     # bond 25% of mined rewards, hands-free
#
# Re-running is safe (idempotent): the venv is reused and deps are upgraded in place. The shielded-pool node
# needs no extra dependencies (aiohttp is already required) and the WASM prover ships prebuilt — nothing to compile.
set -euo pipefail

# ---- locate the repo (this script lives in <repo>/scripts/) --------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_DIR/nado_venv"
SERVICE_USER="${SUDO_USER:-$(id -un)}"

# ---- parse args ----------------------------------------------------------------------------------
WITH_WALLET=0
WITH_SERVICE=0
WITH_EXEC=0
EXEC_SETTLE=0
AUTO_BOND="${NADO_AUTO_BOND_PERCENT:-0}"
while [ $# -gt 0 ]; do
  case "$1" in
    --wallet)      WITH_WALLET=1 ;;
    --service)     WITH_SERVICE=1 ;;
    --exec)        WITH_EXEC=1 ;;            # also run the execution / shielded-pool node (:9273)
    --exec-settle) WITH_EXEC=1; EXEC_SETTLE=1 ;;  # + settle the exec state-root to L1 (uses this node's keys)
    --auto-bond)   shift; AUTO_BOND="${1:-0}" ;;
    --auto-bond=*) AUTO_BOND="${1#*=}" ;;
    -h|--help)
      sed -n '3,26p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# validate auto-bond is an int 0..100
if ! [[ "$AUTO_BOND" =~ ^[0-9]+$ ]] || [ "$AUTO_BOND" -gt 100 ]; then
  echo "ERROR: --auto-bond must be an integer 0..100 (got '$AUTO_BOND')." >&2; exit 2
fi

echo "==> NADO install"
echo "    repo:        $REPO_DIR"
echo "    venv:        $VENV_DIR"
echo "    wallet deps: $([ $WITH_WALLET -eq 1 ] && echo yes || echo no)"
echo "    service:     $([ $WITH_SERVICE -eq 1 ] && echo yes || echo no)"
echo "    exec node:   $([ $WITH_EXEC -eq 1 ] && echo "yes (shielded pool :9273$([ $EXEC_SETTLE -eq 1 ] && echo ", settles to L1"))" || echo no)"
echo "    auto-bond:   ${AUTO_BOND}%"

# ---- pick a Python >= 3.10 -----------------------------------------------------------------------
pick_python() {
  for c in python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
        echo "$c"; return 0
      fi
    fi
  done
  return 1
}
PY="$(pick_python || true)"
if [ -z "${PY:-}" ]; then
  echo "ERROR: need Python 3.10+. On Ubuntu: sudo add-apt-repository ppa:deadsnakes/ppa && \
sudo apt install python3.10 python3.10-venv" >&2
  exit 1
fi
echo "==> using $("$PY" --version 2>&1) ($PY)"

# ---- create / reuse the venv ---------------------------------------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "==> creating venv at $VENV_DIR"
  "$PY" -m venv "$VENV_DIR"
else
  echo "==> reusing existing venv"
fi
VENV_PY="$VENV_DIR/bin/python"
"$VENV_PY" -m pip install --upgrade pip >/dev/null

# ---- install dependencies ------------------------------------------------------------------------
# The node does NOT need the desktop-wallet packages (PySide6 etc.). For a headless node we strip the
# wallet-only line from requirements so a server install stays lean; --wallet keeps everything.
REQ="$REPO_DIR/requirements.txt"
if [ $WITH_WALLET -eq 1 ]; then
  echo "==> installing all dependencies (incl. desktop wallet)"
  "$VENV_PY" -m pip install -r "$REQ"
else
  echo "==> installing node dependencies (excluding wallet-only PySide6)"
  TMP_REQ="$(mktemp)"
  grep -viE '^[[:space:]]*PySide6' "$REQ" > "$TMP_REQ"
  "$VENV_PY" -m pip install -r "$TMP_REQ"
  rm -f "$TMP_REQ"
fi

echo "==> dependencies installed."

# ---- native Goldilocks lib (optional; speeds up shielded proving ~2x on top of the pure-Python batch path) ---
if [ $WITH_EXEC -eq 1 ]; then
  if command -v cargo >/dev/null 2>&1; then
    echo "==> building the native Goldilocks NTT (faster shielded proving)..."
    if ( cd "$REPO_DIR/wasm/goldilocks" && cargo build --release >/dev/null 2>&1 ); then
      echo "    built wasm/goldilocks/target/release/libgoldilocks.so"
    else
      echo "    (build failed — the shielded-pool node will use the pure-Python prover; still correct, just slower.)"
    fi
  else
    echo "==> cargo/Rust not found — the shielded-pool node will use the pure-Python prover (correct, ~2x slower)."
    echo "    For faster proving: install Rust (https://rustup.rs), then: (cd wasm/goldilocks && cargo build --release)"
  fi
fi

# ---- systemd service (unattended) ----------------------------------------------------------------
if [ $WITH_SERVICE -eq 1 ]; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: --service needs root (run with sudo) to write /etc/systemd/system/nado.service." >&2
    exit 1
  fi
  UNIT=/etc/systemd/system/nado.service
  echo "==> writing $UNIT (user: $SERVICE_USER, auto-bond: ${AUTO_BOND}%)"
  cat > "$UNIT" <<UNITEOF
[Unit]
Description=NADO node (unattended fair-launch miner)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$REPO_DIR
# Auto-compound this %% of mined rewards into bonded stake (0 = off). See README "Auto-bond".
Environment=NADO_AUTO_BOND_PERCENT=$AUTO_BOND
ExecStart=$VENV_PY $REPO_DIR/nado.py
Restart=always
RestartSec=5
# raise the open-file limit (the node keeps many block/peer handles)
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
UNITEOF
  systemctl daemon-reload
  systemctl enable nado.service
  systemctl restart nado.service
  echo "==> service installed, enabled and started."
  echo "    status:  systemctl status nado"
  echo "    logs:    journalctl -u nado -f"
  echo "    stop:    systemctl stop nado     (clean shutdown; never kill -9)"

  # ---- shielded-pool / execution node service (optional) -----------------------------------------
  if [ $WITH_EXEC -eq 1 ]; then
    EUNIT=/etc/systemd/system/nado-exec.service
    echo "==> writing $EUNIT (shielded pool on :9273$([ $EXEC_SETTLE -eq 1 ] && echo ", settles to L1"))"
    cat > "$EUNIT" <<EXECEOF
[Unit]
Description=NADO execution / shielded-pool node (private deposits, withdrawals, shielded transfers)
After=nado.service network-online.target
Wants=network-online.target
Requires=nado.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$REPO_DIR
Environment=NADO_L1_URL=http://127.0.0.1:9173
Environment=NADO_EXEC_STATE=$REPO_DIR/exec_state.json
Environment=NADO_EXEC_PORT=9273
$([ $EXEC_SETTLE -eq 1 ] && echo "Environment=NADO_EXEC_SETTLE=1")
ExecStart=$VENV_PY $REPO_DIR/execnode/execnode.py
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EXECEOF
    systemctl daemon-reload
    systemctl enable nado-exec.service
    systemctl restart nado-exec.service
    echo "==> shielded-pool node installed, enabled and started."
    echo "    status:  systemctl status nado-exec"
    echo "    logs:    journalctl -u nado-exec -f"
  fi
else
  echo
  echo "==> Done. Run the node unattended without systemd via nohup:"
  if [ "$AUTO_BOND" != "0" ]; then
    echo "      cd $REPO_DIR && NADO_AUTO_BOND_PERCENT=$AUTO_BOND nohup $VENV_PY nado.py > nado.out 2>&1 &"
  else
    echo "      cd $REPO_DIR && nohup $VENV_PY nado.py > nado.out 2>&1 &"
  fi
  echo "    or in the foreground:    $VENV_PY $REPO_DIR/nado.py"
  if [ $WITH_EXEC -eq 1 ]; then
    echo
    echo "==> Then start the shielded-pool node (needs the L1 above running):"
    echo "      cd $REPO_DIR && NADO_L1_URL=http://127.0.0.1:9173 NADO_EXEC_STATE=$REPO_DIR/exec_state.json \\"
    echo "        $([ $EXEC_SETTLE -eq 1 ] && echo "NADO_EXEC_SETTLE=1 ")nohup $VENV_PY execnode/execnode.py > exec.out 2>&1 &"
  fi
  echo "    (re-run with sudo and --service to install boot-on-start systemd services.)"
fi

echo "==> The node serves its API + web miner on http://<this-host>:9173  (forward port 9173 for rewards)."
if [ $WITH_EXEC -eq 1 ]; then
  echo "==> The shielded pool (deposits / withdrawals / shielded transfers + on-device prover) runs on :9273."
  echo "    Forward port 9273 too so browsers can reach your shielded-pool node (the Shield tab talks to it)."
fi

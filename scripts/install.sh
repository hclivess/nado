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
# Auto-update is BUILT INTO THE NODE (ops/self_update.py): a daily fast-forward check against origin/main
# of the official repo, plus a remote GET /update trigger any peer can send (safe: ff-only, pinned repo +
# branch, refuses a dirty/diverged tree, never touches the gitignored chain data). Default ON; opt out with
# "auto_update": false in private/config.json. The old nado-update.service/.timer pair is retired — this
# installer removes it if found. Legacy --auto-update flags are accepted and ignored.
#
# Data directory: the node keeps its chain under $HOME/nado. Pass --home <dir> to put it elsewhere
# (the services then run with HOME=<dir>, so chain data lands in <dir>/nado). Recommended whenever the
# repo checkout itself sits at ~/nado, so chain data does not mix into the working tree:
#
#   sudo scripts/install.sh --service --home /srv/nado-data
#
# Native ML-DSA verify backend (Rust, optional): 55x faster signature verification — the L1 node's main
# CPU cost. install.sh ASKS interactively; force it either way with --pq-native / --no-pq-native. It offers
# to install Rust via rustup if missing, builds native/mldsa44, and enables it ONLY if it passes the startup
# interop self-test (so a bad build can never split consensus). Build it later by hand: scripts/build_pq_native.sh
#
#   sudo scripts/install.sh --service --pq-native      # unattended node + native verify (auto-installs Rust)
#
# Re-running is safe (idempotent): the venv is reused and deps are upgraded in place. The shielded-pool node
# needs no extra dependencies (aiohttp is already required) and the WASM prover ships prebuilt.
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
DATA_HOME=""
# native ML-DSA (Rust) backend: 55x faster signature verify — the chain's main CPU cost. Empty = ASK
# interactively (or auto-skip when non-interactive); 1 = build it; 0 = skip. Adopted only if it passes
# signatures.py's startup interop self-test, so a bad build can never split consensus.
PQ_NATIVE=""
# Empty = "not set": the node then uses its own default (config auto_bond_percent, 80). The env var is
# only baked into the service when explicitly requested, because NADO_AUTO_BOND_PERCENT OVERRIDES config —
# an unconditional =0 here would silently switch auto-bond off on nodes that rely on the default.
AUTO_BOND="${NADO_AUTO_BOND_PERCENT:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --wallet)      WITH_WALLET=1 ;;
    --service)     WITH_SERVICE=1 ;;
    # LEGACY (auto-update moved into the node itself — ops/self_update.py, config "auto_update"): accepted,
    # ignored, so old provisioning scripts keep working.
    --auto-update|--auto-update=*|--no-auto-update|--update-interval=*)
      echo "note: auto-update is built into the node now (config auto_update, default on) — $1 ignored" ;;
    --update-interval) shift; echo "note: auto-update is built into the node now — --update-interval ignored" ;;
    --pq-native)   PQ_NATIVE=1 ;;            # build the native Rust ML-DSA verify backend (55x faster)
    --no-pq-native) PQ_NATIVE=0 ;;           # skip it (stay pure-Python)
    --exec)        WITH_EXEC=1 ;;            # also run the execution / shielded-pool node (:9273)
    --exec-settle) WITH_EXEC=1; EXEC_SETTLE=1 ;;  # + settle the exec state-root to L1 (uses this node's keys)
    --auto-bond)   shift; AUTO_BOND="${1:-0}" ;;
    --auto-bond=*) AUTO_BOND="${1#*=}" ;;
    --home)        shift; DATA_HOME="${1:-}" ;;   # chain data goes under <dir>/nado (services run with HOME=<dir>)
    --home=*)      DATA_HOME="${1#*=}" ;;
    -h|--help)
      sed -n '3,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# validate auto-bond is an int 0..100 (only when given; empty = leave the node's default in charge)
if [ -n "$AUTO_BOND" ]; then
  if ! [[ "$AUTO_BOND" =~ ^[0-9]+$ ]] || [ "$AUTO_BOND" -gt 100 ]; then
    echo "ERROR: --auto-bond must be an integer 0..100 (got '$AUTO_BOND')." >&2; exit 2
  fi
fi

# validate/prepare the data home (must be absolute — it becomes the services' HOME)
if [ -n "$DATA_HOME" ]; then
  case "$DATA_HOME" in
    /*) ;;
    *) echo "ERROR: --home must be an absolute path (got '$DATA_HOME')." >&2; exit 2 ;;
  esac
  mkdir -p "$DATA_HOME"
fi

echo "==> NADO install"
echo "    repo:        $REPO_DIR"
echo "    venv:        $VENV_DIR"
echo "    wallet deps: $([ $WITH_WALLET -eq 1 ] && echo yes || echo no)"
echo "    service:     $([ $WITH_SERVICE -eq 1 ] && echo yes || echo no)"
echo "    exec node:   $([ $WITH_EXEC -eq 1 ] && echo "yes (shielded pool :9273$([ $EXEC_SETTLE -eq 1 ] && echo ", settles to L1"))" || echo no)"
echo "    data home:   $([ -n "$DATA_HOME" ] && echo "$DATA_HOME (chain data in $DATA_HOME/nado)" || echo "(user home — chain data in ~/nado)")"
echo "    auto-bond:   $([ -n "$AUTO_BOND" ] && echo "${AUTO_BOND}%" || echo "(node default: 80%, see auto_bond_percent in private/config.json)")"
echo "    auto-update: built into the node (daily origin/main check + remote /update trigger; disable with \"auto_update\": false in private/config.json)"

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

# ---- Rust toolchain helper (shared by the native ML-DSA verify backend + the Goldilocks prover) ---
# Ensures `cargo` is on PATH; offers to install it via rustup (official, per-user, no root) when missing.
# Returns 0 if cargo is available afterward, 1 otherwise. Never fails the install — native code is optional.
ensure_rust() {
  if command -v cargo >/dev/null 2>&1; then return 0; fi
  [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env" 2>/dev/null || true
  if command -v cargo >/dev/null 2>&1; then return 0; fi
  local do_install="$1"   # "ask" | "yes" | "no"
  if [ "$do_install" = "no" ]; then return 1; fi
  if [ "$do_install" = "ask" ]; then
    if [ ! -t 0 ]; then return 1; fi   # non-interactive: don't silently pull the internet
    printf "    Rust (cargo) is not installed. Install it now via rustup? [y/N] "
    read -r _ans || _ans=""
    case "$_ans" in y|Y|yes|YES) ;; *) return 1 ;; esac
  fi
  echo "==> installing Rust via rustup (per-user, no root)..."
  if command -v curl >/dev/null 2>&1; then
    curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal >/dev/null 2>&1 || true
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://sh.rustup.rs | sh -s -- -y --profile minimal >/dev/null 2>&1 || true
  else
    echo "    (need curl or wget to fetch rustup — skipping; install Rust manually from https://rustup.rs)"
    return 1
  fi
  [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env" 2>/dev/null || true
  command -v cargo >/dev/null 2>&1
}

# ---- native ML-DSA-44 verify backend (optional; 55x faster signature verify — the L1 CPU bottleneck) ---
# Decide whether to build: explicit flag wins; else ASK when interactive, skip when not.
PQ_BUILT=0
_pq_want="$PQ_NATIVE"
if [ -z "$_pq_want" ]; then
  if [ -t 0 ]; then
    printf "==> Build the native Rust ML-DSA backend? 55x faster signature verify (needs Rust). [y/N] "
    read -r _ans || _ans=""
    case "$_ans" in y|Y|yes|YES) _pq_want=1 ;; *) _pq_want=0 ;; esac
  else
    _pq_want=0   # non-interactive default: stay pure-Python unless --pq-native was passed
  fi
fi
if [ "$_pq_want" = "1" ]; then
  if ensure_rust "yes"; then
    echo "==> building the native ML-DSA-44 verify backend (native/mldsa44)..."
    if ( cd "$REPO_DIR/native/mldsa44" && cargo build --release >/dev/null 2>&1 ); then
      cp "$REPO_DIR/native/mldsa44/target/release/libnado_mldsa44.so" \
         "$REPO_DIR/native/mldsa44/libnado_mldsa44.so" 2>/dev/null || true
      # verify it actually passes the interop self-test before we commit to baking the env var in
      if NADO_PQ_NATIVE_MODULE=nado_pq_native "$VENV_PY" -c \
           "import sys; sys.path.insert(0,'$REPO_DIR'); import signatures as s; sys.exit(0 if 'native' in s._BACKEND.name else 1)" 2>/dev/null; then
        PQ_BUILT=1
        echo "    built + interop-verified: native/mldsa44/libnado_mldsa44.so (55x faster verify)"
      else
        echo "    (built but FAILED the interop self-test — not enabling it; staying pure-Python.)"
      fi
    else
      echo "    (build failed — staying pure-Python; still correct, just slower.)"
    fi
  else
    echo "==> Rust not available — skipping the native ML-DSA backend (staying pure-Python)."
    echo "    To add it later: install Rust (https://rustup.rs), then scripts/build_pq_native.sh"
  fi
fi

# ---- native STARK-prover libs (optional; speed up shielded proving + the alghash2 recursion hot path) ---
# Both are cdylibs bound via ctypes and are BIT-IDENTICAL to their pure-Python counterparts (they just run
# the same field/hash arithmetic faster), so the node stays correct whether or not they build.
if [ $WITH_EXEC -eq 1 ]; then
  if ensure_rust "ask"; then
    echo "==> building the native Goldilocks NTT (faster shielded proving)..."
    if ( cd "$REPO_DIR/wasm/goldilocks" && cargo build --release >/dev/null 2>&1 ); then
      echo "    built wasm/goldilocks/target/release/libgoldilocks.so"
    else
      echo "    (build failed — the shielded-pool node will use the pure-Python prover; still correct, just slower.)"
    fi
    echo "==> building the native alghash2 hash (recursion hot path; ~20x faster)..."
    if ( cd "$REPO_DIR/native/alghash2" && cargo build --release >/dev/null 2>&1 ); then
      # confirm the .so loads + initializes (its bit-identity to Python is covered by tests/test_recursion.py)
      if "$VENV_PY" -c "import sys; sys.path.insert(0,'$REPO_DIR'); from execnode.stark import alghash2 as a; sys.exit(0 if a._try_native() and len(a.hashn([1,2,3]))==a.CAPACITY else 1)" 2>/dev/null; then
        echo "    built + loaded: native/alghash2/target/release/libnado_alghash2.so"
      else
        echo "    (built but the .so did not load — recursion/alghash2 paths use pure Python; still correct.)"
      fi
    else
      echo "    (build failed — recursion/alghash2 paths use pure Python; still correct, just slower.)"
    fi
    echo "==> building the native STARK composition (constraint-IR evaluator; ~10x on the composition loop)..."
    if ( cd "$REPO_DIR/native/starkcompose" && cargo build --release >/dev/null 2>&1 ); then
      # confirm the .so loads (its bit-identity to stark._composition is covered by tests/test_air_ir.py)
      if "$VENV_PY" -c "import sys; sys.path.insert(0,'$REPO_DIR'); from execnode.stark import air_ir; sys.exit(0 if air_ir._native() else 1)" 2>/dev/null; then
        echo "    built + loaded: native/starkcompose/target/release/libnado_starkcompose.so"
      else
        echo "    (built but the .so did not load — the prover uses the pure-Python composition; still correct.)"
      fi
    else
      echo "    (build failed — the prover uses the pure-Python composition; still correct, just slower.)"
    fi
    echo "==> building the holistic native prover (recursion proving + PARALLEL fold/composition Merkle)..."
    if ( cd "$REPO_DIR/native/starkprove" && cargo build --release >/dev/null 2>&1 ); then
      # confirm the .so loads (bit-identity to stark.prove is covered by tests/test_starkprove.py). stark.prove
      # routes RECURSION/ALGHASH2 proving through this arena; the Merkle commits hash in parallel across all
      # cores (NADO_NATIVE_THREADS caps the fan-out) — the fold/composition pipeline's dominant cost.
      if "$VENV_PY" -c "import sys; sys.path.insert(0,'$REPO_DIR'); from execnode.stark import stark_native as s; sys.exit(0 if s.available() else 1)" 2>/dev/null; then
        echo "    built + loaded: native/starkprove/target/release/libnado_starkprove.so"
      else
        echo "    (built but the .so did not load — recursion proving uses pure Python; still correct, much slower.)"
      fi
    else
      echo "    (build failed — recursion proving uses pure Python; still correct, much slower.)"
    fi
  else
    echo "==> Rust not available — the shielded-pool node will use the pure-Python prover (correct, ~2x slower)."
    echo "    For faster proving: install Rust (https://rustup.rs), then:"
    echo "      (cd wasm/goldilocks && cargo build --release) && (cd native/alghash2 && cargo build --release) \\"
    echo "        && (cd native/starkcompose && cargo build --release)"
  fi
fi

# ---- systemd service (unattended) ----------------------------------------------------------------
if [ $WITH_SERVICE -eq 1 ]; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: --service needs root (run with sudo) to write /etc/systemd/system/nado.service." >&2
    exit 1
  fi
  UNIT=/etc/systemd/system/nado.service
  echo "==> writing $UNIT (user: $SERVICE_USER$([ -n "$DATA_HOME" ] && echo ", data home: $DATA_HOME")$([ -n "$AUTO_BOND" ] && echo ", auto-bond: ${AUTO_BOND}%"))"
  cat > "$UNIT" <<UNITEOF
[Unit]
Description=NADO node (unattended fair-launch miner)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$REPO_DIR
$([ -n "$DATA_HOME" ] && echo "# chain data lives under \$HOME/nado — pin HOME so it stays out of the repo checkout
Environment=HOME=$DATA_HOME")
$([ -n "$AUTO_BOND" ] && echo "# Auto-compound this % of mined rewards into bonded stake (0 = off). See README \"Auto-bond\".
# Written only because --auto-bond was passed; the env var overrides the node's config default (80).
Environment=NADO_AUTO_BOND_PERCENT=$AUTO_BOND")
$([ "$PQ_BUILT" = "1" ] && echo "# Native Rust ML-DSA verify backend (55x faster; built + interop-verified by install.sh).
# signatures.py re-runs the interop self-test at boot and falls back to pure-Python on any mismatch.
Environment=NADO_PQ_NATIVE_MODULE=nado_pq_native")
ExecStart=$VENV_PY $REPO_DIR/nado.py
Restart=always
RestartSec=5
# SIGTERM triggers the node's clean shutdown (it needs a few seconds to close the chain DB);
# escalate to SIGKILL only if it hangs well past that.
TimeoutStopSec=60
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
    # exec state (the replayable shielded-pool/contract state snapshot) lives beside the chain data
    # when --home is given, else in the repo dir (historical default).
    EXEC_STATE="${DATA_HOME:-$REPO_DIR}/exec_state.json"
    echo "==> writing $EUNIT (shielded pool on :9273$([ $EXEC_SETTLE -eq 1 ] && echo ", settles to L1"); state: $EXEC_STATE)"
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
$([ -n "$DATA_HOME" ] && echo "# settling reads this node's keys from \$HOME/nado/private — keep HOME in step with nado.service
Environment=HOME=$DATA_HOME")
Environment=NADO_L1_URL=http://127.0.0.1:9173
Environment=NADO_EXEC_STATE=$EXEC_STATE
Environment=NADO_EXEC_PORT=9273
# --exec means "let browsers reach the shielded pool", so bind publicly. The mutating /exec POSTs are
# unauthenticated but bounded (STARK size cap + in-flight limit); drop this line to keep it loopback-only.
Environment=NADO_EXEC_BIND=0.0.0.0
$([ $EXEC_SETTLE -eq 1 ] && echo "Environment=NADO_EXEC_SETTLE=1")
ExecStart=$VENV_PY $REPO_DIR/execnode/execnode.py
Restart=always
RestartSec=5
TimeoutStopSec=60
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

  # ---- retire the LEGACY auto-update timer (updating now lives inside the node) -------------------
  if [ -f /etc/systemd/system/nado-update.timer ] || [ -f /etc/systemd/system/nado-update.service ]; then
    echo "==> removing legacy nado-update.service/.timer (auto-update is built into the node now)"
    systemctl disable --now nado-update.timer 2>/dev/null || true
    rm -f /etc/systemd/system/nado-update.timer /etc/systemd/system/nado-update.service
    systemctl daemon-reload
  fi
else
  # env prefix for the manual-run hints (mirrors what --service would bake into the units)
  ENV_PREFIX=""
  if [ -n "$DATA_HOME" ]; then ENV_PREFIX="HOME=$DATA_HOME "; fi
  if [ -n "$AUTO_BOND" ]; then ENV_PREFIX="${ENV_PREFIX}NADO_AUTO_BOND_PERCENT=$AUTO_BOND "; fi
  echo
  echo "==> Done. Run the node unattended without systemd via nohup:"
  echo "      cd $REPO_DIR && ${ENV_PREFIX}nohup $VENV_PY nado.py > nado.out 2>&1 &"
  echo "    or in the foreground:    ${ENV_PREFIX}$VENV_PY $REPO_DIR/nado.py"
  if [ $WITH_EXEC -eq 1 ]; then
    echo
    echo "==> Then start the shielded-pool node (needs the L1 above running):"
    echo "      cd $REPO_DIR && ${ENV_PREFIX}NADO_L1_URL=http://127.0.0.1:9173 NADO_EXEC_STATE=${DATA_HOME:-$REPO_DIR}/exec_state.json \\"
    echo "        $([ $EXEC_SETTLE -eq 1 ] && echo "NADO_EXEC_SETTLE=1 ")nohup $VENV_PY execnode/execnode.py > exec.out 2>&1 &"
  fi
  echo "    (re-run with sudo and --service to install boot-on-start, restart-on-crash systemd services.)"
fi

echo "==> The node serves its API + web miner on http://<this-host>:9173  (forward port 9173 for rewards)."
if [ $WITH_EXEC -eq 1 ]; then
  echo "==> The shielded pool (deposits / withdrawals / shielded transfers + on-device prover) runs on :9273."
  echo "    Forward port 9273 too so browsers can reach your shielded-pool node (the Shield tab talks to it)."
fi

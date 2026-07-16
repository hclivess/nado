#!/usr/bin/env bash
# NADO auto-updater — fast-forward the checkout to origin and restart the node service(s) when new code lands.
# Installed as nado-update.service + nado-update.timer by scripts/install.sh --service --auto-update.
#
# SAFE BY DESIGN (this runs unattended on a live money node whose repo dir IS the data dir):
#   • FAST-FORWARD ONLY — never a hard reset, never a merge that could rewrite local state. If the local HEAD
#     has diverged from origin (local commits) or the working tree is dirty, it REFUSES and leaves the node
#     running the current code. So it only ever advances a checkout that cleanly tracks origin.
#   • Touches only TRACKED files — the chain DB / index / peers / private keys are gitignored runtime data and
#     are never affected by a fast-forward.
#   • Restart is a clean SIGTERM via systemctl (the node shuts the chain DB down gracefully); it is crash- and
#     shutdown-safe, so a restart at any moment cannot corrupt state.
#
# Usage: nado_autoupdate.sh [REPO_DIR]   (branch = whatever the checkout is on; default repo /root/nado)
set -u
REPO_DIR="${1:-/root/nado}"

log() { echo "[nado-autoupdate] $*"; }

cd "$REPO_DIR" 2>/dev/null || { log "repo dir $REPO_DIR not found"; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { log "$REPO_DIR is not a git repo"; exit 1; }

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
[ -n "$BRANCH" ] && [ "$BRANCH" != "HEAD" ] || { log "detached HEAD — refusing to auto-update"; exit 1; }

# Fetch is best-effort: a transient network failure must NOT be an error (the timer just tries again later).
if ! git fetch --quiet origin "$BRANCH" 2>/dev/null; then
  log "fetch failed (offline?) — will retry next tick"; exit 0
fi

LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null)
if [ -z "$REMOTE" ]; then log "no origin/$BRANCH — nothing to track"; exit 0; fi
if [ "$LOCAL" = "$REMOTE" ]; then log "up to date (${LOCAL:0:12})"; exit 0; fi

# Only advance if the remote is strictly AHEAD of us (local is an ancestor) — never clobber local commits.
if ! git merge-base --is-ancestor "$LOCAL" "$REMOTE" 2>/dev/null; then
  log "local HEAD ${LOCAL:0:12} is not an ancestor of origin/$BRANCH ${REMOTE:0:12} (diverged / local commits) — refusing to auto-merge; update manually"
  exit 1
fi
# Refuse on a dirty working tree — a fast-forward would fail anyway, and we never want to touch local edits.
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "working tree has uncommitted changes — refusing to auto-update (commit/stash them, or they are meant to stay local)"
  exit 1
fi

if ! git merge --ff-only --quiet "origin/$BRANCH" 2>/dev/null; then
  log "fast-forward failed unexpectedly — leaving node on ${LOCAL:0:12}"; exit 1
fi
log "updated ${LOCAL:0:12} -> ${REMOTE:0:12} on $BRANCH; restarting node service(s)"

# Rebuild native crates if the Rust sources changed (they are optional accelerators; failure is non-fatal —
# the node falls back to pure Python, still correct). Only if cargo + the crates are present.
if command -v cargo >/dev/null 2>&1 && git diff --name-only "$LOCAL" "$REMOTE" | grep -qE '^(native|wasm)/.*\.rs$'; then
  log "native sources changed — rebuilding crates"
  for crate in native/mldsa44 native/alghash2 native/starkcompose native/starkprove wasm/goldilocks; do
    [ -d "$REPO_DIR/$crate" ] && ( cd "$REPO_DIR/$crate" && cargo build --release >/dev/null 2>&1 ) \
      && log "  rebuilt $crate" || true
  done
fi

# Restart whichever node services are installed + enabled. Clean SIGTERM; systemd waits for graceful shutdown.
restarted=0
for svc in nado nado-exec; do
  if systemctl list-unit-files "$svc.service" >/dev/null 2>&1 \
     && systemctl cat "$svc.service" >/dev/null 2>&1; then
    if systemctl restart "$svc.service"; then log "restarted $svc"; restarted=1; else log "restart $svc FAILED"; fi
  fi
done
[ "$restarted" = "1" ] || log "no nado systemd service found to restart (new code will apply on next manual start)"

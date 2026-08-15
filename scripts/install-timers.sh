#!/usr/bin/env bash
# Install the OPERATOR TIMERS — the periodic bots that are not part of the node process.
#
# These are deliberately separate from scripts/install.sh: a node does not need them to follow consensus,
# and most operators should not run them. They act as the OPERATOR (they spend from operator-owned banks
# and post as the operator's key), so installing them on a machine whose keys.dat is not the operator's
# just produces transactions the contracts reject.
#
# WHY THIS EXISTS: the faucet distributor was written, enrolled 14 games, and was never scheduled anywhere.
# The faucet accumulated donations and paid nothing, and there was no artifact in the repo to notice was
# missing. A unit that only lives on one box is a unit that silently stops existing.
#
#   sudo scripts/install-timers.sh            # install + enable everything below
#   sudo scripts/install-timers.sh --list     # show what would be installed, change nothing
set -euo pipefail

UNITS=(
  # faucet prize distributor — pays airdrop-play leaderboards from the faucet bank (doc/faucet.md)
  "nado-faucet-rewards.service" "nado-faucet-rewards.timer"
  # bet oracle — fills fixtures and posts finished results (scripts/bet_oracle.py)
  "bet-oracle.service" "bet-oracle.timer"
)
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/etc/systemd/system

if [ "${1:-}" = "--list" ]; then
  printf 'would install from %s:\n' "$SRC"
  for u in "${UNITS[@]}"; do printf '  %s\n' "$u"; done
  exit 0
fi
[ "$(id -u)" -eq 0 ] || { echo "run as root (it writes $DEST)" >&2; exit 1; }

for u in "${UNITS[@]}"; do
  [ -f "$SRC/$u" ] || { echo "missing $SRC/$u — skipping" >&2; continue; }
  install -m 0644 "$SRC/$u" "$DEST/$u"
  echo "installed $u"
done
systemctl daemon-reload
# Enable only the TIMERS; the .service units are oneshots the timers trigger.
for u in "${UNITS[@]}"; do
  case "$u" in *.timer)
    systemctl enable --now "$u" && echo "enabled $u" ;;
  esac
done
echo
systemctl list-timers --no-pager 'nado-*' 'bet-oracle*' || true

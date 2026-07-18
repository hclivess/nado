#!/usr/bin/env bash
# fire_cutover.sh — EXECUTE the alphanet-7 debrand reroll. Run ON THE OPERATOR NODE, from the repo
# root, AFTER the debrand-cutover branch is merged to the working tree you are about to ship.
#
# PRECONDITIONS (the announced pre-snapshot window — doc/debrand.md):
#   · open game tables settled / refunded
#   · multisig + HD-DERIVED account balances moved to MAIN keyed accounts
#   · shielded notes unshielded
#   (anything not moved does NOT carry to alphanet-7)
#
# What it does: snapshot final balances from the LIVE chain -> re-key alloc + open-registry to the
# new prefix -> stamp GENESIS_TIMESTAMP -> commit -> push -> /update wave (nodes see the
# CHAIN_GENERATION bump, purge, and boot alphanet-7 from block 1 with balances pre-seeded).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-./nado_venv/bin/python}
NEW_PREFIX=$(python3 -c "import protocol; print(protocol.ADDRESS_PREFIX)")
[ "$NEW_PREFIX" != "ndo" ] || { echo "ABORT: tree still has the old prefix — merge debrand-cutover first"; exit 1; }

echo "== 1/5 snapshot final balances from the live chain"
HOME=/root $PY tools/relaunch_carry_forward.py
echo "== 2/5 re-key alloc + open registry ndo -> $NEW_PREFIX"
$PY scripts/rekey_alloc.py /root/nado/private/genesis_alloc.dat ndo "$NEW_PREFIX" > genesis_data/genesis_alloc.dat
$PY scripts/rekey_alloc.py genesis_data/genesis_open.dat ndo "$NEW_PREFIX" > /tmp/_open.$$ && mv /tmp/_open.$$ genesis_data/genesis_open.dat
python3 -m json.tool genesis_data/genesis_alloc.dat > /dev/null && echo "   alloc valid JSON"
echo "== 3/5 stamp the new genesis"
NOW=$(date +%s)
sed -i "s/^GENESIS_TIMESTAMP = .*/GENESIS_TIMESTAMP = ${NOW}  # alphanet-7 — the debrand cutover reroll/" protocol.py
echo "== 4/5 commit + push"
git add protocol.py genesis_data/genesis_alloc.dat genesis_data/genesis_open.dat
git commit -m "FIRE: alphanet-7 debrand reroll — genesis $(date -u -d @${NOW} +%FT%TZ), balances re-keyed to ${NEW_PREFIX}"
git push origin HEAD
echo "== 5/5 the wave"
curl -s "http://127.0.0.1:9173/update" || true
for ip in 185.184.192.210 185.100.232.5 185.100.232.131 208.87.242.141; do
  echo; echo "-- $ip"; timeout 20 curl -s "http://$ip:9173/update" | head -c 200 || true
done
echo; echo "DONE — watch /status: nodes purge + boot alphanet-7 from block 1. (185.184.192.210 has no systemd: its operator must restart the process.)"

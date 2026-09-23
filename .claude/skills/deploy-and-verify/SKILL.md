---
name: deploy-and-verify
description: Push a change to the live NADO fleet and prove it is actually running. Use for ANY push to main, because pushing restarts production - and because "committed" is not "deployed".
---

# Deploying, and knowing that you did

`git push origin main` restarts production across the fleet. There is no staging copy.

The failure this exists to prevent is not a bad push. It is **believing a push took effect when it did
not** — twice in one night: a gate was announced as live while the node process still ran the previous
commit, and a wave was fired at five peers while eleven nodes existed.

## The procedure

```bash
git push origin main
```

Then fan the update out over **every IP in `peers.dat`**, not just the peers the node currently lists.
The live peer set is a horizon, not the network:

```bash
python3 - <<'PY'
import json, urllib.request, time
from concurrent.futures import ThreadPoolExecutor
ips = ["127.0.0.1"] + sorted(json.load(open("peers.dat")).keys())
def upd(ip):
    try: return json.load(urllib.request.urlopen(f"http://{ip}:9173/update", timeout=45)).get("status")
    except Exception: return "ERR"
with ThreadPoolExecutor(16) as ex: print(sorted(set(ex.map(upd, ips))))
time.sleep(80)                      # restarts take a while; do not check before this
def probe(ip):
    try: return str(json.load(urllib.request.urlopen(f"http://{ip}:9173/status", timeout=10)).get("running_commit"))[:12]
    except Exception: return "unreachable"
from collections import Counter
with ThreadPoolExecutor(16) as ex:
    for c, n in Counter(ex.map(probe, ips)).most_common(): print(f"{n:3d}  {c}")
PY
```

## Keep the tree CLEAN until the local process has restarted

The node restarts itself ~90 s after the checkout gets ahead of the running process
(`ops/self_update.apply_stale_checkout`) — but refuses while any tracked file has uncommitted changes.
Pushing from this checkout and then starting the next edit within two minutes leaves this node on the
old commit indefinitely, logging `RESTART to apply (observing)` every 10 s while every peer moves on
(2026-09-23, second push: one hour on the old commit, unnoticed until `/status_pool` was read beside
`/status`). Wait for `running_commit` to change before editing, or edit in a scratch worktree.

## Check the PROCESS, never the tree

`git log` tells you what the checkout contains. `/status` `running_commit` tells you what is **executing**.
They differ whenever a restart has not happened yet, and that gap is where the false confidence lives.

```bash
curl -s localhost:9173/status | python3 -c "import json,sys; print(json.load(sys.stdin)['running_commit'])"
```

If it lags after `/update` returned `up_to_date` — which means the git tree is current, not the process —
restart it:

```bash
systemctl restart nado.service
```

`rate_limited` and `busy` are not success. Re-fire at those hosts specifically and re-probe.

## Then watch

- `/status` height climbing, `last_block_reject: null`
- `journalctl -u nado.service --since "3 min ago" | grep -iE "error|traceback"` — count them, do not skim
- for a gated change: the fleet must be **uniform before the gate height**, not after — and the gate must
  still be AHEAD of the tip when you push (`curl -s localhost:9173/status` → `latest_block_height` vs the
  constant). A gate already behind the tip fires on each node at its own restart, which is a fork.
- a settle proof in flight: `journalctl -u nado-exec` for `settle-with-proof … BUILT` — a proof that
  straddles a format gate is refused once and re-proved next cadence; two refusals in a row is a bug.

## Never report a deploy from the push output alone

Say how many nodes are on the new commit and what the tip was. If some are unreachable, say that too —
they are still running old code and will judge blocks by old rules.

## Contract code is not live when it is pushed

A change under `execnode/games/*.py` reaches the chain only through an in-place upgrade signed by the
deployer key: `HOME=/root python3 -m execnode.games.deploy <game> --upgrade <cid>` (same cid; never a new
one — [exec-contract-upgrade-in-place]). The push restarts the fleet but changes no contract. Report a
contract fix as "code committed, upgrade pending" until `/exec/contracts` on port 9273 shows the new
first instruction for that cid, and hand the operator the exact per-contract commands (the review doc
§7 has the fourteen for the 2026-09-23 id bounds).

Verify an upgrade by equality, not by a marker: fetch `/exec/contract?cid=<cid>` (port 9273) and compare its
`code` with `execnode.games.<name>.build()` after a JSON round trip. The upgrade lands ~5-6 minutes after
submit (finality plus exec apply). And take the cid from `/exec/contracts` matched by METHOD SET, not from
the wallet page's constant — reserve's constant named a contract the exec node no longer held.

## A Rust edit is a fleet-wide rebuild: commit it promptly, and expect the old kernel until the restart

Editing anything under `native/<crate>/src` makes the running node's health line say `Native STALE
['native/<crate>'] — working tree has uncommitted edits, refusing to auto-rebuild` every 10 s until the edit is
committed, even after you ran `cargo build --release` yourself (2026-09-23, starkprove). Nothing stops: the exec
node keeps the `.so` it loaded at start and only picks up the rebuilt one at its next restart, which the push
causes. On every other node the updater rebuilds the crate before restarting (`_rebuild_native_if_changed`, ~1
min for starkprove), so allow for that in the wave. Before committing, check `git status native/` — cargo may
rewrite a tracked `Cargo.lock`; restore HEAD's copy rather than committing the rewrite.

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
- for a gated change: the fleet must be **uniform before the gate height**, not after

## Never report a deploy from the push output alone

Say how many nodes are on the new commit and what the tip was. If some are unreachable, say that too —
they are still running old code and will judge blocks by old rules.

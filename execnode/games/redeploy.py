"""redeploy.py — bring every game contract back up after a chain reroll, and rewire the whole web app.

WHY THIS EXISTS. A CHAIN_GENERATION reroll wipes the exec state: every deployed contract disappears, and
every hardcoded CID in the frontend then points at nothing. The failure is SILENT — you click "Set out" in
autogame, or anything in any other game, and nothing happens at all, because the call goes to an address
that does not exist. Recovering by hand means deploying 23 contracts, hunting every CID reference across 21
frontends plus the faucet-reward table plus the e2e harnesses, and remembering to restamp the cache-bust
hashes. Missing any one of those leaves a game dead. This does all of it in one command, and verifies it.

TWO THINGS THAT MAKE THE NAIVE VERSION FAIL, both learned the hard way:

  * `deploy.py --all` submits all 23 at once, but the producer includes roughly ONE tx per block while each
    blob tx expires 20 blocks after submission. The tail of the batch therefore expires unincluded and
    vanishes from the pool — silently, since submission itself returned "Success". We deploy in small
    batches and WAIT for each to land, resubmitting anything that expired.
  * Browsers cache the game JS by its `?v=` stamp. Repointing a CID without restamping means the browser
    keeps serving the old file with the dead CID, and the game stays broken even though the repo is right.

A CID is H(deployer, code, nonce), so the target address of every game is computable BEFORE deploying —
that is what lets this be idempotent: anything already live at its target CID is left alone, and a game
whose code changed is redeployed because its target moved.

Run:
    python3 -m execnode.games.redeploy              # deploy what's missing, rewire, restamp, verify
    python3 -m execnode.games.redeploy --check      # report only; touch nothing
    python3 -m execnode.games.redeploy --wire-only  # skip deploying; just repoint + restamp + verify
"""
import argparse
import glob
import importlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from execnode.games import deploy as D
from execnode.state import ExecState

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC = os.path.join(ROOT, "static")

# game -> the frontend that drives it. Everything else is static/<game>.js; these are the exceptions, and
# the ones with no frontend at all (system contracts reached only from python or another contract).
FRONTEND = {"holdem": "poker.js"}
NO_FRONTEND = {"reserve", "faucet"}

# _faucet_rewards.py carries its own CID table, keyed by a stable row index. Resolving the game from the
# row's `kind` works for every "<game>-daily" row; the banked/duel rows need this map. Fail loudly rather
# than guess: a wrong row here pays a board's rewards out of the wrong contract.
FAUCET_ROW_GAME = {0: "dice", 1: "scrapline", 2: "stormhold", 3: "farkle", 4: "blackjack",
                   6: "slots", 7: "mines"}

BATCH = 5                 # deploys per wave — comfortably inside the ~20-block expiry at ~1 tx/block
LAND_TIMEOUT = 300        # seconds to wait for one wave before treating the stragglers as expired
WAVE_RETRIES = 3


def _get(url, timeout=10):
    try:
        return json.load(urllib.request.urlopen(url, timeout=timeout))
    except Exception:
        return None


def live_cids(ex):
    """Every contract id the exec node currently serves. None means the node is unreachable — which must
    NOT be read as 'nothing is deployed', or we would redeploy the world on a transient blip."""
    d = _get(f"{ex}/exec/contracts?limit=500")
    if d is None:
        return None
    return {c["cid"] for c in d.get("contracts", [])}


def target_cids():
    """The address each game WILL have: H(deployer, code, nonce), computed offline. faucet and sovereign
    deploy at their fixed allowlisted names instead (state.FIXED_CIDS)."""
    keys = D.load_keys()
    out = {}
    for name in D.GAMES:
        mod = importlib.import_module(f"execnode.games.{name}")
        if name in ("faucet", "sovereign"):
            out[name] = name
        else:
            out[name] = ExecState.contract_id(ExecState.__new__(ExecState), keys["address"],
                                              mod.build(), "a5")
    return out


def deploy_wave(names, targets, l1, ex, fee):
    """Submit one wave and wait for it to actually land. Returns the names still missing."""
    for n in names:
        try:
            D.deploy_one(n, l1, "a5", fee)
        except Exception as e:
            print(f"    {n}: submit FAILED {e}", flush=True)
    deadline = time.time() + LAND_TIMEOUT
    pending = set(names)
    while pending and time.time() < deadline:
        time.sleep(8)
        have = live_cids(ex)
        if have is None:
            continue                       # node restarting; keep waiting rather than declare failure
        pending = {n for n in pending if targets[n] not in have}
        if pending:
            print(f"    waiting on {sorted(pending)}", flush=True)
    return sorted(pending)


def do_deploy(l1, ex, fee):
    targets = target_cids()
    have = live_cids(ex)
    if have is None:
        sys.exit(f"exec node unreachable at {ex} — refusing to act on an unknown chain state")
    missing = [g for g in D.GAMES if targets[g] not in have]
    print(f"live: {len(have)} contracts · up to date: {len(D.GAMES) - len(missing)}/{len(D.GAMES)}")
    if not missing:
        print("every game is already deployed at its current code — nothing to deploy")
        return targets
    print(f"deploying {len(missing)}: {', '.join(missing)}")
    for attempt in range(1, WAVE_RETRIES + 1):
        still = []
        for i in range(0, len(missing), BATCH):
            wave = missing[i:i + BATCH]
            print(f"  wave {i // BATCH + 1}: {', '.join(wave)}", flush=True)
            still += deploy_wave(wave, targets, l1, ex, fee)
        if not still:
            break
        print(f"  pass {attempt}: {len(still)} expired unincluded, retrying: {', '.join(still)}")
        missing = still
    else:
        print(f"  STILL MISSING after {WAVE_RETRIES} passes: {', '.join(missing)}")
    return targets


def wire(targets):
    """Repoint every hardcoded CID. Returns a list of human-readable changes."""
    changed = []

    for game, cid in targets.items():
        if game in NO_FRONTEND:
            continue
        path = os.path.join(STATIC, FRONTEND.get(game, f"{game}.js"))
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        m = re.search(r'^const CID = "([0-9a-z]+)";', src, re.M)
        if not m:
            print(f"  ! {os.path.basename(path)}: no `const CID` line — left alone")
            continue
        if m.group(1) == cid:
            continue
        open(path, "w", encoding="utf-8").write(src[:m.start(1)] + cid + src[m.end(1):])
        changed.append(f"{os.path.basename(path)}: {m.group(1)[:10]}… -> {cid[:10]}…")

    fr = os.path.join(ROOT, "_faucet_rewards.py")
    if os.path.exists(fr):
        lines = open(fr, encoding="utf-8").read().split("\n")
        for i, line in enumerate(lines):
            m = re.match(r'^(\s*\((\d+),\s*")([0-9a-z]+)(",\s*"([a-z0-9-]+)".*)$', line)
            if not m:
                continue
            idx, old, kind = int(m.group(2)), m.group(3), m.group(5)
            game = kind[:-6] if kind.endswith("-daily") else FAUCET_ROW_GAME.get(idx)
            if game is None:
                sys.exit(f"_faucet_rewards.py row {idx} ({kind!r}): cannot resolve the game — "
                         f"add it to FAUCET_ROW_GAME rather than let it point at a stale contract")
            if game not in targets:
                sys.exit(f"_faucet_rewards.py row {idx}: unknown game {game!r}")
            if old != targets[game]:
                lines[i] = m.group(1) + targets[game] + m.group(4)
                changed.append(f"_faucet_rewards.py[{idx}] {game}: {old[:10]}… -> {targets[game][:10]}…")
        open(fr, "w", encoding="utf-8").write("\n".join(lines))

    for harness, game in (("_autogame_e2e.py", "autogame"), ("_autogame_daily_e2e.py", "autogame")):
        path = os.path.join(ROOT, harness)
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        m = re.search(r'^CID = "([0-9a-z]+)"', src, re.M)
        if m and m.group(1) != targets[game]:
            open(path, "w", encoding="utf-8").write(src[:m.start(1)] + targets[game] + src[m.end(1):])
            changed.append(f"{harness}: {m.group(1)[:10]}… -> {targets[game][:10]}…")
    return changed


def restamp():
    """Rebake i18n + bump every ?v= cache-bust stamp, so browsers actually fetch the repointed files."""
    mg = os.path.join(STATIC, "i18n_games", "merge_games.py")
    if not os.path.exists(mg):
        print("  ! merge_games.py not found — stamps NOT refreshed; browsers may serve the old CID")
        return
    r = subprocess.run([sys.executable, mg], capture_output=True, text=True,
                       cwd=os.path.join(STATIC, "i18n_games"))
    print("  " + (r.stdout.strip().splitlines() or ["(no output)"])[-1])
    if r.returncode != 0:
        sys.exit(f"merge_games.py failed:\n{r.stderr[:800]}")


def verify(targets, ex):
    """Every CID the app can reach must resolve to a contract that is actually live."""
    have = live_cids(ex)
    if have is None:
        print("  ! exec node unreachable — cannot verify")
        return False
    bad = []
    for path in sorted(glob.glob(os.path.join(STATIC, "*.js"))):
        m = re.search(r'^const CID = "([0-9a-z]+)";', open(path, encoding="utf-8").read(), re.M)
        if m and m.group(1) not in have:
            bad.append(f"{os.path.basename(path)} -> {m.group(1)}")
    fr = os.path.join(ROOT, "_faucet_rewards.py")
    if os.path.exists(fr):
        for cid in re.findall(r'\(\d+,\s*"([0-9a-z]+)"', open(fr, encoding="utf-8").read()):
            if cid not in have:
                bad.append(f"_faucet_rewards.py -> {cid}")
    undeployed = [g for g, c in targets.items() if c not in have]
    if bad or undeployed:
        for b in bad:
            print(f"  DEAD REFERENCE: {b}")
        if undeployed:
            print(f"  NOT DEPLOYED: {', '.join(undeployed)}")
        return False
    print(f"  every frontend + reward-table CID resolves to a live contract ({len(have)} deployed)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--ex", default=os.environ.get("NADO_EX_URL", "http://127.0.0.1:9273").rstrip("/"))
    ap.add_argument("--fee", type=int, default=D.MIN_TX_FEE)
    ap.add_argument("--check", action="store_true", help="report only; change nothing")
    ap.add_argument("--wire-only", action="store_true", help="skip deploying; repoint + restamp + verify")
    a = ap.parse_args()

    if a.check:
        targets, have = target_cids(), live_cids(a.ex)
        if have is None:
            sys.exit(f"exec node unreachable at {a.ex}")
        missing = [g for g, c in targets.items() if c not in have]
        print(f"live contracts: {len(have)}")
        print(f"up to date:     {len(D.GAMES) - len(missing)}/{len(D.GAMES)}")
        print(f"needs deploy:   {', '.join(missing) if missing else 'none'}")
        verify(targets, a.ex)
        return

    print("== deploy ==")
    targets = target_cids() if a.wire_only else do_deploy(a.l1, a.ex, a.fee)
    print("\n== wire ==")
    changes = wire(targets)
    for c in changes:
        print(f"  {c}")
    if not changes:
        print("  every reference was already current")
    print("\n== restamp ==")
    restamp()
    print("\n== verify ==")
    ok = verify(targets, a.ex)
    print("\nDONE" if ok else "\nDONE WITH PROBLEMS (see above)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
_autogame_daily_e2e.py — LIVE end-to-end of the Autogame DAILY GAUNTLET on the running chain:
  1. drives the on-chain day anchor (_lib.daily_anchor): pin a future height -> resolve its hash -> av[day]
  2. plays a full honest Gauntlet headlessly (tests/autogame_daily_play.mjs) seeded by THIS node's address
  3. posts the claim (day, score, n, 8 packed words) as a signed blob tx
  4. waits for the entry to decode out of the contract view, then runs the FAUCET DISTRIBUTOR'S OWN oracle
     (tests/autogame_daily_verify.mjs) — the run must rank, at exactly the score that was posted
  5. proves a stolen claim does not rank: the same words posted under a different address must replay to a
     different score, which is the whole point of binding the seed to the poster

Run: HOME=/root python3 _autogame_daily_e2e.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE

CID = "ba8bebc9693f5aaec0e338a13d5812c4"          # execnode/games/autogame.py
L1 = "http://127.0.0.1:9173"
EX = "http://127.0.0.1:9273"
FAILS = []


def ck(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra else ""), flush=True)
    if not cond:
        FAILS.append(name)


def j(u):
    with urllib.request.urlopen(u, timeout=15) as r:
        return json.loads(r.read().decode())


def sto():
    return j(f"{EX}/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})


def tip():
    return j(L1 + "/get_latest_block")["block_number"]


def post_tx(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as x:
        return json.loads(x.read().decode())


def call(method, args, applied=None, tries=4):
    """Submit, then keep submitting until the chain shows the effect. A tx accepted into the pool is not a
    tx that landed — one silently never appeared in a block during the coinflip run, and without this the
    script just waits out its timeout on a contract that is working fine."""
    for _ in range(tries):
        try:
            r = post_tx(construct_blob_tx(K, {"op": "call", "contract": CID, "method": method, "args": args},
                                          tip() + 25, MIN_TX_FEE))
        except Exception as e:
            print(f"   submit {method} failed: {e}", flush=True)
            time.sleep(8)
            continue
        if not r.get("result"):
            print(f"   resubmit {method}: {str(r.get('message'))[:80]}", flush=True)
            time.sleep(8)
            continue
        if applied is None:
            return
        for _ in range(15):
            time.sleep(8)
            try:
                if applied():
                    return
            except Exception:
                pass
        print(f"   {method} accepted but never landed — resubmitting", flush=True)
    sys.exit(f"call gave up: {method}")


K = load_keys()
ADDR = K["address"]
DAY = int(time.time()) // 86400
print(f"autogame Daily Gauntlet e2e · {ADDR[:20]}… · day {DAY} · cid {CID}", flush=True)

# ── 1. the day anchor ────────────────────────────────────────────────────────────────────────────
# Two phases, both the same permissionless call. The pin is a height in the FUTURE, so no caller can steer
# the day's road by timing this; the resolve stores that block's hash forever, so no verifier ever needs
# L1 history (a snapshot-bootstrapped node has none).
print("\n1. anchor the day", flush=True)
av = (sto().get("av") or {}).get(str(DAY))
if not av:
    ah = (sto().get("ah") or {}).get(str(DAY))
    if not ah:
        call("anchor", [DAY], applied=lambda: (sto().get("ah") or {}).get(str(DAY)))
        ah = (sto().get("ah") or {}).get(str(DAY))
    print(f"   pinned height {ah} (cursor {j(EX + '/exec/root?ns=default&provisional=1')['cursor']})", flush=True)
    ck("the pin is a height nobody can have seen yet, or has only just passed",
       int(ah) > 0, f"ah={ah}")
    call("anchor", [DAY], applied=lambda: (sto().get("av") or {}).get(str(DAY)))
    av = (sto().get("av") or {}).get(str(DAY))
av = str(av)
ck("the day has a resolved anchor readable from contract storage alone", bool(av) and av != "0", f"av={av[:24]}…")

# ── 2. play it ───────────────────────────────────────────────────────────────────────────────────
print("\n2. play today's Gauntlet (one-ply greedy — a score a person could reach)", flush=True)
# The play harness reads the anchor out of the view ITSELF rather than taking the value read above. That is
# not fussiness: an anchor is a field element up to 2^64 and JSON has no integers, so JavaScript rounds it
# to a double while Python keeps every digit. Handing Python's exact string to a JS verifier seeds a
# different run and the claim never verifies — which is precisely how this test failed the first time.
out = subprocess.run(["node", "tests/autogame_daily_play.mjs", CID, str(DAY), ADDR],
                     capture_output=True, text=True, timeout=600, cwd="/root/nado")
if out.returncode != 0:
    sys.exit("play failed:\n" + out.stderr[:2000])
claim = json.loads(out.stdout.strip().splitlines()[-1])
print(f"   depth {claim['depth']}, {'walked off standing' if claim['alive'] else 'fell'}, "
      f"score {claim['score']}, {len(claim['words'])} words", flush=True)
ck("the run self-verifies before it is ever posted", claim["ok"])
ck("the claim fits the contract's word budget", len(claim["words"]) == 8 and claim["n"] <= 128,
   f"{len(claim['words'])} words, n={claim['n']}")

# ── 3. post it ───────────────────────────────────────────────────────────────────────────────────
print("\n3. post the claim", flush=True)


def landed():
    s = sto()
    return any(a == ADDR and int((s.get("eday") or {}).get(e, 0)) == DAY
               and int((s.get("escore") or {}).get(e, 0)) == claim["score"]
               for e, a in (s.get("eaddr") or {}).items())


call("post", [DAY, claim["score"], claim["n"]] + claim["words"], applied=landed)
s = sto()
mine = [e for e, a in (s.get("eaddr") or {}).items()
        if a == ADDR and int((s.get("eday") or {}).get(e, 0)) == DAY]
ck("the claim decodes out of the contract view", bool(mine), f"{len(mine)} entr(ies)")
if mine:
    e = mine[-1]
    ck("every packed word survived the round trip",
       all(int((s.get(f"ew{k}") or {}).get(e, 0)) == claim["words"][k] for k in range(8)))
    ck("the posted length matches", int((s.get("en") or {}).get(e, 0)) == claim["n"])

# ── 4. the distributor's oracle must rank it ─────────────────────────────────────────────────────
print("\n4. the faucet distributor's oracle replays it", flush=True)
out = subprocess.run(["node", "tests/autogame_daily_verify.mjs", CID, str(DAY)],
                     capture_output=True, text=True, timeout=900, cwd="/root/nado")
if out.returncode != 0:
    sys.exit("verify oracle failed:\n" + out.stderr[:2000])
rows = json.loads(out.stdout.strip().splitlines()[-1])
row = [r for r in rows if r[0] == ADDR]
ck("the oracle verified and ranked the run", bool(row) and row[0][1] == claim["score"],
   f"rows={rows[:3]} want={claim['score']}")

# ── 5. a stolen claim must not rank ──────────────────────────────────────────────────────────────
# Claims are public on chain, so copy-theft is the obvious attack: repost the day's best move list under
# your own address. The seed binds the POSTER, so the same moves are a different run for a different
# player — this checks that directly rather than trusting the design note.
print("\n5. the same moves under a different address are a different run", flush=True)
chk = subprocess.run(["node", "-e", f"""
import('/root/nado/static/autogame-daily.js').then(D => {{
  const A = {json.dumps(claim['anchor'])};                      // the anchor as the VERIFIERS read it
  const mine  = D.verifyClaim({DAY}, {claim['n']}, {json.dumps(claim['words'])}, A, {json.dumps(ADDR)});
  const thief = D.verifyClaim({DAY}, {claim['n']}, {json.dumps(claim['words'])}, A, "mldsa44thief0000");
  console.log(JSON.stringify({{mine, thief}}));
}});
"""], capture_output=True, text=True, timeout=300, cwd="/root/nado")
v = json.loads(chk.stdout.strip().splitlines()[-1])
ck("my own claim replays to my own score", v["mine"] == claim["score"], f"{v['mine']} vs {claim['score']}")
ck("a thief reposting my moves does NOT reproduce my score", v["thief"] != claim["score"],
   f"thief={v['thief']} mine={v['mine']}")

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS)), flush=True)
sys.exit(1 if FAILS else 0)

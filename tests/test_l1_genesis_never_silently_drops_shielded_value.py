"""L1 genesis never silently drops shielded value: a SHIELD_ESCROW balance that no exec genesis of THIS generation accounts
for refuses to build (review 2026-10-12; genesis.py make_genesis "NO SILENT DROP OF SHIELDED VALUE").

genesis.py asserted SHIELD_ESCROW == stwo_value + pool_fees only when the exec genesis document was present, for this
generation, and carried the shielded section. With the document missing (not committed with the other genesis files)
or left over from another generation (exec_genesis.load() then ignores it), the exec layer started with an EMPTY Stwo
pool while SHIELD_ESCROW still held the carried notes' value: every carried note lost, silently. Pins, by building a real
L1 genesis in a child process (throwaway HOME):
  1. no document, SHIELD_ESCROW non-empty -> refused;
  2. a document for another generation, SHIELD_ESCROW non-empty -> refused (even though that document would have
     accounted for exactly that escrow on its own generation);
  3. a document of this generation without the shielded section, SHIELD_ESCROW non-empty -> refused;
  4. SHIELD_ESCROW empty and no document -> builds (a fresh chain);
  5. the live generation's own tracked allocation still builds: gen 28 holds genesis.UNCARRIED_SHIELD_ESCROW (1,123,000
     raw stranded before the carry existed) with no exec genesis, and a fresh node must still build it — exactly that
     amount, on gen 28 only (one raw more refuses; the same amount on generation 29 refuses);
  6. a document that accounts for it (stwo_value + pool_fees == escrow) builds.
Run: python3 tests/test_l1_genesis_never_silently_drops_shielded_value.py
"""
import os, sys, json, tempfile, subprocess
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-genesis-shield-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if os.environ.get("NADO_TEST_PHASE") == "l1":
    import logging
    import protocol as P
    if os.environ.get("NADO_TEST_GEN"):
        P.CHAIN_GENERATION = int(os.environ["NADO_TEST_GEN"])     # before genesis / exec_genesis read it
    os.makedirs(os.path.join(H, "nado", "private"), exist_ok=True)
    esc = int(os.environ["NADO_TEST_ESCROW"])
    json.dump([{"address": P.SHIELD_ESCROW, "balance": esc, "bonded": 0}] if esc else [],
              open(os.path.join(H, "nado", "private", "genesis_alloc.dat"), "w"))
    json.dump([], open(os.path.join(H, "nado", "private", "genesis_open.dat"), "w"))
    from genesis import make_folders, make_genesis
    make_folders()
    try:
        make_genesis(address=P.GENESIS_ADDRESS, balance=P.TREASURY_GENESIS, ip="127.0.0.1", port=9173,
                     timestamp=P.GENESIS_TIMESTAMP, logger=logging.getLogger("t"))
    except SystemExit as e:
        print("REFUSED", e)
        sys.exit(3)
    print("BUILT")
    sys.exit(0)

import protocol as P
import genesis as G
from execnode import shielded_stwo as SP

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def l1(escrow, doc=None, gen=None):
    home = tempfile.mkdtemp(dir=H)
    gfile = os.path.join(home, "exec_genesis.json")          # never the tracked file: absent unless written here
    if doc is not None:
        json.dump(doc, open(gfile, "w"))
    env = dict(os.environ, NADO_TEST_PHASE="l1", NADO_TEST_ESCROW=str(escrow), HOME=home, NADO_EXEC_GENESIS=gfile,
               NADO_EXEC_STATE=os.path.join(home, "exec_state.json"), NADO_EXEC_DA=os.path.join(home, "exec_da"))
    if gen is not None:
        env["NADO_TEST_GEN"] = str(gen)
    return subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True, timeout=600)


def built(r):
    return r.returncode == 0 and "BUILT" in r.stdout


def refused(r):
    return r.returncode == 3 and "SHIELD_ESCROW" in r.stdout


cm = SP.commit(5, SP.owner_of("ab" * 32), 1)
shield_doc = {"contracts": {}, "bridge": {}, "stwo_value": "5", "pool_fees": "2",
              "stwo_pool": {"commitments": [cm], "nullifiers": []}}
GEN = P.CHAIN_GENERATION

r = l1(7)
check("1. no exec genesis and a non-empty SHIELD_ESCROW refuses (the carried notes would be dropped)", refused(r),
      (r.returncode, r.stdout[-300:], r.stderr[-300:]))
r = l1(7, dict(shield_doc, generation=GEN - 1))
check("2. an exec genesis for another generation refuses too (load() ignores it)", refused(r), (r.returncode, r.stdout[-300:]))
r = l1(7, {"generation": GEN, "contracts": {}, "bridge": {}})
check("3. a document of this generation without the shielded section refuses", refused(r), (r.returncode, r.stdout[-300:]))
r = l1(0)
check("4. an empty SHIELD_ESCROW and no document builds (a fresh chain)", built(r), (r.returncode, r.stdout[-300:], r.stderr[-500:]))
check("5. the gen-28 residual is the one the tracked allocation holds", G.UNCARRIED_SHIELD_ESCROW == 1_123_000 and any(
    e["address"] == P.SHIELD_ESCROW and int(e["balance"]) == G.UNCARRIED_SHIELD_ESCROW
    for e in json.load(open(os.path.join(ROOT, "genesis_data", "genesis_alloc.dat")))) if GEN == 28 else True)
r = l1(G.UNCARRIED_SHIELD_ESCROW, gen=28)
check("...gen 28 builds with exactly that residual and no exec genesis (a fresh node joining betanet-9)", built(r),
      (r.returncode, r.stdout[-300:], r.stderr[-500:]))
r = l1(G.UNCARRIED_SHIELD_ESCROW + 1, gen=28)
check("...one raw more refuses", refused(r), (r.returncode, r.stdout[-300:]))
r = l1(G.UNCARRIED_SHIELD_ESCROW, gen=29)
check("...and the same residual on the next generation refuses (the carry always writes the shielded section there)",
      refused(r), (r.returncode, r.stdout[-300:]))
r = l1(7, dict(shield_doc, generation=GEN))
check("6. a document that accounts for SHIELD_ESCROW builds", built(r), (r.returncode, r.stdout[-300:], r.stderr[-500:]))

print("ALL PASS — L1 genesis never silently drops shielded value" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

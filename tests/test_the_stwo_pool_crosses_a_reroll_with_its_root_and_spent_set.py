"""The Stwo shielded pool crosses a reroll with its root, its spent set and its value, and SHIELD_ESCROW keeps backing it
(tools/alphanet6_carryforward.exec_shield_doc, execnode/exec_genesis.py, genesis.py).

Before 2026-10-12 the carry REFUSED a non-empty Stwo pool: holders had to unshield before every reroll, which publishes
every holder's amount and destination — a forced de-anonymisation of the whole pool. Now the pool carries. Pins, on the
real carry builder, the real exec layer and the real L1 genesis (throwaway HOME):
  1. the carry accepts a Stwo pool whose value explains pool_value, and still refuses notes in every other pool, a
     pool_value the Stwo pool does not explain, and stwo_value with no note;
  2. SHIELD_ESCROW must back the carried notes: less than stwo_value + in-pool fees refuses; the surplus (fees burned
     in-pool, stranded deposits) is carried as pool_fees, so escrow == stwo_value + pool_fees exactly;
  3. the genesis document keeps the commitments in order, the nullifiers sorted, and NO block marks; a document naming
     marks, a digest in another spelling, unsorted nullifiers or value without a note is refused when loaded;
  4. the new exec layer has the old one's stwo_root, nullifier digest and stwo_value (the exec-root records equal but for
     the marks record), its root is genesis_root(), and the shielded invariant is exact (OK) against the carried escrow;
  5. the carried root is a spend anchor at the new chain's first block, and the first append on the new chain works
     (a carried old-chain mark would make it raise);
  6. an already-spent nullifier stays spent: stwo_spend_refusal refuses it on the new chain;
  7. L1 genesis builds when SHIELD_ESCROW == stwo_value + pool_fees and refuses otherwise.
The real-proof half (an old note SPENDS on the new chain) is tests/test_an_old_stwo_note_spends_on_the_new_chain_and_a_
spent_one_stays_spent.py.

Run: python3 tests/test_the_stwo_pool_crosses_a_reroll_with_its_root_and_spent_set.py
"""
import os, sys, json, tempfile, subprocess
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-carry-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
# THIS TEST'S OWN GENESIS ONLY: genesis.py seeds genesis_data/genesis_carry.dat when it names the live generation — the
# REAL chain's carried identities and open invites, whose INVITE_ESCROW a test alloc does not hold (the gen-29 rehearsal
# refused every genesis here, 2026-10-25). A path that does not exist = no carry file.
os.environ["NADO_GENESIS_CARRY"] = os.path.join(H, "no_genesis_carry.dat")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
GEN_FILE = os.environ.get("NADO_EXEC_GENESIS") or os.path.join(H, "exec_genesis.json")   # the L1 child inherits it
os.environ["NADO_EXEC_GENESIS"] = GEN_FILE
import protocol as P

import _harness
_report = _harness.Report()
check = _report.check


if os.environ.get("NADO_TEST_PHASE") == "l1":
    # 7) L1 genesis in a child process with its own HOME (make_genesis writes the L1 database)
    import logging
    os.makedirs(os.path.join(H, "nado", "private"), exist_ok=True)
    json.dump([{"address": P.SHIELD_ESCROW, "balance": int(os.environ["NADO_TEST_ESCROW"]), "bonded": 0}],
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

from execnode.state import ExecState
from execnode import exec_genesis as EG, exec_root_b2 as ER, shielded_stwo as SP
from ops import invariants as INV
import tools.alphanet6_carryforward as C

GATE = 182_000                           # a test height on the old chain (the pool holds from block 1)
own = SP.owner_of("11" * 32)

# ---- the old chain: seven deposits over three blocks, two of the notes spent (pool.spend, as the transfer does) ----
old = ExecState(os.path.join(H, "old.json"))
for blk, vals in ((GATE, (5, 7)), (GATE + 3, (11, 13, 17)), (GATE + 9, (19, 23))):
    old.cursor = blk - 1
    for i, v in enumerate(vals):
        r = old.apply_field_shield(v, own, blk * 10 + i)
        assert "stwo note" in r, r
NF1, NF2 = SP.nullifier("22" * 32, 1), SP.nullifier("22" * 32, 2)
old.stwo_pool.spend(NF2)
old.stwo_pool.spend(NF1)
old.stwo_value -= 12                     # the two spends took 12 out (unshield + fee), as _apply_stwo_transfer does
old.pool_value -= 12
old.pool_fees += 2                       # ...2 of it burned as fees
old.cursor = GATE + 20
check("setup: the old chain holds 7 Stwo notes over 3 block marks, 2 nullifiers, stwo_value 83",
      len(old.stwo_pool.commitments) == 7 and len(old.stwo_pool.marks) == 3 and old.stwo_value == 83
      and old.pool_value == 83, (old.stwo_pool.marks, old.stwo_value))
snap = json.loads(json.dumps(old._snapshot()))

# ---- 1. what the carry refuses and accepts ----
check("1. a Stwo pool whose value explains pool_value is no longer a refusal", C.exec_value_the_carry_would_drop(snap) == [],
      C.exec_value_the_carry_would_drop(snap))
for pool in ("shielded", "field_pool", "wide_pool"):
    got = C.exec_value_the_carry_would_drop(dict(snap, **{pool: {"commitments": ["ab" * 32], "nullifiers": []}}))
    check(f"...notes in the {pool} are still refused", len(got) == 1 and pool in got[0], got)
check("...app_state notes are still refused",
      any("app_state" in r for r in C.exec_value_the_carry_would_drop(dict(snap, app_state={"trees": {"x": 1}}))))
got = C.exec_value_the_carry_would_drop(dict(snap, pool_value=90))
check("...a pool_value the Stwo pool does not explain is refused (7 raw sit in a pool the carry does not move)",
      len(got) == 1 and "pool_value" in got[0] and "7 raw" in got[0], got)
got = C.exec_value_the_carry_would_drop({"stwo_value": 5, "pool_value": 5})
check("...stwo_value with no Stwo note is refused", any("holds no note" in r for r in got), got)
got = C.exec_value_the_carry_would_drop(dict(snap, stwo_pool=dict(snap["stwo_pool"], commitments=["AB" * 32])))
check("...a Stwo pool the exec layer would not load is refused", any("cannot be carried" in r for r in got), got)

# ---- 2. SHIELD_ESCROW backs the carried notes ----
def refused(fn):
    try:
        fn()
        return ""
    except SystemExit as e:
        return str(e)
why = refused(lambda: C.exec_shield_doc(snap, 83 + 2 - 1))
check("2. an escrow below stwo_value + in-pool fees refuses (an unbacked note would carry)",
      "REFUSING" in why and "does not back" in why, why)
STRANDED = 1_123_000                     # betanet-9's SHIELD_ESCROW residual, locked since an earlier generation
sdoc = C.exec_shield_doc(snap, 83 + 2 + STRANDED)
check("...the surplus (fees burned in-pool + stranded deposits) carries as pool_fees: escrow == stwo_value + pool_fees",
      int(sdoc["stwo_value"]) == 83 and int(sdoc["pool_fees"]) == 2 + STRANDED, sdoc)
check("...an empty pool carries only the residual, with no pool section",
      C.exec_shield_doc({}, STRANDED) == {"stwo_value": "0", "pool_fees": str(STRANDED)}, C.exec_shield_doc({}, STRANDED))

# ---- 3. the genesis document ----
check("3. the document keeps the commitments in order, the nullifiers sorted, and no marks",
      sdoc["stwo_pool"] == {"commitments": old.stwo_pool.commitments, "nullifiers": sorted([NF1, NF2])}, sdoc.get("stwo_pool"))


def write_gen(extra, generation=None):
    json.dump({"generation": P.CHAIN_GENERATION if generation is None else generation, "contracts": {}, "bridge": {},
               **extra}, open(GEN_FILE, "w"))
    EG._CACHE.clear()


def load_refused(extra):
    write_gen(extra)
    try:
        EG.load()
        return False
    except ValueError:
        return True
check("...a document naming block marks is refused",
      load_refused(dict(sdoc, stwo_pool=dict(sdoc["stwo_pool"], marks=[[GATE, 2]]))))
check("...a nullifier in another spelling is refused",
      load_refused(dict(sdoc, stwo_pool=dict(sdoc["stwo_pool"], nullifiers=[NF1.upper()]))))
check("...unsorted nullifiers are refused",
      load_refused(dict(sdoc, stwo_pool=dict(sdoc["stwo_pool"], nullifiers=sorted([NF1, NF2], reverse=True)))))
check("...stwo_value without a note is refused", load_refused({"stwo_value": "5", "pool_fees": "0"}))

# ---- 4. the new exec layer ----
write_gen(json.loads(json.dumps(sdoc)))
new = ExecState(os.path.join(H, "new.json"))
check("4. a fresh exec layer loads the carried pool", EG.apply(new) and len(new.stwo_pool.commitments) == 7)
check("...with the old stwo_root, nullifier digest and stwo_value",
      (new.stwo_pool.root(), new.stwo_pool.nullifier_digest(), new.stwo_value)
      == (old.stwo_pool.root(), old.stwo_pool.nullifier_digest(), old.stwo_value))
check("...and no marks: they named old-chain heights", new.stwo_pool.marks == [])
marks_key = ER.record_key(ER.T_DIGEST, "stwo_marks", old.stwo_pool.marks_digest())
ro, rn = ER.records_projection(old), ER.records_projection(new)
check("...the exec-root records equal the old layer's but for the marks record",
      marks_key in ro and {k: v for k, v in ro.items() if k != marks_key} == rn)
check("...its root is genesis_root() (every node computes it from the document alone)", new.state_root() == EG.genesis_root())
check("...pool_value is stwo_value and pool_fees the carried residual",
      new.pool_value == 83 and new.pool_fees == 2 + STRANDED, (new.pool_value, new.pool_fees))
ok, det = INV.check_shielded(lambda a, create_on_error=False: {"balance": EG.shield_total()} if a == P.SHIELD_ESCROW else None, new)
check("...the shielded invariant is EXACT against the carried escrow (OK, not STRANDED)",
      ok and det["status"] == INV.OK and EG.shield_total() == 83 + 2 + STRANDED, det)
check("...loading twice is a no-op", not EG.apply(new))

# ---- 5. anchors and the first append on the new chain ----
new.cursor = 0                           # block 1 of the new chain
check("5. the carried root is a spend anchor at the new chain's first block",
      new.stwo_pool.knows_root(old.stwo_pool.root(), 1))
r = new.apply_field_shield(29, own, 999)
check("...the first deposit on the new chain appends at block 1 and marks it",
      "stwo note #8" in r and new.stwo_pool.marks == [[1, 8]] and new.stwo_value == 83 + 29, (r, new.stwo_pool.marks))
stale = SP.StwoShieldedPool.from_dict(old.stwo_pool.to_dict())
try:
    stale.append(SP.commit(1, own, 4242), 1)
    stale_raised = False
except ValueError:
    stale_raised = True
check("...whereas a pool carrying its old-chain marks could not append at block 1 (why marks restart empty)", stale_raised)

# ---- 6. an already-spent nullifier stays spent ----
why = new.stwo_spend_refusal(new.stwo_pool.root(), NF1, SP.commit(1, own, 7001), SP.commit(1, own, 7002), 1, 0, 1)
check("6. a nullifier spent on the old chain is refused on the new one", why and "double-spend" in why, why)
why = new.stwo_spend_refusal(new.stwo_pool.root(), SP.nullifier("22" * 32, 3), SP.commit(1, own, 7001),
                             SP.commit(1, own, 7002), 1, 0, 1)
check("...while an unspent one passes every check but the proof", why is None, why)


# ---- 7. L1 genesis ----
def l1(escrow):
    env = dict(os.environ, NADO_TEST_PHASE="l1", NADO_TEST_ESCROW=str(escrow), HOME=tempfile.mkdtemp(dir=H))
    env["NADO_EXEC_STATE"] = os.path.join(env["HOME"], "exec_state.json")
    env["NADO_EXEC_DA"] = os.path.join(env["HOME"], "exec_da")
    return subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True, timeout=600)
good = l1(83 + 2 + STRANDED)
check("7. L1 genesis builds when SHIELD_ESCROW == stwo_value + pool_fees",
      good.returncode == 0 and "BUILT" in good.stdout, (good.returncode, good.stdout[-300:], good.stderr[-500:]))
for off in (-1, 1):
    bad = l1(83 + 2 + STRANDED + off)
    check(f"...and refuses when it holds {'less' if off < 0 else 'more'}",
          bad.returncode == 3 and "SHIELD_ESCROW" in bad.stdout, (bad.returncode, bad.stdout[-300:]))
json.dump({"generation": P.CHAIN_GENERATION, "contracts": {}, "bridge": {}}, open(GEN_FILE, "w"))
old_doc = l1(STRANDED)
# genesis.UNCARRIED_SHIELD_ESCROW is generation 28's OWN stranded allocation (built before the Stwo carry existed); from
# generation 29 the carry always writes the shielded section, so a document without one may hold nothing in the escrow
if P.CHAIN_GENERATION == 28:
    check("...a document without the shielded section accepts gen 28's own stranded escrow (as before the carry)",
          old_doc.returncode == 0, (old_doc.returncode, old_doc.stdout[-300:]))
else:
    check(f"...on generation {P.CHAIN_GENERATION} a document without the shielded section refuses a non-empty escrow "
          "(gen 28's exception is its own)", old_doc.returncode == 3 and "SHIELD_ESCROW" in old_doc.stdout,
          (old_doc.returncode, old_doc.stdout[-300:]))
empty = l1(0)
check("...and an empty escrow builds without the shielded section on any generation", empty.returncode == 0,
      (empty.returncode, empty.stdout[-300:]))

print("ALL PASS — the Stwo pool crosses a reroll with its root and spent set" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)

"""A Stwo note made on the old chain spends on the new chain with a REAL proof against the carried root, and a note
spent on the old chain stays spent (tools/alphanet6_carryforward.exec_shield_doc, execnode/exec_genesis.py).

The carry exists so a reroll never forces holders to unshield (which publishes every holder's amount and destination).
That promise is only kept if a note a wallet holds is still SPENDABLE afterwards: its leaf position, the root it proves
against and its nullifier must all mean the same on the new chain. The pure half (roots, digests, escrow, L1 genesis)
is tests/test_the_stwo_pool_crosses_a_reroll_with_its_root_and_spent_set.py; this one proves the spend. Pins:
  1. eleven deposits on the old chain rebuild the real prover's fixture b (the root inside the real proof);
  2. the carry builds the exec genesis from the old snapshot, and a fresh exec layer loaded from it has the same root;
  3. on the new chain (block 1, the gate at 1 as a fresh generation has it) the real proof applies through the native
     verifier: nullifier spent, both outputs appended, the unshield an exit to the bound destination, stwo_value down
     by unshield + fee;
  4. a note spent on the OLD chain, carried, cannot be spent again on the new one: the same proof is refused as a
     double-spend and changes nothing.
SKIPs without a stable cargo (the verifier) or the nightly toolchain (the prover).

Run: python3 tests/test_an_old_stwo_note_spends_on_the_new_chain_and_a_spent_one_stays_spent.py
"""
import os, sys, tempfile, struct, copy, json, subprocess
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-carry-e2e-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
GEN_FILE = os.path.join(_T, "exec_genesis.json")
os.environ["NADO_EXEC_GENESIS"] = GEN_FILE
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests._stwo_js_build import Env

import _harness
_report = _harness.Report()
check = _report.check


env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo: the verifier cannot be built here"); sys.exit(0)
nbin = env.nightly_bin()
if not nbin:
    print("SKIP  no nightly-2026-01-15 toolchain: the prover cannot be built here"); sys.exit(0)
so, _s, log = env.build_verifier()
exe, _p, plog = env.build_prover(nbin)
if not so or not exe:
    print("FAIL  build", (log or "")[-500:], (plog or "")[-500:]); sys.exit(1)
os.environ["NADO_STWO_JS_LIB"] = so

import protocol as P
from execnode.state import ExecState
from execnode import shielded_stwo as SP, exec_genesis as EG
from ops.address_ops import make_address
import tools.alphanet6_carryforward as C

from execnode.stark import stwo_js_native as SJ

DEST = make_address("cd" * 1312)


def bundle_at(cfg):
    """Fixture b proved at node config `cfg` -> (bundle, public inputs)."""
    out = tempfile.mkdtemp(dir=_T)
    r = subprocess.run([exe, "b", DEST, out, "-", str(cfg)], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-1000:]
    proof = open(os.path.join(out, "proof.bin"), "rb").read()
    pub = json.load(open(os.path.join(out, "public.json")))
    return ({"stark": {"stwo_js": {"proof": proof.hex(), "root": pub["root"], "nf": pub["nf"], "cm_out1": pub["cm1"],
                                   "cm_out2": pub["cm2"], "unshield": pub["unshield"], "fee": pub["fee"]}},
             "withdraw_addr": DEST}, pub)


# EACH CHAIN VERIFIES AT ITS OWN NODE CONFIG (STWO_JS_128_HEIGHT): the old chain at the running generation's rule, the
# new one at `else 1` — the 128-bit config from block 1. A note carried across is spent there with a NEW proof, made at
# the new chain's config; the old chain's proof would be refused for its config (tests/
# test_stwo_js_honest_proof_verifies_and_forged_public_inputs_are_refused.py). Same witness, so the same public inputs.
LIVE_128 = P.STWO_JS_128_HEIGHT
OLD_GATE = 182_000
old_bundle, pub = bundle_at(SJ.config_id_at(OLD_GATE + 40))
P.STWO_JS_128_HEIGHT = 1
bundle, pub_new = bundle_at(SJ.config_id_at(1))
P.STWO_JS_128_HEIGHT = LIVE_128
assert pub_new == pub, (pub_new, pub)

# fixture b (native/stwo_js/src/prover.rs fixture_b), as tests/test_a_stwo_spend_applies_end_to_end.py builds it
w = lambda *x: struct.pack("<8I", *x).hex()
o1 = SP.owner_of(w(0xFEED, 9, 9, 9, 9, 9, 9, 9))
nsk = w(0x12345678, 0x9ABCDEF0, 0x0F0F0F0F, 0xDEADBEEF, 0x0BADF00D, 0x77777777, 0x2468ACE0, 0x13579BDF)
v_in, rho = 0x0123456789ABCDEF & ((1 << 61) - 1), 0x5EED5EED5EED


def old_chain(spend_too):
    """The old chain: fixture b's eleven notes deposited in two blocks past the gate (so the pool has old-chain marks),
    optionally the spend applied there too."""
    P.STWO_POOL_HEIGHT = OLD_GATE
    P.STWO_JS_128_HEIGHT = LIVE_128         # the old chain: the running generation's rule
    st = ExecState(os.path.join(_T, f"old{int(spend_too)}.json"))
    st.cursor = OLD_GATE - 1
    for i in range(6):
        st.apply_field_shield(i * 3 + 1, o1, i)
    st.cursor = OLD_GATE + 4
    for i in range(6, 10):
        st.apply_field_shield(i * 3 + 1, o1, i)
    st.apply_field_shield(v_in, SP.owner_of(nsk), rho)
    if spend_too:
        st.cursor = OLD_GATE + 40
        res = st.apply_field_transfer(copy.deepcopy(old_bundle))
        assert "field-transfer stwo" in res, res
        st.unshield_withdrawals.clear()     # the carry folds a pending unshield exit into L1 (debited from the escrow)
    st.cursor = OLD_GATE + 100
    return st


def new_chain(old, escrow):
    """Carry `old` exactly as the tool does (refusal check, exec genesis document, JSON file) and load a fresh layer."""
    snap = json.loads(json.dumps(old._snapshot()))
    lost = C.exec_value_the_carry_would_drop(snap)
    assert lost == [], lost
    json.dump({"generation": P.CHAIN_GENERATION, "contracts": {}, "bridge": {}, **C.exec_shield_doc(snap, escrow)},
              open(GEN_FILE, "w"), indent=0, sort_keys=True)
    EG._CACHE.clear()
    P.STWO_POOL_HEIGHT = 1                  # a fresh generation: `STWO_POOL_HEIGHT = ... else 1`
    P.STWO_JS_128_HEIGHT = 1                # ...and `STWO_JS_128_HEIGHT = ... else 1`: spends prove at 128 bits
    st = ExecState(os.path.join(_T, f"new-{len(os.listdir(_T))}.json"))
    assert EG.apply(st)
    st.cursor = 0                           # block 1 of the new chain
    return st


old = old_chain(spend_too=False)
check("1. eleven deposits on the old chain rebuild fixture b: the pool's root is the root inside the real proof",
      old.stwo_pool.root() == pub["root"] and len(old.stwo_pool.marks) == 2, (old.stwo_pool.root(), pub["root"]))
new = new_chain(old, escrow=old.stwo_value)
check("2. the carried layer has the old stwo_root and nullifier digest, and its root is genesis_root()",
      new.stwo_pool.root() == old.stwo_pool.root() and new.stwo_pool.nullifier_digest() == old.stwo_pool.nullifier_digest()
      and new.state_root() == EG.genesis_root() and new.stwo_pool.marks == [])
v0 = new.stwo_value
r = new.apply_field_transfer(copy.deepcopy(bundle))
uw = list(new.unshield_withdrawals.values())
check("3. the old note SPENDS on the new chain with the real proof against the carried root", "field-transfer stwo" in r, r)
check("...the nullifier is spent and both outputs appended at block 1",
      new.stwo_pool.has_nullifier(pub["nf"]) and new.stwo_pool.commitments[-2:] == [pub["cm1"], pub["cm2"]]
      and new.stwo_pool.marks == [[1, 13]], new.stwo_pool.marks)
check("...the unshield is an exit to the bound destination", uw and uw[-1] == {"addr": DEST, "amount": pub["unshield"]}, uw)
check("...and stwo_value falls by exactly unshield + fee", v0 - new.stwo_value == pub["unshield"] + pub["fee"],
      (v0, new.stwo_value))

spent = old_chain(spend_too=True)
check("setup: the same note spent on the old chain", spent.stwo_pool.has_nullifier(pub["nf"]))
new2 = new_chain(spent, escrow=spent.stwo_value + spent.pool_fees)
check("...its nullifier is carried", new2.stwo_pool.has_nullifier(pub["nf"])
      and new2.stwo_pool.nullifier_digest() == spent.stwo_pool.nullifier_digest())
before = copy.deepcopy(new2._snapshot())
r = new2.apply_field_transfer(copy.deepcopy(bundle))
check("4. spending it again on the new chain is refused as a double-spend and changes nothing",
      "double-spend" in r and new2._snapshot() == before, r)

print("ALL PASS — an old Stwo note spends on the new chain and a spent one stays spent" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)

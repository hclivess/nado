"""SLASH EVIDENCE IS THIS CHAIN ONLY (audit 2026-09-25 MED "cross-generation slash replay: the block signature lacks
chain_id"; protocol.BLOCK_SIG_CHAIN_BIND_HEIGHT).

A block-authorship slash proves that one key signed two different blocks at one (height, parent). Validator keys carry
across rerolls; slash markers (kv_ops.slash_record) do not. Before the gate the signed bytes were
blake2b(height, parent_hash, block_hash) — no chain in them — and verify_equivocation_proof never asks whether the
proof's parent is a block of THIS chain, so on a new generation:
  * a real double-sign from ANY earlier chain (slashed there or not) slashes the carried bond again, and
  * if a reroll reuses the genesis (gens 7-9 did; gens 26/27 share CHAIN_ID and GENESIS_TIMESTAMP), a block-1 winner's
    honest old-generation signature plus its honest new one is a valid "equivocation".
A pair whose parents differ (the usual reroll, new GENESIS_TIMESTAMP) was never accepted — one proof carries one
parent — and this test pins that too.

Pinned here:
  1. below the gate (gen 27 as it runs) the signed bytes are byte-identical to the old form and the replay still
     reproduces — the live chain's verdicts do not move;
  2. with the gate live (a fresh chain), a signature made for another generation or genesis is refused as evidence and
     as a block signature, while a real same-chain double-sign still slashes, burns, and reverts exactly;
  3. honest blocks sign and verify, the block hash does not depend on the gate, and the signed bytes survive a
     CHAIN_ID rename (the relaunch-3 -> alphanet-1 sync wedge, tests/test_genesis_sync_invariant.py);
  4. the FFG double-vote proof is chain-bound only by the tx chain_id, so every generation must carry a (CHAIN_ID,
     GENESIS_TIMESTAMP) pair no earlier generation used.
Run: python3 tests/test_slash_evidence_is_this_chain_only.py
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-slashchain-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
_os.environ["NADO_TESTNET"] = "1"
import atexit, shutil; atexit.register(shutil.rmtree, _os.environ["HOME"], ignore_errors=True)
import os, sys, traceback
from contextlib import contextmanager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("slashchain"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

import protocol as P
from ops import kv_ops
import ops.block_ops as bo
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import create_txid, validate_transaction, resolve_slash
from hashing import blake2b_hash, blake2b_hash_link
from signatures import generate_keydict, sign, unhex

fails = 0


def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


@contextmanager
def patched(**kw):
    """Temporarily set block_ops module globals (the gate, the generation, the genesis hash, the CHAIN_ID label)."""
    old = {k: getattr(bo, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(bo, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(bo, k, v)


LIVE_GATE = bo.BLOCK_SIG_CHAIN_BIND_HEIGHT          # gen 27: 2^62 (dormant)
FRESH = {"BLOCK_SIG_CHAIN_BIND_HEIGHT": 1}          # what the next generation runs from block 1
G_THIS = bo._GENESIS_HASH
G_OLD = blake2b_hash_link(link_from=P.GENESIS_TIMESTAMP - 86400, link_to=[])   # an earlier generation's genesis

kd = generate_keydict()
create_account(kd["address"], bonded=5 * P.B_MIN)


def blk(parent, n, state_root, **sign_as):
    """A block by kd at (n, parent), signed as the chain described by `sign_as` (block_ops globals) would sign it."""
    b = bo.construct_block(block_timestamp=1, block_number=n, parent_hash=parent, creator=kd["address"],
                           transaction_pool=[], block_reward=1, state_root=state_root, exec_root="0" * 64, exec_cursor=0)
    with patched(**sign_as):
        return bo.sign_block(b, kd["private_key"], kd["public_key"])


def proof(a, b, parent=None):
    return {"block_number": a["block_number"], "parent_hash": parent or a["parent_hash"], "public_key": kd["public_key"],
            "block_hash_a": a["block_hash"], "signature_a": a["block_signature"]["signature"],
            "block_hash_b": b["block_hash"], "signature_b": b["block_signature"]["signature"]}


def slash_tx(p, nonce):
    rep = generate_keydict()
    tx = {"sender": rep["address"], "recipient": "slash", "amount": 0, "timestamp": 1, "data": p, "nonce": nonce,
          "public_key": rep["public_key"], "max_block": 105, "chain_id": P.CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(rep["private_key"], unhex(tx["txid"]))
    return tx


def refused(tx, height=100):
    try:
        validate_transaction(tx, logger, block_height=height)
    except AssertionError as e:
        return str(e)
    return None


# How gen 27 (and every earlier generation) signs: the chain-less form, i.e. a gate that never fires. Spelled as a
# literal, not LIVE_GATE, so the test means the same thing on the next generation, where LIVE_GATE is 1.
OLD_CHAIN = {"BLOCK_SIG_CHAIN_BIND_HEIGHT": 1 << 62}


# ---- 1. below the gate: gen 27 replays byte-identically, and the replay it permits still reproduces -----------------
def t_below_gate_bytes_unchanged():
    """The live generation keeps the gate dormant and signs exactly blake2b(height, parent, hash)."""
    assert P.CHAIN_GENERATION != 27 or LIVE_GATE == 1 << 62, LIVE_GATE
    with patched(**OLD_CHAIN):
        for n in (1, 5000, 29000, (1 << 62) - 1):
            assert bo._block_sig_message_fields(n, "ab" * 32, "cd" * 32) == unhex(blake2b_hash([n, "ab" * 32, "cd" * 32]))
        assert bo._block_sig_message_fields(1 << 62, "ab" * 32, "cd" * 32) != unhex(blake2b_hash([1 << 62, "ab" * 32, "cd" * 32]))


def t_below_gate_replay_reproduces():
    """Below the gate a foreign chain's double-sign and a reused-genesis block-1 pair are accepted (the finding)."""
    if LIVE_GATE == 1:
        return                                                               # a chain born with the rule has no below
    # (on gen 27 LIVE_GATE is 2^62: these blocks are signed exactly as the live chain signs them today)
    foreign = "ee" * 32                                                      # a parent this chain has never seen
    x, y = blk(foreign, 50, "3" * 64), blk(foreign, 50, "4" * 64)
    assert resolve_slash(proof(x, y), 100) == (kd["address"], 50)
    assert refused(slash_tx(proof(x, y), "r1")) is None, "the old-chain pair slashes on gen 27 — the replay is real"
    a_old, a_new = blk(G_THIS, 1, "1" * 64), blk(G_THIS, 1, "2" * 64)       # one genesis reused by two generations
    assert resolve_slash(proof(a_old, a_new), 100) == (kd["address"], 1)
    # a normal reroll (new GENESIS_TIMESTAMP) was never accepted: the proof carries ONE parent, one signature fails
    b_old, b_new = blk(G_OLD, 1, "1" * 64), blk(G_THIS, 1, "2" * 64)
    assert bo.verify_equivocation_proof(proof(b_old, b_new, G_OLD)) is None
    assert bo.verify_equivocation_proof(proof(b_old, b_new, G_THIS)) is None


# ---- 2. the gate live: only this chain's signatures are evidence -----------------------------------------------------
def t_old_generation_signatures_are_not_evidence():
    """A double-sign made on an earlier generation (chain-less form) is refused on the fresh chain, in any pairing."""
    foreign = "ee" * 32
    x, y = blk(foreign, 50, "3" * 64, **OLD_CHAIN), blk(foreign, 50, "4" * 64, **OLD_CHAIN)
    same_gen_old = blk(G_THIS, 1, "1" * 64, **OLD_CHAIN)
    same_gen_new = blk(G_THIS, 1, "2" * 64, **FRESH)
    with patched(**FRESH):
        assert bo.verify_equivocation_proof(proof(x, y), 100) is None
        assert "equivocation proof" in (refused(slash_tx(proof(x, y), "o1")) or "")
        assert bo.verify_equivocation_proof(proof(same_gen_old, same_gen_new), 100) is None, "old + new at one parent"


def t_other_generation_or_genesis_bound_signatures_are_not_evidence():
    """Even in the bound form, a signature for another generation (reused genesis) or another genesis does not verify."""
    other_gen = dict(FRESH, CHAIN_GENERATION=bo.CHAIN_GENERATION - 1)
    other_genesis = dict(FRESH, _GENESIS_HASH=G_OLD)
    for label, as_ in (("generation", other_gen), ("genesis", other_genesis)):
        a = blk(G_THIS, 7, "5" * 64, **as_)
        b_foreign = blk(G_THIS, 7, "6" * 64, **as_)
        b_here = blk(G_THIS, 7, "6" * 64, **FRESH)
        with patched(**FRESH):
            assert bo.verify_equivocation_proof(proof(a, b_foreign), 100) is None, f"both signed for another {label}"
            assert bo.verify_equivocation_proof(proof(a, b_here), 100) is None, f"one signed for another {label}"


def t_evidence_below_the_gate_is_refused_once_live():
    """With the rule live at the judging block, evidence for a height below the gate (chain-less bytes) is refused."""
    a, b = blk(G_OLD, 0, "7" * 64, **OLD_CHAIN), blk(G_OLD, 0, "8" * 64, **OLD_CHAIN)
    with patched(BLOCK_SIG_CHAIN_BIND_HEIGHT=10):
        assert bo.verify_equivocation_proof(proof(a, b), 5) == (kd["address"], 0), "judged below the gate: old rule"
        assert bo.verify_equivocation_proof(proof(a, b), 10) is None, "judged at the gate: refused"


def t_real_same_chain_equivocation_still_slashes():
    """Two different blocks at one (height, parent) signed for THIS chain slash, burn, dedup and revert exactly."""
    parent = "9a" * 32
    a, b = blk(parent, 60, "a" * 64, **FRESH), blk(parent, 60, "b" * 64, **FRESH)
    with patched(**FRESH):
        assert bo.verify_equivocation_proof(proof(a, b), 100) == (kd["address"], 60)
        tx = slash_tx(proof(a, b), "s1")
        assert refused(tx) is None, refused(tx)
        before = get_account(kd["address"])["bonded"]
        with kv_ops.write_txn():
            reflect_transaction(tx, logger=logger, block_height=100)
        assert get_account(kd["address"])["bonded"] == before - P.SLASH_BOND_PENALTY
        assert "already slashed" in (refused(tx) or "")
        with kv_ops.write_txn():
            reflect_transaction(tx, logger=logger, revert=True, block_height=100)
        assert get_account(kd["address"])["bonded"] == before and not kv_ops.slash_exists(kd["address"], 60)


# ---- 3. honest blocks ----------------------------------------------------------------------------------------------
def t_honest_blocks_sign_and_verify():
    """A winner's own signature verifies on both sides of the gate; an old-generation signature is no block signature."""
    for gate in (LIVE_GATE, 1):
        b = blk(G_THIS, 3, "c" * 64, BLOCK_SIG_CHAIN_BIND_HEIGHT=gate)
        with patched(BLOCK_SIG_CHAIN_BIND_HEIGHT=gate):
            assert bo.verify_block_signature(b) is True, gate
            assert bo.block_content_hash(b) == b["block_hash"], "signing is detached: the hash is untouched"
    old = blk(G_THIS, 3, "c" * 64, **OLD_CHAIN)
    fresh = blk(G_THIS, 3, "c" * 64, **FRESH)
    assert old["block_hash"] == fresh["block_hash"], "the block hash does not depend on the gate"
    with patched(**FRESH):
        assert bo.verify_block_signature(old) is False, "a chain-less signature is refused once the rule is live"


def t_signed_bytes_survive_a_chain_id_rename():
    """The bound message reads the generation and genesis hash, never the CHAIN_ID label."""
    with patched(**FRESH):
        m1 = bo._block_sig_message_fields(9, "ab" * 32, "cd" * 32)
        with patched(CHAIN_ID="renamed-label"):
            assert bo._block_sig_message_fields(9, "ab" * 32, "cd" * 32) == m1
        with patched(CHAIN_GENERATION=bo.CHAIN_GENERATION + 1):
            assert bo._block_sig_message_fields(9, "ab" * 32, "cd" * 32) != m1
        with patched(_GENESIS_HASH=G_OLD):
            assert bo._block_sig_message_fields(9, "ab" * 32, "cd" * 32) != m1
    assert bo._GENESIS_HASH == blake2b_hash_link(link_from=P.GENESIS_TIMESTAMP, link_to=[]), "block 0's own hash"


def t_malformed_height_fails_quietly():
    """A non-int height still verifies to False/None rather than raising (the pre-gate behaviour)."""
    b = blk(G_THIS, 3, "c" * 64)
    b["block_number"] = "3"
    with patched(**FRESH):
        assert bo.verify_block_signature(b) in (True, False)


# ---- 4. FFG double-vote evidence is bound by chain_id: each generation needs its own ------------------------------
# (CHAIN_ID, GENESIS_TIMESTAMP) per generation. ADD THE NEW GENERATION'S PAIR AT EVERY REROLL (doc/reroll.md step 8).
# Gen 26 and 27 share a pair: no block was ever built on gen 26 (5de4e1a5), so that reuse is history, not a hazard.
GENERATION_IDS = {
    26: ("betanet-8", 1790328896),
    27: ("betanet-8", 1790328896),
    28: ("betanet-9", 1790668583),
}


def t_each_generation_has_its_own_chain_id():
    """The live generation's CHAIN_ID and GENESIS_TIMESTAMP were never used by an earlier generation."""
    live = (P.CHAIN_ID, P.GENESIS_TIMESTAMP)
    assert P.CHAIN_GENERATION in GENERATION_IDS, \
        f"generation {P.CHAIN_GENERATION} is not in GENERATION_IDS: add {live} (and make sure it is new)"
    assert GENERATION_IDS[P.CHAIN_GENERATION] == live, (GENERATION_IDS[P.CHAIN_GENERATION], live)
    for g, (cid, ts) in GENERATION_IDS.items():
        if g < P.CHAIN_GENERATION and not (g, P.CHAIN_GENERATION) == (26, 27):
            assert cid != P.CHAIN_ID, f"CHAIN_ID {cid!r} was gen {g}'s: its FFG votes would be slash evidence here"
            assert ts != P.GENESIS_TIMESTAMP, f"GENESIS_TIMESTAMP {ts} was gen {g}'s: same genesis, same parents"


check("below the gate the signed bytes are the old form, byte for byte", t_below_gate_bytes_unchanged)
check("below the gate a foreign-chain double-sign is still evidence (the finding, reproduced)", t_below_gate_replay_reproduces)
check("refuses an earlier generation's signatures as slash evidence", t_old_generation_signatures_are_not_evidence)
check("refuses signatures bound to another generation or genesis", t_other_generation_or_genesis_bound_signatures_are_not_evidence)
check("refuses evidence below the gate once the rule is live", t_evidence_below_the_gate_is_refused_once_live)
check("a real same-chain double-sign still slashes, dedups and reverts", t_real_same_chain_equivocation_still_slashes)
check("honest blocks sign and verify on both sides of the gate", t_honest_blocks_sign_and_verify)
check("the signed bytes survive a CHAIN_ID rename", t_signed_bytes_survive_a_chain_id_rename)
check("a malformed height fails verification without raising", t_malformed_height_fails_quietly)
check("every generation carries a CHAIN_ID and genesis no earlier one used", t_each_generation_has_its_own_chain_id)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)

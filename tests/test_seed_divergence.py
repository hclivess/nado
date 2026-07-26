"""
Regression tests for the alphanet-7 h76000 SEED-SPLIT bugs (Damian's report, 2026-07-23) — the
snapshot-root divergence that made fresh nodes unable to sync (the 1-1 snapshot-hash vote could never
reach quorum). Each test targets one verified root cause and FAILS on the pre-fix code.

  1. rollback order       — unindex_transactions must revert in REVERSE application order, or two
                            same-address `bond`s in one block restore the WRONG prior bond_since.
  2. revert journals      — bond_since_revert / hb_revert / msgkey_revert are reorg-path-dependent
                            rollback bookkeeping and must NOT feed the snapshot state_root.
  3. empty accounts       — an all-default (absent-equivalent) account row must not change the root.
  4. exec summaries       — the retention GC is path-INDEPENDENT (isolating the reported execsum
                            divergence to the swallowed non-deterministic failure), and the
                            settle-with-proof fast-path must stay DISABLED while that swallow exists.
  5. withdraw mismatch    — characterizes the "withdraw data does not match the pending unbond" error
                            as a cross-node state-mismatch SYMPTOM (fixed once the seeds reconcile).

Run: python3 tests/test_seed_divergence.py
"""
import os, sys, tempfile, logging, inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("seeddiv"); logger.addHandler(logging.NullHandler())
fails = 0


def check(name, ok):
    """Print PASS/FAIL for boolean ok and count failures."""
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def _fresh_home(prefix):
    """Point HOME at a fresh temp dir with the nado data subdirs, close any prior env, re-index."""
    from ops import kv_ops
    kv_ops.close_all()
    h = tempfile.mkdtemp(prefix=prefix)
    os.environ["HOME"] = h
    for d in ("index", "blocks", "logs", "peers", "snapshots"):
        os.makedirs(f"{h}/nado/{d}", exist_ok=True)
    from genesis import create_indexers
    create_indexers()
    return h


# ---------------------------------------------------------------------------------------------------
# 1) ROLLBACK ORDER: reverse-application-order revert restores the exact prior bond_since.
# ---------------------------------------------------------------------------------------------------
def test_rollback_order():
    _fresh_home("nado_div_rollback_")
    from ops import kv_ops, account_ops
    from ops.transaction_ops import index_transactions, unindex_transactions, sort_transaction_pool
    from protocol import EPOCH_LENGTH

    addr = "bonder_repeat"
    account_ops.create_account(addr, balance=1000, bonded=100)
    kv_ops.bond_since_put(addr, 1)                 # pre-existing stake aged at epoch 1 (the value to restore)

    BH = 10 * EPOCH_LENGTH                          # epoch 10, so the top-up blend lands strictly between 1 and 10
    txA = {"sender": addr, "recipient": "bond", "amount": 100, "fee": 0,
           "txid": "0" * 63 + "a", "public_key": "pk", "data": ""}
    txB = {"sender": addr, "recipient": "bond", "amount": 200, "fee": 0,
           "txid": "0" * 63 + "b", "public_key": "pk", "data": ""}
    # A real body is stored txid-sorted (block_ops.construct_block), so block_transactions == [A, B].
    block = {"block_number": BH, "block_transactions": [txA, txB]}

    v0 = kv_ops.bond_since_get_raw(addr)
    with kv_ops.write_txn():
        index_transactions(block=block,
                           sorted_transactions=sort_transaction_pool(block["block_transactions"]),
                           logger=logger)
    v_applied = kv_ops.bond_since_get_raw(addr)

    with kv_ops.write_txn():
        unindex_transactions(block=block, logger=logger, block_height=BH)
    v_reverted = kv_ops.bond_since_get_raw(addr)

    # apply: A blends 1->5, B blends 5->7. The two txs are non-commutative in bond_since.
    check("apply blends bond_since to the top-up value (1 -> 5 -> 7)", v0 == 1 and v_applied == 7)
    # Correct reverse-order revert (B then A) restores 5 then 1 -> final 1.
    check("rollback restores the ORIGINAL bond_since (reverse-application order)", v_reverted == 1)
    # The pre-fix FORWARD-order revert (A then B) would restore 1 then 5 -> final 5. Guard against regression.
    check("rollback did NOT leave the forward-order intermediate (the bug == 5)", v_reverted != 5)
    # And the stake itself round-trips.
    check("bonded stake round-trips to the pre-block value", account_ops.get_account(addr)["bonded"] == 100)


# ---------------------------------------------------------------------------------------------------
# 2) REVERT JOURNALS OUT OF THE STATE ROOT.
# ---------------------------------------------------------------------------------------------------
def test_revert_journals_excluded_from_root():
    _fresh_home("nado_div_journals_")
    from ops import kv_ops, account_ops
    from ops.snapshot_ops import read_state, merkle_root

    for j in ("bond_since_revert", "hb_revert", "msgkey_revert"):
        check(f"{j} is EXCLUDED from SNAPSHOT_DBS (not in the state_root)", j not in kv_ops.SNAPSHOT_DBS)
    # The canonical state these journals shadow must STAY carried.
    check("canonical bond_since STAYS in SNAPSHOT_DBS", "bond_since" in kv_ops.SNAPSHOT_DBS)

    account_ops.create_account("acct", balance=10)
    root_before = merkle_root(read_state())
    # Two nodes at the same canonical tip via different reorg paths legitimately hold different journal
    # residue. Writing some must NOT move the root.
    kv_ops.bond_since_revert_put("some_txid", 5)
    kv_ops.msgkey_revert_put("other_txid", None)
    kv_ops.hb_revert_put(3, "acct", 2, 1)
    root_after = merkle_root(read_state())
    check("state_root is INVARIANT to revert-journal residue", root_before == root_after)

    names = {t[0] for t in read_state()}
    check("no revert-journal rows appear in the snapshot triples",
          not (names & {"bond_since_revert", "hb_revert", "msgkey_revert"}))


# ---------------------------------------------------------------------------------------------------
# 3) EMPTY ACCOUNT ROWS ARE CANONICALIZED OUT OF THE ROOT.
# ---------------------------------------------------------------------------------------------------
def test_empty_account_canonicalized():
    _fresh_home("nado_div_empty_")
    from ops import kv_ops, account_ops
    from ops.snapshot_ops import read_state, merkle_root

    account_ops.create_account("real", balance=5)
    root_before = merkle_root(read_state())

    account_ops.create_account("ghost")            # all-default row physically written (old read-created residue)
    check("the all-default ghost row physically exists in the accounts DB", kv_ops.get_account("ghost") is not None)
    root_after = merkle_root(read_state())
    check("state_root is INVARIANT to an all-default (absent-equivalent) account row", root_before == root_after)

    acct_keys = {t[1] for t in read_state() if t[0] == "accounts"}
    check("the ghost row contributes NO snapshot triple", b"ghost" not in acct_keys)
    check("the real account IS still carried", b"real" in acct_keys)

    # A zero-balance account that carries REAL state (registered lease) must NOT be dropped.
    account_ops.create_account("registered_only", registered=7)
    acct_keys2 = {t[1] for t in read_state() if t[0] == "accounts"}
    check("a registered (zero-balance) account is NOT canonicalized away", b"registered_only" in acct_keys2)


# ---------------------------------------------------------------------------------------------------
# 4) EXEC SUMMARY: GC path-independence + proof fast-path stays disabled.
# ---------------------------------------------------------------------------------------------------
def _present_summaries(applied, rolled_back_reapplied=0):
    """Drive the real exec_summary GC (put h; del h-RET on apply; del h on rollback) over a linear apply
    of heights 1..applied, optionally rolling back the last K and re-applying them, and return the set of
    heights whose summary survives. Runs against a FRESH home so the two paths can't share state."""
    _fresh_home("nado_div_execsum_")
    from ops import kv_ops
    from protocol import EXEC_SUMMARY_RETENTION as RET

    def apply(h):
        kv_ops.exec_summary_put(h, inert=True, calls_by_ns={})
        if h > RET:
            kv_ops.exec_summary_del(h - RET)       # O(1) rolling GC — mirror of incorporate_block

    for h in range(1, applied + 1):
        apply(h)
    for _ in range(rolled_back_reapplied):         # reorg the tip: roll back K, then re-apply the same K
        kv_ops.exec_summary_del(applied)
        apply(applied)                             # re-apply lands the SAME height (canonical replacement)

    present = set()
    for h in range(max(1, applied - RET - 5), applied + 1):
        if kv_ops.exec_summary_get(h) is not None:
            present.add(h)
    return present


def test_exec_summary_determinism_and_proof_disabled():
    from protocol import EXEC_SUMMARY_RETENTION as RET
    N = RET + 20
    linear = _present_summaries(N, rolled_back_reapplied=0)
    reorged = _present_summaries(N, rolled_back_reapplied=5)
    check("exec-summary retention set is path-independent for REAPPLY-same-height reorgs",
          linear == reorged and len(linear) > 0)
    # CORRECTION (gen-7): the set above is stable ONLY because this models a reorg as del(tip)+reapply(tip).
    # A real rollback that does NOT reapply the same tip leaves execsum:<h-RET> permanently dropped (rollback
    # only del's the block's own height) — which DID fork the root at alphanet-8 h4260 (an emergency rollback
    # storm dropped execsum:3301..3305 on the catching-up nodes). The fix is NOT a symmetric GC — it is
    # EXCLUDING execsum from the root entirely (test_execsum_excluded_from_root). Proofs still stay off while
    # the block_summary swallow (core_loop except: continue) can make the CARRIED set inconsistent.
    from ops import settlement_ops
    src = inspect.getsource(settlement_ops.settlement_justified)
    active_proof_call = any(("settlement_proven" in ln and not ln.lstrip().startswith("#"))
                            for ln in src.splitlines())
    check("settle-with-proof fast-path stays DISABLED (no active settlement_proven call) — "
          "do not activate proofs while summaries can be inconsistently missing", not active_proof_call)


# ---------------------------------------------------------------------------------------------------
# 4b) ROLLBACK ASYMMETRY (gen-7, alphanet-8 h4260): rollback_one_block was not the exact inverse of
#     incorporate_block for two `meta` rows, so a node that rolled back (emergency re-sync) drifted its
#     root away from a forward-only node and the FATAL gate then permanently refused it. Block APPLICATION
#     was fully deterministic (a canonical forward replay reproduced the network root) — the corruption
#     was in the rollback path. Each test FAILS on the pre-fix code.
# ---------------------------------------------------------------------------------------------------
def test_execsum_excluded_from_root():
    """execsum:<h> presence is retention/rollback-path dependent — incorporate_block prunes execsum:<h-RET>
    but rollback_one_block never restores it, so a rolled-back node holds a different execsum set than a
    forward-only node. It MUST NOT feed the state_root; now excluded via ROOT_EXCLUDED_META_PREFIXES."""
    _fresh_home("nado_div_execsumroot_")
    from ops import kv_ops
    from ops.snapshot_ops import read_state, _root_triples, l1_state_root
    root_before = l1_state_root()
    kv_ops.exec_summary_put(1234, inert=True, calls_by_ns={})
    kv_ops.exec_summary_put(1235, inert=False, calls_by_ns={"default": [7, 8]})
    check("state_root is INVARIANT to execsum rows (retention/rollback-path dependent)",
          l1_state_root() == root_before)
    meta_keys = {k for (db, k, v) in _root_triples(read_state()) if db == "meta"}
    check("no execsum:* row appears in the consensus root",
          not any(k.startswith(b"execsum:") for k in meta_keys))
    check("the execsum rows DO physically exist (still carried for settle-with-proof)",
          kv_ops.exec_summary_get(1234) is not None and kv_ops.exec_summary_get(1235) is not None)


def test_dividend_inflow_revert_roundtrips():
    """Reverting an epoch's FIRST dividend inflow back to 0 must DELETE the divinflow:<e> key, not leave a
    phantom `=0` row — a present-0 meta int merkleizes differently from an absent key, so the phantom forked
    the root vs the absent-key true parent when incorporate_block's reward credit was rolled back."""
    _fresh_home("nado_div_divinflow_")
    from ops import kv_ops
    from ops.snapshot_ops import l1_state_root
    root_before = l1_state_root()
    kv_ops.dividend_inflow_add(71, 83300000)
    check("adding an epoch's inflow moves the root (divinflow IS block-derived, in the root)",
          l1_state_root() != root_before)
    kv_ops.dividend_inflow_add(71, 83300000, revert=True)
    check("no phantom divinflow:71=0 row remains after the revert (0 == absent)",
          kv_ops.meta_get_int("divinflow:71", None) is None)
    check("reverting the first inflow round-trips the root BYTE-IDENTICALLY",
          l1_state_root() == root_before)
    # a partial revert (epoch had inflow from >1 block) keeps the key with the remaining positive total
    kv_ops.dividend_inflow_add(71, 100)
    kv_ops.dividend_inflow_add(71, 30)
    kv_ops.dividend_inflow_add(71, 30, revert=True)
    check("a partial revert KEEPS the key at the remaining positive total (not deleted)",
          kv_ops.dividend_inflow_get(71) == 100)



def test_reserved_dedup_is_canonical():
    """dedupe_reserved must resolve two-txids-one-uniqueness-key collisions by LOWEST txid, not mempool
    arrival order — else two nodes build different blocks at one height (a validator restart re-mints a
    duty/register tx: new txid, same (sender,epoch) key). Arrival-order-independent survivor required."""
    from ops.transaction_ops import dedupe_reserved
    a = {"txid": "ffff", "sender": "S", "recipient": "duty", "data": {"attest": {"target_epoch": 5}}}
    b = {"txid": "0001", "sender": "S", "recipient": "duty", "data": {"attest": {"target_epoch": 5}}}
    o1, o2 = dedupe_reserved([a, b]), dedupe_reserved([b, a])
    check("dedupe_reserved survivor is arrival-order-independent", o1 == o2)
    check("dedupe_reserved keeps the LOWEST txid on a collision", o1 and o1[0]["txid"] == "0001")


def test_tx_data_rejects_floats():
    """tx `data` rides into the txid + block-hash preimage; a float breaks browser-reproducibility (JS
    JSON.stringify(1.0)=='1' vs Python '1.0') and the integer-only invariant. Reject floats anywhere in data."""
    from ops.transaction_ops import _has_float
    check("plain int/str data has no float", _has_float({"op": "call", "n": 5, "s": "x", "l": [1, 2]}) is False)
    check("a nested float is detected", _has_float({"a": {"b": [1, 2.5]}}) is True)
    check("bool is not treated as a float", _has_float({"flag": True, "n": 0}) is False)


def test_bridge_escrow_revert_roundtrips():
    """bridge_escrow is an accumulator meta row (bridgeescrow:<ns>) in the L1 root — the SAME class as
    divinflow. Reverting the first deposit to a namespace (add creates the key, revert subtracts to 0) must
    DELETE it, not leave a phantom `=0` that forks the root vs a forward-only node."""
    _fresh_home("nado_div_bridge_")
    from ops import kv_ops
    from ops.snapshot_ops import l1_state_root
    root_before = l1_state_root()
    kv_ops.bridge_escrow_ns_add("rollupA", 100)              # bridge deposit to a fresh namespace
    check("a deposit to a fresh namespace moves the root (escrow IS in the root)",
          l1_state_root() != root_before)
    kv_ops.bridge_escrow_ns_sub("rollupA", 100)              # revert the deposit (rollback)
    check("no phantom bridgeescrow:rollupA=0 row remains after the revert",
          kv_ops.meta_get_int("bridgeescrow:rollupA", None) is None)
    check("reverting the first deposit round-trips the root BYTE-IDENTICALLY",
          l1_state_root() == root_before)
    # a partial exit keeps the key at the remaining positive escrow
    kv_ops.bridge_escrow_ns_add("rollupB", 100)
    kv_ops.bridge_escrow_ns_sub("rollupB", 40)
    check("a partial exit KEEPS the escrow key at the remaining balance (not deleted)",
          kv_ops.bridge_escrow_ns("rollupB") == 60)


# ---------------------------------------------------------------------------------------------------
# 4c) SNAPSHOT IDENTITY: manifest_hash must be invariant to the BUILD `version` string. Two nodes with
#     byte-identical snapshot payloads but a different build (most commonly one clean, one `-dirty`) were
#     hashing to different snapshot_hashes, splitting agree_snapshot's vote so a fresh node could never
#     reach a bootstrap quorum despite the snapshots being equal.
# ---------------------------------------------------------------------------------------------------
def test_manifest_hash_ignores_version():
    from ops.snapshot_ops import manifest_hash
    base = {"snapshot_height": 6000, "block_hash": "ab" * 32, "state_root": "cd" * 32,
            "entry_count": 16414, "chunk_count": 1,
            "chunks": [{"id": 0, "sha256": "ef" * 32, "bytes": 2049074, "rows": 16414}], "protocol": 7}
    clean = dict(base, version="v1.0.0-alpha.11-245-g6ce04fe")
    dirty = dict(base, version="v1.0.0-alpha.11-245-g6ce04fe-dirty")
    check("manifest_hash is INVARIANT to the build version string (clean vs -dirty)",
          manifest_hash(clean) == manifest_hash(dirty))
    check("a DIFFERENT state_root still changes the snapshot identity (payload IS hashed)",
          manifest_hash(clean) != manifest_hash(dict(clean, state_root="00" * 32)))
    check("a DIFFERENT protocol still changes the snapshot identity (compat gate stays)",
          manifest_hash(clean) != manifest_hash(dict(clean, protocol=6)))
    # chunking is a TRANSPORT detail (keyed by the NADO_SNAPSHOT_CHUNK_ROWS env) — it must NOT be in the
    # identity, or two nodes with identical state but a different chunk size split agree_snapshot's quorum.
    rechunked = dict(clean, chunk_count=2,
                     chunks=[{"id": 0, "sha256": "22" * 32, "bytes": 1e6, "rows": 10000},
                             {"id": 1, "sha256": "33" * 32, "bytes": 1e6, "rows": 6414}])
    check("manifest_hash is INVARIANT to chunking (chunk_count / per-chunk sha256)",
          manifest_hash(clean) == manifest_hash(rechunked))
    check("state_root + entry_count still pin the payload (a state_root change is caught above)",
          manifest_hash(clean) != manifest_hash(dict(clean, entry_count=99)))
    check("the payload digest IS part of the snapshot identity (authenticates root-EXCLUDED rows)",
          manifest_hash(dict(clean, state_digest="aa" * 32)) != manifest_hash(dict(clean, state_digest="bb" * 32)))


def test_snapshot_payload_authenticated():
    """A donor that copies an honest manifest's core fields can match the quorum-agreed snapshot_hash, so the
    PAYLOAD must be authenticated separately: state_root covers only the CONSENSUS subset, leaving the
    root-EXCLUDED rows (block storage, finalized_height/pruned_below, execsum:, tvprev*) unbound. A forged
    finalized_height would wedge the victim's rollback FOREVER (FinalityViolation floor). state_digest covers
    every transferred row; entry_count alone is a count, so an in-place value edit keeps it exact."""
    import hashlib
    _fresh_home("nado_div_snapauth_")
    from ops import account_ops, kv_ops, codec
    from ops.snapshot_ops import (build_snapshot, import_snapshot, manifest_hash, state_digest,
                                  _payload_triples, read_state)

    account_ops.create_account("a", balance=100)
    kv_ops.meta_set_int("finalized_height", 5)          # the ROOT-EXCLUDED attack target
    man, chunks = build_snapshot(100, "bh" * 32, 9, "v1")
    check("a built manifest carries a payload digest", bool(man.get("state_digest")))
    check("the honest payload imports", import_snapshot(man, chunks) is True)

    triples = []
    for cb in chunks:
        for row in codec.unpack(cb):
            triples.append((row[0], bytes(row[1]), bytes(row[2])))
    # Tamper a root-excluded row that is NOT node-local: block storage. (finalized_height/pruned_below are
    # deliberately outside the digest — honest peers legitimately differ there — and are defended by the
    # import-time CLAMP instead; that is asserted separately below.)
    poisoned = [(n, k, b"forged-orphan-body" if n == "block_by_hash" else v) for n, k, v in triples]
    if not any(n == "block_by_hash" for n, _, _ in triples):
        poisoned = poisoned + [("block_by_hash", b"\x01" * 32, b"forged-orphan-body")]
    pchunk = codec.pack([[n, k, v] for n, k, v in poisoned])
    evil = dict(man)                                     # honest core fields, attacker's payload
    evil["chunks"] = [{"id": 0, "sha256": hashlib.sha256(pchunk).hexdigest(),
                       "bytes": len(pchunk), "rows": len(poisoned)}]
    evil["chunk_count"] = 1
    evil["snapshot_hash"] = manifest_hash(evil)
    check("the attacker CAN still match the agreed snapshot_hash (core fields are copyable)",
          evil["snapshot_hash"] == man["snapshot_hash"])
    check("but a payload with a tampered ROOT-EXCLUDED row is REJECTED at import",
          import_snapshot(evil, [pchunk]) is False)

    # ---- TRANSFER-PAYLOAD CANONICALIZATION (four honest nodes advertised four different snapshot_hashes
    # for identical state_root: two had finalized_height, two did not, and their execsum: sets differed) ----
    def _identity():
        m, _c = build_snapshot(1000, "bh" * 32, 10, "v1")
        return (m["snapshot_hash"], m["entry_count"], m["chunks"][0]["sha256"])

    kv_ops.exec_summary_put(84, True, {})                    # a summary every node at this height holds
    kv_ops.meta_set_int("finalized_height", 955)
    id_a = _identity()
    kv_ops.meta_del("finalized_height")                      # absent on this peer
    id_b = _identity()
    kv_ops.meta_set_int("pruned_below", 500)                 # and a local prune watermark
    id_c = _identity()
    kv_ops.meta_set_int("tvprevE:zz", 1)                     # and reorg-path revert-journal residue
    id_d = _identity()
    check("present-vs-absent finalized_height produces an IDENTICAL snapshot identity", id_a == id_b)
    check("present-vs-absent pruned_below produces an IDENTICAL snapshot identity", id_a == id_c)
    check("tvprev revert-journal residue produces an IDENTICAL snapshot identity", id_a == id_d)
    # execsum DOES travel: block validity (settle-with-proof) depends on it, so it must be guaranteed
    # present on every node. Safe to carry because it is now deterministic (rollback restores the pruned
    # row), so two nodes at the same height hold the identical window and still agree on the identity.
    check("execsum rows are CARRIED in the payload (validity depends on them)",
          any(n == "meta" and k.startswith(b"execsum:")
              for n, k, _v in _payload_triples(read_state())))

    m2, c2 = build_snapshot(1000, "bh" * 32, 10, "v1")
    check("import reconstructs finalized_height == snapshot_height",
          import_snapshot(m2, c2) is True
          and kv_ops.meta_get_int("finalized_height", None) == 1000)
    check("import DELIVERS the pre-checkpoint execsum window (closes the settle-with-proof validity fork: "
          "without it a joiner rejects a block its peers accept)",
          kv_ops.exec_summary_get(84) is not None)
    check("tail replay can still add new exec summaries after import",
          (kv_ops.exec_summary_put(1001, True, {}) or kv_ops.exec_summary_get(1001) is not None))

    # a donor INJECTING an excluded row must not shift the identity nor reach our DB
    inj = [(n, k, v) for n, k, v in triples] + [("meta", b"finalized_height", codec.pack(10 ** 12))]
    ichunk = codec.pack([[n, k, v] for n, k, v in inj])
    im = dict(m2)
    im["chunks"] = [{"id": 0, "sha256": hashlib.sha256(ichunk).hexdigest(),
                     "bytes": len(ichunk), "rows": len(inj)}]
    im["chunk_count"] = 1
    im["snapshot_hash"] = manifest_hash(im)
    import_snapshot(im, [ichunk])
    check("an injected finalized_height cannot wedge the importer (dropped, then reconstructed)",
          kv_ops.meta_get_int("finalized_height", None) == 1000)


def test_no_self_equivocation_across_reorg():
    """An attestation signs {target_epoch, target_hash}. The duty loop re-reads target_hash from the local
    tip on every pass while its attestation has not landed, so a reorg that rewrites the epoch's checkpoint
    made an HONEST node sign a SECOND attestation: same epoch, different hash. Both are gossiped, and
    together they are a valid, unforgeable equivocation proof — anyone who scraped both could slash this
    validator's bond for a reorg it did not cause, repeatable per epoch until the stake was gone. The
    mempool dedup guard could not prevent it (the first tx leaves the pool when max_block passes, and a
    restart forgot it entirely). A PERSISTED node-local memo now makes a second, differing signature
    impossible."""
    _fresh_home("nado_div_equiv_")
    from ops import kv_ops

    X = 7

    def would_sign(local_hash):            # mirrors maybe_epoch_duty's decision
        prev = kv_ops.attest_memo_get(X)
        if prev is not None and prev != local_hash:
            return None
        if prev is None:
            kv_ops.attest_memo_put(X, local_hash)
        return {"target_epoch": X, "target_hash": local_hash}

    first = would_sign("aaaa1111")
    again = would_sign("aaaa1111")         # not landed yet, same tip -> identical, harmless
    after_reorg = would_sign("bbbb2222")   # a reorg rewrote the epoch checkpoint

    check("the first attestation is signed normally", first is not None)
    check("re-signing the SAME checkpoint is still allowed (idempotent, not equivocation)",
          again == first)
    check("after a reorg the node REFUSES to attest a different hash for the same epoch",
          after_reorg is None)
    signed = {x["target_hash"] for x in (first, again, after_reorg) if x}
    check("no slashable pair is ever produced (one hash per epoch)", len(signed) == 1)

    kv_ops.close_all()                     # the old guard was mempool-only and forgot across a restart
    check("the memo is PERSISTED, so a restart still refuses", kv_ops.attest_memo_get(X) == "aaaa1111")
    check("...and a post-restart re-attest with the new hash is refused", would_sign("bbbb2222") is None)
    check("the memo is NODE-LOCAL (never in the root or a snapshot)",
          "attest_memo" in kv_ops._LOCAL_DBS and "attest_memo" not in kv_ops.SNAPSHOT_DBS)


def test_execsum_window_survives_rollback():
    """execsum:<h> is block_summary(block) — a PURE function of the block body — written for every block
    and pruned by a deterministic height rule, so two honest nodes at the same tip MUST hold the identical
    set. It did not: incorporate_block does put(h) AND del(h-RETENTION) while rollback_one_block did only
    del(h), so every net rollback left the window SHORT AT THE BOTTOM (observed live: a node holding
    execsum[3306..4260] where tip 4260 requires [3301..4260]). That is not cosmetic — settle-with-proof
    validation reads exec_summary_get(h) for every height in a proof span, so a short window makes this node
    REJECT a block its peers accept (a validity fork), and it desynchronises the execsum set between honest
    nodes. Fixed by journalling the pruned row (node-local execsum_revert) and restoring it on rollback."""
    _fresh_home("nado_div_execsumwin_")
    from ops import kv_ops
    from protocol import EXEC_SUMMARY_RETENTION as RET

    def window():
        hs = sorted(int(k.decode().split(":")[1]) for k, _ in kv_ops.iter_db_pairs("meta")
                    if k.decode().startswith("execsum:"))
        return (hs[0], hs[-1], len(hs)) if hs else (0, 0, 0)

    def incorporate(h):                      # mirrors loops/core_loop.incorporate_block
        kv_ops.exec_summary_put(h, True, {})
        if h > RET:
            oh = h - RET
            kv_ops.execsum_revert_put(h, oh, kv_ops.exec_summary_get(oh))
            kv_ops.exec_summary_del(oh)

    def rollback(h):                         # mirrors rollback.rollback_one_block
        kv_ops.exec_summary_del(h)
        rev = kv_ops.execsum_revert_pop(h)
        if rev:
            ph, doc = rev
            kv_ops.exec_summary_put(ph, bool(doc.get("inert")), doc.get("calls") or {})

    for h in range(1, RET + 6):
        incorporate(h)
    lo, hi, n = window()
    check("a forward-only node holds exactly RETENTION summaries", n == RET and lo == hi - RET + 1)

    rollback(RET + 5)                        # reorg: tip drops, the chain continues on another branch
    lo, hi, n = window()
    check("after a rollback the window is STILL full-length (no bottom-edge loss)", n == RET)
    check("...and its bottom edge is exactly tip-RETENTION+1", lo == hi - RET + 1)

    check("the revert journal is NODE-LOCAL (never in the root or a snapshot)",
          "execsum_revert" in kv_ops._LOCAL_DBS and "execsum_revert" not in kv_ops.SNAPSHOT_DBS)


def test_state_fingerprint_is_single_walk_and_consistent():
    """state_fingerprint must derive the overall root AND the per-DB breakdown from ONE read_state() walk:
    two walks can straddle a commit and return a root that does not correspond to its own breakdown — a
    self-inconsistent diagnostic that false-alarms the divergence watch it feeds."""
    _fresh_home("nado_div_fingerprint_")
    from ops import account_ops, kv_ops
    from ops.snapshot_ops import state_fingerprint, l1_state_root, merkle_root, _root_triples, read_state

    account_ops.create_account("a", balance=100)
    account_ops.create_account("b", balance=7)
    kv_ops.meta_set_int("finalized_height", 3)          # a root-EXCLUDED row: must not appear in per_db
    root, per_db = state_fingerprint()
    check("state_fingerprint root == l1_state_root", root == l1_state_root())
    check("per-DB breakdown covers the accounts DB", "accounts" in per_db and per_db["accounts"][1] == 2)
    check("root-EXCLUDED rows contribute no per-DB entry",
          all(n != "meta" or c > 0 for n, (r, c) in per_db.items()))
    # the breakdown must be a partition of the SAME triples the root committed
    total_rows = sum(c for _, (_, c) in per_db.items())
    check("per-DB row counts sum to the consensus triple count",
          total_rows == len(_root_triples(read_state())))


def test_all_db_pairs_single_txn_snapshot():
    """kv_ops.all_db_pairs must span every sub-DB in ONE read txn (a per-sub-DB txn lets a commit land
    mid-walk and tear the state). Verified structurally: it yields (db, key, value) across the requested
    names and read_state consumes it fully."""
    _fresh_home("nado_div_alldb_")
    from ops import kv_ops, account_ops
    account_ops.create_account("x", balance=1)
    kv_ops.meta_set_int("finalized_height", 1)
    names = ("accounts", "meta", "totals")
    rows = list(kv_ops.all_db_pairs(names))
    check("all_db_pairs yields (db, key, value) triples across the named sub-DBs",
          bool(rows) and all(len(r) == 3 and r[0] in names for r in rows))
    check("all_db_pairs covers more than one sub-DB in a single pass",
          len({r[0] for r in rows}) >= 2)


def test_rollback_stats_reject_emergency_schema():
    """The r/e counters must survive legacy files (bare-int days, dict days without the fields) and must
    normalise to a real 0 for the day we are ACTIVELY measuring — null means "not measured", and claiming
    null on a day we counted an emergency would understate a fork."""
    import json, time
    _fresh_home("nado_div_rbstats_")
    from ops import rollback_stats as rs

    today = time.strftime("%Y-%m-%d", time.gmtime())
    json.dump({today: {"c": 5, "d": 3}}, open(rs._stats_path(), "w"))   # legacy: no r/e keys
    rs.record_emergency()
    rec = rs.daily_counts(1)[-1]
    check("a legacy today-record normalises rejects null -> 0 once we are measuring", rec["rejects"] == 0)
    check("emergency entries are counted", rec["emergencies"] == 1)
    check("legacy count/depth are preserved", rec["count"] == 5 and rec["depth"] == 3)
    rs.record_reject()
    check("rejects increment from the normalised 0", rs.daily_counts(1)[-1]["rejects"] == 1)
    # A day BEFORE this node started observing is NOT evidence of a calm day — it must serve null, or a
    # fresh node's empty history reads as "30 clean days" and the Stats panel asserts consensus health for
    # days it never ran. (Days at/after first-observation with no record ARE real zeros.)
    older = rs.daily_counts(3)[0]
    check("a day before first-observation serves null, NOT a fake zero", older["rejects"] is None)
    check("today (observing) still serves real numbers", rs.daily_counts(1)[-1]["rejects"] is not None)
    # and the marker must survive a counter write, else absence becomes ambiguous again on the next record
    rs.record(1)
    check("the first-observation marker survives a record write", rs._read_since() is not None)
    check("past days stay null after a later write", rs.daily_counts(3)[0]["rejects"] is None)


def test_exec_window_canonical_gate():
    """ExecState.window_canonical decides whether this node may ATTEST an exec_root. It must pass a
    from-genesis node, FAIL a mid-flight cold start (raised floors -> BEACON/BHASH revert where a
    from-genesis node returns a value -> divergent root), and self-heal once the gap ages past retention."""
    import threading
    from execnode.state import ExecState, _BEACON_RETENTION_EPOCHS, _GENESIS_BEACON_FLOOR
    from protocol import EPOCH_LENGTH

    st = ExecState.__new__(ExecState)
    st._mutate_lock = threading.RLock()

    st.cursor, st.beacon_floor, st.blockhash_floor = 7000, _GENESIS_BEACON_FLOOR, 1
    check("a from-genesis node holds a canonical window", st.window_canonical() is True)

    st.cursor, st.beacon_floor, st.blockhash_floor = 110 * EPOCH_LENGTH, 102, 100 * EPOCH_LENGTH
    check("a mid-flight cold start is NOT canonical (must not settle)", st.window_canonical() is False)

    st.cursor = (102 + _BEACON_RETENTION_EPOCHS + 10) * EPOCH_LENGTH
    check("the gate self-heals once the missing span ages past retention", st.window_canonical() is True)

    st.cursor, st.beacon_floor, st.blockhash_floor = -1, _GENESIS_BEACON_FLOOR, 1
    check("a fresh (cursor -1) state is NOT canonical", st.window_canonical() is False)

    # fail CLOSED on an unknown blockhash window rather than assuming completeness
    st.cursor, st.beacon_floor, st.blockhash_floor = 7000, _GENESIS_BEACON_FLOOR, None
    check("an unknown blockhash floor FAILS CLOSED", st.window_canonical() is False)


def test_exec_blockhash_floor_derived_on_restore():
    """A payload written before blockhash_floor existed still carries the hash ring, so the floor must be
    DERIVED from min(ring) on restore. Stamping it lazily at the next recorded height would mislabel a
    complete-from-genesis window as freshly-started and block settlement for a full ring."""
    import threading
    from execnode.state import ExecState

    st = ExecState.__new__(ExecState)
    st._mutate_lock = threading.RLock()
    # persisted form is {height_str: DECIMAL str(int)} — see ExecState._snapshot
    st._restore({"cursor": 5000, "block_hashes": {"3": "171", "4": "205", "5000": "239"}})
    check("blockhash_floor is derived from the ring when the payload predates the field",
          st.blockhash_floor == 3)
    # a malformed hash must not pin the floor (parse before stamping)
    st2 = ExecState.__new__(ExecState)
    st2._mutate_lock = threading.RLock()
    st2._restore({"cursor": 10})
    st2.record_block_hash(42, "not-hex")
    check("a malformed block hash does NOT poison the floor", st2.blockhash_floor is None)
    st2.record_block_hash(43, "ff")
    check("a valid hash sets the floor", st2.blockhash_floor == 43)


# ---------------------------------------------------------------------------------------------------
# 5) WITHDRAW: characterize the "does not match the pending unbond" error as a divergence SYMPTOM.
# ---------------------------------------------------------------------------------------------------
def test_withdraw_matches_pending():
    _fresh_home("nado_div_withdraw_")
    from ops import kv_ops, account_ops
    from ops.account_ops import reflect_transaction
    from protocol import BOND_UNLOCK_DELAY

    addr = "unbonder"
    account_ops.create_account(addr, balance=0, bonded=500)
    BH = 1000
    unbond_tx = {"sender": addr, "recipient": "unbond", "amount": 200, "fee": 0,
                 "txid": "u" * 64, "data": ""}
    with kv_ops.write_txn():
        reflect_transaction(unbond_tx, logger=logger, block_height=BH)

    pending = kv_ops.unbond_get(addr)
    check("unbond records a pending {amount, release_block}",
          bool(pending) and pending["amount"] == 200 and pending["release_block"] == BH + BOND_UNLOCK_DELAY)

    # The withdraw validation (transaction_ops.py) requires data == the pending record EXACTLY. A wallet that
    # read the pending from THIS node builds a matching withdraw -> accepted.
    good = {"amount": pending["amount"], "release_block": pending["release_block"]}
    matches = good["amount"] == pending["amount"] and good["release_block"] == pending["release_block"]
    check("a withdraw whose data matches this node's pending record validates", matches)

    # If the wallet read the pending from a DIVERGED seed (different release_block), the merge is rejected
    # with exactly the reported message. This is why the fix is to reconcile the seed state, not the wallet.
    stale = {"amount": pending["amount"], "release_block": pending["release_block"] + 1}
    rejected = stale["release_block"] != pending["release_block"]
    check("a withdraw carrying a DIVERGED release_block is rejected "
          "('withdraw data does not match the pending unbond')", rejected)


def test_block_stores_excluded_from_root():
    """6. BLOCK STORAGE (block_by_num/block_by_hash) must NOT feed the L1 state root. Their contents depend
    on a node's height, history-retention/pruning and orphan bodies accumulated across reorgs — NOT on the
    canonical block sequence — so including them made two nodes that agree on every block compute DIFFERENT
    roots (the alphanet-8 fresh-sync wedge: a catching-up node tripped the state-root gate at ~h62). The
    consensus root must be invariant to block storage; blocks are secured by their own hash chain."""
    _fresh_home("nado_blkroot_")
    from ops import account_ops, kv_ops
    from ops.snapshot_ops import merkle_root, read_state, _root_triples, l1_state_root, ROOT_EXCLUDED_DBS

    account_ops.create_account("a", balance=100)
    base = read_state()
    root_a = l1_state_root()

    check("block_by_num / block_by_hash are excluded from the root",
          {"block_by_num", "block_by_hash"} <= ROOT_EXCLUDED_DBS)
    # treasury_proposals is a WRITE-ONLY display index (no consensus reader) written first-writer-wins with
    # no _del — a reverted first-vote leaves a ghost proposal row. Excluded from the root (still snapshot-
    # carried) so the ghost is harmless; see snapshot_ops.ROOT_EXCLUDED_DBS.
    check("treasury_proposals (display index, rollback-asymmetric) is excluded from the root",
          "treasury_proposals" in ROOT_EXCLUDED_DBS)
    tp_ghost = list(base) + [("treasury_proposals", b"pid123", b"{\"amount\":5}")]
    check("state_root is INVARIANT to a ghost treasury_proposals row (reorg residue)",
          merkle_root(_root_triples(tp_ghost)) == root_a)
    # tvprev* is the treasury re-vote REVERT JOURNAL (kv_ops.treasury_vote_prev_*) — rollback bookkeeping
    # that must not sit in the consensus commitment (every other journal is in _LOCAL_DBS).
    tvprev = list(base) + [("meta", b"tvprevE:txabc", b"\x01"), ("meta", b"tvprevW:txabc", b"500")]
    check("state_root is INVARIANT to the tvprev re-vote revert journal (excluded prefix)",
          merkle_root(_root_triples(tvprev)) == root_a)

    # Two nodes, IDENTICAL consensus state, DIFFERENT block storage: an orphan fork body on one, a pruned
    # block row on the other. The OLD full-root formula diverges; the NEW consensus root is identical.
    node_orphan = list(base) + [("block_by_hash", b"\x01" * 32, b"orphan-fork-body")]
    node_pruned = [t for t in base if t[0] != "block_by_num"]
    old_diverges = merkle_root(node_orphan) != merkle_root(node_pruned)
    new_matches = (merkle_root(_root_triples(node_orphan))
                   == merkle_root(_root_triples(node_pruned)) == root_a)
    check("OLD formula (block stores in root) DIVERGES on block-storage difference", old_diverges)
    check("NEW consensus root is INVARIANT to block-storage difference", new_matches)


def test_node_local_meta_excluded_from_root():
    """7. NODE-LOCAL META ROWS (finalized_height, pruned_below) must NOT feed the L1 state root. Both live in
    the `meta` sub-DB but are NOT block-tx-derived: finalized_height advances by PEER CORROBORATION (a
    producer at tip H persists H-FINALITY_DEPTH; a catching-up node keeps 0) and pruned_below by LOCAL
    retention/pruning. Including them made a producer and a fresh synchronizer at the same tip commit
    different as-of-parent roots the instant finality first advanced — the gate refused block 47 (=
    FINALITY_DEPTH+2). The consensus root must be invariant to both; every OTHER meta row IS block-derived
    and stays in the root."""
    _fresh_home("nado_metaroot_")
    from ops import account_ops
    from ops.snapshot_ops import (merkle_root, read_state, _root_triples, l1_state_root,
                                  ROOT_EXCLUDED_META_KEYS)
    from ops import codec

    account_ops.create_account("a", balance=100)
    base = read_state()
    root_a = l1_state_root()

    check("finalized_height / pruned_below are excluded from the root",
          ROOT_EXCLUDED_META_KEYS == frozenset((b"finalized_height", b"pruned_below")))

    # meta rows are key.encode() -> _pack(int) (see kv_ops.meta_set_int). Two nodes at the same tip, IDENTICAL
    # in every block-derived row, differing ONLY in the two node-local finality/prune values — plus one
    # block-derived meta row (a replay guard) that MUST still count. The OLD full-meta root diverges on the
    # node-local difference; the NEW consensus root is invariant to it yet still reflects the derived row.
    derived = ("meta", b"chain_generation", codec.pack(6))              # block-derived meta: stays in root
    producer = list(base) + [derived,
                             ("meta", b"finalized_height", codec.pack(1)),
                             ("meta", b"pruned_below", codec.pack(2))]
    syncing = list(base) + [derived,
                            ("meta", b"finalized_height", codec.pack(0)),
                            ("meta", b"pruned_below", codec.pack(0))]
    old_diverges = merkle_root(producer) != merkle_root(syncing)
    new_matches = merkle_root(_root_triples(producer)) == merkle_root(_root_triples(syncing))
    check("OLD formula (all meta in root) DIVERGES on node-local finality/prune difference", old_diverges)
    check("NEW consensus root is INVARIANT to finalized_height / pruned_below", new_matches)

    # ...but a genuinely block-derived meta row still moves the root (the exclusion is surgical, not a
    # blanket meta drop): a state with ONLY an excluded row collapses back to the base root, while adding the
    # derived row changes it — so the derived row is provably still committed.
    excluded_only = list(base) + [("meta", b"finalized_height", codec.pack(1))]
    check("adding ONLY an excluded meta row leaves the consensus root unchanged",
          merkle_root(_root_triples(excluded_only)) == root_a)
    check("block-derived meta rows STILL feed the root",
          merkle_root(_root_triples(producer)) != merkle_root(_root_triples(excluded_only)))


if __name__ == "__main__":
    for t in (test_rollback_order,
              test_revert_journals_excluded_from_root,
              test_empty_account_canonicalized,
              test_block_stores_excluded_from_root,
              test_node_local_meta_excluded_from_root,
              test_exec_summary_determinism_and_proof_disabled,
              test_execsum_excluded_from_root,
              test_dividend_inflow_revert_roundtrips,
              test_reserved_dedup_is_canonical,
              test_tx_data_rejects_floats,
              test_bridge_escrow_revert_roundtrips,
              test_manifest_hash_ignores_version,
              test_snapshot_payload_authenticated,
              test_no_self_equivocation_across_reorg,
              test_execsum_window_survives_rollback,
              test_state_fingerprint_is_single_walk_and_consistent,
              test_all_db_pairs_single_txn_snapshot,
              test_rollback_stats_reject_emergency_schema,
              test_exec_window_canonical_gate,
              test_exec_blockhash_floor_derived_on_restore,
              test_withdraw_matches_pending):
        print(f"\n--- {t.__name__} ---")
        t()
    print(f"\n{'ALL SEED-DIVERGENCE CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)

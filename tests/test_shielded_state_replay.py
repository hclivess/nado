"""
Replay and duplication — the fund-lock class, found by attacking the finished system.

THE BUG THIS FILE EXISTS FOR. A deposit is 0-in/1-out: it has no nullifier, because there is nothing to
spend. That makes its proof and public statement INFINITELY REPLAYABLE — nothing about them is consumed.
Each replay appended the same commitment to the tree again, and since nf = H(nsk, cm) depends only on the
note, every copy shared ONE nullifier. Spend either and the rest become permanently unspendable while
their value still sits in the contract's escrow: coins locked forever, and the turnstile invariant
(escrow == private total) broken with them.

That is the same shape as the fund locks this repo has paid for before, and it was not caught by any of
the 86 checks that existed when the feature was "finished" — every one of them exercised the system
working, not an adversary reusing a valid artefact.

THE FIX is one rule: a commitment is UNIQUE, exactly as a nullifier is. Checked before either verifier
runs, so it covers deposits and transitions alike rather than only the path that exposed it. An honest
depositor pays nothing for it — fresh rho gives a fresh commitment.

Run: python3 tests/test_shielded_state_replay.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_replay_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
from execnode import shielded_state as S

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


CID = "d0be764f3da9c9cc6bb609280a887929"
OTHER_CID = "230860957a7c1db403434ffb4a3969b3"
REAL_ADDR = "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"
ALICE = 0xA11CE

print("proving one deposit (~6 s)…", flush=True)
DEP_PUBLIC, DEP_PROOF = S.prove_deposit(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 111,
                                        public_delta=1000)
DEP_CM = DEP_PUBLIC["out_commitments"][0]


def _state():
    st = ExecState(path=os.path.join(os.environ["HOME"], f"s{os.urandom(4).hex()}.json"))
    st.contracts[CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
    st.bridge["alice"] = 5000
    st.bridge["attacker"] = 5000
    return st


def _deposit(st, sender="alice", label="d"):
    return st.apply_blob({"op": "private_call", "public": DEP_PUBLIC, "proof": DEP_PROOF}, sender, label)


# ---- the bug itself ----------------------------------------------------------------------------------
def t_a_deposit_cannot_be_replayed():
    st = _state()
    assert _deposit(st).startswith("private_call "), "the honest deposit was rejected"
    r = _deposit(st, "alice", "d2")
    assert r == "skip private_call: output commitment already exists (a replayed or reused note)", \
        f"a deposit was replayable: {r}"


def t_a_third_party_cannot_replay_someones_deposit():
    """The griefing shape: the attacker pays for the replay out of their OWN balance, so it costs them
    money — and the damage lands on the depositor, whose second note would be unspendable."""
    st = _state()
    assert _deposit(st).startswith("private_call ")
    before = st.bridge["attacker"]
    r = _deposit(st, "attacker", "grief")
    assert r.startswith("skip"), f"a third party replayed the deposit: {r}"
    assert st.bridge["attacker"] == before, "the rejected replay still debited the attacker"


def t_a_replay_mutates_nothing():
    st = _state()
    _deposit(st)
    esc, notes, alice = st.bridge[CID], list(st.app_state.trees[CID]), st.bridge["alice"]
    _deposit(st, "alice", "d3")
    assert st.bridge[CID] == esc, "a rejected replay moved escrow"
    assert st.app_state.trees[CID] == notes, "a rejected replay appended a note"
    assert st.bridge["alice"] == alice, "a rejected replay debited the sender"


def t_the_turnstile_survives_a_replay_attempt():
    """The invariant the bug broke: escrow must equal the claimable private total. A duplicated note is
    NOT claimable twice — it shares one nullifier — so escrow that counted it twice was unbacked."""
    st = _state()
    _deposit(st)
    _deposit(st, "attacker", "d4")
    claimable = 1000                      # exactly one spendable note exists
    assert st.bridge[CID] == claimable, \
        f"escrow {st.bridge[CID]} exceeds the claimable private total {claimable}"


# ---- the rule, at the state-machine level ------------------------------------------------------------
def t_a_commitment_is_unique_per_contract():
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    assert not p.has_commitment(CID, cm), "an empty pool claims to hold a commitment"
    p.append(CID, cm)
    assert p.has_commitment(CID, cm), "an appended commitment is not found"
    assert not p.has_commitment("other_cid", cm), "commitments are not scoped per contract"


def t_the_membership_index_survives_a_snapshot():
    """_cmset is derived state and is never persisted, so a reloaded pool must rebuild it — otherwise the
    guard silently stops working after a restart, which is the worst possible failure for it."""
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    p.append(CID, cm)
    q = S.ShieldedStatePool.from_dict(p.to_dict())
    assert q.has_commitment(CID, cm), "the duplicate guard does not survive a reload"


def t_a_duplicate_within_one_transition_is_refused():
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "nullifiers": [],
                             "out_commitments": [cm, cm], "public_delta": 1}, {"stark": {}}, p)
    assert r == "duplicate output commitment within one transition", \
        f"one transition created the same note twice: {r}"


def t_a_transition_cannot_recreate_an_existing_note():
    """The rule is not deposit-specific: a prover reusing rho on the OUTPUT side hits it too."""
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    p.append(CID, cm)
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "root": p.root(CID), "nullifiers": [7],
                             "out_commitments": [cm], "public_delta": 0}, {"stark": {}}, p)
    assert r == "output commitment already exists (a replayed or reused note)", \
        f"a transition recreated an existing note: {r}"


# ---- mod-P aliasing of the public delta ---------------------------------------------------------------
# The circuit pins CONS = -public_delta as a FIELD element, so every delta congruent mod P satisfies the
# same boundary: a proof for -1000 is equally a proof for -1000 - P. Without a bound, the proof attests to
# `delta mod P`, not to the delta the ledger then moves.
#
# HONEST SEVERITY: this was not exploitable in practice. Total supply (~2.3e12 raw) is nine orders of
# magnitude below P (~1.8e19), so the op's solvency checks would always have refused an aliased amount.
# It is fixed because "an unreachable amount stops it" is a property of today's supply and check ordering,
# not of the proof — and the proof is what is supposed to be doing the work.
def t_the_delta_is_bound_to_an_integer_not_a_residue():
    from execnode.stark import field as Fld
    cm = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 222)
    pool = S.ShieldedStatePool({CID: [cm]})
    public, proof = S.prove_transition(pool, CID, S.KIND_VALUE, ALICE, [1000], 222,
                                       pool.position(CID, cm), [0], S.owner_of(ALICE), 333,
                                       public_delta=-1000, withdraw_addr="dest")
    fresh = lambda: S.ShieldedStatePool({CID: [cm]})
    assert S.verify_transition(public, proof, fresh()) is None, "the honest withdrawal was rejected"
    for alias in (-1000 - Fld.P, -1000 + Fld.P):
        pub = dict(public, public_delta=alias)
        r = S.verify_transition(pub, proof, fresh())
        assert r is not None and "out of range" in r, \
            f"a delta aliased mod P was accepted ({alias}): {r}"


def t_the_bound_matches_the_in_circuit_range():
    """|delta| < VALUE_MAX, and VALUE_MAX is the bound the notes are ACTUALLY held to in-circuit — measured
    by building honest traces, not read off a docstring. Together they make the mod-P conservation equation
    coincide with the integer one: the C-3 argument, applied to the one public value the gadget does not
    cover. The two verifiers must agree on the note range, or the transparent path (which exists to be the
    circuit's specification) would admit notes no proof could ever spend."""
    from execnode.stark import appnote_circuit as AC, alghash

    def trace_ok(v):
        tr, T, _cm = AC.build_deposit_trace(12345, S.KIND_VALUE, [v], alghash.owner_of(9), 5)
        per = AC.deposit_periodic(T, 1, 12345, S.KIND_VALUE)
        return not any(c(tr[r], tr[r + 1], [x[r] for x in per]) != 0
                       for r in range(T - 1) for c in AC.transitions())

    assert trace_ok(S.VALUE_MAX - 1), "a value just under VALUE_MAX is not provable — the bound is too high"
    assert not trace_ok(S.VALUE_MAX), "a value at VALUE_MAX is provable — the bound is too low"
    assert S.PREDICATES[S.KIND_VALUE]([[S.VALUE_MAX]], [[0]], -S.VALUE_MAX) is not None, \
        "the transparent predicate admits a value the circuit refuses"
    p = S.ShieldedStatePool()
    # the stub declares a VALID shape, so the delta bound is the check under test rather than the arity one
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "nullifiers": [], "public_delta": S.VALUE_MAX,
                             "out_commitments": [1]}, {"stark": {"arity": 1}}, p)
    assert r is not None and "out of range" in r, f"a delta at the bound was accepted: {r}"


# ---- the withdrawal destination ----------------------------------------------------------------------
# Unlike the pool's unshield — which records an exit for L1 to release, and lets L1 check the address —
# a private withdrawal credits an exec-layer balance DIRECTLY. Whatever string lands there IS the account.
def _withdraw_to(dest):
    cm = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 222)
    pool = S.ShieldedStatePool({CID: [cm]})
    public, proof = S.prove_transition(pool, CID, S.KIND_VALUE, ALICE, [1000], 222,
                                       pool.position(CID, cm), [0], S.owner_of(ALICE), 333,
                                       public_delta=-1000, withdraw_addr=dest)
    st = _state()
    st.contracts[OTHER_CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
    st.bridge[CID] = 1000
    st.app_state = S.ShieldedStatePool({CID: [cm]})
    return st, st.apply_blob({"op": "private_call", "public": public, "proof": proof}, "alice", "w")


def t_a_withdrawal_to_a_real_address_works():
    st, r = _withdraw_to(REAL_ADDR)
    assert r.startswith("private_call "), f"an honest withdrawal was rejected: {r}"
    assert st.bridge[REAL_ADDR] == 1000, "the destination was not credited"


def t_a_withdrawal_cannot_target_a_contract():
    """The turnstile-breaking shape: crediting a contract's escrow while it holds NO notes makes
    bridge[cid] != that contract's private total, and the coins are unspendable, because spending contract
    escrow requires a note under that cid."""
    st, r = _withdraw_to(OTHER_CID)
    assert "not a spendable account" in r, f"a withdrawal credited a contract's escrow: {r}"
    assert OTHER_CID not in st.bridge, "the rejected withdrawal still moved value"
    assert st.bridge[CID] == 1000, "the rejected withdrawal drained the source contract"


def t_a_withdrawal_cannot_burn_to_a_non_address():
    """A typo or truncation would otherwise create a balance under a key no bridge_withdraw can move."""
    st, r = _withdraw_to("not-an-address")
    assert "not a spendable account" in r, f"value was burned to a non-address: {r}"


def t_a_withdrawal_cannot_target_a_reserved_name():
    st, r = _withdraw_to("bond")
    assert "not a spendable account" in r, f"a reserved protocol name was accepted as a destination: {r}"


# ---- the anchor window: consensus-gating, but NOT in the state root ----------------------------------
# knows_root decides whether a transition is ACCEPTED, yet the anchor list is not committed by exec_root.
# So a divergence here would fork the fleet with no root mismatch to signal it — which is the reason these
# checks exist even though the current implementation is sound.
def t_the_anchor_set_is_a_pure_function_of_the_applied_sequence():
    def build(n):
        p = S.ShieldedStatePool()
        for i in range(n):
            p.append(CID, S.note_commitment(CID, S.KIND_VALUE, [i], S.owner_of(ALICE), i))
        return p
    a, b = build(40), build(40)
    assert a.anchors == b.anchors, "two nodes applying the same sequence disagree about known roots"
    assert S.ShieldedStatePool.from_dict(a.to_dict()).anchors == a.anchors, \
        "the anchor set does not survive a snapshot — a restored node would reject live proofs"


def t_the_window_evicts_at_exactly_the_documented_depth():
    """MEASURED: 128 appends to ONE contract evict a root. A transition proof takes ~31 s to build (~5
    blocks), and blob inclusion runs at roughly one per block, so the margin is ~25x. Recorded rather than
    widened: this is a liveness property to watch if a single contract ever sustains high append
    throughput, not a live problem, and ANCHOR_WINDOW gates acceptance so it cannot be changed unilaterally."""
    p = S.ShieldedStatePool()
    p.append(CID, S.note_commitment(CID, S.KIND_VALUE, [0], S.owner_of(ALICE), 0))
    target = p.root(CID)
    for k, expected in ((S.ANCHOR_WINDOW - 1, True), (S.ANCHOR_WINDOW, False)):
        q = S.ShieldedStatePool.from_dict(p.to_dict())
        for i in range(1, k + 1):
            q.append(CID, S.note_commitment(CID, S.KIND_VALUE, [i], S.owner_of(ALICE), i))
        assert q.knows_root(CID, target) is expected, \
            f"after {k} appends the root should be {'known' if expected else 'evicted'}"


def t_one_contracts_activity_cannot_evict_anothers_anchors():
    """Trees and anchor windows are per-contract, so a busy vault cannot invalidate a quiet one's
    in-flight proofs. This is the reason the trees were split per contract in the first place."""
    p = S.ShieldedStatePool()
    p.append(CID, S.note_commitment(CID, S.KIND_VALUE, [0], S.owner_of(ALICE), 0))
    target = p.root(CID)
    for i in range(S.ANCHOR_WINDOW * 2):
        p.append(OTHER_CID, S.note_commitment(OTHER_CID, S.KIND_VALUE, [i], S.owner_of(ALICE), i))
    assert p.knows_root(CID, target), "activity on another contract evicted this contract's anchor"


# ---- the note kind cannot be aliased -----------------------------------------------------------------
def t_the_kind_cannot_be_aliased_mod_p():
    """kind is absorbed into the circuit as kind % P, so kind and kind + P would produce the same public
    column. What closes it is that PREDICATES and STARK_KINDS are looked up on the RAW integer, before the
    circuit is ever reached — the same shape as the delta bound, and worth pinning so a future refactor
    that normalises the lookup key does not quietly open it."""
    from execnode.stark import field as Fld
    p = S.ShieldedStatePool()
    for aliased in (S.KIND_VALUE + Fld.P, S.KIND_VALUE - Fld.P):
        r = S.verify_transition({"cid": CID, "kind": aliased, "nullifiers": [], "out_commitments": [1],
                                 "public_delta": 5}, {"stark": {}}, p)
        assert r == f"unknown note kind {aliased}", f"a kind aliased mod P was accepted: {r}"


# ---- the proof's declared shape must match the kind's -------------------------------------------------
# The circuit is arity-parametric BY DESIGN — that is what makes a new note type a new predicate rather
# than a new circuit. So the circuit will happily prove a two-field KIND_VALUE note, and the binding
# between shape and kind can only be made by the state machine. Without it, a KIND_VALUE note could carry
# a second field that _predicate_value never looks at and therefore no rule governs.
def t_a_kind_cannot_be_minted_at_the_wrong_arity():
    from execnode.stark import appnote_circuit as AC
    stark, cm = AC.prove_deposit(S.cid_element(CID), S.KIND_VALUE, [1000, 777], S.owner_of(ALICE), 42,
                                 public_delta=1000, aux="")
    ok, _ = AC.verify_deposit(stark, S.cid_element(CID), S.KIND_VALUE, cm, 1000, aux="")
    assert ok, "the fixture proof should be valid — the point is that VALIDITY is not enough"
    pub = {"cid": CID, "kind": S.KIND_VALUE, "root": S.EMPTY_ROOT, "nullifiers": [],
           "out_commitments": [cm], "public_delta": 1000}
    p = S.ShieldedStatePool()
    r = S.apply_transition(pub, {"stark": stark}, p)
    assert r == "kind 1 takes 1 field(s); the proof declares 2", f"wrong-arity note minted: {r}"
    assert not p.trees.get(CID), "the refused note was still appended"


def t_every_provable_kind_declares_its_arity():
    """A kind that can be proved but has no declared shape would slip past the check above entirely."""
    missing = S.STARK_KINDS - set(S.KIND_ARITY)
    assert not missing, f"provable kinds with no declared arity: {missing}"


def t_a_membership_proof_must_match_the_pool_depth():
    """A proof at another depth could only fold to a known root by hash collision — but the verifier can
    simply check it, and should, rather than leaning on collision-resistance for a structural property."""
    cm = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 1)
    pool = S.ShieldedStatePool({CID: [cm]})
    pub, prf = S.prove_transition(pool, CID, S.KIND_VALUE, ALICE, [1000], 1, 0, [1000],
                                  S.owner_of(ALICE), 2, public_delta=0)
    fresh = lambda: S.ShieldedStatePool({CID: [cm]})
    assert S.verify_transition(pub, prf, fresh()) is None, "the honest transition was rejected"
    shallow = {"stark": dict(prf["stark"], D=4)}
    r = S.verify_transition(pub, shallow, fresh())
    assert r == f"membership proof is depth 4, this pool is depth {S.TREE_DEPTH}", \
        f"a relabelled depth was accepted: {r}"


def t_tree_depth_is_the_largest_free_depth():
    """TREE_DEPTH must be the deepest tree whose trace still fits the current power of two. RECOMPUTED from
    the circuit's own geometry, not asserted as a literal: the constant arrived here at 20 because that was
    measured against the JOIN-SPLIT, whose commitment region is 3R smaller — so this circuit was paying a
    doubled trace (T=4096, ~31% more prove time) for capacity it does not need. A constant that mirrors a
    circuit has to be checked against that circuit."""
    from execnode.stark import appnote_circuit as AC
    T = AC.trace_len(1, S.TREE_DEPTH)
    assert AC.trace_len(1, S.TREE_DEPTH + 1) > T, \
        f"depth {S.TREE_DEPTH + 1} would still fit T={T} — TREE_DEPTH is leaving capacity unused"
    assert AC.trace_len(1, S.TREE_DEPTH) == T, "geometry is not self-consistent"
    # and the tree the pool actually builds must match what the circuit is told to expect
    p = S.ShieldedStatePool()
    p.append(CID, S.note_commitment(CID, S.KIND_VALUE, [1], S.owner_of(ALICE), 1))
    sibs, dirs = S.tree_path(p.trees[CID], 0)
    assert len(sibs) == S.TREE_DEPTH == len(dirs), "the pool's path depth differs from TREE_DEPTH"


# ---- the verifier must not allocate from numbers a stranger chose ------------------------------------
# verify() reads arity and depth from the PROOF and builds NPER periodic columns of length
# trace_len(arity, D) from them. Unbounded, a declared arity of 10^6 asks for a 67M-row trace (~49 GB of
# columns) and a declared depth of 10^6 asks for ~98 GB. The state machine pins both before calling — but
# that guard lives in the CALLER, and the allocation happens in the callee.
def t_an_absurd_geometry_is_refused_before_anything_is_built():
    import time
    from execnode.stark import appnote_circuit as AC
    for label, proof in [("arity 10^6", {"arity": 10 ** 6, "D": 18}),
                         ("depth 10^6", {"arity": 1, "D": 10 ** 6}),
                         ("arity MAX+1", {"arity": AC.MAX_FIELDS + 1, "D": 18}),
                         ("depth MAX+1", {"arity": 1, "D": AC.MAX_DEPTH + 1})]:
        proof["T"] = AC.trace_len(proof["arity"], proof["D"])   # a T that MATCHES, so that check passes
        t0 = time.time()
        ok, why = AC.verify(proof, 1, 1, 0, 0, 0, 0, lambda r: True)
        assert not ok and "out of range" in why, f"{label} was not refused: {why}"
        assert time.time() - t0 < 1.0, f"{label} took real work to refuse — something was allocated"


def t_the_deposit_verifier_bounds_arity_too():
    from execnode.stark import appnote_circuit as AC
    p = {"deposit": True, "arity": 10 ** 6}
    p["T"] = AC.trace_len(p["arity"], 1)
    ok, why = AC.verify_deposit(p, 1, 1, 0, 5)
    assert not ok and "out of range" in why, f"the deposit verifier accepted an absurd arity: {why}"


def t_max_fields_has_one_definition():
    """It was defined in both the circuit and the state machine. A bound that exists twice is a bound that
    can disagree with itself — the same reason the domain tags live in one place."""
    from execnode.stark import appnote_circuit as AC
    assert S.MAX_FIELDS is AC.MAX_FIELDS, "MAX_FIELDS has drifted into two definitions"


def t_the_value_bound_is_derived_from_the_gadget_not_restated():
    """VALUE_MAX was 2^62 while the circuit enforced 2^61, because the constant was copied from prose about
    the constraint instead of from the constraint. It is now COMPUTED from RNG_TOP_BITS — the same number
    c_rng_top sums bit columns from — so the two cannot say different things. This checks the derivation
    against reality by building traces at the boundary, not against another constant."""
    from execnode.stark import appnote_circuit as AC, alghash

    def provable(v):
        tr, T, _cm = AC.build_deposit_trace(12345, S.KIND_VALUE, [v], alghash.owner_of(9), 5)
        per = AC.deposit_periodic(T, 1, 12345, S.KIND_VALUE)
        return not any(c(tr[r], tr[r + 1], [x[r] for x in per]) != 0
                       for r in range(T - 1) for c in AC.transitions())

    assert S.VALUE_MAX is AC.RANGE_BOUND, "the state machine restates the bound instead of importing it"
    assert AC.RANGE_BOUND == 1 << (4 * AC.RNG_NIBBLES - AC.RNG_TOP_BITS), "the derivation drifted"
    assert provable(AC.RANGE_BOUND - 1), "the derived bound is above the circuit's real one"
    assert not provable(AC.RANGE_BOUND), "the derived bound is below the circuit's real one"


def t_oversized_lists_are_rejected_before_being_converted():
    import time
    pub = {"cid": CID, "kind": S.KIND_VALUE, "public_delta": 0, "out_commitments": [1],
           "nullifiers": list(range(200_000))}
    t0 = time.time()
    r = S.verify_transition(pub, {"stark": {"arity": 1}}, S.ShieldedStatePool())
    dt = time.time() - t0
    assert "exceeds" in r, f"an oversized statement was not rejected: {r}"
    assert dt < 0.01, f"rejection took {dt:.3f}s — the list was converted before the bound ran"


def t_a_non_list_statement_is_refused():
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "nullifiers": "not-a-list",
                             "out_commitments": [1], "public_delta": 0}, {"stark": {"arity": 1}},
                            S.ShieldedStatePool())
    assert r == "nullifiers and out_commitments must be lists", f"a string was iterated as a list: {r}"


def t_a_malformed_contract_id_is_typed_out_not_caught_by_the_catch_all():
    """apply_blob's catch-all would turn an unhashable cid into a skip anyway. Checking the type is still
    the right guard: this dispatch has been here before — a blob carrying an unhashable `ns` once raised in
    the block loop and froze the exec cursor fleet-wide for one MIN_TX_FEE transaction — and 'an exception
    handler happens to catch it' is not the same guarantee as 'it is rejected on purpose'."""
    import tempfile
    from execnode.state import ExecState
    st = ExecState(path=os.path.join(tempfile.mkdtemp(), "s.json"))
    for bad in (["a"], {"a": 1}, 7, None):
        r = st.apply_blob({"op": "private_call", "public": {"cid": bad}, "proof": {}}, "s", "t")
        assert r == "skip private_call: contract id must be a string", f"cid={bad!r} gave {r}"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL REPLAY CHECKS PASSED")
sys.exit(1 if FAILS else 0)

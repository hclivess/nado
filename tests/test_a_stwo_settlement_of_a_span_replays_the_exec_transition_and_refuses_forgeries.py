"""A Stwo settlement of a span replays the exec transition from a witness and refuses forgeries (Goldilocks retirement G4,
doc/stwo/g4-settlement-statement.md section 5; execnode/settle_b2.py).

A real exec state plays a 239-block span through execnode/block_apply.py (the code the exec node runs): a tictactoe game
to a win and its payout, a dice bet bound to an epoch beacon and settled from it (a BEACON chain read), RANDAO reveals,
six asset ops on an asset created before the span, an emit, a bridge withdrawal, the L1 claim that garbage-collects an
older one, a deploy, transfer_contract and lock, the dividend accrual across an epoch boundary and a collect_dividend.
Then:
  1. prove_span builds the witness and the Stwo proof of the 9 VM runs; verify_span, holding no exec state, replays the
     span on the witness and lands on EXACTLY the exec node's post root;
  2. every forgery is refused, each for its own reason: an opening's value, an opening claimed absent, an opening
     dropped, a slot, the contract code, a tree proof, a sibling opening, the pre halves, an SLOAD value, an SSTORE
     value, a step count, a VM run dropped or added, the VM proof (from another span, or corrupted), a revert's kind, a
     reverted run claimed returning, a chain read the chain does not hold, a call's argument in the block, a transaction
     removed from a block, the claimed post root;
  3. a REVERTING call proves (the out-of-turn move in the span; a span whose only call reverts lands on the exec node's
     root with the escrow refunded); the four reverts the circuit leaves to the verifier (an asset PAY or ABURN beyond the
     holding, a BHASH or BEACON the chain does not hold) are accepted only as exactly that. What the witness cannot carry
     yet is reported as UNPROVABLE, never proven: an asset created inside the span, and (below
     protocol.EXEC_ADDR_ROOT_HEIGHT only) a payout to an address registered before the span;
  5. BOTH RULE SETS of the registry gate: below it that payout is unprovable; from it the registry is a committed ledger
     (exec_root_b2.T_ADDR), the same span proves and lands on the exec node's root, a registered payee claimed absent is
     refused, and a span that crosses the gate (the root that inserts the whole registry) is unprovable;
  4. the partial tree (execnode/csmt_partial.py) agrees with csmt.Tree on 400 random write batches (inserts beside deep
     shared prefixes, collapsing deletes, updates) and refuses an opening that does not hash to its node.
Prints the prove / verify time and the witness size.

Needs the nightly toolchain to build native/stwo_settle; skips with the reason when it is not installed.
Run: python3 tests/test_a_stwo_settlement_of_a_span_replays_the_exec_transition_and_refuses_forgeries.py
"""
import os
_REAL_HOME = os.path.expanduser("~")      # BEFORE isolate: the toolchain lives under the real HOME
import _harness
HOME = _harness.isolate("nado-test-stwo-span-")
os.environ["NADO_EXEC_STATE"] = os.path.join(HOME, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(HOME, "exec_da")
import copy
import json
import random
import sys
import time

from execnode import block_apply, csmt, settle_b2 as S, zkvm2
from execnode.csmt_partial import PartialTree, opener_for
from execnode.games import coinflip, dice, tictactoe
from execnode.state import ExecState, asset_id
from execnode.stark import stark as _stk
from protocol import EPOCH_LENGTH
from tests._stwo_settle_build import NIGHTLY, build

T = _harness.Report()
A = "ndo" + "A" * 45
B = "ndo" + "B" * 45
C = "ndo" + "C" * 45


class World:
    """an exec state driven by L1-shaped blocks, and the L1 inputs a verifier derives itself"""

    def __init__(self, h0):
        self.st = ExecState(os.path.join(HOME, "st.json"))
        self.st.cursor = self.h = h0
        self.n, self.weights, self.inflow = 0, {}, {}

    def blob(self, who, payload):
        self.n += 1
        return {"recipient": "blob", "sender": who, "txid": "t%d" % self.n, "data": payload}

    def call(self, cid, who, m, args, value=0):
        return self.blob(who, {"op": "call", "contract": cid, "method": m, "args": args, **({"value": value} if value else {})})

    def block(self, txs):
        self.h += 1
        return {"block_number": self.h, "block_hash": "%064x" % (0xabc000 + self.h), "block_transactions": txs}

    def reveal(self):
        """a RANDAO reveal in the first block of each epoch, for the next epoch (so beacons become final)"""
        if (self.h + 1) % EPOCH_LENGTH != 1:
            return []
        return [{"recipient": "reveal", "sender": A,
                 "data": {"target_epoch": (self.h + 1) // EPOCH_LENGTH + 1, "secret": "s%d" % self.h}}]

    def accrual(self, E):
        return self.inflow.get(E, 0), dict(self.weights.get(E, {}))

    def apply(self, blocks, st, seen=None):
        states = {"default": st}
        for b in blocks:
            h = b["block_number"]
            while st.last_div_epoch < h // EPOCH_LENGTH - 1:
                E = st.last_div_epoch + 1
                st.accrue_dividend_epoch(*self.accrual(E), epoch=E)
                st.last_div_epoch = E
            if seen is not None:
                seen[h] = (dict(st.beacons), dict(st.block_hashes))
            with _stk.rules_at(h):
                block_apply.begin(states, h)
                block_apply.dispatch(states, st, b, {}, set(), verbose=False)
                block_apply.close(states, h, b["block_hash"])

    def chain_for(self, pre, blocks, lie=None):
        """the L1 stand-in: what a call in block h may read (a from-genesis exec node's beacons and block hashes at h),
        the accrual inputs and the carry. `lie` = (kind, key) whose value the chain reports differently"""
        seen = {}
        self.apply(blocks, pre.clone(), seen)

        def read(kind, key, h):
            bc, bh = seen[h]
            v = (bc if kind == zkvm2.IO_BEACON else bh).get(key)
            if v is None:
                return None
            v = int(v) & S.MASK
            return v ^ 1 if lie == (kind, key) else v
        return S.Chain(self.accrual, pre.div_carry, read)


def scenario():
    w = World(6000)
    ttt, dc = tictactoe.build(), dice.build()
    w.apply([w.block([w.blob(A, {"op": "deploy", "runtime": "zkvm", "code": ttt, "nonce": "t"}),
                      w.blob(A, {"op": "deploy", "runtime": "zkvm", "code": dc, "nonce": "d"}),
                      *[{"recipient": "bridge", "sender": x, "amount": 10**7} for x in (A, B, C)]])], w.st)
    t_cid, d_cid = w.st.contract_id(A, ttt, "t"), w.st.contract_id(A, dc, "d")
    aid = str(asset_id(A, 1))
    w.apply([w.block([w.blob(A, {"op": "asset_create", "seed": 1, "name": "Tok", "sym": "TOK", "dec": 0, "supply": 1000,
                                 "mintable": True}),
                      w.blob(A, {"op": "asset_approve", "asset": aid, "spender": B, "amount": 100}),
                      w.blob(C, {"op": "bridge_withdraw", "amount": 777}),
                      w.call(d_cid, A, "open", [1], 10**6)])], w.st)
    pre = w.st.clone()
    e0 = pre.cursor // EPOCH_LENGTH
    w.weights, w.inflow = {e0: {A: 3, B: 1}}, {e0: 4000}
    span = [w.block([w.call(t_cid, A, "open", [7], 500), w.call(t_cid, B, "join", [7], 500),
                     w.call(d_cid, B, "bet", [3, 1, 50], 100)]),
            w.block([w.call(t_cid, B, "move", [7, 5, 0]),            # out of turn: REQUIRE reverts (proven, section 3)
                     w.call(t_cid, A, "move", [7, 0, 0]), w.call(t_cid, B, "move", [7, 3, 1]),
                     w.call(t_cid, A, "move", [7, 1, 2])]),
            w.block([w.call(t_cid, B, "move", [7, 4, 3]), w.call(t_cid, A, "move", [7, 2, 4]),
                     w.blob(A, {"op": "asset_transfer", "asset": aid, "to": C, "amount": 10}),
                     w.blob(B, {"op": "asset_transfer_from", "asset": aid, "from": A, "to": C, "amount": 20}),
                     w.blob(A, {"op": "asset_burn", "asset": aid, "amount": 5}),
                     w.blob(A, {"op": "asset_mint", "asset": aid, "to": B, "amount": 7}),
                     w.blob(A, {"op": "asset_set_uri", "asset": aid, "uri": "ipfs://x"}),
                     w.blob(A, {"op": "emit", "to_ns": "other", "data": {"k": 1}}),
                     w.blob(B, {"op": "bridge_withdraw", "amount": 1234}),
                     {"recipient": "bridge_withdraw", "sender": C, "data": {"nonce": 1}},
                     w.blob(C, {"op": "deploy", "runtime": "zkvm", "code": coinflip.build(), "nonce": "c"}),
                     w.blob(A, {"op": "transfer_contract", "contract": t_cid, "to": C}),
                     w.blob(C, {"op": "lock", "contract": t_cid})])]
    while (w.h + 1) % EPOCH_LENGTH:
        span.append(w.block(w.reveal()))
    span.append(w.block([w.blob(A, {"op": "collect_dividend"}), w.blob(A, {"op": "asset_renounce", "asset": aid})]))
    for _ in range(3 * EPOCH_LENGTH):
        span.append(w.block(w.reveal()))
    span.append(w.block([w.call(d_cid, C, "settle", [3])]))
    return w, pre, span, t_cid, d_cid, aid


# ---- 4 first (no toolchain needed): the partial tree against csmt.Tree --------------------------------------------------
rng = random.Random(29)
bad = 0
for trial in range(400):
    keys = [rng.getrandbits(256).to_bytes(32, "big") for _ in range(rng.choice([0, 1, 2, 5, 40]))]
    if keys and rng.random() < 0.5:
        for _ in range(3):
            d = rng.randint(1, 60)
            keys.append((int.from_bytes(keys[0], "big") ^ (1 << (255 - d)) ^ rng.getrandbits(255 - d)).to_bytes(32, "big"))
    items = {k: rng.getrandbits(32).to_bytes(4, "big") for k in keys}
    t = csmt.Tree(items)
    writes = {}
    for _ in range(rng.randint(1, 10)):
        r = rng.random()
        if keys and r < 0.35:
            writes[rng.choice(keys)] = None
        elif keys and r < 0.6:
            writes[rng.choice(keys)] = b"u"
        elif keys and r < 0.85:
            d = rng.randint(0, 40)
            writes[(int.from_bytes(rng.choice(keys), "big") ^ (1 << (255 - d)) ^ rng.getrandbits(255 - d)).to_bytes(32, "big")] = b"n"
        else:
            writes[rng.getrandbits(256).to_bytes(32, "big")] = b"f"
    full = csmt.Tree(items)
    for k, v in writes.items():
        full.delete(k) if v is None else full.set(k, v)
    p = PartialTree(t.root(), on_open=opener_for(t))
    for k in writes:
        p.add_proof(k, items.get(k), t.prove(k))
    p.apply(writes)
    q = PartialTree(t.root(), opens=p.opens)              # the verifier: only the recorded openings
    for k in writes:
        q.add_proof(k, items.get(k), t.prove(k))
    q.apply(dict(reversed(list(writes.items()))))
    bad += not (p.root() == q.root() == full.root())
T.check("4a. the partial tree lands on csmt.Tree's root for 400 random write batches, prover and verifier alike", bad == 0, bad)
items = {bytes([i]) * 32: b"v%d" % i for i in range(1, 4)}
t = csmt.Tree(items)
k = bytes([1]) * 32
p = PartialTree(t.root(), on_open=opener_for(t))
p.add_proof(k, items[k], t.prove(k))
p.apply({k: None})
forged_opens = {h: ("leaf", bytes([9]) * 32, b"x") for h in p.opens}
q = PartialTree(t.root(), opens=forged_opens)
q.add_proof(k, items[k], t.prove(k))
try:
    q.apply({k: None})
    refused = False
except ValueError:
    refused = True
T.check("4b. a sibling opening that does not hash to its node is refused", bool(p.opens) and refused, p.opens)
try:
    PartialTree(t.root()).add_proof(k, b"other", t.prove(k))
    refused = False
except ValueError:
    refused = True
T.check("4c. a proof for a value the tree does not hold is refused", refused)

# ---- the Stwo part --------------------------------------------------------------------------------------------------------
BIN, log = build(_REAL_HOME, "vm_settle")
if BIN is None and not log:
    print(f"SKIP  no {NIGHTLY} toolchain: the Stwo span settlement cannot be run here (native/stwo_settle needs it)")
    T.done("SKIPPED (no toolchain)")
T.check("the vm_settle binary builds", BIN is not None, log)
if BIN is None:
    T.done()

GATE_ON, GATE_OFF = 1, 1 << 62                       # EXEC_ADDR_ROOT_HEIGHT: committed registry from block 1 / never
_gate = _harness.pinned(EXEC_ADDR_ROOT_HEIGHT=GATE_ON)
_gate.__enter__()                                   # the main scenario runs under the committed registry (section 5)
w, pre, span, t_cid, d_cid, aid = scenario()
real = pre.clone()
w.apply(span, real)
chain = w.chain_for(pre, span)
pre_root, cur = pre.state_root(), pre.cursor
t0 = time.time()
bundle = S.prove_span(pre, span, chain, BIN)
prove_s = time.time() - t0
t0 = time.time()
ok, why, post = S.verify_span(cur, pre_root, span, chain, bundle, BIN)
verify_s = time.time() - t0
T.check("1a. the honest span verifies", ok, why)
T.check("1b. ...and lands on exactly the exec node's post root", post == real.state_root(), (post, real.state_root()))
T.check("1c. the span did what it says: the tictactoe winner was paid, the dice bet settled, the dividend was collected,"
        " the old withdrawal was collected and the new one recorded",
        real.bridge.get(A) == 10**7 - 10**6 - 500 + 1000 and real.contracts[d_cid]["storage"]["slots"]
        and "1" in real.dividend_withdrawals and "1" not in real.withdrawals and "2" in real.withdrawals,
        (real.bridge.get(A), real.dividend_withdrawals, real.withdrawals))
T.check("1d. 10 VM runs went into the Stwo proof, the out-of-turn move as a proven REQUIRE revert",
        len(bundle["runs"]) == 10 and [r.get("revert") for r in bundle["runs"] if not r["ok"]] == [zkvm2.REVERT_KINDS.index("REQUIRE")],
        [(r["ok"], r.get("revert")) for r in bundle["runs"]])


def refused(name, b, *, blocks=None, ch=None, want=None):
    r = S.verify_span(cur, pre_root, blocks or span, ch or chain, b, BIN)
    T.check(f"2. refused: {name}", (not r[0]) and (want is None or want in r[1]), r[1])


def edit(f):
    b = copy.deepcopy(bundle)
    f(b)
    return b


def opening(b, fam, pred=lambda o: True):
    return next(o for o in b["openings"] if o[0] == fam and o[2] is not None and pred(o))


refused("an opening's value (A's bridge balance +1)", edit(lambda b: opening(b, "bridge", lambda o: o[1] == [A]).__setitem__(2, opening(b, "bridge", lambda o: o[1] == [A])[2] + 1)), want="does not match the tree")
refused("a present entry claimed absent", edit(lambda b: opening(b, "bridge", lambda o: o[1] == [A]).__setitem__(2, None)), want="tree disagrees")
refused("an opening dropped", edit(lambda b: b["openings"].remove(opening(b, "bridge", lambda o: o[1] == [A]))), want="does not open")
refused("a storage slot's value", edit(lambda b: opening(b, "slots").__setitem__(2, opening(b, "slots")[2] + 1)), want="does not match the tree")


def code_edit(b):
    o = opening(b, "contracts", lambda o: o[1] == [t_cid])
    m = sorted(o[2]["code"])[0]
    o[2]["code"][m][0][3] = int(o[2]["code"][m][0][3]) + 1


refused("the contract's code", edit(code_edit), want="does not match the tree")
refused("a tree proof (a sibling flipped)", edit(lambda b: (lambda pj: pj["s"].__setitem__(0, "%064x" % (int(pj["s"][0], 16) ^ 1)))(
    next(v for v in b["proofs"]["rec"].values() if v["s"]))), want="does not verify")
refused("the pre halves swapped", edit(lambda b: b.update(kv_pre=b["rec_pre"], rec_pre=b["kv_pre"])), want="pre halves")


def run_io(b, kind):
    for r in b["runs"]:
        for e in r["io"]:
            if e[0] == kind:
                return e
    raise AssertionError(kind)


refused("an SLOAD value", edit(lambda b: run_io(b, zkvm2.IO_SLOAD).__setitem__(2, run_io(b, zkvm2.IO_SLOAD)[2] ^ 1)), want="SLOAD")
def last_sstore(b):
    """the span's last SSTORE: nothing reads it back, so only the Stwo proof can catch a change to it"""
    return [e for r in b["runs"] for e in r["io"] if e[0] == zkvm2.IO_SSTORE][-1]


refused("an SSTORE value (the Stwo proof)", edit(lambda b: last_sstore(b).__setitem__(2, last_sstore(b)[2] ^ 1)), want="VM proof")
refused("a step count (the Stwo proof)", edit(lambda b: b["runs"][0].__setitem__("n_steps", b["runs"][0]["n_steps"] + 1)), want="VM proof")
refused("a VM run dropped", edit(lambda b: b["runs"].pop()), want="fewer VM runs")
refused("a VM run added", edit(lambda b: b["runs"].append(copy.deepcopy(b["runs"][0]))), want="more VM runs")
refused("the VM proof corrupted", edit(lambda b: b.update(vm_proof=b["vm_proof"][:-8] + "%08x" % (int(b["vm_proof"][-8:], 16) ^ 1))), want="VM proof")
refused("the claimed post root", edit(lambda b: b.update(post_root="00" * 32)), want="post root")
refused("a BEACON value the chain does not hold", bundle,
        ch=w.chain_for(pre, span, lie=next((e[0], e[1]) for r in bundle["runs"] for e in r["io"] if e[0] == zkvm2.IO_BEACON)),
        want="chain read")
blocks2 = copy.deepcopy(span)
blocks2[1]["block_transactions"][0]["data"]["args"][1] = 8          # A's first move to another cell
refused("a call's argument changed in the block", bundle, blocks=blocks2)
blocks3 = copy.deepcopy(span)
del blocks3[2]["block_transactions"][2]                              # the asset_transfer removed
refused("a transaction removed from a block", bundle, blocks=blocks3)


# a VM proof of another span's calls, offered for this one
def other_proof():
    w2 = World(9000)
    w2.apply([w2.block([w2.blob(A, {"op": "deploy", "runtime": "zkvm", "code": tictactoe.build(), "nonce": "t"}),
                        {"recipient": "bridge", "sender": A, "amount": 10**6}])], w2.st)
    c2 = w2.st.contract_id(A, tictactoe.build(), "t")
    p2 = w2.st.clone()
    s2 = [w2.block([w2.call(c2, A, "open", [5], 10)])]
    return S.prove_span(p2, s2, w2.chain_for(p2, s2), BIN)["vm_proof"]


refused("a VM proof of another span", edit(lambda b: b.update(vm_proof=other_proof())), want="VM proof")
_rv = next(i for i, r in enumerate(bundle["runs"]) if not r["ok"])
refused("a reverted run's revert kind (the Stwo proof)", edit(lambda b: b["runs"][_rv].update(revert=zkvm2.REVERT_KINDS.index("ASEL"))),
        want="VM proof")
refused("a reverted run claimed returning", edit(lambda b: b["runs"][_rv].update(ok=True, revert=None)))


# ---- 3: unprovable, named ---------------------------------------------------------------------------------------------
def unprovable(name, mk, want):
    w3, p3, s3 = mk()
    try:
        S.prove_span(p3, s3, w3.chain_for(p3, s3), BIN)
        T.check(f"3. unprovable: {name}", False, "it proved")
    except S.Unprovable as e:
        T.check(f"3. unprovable: {name}", want in str(e), str(e))


def game_pre():
    w3 = World(7000)
    code = tictactoe.build()
    w3.apply([w3.block([w3.blob(A, {"op": "deploy", "runtime": "zkvm", "code": code, "nonce": "t"}),
                        *[{"recipient": "bridge", "sender": x, "amount": 10**6} for x in (A, B)]])], w3.st)
    return w3, w3.st.contract_id(A, code, "t")


def mk_revert():
    w3, c3 = game_pre()
    p3 = w3.st.clone()
    return w3, p3, [w3.block([w3.call(c3, A, "open", [1], 10), w3.call(c3, B, "move", [1, 0, 0], 7)])]   # not B's game


def mk_old_payee():
    w3, c3 = game_pre()
    w3.apply([w3.block([w3.call(c3, A, "open", [1], 10), w3.call(c3, B, "join", [1], 10)])], w3.st)
    p3 = w3.st.clone()
    return w3, p3, [w3.block([w3.call(c3, B, "resign", [1])])]                                      # pays A, registered earlier


def mk_asset_create():
    w3, _c3 = game_pre()
    p3 = w3.st.clone()
    return w3, p3, [w3.block([w3.blob(A, {"op": "asset_create", "seed": 9, "name": "N", "sym": "N", "dec": 0, "supply": 5})])]


unprovable("an asset created inside the span", mk_asset_create, "absence is not provable")
w3, p3, s3 = mk_revert()
real3 = p3.clone()
w3.apply(s3, real3)
ch3 = w3.chain_for(p3, s3)
b3 = S.prove_span(p3, s3, ch3, BIN)
ok3, why3, post3 = S.verify_span(p3.cursor, p3.state_root(), s3, ch3, b3, BIN)
T.check("3a. a span whose call reverts proves: the revert is proven and lands on the exec node's root (its escrow back)",
        ok3 and post3 == real3.state_root() and [r["ok"] for r in b3["runs"]] == [True, False]
        and real3.bridge.get(B) == 10**6, (why3, b3["runs"], real3.bridge.get(B)))

# the four reverts the circuit leaves to the verifier: each judged exactly as zkvm2 fails it, and refused otherwise
RK = zkvm2.REVERT_KINDS.index
o = S.Oracle([], S.Chain(None, 0, lambda kind, key, h: 99 if key == 5 else None))


def judge(io, kind, abal=None):
    try:
        o._walk(None, io, S.Overlay({}), abal or {}, 0xabc, 10, RK(kind))
        return "accepted"
    except S.Refused as e:
        return f"refused: {e}"


T.check("3b. a PAY revert is accepted only as an overspend of the selected asset",
        judge([(zkvm2.IO_ASEL, 7, 0), (zkvm2.IO_PAY, 1, 11)], "PAY", {7: 10}) == "accepted"
        and judge([(zkvm2.IO_ASEL, 7, 0), (zkvm2.IO_PAY, 1, 10)], "PAY", {7: 10}).startswith("refused")
        and judge([(zkvm2.IO_ASEL, 7, 0), (zkvm2.IO_PAY, 0xabc, 99)], "PAY", {7: 10}).startswith("refused")
        and judge([(zkvm2.IO_PAY, 1, 99)], "PAY", {7: 10}).startswith("refused"))
T.check("3c. an ABURN revert is accepted only beyond the holding",
        judge([(zkvm2.IO_ABURN, 7, 11)], "ABURN", {7: 10}) == "accepted"
        and judge([(zkvm2.IO_ABURN, 7, 10)], "ABURN", {7: 10}).startswith("refused"))
T.check("3d. a BHASH/BEACON revert is accepted only for a value the chain does not hold at that height",
        judge([(zkvm2.IO_BHASH, 6, 0)], "BHASH") == "accepted" and judge([(zkvm2.IO_BHASH, 5, 0)], "BHASH").startswith("refused")
        and judge([(zkvm2.IO_BEACON, 5, 0)], "BEACON").startswith("refused"))
T.check("3e. a reverted run that returns, or lacks its judged entry, is refused",
        judge([(zkvm2.IO_RET, 0, 0)], "REQUIRE").startswith("refused") and judge([], "PAY").startswith("refused"))
_gate.__exit__(None, None, None)

# ---- 5: the registry gate, both rule sets -------------------------------------------------------------------------
with _harness.pinned(EXEC_ADDR_ROOT_HEIGHT=GATE_OFF):
    unprovable("below the registry gate, a payout to an address registered before the span", mk_old_payee,
               "registered before the span")
with _harness.pinned(EXEC_ADDR_ROOT_HEIGHT=GATE_ON):
    w5, p5, s5 = mk_old_payee()
    real5 = p5.clone()
    w5.apply(s5, real5)
    ch5 = w5.chain_for(p5, s5)
    b5 = S.prove_span(p5, s5, ch5, BIN)
    ok5, why5, post5 = S.verify_span(p5.cursor, p5.state_root(), s5, ch5, b5, BIN)
    T.check("5a. from the registry gate, the payout to an address registered before the span proves and lands on the "
            "exec node's root", ok5 and post5 == real5.state_root() and real5.bridge.get(A) == 10**6 + 10, (why5, real5.bridge))
    b5x = copy.deepcopy(b5)
    o = next(o for o in b5x["openings"] if o[0] == "addr" and o[2] == A)
    o[2] = None
    r = S.verify_span(p5.cursor, p5.state_root(), s5, ch5, b5x, BIN)
    T.check("5b. ...and the payee's registry entry claimed absent (the call would revert) is refused",
            not r[0] and "tree disagrees" in r[1], r[1])
from execnode import exec_root_b2 as B2  # noqa: E402
_reg = real.zk_addrs
with _harness.pinned(EXEC_ADDR_ROOT_HEIGHT=real.cursor + 1):
    below = {k for k in B2.records_projection(real) if k in {B2.record_key(B2.T_ADDR, d) for d in _reg}}
with _harness.pinned(EXEC_ADDR_ROOT_HEIGHT=real.cursor):
    at = B2.records_projection(real)
T.check("5d. the root commits the registry exactly from the gate: none of it one block below, every entry at it",
        not below and len(_reg) >= 3 and all(at.get(B2.record_key(B2.T_ADDR, d)) == B2.addr_value(a) for d, a in _reg.items()),
        (len(below), len(_reg)))
w6, c6 = game_pre()
w6.apply([w6.block([w6.call(c6, A, "open", [1], 10)])], w6.st)
with _harness.pinned(EXEC_ADDR_ROOT_HEIGHT=w6.h + 2):                    # the gate falls inside the span
    p6 = w6.st.clone()
    s6 = [w6.block([w6.call(c6, B, "join", [1], 10)]), w6.block([]), w6.block([])]
    try:
        S.prove_span(p6, s6, w6.chain_for(p6, s6), BIN)
        T.check("5c. a span that crosses the registry gate is unprovable", False, "it proved")
    except S.Unprovable as e:
        T.check("5c. a span that crosses the registry gate is unprovable", "crosses" in str(e), str(e))

# ---- 6: the shadow run (tools/settle_b2_shadow.py), end to end: stash files, an L1 over HTTP, the tool's verdicts --------
import http.server  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import urllib.parse  # noqa: E402

# under the protocol's own gate values: the tool runs in a subprocess, which sees no pin
w7, c7 = game_pre()
p7 = w7.st.clone()
s7 = [w7.block([w7.call(c7, A, "open", [3], 10), w7.call(c7, B, "join", [3], 10)])]
while (w7.h + 1) % EPOCH_LENGTH:
    s7.append(w7.block([]))
s7.append(w7.block([w7.call(c7, B, "resign", [3])]))           # an epoch boundary block, and a payout
mid = p7.clone()
w7.apply(s7, mid)
s7b = [w7.block([])]
end = mid.clone()
w7.apply(s7b, end)
sd = os.path.join(HOME, "shadow_state")
os.makedirs(sd)


def stash(st, label=None):
    c = st.cursor if label is None else label
    with open(os.path.join(sd, f"exec_state.json~stash~default~{c}.json"), "w") as f:
        json.dump({"ns": "default", "cursor": c, "state_root": st.state_root(), "state": st._snapshot()}, f)


stash(p7)
stash(mid)
stash(end, label=end.cursor - 1 + 2)            # a stash labeled with another cursor than its state's: must be skipped
blocks7 = {b["block_number"]: b for b in s7 + s7b}


class L1(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/get_block":
            body = blocks7.get(int(q["number"]), {})
        elif u.path == "/get_dividend_inflow":
            body = {"inflow": w7.accrual(int(q["epoch"]))[0]}
        elif u.path == "/get_open_weights":
            body = {"weights": w7.accrual(int(q["epoch"]))[1]}
        else:
            body = {"error": "no"}
        out = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), L1)
threading.Thread(target=srv.serve_forever, daemon=True).start()
outp = os.path.join(HOME, "shadow.jsonl")
env = dict(os.environ)
r = subprocess.run([sys.executable, os.path.join(_harness.ROOT, "tools", "settle_b2_shadow.py"), "--bin", BIN, "--out", outp,
                    "--state-dir", sd, "--l1", f"http://127.0.0.1:{srv.server_address[1]}"], capture_output=True, text=True,
                   timeout=1800, env=env)
srv.shutdown()
res = [json.loads(line) for line in open(outp)] if os.path.exists(outp) else []
by = {(x["from"], x["to"]): x for x in res}
first = by.get((p7.cursor, mid.cursor), {})
T.check("6a. the shadow run proves a real span between two stashes, on exactly the exec node's root (3 calls, an epoch "
        "boundary, a payout)", first.get("result") == "proven" and first.get("calls") == 3, (first, r.stderr[-1500:]))
T.check("6b. ...and skips a stash whose state is not at its own label, saying why",
        any(x.get("result") == "skipped" and "not at its own" in x.get("reason", "") for x in res), res)
r2 = subprocess.run([sys.executable, os.path.join(_harness.ROOT, "tools", "settle_b2_shadow.py"), "--bin", BIN, "--out", outp,
                     "--state-dir", sd, "--l1", "http://127.0.0.1:9"], capture_output=True, text=True, timeout=600, env=env)
T.check("6c. a rerun continues where the results file ends (nothing reproven, nothing fetched)",
        r2.returncode == 0 and len(open(outp).read().splitlines()) == len(res), (r2.returncode, r2.stderr[-500:]))

size = len(json.dumps({k: v for k, v in bundle.items() if k != "vm_proof"}))
print(f"TIME blocks={len(span)} runs={len(bundle['runs'])} steps={sum(r['n_steps'] for r in bundle['runs'])} "
      f"openings={len(bundle['openings'])} prove_s={prove_s:.1f} verify_s={verify_s:.2f} "
      f"witness_json_bytes={size} vm_proof_bytes={len(bundle['vm_proof']) // 2}")
T.done()

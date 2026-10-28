"""The BLAKE2s exec root commits every leaf the old root does, and its exits refuse forgeries.

execnode/exec_root_b2.py is the generation-29 exec root (Goldilocks retirement G2): exec_root.py's two halves with
BLAKE2s positions, exact-integer values and the compressed tree. So:
  1. PARITY: over a rich exec state (contracts with int, zero, huge and non-int storage; bridge, dividend, asset,
     allowance and all three withdrawal kinds; outbox/inbox messages; zero amounts), the projection is rewritten to
     LOGICAL descriptors (the position functions patched to return what they were called with) and compared with the
     old root's descriptors of the same state: the same facts, the same values, the same omissions. The old root went
     with execnode/exec_root.py in G9 slice 4, so its descriptors are FROZEN below (OLD_REC / OLD_KV, computed by
     exec_root.py at e70fa444): a fact the BLAKE2s root drops, or adds without saying so, still fails here;
  2. the root is a pure function: rebuilt from a shuffled state it is the same, and any one changed amount moves it;
  3. EXITS: a withdrawal, dividend, unshield and outbox message each verify against the settled root; and are refused
     with a wrong amount, nonce, address or message, a wrong KV half, another record's proof, an absence proof posed
     as membership, a proof against a different root, and malformed input (never raising);
  4. positions are domain-separated: a slot, code, meta, KVX and record position never coincide, and the cid's
     length prefix stops ("ab", slot) from reading as ("a", slot').

Run: python3 tests/test_the_blake2s_exec_root_commits_every_leaf_the_old_root_does.py
"""
import _harness
HOME = _harness.isolate("nado-test-exec-root-b2-")
import copy
import os
import random

import ast
from execnode import csmt, exec_root_b2 as R2
from execnode.state import ExecState

T = _harness.Report()
rnd = random.Random(29)
A = ["ndo" + c * 45 for c in "abcdefgh"]


def rich_state():
    st = ExecState(os.path.join(HOME, f"s{rnd.random()}.json"))
    st.cursor = 500
    st.bridge = {A[0]: 10**12, A[1]: 7, A[2]: 0}                      # a zero balance: absent in both
    st.dividend = {A[3]: 5 * 10**10, A[4]: 1}
    st.abal = {"aa" * 32: {A[0]: 100, A[1]: 0}}
    st.assets = {"aa" * 32: {"issuer": A[0], "seed": 1, "name": "Tok", "sym": "TK", "dec": 8, "supply": 10**9,
                             "mintable": False}}
    st.allow = {"aa" * 32: {A[0]: {A[2]: 50}}}
    st.withdrawals = {"n1": {"addr": A[5], "amount": 3 * 10**10}, "n2": {"addr": A[6], "amount": 0}}
    st.dividend_withdrawals = {"d1": {"addr": A[3], "amount": 10**9}}
    st.unshield_withdrawals = {"u1": {"addr": A[7], "amount": 42}}
    st.outbox = {1: {"seq": 1, "from": A[0], "to_ns": "default", "data": {"x": 1}}}
    st.inbox = [{"from_ns": "other", "seq": 3, "data": "hi"}]
    st.wd_nonce, st.dw_nonce, st.uw_nonce, st.outbox_seq = 7, 3, 0, 2      # uw zero: absent, like every zero record
    contracts = {
        "c" * 32: {"deployer": A[0], "code": {"m": [1, 2, 3]}, "runtime": "zkvm",
                   "storage": {"slots": {"1": 5, "2": 0, "3": (1 << 40), "4294967296": 77}}},
        "faucet": {"deployer": A[1], "code": {"r": [9]}, "upgradable": False,
                   "storage": {"slots": {"7": 1}, "names": {"x": "y"}}},           # a non-slots map: KVX in both
        "d" * 32: {"deployer": A[2], "code": None, "storage": {}},
    }
    return st, contracts


# ---- 1: parity, via logical descriptors
def descr_records(mod, st):
    saved = mod.record_key
    mod.record_key = lambda tag, *parts: ("rec", int(tag), tuple(str(p) for p in parts))
    try:
        return mod.records_projection(st)
    finally:
        mod.record_key = saved


# The old (Goldilocks) root's logical descriptors of rich_state(), zero values dropped as its tree dropped them — frozen
# from execnode/exec_root.py at e70fa444 when G9 slice 4 deleted it. Values are residues mod the Goldilocks P.
P_GOLDILOCKS = 2**64 - 2**32 + 1
OLD_REC = {ast.literal_eval(k): v for k, v in [["('rec', 1, ('ndoaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',))", 1000000000000], ["('rec', 1, ('ndobbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',))", 7], ["('rec', 10, ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'ndoaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'ndoccccccccccccccccccccccccccccccccccccccccccccc'))", 50], ["('rec', 2, ('ndoddddddddddddddddddddddddddddddddddddddddddddd',))", 50000000000], ["('rec', 2, ('ndoeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',))", 1], ["('rec', 3, ('ndofffffffffffffffffffffffffffffffffffffffffffff', 'n1'))", 30000000000], ["('rec', 4, ('ndoddddddddddddddddddddddddddddddddddddddddddddd', 'd1'))", 1000000000], ["('rec', 5, ('ndohhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh', 'u1'))", 42], ["('rec', 6, ('field_nfset', 'caeaaec45c69de5493ca19f3967f5706552b5840fa46f33a33681f97d0f72b37'))", 1], ["('rec', 6, ('field_root', '12068980620996700996'))", 1], ["('rec', 6, ('inbox', 'baffd786f2a4b4e2668a13de8530b0bec57d53c11da1e9e10ebbf1691773299e'))", 1], ["('rec', 6, ('outbox', 'c0aca98b9f8ec468ae75bd7b02fd79d99f83adbda04b5fc9f70f34c0d5fa402e'))", 1], ["('rec', 6, ('shield_nfset', 'a96aa2bd2e3510ee04e8cd838054a36328c80584160b3170b6fc242077f56d14'))", 1], ["('rec', 6, ('shield_root', '3494ed478a1577a5dad291006765ffcbf43096c44f1cec9121c302cf6b767f92'))", 1], ["('rec', 8, ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'ndoaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'))", 100], ["('rec', 9, ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '2433a894e380e08ee5a609d45713a26772a51f67b16f7df6578af40c467dc361'))", 1]]}
OLD_KV = {ast.literal_eval(k): ast.literal_eval(v) for k, v in [["('code', 'cccccccccccccccccccccccccccccccc')", "('codeval', \"{'m': [1, 2, 3]}\")"], ["('code', 'faucet')", "('codeval', \"{'r': [9]}\")"], ["('kvx', 'faucet', 'names', 'x', \"'y'\")", "1"], ["('meta', 'cccccccccccccccccccccccccccccccc')", "('metaval', ('ndoaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', True, 'zkvm'))"], ["('meta', 'dddddddddddddddddddddddddddddddd')", "('metaval', ('ndoccccccccccccccccccccccccccccccccccccccccccccc', True, 'zkvm'))"], ["('meta', 'faucet')", "('metaval', ('ndobbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', False, 'zkvm'))"], ["('slot', 'cccccccccccccccccccccccccccccccc', 1)", "5"], ["('slot', 'cccccccccccccccccccccccccccccccc', 3)", "1099511627776"], ["('slot', 'cccccccccccccccccccccccccccccccc', 4294967296)", "77"], ["('slot', 'faucet', 7)", "1"]]}


def descr_kv_new(contracts):
    saved = (R2.slot_key, R2.code_key, R2.meta_key, R2.kvx_key, R2.meta_value, R2.code_value)
    R2.slot_key = lambda cid, slot: ("slot", str(cid), int(slot))
    R2.code_key = lambda cid: ("code", str(cid))
    R2.meta_key = lambda cid: ("meta", str(cid))
    R2.kvx_key = lambda cid, m, k, v: ("kvx", str(cid), str(m), str(k), repr(v))
    R2.meta_value = lambda *a: ("metaval", a)
    R2.code_value = lambda code: ("codeval", repr(code))
    try:
        return R2.kv_projection(contracts)
    finally:
        (R2.slot_key, R2.code_key, R2.meta_key, R2.kvx_key, R2.meta_value, R2.code_value) = saved


def same_values(old, new):
    """old values are residues mod P (or 1 for digest records); new are exact 32-byte ints (or b'\\x01')"""
    bad = []
    for k in old:
        o, n = old[k], new.get(k)
        if isinstance(o, tuple):
            ok = o == n
        elif isinstance(n, bytes) and len(n) == 32:
            ok = int.from_bytes(n, "big") % P_GOLDILOCKS == o
        else:
            ok = (o == 1 and n == R2.ONE)
        if not ok:
            bad.append((k, o, n))
    return bad


st, contracts = rich_state()
o_rec, n_rec = dict(OLD_REC), descr_records(R2, st)
# the BLAKE2s root ALSO commits the nonce counters (T_COUNTER, G4) — the one deliberate addition; checked on its own
counters = {k: v for k, v in n_rec.items() if k[1] == R2.T_COUNTER}
T.check("1e. the BLAKE2s root commits the nonce counters, zero absent (the old root commits none)",
        {k[2][0]: int.from_bytes(v, "big") for k, v in counters.items()} == {"wd_nonce": 7, "dw_nonce": 3, "outbox_seq": 2}
        and not [k for k in o_rec if k[1] == R2.T_COUNTER], counters)
n_rec = {k: v for k, v in n_rec.items() if k[1] != R2.T_COUNTER}
# (the old tree dropped a zero VALUE at write time: OLD_REC was frozen with the zero leaves removed)
T.check("1a. records: the same facts in both roots", set(o_rec) == set(n_rec),
        (sorted(set(o_rec) - set(n_rec))[:3], sorted(set(n_rec) - set(o_rec))[:3]))
T.check("1b. records: the same values (exact here, the residue there)", not same_values(o_rec, n_rec),
        same_values(o_rec, n_rec)[:3])
o_kv = dict(OLD_KV)
n_kv = descr_kv_new(contracts)
T.check("1c. contract storage, code and meta: the same facts in both roots", set(o_kv) == set(n_kv),
        (sorted(map(str, set(o_kv) - set(n_kv)))[:3], sorted(map(str, set(n_kv) - set(o_kv)))[:3]))
T.check("1d. contract storage: the same values", not same_values(o_kv, n_kv), same_values(o_kv, n_kv)[:3])

# ---- 2: a pure function of the state
r0 = R2.state_root_hex(contracts, st)
st2, c2 = rich_state()
c2 = dict(reversed(list(c2.items())))
st2.bridge = dict(reversed(list(st2.bridge.items())))
T.check("2a. the root does not depend on insertion order", R2.state_root_hex(c2, st2) == r0)
st3, _ = rich_state(); st3.bridge[A[1]] = 8                       # an ExecState holds a lock: rebuild, never deepcopy
T.check("2b. one changed amount moves the root", R2.state_root_hex(contracts, st3) != r0)
c3 = copy.deepcopy(contracts); c3["c" * 32]["storage"]["slots"]["1"] = 6
T.check("2c. one changed slot moves the root", R2.state_root_hex(c3, st) != r0)

# ---- 3: exits
kv_tree = csmt.Tree(R2.kv_projection(contracts))
rec_tree = csmt.Tree(R2.records_projection(st))
settled = R2.full_root(kv_tree.root(), rec_tree.root()).hex()
T.check("3a. the incremental trees give the cold root", settled == r0)
wd = st.withdrawals["n1"]
pw = R2.record_proof(kv_tree.root(), rec_tree, R2.record_key(R2.T_BRIDGE_WD, wd["addr"], "n1"))
dv = st.dividend_withdrawals["d1"]
pd = R2.record_proof(kv_tree.root(), rec_tree, R2.record_key(R2.T_DIV_WD, dv["addr"], "d1"))
us = st.unshield_withdrawals["u1"]
pu = R2.record_proof(kv_tree.root(), rec_tree, R2.record_key(R2.T_UNSHIELD_WD, us["addr"], "u1"))
msg = st.outbox[1]
dg = R2.leaf_digest(R2.msg_outbox_leaf(msg))
pm = R2.record_proof(kv_tree.root(), rec_tree, R2.record_key(R2.T_DIGEST, "outbox", dg))
T.check("3b. a withdrawal exit verifies", R2.verify_withdrawal(settled, wd["addr"], wd["amount"], "n1", pw))
T.check("3c. a dividend exit verifies", R2.verify_dividend(settled, dv["addr"], dv["amount"], "d1", pd))
T.check("3d. an unshield exit verifies", R2.verify_unshield(settled, us["addr"], us["amount"], "u1", pu))
T.check("3e. an outbox message verifies",
        R2.verify_outbox_msg(settled, msg["seq"], msg["from"], msg["to_ns"], msg["data"], pm))
forged = {
    "a wrong amount": R2.verify_withdrawal(settled, wd["addr"], wd["amount"] + 1, "n1", pw),
    "a residue-equal amount (amount + P)": R2.verify_withdrawal(settled, wd["addr"], wd["amount"] + P_GOLDILOCKS, "n1", pw),
    "a wrong nonce": R2.verify_withdrawal(settled, wd["addr"], wd["amount"], "n9", pw),
    "a wrong address": R2.verify_withdrawal(settled, A[0], wd["amount"], "n1", pw),
    "the zero-amount withdrawal (absent)": R2.verify_withdrawal(settled, A[6], 0, "n2", pw),
    "another record's proof": R2.verify_withdrawal(settled, wd["addr"], wd["amount"], "n1", pd),
    "a wrong KV half": R2.verify_withdrawal(settled, wd["addr"], wd["amount"], "n1", {**pw, "kv": "00" * 32}),
    "a proof against a different root": R2.verify_withdrawal(R2.state_root_hex(contracts, st3), wd["addr"],
                                                               wd["amount"], "n1", pw),
    "an altered message": R2.verify_outbox_msg(settled, msg["seq"], msg["from"], msg["to_ns"], {"x": 2}, pm),
}
absent_key = R2.record_key(R2.T_BRIDGE_WD, A[0], "nope")
pa = R2.record_proof(kv_tree.root(), rec_tree, absent_key)
T.check("3f. an absence proof verifies as absence", R2.verify_record(settled, absent_key, None, pa))
forged["an absence proof posed as membership"] = R2.verify_record(settled, absent_key, R2.int_value(5), pa)
for name, got in forged.items():
    T.check(f"3. refused: {name}", got is False, got)
weird = []
for name, fn in (("proof None", lambda: R2.verify_record(settled, absent_key, None, None)),
                 ("bad hex", lambda: R2.verify_record(settled, absent_key, None, {**pa, "kv": "zz"})),
                 ("terminal junk", lambda: R2.verify_record(settled, absent_key, None, {**pa, "t": ["node"]})),
                 ("root not str", lambda: R2.verify_record(None, absent_key, None, pa))):
    try:
        if fn() is not False:
            weird.append(name)
    except Exception as e:
        weird.append(f"{name} raised {e!r}")
T.check("3. malformed exits return False, never raise", not weird, weird)

# ---- 4: domain separation
keys = [R2.slot_key("ab", 1), R2.code_key("ab"), R2.meta_key("ab"), R2.kvx_key("ab", "slots", "1", 1),
        R2.record_key(1, "ab"), R2.slot_key("a", int.from_bytes(b"b" + b"\x00" * 31, "big"))]
T.check("4. slot, code, meta, KVX and record positions never coincide; the cid is length-prefixed",
        len(set(keys)) == len(keys))
T.done("ALL PASS — the BLAKE2s exec root commits every leaf the old root does, and its exits refuse forgeries")

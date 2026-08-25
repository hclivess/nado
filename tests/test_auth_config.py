"""ACCOUNT AUTHENTICATION AS STATE — the core (ops/auth_ops.py, doc/key-rotation.md).

Pins: the policy language and its bounds; the implicit legacy config; effective_config as a pure function of
(doc, height) with a matured pending change authorizing WITHOUT a write; signature-entry verification against
a config; validate_auth_tx (install, rotate, partial -> pending, cancel by a reconfig-only key + freeze,
version/replay guard, proof of possession); and apply -> revert being BYTE-IDENTICAL on the account doc AND
on auth_history, through every branch (immediate, pending, cancel, supersede, prune).

Run: NADO_AUTH_FORCE=1 python3 tests/test_auth_config.py   (the env var activates the feature on this generation)
"""
import os, sys, tempfile, logging, traceback, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_auth_")
os.environ["NADO_AUTH_FORCE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("auth"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops
from ops import auth_ops as A
from ops.account_ops import create_account, get_account
from ops.transaction_ops import construct_auth_tx, auth_pop
from signatures import generate_keydict

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def raises(fn, frag=""):
    try:
        fn()
    except AssertionError as e:
        assert frag in str(e), f"wrong error: {e}"
        return
    raise AssertionError("expected an AssertionError")

HOT, REC, G1, G2 = [generate_keydict() for _ in range(4)]
ADDR = HOT["address"]
FEE = P.MIN_TX_FEE

def protected(v):
    return {"v": v, "keys": [HOT["public_key"], REC["public_key"]], "sign": ["ID", 0],
            "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}

def snapshot():
    return copy.deepcopy(get_account(ADDR) or {}), kv_ops.auth_history(ADDR)


# ---- 1. policy language ------------------------------------------------------------------------------
def t_policy():
    assert P.AUTH_ACTIVE, "test must run with NADO_AUTH_FORCE=1"
    ok = ["THRESHOLD", 1, [["ID", 0], ["THRESHOLD", 2, [["ID", 1], ["ID", 2]]]]]
    A.validate_policy(ok, 3)
    assert A.policy_satisfied(ok, {0}) and A.policy_satisfied(ok, {1, 2})
    assert not A.policy_satisfied(ok, {1}) and not A.policy_satisfied(ok, set())
    assert A.policy_keys(ok) == {0, 1, 2}
    raises(lambda: A.validate_policy(["ID", 3], 3), "out of range")
    raises(lambda: A.validate_policy(["THRESHOLD", 3, [["ID", 0]]], 1), "k must be within")
    raises(lambda: A.validate_policy(["THRESHOLD", 1, [["THRESHOLD", 1, [["THRESHOLD", 1, [["ID", 0]]]]]]], 1), "too deep")
    raises(lambda: A.validate_policy(["OR", 0], 1), "unknown")
    raises(lambda: A.validate_policy(["ID", True], 1))
    cfg = protected(1); A.validate_config(cfg)
    bad = protected(1); bad["keys"].append(G1["public_key"])
    raises(lambda: A.validate_config(bad), "must appear")                 # unreachable key refused
    bad = protected(1); bad["keys"][1] = bad["keys"][0]
    raises(lambda: A.validate_config(bad), "duplicate")
    bad = protected(0); raises(lambda: A.validate_config(bad), "version")
    bad = protected(1); bad["extra"] = 1; raises(lambda: A.validate_config(bad), "exactly")
    too_many = {"v": 1, "keys": [generate_keydict()["public_key"] for _ in range(5)], "sign": ["ID", 0],
                "reconf": ["THRESHOLD", 1, [["ID", i] for i in range(5)]]}
    raises(lambda: A.validate_config(too_many), "keys")


# ---- 2. implicit config + effective_config purity ----------------------------------------------------
def t_effective():
    create_account(ADDR, balance=10 * FEE)
    acc = get_account(ADDR)
    cfg = A.effective_config(ADDR, acc, 100)
    assert cfg["implicit"] and cfg["keys"] == [] and cfg["sign"] == ["ID", 0]
    assert A.signer_index(HOT["public_key"], ADDR, cfg) == 0, "the deriving key is authenticator 0 before any tx"
    assert A.signer_index(REC["public_key"], ADDR, cfg) is None
    kv_ops.account_set_field(ADDR, "public_key", HOT["public_key"])          # what PUBKEY-ONCE does on first tx
    cfg = A.effective_config(ADDR, get_account(ADDR), 100)
    assert cfg["keys"] == [HOT["public_key"]]
    pend = {"cfg": protected(1), "eff": 500, "txid": "x"}
    doc = dict(get_account(ADDR)); doc["auth_pending"] = pend
    assert A.effective_config(ADDR, doc, 499)["implicit"], "not yet effective"
    assert A.effective_config(ADDR, doc, 500) == protected(1), "matured pending authorizes with no write"
    assert A.effective_config(ADDR, doc, None)["implicit"], "no height -> installed/implicit, never pending"
    assert A.key_authorized(HOT["public_key"], ADDR, acc=get_account(ADDR))
    assert not A.key_authorized(REC["public_key"], ADDR, acc=get_account(ADDR))


# ---- 3. entries ------------------------------------------------------------------------------------
def t_entries():
    cfg = protected(1)
    tx = construct_auth_tx(ADDR, [HOT, REC], {"op": "cancel"}, FEE, 1000)
    assert A.verify_entries(tx, ADDR, cfg) == {0, 1}
    tx1 = construct_auth_tx(ADDR, [HOT], {"op": "cancel"}, FEE, 1000)
    assert A.verify_entries(tx1, ADDR, cfg) == {0}
    bad = construct_auth_tx(ADDR, [G1], {"op": "cancel"}, FEE, 1000)
    raises(lambda: A.verify_entries(bad, ADDR, cfg), "does not authorize")
    dup = construct_auth_tx(ADDR, [HOT, HOT], {"op": "cancel"}, FEE, 1000)
    raises(lambda: A.verify_entries(dup, ADDR, cfg), "duplicate")
    forged = copy.deepcopy(tx1); forged["signature"][0]["signature"] = "00" * 32
    raises(lambda: A.verify_entries(forged, ADDR, cfg), "invalid signature")
    # string form == one entry (the legacy wire shape)
    legacy = dict(tx1); legacy["public_key"] = HOT["public_key"]; legacy["signature"] = tx1["signature"][0]["signature"]
    assert A.verify_entries(legacy, ADDR, cfg) == {0}
    assert A.signer_indices(tx, ADDR, cfg) == {0, 1}


# ---- 4. install (legacy -> protected) is immediate; apply/revert exact -------------------------------
def t_install():
    before = snapshot()
    cfg = protected(1)
    data = {"op": "set", "cfg": cfg, "pop": {REC["public_key"]: auth_pop(ADDR, cfg, REC)}}
    tx = construct_auth_tx(ADDR, [HOT], data, FEE, 1000)
    signers = A.verify_entries(tx, ADDR, A.effective_config(ADDR, get_account(ADDR), 100))
    A.validate_auth_tx(tx, 100, signers)
    # proof of possession must cover exactly the new keys, and must verify
    d2 = copy.deepcopy(data); d2["pop"] = {}
    tx2 = construct_auth_tx(ADDR, [HOT], d2, FEE, 1000)
    raises(lambda: A.validate_auth_tx(tx2, 100, {0}), "pop must cover")
    d3 = copy.deepcopy(data); d3["pop"][REC["public_key"]] = auth_pop(ADDR, protected(2), REC)   # wrong statement
    tx3 = construct_auth_tx(ADDR, [HOT], d3, FEE, 1000)
    raises(lambda: A.validate_auth_tx(tx3, 100, {0}), "possession")
    with kv_ops.write_txn():
        A.apply_auth_tx(tx, 100, logger)
    acc = get_account(ADDR)
    assert acc["auth"] == cfg and "auth_pending" not in acc, "hot key alone satisfies the implicit reconfig -> immediate"
    assert kv_ops.auth_history(ADDR) == [(100, 1, A.key_digests(cfg["keys"]))]
    with kv_ops.write_txn():
        A.apply_auth_tx(tx, 100, logger, revert=True)
    assert snapshot() == before, "revert must restore the doc and history byte-identically"
    with kv_ops.write_txn():
        A.apply_auth_tx(tx, 100, logger)


# ---- 5. protected: hot alone -> pending; recovery cancels + freezes; hot+recovery immediate -----------
def t_protected_flows():
    acc = get_account(ADDR); assert acc["auth"] == protected(1)
    # a thief with the hot key tries to rotate to G1
    thief = {"v": 2, "keys": [G1["public_key"]], "sign": ["ID", 0], "reconf": ["ID", 0]}
    data = {"op": "set", "cfg": thief, "pop": {G1["public_key"]: auth_pop(ADDR, thief, G1)}}
    tx = construct_auth_tx(ADDR, [HOT], data, FEE, 1000)
    A.validate_auth_tx(tx, 200, {0})
    before = snapshot()
    with kv_ops.write_txn():
        A.apply_auth_tx(tx, 200, logger)
    acc = get_account(ADDR)
    assert acc["auth"] == protected(1) and acc["auth_pending"]["eff"] == 200 + P.AUTH_DELAY
    assert kv_ops.auth_history(ADDR)[-1] == (200 + P.AUTH_DELAY, 2, A.key_digests([G1["public_key"]]))
    # second pending refused; thief's key is not yet authorized; after eff it would be
    raises(lambda: A.validate_auth_tx(construct_auth_tx(ADDR, [HOT], data, FEE, 1000), 201, {0}), "already pending")
    assert not A.key_authorized(G1["public_key"], ADDR, height=201, acc=get_account(ADDR))
    assert A.key_authorized(G1["public_key"], ADDR, height=200 + P.AUTH_DELAY, acc=get_account(ADDR))
    # the recovery key alone cannot spend and cannot set, but CAN cancel — and that freezes
    cur = A.effective_config(ADDR, get_account(ADDR), 300)
    assert not A.policy_satisfied(cur["sign"], {1})
    raises(lambda: A.validate_auth_tx(construct_auth_tx(ADDR, [REC], data, FEE, 1000), 300, {1}), "needs the reconfig policy")
    cancel = construct_auth_tx(ADDR, [REC], {"op": "cancel"}, FEE, 1000)
    A.validate_auth_tx(cancel, 300, {1})
    mid = snapshot()
    with kv_ops.write_txn():
        A.apply_auth_tx(cancel, 300, logger)
    acc = get_account(ADDR)
    assert "auth_pending" not in acc and acc["auth_freeze"] == 300 + P.AUTH_FREEZE
    assert kv_ops.auth_history(ADDR) == [(100, 1, A.key_digests(protected(1)["keys"]))], "the pending row is gone with the cancel"
    # frozen: the hot key cannot pend again; the full policy still works and does not need the freeze to lift
    raises(lambda: A.validate_auth_tx(construct_auth_tx(ADDR, [HOT], data, FEE, 1000), 301, {0}), "frozen")
    rot = protected(2); rot["keys"][0] = G2["public_key"]                       # owner rotates the hot key
    data2 = {"op": "set", "cfg": rot, "pop": {G2["public_key"]: auth_pop(ADDR, rot, G2)}}
    full = construct_auth_tx(ADDR, [HOT, REC], data2, FEE, 1000)
    A.validate_auth_tx(full, 301, {0, 1})
    with kv_ops.write_txn():
        A.apply_auth_tx(full, 301, logger)
    acc = get_account(ADDR)
    assert acc["auth"] == rot and kv_ops.auth_history(ADDR)[-1] == (301, 2, A.key_digests(rot["keys"]))
    assert not A.key_authorized(HOT["public_key"], ADDR, height=302, acc=acc), "rotated-away key is revoked"
    assert A.key_authorized(G2["public_key"], ADDR, height=302, acc=acc)
    assert A.key_valid_at(HOT["public_key"], ADDR, 250) and not A.key_valid_at(HOT["public_key"], ADDR, 301), "evidence at height"
    # exact reverts back through every step
    with kv_ops.write_txn():
        A.apply_auth_tx(full, 301, logger, revert=True)
    assert snapshot()[0] == get_account(ADDR) and "auth_freeze" in get_account(ADDR)
    with kv_ops.write_txn():
        A.apply_auth_tx(cancel, 300, logger, revert=True)
    assert snapshot() == mid
    with kv_ops.write_txn():
        A.apply_auth_tx(tx, 200, logger, revert=True)
    assert snapshot() == before
    # replay guard: version must be current + 1
    stale = copy.deepcopy(data2); stale["cfg"]["v"] = 3
    raises(lambda: A.validate_auth_tx(construct_auth_tx(ADDR, [HOT, REC], stale, FEE, 1000), 400, {0, 1}), "version")


# ---- 6. a matured pending is superseded/materialised correctly; pruning journals ----------------------
def t_matured_and_prune():
    before = snapshot()
    thief = {"v": 2, "keys": [G1["public_key"]], "sign": ["ID", 0], "reconf": ["ID", 0]}
    data = {"op": "set", "cfg": thief, "pop": {G1["public_key"]: auth_pop(ADDR, thief, G1)}}
    tx = construct_auth_tx(ADDR, [HOT], data, FEE, 1000)
    with kv_ops.write_txn():
        A.apply_auth_tx(tx, 500, logger)
    eff = 500 + P.AUTH_DELAY
    # after eff the pending config IS live: cancel is refused, G1 acts, HOT is out
    raises(lambda: A.validate_auth_tx(construct_auth_tx(ADDR, [G1], {"op": "cancel"}, FEE, 1000), eff, {0}), "nothing pending")
    cur = A.effective_config(ADDR, get_account(ADDR), eff); assert cur == thief
    nxt = {"v": 3, "keys": [G2["public_key"]], "sign": ["ID", 0], "reconf": ["ID", 0]}
    d3 = {"op": "set", "cfg": nxt, "pop": {G2["public_key"]: auth_pop(ADDR, nxt, G2)}}
    t3 = construct_auth_tx(ADDR, [G1], d3, FEE, 1000)
    A.validate_auth_tx(t3, eff + 1, A.verify_entries(t3, ADDR, cur))
    with kv_ops.write_txn():
        A.apply_auth_tx(t3, eff + 1, logger)
    acc = get_account(ADDR)
    assert acc["auth"] == nxt and "auth_pending" not in acc, "matured pending materialised, then replaced"
    assert [r[1] for r in kv_ops.auth_history(ADDR)] == [1, 2, 3]
    with kv_ops.write_txn():
        A.apply_auth_tx(t3, eff + 1, logger, revert=True)
    acc = get_account(ADDR)
    assert acc["auth"] == protected(1) and acc["auth_pending"]["cfg"] == thief, "revert re-suspends the pending change"
    with kv_ops.write_txn():
        A.apply_auth_tx(tx, 500, logger, revert=True)
    assert snapshot() == before
    # prune: more than AUTH_HISTORY_KEEP rotations keep only the newest rows, and every prune reverts
    txs = []
    cur_cfg = protected(1); h = 600
    for n in range(P.AUTH_HISTORY_KEEP + 2):
        k = generate_keydict()
        cfg = {"v": cur_cfg["v"] + 1, "keys": [k["public_key"], REC["public_key"]], "sign": ["ID", 0],
               "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}
        signer = HOT if n == 0 else prev_k
        t = construct_auth_tx(ADDR, [signer, REC], {"op": "set", "cfg": cfg, "pop": {k["public_key"]: auth_pop(ADDR, cfg, k)}}, FEE, 1000)
        A.validate_auth_tx(t, h, A.verify_entries(t, ADDR, A.effective_config(ADDR, get_account(ADDR), h)))
        with kv_ops.write_txn():
            A.apply_auth_tx(t, h, logger)
        txs.append((t, h)); cur_cfg, prev_k, h = cfg, k, h + 1
    rows = kv_ops.auth_history(ADDR)
    assert len(rows) == P.AUTH_HISTORY_KEEP and rows[-1][1] == cur_cfg["v"], "bounded history keeps the newest"
    for t, hh in reversed(txs):
        with kv_ops.write_txn():
            A.apply_auth_tx(t, hh, logger, revert=True)
    assert snapshot() == before, "every prune was journaled and restored"


if __name__ == "__main__":
    check("policy language: ID/THRESHOLD, bounds, unreachable keys refused", t_policy)
    check("implicit config + effective_config is a pure function of (doc, height)", t_effective)
    check("signature entries verify against a config; legacy string form is one entry", t_entries)
    check("install from legacy is immediate; apply -> revert exact", t_install)
    check("protected: hot alone pends, recovery cancels + freezes, hot+recovery rotates now, evidence at height", t_protected_flows)
    check("matured pending materialises; supersede; bounded history prunes and reverts", t_matured_and_prune)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)

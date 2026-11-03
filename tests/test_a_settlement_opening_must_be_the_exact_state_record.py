"""A settlement witness opens each dict-valued entry as EXACTLY the state's record, or the verifier refuses it.

The leaf digests normalise what they hash (asset_meta_digest: int(supply), bool(mintable); _amount_leaf: int(amount)),
and an outbox leaf is positioned by its message's digest, not by its seq. So without an exactness check a prover can open
  - an asset with supply "5" (a str) or mintable 1, which still matches the tree, and then the replay runs on a value
    the chain never held (a burn raises inside the transition and its skip keeps the effects already applied);
  - a withdrawal with a str amount or an extra key;
  - outbox message 2 at message 1's position, which pops the wrong message.
Each forgery below MATCHES THE TREE (checked first, so the case is real) and is refused by settle_b2._canonical_opening;
the honest openings of the same tree pass. Real csmt trees and proofs, the real _verifier_store.

Run: python3 tests/test_a_settlement_opening_must_be_the_exact_state_record.py
"""
import os, sys, tempfile, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-settle-open-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import settle_b2 as S, csmt
from execnode import exec_root_b2 as B2

fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        fails.append(name)

A = "8989bff323ebf069dd441fb6b858226e4b9e64ecfae1fd2d24"
AID = "777"
META = {"issuer": A, "seed": 9, "name": "N", "sym": "N", "dec": 0, "supply": 5, "mintable": True, "uri": ""}
WD = {"addr": A, "amount": 1000}
M1 = {"seq": 1, "from": A, "to_ns": "other", "data": {"x": 1}}
M2 = {"seq": 2, "from": A, "to_ns": "other", "data": {"x": 2}}

leaves = {}
for fam, path, v in (("assets", (AID,), META), ("wd", ("1",), WD), ("outbox", ("1",), M1), ("outbox", ("2",), M2)):
    for k, b in S.FAMILIES[fam][1](path, v):
        leaves[k] = b
rec = csmt.Tree(leaves)
kv = csmt.Tree({})


def bundle(openings):
    # cursor 0: below protocol.EXEC_ASSET_ID_ROOT_HEIGHT, the S.FAMILIES table the leaves above were built with
    return {"cursor": 0, "kv_pre": kv.root().hex(), "rec_pre": rec.root().hex(),
            "proofs": {"kv": {}, "rec": {k.hex(): S._proof_json(rec.prove(k)) for k in leaves}},
            "openings": [[f, list(p), v] for f, p, v in openings]}


def verdict(openings):
    try:
        S._verifier_store(bundle(openings))
        return None
    except S.Refused as e:
        return str(e)


def matches_tree(fam, path, v):
    """the old check alone: does this opening's leaf sit in the tree?"""
    try:
        lv = S.FAMILIES[fam][1](tuple(path), v)
    except Exception:
        return False
    return bool(lv) and all(leaves.get(k) == b for k, b in lv)


HONEST = [("assets", (AID,), META), ("wd", ("1",), WD), ("outbox", ("1",), M1), ("outbox", ("2",), M2)]
check("the honest openings of the tree are accepted", verdict(HONEST) is None, verdict(HONEST))

FORGED = [
    ("an asset whose supply is a str", "assets", (AID,), dict(META, supply="5")),
    ("an asset whose mintable is 1, not True", "assets", (AID,), dict(META, mintable=1)),
    ("an asset whose dec is False, not 0", "assets", (AID,), dict(META, dec=False)),
    ("an asset with an extra key", "assets", (AID,), dict(META, extra=1)),
    ("a withdrawal whose amount is a str", "wd", ("1",), dict(WD, amount="1000")),
    ("a withdrawal with an extra key", "wd", ("1",), dict(WD, note="x")),
    ("outbox message 2 opened at message 1's position", "outbox", ("1",), M2),
]
for name, fam, path, v in FORGED:
    check(f"(the case is real) {name} still matches the tree", matches_tree(fam, path, v))
    ops = [o if (o[0], o[1]) != (fam, path) else (fam, path, v) for o in HONEST]
    if (fam, path, M2) == (fam, path, v):                          # M2 moved to M1's slot: drop its own opening
        ops = [o for o in ops if o[1] != ("2",)]
    why = verdict(ops)
    check(f"refused: {name}", why is not None and "exact" in why or (why or "").endswith("position"), why)

print("ALL PASS" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)

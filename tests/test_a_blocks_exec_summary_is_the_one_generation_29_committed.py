"""A BLOCK'S EXEC SUMMARY IS THE ONE GENERATION 29 COMMITTED — the call leaves and records-inert bit
(execnode/calls_commit.py) and the records effects and dividend accrual (execnode/records_effects.py) that
incorporate_block writes into the exec summaries in L1 `meta`, which feed the L1 state root.

G9 slice 4 moved both modules out of execnode/stark and cut away every Goldilocks part nothing on generation 29 runs.
This pins that what remains answers EXACTLY as the pre-slice code did, on fixtures that reach every branch the summary
has (each call field, string and wide args, every code event, a namespace, a poison value, native and asset value
calls, every derivable recipient, the fail-closed cases, a block 0 carrying an entry, the accrual's carry and floor
cases, epoch attribution). EXPECTED was computed by running the fixtures below against e70fa444 (execnode.stark.
calls_commit / records_bind); the chain replay of blocks 0..10533 proved the same on the live chain. A change here is a
change to the L1 state root: it rides a reroll or it forks the fleet.

Also carried over from the retired tests whose other subjects went with execnode/stark (test_calls_commit,
test_da_binding, test_exec_summary_binding): string args never kill a summary, block_calls carries committed data only,
and the records-inert bit is an allowlist that fails closed.

Run: python3 tests/test_a_blocks_exec_summary_is_the_one_generation_29_committed.py
"""
import copy
import json
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-exec-summary-g29-")      # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # ASSIGN: CWD-relative otherwise
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol
from execnode import calls_commit as CC, records_effects as RE, runtimes

import _harness
_report = _harness.Report()
check = _report.run


# ---- the fixtures (verbatim from the generator run against e70fa444) ----------------------------------------------

import base64
BUMP = {"bump": [[1, 1, 0], [13, 2, 1]]}
BUMP2 = {"bump": [[1, 1, 0], [13, 2, 2]]}
A = "ndoAAAA" + "A" * 41
B = "ndoBBBB" + "B" * 41


def tx(sender, recipient, data=None, amount=0, txid="t"):
    t = {"sender": sender, "recipient": recipient, "amount": amount, "txid": txid}
    if data is not None:
        t["data"] = data
    return t


def blocks():
    import zstandard
    codez = base64.b64encode(zstandard.ZstdCompressor(level=3).compress(json.dumps(BUMP2).encode())).decode()
    H = 4321
    kv = [tx(A, "blob", {"op": "call", "contract": "c1", "method": "m", "args": [1, "mldsa44deadbeef", 2 ** 200]}, txid="a"),
          tx(B, "blob", {"op": "deploy", "code": BUMP, "nonce": "n1"}, txid="b"),
          tx(A, "blob", {"op": "upgrade", "contract": "c1", "codez": codez}, txid="c"),
          tx(A, "blob", {"op": "lock", "contract": "c1"}, txid="d"),
          tx(A, "blob", {"op": "transfer_contract", "contract": "c1", "to": B}, txid="e"),
          tx(A, "blob", {"op": "call", "contract": "c2", "method": "x", "args": ["AS Roma\nDraw"], "ns": "other"}, txid="f"),
          tx(A, "blob", {"op": "deploy", "code": {"m": "not-a-list"}, "at": {"w": 1}, "upgradable": "no"}, txid="g"),
          tx(A, "blob", {"op": "call", "contract": "c1", "method": "m", "args": [[1, 2]], "value": "abc", "asset": "x"}, txid="h"),
          tx(A, B, None, amount=5, txid="i")]
    value = [tx(A, "blob", {"op": "call", "contract": "c3", "method": "pay", "args": [], "value": 7}, txid="v1"),
             tx(B, "blob", {"op": "call", "contract": "c4", "method": "pay", "args": [], "value": 9, "asset": "123"}, txid="v2")]
    recip = [tx(A, "bridge", None, amount=1000, txid="r1"), tx(B, "faucet", None, amount=50, txid="r2"),
             tx(A, "treasury_execute", {"spend": {"recipient": "faucet", "amount": 30}}, txid="r3"),
             tx(A, "treasury_execute", {"spend": {"recipient": B, "amount": 30}}, txid="r4")]
    out = {
        "kv": {"block_number": H, "block_timestamp": 99, "block_transactions": kv},
        "genesis": {"block_number": 0, "block_transactions": []},
        "zero_with_call": {"block_number": 0, "block_transactions": kv[:2]},
        "value_calls": {"block_number": H + 1, "block_transactions": value},
        "recipients": {"block_number": H + 2, "block_transactions": recip},
        "emit": {"block_number": H + 3, "block_transactions": [tx(A, "blob", {"op": "emit", "to_ns": "y"})]},
        "shield": {"block_number": H + 4, "block_transactions": [tx(A, "shield", {"x": 1}, amount=3)]},
        "bad_value": {"block_number": H + 5, "block_transactions": [tx(A, "blob", {"op": "call", "contract": "c", "method": "m", "value": "zz"})]},
        "odd_asset": {"block_number": H + 6, "block_transactions": [tx(A, "blob", {"op": "call", "contract": "c", "method": "m", "value": 4, "asset": "0123"})]},
        "undecodable": {"block_number": H + 7, "block_transactions": [tx(A, "blob", "not-a-dict")]},
        "bad_deposit": {"block_number": H + 8, "block_transactions": [tx(A, "bridge", None, amount=0)]},
    }
    return out


def run(cc, re_):
    res = {}
    for name, blk in blocks().items():
        inert, calls = cc.block_summary(blk)
        eff, der = re_.block_records_effects(blk)
        res[name] = {"inert": inert, "calls": {k: [str(x) for x in v] for k, v in calls.items()},
                     "effects": None if eff is None else [[t, list(p), d] for t, p, d in eff], "derivable": der}
    w = {B: 3, A: 1, "ndoC": 0}
    res["accrual"] = [[[[t, list(p), d] for t, p, d in e], c] for e, c in
                      (re_.dividend_accrual_effects(i, w, c0, 5) for i, c0 in ((1000, 0), (7, 10 ** 6), (0, 0), (5, 3)))]
    res["accrual_empty"] = [[[[t, list(p), d] for t, p, d in e], c] for e, c in (re_.dividend_accrual_effects(100, {}, 7, 0),)]
    res["due"] = [re_.epoch_accrual_due(h, L) for h, L in ((0, 60), (60, 60), (61, 60), (120, 60), (-60, 60), (60, 0), (45660, 60))]
    return res


EXPECTED = json.loads(r"""
{
 "accrual": [
  [
   [
    [
     2,
     [
      "ndoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
     ],
     200
    ],
    [
     2,
     [
      "ndoBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
     ],
     600
    ],
    [
     2,
     [
      "ndoC"
     ],
     200
    ]
   ],
   0
  ],
  [
   [
    [
     2,
     [
      "ndoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
     ],
     200001
    ],
    [
     2,
     [
      "ndoBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
     ],
     600004
    ],
    [
     2,
     [
      "ndoC"
     ],
     200001
    ]
   ],
   1
  ],
  [
   [],
   0
  ],
  [
   [
    [
     2,
     [
      "ndoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
     ],
     1
    ],
    [
     2,
     [
      "ndoBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
     ],
     4
    ],
    [
     2,
     [
      "ndoC"
     ],
     1
    ]
   ],
   2
  ]
 ],
 "accrual_empty": [
  [
   [],
   107
  ]
 ],
 "bad_deposit": {
  "calls": {},
  "derivable": false,
  "effects": null,
  "inert": false
 },
 "bad_value": {
  "calls": {
   "default": [
    "112762174827807692500273273997786584962416733031144207866583732472962891501371"
   ]
  },
  "derivable": false,
  "effects": null,
  "inert": true
 },
 "due": [
  null,
  0,
  null,
  1,
  null,
  null,
  760
 ],
 "emit": {
  "calls": {},
  "derivable": false,
  "effects": null,
  "inert": false
 },
 "genesis": {
  "calls": {},
  "derivable": true,
  "effects": [],
  "inert": true
 },
 "kv": {
  "calls": {
   "default": [
    "18833119139657324225317238740985208345784177578133673966866077189453191324149",
    "60291182327720819956758061540890652835771887175067790193672865411199418044321",
    "59158448321652107559128411332345856883667946181785953436658771245749374647199",
    "71948704216228564100770204819709857441624777981522107239598494861043140069778",
    "22406228758215745334034691170203125311662550873389822917621994176185162896192",
    "9945184476297232912252405483937271315043561459205428085633065589001376986834",
    "60306303471925439839714269871160477168112419310633828147700665862811391388777"
   ],
   "other": [
    "25109573177906480126182019061736364503447049950303294039971301489730256218312"
   ]
  },
  "derivable": false,
  "effects": null,
  "inert": true
 },
 "odd_asset": {
  "calls": {
   "default": [
    "50199300126637741715502328567832857294366683985359907052780985950607168598186"
   ]
  },
  "derivable": false,
  "effects": null,
  "inert": false
 },
 "recipients": {
  "calls": {},
  "derivable": true,
  "effects": [
   [
    1,
    [
     "ndoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    ],
    1000
   ],
   [
    1,
    [
     "faucet"
    ],
    50
   ],
   [
    1,
    [
     "faucet"
    ],
    30
   ]
  ],
  "inert": false
 },
 "shield": {
  "calls": {},
  "derivable": false,
  "effects": null,
  "inert": false
 },
 "undecodable": {
  "calls": {},
  "derivable": false,
  "effects": null,
  "inert": false
 },
 "value_calls": {
  "calls": {
   "default": [
    "15658730276344655017430514498209160210417705921226018182176972097225582887185",
    "81719553278270204663991065381827161435044075223881412871739699970276586337236"
   ]
  },
  "derivable": true,
  "effects": [
   [
    1,
    [
     "ndoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    ],
    -7
   ],
   [
    1,
    [
     "c3"
    ],
    7
   ],
   [
    8,
    [
     "123",
     "ndoBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    ],
    -9
   ],
   [
    8,
    [
     "123",
     "c4"
    ],
    9
   ]
  ],
  "inert": false
 },
 "zero_with_call": {
  "calls": {
   "default": [
    "1404006746375911435"
   ]
  },
  "derivable": true,
  "effects": [],
  "inert": true
 }
}
""")


def t_every_fixture_summarises_exactly_as_generation_29_committed():
    got = json.loads(json.dumps(run(CC, RE), sort_keys=True))
    bad = [k for k in EXPECTED if got.get(k) != EXPECTED[k]]
    assert not bad and set(got) == set(EXPECTED), f"differs at {bad}: " + "; ".join(f"{k}: {got.get(k)}" for k in bad)


def t_block_0_keeps_its_narrow_leaf_and_every_later_block_is_wide():
    """the one input where the two leaf forms meet: genesis carries no entry, but the function still answers block 0 the
    way it always did (one Goldilocks element) and every later height with the 256-bit digest"""
    z = EXPECTED["zero_with_call"]["calls"]["default"][0]
    assert int(z) < 2**64 and all(int(x) >= 2**64 for x in EXPECTED["kv"]["calls"]["default"])
    one = {"cid": "c", "method": "m", "args": [], "cursor": 0}
    assert CC.call_leaf(one) < 2**64 and CC.call_leaf(dict(one, cursor=1)) >= 2**64


# ---- carried over: string args never kill a summary (test_calls_commit) --------------------------------------------
def t_string_args_do_not_kill_the_summary():
    """REGRESSION: call_leaf did int() on every arg, so ONE call carrying a string arg raised — and because
    block_summary derives a whole block's leaves at once, that killed the summary for every call in the block (the bet
    oracle's fixture names, logged `exec summary for block N failed: invalid literal for int()` block after block).
    A string commits to the SAME leaf as its digested form, as the VM receives it."""
    base = {"cid": "c", "method": "m", "caller": "mldsa44abc", "value": 0, "cursor": 5, "timestamp": 9}
    addr = "mldsa44deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert CC.call_leaf({**base, "args": [addr]}) == CC.call_leaf({**base, "args": [runtimes.zkvm_addr_digest(addr)]})
    poison = "AS Roma vs Fiorentina\nAS Roma\nDraw\nFiorentina"
    CC.call_leaf({**base, "args": [1, poison, 2]})                      # must not raise
    blk = {"block_number": 7, "block_timestamp": 11, "block_transactions": [
        {"recipient": "blob", "sender": "s1", "data": {"op": "call", "contract": "c", "method": "ok", "args": [1, 2]}},
        {"recipient": "blob", "sender": "s2", "data": {"op": "call", "contract": "c", "method": "oracle", "args": [poison]}}]}
    _inert, calls = CC.block_summary(blk)
    assert len(calls.get("default") or []) == 2, calls


# ---- carried over: block_calls carries committed data only (test_da_binding) ----------------------------------------
def _blob(sender, cid, method, args, ns=None):
    d = {"op": "call", "contract": cid, "method": method, "args": args, "value": 0}
    if ns:
        d["ns"] = ns
    return {"recipient": "blob", "sender": sender, "data": d}


BLK1 = {"block_number": 100, "block_timestamp": 1700, "block_transactions": [
    _blob(A, "cid_dice", "bet", [3, 50]),
    {"recipient": "bond", "sender": B, "data": {}},                              # non-blob: ignored
    _blob(B, "cid_dice", "settle", [3]),
    _blob(A, "cid_other", "run", [7], ns="rollup2"),                             # another namespace
    {"recipient": "blob", "sender": A, "data": {"op": "deploy", "code": {}}}]}   # a code event rides the list


def t_block_calls_extracts_one_namespace_in_order_with_committed_context():
    entries = CC.block_calls(BLK1, "default")
    cs = [c for c in entries if c.get("op") is None]
    assert len(cs) == 2 and [e.get("op") for e in entries if e.get("op")] == ["deploy"]
    # the timestamp is chain_clock(cursor), a pure function of the height: block_timestamp is outside the block hash
    assert cs[0] == {"cid": "cid_dice", "method": "bet", "caller": A, "args": [3, 50], "value": 0, "asset": 0,
                     "cursor": 100, "timestamp": protocol.chain_clock(100)}
    assert cs[1]["method"] == "settle" and cs[1]["caller"] == B
    assert CC.block_calls(BLK1, "rollup2")[0]["cid"] == "cid_other"


def t_clock_skew_cannot_change_a_summary():
    skewed = copy.deepcopy(BLK1); skewed["block_timestamp"] += 1
    assert CC.block_calls(skewed, "default") == CC.block_calls(BLK1, "default")
    assert CC.block_summary(skewed) == CC.block_summary(BLK1)


# ---- carried over: the records-inert bit is an allowlist (test_exec_summary_binding) --------------------------------
def _inert(*txs):
    return CC.block_records_inert({"block_number": 10, "block_transactions": list(txs)})


def t_the_inert_bit_is_an_allowlist_that_fails_closed():
    for op in ("deploy", "lock", "upgrade", "transfer_contract"):
        assert _inert({"recipient": "blob", "sender": "a", "data": {"op": op}}), op
    assert _inert(_blob("a", "c", "m", [])), "a value-0 call is inert"
    assert _inert({"recipient": "ndoSomeone", "sender": "a", "amount": 5}), "a transfer touches no exec state"
    assert not _inert({"recipient": "blob", "sender": "a", "data": {"op": "call", "value": 1}}), "value escrow moves records"
    for op in ("emit", "bridge_withdraw", "collect_dividend", "field_transfer", "shielded_transfer", "brand_new"):
        assert not _inert({"recipient": "blob", "sender": "a", "data": {"op": op}}), op
    for r in ("bridge", "bridge_withdraw", "dividend", "dividend_withdraw", "shield", "unshield", "xmsg", "faucet",
              "treasury_execute"):
        assert not _inert({"recipient": r, "sender": "a"}), r
    assert not _inert({"recipient": "blob", "sender": "a", "data": "not-a-dict"}), "undecodable cannot be shown safe"


def t_nothing_imports_the_deleted_goldilocks_package():
    """execnode/stark is gone: a lazy import of it left anywhere would raise only on the path that reaches it"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # (a git-ignored __pycache__ may outlive the package on an updated node; only a source file would be importable)
    stark_dir = os.path.join(root, "execnode", "stark")
    left = [f for _r, _d, fs in os.walk(stark_dir) for f in fs if f.endswith(".py")] if os.path.isdir(stark_dir) else []
    assert not left, left
    hits = []
    for d in ("execnode", "ops", "loops", "tools", "scripts"):
        for r, _ds, fs in os.walk(os.path.join(root, d)):
            for f in fs:
                if f.endswith(".py"):
                    p = os.path.join(r, f)
                    s = open(p).read()
                    if "from execnode.stark" in s or "import execnode.stark" in s or "from execnode import stark" in s:
                        hits.append(os.path.relpath(p, root))
    for f in os.listdir(root):
        if f.endswith(".py") and "execnode.stark" in open(os.path.join(root, f)).read():
            hits.append(f)
    assert hits == ["tools/replay_exec.py"], hits      # replay_exec: only behind try/ImportError, to replay older trees


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)
print()
print("ALL PASS — a block's exec summary is the one generation 29 committed" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)

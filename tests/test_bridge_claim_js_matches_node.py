"""A cash-out finishes: the wallet's L1 claim, built by the wallet's own code, is the tx L1 accepts.

WHY THIS EXISTS. A cash-out (blob op bridge_withdraw, from the wallet or any game) only debits the playable balance and
records a withdrawal on the exec layer; the coins reach L1 when a SECOND, L1 `bridge_withdraw` tx proves that record
against a settled exec root. Nothing in the product ever built that tx — four cash-outs (10.06 NADO) sat debited and
unpaid on 2026-10-10 while the dialog promised they "land automatically". The wallet now claims each one
(static/interface.js "CASH-OUT CLAIM"), and this pins every hop of that journey offline:

  exec record -> /exec/withdrawals (execnode.h_withdrawals) lists it with a proof against the SETTLED root
              -> the wallet's buildBridgeClaimTx (lifted from interface.js, run in node with the wallet's crypto)
              -> its txid is the one construct_bridge_withdraw_tx produces from the same inputs (+ min_block)
              -> L1 validate_transaction accepts it, applying it pays the user from escrow
              -> a second copy is refused (nullifier), and once the exec tail drops the claimed record the
                 endpoint stops listing it (the wallet's "received" signal).

Also pinned: a record newer than the settled root is listed WITHOUT a proof (the wallet waits rather than submitting a
claim L1 would refuse); another address's records are never listed; an address with nothing pending costs no L1 read;
amounts are strings (a JSON number past 2^53 would round and the proof would no longer match).

Run: python3 tests/test_bridge_claim_js_matches_node.py   (needs node)
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-bridgeclaim-")     # ASSIGN, never setdefault (CLAUDE.md rule 4)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # execnode resolves these from CWD
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio
import json
import logging
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.join(os.environ["HOME"], "nado", _d), exist_ok=True)

logger = logging.getLogger("bridgeclaim"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers                                    # noqa: E402
create_indexers()

from protocol import B_MIN, MIN_TX_FEE, BRIDGE_ESCROW, CHAIN_ID         # noqa: E402
from ops.account_ops import create_account, get_account, reflect_transaction   # noqa: E402
from ops import transaction_ops as TO                                   # noqa: E402
from ops.transaction_ops import (validate_transaction, construct_settle_tx, construct_bridge_deposit_tx,   # noqa: E402
                                 construct_bridge_withdraw_tx, create_txid)
from ops.settlement_ops import latest_settled                           # noqa: E402
from ops.key_ops import generate_keys                                   # noqa: E402
from signatures import verify, unhex                                    # noqa: E402
from aiohttp.test_utils import make_mocked_request                      # noqa: E402
from execnode import execnode as EN                                     # noqa: E402
from execnode.state import ExecState                                    # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def _bal(a):
    return (get_account(a) or {}).get("balance", 0)


# the wallet's own code: canonical encoder + txid + signer + the CASH-OUT CLAIM block, lifted from interface.js and run
# with the wallet's vendored crypto bundle — an edit to the wallet is what gets tested, not a copy of it here
NODE_RUNNER = r"""
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
const nc = await import(%(crypto)s);
const js = readFileSync(%(iface)s, "utf8");
const cut = (a, b) => { const i = js.indexOf(a), j = js.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error("slice not found: " + a); return js.slice(i, j); };
const src = cut("function jsonEscapeAscii(", "function blake2bHashLink(")
  + cut("function randNonce(", "// REGISTER is by definition")
  + cut("/* ==== CASH-OUT CLAIM", "/* ==== end CASH-OUT CLAIM ==== */");
let raw = ""; process.stdin.on("data", (c) => raw += c); process.stdin.on("end", () => {
  const req = JSON.parse(raw);
  const w = new Function("env", `with (env) { ${src}\n return { buildBridgeClaimTx, canonicalize }; }`)({
    blake2b: nc.blake2b, bytesToHex: nc.bytesToHex, hexToBytes: nc.hexToBytes, ml_dsa44: nc.ml_dsa44, TextEncoder,
    crypto: webcrypto, CHAIN_ID: req.chain_id, TX_INCLUSION_DELAY: 8 });
  const c = req.claim;
  const tx = w.buildBridgeClaimTx(c.wallet, c.addr, c.amount, c.nonce, c.proof, c.target, c.ts, c.min_block);
  process.stdout.write(w.canonicalize(tx));
});
"""


def js_claim(claim):
    runner = os.path.join(os.environ["HOME"], "claim_runner.mjs")
    with open(runner, "w") as f:
        f.write(NODE_RUNNER % {"crypto": json.dumps("file://" + os.path.join(ROOT, "static", "vendor", "nado-crypto.js")),
                               "iface": json.dumps(os.path.join(ROOT, "static", "interface.js"))})
    out = subprocess.run(["node", runner], input=json.dumps({"chain_id": CHAIN_ID, "claim": claim}),
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-800:])
    return json.loads(out.stdout)


def call(handler, url):
    resp = asyncio.run(handler(make_mocked_request("GET", url)))
    return resp.status, json.loads(resp.body)


def main():
    V = generate_keys(); create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)   # bonded validator (4/4 > 2/3)
    U = generate_keys(); create_account(U["address"], balance=2_000_000)                 # the player cashing out
    O = generate_keys()                                                                   # someone else
    D, W, LATE = 900_000, 300_000, 50_000

    # L1 deposit escrows D (the cash-out can only be paid from what was bridged in)
    dep = construct_bridge_deposit_tx(U, D, max_block=1, fee=MIN_TX_FEE)
    validate_transaction(dep, logger, 1); reflect_transaction(dep, logger, 1)

    # exec side: the player's cash-out (nonce 1) and someone else's (nonce 2), then the root settles on L1
    st = ExecState(os.path.join(os.environ["HOME"], "s.json"))
    st.credit_deposit(U["address"], D); st.credit_deposit(O["address"], 10_000)
    st.apply_blob({"op": "bridge_withdraw", "amount": W}, sender=U["address"], txid="wd1")
    st.apply_blob({"op": "bridge_withdraw", "amount": 7_000}, sender=O["address"], txid="wd2")
    root = st.state_root()
    st.note_root_point()                         # the finalized tail remembers each root it applied
    reflect_transaction(construct_settle_tx(V, exec_cursor=7, state_root=root, max_block=1), logger, 1)
    check("the exec root is L1's settled root", latest_settled()[1] == root)
    # a later cash-out the settled root does NOT cover yet
    st.apply_blob({"op": "bridge_withdraw", "amount": LATE}, sender=U["address"], txid="wd3")
    check("the later cash-out moved the live root past the settled one", st.state_root() != root)

    EN.states["default"] = st
    EN.state = st
    hint_calls = []

    async def _hint(ns="default"):
        hint_calls.append(ns)
        return 7, root
    EN._settled_root_hint = _hint                # L1's justified root, as the poll loop would have cached it

    s400, _ = call(EN.h_withdrawals, "/exec/withdrawals")
    check("no address is a 400", s400 == 400, s400)
    s, nobody = call(EN.h_withdrawals, "/exec/withdrawals?address=" + V["address"])
    check("an address with nothing pending gets an empty list", s == 200 and nobody["pending"] == [], nobody)
    check("... and costs no L1 read", hint_calls == [], hint_calls)

    s, mine = call(EN.h_withdrawals, "/exec/withdrawals?address=" + U["address"])
    nonces = [p["nonce"] for p in mine["pending"]]
    check("lists exactly this address's cash-outs, in nonce order", s == 200 and nonces == ["1", "3"], mine["pending"])
    check("amounts are strings (exact past 2^53)",
          [p["amount"] for p in mine["pending"]] == [str(W), str(LATE)], [p["amount"] for p in mine["pending"]])
    first, late = mine["pending"]
    check("the settled cash-out carries a proof against the SETTLED root", first.get("state_root") == root and
          isinstance(first.get("proof"), dict), first.keys())
    check("the cash-out newer than the settled root has NO proof (the wallet waits)", "proof" not in late, late.keys())
    check("the settle cadence and cursors ride along for the wallet's ETA",
          mine["settled_root"] == root and mine["settled_cursor"] == 7 and mine["settle_every"] == EN.SETTLE_EVERY
          and mine["cursor"] == st.cursor, {k: mine[k] for k in ("settled_cursor", "settle_every", "cursor")})
    s, theirs = call(EN.h_withdrawals, "/exec/withdrawals?address=" + O["address"])
    check("another address sees only its own", [p["nonce"] for p in theirs["pending"]] == ["2"], theirs["pending"])
    s, pinned = call(EN.h_withdrawals, "/exec/withdrawals?address=" + U["address"] + "&root=" + root)
    check("?root= builds the same proof", pinned["pending"][0].get("proof") == first["proof"])

    if not shutil.which("node"):
        print("SKIP  node not installed: the wallet half was not run")
        return
    # the WALLET builds the claim from exactly what the endpoint served (JSON round trip, as the browser sees it)
    served = json.loads(json.dumps(first))
    TS, TARGET, MINB = 1_760_000_000, 301, 9
    claim = {"wallet": {"address": U["address"], "publicKey": U["public_key"], "privateKey": U["private_key"]},
             "addr": U["address"], "amount": served["amount"], "nonce": served["nonce"], "proof": served["proof"],
             "target": TARGET, "ts": TS, "min_block": MINB}
    tx = js_claim(claim)
    # the node's builder from the same inputs: pin its clock + nonce to the wallet's, add the wallet's min_block
    TO.get_timestamp_seconds, TO.create_nonce = (lambda: TS), (lambda: tx["nonce"])
    ref = construct_bridge_withdraw_tx(U, U["address"], W, "1", served["proof"], max_block=TARGET)
    ref["min_block"] = MINB
    ref.pop("signature"); ref["txid"] = create_txid({k: v for k, v in ref.items() if k != "txid"})
    shape = {k: v for k, v in tx.items() if k not in ("signature",)}
    check("the wallet's claim is construct_bridge_withdraw_tx field for field (+ min_block)", shape == ref,
          {k: (shape.get(k), ref.get(k)) for k in set(shape) | set(ref) if shape.get(k) != ref.get(k)})
    check("its txid is the node's txid", tx["txid"] == create_txid({k: v for k, v in tx.items() if k not in ("txid", "signature")}))
    check("data.amount is an int on the wire", type(tx["data"]["amount"]) is int, type(tx["data"]["amount"]))
    check("fee-exempt, zero L1 amount, self-claimed", tx["fee"] == 0 and tx["amount"] == 0 and
          tx["sender"] == tx["data"]["addr"] == U["address"])
    check("the signature verifies over the txid", verify(signed=tx["signature"], public_key=U["public_key"],
                                                         message=unhex(tx["txid"])))

    # L1 accepts it and pays the player from escrow
    ok = not raises(lambda: validate_transaction(tx, logger, 10))
    check("L1 validate_transaction accepts the wallet-built claim", ok)
    if ok:
        u0, e0 = _bal(U["address"]), _bal(BRIDGE_ESCROW)
        reflect_transaction(tx, logger, 10)
        check("applying it pays the player the cash-out", _bal(U["address"]) == u0 + W, (_bal(U["address"]), u0))
        check("... out of the bridge escrow", _bal(BRIDGE_ESCROW) == e0 - W, (_bal(BRIDGE_ESCROW), e0))
        again = js_claim(claim)
        check("a second claim of the same cash-out is refused", raises(lambda: validate_transaction(again, logger, 11)))
    # a claim whose amount was tampered with fails the proof
    bad = js_claim(dict(claim, amount=str(W + 1)))
    check("a claim for a different amount is refused", raises(lambda: validate_transaction(bad, logger, 11)))

    # the exec tail drops a record whose claim FINALIZED on L1 (state.drop_claimed) — the endpoint stops listing it,
    # which is the only signal the wallet and the SDK treat as "received"
    st.drop_claimed("bridge_withdraw", "1")
    s, after = call(EN.h_withdrawals, "/exec/withdrawals?address=" + U["address"])
    check("a claimed cash-out disappears from the list", [p["nonce"] for p in after["pending"]] == ["3"], after["pending"])


if __name__ == "__main__":
    main()
    print(f"\n{'ALL PASSED' if not _fails else str(len(_fails)) + ' FAILED'}")
    sys.exit(1 if _fails else 0)

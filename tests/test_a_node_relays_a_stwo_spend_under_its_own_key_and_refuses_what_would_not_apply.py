"""A node relays a wallet's private Stwo spend under ITS OWN key, and refuses — before spending anything — every spend
that would not pay it or would not apply (ops/stwo_relay.py, POST /stwo/relay, GET /stwo/relay_info).

Why the relay exists: tests/test_a_stwo_spend_is_not_published_under_the_spenders_own_account.mjs (the wallet used to
sign the blob carrying a spend with the spender's account, tying every nullifier to it). The relay is driven here
over HTTP — the real aiohttp handlers (make_handlers, as nado.py routes them) on a local test server — with REAL
proofs from the shipped wallet WASM, the REAL native verifier, and a real ExecState behind the exec node's own
/exec/stwo_spendable and /exec/field_shielded handlers. Pins:
  1. /stwo/relay_info: available, this node's address, the fee; an opted-out node ("stwo_relay": false) says it is
     not available and refuses to relay;
  2. refused, nothing submitted, nothing published to DA: a proof binding ANOTHER withdraw_addr; a proof paying the
     relay LESS than its fee; a proof whose public input was altered (forged) and one with a flipped proof byte;
     a malformed body;
  3. the honest spend is published: the blob tx is signed by the NODE key (sender, public_key and a verifying
     signature over the recomputed txid), carries only the DA commitment, and the DA bytes are the bundle;
  4. it applies end to end: the exec layer resolves the DA bytes and applies them — nullifier spent, the relay's fee
     recorded as an exit to the node's address;
  5. the same spend again while in flight is refused (409) without a second submit; after the hold, the exec view
     refuses it as spent; a full in-flight set refuses (429); the per-IP rate limit answers 429.
SKIPs without node or a stable cargo (the verifier).

Run: python3 tests/test_a_node_relays_a_stwo_spend_under_its_own_key_and_refuses_what_would_not_apply.py
"""
import os, sys, tempfile, json, secrets, shutil, hashlib, asyncio, copy
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-relay-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests._stwo_js_build import Env, wallet_prove

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


if not shutil.which("node"):
    print("SKIP  no node"); sys.exit(0)
env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo: the verifier cannot be built here"); sys.exit(0)
so, _s, log = env.build_verifier()
if not so:
    print("FAIL  verifier build", (log or "")[-800:]); sys.exit(1)
os.environ["NADO_STWO_JS_LIB"] = so

import protocol as P
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from execnode.state import ExecState
from execnode import shielded_stwo as SP
import execnode.execnode as EN
from ops.key_ops import generate_keys
from ops.address_ops import make_address
from ops.transaction_ops import create_txid
from signatures import verify as sig_verify, unhex
import ops.stwo_relay as R

GATE = 1000
P.STWO_POOL_HEIGHT = GATE
node = generate_keys()                       # a throwaway NODE key for this test (a node signs with its own key)
OTHER = make_address("ef" * 1312)
FEE = R.STWO_RELAY_FEE_RAW

# ---- the exec layer: deposits at the gate, the wallet's two notes among them ----------------------------------------
nsk = secrets.token_hex(32)
me = SP.owner_of(nsk)
st = ExecState(os.path.join(_T, "s.json"))
st.cursor = GATE - 1
notes = []
for i in range(3):
    st.apply_field_shield(5000 + i, SP.owner_of(secrets.token_hex(32)), 900 + i)
for v in (10 ** 9, 2 * 10 ** 9):
    rho = secrets.randbits(64)
    st.apply_field_shield(v, me, rho)
    notes.append((v, rho))
EN.state = st


def exec_get(path):
    """This host's exec node, answered by the exec node's own handlers over the live ExecState."""
    from urllib.parse import urlsplit, parse_qsl
    u = urlsplit(path)
    h = {"/exec/stwo_spendable": EN.h_stwo_spendable, "/exec/field_shielded": EN.h_field_shielded}.get(u.path)
    if h is None:
        return None

    class _Req:
        query = dict(parse_qsl(u.query))
    return json.loads(asyncio.run(h(_Req())).body)


DA, SUBMITTED = {}, []


def da_publish(b):
    c = hashlib.sha256(b).hexdigest()
    DA[c] = b
    return c


def submit(tx):
    SUBMITTED.append(tx)
    return {"result": True, "message": "Success"}


def make_relay(**kw):
    a = dict(keydict_fn=lambda: node, tip_fn=lambda: GATE + 5, exec_get=exec_get, da_publish=da_publish, submit=submit,
             allow=lambda *_: True)
    a.update(kw)
    return R.StwoRelay(**a)


def prove(note_i, unshield, dest, fee=0):
    v, rho = notes[note_i]
    leaves = list(st.stwo_pool.commitments)
    spend = {"nsk": nsk, "vIn": str(v), "rho": str(rho), "v1": str(v - unshield - fee), "o1": me,
             "r1": str(secrets.randbits(64)), "v2": "0", "o2": me, "r2": str(secrets.randbits(64)),
             "unshield": str(unshield), "fee": str(fee), "dest": dest}
    return wallet_prove(spend, leaves, leaves.index(SP.commit(v, me, rho)))["bundle"]


async def drive(relay, calls):
    """POST/GET against the real handlers on a local server; calls = [(method, path, body)] -> [(status, json)]."""
    info_h, post_h = R.make_handlers(relay, lambda r: r.remote)
    app = web.Application(client_max_size=R.STWO_RELAY_MAX_BODY)
    app.add_routes([web.get("/stwo/relay_info", info_h), web.post("/stwo/relay", post_h)])
    out = []
    async with TestClient(TestServer(app)) as c:
        for m, p, b in calls:
            r = await (c.get(p) if m == "GET" else c.post(p, data=b if isinstance(b, (bytes, str)) else json.dumps(b),
                                                          headers={"Content-Type": "application/json"}))
            out.append((r.status, await r.json()))
    return out


def one(relay, m, p, b=None):
    return asyncio.run(drive(relay, [(m, p, b)]))[0]


relay = make_relay()
s, info = one(relay, "GET", "/stwo/relay_info")
check("1. relay_info: available, with this node's address and the fee",
      s == 200 and info.get("available") is True and info.get("address") == node["address"] and info.get("fee") == FEE, info)
off = make_relay(enabled_fn=lambda: False)
s, info = one(off, "GET", "/stwo/relay_info")
check("...an opted-out node says it does not relay", info.get("available") is False and "does not relay" in info["reason"], info)

print("      proving (shipped wallet WASM, ~20 s each)…")
honest = prove(0, FEE, node["address"])
wrong_dest = prove(1, FEE, OTHER)
low_fee = prove(1, FEE - 1, node["address"])

# a node that cannot pay the blob's L1 fee (loopback walk 2026-10-12: it advertised itself, wrote the proof to DA and only
# then had its own tx refused) says so in relay_info and refuses BEFORE publishing anything
broke = make_relay(balance_fn=lambda: 0)
s, info = one(broke, "GET", "/stwo/relay_info")
check("...a node that cannot pay the L1 fee says it is unavailable", info.get("available") is False
      and "cannot pay" in info["reason"], info)
n_da, n_sub = len(DA), len(SUBMITTED)
s, r = one(broke, "POST", "/stwo/relay", {"bundle": honest})
check("...and refuses a spend before publishing or submitting anything", s == 503 and len(DA) == n_da
      and len(SUBMITTED) == n_sub, (s, r))
check("...an unknown balance (no reader, or a read error) does not block", make_relay(balance_fn=None)._can_pay()
      and make_relay(balance_fn=lambda: 1 / 0)._can_pay())

s, r = one(off, "POST", "/stwo/relay", {"bundle": honest})
check("...and refuses to relay", s == 503 and not SUBMITTED, (s, r))

base = (len(SUBMITTED), len(DA))
s, r = one(relay, "POST", "/stwo/relay", {"bundle": wrong_dest})
check("2. a proof binding ANOTHER withdraw_addr is refused", s == 400 and "does not pay this relay" in r["reason"], (s, r))
s, r = one(relay, "POST", "/stwo/relay", {"bundle": low_fee})
check("...a proof paying the relay less than its fee is refused", s == 400 and "relay fee" in r["reason"], (s, r))
forged = copy.deepcopy(honest)
forged["stark"]["stwo_js"]["cm_out1"] = SP.commit(1, me, 1)          # a public input the proof does not bind
s, r = one(relay, "POST", "/stwo/relay", {"bundle": forged})
check("...a forged public input is refused by the verifier", s == 400 and "does not verify" in r["reason"], (s, r))
flipped = copy.deepcopy(honest)
p = flipped["stark"]["stwo_js"]["proof"]
i = len(p) // 2
flipped["stark"]["stwo_js"]["proof"] = p[:i] + ("0" if p[i] != "0" else "1") + p[i + 1:]
s, r = one(relay, "POST", "/stwo/relay", {"bundle": flipped})
check("...a proof with a flipped byte is refused", s == 400, (s, r))
s, r = one(relay, "POST", "/stwo/relay", b"{not json")
check("...a malformed body is refused", s == 400, (s, r))
s, r = one(relay, "POST", "/stwo/relay", {"bundle": {"stark": {"stwo_js": {"nf": "AB" * 32}}}})
check("...a bundle the exec layer would not read is refused", s == 400, (s, r))
check("...and none of them submitted a transaction or published to DA", (len(SUBMITTED), len(DA)) == base,
      (len(SUBMITTED), len(DA)))
check("...nor left a nullifier held in flight (a retry elsewhere is free)", not relay.inflight, relay.inflight)

s, r = one(relay, "POST", "/stwo/relay", {"bundle": honest})
check("3. the honest spend is relayed", s == 200 and r.get("ok") and len(SUBMITTED) == 1, (s, r))
tx = SUBMITTED[-1] if SUBMITTED else {}
body = {k: v for k, v in tx.items() if k not in ("signature", "txid")}
check("...its transaction is the NODE's: sender and public key are the node's",
      tx.get("sender") == node["address"] and tx.get("public_key") == node["public_key"], tx.get("sender"))
check("...the signature verifies against the node key over the recomputed txid",
      create_txid(body) == tx.get("txid") and sig_verify(tx.get("signature"), node["public_key"], unhex(tx["txid"])))
check("...it is a field_transfer blob carrying only the DA commitment",
      tx.get("recipient") == "blob" and tx.get("data") == {"op": "field_transfer", "proof_da": r.get("commitment")}
      and tx.get("fee") == P.MIN_TX_FEE, tx.get("data"))
check("...and the DA bytes are the bundle", json.loads(DA[r["commitment"]]) == honest)

v0 = st.pool_value
res = st.apply_field_transfer(json.loads(DA[tx["data"]["proof_da"]]))     # what an exec node does with the blob
uw = list(st.unshield_withdrawals.values())
check("4. it applies end to end: the exec layer resolves the DA bytes and applies the spend",
      "field-transfer stwo" in res and st.stwo_pool.has_nullifier(honest["stark"]["stwo_js"]["nf"]), res)
check("...paying the relay its fee as an exit to the node's address",
      uw and uw[-1] == {"addr": node["address"], "amount": FEE} and v0 - st.pool_value == FEE, uw)

n = len(SUBMITTED)
s, r = one(relay, "POST", "/stwo/relay", {"bundle": honest})
check("5. the same spend again while in flight is refused without a second submit",
      s == 409 and "already being published" in r["reason"] and len(SUBMITTED) == n, (s, r))
later = make_relay()                                    # a fresh relay (restart, or after the hold expired)
s, r = one(later, "POST", "/stwo/relay", {"bundle": honest})
check("...after the hold, the exec view refuses it as spent", s == 409 and "double-spend" in r["reason"]
      and len(SUBMITTED) == n, (s, r))
busy = make_relay()
busy.inflight = {secrets.token_hex(32): 10 ** 12 for _ in range(R.STWO_RELAY_INFLIGHT_MAX)}
s, r = one(busy, "POST", "/stwo/relay", {"bundle": wrong_dest | {"withdraw_addr": node["address"]}})
check("...a full in-flight set refuses (429)", s == 429 and "busy" in r["reason"], (s, r))
from ops.ratelimit import allow
limited = make_relay(allow=allow)
codes = [st_ for st_, _ in asyncio.run(drive(limited, [("POST", "/stwo/relay", {"bundle": {}})] * (R.STWO_RELAY_PER_IP + 1)))]
check("...and the per-IP rate limit answers 429", codes[-1] == 429 and all(c == 400 for c in codes[:-1]), codes)

NADO = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nado.py")).read()
check("6. nado.py routes both endpoints to these handlers",
      'web.get("/stwo/relay_info", stwo_relay_info)' in NADO and 'web.post("/stwo/relay", stwo_relay_post)' in NADO)
check("...ON BY DEFAULT on every node: the default is in the code, opt-out only by an explicit false",
      'get_config().get("stwo_relay", True) is not False' in NADO)
check("...signing with the node's own keydict and refusing while the node is in emergency mode",
      "keydict_fn=lambda: memserver.keydict" in NADO and "emergency_mode" in NADO[NADO.index("_stwo_relay = StwoRelay("):])
check("...and the relay route has a body cap that fits a proof bundle",
      '"/stwo/relay": STWO_RELAY_MAX_BODY' in NADO and len(json.dumps({"bundle": honest})) < R.STWO_RELAY_MAX_BODY)

print("ALL PASS — a node relays a Stwo spend under its own key and refuses what would not apply" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

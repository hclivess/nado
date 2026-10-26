"""From STWO_FEE_TO_HEIGHT a Stwo spend may name `fee_to`: its fee is paid to that address (an unshield exit) and its
payout goes to any address — a fresh per-dApp shadow account — with both bound into the proof; below the gate the key is
ignored exactly as the code before the gate ignored it (execnode/shielded_stwo.parse_transfer, ExecState._apply_stwo_transfer,
ops/stwo_relay.py, /exec/stwo_spendable).

WHY (shadow accounts, 2026-10-18). A proof binds ONE address. Before this, a relay could only be paid by the payout itself,
so a withdrawal to any other address had to be published — and signed — by the user's own account, re-linking the
"private" account to it. With fee_to the relay is paid by `fee`, the payout goes to the shadow account, and the proof is
bound to "<withdraw_addr>|fee:<fee_to>" (the circuit's aux is BLAKE2s of the destination string — no circuit change), so
a copied bundle cannot redirect either.

Pins, with real wallet-WASM proofs and the real native verifier:
  1. at the gate: a spend paying U to a shadow address and F to the relay applies — two exits, pool_fees unchanged,
     stwo_value down by U + F;
  2. the same bundle with fee_to swapped to another address is refused by the verifier (the fee cannot be stolen);
  3. below the gate the key is ignored: the composite-bound proof is refused (verified against the bare payout) and the
     state does not move, while a bundle carrying a stray fee_to over a plain-bound proof applies with its fee in
     pool_fees — the pre-gate behaviour, unchanged;
  4. fee_to with a zero fee, or naming a contract, is refused;
  5. the relay: from the gate it accepts a spend paying it by fee (payout elsewhere) and refuses one paying another
     relay; below the gate /exec/stwo_spendable refuses a fee_to spend so no relay pays for one.
SKIPs without node or a stable cargo (the verifier).

Run: python3 tests/test_a_stwo_spend_pays_its_fee_to_the_named_relay_and_its_payout_anywhere.py
"""
import os, sys, tempfile, json, secrets, shutil, hashlib, asyncio, copy
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-feeto-")
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
from execnode.state import ExecState
from execnode import shielded_stwo as SP
import execnode.execnode as EN
from ops.key_ops import generate_keys
from ops.address_ops import make_address
import ops.stwo_relay as R

GATE, FEE_GATE = 1000, 2000
P.STWO_POOL_HEIGHT, P.STWO_FEE_TO_HEIGHT = GATE, FEE_GATE
relay_key = generate_keys()
RELAY, SHADOW, OTHER = relay_key["address"], make_address("ab" * 1312), make_address("ef" * 1312)
FEE, U = R.STWO_RELAY_FEE_RAW, 3 * 10 ** 8

nsk = secrets.token_hex(32)
me = SP.owner_of(nsk)


def pool():
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=_T), "s.json"))
    st.cursor = GATE - 1
    for i in range(2):
        st.apply_field_shield(5000 + i, SP.owner_of(secrets.token_hex(32)), 900 + i)
    v, rho = 10 ** 9, secrets.randbits(64)
    st.apply_field_shield(v, me, rho)
    return st, v, rho


def prove(st, v, rho, dest, unshield=U, fee=FEE):
    leaves = list(st.stwo_pool.commitments)
    spend = {"nsk": nsk, "vIn": str(v), "rho": str(rho), "v1": str(v - unshield - fee), "o1": me,
             "r1": str(secrets.randbits(64)), "v2": "0", "o2": me, "r2": str(secrets.randbits(64)),
             "unshield": str(unshield), "fee": str(fee), "dest": dest}
    return wallet_prove(spend, leaves, leaves.index(SP.commit(v, me, rho)), FEE_GATE)["bundle"]


def at(st, h):
    st._applying = h
    st.cursor = h - 1


def snap(st):
    return json.dumps(st.to_dict() if hasattr(st, "to_dict") else st._snapshot(), sort_keys=True, default=str)


# ---- 1/2. at the gate ----------------------------------------------------------------------------------------------
st, v, rho = pool()
print("      proving (shipped wallet WASM)…")
b = prove(st, v, rho, f"{SHADOW}|fee:{RELAY}")
b["withdraw_addr"], b["fee_to"] = SHADOW, RELAY
at(st, FEE_GATE)
stolen = copy.deepcopy(b); stolen["fee_to"] = OTHER
r_stolen = st.apply_field_transfer(copy.deepcopy(stolen))
check("2. the same bundle with fee_to swapped to another address is refused (the fee cannot be redirected)",
      r_stolen.startswith("skip") and not st.stwo_pool.has_nullifier(b["stark"]["stwo_js"]["nf"]), r_stolen)
fees0, sv0, n0 = st.pool_fees, st.stwo_value, st.uw_nonce
r = st.apply_field_transfer(copy.deepcopy(b))
exits = [st.unshield_withdrawals[str(i)] for i in range(n0 + 1, st.uw_nonce + 1)]
check("1. at the gate a spend paying the payout to a shadow address and the fee to the relay applies", r.startswith("field-transfer stwo"), r)
check("...two exits: the payout to the shadow account, the fee to the relay",
      exits == [{"addr": SHADOW, "amount": U}, {"addr": RELAY, "amount": FEE}], exits)
check("...pool_fees unchanged, stwo_value down by payout + fee", st.pool_fees == fees0 and st.stwo_value == sv0 - U - FEE,
      (st.pool_fees, fees0, st.stwo_value, sv0))

# ---- 3. below the gate the key is ignored ---------------------------------------------------------------------------
st, v, rho = pool()
b = prove(st, v, rho, f"{SHADOW}|fee:{RELAY}")
b["withdraw_addr"], b["fee_to"] = SHADOW, RELAY
at(st, FEE_GATE - 1)
before = (st.pool_value, st.stwo_value, st.uw_nonce, len(st.stwo_pool.nullifiers))
r = st.apply_field_transfer(copy.deepcopy(b))
check("3. below the gate a composite-bound proof is refused (fee_to ignored, verified against the bare payout)",
      r.startswith("skip") and before == (st.pool_value, st.stwo_value, st.uw_nonce, len(st.stwo_pool.nullifiers)), r)
plain = prove(st, v, rho, SHADOW)
plain["withdraw_addr"], plain["fee_to"] = SHADOW, RELAY        # a stray key the old code never read
fees0 = st.pool_fees
r = st.apply_field_transfer(copy.deepcopy(plain))
check("...while a stray fee_to over a plain-bound proof applies with its fee in pool_fees, as before the gate",
      r.startswith("field-transfer stwo") and st.pool_fees == fees0 + FEE
      and st.unshield_withdrawals[str(st.uw_nonce)] == {"addr": SHADOW, "amount": U}, r)

# ---- 4. malformed fee_to --------------------------------------------------------------------------------------------
why, _ = SP.parse_transfer({"stark": {"stwo_js": {**b["stark"]["stwo_js"], "fee": "0"}}, "withdraw_addr": SHADOW,
                            "fee_to": RELAY}, 1 << 61, fee_to_ok=True)
check("4. fee_to with a zero fee is refused", why and "zero fee" in why, why)
st, v, rho = pool()
st.contracts["c" * 64] = {"code": []}
b = prove(st, v, rho, f"{SHADOW}|fee:{'c' * 64}")
b["withdraw_addr"], b["fee_to"] = SHADOW, "c" * 64
at(st, FEE_GATE)
r = st.apply_field_transfer(copy.deepcopy(b))
check("...and so is one naming a contract (or any non-address)", r.startswith("skip"), r)

# ---- 5. the relay -------------------------------------------------------------------------------------------------------
st, v, rho = pool()
EN.state = st


def exec_get(path):
    from urllib.parse import urlsplit, parse_qsl
    u = urlsplit(path)
    h = {"/exec/stwo_spendable": EN.h_stwo_spendable, "/exec/field_shielded": EN.h_field_shielded}.get(u.path)
    if h is None:
        return None

    class _Req:
        query = dict(parse_qsl(u.query))
    return json.loads(asyncio.run(h(_Req())).body)


DA, SUBMITTED = {}, []


def da_publish(bts):
    c = hashlib.sha256(bts).hexdigest(); DA[c] = bts; return c


def submit(tx):
    SUBMITTED.append(tx); return {"result": True, "message": "Success"}


TIP = [FEE_GATE + 5]
relay = R.StwoRelay(keydict_fn=lambda: relay_key, tip_fn=lambda: TIP[0], exec_get=exec_get, da_publish=da_publish,
                    submit=submit, allow=lambda *_: True)
b = prove(st, v, rho, f"{SHADOW}|fee:{RELAY}")
b["withdraw_addr"], b["fee_to"] = SHADOW, RELAY
other = prove(st, v, rho, f"{SHADOW}|fee:{OTHER}")
other["withdraw_addr"], other["fee_to"] = SHADOW, OTHER
st.cursor = FEE_GATE - 2                                         # the exec node is still below the gate
res, status = relay.relay({"bundle": copy.deepcopy(b)}, "198.51.100.1")
check("5. below the gate the relay refuses a fee_to spend before paying anything", status != 200 and not SUBMITTED, (status, res))
st.cursor = FEE_GATE
res, status = relay.relay({"bundle": copy.deepcopy(other)}, "198.51.100.2")
check("...from the gate it refuses a spend whose fee pays another relay", status == 400 and not SUBMITTED, (status, res))
res, status = relay.relay({"bundle": copy.deepcopy(b)}, "198.51.100.3")
check("...and accepts one paying it by fee, the payout going to the shadow account", status == 200 and len(SUBMITTED) == 1
      and SUBMITTED[0]["sender"] == RELAY, (status, res))
# ---- 6. the wallet's own prover builds the composite binding (static/stark/stwo_js.js proveSpend feeTo) ----------------
st, v, rho = pool()
leaves = list(st.stwo_pool.commitments)
spend = {"nsk": nsk, "vIn": str(v), "rho": str(rho), "v1": str(v - U - FEE), "o1": me, "r1": str(secrets.randbits(64)),
         "v2": "0", "o2": me, "r2": str(secrets.randbits(64)), "unshield": str(U), "fee": str(FEE), "dest": SHADOW, "feeTo": RELAY}
wb = wallet_prove(spend, leaves, leaves.index(SP.commit(v, me, rho)), FEE_GATE)["bundle"]
at(st, FEE_GATE)
n0 = st.uw_nonce
r = st.apply_field_transfer(copy.deepcopy(wb))
check("6. a bundle the wallet's own prover builds with feeTo carries withdraw_addr + fee_to and applies at the gate",
      wb.get("withdraw_addr") == SHADOW and wb.get("fee_to") == RELAY and r.startswith("field-transfer stwo")
      and [st.unshield_withdrawals[str(i)] for i in range(n0 + 1, st.uw_nonce + 1)]
      == [{"addr": SHADOW, "amount": U}, {"addr": RELAY, "amount": FEE}], (r, {k: wb.get(k) for k in ("withdraw_addr", "fee_to")}))
print("ALL PASS — a Stwo spend pays its fee to the named relay and its payout anywhere" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

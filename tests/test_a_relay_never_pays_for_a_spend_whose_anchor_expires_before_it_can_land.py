"""A node's Stwo spend relay never pays an L1 fee for a spend the exec layer will refuse in the block it can land in.

REVIEW 2026-10-12 (pre-push, stwo-on), reproduced here. The relay (ops/stwo_relay.py) asks its exec node whether a spend
"would apply in the next block" — /exec/stwo_spendable judges ExecState.stwo_spend_refusal at FINALIZED cursor + 1. But
the blob the relay signs cannot land before min_block = L1 tip + TX_INCLUSION_DELAY, and the exec node's finalized cursor
trails the L1 tip by the finality depth on top of that. A spend's anchor that is a block-closing root (shielded_stwo
ANCHORS: kept ANCHOR_BLOCKS blocks) is therefore checked against a window that is at least TX_INCLUSION_DELAY blocks
(in production ~finality + 8 blocks) younger than the one it is applied against.

THE ATTACK. A wallet that owns one note proves a spend of it to relay R (unshield = R's fee, withdraw_addr = R, a fully
valid proof) anchored to a block-closing root that is about to leave the window. Every relay check passes — parse, pays
this relay, nullifier not in flight, stwo_spendable ok, proof verifies — so R writes ~3 MB to DA, signs and pays the
blob's L1 fee, and holds the nullifier in flight for STWO_RELAY_HOLD_S. In the block it lands in, every exec node skips
it as "unknown anchor root". Nothing is spent: the note is unspent, the relay is never paid its fee, and the attacker
repeats it with the same note (and 63 more) against every relay — each relay's 64 in-flight slots stay full for 45 min,
so no honest private spend can be relayed, for the price of proving alone.

Even with the exec node fully caught up with the L1 tip (no finality lag at all) the gap is TX_INCLUSION_DELAY; this
test uses exactly that best case. The property: what the relay vouches for (and pays for) is judged at the height the
blob can first land, not at cursor + 1.

SKIPs without node or a stable cargo (the verifier).
Run: python3 tests/test_a_relay_never_pays_for_a_spend_whose_anchor_expires_before_it_can_land.py
"""
import os, sys, tempfile, json, secrets, shutil, hashlib, asyncio
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-relay-anchor-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests._stwo_js_build import Env, wallet_prove

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
import ops.stwo_relay as R

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


GATE = 1000
node = generate_keys()                       # a throwaway NODE key (the relay signs with its node key)
FEE = R.STWO_RELAY_FEE_RAW

# ---- block GATE: the attacker's note lands; that block closes on root R0 (a block mark) ------------------------------
nsk = secrets.token_hex(32)
me = SP.owner_of(nsk)
st = ExecState(os.path.join(_T, "s.json"))
st.cursor = GATE - 1
for i in range(2):
    st.apply_field_shield(5000 + i, SP.owner_of(secrets.token_hex(32)), 900 + i)
v, rho = 10 ** 9, secrets.randbits(64)
st.apply_field_shield(v, me, rho)
leaves0 = list(st.stwo_pool.commitments)
R0 = SP.tree_root(leaves0)
# ---- block GATE+1: ordinary traffic pushes R0 out of the 128-append window; only its block mark keeps it -------------
st.cursor = GATE
for i in range(SP.ANCHOR_WINDOW + 2):
    st.apply_field_shield(1 + i, SP.owner_of(secrets.token_hex(32)), i)
check("setup: R0 is reachable only through its block mark", R0 not in st.stwo_pool.anchors
      and st.stwo_pool.knows_root(R0, GATE + SP.ANCHOR_BLOCKS) and not st.stwo_pool.knows_root(R0, GATE + SP.ANCHOR_BLOCKS + 1))

# ---- the exec node is FULLY caught up with L1 (best case: no finality lag); its next block is GATE + ANCHOR_BLOCKS ----
st.cursor = GATE + SP.ANCHOR_BLOCKS - 1
TIP = st.cursor
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


relay = R.StwoRelay(keydict_fn=lambda: node, tip_fn=lambda: TIP, exec_get=exec_get, da_publish=da_publish,
                    submit=submit, allow=lambda *_: True)

print("      proving against R0 (shipped wallet WASM)…")
spend = {"nsk": nsk, "vIn": str(v), "rho": str(rho), "v1": str(v - FEE), "o1": me, "r1": str(secrets.randbits(64)),
         "v2": "0", "o2": me, "r2": str(secrets.randbits(64)), "unshield": str(FEE), "fee": "0", "dest": node["address"]}
bundle = wallet_prove(spend, leaves0, leaves0.index(SP.commit(v, me, rho)), TIP + P.TX_INCLUSION_DELAY)["bundle"]
check("setup: the proof is anchored to R0", bundle["stark"]["stwo_js"]["root"] == R0)

res, status = relay.relay({"bundle": bundle}, "203.0.113.7")
paid = len(SUBMITTED)
tx = SUBMITTED[-1] if SUBMITTED else None
land = int((tx or {}).get("min_block") or (TIP + P.TX_INCLUSION_DELAY))
check("setup: a blob the relay signs cannot land before tip + TX_INCLUSION_DELAY",
      tx is None or land == TIP + P.TX_INCLUSION_DELAY, tx and tx.get("min_block"))

# what every exec node does with the blob in the first block it may land in
st._applying = land
st.cursor = land - 1
# the same bundle the relay was handed (it never published one once fixed): what every exec node would do with it there
applied = st.apply_field_transfer(json.loads(DA[tx["data"]["proof_da"]]) if tx else json.loads(json.dumps(bundle)))
st._applying = None
check("the exec layer refuses this spend in the first block it can land in (the anchor aged out)",
      "unknown anchor root" in applied, applied)
check("the relay refuses it BEFORE paying an L1 fee or writing DA — it judges the spend at the height it can land",
      paid == 0 and not DA and status != 200,
      f"relay answered {status} {res}; signed {paid} fee-paying blob(s), wrote {len(DA)} DA object(s); the exec layer "
      f"then said: {applied!r}; the note stays unspent ({not st.stwo_pool.has_nullifier(bundle['stark']['stwo_js']['nf'])}) "
      f"and the nullifier holds one of this relay's {R.STWO_RELAY_INFLIGHT_MAX} in-flight slots for "
      f"{R.STWO_RELAY_HOLD_S} s ({len(relay.inflight)} held)")

print("ALL PASS — a relay never pays for a spend whose anchor expires before it can land" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

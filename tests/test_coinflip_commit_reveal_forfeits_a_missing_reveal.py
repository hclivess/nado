"""Coin Flip: commit-reveal decides the coin, and a missing reveal forfeits (execnode/games/coinflip.py, Release B
rule consistency).

  * open(g, C1) / join(g, C2): each player commits C = HASH(secret); join opens the reveal window
    dl = cursor + REVEAL_WINDOW; a zero commitment is refused;
  * reveal(g, s): only a player of g, only while cursor < dl, only the secret behind THEIR commitment, only once;
  * settle(g): both revealed -> winner = HASH(s1 + s2 + g) LO32 % 2 (equal to the in-clear reference AND to the
    browser's chainResultAlg(s1, s2, g, 2)); one revealed -> the revealer takes the pot, but only once
    cursor >= dl; none revealed -> each stake back; reclaim is refused for a commit-reveal game;
  * a game written the way the OLD code wrote it (md == 0, no commitments, sh = join cursor + 2) still settles
    from BLOCKHASH(sh) + BLOCKHASH(sh+1) and is still reclaimable past the horizon; an old open still joins
    under the old rule;
  * the client's commitment of a secret (algHashn([secret mod P]) from static/nadodapp.js) equals the VM's
    HASH of it — so a browser-made commitment is revealable.

Run: python3 tests/test_coinflip_commit_reveal_forfeits_a_missing_reveal.py
"""
import os
import sys
import tempfile
import json
import shutil
import subprocess

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-coinflip-cr-")      # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.state import ExecState                                   # noqa: E402
from execnode.runtimes import zkvm_addr_digest                         # noqa: E402
from execnode.stark import alghash, field as F                         # noqa: E402
from execnode.games import coinflip as CF                              # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


A = "ndoA" + "a" * 44
B = "ndoB" + "b" * 44
C = "ndoC" + "c" * 44
STAKE = 50_000
START = 10 ** 9
_n = [0]


def H(x):
    return alghash.hashn([x % F.P])


def ref_slot(s1, s2, g):
    """In-clear reference: winner slot = (HASH(s1 + s2 + g) LO32 % 2) + 1."""
    return (H((s1 % F.P + s2 % F.P + g) % F.P) & 0xFFFFFFFF) % 2 + 1


def fresh(cursor=1000):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
    st.cursor = cursor
    for w in (A, B, C):
        st.bridge[w] = START
    code = CF.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": CF.ABI, "nonce": "n"}, A, "d")
    return st, st.contract_id(A, code, "n")


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    blob = {"op": "call", "contract": cid, "method": m, "args": args}
    if value is not None:
        blob["value"] = value
    return st.apply_blob(blob, who, f"{m}-{_n[0]}")


def rd(st, cid, f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


def snap(st, cid):
    return json.dumps({"s": st.contracts[cid]["storage"], "b": st.bridge}, sort_keys=True, default=str)


def refused(st, cid, who, m, args, value=None):
    before = snap(st, cid)
    try:
        call(st, cid, who, m, args, value)
    except Exception:
        pass
    return snap(st, cid) == before


def started(g, s1, s2):
    """A joined commit-reveal game; returns (st, cid)."""
    st, cid = fresh()
    call(st, cid, A, "open", [g, H(s1)], STAKE)
    call(st, cid, B, "join", [g, H(s2)], STAKE)
    return st, cid


# ---- 1. open/join record the commit-reveal game --------------------------------------------------------------
S1, S2, G = 0x1234567890ABCDEF % F.P, 0xFEDCBA0987654321 % F.P, 777
st, cid = fresh()
check("open refuses a zero commitment", refused(st, cid, A, "open", [G, 0], STAKE))
call(st, cid, A, "open", [G, H(S1)], STAKE)
check("open records md = 1 and c1 = HASH(s1)", rd(st, cid, CF.MD, G) == 1 and rd(st, cid, CF.C1, G) == H(S1))
check("reveal is refused before anyone joined", refused(st, cid, A, "reveal", [G, S1]))
check("join refuses a zero commitment", refused(st, cid, B, "join", [G, 0], STAKE))
call(st, cid, B, "join", [G, H(S2)], STAKE)
check("join records c2 and dl = cursor + REVEAL_WINDOW",
      rd(st, cid, CF.C2, G) == H(S2) and rd(st, cid, CF.DL, G) == 1000 + CF.REVEAL_WINDOW and rd(st, cid, CF.NN, G) == 2)
check("settle is refused while nobody revealed inside the window", refused(st, cid, C, "settle", [G]))

# ---- 2. reveal guards ----------------------------------------------------------------------------------------
check("a wrong secret is refused", refused(st, cid, A, "reveal", [G, S1 + 1]))
check("the opponent's secret is refused (each player opens only their own commitment)", refused(st, cid, A, "reveal", [G, S2]))
check("a non-player's reveal is refused, even with a valid secret", refused(st, cid, C, "reveal", [G, S1]))
call(st, cid, A, "reveal", [G, S1])
check("p1 reveals", rd(st, cid, CF.V1, G) == 1 and rd(st, cid, CF.S1, G) == S1)
check("a double reveal is refused", refused(st, cid, A, "reveal", [G, S1]))
check("a lone reveal does not settle before the deadline", refused(st, cid, C, "settle", [G]))

# ---- 3. both reveal -> deterministic winner equal to the reference ---------------------------------------------
call(st, cid, B, "reveal", [G, S2])
want = ref_slot(S1, S2, G)
a0, b0 = st.bridge[A], st.bridge[B]
call(st, cid, C, "settle", [G])                                         # permissionless, before the deadline
check("both revealed: settles at once, winner == HASH(s1 + s2 + g) LO32 % 2 reference",
      rd(st, cid, CF.SD, G) == 1 and rd(st, cid, CF.WS, G) == want, f"ws={rd(st, cid, CF.WS, G)} want={want}")
check("both revealed: the winner receives the whole pot, the loser nothing",
      (st.bridge[A] - a0, st.bridge[B] - b0) == ((2 * STAKE, 0) if want == 1 else (0, 2 * STAKE))
      and st.bridge.get(cid, 0) == 0 and rd(st, cid, CF.PT, G) == 0)
check("a settled game cannot be settled again", refused(st, cid, C, "settle", [G]))
check("reveal after settle is refused", refused(st, cid, B, "reveal", [G, S2]))

# both slots happen: over a handful of secret pairs the reference must produce both outcomes and the VM must agree
seen = set()
for i in range(8):
    s1, s2, g = (i * 0x9E3779B97F4A7C15 + 5) % F.P, (i * 0xC2B2AE3D27D4EB4F + 11) % F.P, 1000 + i
    st_i, cid_i = started(g, s1, s2)
    call(st_i, cid_i, A, "reveal", [g, s1])
    call(st_i, cid_i, B, "reveal", [g, s2])
    call(st_i, cid_i, A, "settle", [g])
    seen.add(rd(st_i, cid_i, CF.WS, g))
    if rd(st_i, cid_i, CF.WS, g) != ref_slot(s1, s2, g):
        check(f"pair {i}: VM winner equals the reference", False, f"{rd(st_i, cid_i, CF.WS, g)} vs {ref_slot(s1, s2, g)}")
check("eight secret pairs: the VM matches the reference on every one and both slots occur", seen == {1, 2}, str(seen))

# ---- 4. one reveal -> the revealer wins after the deadline (and not before) ------------------------------------
for who, slot in ((A, 1), (B, 2)):
    st, cid = started(G, S1, S2)
    call(st, cid, who, "reveal", [G, S1 if slot == 1 else S2])
    dl = rd(st, cid, CF.DL, G)
    st.cursor = dl - 1
    check(f"slot {slot} alone revealed: settle refused at dl - 1", refused(st, cid, C, "settle", [G]))
    other = B if slot == 1 else A
    check(f"slot {slot} alone revealed: the other player's reveal still lands at dl - 1 (window open)",
          not refused(st, cid, other, "reveal", [G, S2 if slot == 1 else S1]))
    st, cid = started(G, S1, S2)                                         # the lone-reveal case, cleanly
    call(st, cid, who, "reveal", [G, S1 if slot == 1 else S2])
    st.cursor = dl
    check(f"slot {slot} alone revealed: the late reveal of the other player is refused at dl",
          refused(st, cid, other, "reveal", [G, S2 if slot == 1 else S1]))
    a0, b0 = st.bridge[A], st.bridge[B]
    call(st, cid, C, "settle", [G])
    gain = (st.bridge[A] - a0, st.bridge[B] - b0)
    check(f"slot {slot} alone revealed: at dl the revealer takes the whole pot (ws = {slot})",
          rd(st, cid, CF.SD, G) == 1 and rd(st, cid, CF.WS, G) == slot
          and gain == ((2 * STAKE, 0) if slot == 1 else (0, 2 * STAKE)) and st.bridge.get(cid, 0) == 0, f"{gain}")

# ---- 5. no reveals -> refunds -----------------------------------------------------------------------------------
st, cid = started(G, S1, S2)
st.cursor = rd(st, cid, CF.DL, G) - 1
check("nobody revealed: settle refused before the deadline", refused(st, cid, C, "settle", [G]))
check("reclaim is refused for a commit-reveal game (settle resolves it; a forfeit is never a refund)",
      refused(st, cid, C, "reclaim", [G]))
st.cursor = rd(st, cid, CF.DL, G) + 5
a0, b0 = st.bridge[A], st.bridge[B]
call(st, cid, C, "settle", [G])
check("nobody revealed: past the deadline each player gets their own stake back, ws = 0",
      (st.bridge[A] - a0, st.bridge[B] - b0) == (STAKE, STAKE) and rd(st, cid, CF.SD, G) == 1
      and rd(st, cid, CF.WS, G) == 0 and st.bridge.get(cid, 0) == 0)
st.cursor = 10 ** 6
check("reclaim stays refused after the horizon too", refused(st, cid, C, "reclaim", [G]))

# cancel pre-join is unchanged
st, cid = fresh()
call(st, cid, A, "open", [9, H(1)], 300)
a0 = st.bridge[A]
check("cancel by a non-opener is refused", refused(st, cid, B, "cancel", [9]))
call(st, cid, A, "cancel", [9])
check("cancel pre-join refunds the opener", st.bridge[A] - a0 == 300 and rd(st, cid, CF.SD, 9) == 1 and st.bridge.get(cid, 0) == 0)

# ---- 6. legacy games (md == 0, written as the old code wrote them) ---------------------------------------------
def legacy_joined(st, cid, g, sh):
    """Storage exactly as the pre-upgrade open/join left it: nn=2, stake, pot, p1, p2, sh; no md, no commitments."""
    sl = st.contracts[cid]["storage"].setdefault("slots", {})
    S = lambda f: str(f * (1 << 32) + g)
    sl[S(CF.NN)] = 2; sl[S(CF.ST)] = STAKE; sl[S(CF.PT)] = 2 * STAKE
    sl[S(CF.P1)] = zkvm_addr_digest(A); sl[S(CF.P2)] = zkvm_addr_digest(B); sl[S(CF.SH)] = sh
    st.zk_addrs[str(zkvm_addr_digest(A))] = A; st.zk_addrs[str(zkvm_addr_digest(B))] = B
    cnt = int(sl.get("0", 0)); sl[str(CF.LIST * (1 << 32) + cnt)] = g; sl["0"] = cnt + 1
    st.bridge[cid] = st.bridge.get(cid, 0) + 2 * STAKE


st, cid = fresh()
LG, SH = 4242, 1000
legacy_joined(st, cid, LG, SH)
st.block_hashes[SH] = 0xABCDEF0123; st.block_hashes[SH + 1] = 0x77665544
check("legacy game: reveal is refused (no commitments)", refused(st, cid, A, "reveal", [LG, 1]))
st.cursor = SH
check("legacy game: settle still waits for both settle blocks", refused(st, cid, C, "settle", [LG]))
st.cursor = SH + 1
want = (H((0xABCDEF0123 + 0x77665544 + LG) % F.P) & 0xFFFFFFFF) % 2 + 1
a0, b0 = st.bridge[A], st.bridge[B]
call(st, cid, C, "settle", [LG])
check("legacy game: settles from BLOCKHASH(sh) + BLOCKHASH(sh+1) + g exactly as before",
      rd(st, cid, CF.SD, LG) == 1 and rd(st, cid, CF.WS, LG) == want
      and (st.bridge[A] - a0, st.bridge[B] - b0) == ((2 * STAKE, 0) if want == 1 else (0, 2 * STAKE)),
      f"ws={rd(st, cid, CF.WS, LG)} want={want}")

st, cid = fresh()
legacy_joined(st, cid, LG, SH)
st.cursor = SH + 18000
check("legacy game: reclaim refused inside the horizon", refused(st, cid, C, "reclaim", [LG]))
st.cursor = SH + 18001
a0, b0 = st.bridge[A], st.bridge[B]
call(st, cid, C, "reclaim", [LG])
check("legacy game: reclaim past the horizon refunds both stakes",
      (st.bridge[A] - a0, st.bridge[B] - b0) == (STAKE, STAKE) and rd(st, cid, CF.SD, LG) == 1)

# an old open (md == 0, nn == 1) joined after the upgrade keeps the old rule
st, cid = fresh()
sl = st.contracts[cid]["storage"].setdefault("slots", {})
OG = 5151
for f, v in ((CF.NN, 1), (CF.ST, STAKE), (CF.PT, STAKE), (CF.P1, zkvm_addr_digest(A))):
    sl[str(f * (1 << 32) + OG)] = v
st.bridge[cid] = STAKE
call(st, cid, B, "join", [OG, H(S2)], STAKE)
check("legacy open joined after the upgrade: old rule (sh = cursor + 2, no deadline, no commitment stored)",
      rd(st, cid, CF.NN, OG) == 2 and rd(st, cid, CF.SH, OG) == 1002 and rd(st, cid, CF.DL, OG) == 0
      and rd(st, cid, CF.C2, OG) == 0 and rd(st, cid, CF.MD, OG) == 0)

# ---- 7. view exposes the new fields ------------------------------------------------------------------------------
st, cid = started(G, S1, S2)
call(st, cid, A, "reveal", [G, S1])
v = st.decode_view(st.contracts[cid])
check("decode_view exposes md / c1 / c2 / dl / v1 / s1 (big values as strings)",
      v["md"][str(G)] == 1 and int(v["c1"][str(G)]) == H(S1) and int(v["c2"][str(G)]) == H(S2)
      and v["dl"][str(G)] == 1000 + CF.REVEAL_WINDOW and v["v1"][str(G)] == 1 and int(v["s1"][str(G)]) == S1
      and str(G) not in v.get("v2", {}))


# ---- 8. the browser computes the same commitment and the same winner ---------------------------------------------
def js_eval(pairs):
    """static/nadodapp.js as the browser runs it: commit = algHashn([secret]); preview = chainResultAlg(s1, s2, g, 2)."""
    if not shutil.which("node"):
        return None
    stub = ("const el = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => '' : el, apply: () => el });\n"
            "for (const k of ['document', 'window', 'localStorage', 'sessionStorage', 'location', 'history']) "
            "if (!(k in globalThis)) globalThis[k] = el;\n")
    prog = (stub + "const { algHashn, chainResultAlg, randSecret, ALG_P } = await import('%s');\n"
            % ("file://" + os.path.join(ROOT, "static", "nadodapp.js"))
            + "const xs = JSON.parse(process.argv[2]);\n"
            + "const fresh = (randSecret() % ALG_P());\n"
            + "console.log(JSON.stringify({ rows: xs.map(([a, b, g]) => [String(algHashn([BigInt(a)])), String(algHashn([BigInt(b)])),"
            + " chainResultAlg(BigInt(a).toString(16), BigInt(b).toString(16), g, 2)]),"
            + " fresh: String(fresh), freshC: String(algHashn([fresh])) }));\n"
            + "process.exit(0);\n")
    path = os.path.join(os.environ["HOME"], "cf.mjs")
    open(path, "w").write(prog)
    out = subprocess.run(["node", path, json.dumps(pairs)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(out.stderr[-2000:])
        return "error"
    return json.loads(out.stdout)


pairs = [[str(S1), str(S2), str(G)], [str(F.P - 1), "1", "4294967295"], [str((1 << 63) % F.P), str(12345), "1"]]
js = js_eval(pairs)
if js is None:
    print("SKIP  node not installed: client commitment cross-check")
else:
    check("node ran the client helpers", js != "error")
    if js != "error":
        ok_c = all(int(r[0]) == H(int(a)) and int(r[1]) == H(int(b)) for r, (a, b, _g) in zip(js["rows"], pairs))
        check("client commitment algHashn([secret]) == VM HASH(secret), on edge-of-field secrets", ok_c)
        ok_w = all(r[2] + 1 == ref_slot(int(a), int(b), int(g)) for r, (a, b, g) in zip(js["rows"], pairs))
        check("client preview chainResultAlg(s1, s2, g, 2) == contract winner", ok_w)
        fs = int(js["fresh"])
        check("a fresh client secret is a field element and its commitment matches the VM",
              0 <= fs < F.P and int(js["freshC"]) == H(fs))
        # and the VM accepts that browser-made commitment end to end
        st, cid = started(31, fs, S2)
        st.contracts[cid]["storage"]["slots"][str(CF.C1 * (1 << 32) + 31)] = int(js["freshC"])
        call(st, cid, A, "reveal", [31, fs])
        check("the VM accepts a reveal against the browser-made commitment", rd(st, cid, CF.V1, 31) == 1)

print()
if FAILED:
    print(f"{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")

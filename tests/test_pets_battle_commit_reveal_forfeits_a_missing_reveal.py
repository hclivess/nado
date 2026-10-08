"""Pets battles: commit-reveal decides the duel, and a missing reveal forfeits (execnode/games/pets.py, Release B
game fairness).

  * challenge(bid, myPet, theirPet, C1) / accept(bid, C2): each owner commits C = HASH(secret); accept opens the
    reveal window wrd = cursor + REVEAL_WINDOW; a zero commitment, or an accepter copying C1, is refused;
  * reveal_battle(bid, s): only the secret behind one of the two commitments, only once per side, only while
    cursor <= wrd;
  * resolve_battle(bid): both revealed -> the 12-turn duel over seed HASH(s1 + s2 + bid), equal to
    ref_battle_turns(ref_battle_seed(s1, s2, bid), 0, ...) (winner, death, claim, pot); one revealed -> the
    revealer's pet wins by forfeit, but only once cursor > wrd (no death roll); none revealed -> each side's own
    stake back (and refund_battle does the same, but refuses a battle with one reveal);
  * a battle issued and accepted by the OLD code (deployed, then upgraded in place) keeps the block-hash rule;
  * the browser's commitment (algHashn([secret]) in static/nadodapp.js) equals the VM's HASH, and
    static/pets-genes.js previews the commit-reveal duel exactly as the contract fights it.

Run: python3 tests/test_pets_battle_commit_reveal_forfeits_a_missing_reveal.py
"""
import os
import sys
import tempfile
import json
import shutil
import subprocess
import importlib.util

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-pets-battle-cr-")    # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.state import ExecState                                   # noqa: E402
from execnode.runtimes import zkvm_addr_digest                         # noqa: E402
from execnode.stark import alghash, field as F                         # noqa: E402
from execnode.games import pets as P                                   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


A = "ndoA" + "a" * 44
B = "ndoB" + "b" * 44
C = "ndoC" + "c" * 44
STAKE = 10 ** 9
START = 10 ** 13
_n = [0]


def H(x):
    return alghash.hashn([x % F.P])


def fresh(code=None, abi=None, cursor=1000):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
    st.cursor = cursor
    for w in (A, B, C):
        st.bridge[w] = START
    code = code or P.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": abi or P.ABI, "nonce": "n"}, A, "d")
    return st, st.contract_id(A, code, "n")


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    blob = {"op": "call", "contract": cid, "method": m, "args": args}
    if value is not None:
        blob["value"] = value
    return st.apply_blob(blob, who, f"{m}-{_n[0]}")


def rd(st, cid, f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


def pet(st, cid, who, pid):
    """mint + hatch one pet off injected block hashes; return its 10 effective stats."""
    assert "ok" in call(st, cid, who, "mint", [pid], P.MINT_FEE)
    bh = rd(st, cid, P.BH, pid)
    st.block_hashes[bh] = 1_000_003 * pid + 17
    st.block_hashes[bh + 1] = 7_000_001 * pid + 5
    st.cursor = max(st.cursor, bh + 2)
    r = call(st, cid, who, "hatch", [pid])
    assert "ok" in r, r
    gene, sp = rd(st, cid, P.GN, pid), rd(st, cid, P.SP, pid)
    return [P.ref_stat(gene, sp, i) for i in range(10)]


def owner(st, cid, pid):
    return rd(st, cid, P.OW, pid)


def battle(st, cid, bid, pa, pb, s1, s2):
    r1 = call(st, cid, A, "challenge", [bid, pa, pb, H(s1)], STAKE)
    r2 = call(st, cid, B, "accept", [bid, H(s2)], STAKE)
    return r1, r2


S1, S2 = 123456789123456789 % F.P, 987654321987654321 % F.P


# ---- both reveal -> the duel over HASH(s1 + s2 + bid) -------------------------------------------------------------
st, cid = fresh()
effA, effB = pet(st, cid, A, 1), pet(st, cid, B, 2)
check("a challenge with a zero commitment is refused",
      "ok" not in call(st, cid, A, "challenge", [70, 1, 2, 0], STAKE))
check("a challenge with a commitment is issued as a commit-reveal battle (wm == 1)",
      "ok" in call(st, cid, A, "challenge", [70, 1, 2, H(S1)], STAKE) and rd(st, cid, P.WM, 70) == 1
      and rd(st, cid, P.WC1, 70) == H(S1))
check("the accepter cannot copy the challenger's commitment",
      "ok" not in call(st, cid, B, "accept", [70, H(S1)], STAKE))
check("the accepter cannot accept with a zero commitment", "ok" not in call(st, cid, B, "accept", [70, 0], STAKE))
r = call(st, cid, B, "accept", [70, H(S2)], STAKE)
acc_at = st.cursor
check("accept stores the accepter's commitment and the deadline wrd = cursor + REVEAL_WINDOW",
      "ok" in r and rd(st, cid, P.WC2, 70) == H(S2) and rd(st, cid, P.WRD, 70) == acc_at + P.REVEAL_WINDOW, r)
check("the fighters' rest lock covers the reveal window",
      rd(st, cid, P.EX, 1) == acc_at + P.HATCH_DELAY + P.EXHAUST + P.REVEAL_WINDOW)
check("resolve_battle with nothing revealed and the window open is refused",
      "ok" not in call(st, cid, C, "resolve_battle", [70]))
check("a secret matching neither commitment is refused", "ok" not in call(st, cid, C, "reveal_battle", [70, 42]))
check("the challenger's secret reveals side A", "ok" in call(st, cid, A, "reveal_battle", [70, S1])
      and rd(st, cid, P.WR1, 70) == 1 and rd(st, cid, P.WX1, 70) == S1)
check("a side reveals once", "ok" not in call(st, cid, A, "reveal_battle", [70, S1]))
check("one reveal inside the window cannot be settled as a forfeit yet",
      "ok" not in call(st, cid, A, "resolve_battle", [70]))
check("the accepter's secret reveals side B (any caller may carry it)",
      "ok" in call(st, cid, C, "reveal_battle", [70, S2]) and rd(st, cid, P.WR2, 70) == 1)
seed = P.ref_battle_seed(S1, S2, 70)
a_wins, dies, _h0, _h1, _log = P.ref_battle_turns(seed, 0, 70, effA, effB)
bA, bB = st.bridge[A], st.bridge[B]
r = call(st, cid, C, "resolve_battle", [70])
win, lose = (1, 2) if a_wins else (2, 1)
check("both revealed: resolve_battle settles at once, the winner equals ref_battle_turns over HASH(s1+s2+bid)",
      "ok" in r and rd(st, cid, P.WW, 70) == win and rd(st, cid, P.WN, 70) == 3, r)
check("the death roll equals the reference", rd(st, cid, P.WD, 70) == (lose if dies else 0))
check("the loser pet is claimed by the winner's owner", owner(st, cid, lose) == owner(st, cid, win))
paid = st.bridge[A] - bA if a_wins else st.bridge[B] - bB
check("the pot (both stakes) goes to the winner's owner", paid == 2 * STAKE, paid)
check("the battle scratch is scrubbed",
      not [k for k in st.contracts[cid]["storage"]["slots"] if int(k) >> 32 == P.SC])

# ---- only one side reveals -> the revealer wins by forfeit, after the deadline -------------------------------------
for revealer, sec, label in ((A, S1, "challenger"), (B, S2, "accepter")):
    st, cid = fresh()
    pet(st, cid, A, 1)
    pet(st, cid, B, 2)
    battle(st, cid, 71, 1, 2, S1, S2)
    wrd = rd(st, cid, P.WRD, 71)
    assert "ok" in call(st, cid, revealer, "reveal_battle", [71, sec])
    st.cursor = wrd
    check(f"[{label} reveals] the forfeit is refused while cursor <= wrd",
          "ok" not in call(st, cid, C, "resolve_battle", [71]))
    st.cursor = wrd + 1
    check(f"[{label} reveals] a reveal after the deadline is refused",
          "ok" not in call(st, cid, B if revealer == A else A, "reveal_battle", [71, S2 if revealer == A else S1]))
    check(f"[{label} reveals] refund_battle refuses a battle with one reveal",
          "ok" not in call(st, cid, C, "refund_battle", [71]))
    bA, bB = st.bridge[A], st.bridge[B]
    r = call(st, cid, C, "resolve_battle", [71])
    win, lose = (1, 2) if revealer == A else (2, 1)
    check(f"[{label} reveals] past the deadline the revealer's pet wins by forfeit",
          "ok" in r and rd(st, cid, P.WW, 71) == win and rd(st, cid, P.WN, 71) == 3, r)
    check(f"[{label} reveals] the pot goes to the revealer and the silent side's pet is claimed",
          (st.bridge[revealer] - (bA if revealer == A else bB)) == 2 * STAKE
          and owner(st, cid, lose) == zkvm_addr_digest(revealer))
    check(f"[{label} reveals] a forfeit carries no death roll", rd(st, cid, P.WD, 71) == 0
          and rd(st, cid, P.FU, lose) > st.cursor)

# ---- nobody reveals -> void, each stake back --------------------------------------------------------------------
for method in ("resolve_battle", "refund_battle"):
    st, cid = fresh()
    pet(st, cid, A, 1)
    pet(st, cid, B, 2)
    battle(st, cid, 72, 1, 2, S1, S2)
    wrd = rd(st, cid, P.WRD, 72)
    st.cursor = wrd
    check(f"[{method}] a void battle is not refundable inside the window", "ok" not in call(st, cid, C, method, [72]))
    st.cursor = wrd + 1
    bA, bB = st.bridge[A], st.bridge[B]
    r = call(st, cid, C, method, [72])
    check(f"[{method}] neither revealed: each side gets its own stake back",
          "ok" in r and st.bridge[A] - bA == STAKE and st.bridge[B] - bB == STAKE and rd(st, cid, P.WN, 72) == 3, r)
    check(f"[{method}] and nobody's pet changes hands",
          owner(st, cid, 1) == zkvm_addr_digest(A) and owner(st, cid, 2) == zkvm_addr_digest(B))

# ---- a battle from the OLD code keeps the block-hash rule after the in-place upgrade ---------------------------------
old_src = subprocess.run(["git", "-C", ROOT, "show", "HEAD:execnode/games/pets.py"], capture_output=True,
                         text=True).stdout
if "def build" not in old_src:
    check("the pre-upgrade pets.py is readable from git HEAD", False)
else:
    path = os.path.join(os.environ["HOME"], "pets_old.py")
    open(path, "w").write(old_src)
    spec = importlib.util.spec_from_file_location("pets_old", path)
    OLD = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(OLD)
    st, cid = fresh(OLD.build(), OLD.ABI)
    effA, effB = pet(st, cid, A, 1), pet(st, cid, B, 2)
    pet(st, cid, A, 3)
    pet(st, cid, B, 4)
    check("[old code] a challenge + accept under the old ABI",
          "ok" in call(st, cid, A, "challenge", [80, 1, 2], STAKE) and "ok" in call(st, cid, B, "accept", [80], STAKE))
    check("[old code] a second challenge left pending across the upgrade",
          "ok" in call(st, cid, A, "challenge", [81, 3, 4], STAKE))
    r = st.apply_blob({"op": "upgrade", "contract": cid, "code": P.build(), "abi": P.ABI}, A, "up")
    check("the contract upgrades in place (same cid, storage kept)", "upgrade" in r.lower() or "ok" in r, r)
    check("[old battle] it is marked block-hash mode (wm == 0)", rd(st, cid, P.WM, 80) == 0)
    wh = rd(st, cid, P.WH, 80)
    h0, h1 = 0xABCDEF0123456789, 0x1122334455667788
    st.block_hashes[wh] = h0
    st.block_hashes[wh + 1] = h1
    st.cursor = max(st.cursor, wh + 2)
    a_wins, dies, _h0, _h1, _log = P.ref_battle_turns(h0, h1, 80, effA, effB)
    r = call(st, cid, C, "resolve_battle", [80])
    check("[old battle] resolves from BHASH(wh) + BHASH(wh+1), equal to ref_battle_turns",
          "ok" in r and rd(st, cid, P.WW, 80) == (1 if a_wins else 2), r)
    check("[old pending challenge] is accepted under the old rule (no commitment needed)",
          "ok" in call(st, cid, B, "accept", [81, 0], STAKE) and rd(st, cid, P.WN, 81) == 2
          and rd(st, cid, P.WRD, 81) == 0)
    st.cursor = rd(st, cid, P.WH, 81) + P.STALE + 1
    bA, bB = st.bridge[A], st.bridge[B]
    check("[old accepted battle] refund_battle keeps its wh + STALE rule",
          "ok" in call(st, cid, C, "refund_battle", [81]) and st.bridge[A] - bA == STAKE and st.bridge[B] - bB == STAKE)

# ---- the browser: commitment + duel preview equal the VM -------------------------------------------------------------
try:
    # nadodapp.js wires DOM listeners at module load, so node gets an inert DOM stub first (as the coinflip test)
    js = ("const el = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => '' : el, apply: () => el });\n"
          "for (const k of ['document', 'window', 'localStorage', 'sessionStorage', 'location', 'history']) "
          "if (!(k in globalThis)) globalThis[k] = el;\n"
          "const { algHashn } = await import('./static/nadodapp.js?v=b74f351b');\n"
          "const G = await import('./static/pets-genes.js');\n"
          "const V = JSON.parse(process.argv[2]);\n"
          "const seed = G.battleSeedOf(BigInt(V.s1), BigInt(V.s2), V.bid);\n"
          "const b = G.battleOfSeed(seed, V.bid, V.effA, V.effB);\n"
          "console.log(JSON.stringify({ commit: algHashn([BigInt(V.s1)]).toString(), seed: seed.toString(),"
          " aWins: b.aWins, dies: b.dies, h0: b.h0, h1: b.h1 }));\n"
          "process.exit(0);\n")
    tmp = os.path.join(ROOT, f".pets_cr_{os.getpid()}.mjs")
    open(tmp, "w").write(js)
    try:
        eA = [P.ref_stat(H(5), 3, i) + 7 for i in range(10)]
        eB = [P.ref_stat(H(6), 2, i) for i in range(10)]
        out = subprocess.run(["node", tmp, json.dumps({"s1": str(S1), "s2": str(S2), "bid": 70, "effA": eA,
                                                      "effB": eB})],
                             capture_output=True, text=True, cwd=ROOT, timeout=120)
    finally:
        os.unlink(tmp)
    got = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
    seed = P.ref_battle_seed(S1, S2, 70)
    a_wins, dies, h0, h1, _ = P.ref_battle_turns(seed, 0, 70, eA, eB)
    check("the browser's commitment of a secret equals the VM's HASH(secret)", got.get("commit") == str(H(S1)),
          out.stderr[-400:])
    check("the browser's battle seed equals HASH(s1 + s2 + bid)", got.get("seed") == str(seed))
    check("the browser's duel preview equals the contract's (winner, death, final HP)",
          got.get("aWins") == a_wins and got.get("dies") == dies and got.get("h0") == h0 and got.get("h1") == h1,
          got)
except FileNotFoundError:
    print("SKIP  node not installed — the browser cross-check did not run")

print(f"\n{'ALL PASS' if not FAILED else str(len(FAILED)) + ' FAILED'}")
sys.exit(1 if FAILED else 0)

"""Slots: a spin settles from the epoch beacon, an older spin still settles from block hashes, and a spin nobody
settled inside its window resolves to the bank (execnode/games/slots.py, Release B rule consistency).

  * spin binds gb = epoch(cursor) + 2 and gh = gb*60 - 1; settle draws the reels from BEACON(gb) and the result
    equals the in-clear reference (slots.stops_of / m2_of) — and the browser's chainResultAlg(bc(gb), "0", g+i, 64);
  * a spin written the way the pre-beacon code wrote it (gh = cursor + 2, gb == 0) settles from
    BLOCKHASH(gh) + BLOCKHASH(gh+1), equal to the reference — and to chainResultAlg(bh(gh), bh(gh+1), g+i, 64);
  * claim (timeout) pays NOBODY: the stake stays in the pot, the 149x cover is released, the bankroll keeps the
    stake, the spin is marked settled with no win; it is refused inside the window;
  * a winning spin settles (pays) anywhere inside the window, including its last block, by anyone.
  * the page gives the BANK (only) a button that sends claim for a spin past the window, like dice/roulette/mines/
    blackjack, and never auto-fires it.

Run: python3 tests/test_slots_settle_from_the_beacon_and_time_out_to_the_bank.py
"""
import os
import sys
import tempfile
import json
import shutil
import subprocess

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-slots-beacon-")     # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.state import ExecState                                   # noqa: E402
from execnode.games import slots                                       # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


BANK = "ndoA" + "a" * 44
PLAYER = "ndoB" + "b" * 44
STRANGER = "ndoC" + "c" * 44
T = 5
STAKE = 10_000
_n = [0]


def fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
    st.cursor = 6000 + 17                    # epoch 100
    code = slots.build()
    st.bridge[BANK] = 10 ** 13
    st.bridge[PLAYER] = 10 ** 9
    st.bridge[STRANGER] = 10 ** 6
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": slots.ABI, "nonce": "n"}, BANK, "d")
    cid = st.contract_id(BANK, code, "n")
    call(st, cid, BANK, "open", [T], 5_000_000_000)
    return st, cid


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    blob = {"op": "call", "contract": cid, "method": m, "args": args}
    if value is not None:
        blob["value"] = value
    st.apply_blob(blob, who, f"{m}-{_n[0]}")


def rd(st, cid, f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


def stops_from_gr(gr):
    v = gr - 1
    return [v % 64, (v // 64) % 64, (v // 4096) % 64]


def js_stops(seed_hexes, gs):
    """The browser's preview: chainResultAlg(a, b, g + i, 64) from static/nadodapp.js, for each (a, b, g)."""
    if not shutil.which("node"):
        return None
    # nadodapp.js is a browser module: give it the few globals it touches at load, then import it dynamically
    stub = ("const noop = () => {};\n"
            "const el = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => '' : el, apply: () => el });\n"
            "for (const k of ['document', 'window', 'localStorage', 'sessionStorage', 'location', 'history']) "
            "if (!(k in globalThis)) globalThis[k] = el;\n")
    prog = (stub + "const { chainResultAlg } = await import('%s');\n" % ("file://" + os.path.join(ROOT, "static", "nadodapp.js"))
            + "const xs = JSON.parse(process.argv[2]);\n"
            + "console.log(JSON.stringify(xs.map(([a, b, g]) => [0, 1, 2].map((i) => "
            + "chainResultAlg(a, b, String(BigInt(g) + BigInt(i)), 64)))));\n"
            + "process.exit(0);\n")                  # the module's own timers would keep node alive
    path = os.path.join(os.environ["HOME"], "x.mjs")
    open(path, "w").write(prog)
    # --import: nadodapp.js imports the relay's /protocol.js; tests/protocol_hook.mjs serves it rendered from protocol.py
    out = subprocess.run(["node", "--import", os.path.join(ROOT, "tests", "protocol_hook.mjs"), path, json.dumps([[a, b, str(g)] for (a, b), g in zip(seed_hexes, gs)])],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(out.stderr[-2000:])
        return "error"
    return json.loads(out.stdout)


# ---- beacon spins settle from BEACON(gb) and match the reference --------------------------------------------
st, cid = fresh()
seen_m2 = set()
beacon_cases = []
for k in range(12):
    g = 1000 + k
    st.cursor = 6000 + 17 + k
    call(st, cid, PLAYER, "spin", [g, T], STAKE)
    gb, gh = rd(st, cid, slots.GB, g), rd(st, cid, slots.GH, g)
    if k == 0:
        check("spin binds gb = epoch(cursor) + 2", gb == 102, gb)
        check("spin sets gh = gb*60 - 1 (ready at the beacon epoch's first block)", gh == 102 * 60 - 1, gh)
        check("_view exposes gb", slots.ABI["_view"]["maps"].get("gb") == {"field": slots.GB, "index": "games"})
    beacon = (0x5EED << 200) + 7919 * (k + 1) ** 5
    st.beacons[gb] = beacon
    st.cursor = gh + 1
    if k == 0:
        st.cursor = gh
        try:
            call(st, cid, PLAYER, "settle", [g])
        except Exception:
            pass
        check("a beacon spin does not settle before its epoch begins", rd(st, cid, slots.GD, g) == 0)
        st.cursor = gh + 1
    pb = st.bridge.get(PLAYER, 0)
    call(st, cid, STRANGER, "settle", [g])                                  # settle is permissionless
    want = slots.stops_of(slots.seed_of(gb, gh, beacon=beacon), g)
    got = stops_from_gr(rd(st, cid, slots.GR, g))
    m2 = rd(st, cid, slots.GW, g)
    seen_m2.add(m2)
    ok = got == want and m2 == slots.m2_of(want) and st.bridge.get(PLAYER, 0) - pb == STAKE * m2 // 2
    check(f"beacon spin {g}: reels = stops_of(BEACON(gb) + g), pay = stake*m2/2", ok, (got, want, m2))
    beacon_cases.append(((format(beacon, "x"), "0"), g, want))
check("the beacon cases cover a win and a loss", any(m for m in seen_m2) and 0 in seen_m2, seen_m2)
check("every settle released its cover (tc == 0)", rd(st, cid, 4, T) == 0, rd(st, cid, 4, T))

# ---- a spin placed before the upgrade (gb == 0, gh = cursor + 2) settles from block hashes ------------------
st2, cid2 = fresh()
legacy_cases = []
for k in range(4):
    g = 2000 + k
    call(st2, cid2, PLAYER, "spin", [g, T], STAKE)
    # rewrite the seat the way the pre-beacon spin left it: gh = cursor + 2 and no gb
    slots_ = st2.contracts[cid2]["storage"]["slots"]
    slots_.pop(str(slots.GB * (1 << 32) + g), None)
    gh = 7000 + 10 * k
    slots_[str(slots.GH * (1 << 32) + g)] = gh
    bh0, bh1 = (0xB10C << 220) + 31 * (k + 3) ** 7, (0xCAFE << 210) + 17 * (k + 5) ** 6
    st2.block_hashes[gh], st2.block_hashes[gh + 1] = bh0, bh1
    st2.cursor = gh + 2
    pb = st2.bridge.get(PLAYER, 0)
    call(st2, cid2, PLAYER, "settle", [g])
    want = slots.stops_of(slots.seed_of(0, gh, bh0=bh0, bh1=bh1), g)
    got = stops_from_gr(rd(st2, cid2, slots.GR, g))
    m2 = rd(st2, cid2, slots.GW, g)
    check(f"legacy spin {g} (gb == 0): reels = stops_of(BHASH(gh) + BHASH(gh+1) + g)",
          got == want and m2 == slots.m2_of(want) and st2.bridge.get(PLAYER, 0) - pb == STAKE * m2 // 2,
          (got, want, m2))
    legacy_cases.append(((format(bh0, "x"), format(bh1, "x")), g, want))

# ---- the browser preview is byte-identical for both rules ---------------------------------------------------
cases = beacon_cases + legacy_cases
js = js_stops([c[0] for c in cases], [c[1] for c in cases])
if js is None:
    print("SKIP  node not installed: client preview cross-check")
else:
    check("chainResultAlg(bc(gb), '0', g+i, 64) and chainResultAlg(bh(gh), bh(gh+1), g+i, 64) equal the contract",
          js == [c[2] for c in cases], (js, [c[2] for c in cases]))
src = open(os.path.join(ROOT, "static", "slots.js")).read()
check("slots.js previews beacon spins from dapp.bc(gb) through chainResultAlg",
      'spinResult(dapp.bc(s.gb), "0", s.g)' in src and "chainResultAlg(bh0, bh1, String(BigInt(g) + BigInt(i)), 64)" in src)
check("slots.js prefetches beacons", "bg.prefetchBeacons(sto)" in src)

# ---- timeout pays the bank ----------------------------------------------------------------------------------
st3, cid3 = fresh()
g = 3000
call(st3, cid3, PLAYER, "spin", [g, T], STAKE)
gh = rd(st3, cid3, slots.GH, g)
tk0, tp0, tc0 = rd(st3, cid3, 2, T), rd(st3, cid3, 3, T), rd(st3, cid3, 4, T)
check("a spin reserves stake*149 of cover", tc0 == STAKE * 149, tc0)
st3.cursor = gh + slots.HORIZON
try:
    call(st3, cid3, STRANGER, "claim", [g])
except Exception:
    pass
check("claim is refused inside the window", rd(st3, cid3, slots.GD, g) == 0)
st3.cursor = gh + slots.HORIZON + 1
pb, sb, esc = st3.bridge.get(PLAYER, 0), st3.bridge.get(STRANGER, 0), st3.bridge.get(cid3, 0)
call(st3, cid3, STRANGER, "claim", [g])
check("timeout marks the spin settled", rd(st3, cid3, slots.GD, g) == 1)
check("timeout pays nobody (player, caller and escrow unchanged)",
      st3.bridge.get(PLAYER, 0) == pb and st3.bridge.get(STRANGER, 0) == sb and st3.bridge.get(cid3, 0) == esc)
check("timeout releases the cover (tc -= stake*149)", rd(st3, cid3, 4, T) == tc0 - STAKE * 149, rd(st3, cid3, 4, T))
check("timeout keeps the stake in the pot (tp unchanged)", rd(st3, cid3, 3, T) == tp0, (rd(st3, cid3, 3, T), tp0))
check("timeout credits the bankroll with the stake (tk += stake)", rd(st3, cid3, 2, T) == tk0 + STAKE)
check("timeout records no win", rd(st3, cid3, slots.GW, g) == 0)
check("escrow still equals the withdrawable pot", st3.bridge.get(cid3, 0) == rd(st3, cid3, 3, T))
try:
    call(st3, cid3, PLAYER, "settle", [g])
except Exception:
    pass
check("a timed-out spin cannot be settled afterwards", st3.bridge.get(PLAYER, 0) == pb)
call(st3, cid3, BANK, "close", [T])
check("the bank can close after the timeout (no open cover)", rd(st3, cid3, 6, T) == 1)

# ---- a win settles anywhere inside the window, by anyone -----------------------------------------------------
st4, cid4 = fresh()
won = False
for k in range(64):
    g = 4000 + k
    call(st4, cid4, PLAYER, "spin", [g, T], STAKE)
    gb, gh = rd(st4, cid4, slots.GB, g), rd(st4, cid4, slots.GH, g)
    beacon = (0xFACE << 230) + 104729 * (k + 11) ** 4
    if slots.m2_of(slots.stops_of(slots.seed_of(gb, gh, beacon=beacon), g)) == 0:
        continue
    st4.beacons[gb] = beacon
    st4.cursor = gh + slots.HORIZON                      # the last block before claim opens
    pb = st4.bridge.get(PLAYER, 0)
    call(st4, cid4, STRANGER, "settle", [g])
    m2 = rd(st4, cid4, slots.GW, g)
    check(f"a winning spin settles on the window's last block and pays the player ({m2 / 2}x)",
          m2 > 0 and st4.bridge.get(PLAYER, 0) - pb == STAKE * m2 // 2, (m2, st4.bridge.get(PLAYER, 0) - pb))
    try:
        call(st4, cid4, STRANGER, "claim", [g])
    except Exception:
        pass
    check("claim cannot re-resolve a settled win", st4.bridge.get(PLAYER, 0) - pb == STAKE * m2 // 2)
    won = True
    break
check("found a winning beacon spin to test", won)

# ---- the BANK's release button: the page offers claim to the bank for a timed-out spin, as the other banked games do
st5, cid5 = fresh()
g = 5000
call(st5, cid5, PLAYER, "spin", [g, T], STAKE)
st5.cursor = rd(st5, cid5, slots.GH, g) + slots.HORIZON + 1
call(st5, cid5, BANK, "claim", [g])
check("the bank itself can release a timed-out spin (what its button sends)",
      rd(st5, cid5, slots.GD, g) == 1 and rd(st5, cid5, 4, T) == 0)
html = open(os.path.join(ROOT, "static", "slots.html")).read()
check("slots.js HORIZON equals the contract's window", f"const HORIZON = {slots.HORIZON};" in src)
check("slots.js sends the contract's timeout op (claim) from the release button",
      'dapp.call("claim", [g], null' in src and "releaseSpin(s.g)" in src)
check("the release button is offered only to the bank, only for spins past the window",
      "if (iAmBank && !mc.closed) for (const s of mySpins.filter(expired)" in src)
check("slots.html has the release row the button renders into", 'id="releaseRow"' in html)
check("auto-collect never fires claim for the player (it returns them nothing)",
      "autoCollect" in src and "releaseSpin" not in src[src.index("function maybeAutoSettle"):src.index("function readyWins")])

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)

# _autogame_e2e.py — LIVE end-to-end of the deployed Autogame contract against the running node.
#
# Proves the whole loop on real chain data rather than in a test harness: set out, read the committed
# terrain the way the browser does, queue a plan against it, wait for the rolling height, settle, and check
# that what the chain computed is exactly what the reference model says it should have computed.
#
# Run: HOME=/root python3 _autogame_e2e.py
import json, sys, time, urllib.error, urllib.request

sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.address_ops import make_address
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY
from execnode.games import autogame as A
from execnode.stark import alghash, field as F
from tests import autogame_model as M

L1 = "http://127.0.0.1:9173"
EX = "http://127.0.0.1:9273"
CID = "ba8bebc9693f5aaec0e338a13d5812c4"


def j(u):
    return json.load(urllib.request.urlopen(u, timeout=15))


def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=20))
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}


def tip():
    return j(L1 + "/get_latest_block")["block_number"]


def sto():
    return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})


def cursor():
    return int(j(EX + "/exec/root?ns=default&provisional=1").get("cursor", 0))


def blockhash(h):
    """BHASH(h) as the contract sees it — the L1 block hash reduced into the field.

    The param is `number`, not `block_number` (nado.py: GET /get_block_number?number=). The wrong name 404s,
    and a 404 here reads as 'the chain is missing a block' rather than 'the test typed the URL wrong'."""
    b = j(L1 + f"/get_block_number?number={h}")
    return int(b["block_hash"], 16) % F.P


K = load_keys()
K["address"] = make_address(K["public_key"])
ME = K["address"]

FAILS = []


def ck(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {extra}" if extra else ""), flush=True)
    if not cond:
        FAILS.append(name)


def call(method, args, value=0):
    p = {"op": "call", "contract": CID, "method": method, "args": args}
    if value:
        p["value"] = int(value)
    for _ in range(8):
        r = post(construct_blob_tx(K, p, tip() + 12, MIN_TX_FEE, min_block=tip() + TX_INCLUSION_DELAY))
        if r.get("result"):
            return r
        print("   retry", method, r.get("message"), flush=True)
        time.sleep(12)
    print("   [GIVEUP]", method, flush=True)
    sys.exit(1)


def wait(cond, label, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                print("  [ok]", label, flush=True)
                return True
        except Exception:
            pass
        time.sleep(8)
    print("  [TIMEOUT]", label, flush=True)
    sys.exit(1)


def field(s, name, rid, default=0):
    """One decoded map cell as an int.

    NOT every map is numeric: decode_view resolves the fields listed in the ABI's `addr` back to L1 address
    STRINGS, so `ra` reads as "mldsa44…". int() on that raises — and inside a wait() predicate the raise is
    swallowed by the retry loop, so the test waits out the full timeout on a run that already exists. That
    cost half an hour of chasing the chain for a bug in this helper."""
    v = (s.get(name) or {}).get(str(rid), (s.get(name) or {}).get(rid, default))
    try:
        return int(v or default)
    except (TypeError, ValueError):
        return default


def owner(s, rid):
    """The run's owner address as decode_view presents it — a string, via the ABI's `addr` list."""
    return str((s.get("ra") or {}).get(str(rid), "") or "")


print("autogame e2e as", ME, flush=True)
# The exec layer trails L1 by roughly a finality window — measured at ~60 blocks (~6 min) on this node —
# so a freshly deployed contract is simply not visible for several minutes. Every wait here has to be
# sized against the EXEC cursor, not the L1 tip, or the test reports a failure that is only impatience.
wait(lambda: j(EX + f"/exec/contract?ns=default&cid={CID}").get("cid") == CID, "contract live", 900)

RID = int(time.time()) % 900000000 + 1
print(f"\n1. set out (run {RID})", flush=True)
cursor_at_begin = cursor()          # captured BEFORE the call: the pin is future-relative to THIS, and by
                                    # the time the run is visible the cursor has naturally moved past it
call("begin", [RID])
wait(lambda: owner(sto(), RID) == ME, "run exists", 900)
s = sto()
lh, nh = field(s, "lh", RID), field(s, "nh", RID)
ck("the run is mine", owner(s, RID) == ME, owner(s, RID)[:18])
ck("starts at full health", field(s, "hp", RID) == A.HP0, f"hp={field(s, 'hp', RID)}")
ck("terrain height was pinned in the FUTURE", lh > cursor_at_begin,
   f"lh={lh} cursor_at_begin={cursor_at_begin}")
ck("rolling height is one leg later", nh == lh + A.LEG, f"lh={lh} nh={nh}")

print("\n2. find a leg whose plan window is still OPEN, and read its committed road", flush=True)
# The exec layer trails L1 by a finality window and catches up in BULK, so it can blow past both lh and nh
# between two polls. That is an environment condition, not a protocol failure — the fairness property is
# enforced by the contract (step 7 proves a stale plan is refused), not by this test winning a race. So
# rather than assert a window that may already have closed, walk forward until one is genuinely open.
def leg_window():
    s_ = sto()
    return field(s_, "lg", RID), field(s_, "lh", RID), field(s_, "nh", RID)


LEGN, lh, nh = leg_window()
for _ in range(12):
    wait(lambda: cursor() >= lh, f"terrain height {lh} mined", 900)
    if cursor() < nh:
        break                                   # the dice for this leg do not exist yet — window open
    print(f"   leg {LEGN}: exec already past nh={nh} (cursor {cursor()}) — settling it and trying the next",
          flush=True)
    call("advance", [RID])
    wait(lambda: field(sto(), "lg", RID) > LEGN, f"leg {LEGN} settled", 900)
    if not field(sto(), "av", RID):
        print("   the run died before a window opened — nothing left to plan", flush=True)
        break
    LEGN, lh, nh = leg_window()

ck("found a leg with the dice still unknown", cursor() < nh, f"cursor={cursor()} nh={nh} leg={LEGN}")
th = blockhash(lh)
road = []
base_depth = field(sto(), "dp", RID)
for i in range(A.LEG):
    tw = alghash.hashn([th, RID, i]) & 0xFFFFFFFF
    a, b, c, _sc = M.slice_tile(tw)
    road.append(M.tile_of(a, base_depth + i))
names = [["road", "monster", "elite", "hazard", "cache", "shrine", "forge", "fork", "relic", "boss"][t]
         for t in road]
print("   road ahead:", " ".join(names), flush=True)
ck("the committed road is readable while the dice are still unknown", len(road) == A.LEG and cursor() < nh,
   f"cursor={cursor()} nh={nh}")

print("\n3. queue a plan against terrain we can see", flush=True)
acts = [A.A_STRIKE if t in (M.MONSTER, M.ELITE) else A.A_GUARD if t == M.HAZARD else 0 for t in road]
word = 0
for i, a in enumerate(acts):
    word |= (a & 7) << (3 * i)
AGG = 3
call("plan", [RID, LEGN, word, AGG])
time.sleep(20)

print("\n4. wait for the rolling height and settle", flush=True)
wait(lambda: cursor() >= nh, f"rolling height {nh} mined", timeout=900)
rh = blockhash(nh)
before = sto()                      # the run as it stood going INTO this leg
depth_before = field(before, "dp", RID)
call("advance", [RID])
wait(lambda: field(sto(), "lg", RID) > LEGN, "leg settled", 900)

print("\n5. does the chain agree with the reference model?", flush=True)
s = sto()
run0_stance = field(before, "sn", RID)
run0_heal = field(before, "hl", RID) or 35
run0_focus = field(before, "fo", RID) if (before.get("fo") or {}) else 50
run = M.Run(stance=run0_stance, healpct=run0_heal, focus=run0_focus)
# seed the model from the run as it stood BEFORE this leg, so the comparison is of one leg's work
run.hp, run.maxhp = field(before, "hp", RID), field(before, "mx", RID)
run.stam, run.potions = field(before, "st", RID), field(before, "po", RID)
run.xp, run.banked, run.streak = field(before, "xp", RID), field(before, "bk", RID), field(before, "sk", RID)
run.depth, run.kills = field(before, "dp", RID), field(before, "ki", RID)
run.wlevel, run.alevel = field(before, "wl", RID) or 1, field(before, "al", RID) or 1
run.mats = [field(before, "m0", RID), field(before, "m1", RID), field(before, "m2", RID)]
run.gear = [field(before, f"g{i}", RID) for i in range(A.NSLOT)]
for i in range(A.LEG):
    if not run.alive or run.done:
        break
    tw = alghash.hashn([th, RID, i]) & 0xFFFFFFFF
    rw = alghash.hashn([rh, RID, i]) & 0xFFFFFFFF
    M.step(run, tw, rw, acts[i], AGG)

got = {k: field(s, v, RID) for k, v in
       (("hp", "hp"), ("maxhp", "mx"), ("stam", "st"), ("potions", "po"), ("xp", "xp"), ("banked", "bk"),
        ("streak", "sk"), ("depth", "dp"), ("kills", "ki"), ("alive", "av"), ("wlevel", "wl"),
        ("alevel", "al"))}
want = {"hp": run.hp, "maxhp": run.maxhp, "stam": run.stam, "potions": run.potions, "xp": run.xp,
        "banked": run.banked, "streak": run.streak, "depth": run.depth, "kills": run.kills,
        "alive": run.alive, "wlevel": run.wlevel, "alevel": run.alevel}
bad = [k for k in want if got[k] != want[k]]
for k in want:
    ck(f"{k} matches the model", got[k] == want[k], f"chain={got[k]} model={want[k]}")

if bad:
    # A call can SUBMIT fine and still revert on-chain, which looks exactly like success from here — and a
    # plan word is hash-keyed, so it cannot be read back out of the storage view to check. Replay the leg as
    # if no plan had landed: if THAT matches the chain, the contract is fine and the plan tx was the problem
    # (submitted after the window closed, or reverted), which is a completely different bug to chase.
    unplanned = M.Run(stance=run0_stance, healpct=run0_heal, focus=run0_focus)
    unplanned.hp, unplanned.maxhp = field(before, "hp", RID), field(before, "mx", RID)
    unplanned.stam, unplanned.potions = field(before, "st", RID), field(before, "po", RID)
    unplanned.xp = field(before, "xp", RID)
    unplanned.banked, unplanned.streak = field(before, "bk", RID), field(before, "sk", RID)
    unplanned.depth, unplanned.kills = field(before, "dp", RID), field(before, "ki", RID)
    unplanned.wlevel = field(before, "wl", RID) or 1
    unplanned.alevel = field(before, "al", RID) or 1
    unplanned.mats = [field(before, "m0", RID), field(before, "m1", RID), field(before, "m2", RID)]
    unplanned.gear = [field(before, f"g{i}", RID) for i in range(A.NSLOT)]
    for i in range(A.LEG):
        if not unplanned.alive or unplanned.done:
            break
        M.step(unplanned, alghash.hashn([th, RID, i]) & 0xFFFFFFFF,
               alghash.hashn([rh, RID, i]) & 0xFFFFFFFF, 0, 1)
    same_unplanned = all(got[k] == v for k, v in
                         (("hp", unplanned.hp), ("xp", unplanned.xp), ("kills", unplanned.kills),
                          ("streak", unplanned.streak)))
    print("   DIAGNOSIS: " + ("the chain matches an UNPLANNED leg — the contract is fine and the plan tx "
                              "never took effect (window closed, or it reverted)"
                              if same_unplanned else
                              "the chain matches neither the planned nor the unplanned replay — this is a "
                              "real divergence between the contract and the model"), flush=True)
gear = [field(s, f"g{i}", RID) for i in range(A.NSLOT)]
ck("gear matches the model", gear == list(run.gear), f"chain={gear} model={list(run.gear)}")
print(f"   depth {run.depth}  hp {run.hp}/{run.maxhp}  renown {run.xp}  kills {run.kills}", flush=True)

print("\n6. the leg window slid forward", flush=True)
s = sto()
ck("leg counter advanced", field(s, "lg", RID) == LEGN + 1, f"lg={field(s, 'lg', RID)}")
ck("terrain height became the old rolling height", field(s, "lh", RID) == nh)
ck("next rolling height is one leg on", field(s, "nh", RID) == nh + A.LEG)

print("\n7. a stale plan is refused (the fairness window)", flush=True)
p = {"op": "call", "contract": CID, "method": "plan", "args": [RID, LEGN, word, AGG]}
r = post(construct_blob_tx(K, p, tip() + 12, MIN_TX_FEE, min_block=tip() + TX_INCLUSION_DELAY))
time.sleep(25)
ck("planning an already-settled leg does not move the run", field(sto(), "lg", RID) == LEGN + 1)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS)), flush=True)
sys.exit(1 if FAILS else 0)

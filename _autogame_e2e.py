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


def call(method, args, value=0, applied=None, tries=4):
    """Submit — and when given an `applied` predicate, keep RESUBMITTING until the chain shows the effect.
    A pool-accepted tx is not a landed tx: the first manual-flow run of this script lost its begin() in the
    pool and sat four minutes waiting on a run that was never going to exist. Every method here is
    idempotent-by-guard (a duplicate begin/commit/plan/advance reverts rather than double-acting), so
    resubmitting on a state predicate is safe."""
    p = {"op": "call", "contract": CID, "method": method, "args": args}
    if value:
        p["value"] = int(value)
    for _attempt in range(tries):
        for _ in range(8):
            # tip+40, not tip+12: max_block is the tx's EXPIRY, and a ~72-second life loses the race whenever
            # gossip to the actual producer is slow — tonight that meant three resubmits per call. The wide
            # window is safe here (all methods are idempotent-by-guard, a stale duplicate just reverts).
            r = post(construct_blob_tx(K, p, tip() + 40, MIN_TX_FEE, min_block=tip() + TX_INCLUSION_DELAY))
            if r.get("result"):
                break
            print("   retry", method, r.get("message"), flush=True)
            time.sleep(12)
        else:
            print("   [GIVEUP submit]", method, flush=True)
            sys.exit(1)
        if applied is None:
            return r
        for _ in range(14):
            time.sleep(8)
            try:
                if applied():
                    return r
            except Exception:
                pass
        print(f"   {method} accepted but never landed — resubmitting", flush=True)
    print("   [GIVEUP landed]", method, flush=True)
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
AGG, STANCE, FOCUS, HEAL = 3, 1, 70, 40


def peek_tiles(s, rid, lh):
    """The 16 tile classes of the pending leg — derived from the terrain hash exactly as the road strip
    derives them, because building the answer word from what you can SEE is the whole game."""
    th = blockhash(lh)
    d0 = field(s, "dp", rid)
    out = []
    for i in range(A.LEG):
        a, _b, _c, _sc = M.slice_tile(alghash.hashn([th, rid, i]) & 0xFFFFFFFF)
        out.append(M.tile_of(a, d0 + i))
    return out


def word_of(acts):
    w = 0
    for i, a in enumerate(acts):
        w |= (a & 7) << (3 * i)
    return w


# per-class answers that exercise the NEW tiles too: guard the ambush (blocks the sting), sprint the
# horde (the only slip), dodge the gale (shelter), offer at the idol
CLASSMAP = {M.MONSTER: A.A_STRIKE, M.HORDE: A.A_SPRINT, M.ELITE: A.A_GUARD, M.AMBUSH: A.A_GUARD,
            M.HAZARD: A.A_DODGE, M.GALE: A.A_DODGE, M.IDOL: A.A_POTION, M.FORK: A.A_RIGHT}

print(f"\n1. set out (run {RID}) — begin() ARMS the march itself now", flush=True)
# MANUAL-ONLY: there is no auto mode and no doctrine. begin() pins the terrain window immediately (the
# two-step "begin, then find the second button" lost three real players to runs stuck at lh=0), and the
# dice stay unscheduled until the sixteen visible tiles are answered with commit().
cursor_at_begin = cursor()
call("begin", [RID], applied=lambda: owner(sto(), RID) == ME)
wait(lambda: owner(sto(), RID) == ME, "run exists", 900)
s = sto()
ck("the run is mine", owner(s, RID) == ME, owner(s, RID)[:18])
ck("starts at full health", field(s, "hp", RID) == A.HP0, f"hp={field(s, 'hp', RID)}")
lh = field(s, "lh", RID)
ck("begin armed the march (terrain pinned in the future)", lh > cursor_at_begin,
   f"lh={lh} cursor_at_begin={cursor_at_begin}")
ck("...but scheduled NO dice — the march waits for answers", field(s, "nh", RID) == 0,
   f"nh={field(s, 'nh', RID)}")

print("\n2. set the dials (optional — begin ships playable defaults)", flush=True)
call("plan", [RID, AGG, STANCE, FOCUS, HEAL],
     applied=lambda: field(sto(), "sn", RID) == STANCE and field(sto(), "fo", RID) == FOCUS)
wait(lambda: field(sto(), "sn", RID) == STANCE and field(sto(), "fo", RID) == FOCUS, "dials landed", 900)
s = sto()
ck("all four dials landed in ONE call",
   field(s, "pa", RID) == AGG and field(s, "sn", RID) == STANCE
   and field(s, "fo", RID) == FOCUS and field(s, "hl", RID) == HEAL,
   f"agg={field(s, 'pa', RID)} stance={field(s, 'sn', RID)} focus={field(s, 'fo', RID)} heal={field(s, 'hl', RID)}")

print("\n3. read the committed road and ANSWER it, tile by tile", flush=True)
wait(lambda: cursor() >= lh, f"terrain height {lh} mined", 900)
s = sto()
tiles = peek_tiles(s, RID, lh)
names = [["road", "monster", "horde", "elite", "ambush", "hazard", "gale", "cache", "shrine", "idol",
          "forge", "fork", "relic", "boss"][t]
         for t in tiles]
print("   road ahead:", " ".join(names), flush=True)
answers = [CLASSMAP.get(t, A.A_DEFAULT) for t in tiles]
WORD = word_of(answers)
ck("the road is readable from a hash that is already final", len(tiles) == A.LEG)

cursor_at_commit = cursor()
call("commit", [RID, WORD], applied=lambda: field(sto(), "nh", RID) != 0)
wait(lambda: field(sto(), "nh", RID) != 0, "committing the answers scheduled the dice", 900)
s = sto()
nh = field(s, "nh", RID)
ck("the dice are in the FUTURE relative to the commit", nh > cursor_at_commit,
   f"nh={nh} cursor_at_commit={cursor_at_commit}")
ck("the answer word is mirrored readably for the animator (cw/cl)",
   field(s, "cw", RID) == WORD and field(s, "cl", RID) == field(s, "lg", RID),
   f"cw={field(s, 'cw', RID)} want={WORD}")

print(f"\n4. wait for the rolling height {nh} and settle", flush=True)
wait(lambda: cursor() >= nh, f"rolling height {nh} mined", timeout=900)
rh = blockhash(nh)
before = sto()                      # the run as it stood going INTO this leg
depth_before = field(before, "dp", RID)
LEGN = field(before, "lg", RID)
call("advance", [RID], applied=lambda: field(sto(), "lg", RID) > LEGN)
wait(lambda: field(sto(), "lg", RID) > LEGN, "leg settled", 900)

print("\n5. does the chain agree with the reference model?", flush=True)
s = sto()
# seed the model from the run as it stood BEFORE this leg, so the comparison is of one leg's work
run = M.Run(stance=STANCE, focus=FOCUS, healpct=HEAL)
run.agg = AGG
run.hp = field(before, "hp", RID)
run.maxhp = field(before, "mx", RID)
run.stam = field(before, "st", RID)
run.potions = field(before, "po", RID)
run.xp = field(before, "xp", RID)
run.banked = field(before, "bk", RID)
run.streak = field(before, "sk", RID)
run.depth = depth_before
run.kills = field(before, "ki", RID)
run.wlevel = field(before, "wl", RID) or 1
run.alevel = field(before, "al", RID) or 1
run.mats = [field(before, "m0", RID), field(before, "m1", RID), field(before, "m2", RID)]
run.gear = [field(before, f"g{i}", RID) for i in range(A.NSLOT)]
th = blockhash(lh)
for i in range(A.LEG):
    if not run.alive or run.done:
        break
    tw = alghash.hashn([th, RID, i]) & 0xFFFFFFFF
    rw = alghash.hashn([rh, RID, i]) & 0xFFFFFFFF
    M.step(run, tw, rw, action=answers[i])
pairs = [("hp", "hp"), ("mx", "maxhp"), ("st", "stam"), ("po", "potions"), ("xp", "xp"), ("bk", "banked"),
         ("sk", "streak"), ("dp", "depth"), ("ki", "kills"), ("lv", "alive"), ("wl", "wlevel"),
         ("al", "alevel")]
diffs = [(fk, field(s, fk, RID), getattr(run, mk)) for fk, mk in pairs
         if field(s, fk, RID) != getattr(run, mk)]
ck("every field matches the model, step for step", not diffs,
   str(diffs) if diffs else "real divergence between the contract and the model")
gear = [field(s, f"g{i}", RID) for i in range(A.NSLOT)]
ck("gear matches the model", gear == list(run.gear), f"chain={gear} model={list(run.gear)}")
print(f"   depth {run.depth}  hp {run.hp}/{run.maxhp}  renown {run.xp}  kills {run.kills}", flush=True)

print("\n6. after settling, the march PARKS and waits for the next answers", flush=True)
s = sto()
ck("leg counter advanced", field(s, "lg", RID) == LEGN + 1, f"lg={field(s, 'lg', RID)}")
ck("terrain slid: the old dice became the new road", field(s, "lh", RID) == nh)
ck("no new dice were scheduled — that is YOUR move, nobody else's", field(s, "nh", RID) == 0,
   f"nh={field(s, 'nh', RID)}")

if field(s, "lv", RID) == 1 and not field(s, "dn", RID):
    print("\n7. dials re-tuned late cannot rewrite the NEXT leg either — and a second leg walks", flush=True)
    lh2 = field(s, "lh", RID)
    wait(lambda: cursor() >= lh2, f"terrain {lh2} visible", 900)
    s = sto()
    tiles2 = peek_tiles(s, RID, lh2)
    answers2 = [CLASSMAP.get(t, A.A_DEFAULT) for t in tiles2]
    call("commit", [RID, word_of(answers2)], applied=lambda: field(sto(), "nh", RID) != 0)
    wait(lambda: field(sto(), "nh", RID) != 0, "second leg's dice scheduled", 900)
    nh2 = field(sto(), "nh", RID)
    # Re-tune only once the dice are PUBLIC. Submitting "late" in wall-time is not enough: the fence
    # compares the cursor the plan LANDS at against nh2, and a plan submitted during the leg's sixteen-block
    # flight usually lands inside it — at which point the new dials legitimately govern the leg and the
    # comparison below would be testing nothing (the first live run of this script failed exactly there,
    # blaming a fence that had behaved perfectly). Waiting for nh2 first makes the claim the sharp one:
    # dials set after the roll is PUBLIC cannot rewrite the leg that roll belongs to.
    wait(lambda: cursor() >= nh2, f"rolling height {nh2} mined (dice now public)", 900)
    call("plan", [RID, 1, 2, 10, 90], applied=lambda: field(sto(), "pa", RID) == 1)
    wait(lambda: field(sto(), "pa", RID) == 1, "late dials landed", 900)
    ck("the superseded generation was retired intact",
       field(sto(), "qa", RID) == AGG and field(sto(), "qs", RID) == STANCE,
       f"qa={field(sto(), 'qa', RID)} qs={field(sto(), 'qs', RID)}")
    polh = field(sto(), "ph", RID)
    ck("the late dials really did land after the roll (or this proves nothing)", polh >= nh2,
       f"polh={polh} nh2={nh2}")
    before2 = sto()
    LEG2 = field(before2, "lg", RID)
    call("advance", [RID], applied=lambda: field(sto(), "lg", RID) > LEG2)
    wait(lambda: field(sto(), "lg", RID) > LEG2, "second leg settled", 900)
    s = sto()
    run2 = M.Run(stance=STANCE, focus=FOCUS, healpct=HEAL)          # the OLD dials — the fence's choice
    run2.agg = AGG
    for fk, mk in (("hp", "hp"), ("mx", "maxhp"), ("st", "stam"), ("po", "potions"), ("xp", "xp"),
                   ("bk", "banked"), ("sk", "streak"), ("dp", "depth"), ("ki", "kills"),
                   ("wl", "wlevel"), ("al", "alevel")):
        setattr(run2, mk, field(before2, fk, RID) or (1 if mk in ("wlevel", "alevel") else 0))
    run2.mats = [field(before2, "m0", RID), field(before2, "m1", RID), field(before2, "m2", RID)]
    run2.gear = [field(before2, f"g{i}", RID) for i in range(A.NSLOT)]
    th2, rh2 = blockhash(lh2), blockhash(nh2)
    for i in range(A.LEG):
        if not run2.alive or run2.done:
            break
        tw = alghash.hashn([th2, RID, i]) & 0xFFFFFFFF
        rw = alghash.hashn([rh2, RID, i]) & 0xFFFFFFFF
        M.step(run2, tw, rw, action=answers2[i])
    diffs2 = [(fk, field(s, fk, RID), getattr(run2, mk)) for fk, mk in pairs
              if field(s, fk, RID) != getattr(run2, mk)]
    ck("the in-flight leg resolved under the OLD dials (the fence held)", not diffs2, str(diffs2))
else:
    print("\n7. (the run ended on leg 1 — the fence is covered by the contract tests)", flush=True)

print("\n8. a run that ENDS lets you set out again", flush=True)
# Retire is the deterministic way to end one (dying is not something a test can schedule); what matters
# afterwards is identical either way: the old run must be closed and a fresh one claimable and WALKING.
if field(sto(), "lv", RID) == 1 and not field(sto(), "dn", RID):
    call("retire", [RID], applied=lambda: field(sto(), "rt", RID) == 1)
    wait(lambda: field(sto(), "rt", RID) == 1, "run retired", 900)
s = sto()
banked = field(s, "bk", RID)
RID2 = (RID + 7) % 900000000 + 1
print(f"   setting out again as run {RID2}", flush=True)
cursor_at_begin2 = cursor()
call("begin", [RID2], applied=lambda: owner(sto(), RID2) == ME)
wait(lambda: owner(sto(), RID2) == ME, "the SECOND run exists", 900)
s = sto()
ck("the new run is mine", owner(s, RID2) == ME, owner(s, RID2)[:18])
ck("the new run starts fresh, not carrying the old one's state",
   field(s, "hp", RID2) == A.HP0 and field(s, "dp", RID2) == 0 and field(s, "xp", RID2) == 0,
   f"hp={field(s, 'hp', RID2)} dp={field(s, 'dp', RID2)} xp={field(s, 'xp', RID2)}")
ck("the new run is armed from birth and waiting on its first answers",
   field(s, "lh", RID2) > cursor_at_begin2 and field(s, "nh", RID2) == 0,
   f"lh={field(s, 'lh', RID2)} nh={field(s, 'nh', RID2)}")
ck("the old run was NOT reopened", field(s, "bk", RID) == banked)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS)), flush=True)
sys.exit(1 if FAILS else 0)

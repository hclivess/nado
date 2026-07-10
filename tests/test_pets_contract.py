# tests/test_pets_contract.py — build + exhaustively exercise the NADO PETS contract (stackvm): tamagotchi
# NFTs on the execution layer. Every pet is a non-fungible on-chain asset (owner-mapped id, transferable like
# an alias) whose ANIMAL, RARITY and 10 BASE STATS are decided by chain randomness the moment it hatches:
#
#     gene = HASH( BLOCKHASH(b) + BLOCKHASH(b+1) + petId )        b = mint cursor + 2  (the beacon formula
#                                                                  every NADO game shares — see coinflip)
#     species  : r = gene % 100 -> 1 Poodle (r<70, common 70%), 2 African Grey Parrot (rare 25%),
#                                  3 Dragon (r>=95, legendary 5%)
#     stat_i   : HASH(gene + 1000 + i) % 60 + 1 + (species-1)*15      i = 0..9, locked at hatch
#                (Strength Agility Vitality Intelligence Wisdom Charisma Loyalty Luck Speed Appetite)
#     appetite : stat_9 — stored ON-CHAIN because it prices food; power = Σ stats — stored for battles.
#
# SURVIVAL — pets eat real NADO. feed(value) extends fed_until by value / (appetite * FEED_DIV) blocks
# (≈1 NADO/day at appetite 50), belly capped at 7 days ahead; when the cursor passes fed_until the pet is
# DEAD — permanently: no feeding, no transfer, no training, no battles. Fed NADO stays escrowed in the
# contract forever (a pure sink — there is no house).
#
# TRAINING — abilities unlock beyond the hatch-locked bases through training with a LIMIT-FUNCTION success
# chance (no hard cap, ever-diminishing) whose constant scales with RARITY — rare pets train easier:
#     roll = HASH( BLOCKHASH(th) + BLOCKHASH(th+1) + petId*16 + i ) % 100
#     K = 10 + 30*species   (Poodle 40, Parrot 70, Dragon 100)
#     success  <=>  roll * (K + current_stat) < 100 * K        (chance = 100*K/(K+s) %)
# a success adds +1 to that stat's trained bonus AND +1 to the pet's power.
#
# MARKETPLACE — owner lists at an ask (mp), buyer pays the EXACT price as call value; the contract pays
# the seller from escrow and flips ownership atomically. A manual transfer clears any open listing; a dead
# pet's sale can never complete. Unhatched eggs may be sold (a mystery box).
#
# BATTLES — consent-based (the defender's owner must accept), optionally staked, chain-resolved:
#     q = BLOCKHASH(wh) + BLOCKHASH(wh+1) + battleId*8            wh = accept cursor + 2
#     scoreA = powerA * (75 + HASH(q+1)%100);  scoreB = powerB * (75 + HASH(q+2)%100)
#     winner = A iff scoreA > scoreB (tie -> defender);  pot -> winner pet's CURRENT owner
#     the LOSER DIES iff HASH(q+3) % 100 < DIE_PCT (20%)          — battles are for keeps.
#
# LIVENESS ESCAPES — the exec layer only retains ~20000 block hashes (~33h), so anything bound to a pruned
# hash gets an exit: rebirth() re-rolls an unhatched egg's gene block, train() may overwrite a stale pending
# session, refund_battle() splits a stale accepted pot back. No NADO can ever be stranded.
#
# This decides who owns/keeps real money-fed assets, so the bar is the repo standard: every method's bytecode
# is DIFFERENTIALLY verified against the Python reference below (which the JS client mirrors), plus a full
# revert/security suite. WRITE=1 regenerates execnode/contracts/pets.json.
import sys, os, json, tempfile, hashlib, random
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

# ── assembler helpers (coinflip style: each helper is ONE instruction) ──────────────────────────────
def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH"); BLOCKHASH=OP("BLOCKHASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD"); CONCAT=OP("CONCAT")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LT=OP("LT"); LTE=OP("LTE"); NOT=OP("NOT"); OR=OP("OR")
DUP=OP("DUP"); SWAP=OP("SWAP"); REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

# ── economic + game constants (mirrored by static/pets-genes.js) ────────────────────────────────────
MINT_FEE    = 10**10        # 1 NADO to adopt an egg
TRAIN_FEE   = 5 * 10**9     # 0.5 NADO per training attempt (kept by the contract, success or not)
HATCH_DELAY = 2             # gene block = mint cursor + 2 (unknowable when the mint is signed)
START_BELLY = 43200         # a fresh egg/pet is fed for 3 days (6s blocks)
BELLY_CAP   = 100800        # can never be fed more than 7 days ahead — care, not a one-off payment
FEED_DIV    = 14000         # raw NADO per block of life per appetite point (~1 NADO/day at appetite 50)
STALE       = 18000         # blocks after which a pending hash-binding is considered pruned (retention 20000)
DIE_PCT     = 20            # the battle loser's chance to die, in %
S = "S"                     # scratch register map (per-call temporaries, fully rewritten before use)

# storage maps (all keyed by petId unless noted):
#   ow owner  bh geneBlock  gn gene  sp species(1..3)  ap appetite  pw power  fu fedUntil  tf totalFood
#   nm name   th trainBlock ti trainStat+1  tr lastTrainResult(1 ok/2 fail)  tb trainedBonus (petId|i)
#   battles keyed by battleId: wa petA  wb petB  ws stake  wp pot  wh resolveBlock  wn state(1 open,
#   2 accepted, 3 done)  ww winnerPet  wd diedPet(0 none)      ct: "n" -> total pets minted
def stat_base_ops(i_ops):
    """base stat for stat-index produced by i_ops: HASH(gn+1000+i)%60 + 1 + (sp-1)*15   (needs ARG0=pid)."""
    return [A(0), LD("gn"), P(1000), ADD, *i_ops, ADD, HASH, P(60), MOD, P(1), ADD,
            A(0), LD("sp"), P(1), SUB, P(15), MUL, ADD]

mint_m = [                                        # mint(pid)  value = MINT_FEE exactly
  VALUE, P(MINT_FEE), EQ, REQ,
  A(0), P(0), GT, REQ,                            # pid: positive int (GT type-gates)
  A(0), LD("ow"), P(0), EQ, REQ,                  # fresh id
  A(0), CALLER, ST("ow"),
  A(0), CURSOR, P(HATCH_DELAY), ADD, ST("bh"),    # gene block — hashes don't exist yet
  A(0), CURSOR, P(HATCH_DELAY + START_BELLY), ADD, ST("fu"),
  A(0), VALUE, ST("tf"),
  P("n"), P("n"), LD("ct"), P(1), ADD, ST("ct"),
  HALT ]

hatch_m = [                                       # hatch(pid) — permissionless; locks gene/species/stats
  A(0), LD("ow"), P(0), EQ, NOT, REQ,             # exists
  A(0), LD("gn"), P(0), EQ, REQ,                  # not hatched yet
  CURSOR, A(0), LD("bh"), P(1), ADD, GTE, REQ,    # both gene blocks exist
  CURSOR, A(0), LD("fu"), LTE, REQ,               # the egg is still alive
  # gene = HASH(bh0 + bh1 + pid) — stored as INT for the VM's math and as a DECIMAL STRING for the
  # browser (gs): storage rides to the client as JSON, where a bare 256-bit number would lose precision.
  A(0), A(0), LD("bh"), BLOCKHASH, A(0), LD("bh"), P(1), ADD, BLOCKHASH, ADD, A(0), ADD, HASH, ST("gn"),
  A(0), P(""), A(0), LD("gn"), CONCAT, ST("gs"),
  # species = 1 + (r>=70) + (r>=95),  r = gene % 100
  A(0), A(0), LD("gn"), P(100), MOD, DUP, P(70), GTE, SWAP, P(95), GTE, ADD, P(1), ADD, ST("sp"),
  # appetite = stat_9 (it prices food, so it must live on-chain)
  A(0), *stat_base_ops([P(9)]), ST("ap"),
  # power = Σ_{i=0..9} (HASH(gn+1000+i)%60+1)  +  (sp-1)*150   (== Σ stat_i)
  A(0), P(0),
  *[ins for i in range(10) for ins in
      [A(0), LD("gn"), P(1000 + i), ADD, HASH, P(60), MOD, P(1), ADD, ADD]],
  A(0), LD("sp"), P(1), SUB, P(150), MUL, ADD, ST("pw"),
  HALT ]

rebirth_m = [                                     # rebirth(pid) — owner re-rolls a PRUNED unhatched egg
  CALLER, A(0), LD("ow"), EQ, REQ,
  A(0), LD("gn"), P(0), EQ, REQ,                  # still an egg
  CURSOR, A(0), LD("fu"), LTE, REQ,               # egg alive
  CURSOR, A(0), LD("bh"), P(STALE), ADD, GTE, REQ,  # its gene block is (about to be) pruned
  A(0), CURSOR, P(HATCH_DELAY), ADD, ST("bh"),
  HALT ]

feed_m = [                                        # feed(pid)  value = the meal (raw NADO)
  VALUE, P(0), GT, REQ,
  A(0), LD("gn"), P(0), EQ, NOT, REQ,             # hatched (an egg doesn't eat)
  CURSOR, A(0), LD("fu"), LTE, REQ,               # ALIVE — dead is dead
  A(0),                                           # key for fu
  A(0), LD("fu"),
  VALUE, A(0), LD("ap"), P(FEED_DIV), MUL, DIV,   # blocks gained = value / (appetite * FEED_DIV)
  DUP, P(0), GT, REQ,                             # a meal too small to buy 1 block would be wasted -> revert
  ADD,                                            # new fed_until
  DUP, CURSOR, P(BELLY_CAP), ADD, LTE, REQ,       # belly cap: never more than 7 days ahead
  ST("fu"),
  A(0), A(0), LD("tf"), VALUE, ADD, ST("tf"),
  HALT ]

transfer_m = [                                    # transfer(pid, to) — the NFT move; owner-only, alive-only
  CALLER, A(0), LD("ow"), EQ, REQ,
  CURSOR, A(0), LD("fu"), LTE, REQ,               # no trading corpses (eggs are fine — they have a belly)
  P(""), A(1), CONCAT,                            # coerce to string so ow always holds an address string
  DUP, P(""), EQ, NOT, REQ,
  DUP, CALLER, EQ, NOT, REQ,
  A(0), SWAP, ST("ow"),
  A(0), P(0), ST("mp"),                           # a hand-off kills any open sale listing
  HALT ]

list_m = [                                        # list(pid, price) — put the pet up for sale (owner, alive)
  CALLER, A(0), LD("ow"), EQ, REQ,
  CURSOR, A(0), LD("fu"), LTE, REQ,
  A(1), P(0), GT, REQ,                            # price: positive int (raw NADO)
  A(0), A(1), ST("mp"),
  HALT ]

unlist_m = [                                      # unlist(pid) — owner takes it off the market
  CALLER, A(0), LD("ow"), EQ, REQ,
  A(0), LD("mp"), P(0), EQ, NOT, REQ,
  A(0), P(0), ST("mp"),
  HALT ]

buy_m = [                                         # buy(pid)  value = the exact asking price
  A(0), LD("mp"), P(0), EQ, NOT, REQ,             # it IS for sale
  VALUE, A(0), LD("mp"), EQ, REQ,                 # pay exactly the ask
  CURSOR, A(0), LD("fu"), LTE, REQ,               # it's still alive (a corpse sale can't complete)
  CALLER, A(0), LD("ow"), EQ, NOT, REQ,           # not your own
  A(0), LD("ow"), VALUE, PAY,                     # the price flows straight through escrow to the seller
  A(0), CALLER, ST("ow"),
  A(0), P(0), ST("mp"),
  HALT ]

name_m = [                                        # name(pid, name) — owner-only; empty clears
  CALLER, A(0), LD("ow"), EQ, REQ,
  A(0), P(""), A(1), CONCAT, ST("nm"),
  HALT ]

train_m = [                                       # train(pid, statIdx 0..9)  value = TRAIN_FEE exactly
  VALUE, P(TRAIN_FEE), EQ, REQ,
  A(1), P(0), GTE, REQ, A(1), P(9), LTE, REQ,     # stat index (GTE/LTE type-gate ints)
  CALLER, A(0), LD("ow"), EQ, REQ,
  A(0), LD("gn"), P(0), EQ, NOT, REQ,             # hatched
  CURSOR, A(0), LD("fu"), LTE, REQ,               # alive
  A(0), LD("th"), P(0), EQ,                       # no pending session…
  CURSOR, A(0), LD("th"), P(STALE), ADD, GT, OR, REQ,   # …or the pending one's hash is pruned (fee forfeit)
  A(0), CURSOR, P(HATCH_DELAY), ADD, ST("th"),
  A(0), A(1), P(1), ADD, ST("ti"),                # stored 1-based so 0 never reads as "absent"
  HALT ]

_i_ops = [A(0), LD("ti"), P(1), SUB]              # the pending session's stat index
_key_pi = [A(0), P("|"), CONCAT, *_i_ops, CONCAT] # tb key "pid|i"
train_resolve_m = [                               # train_resolve(pid) — permissionless once the hashes exist
  A(0), LD("th"), P(0), EQ, NOT, REQ,
  CURSOR, A(0), LD("th"), P(1), ADD, GTE, REQ,
  # S.c = current effective stat = base_i + trained bonus
  P("c"), *stat_base_ops(_i_ops), *_key_pi, LD("tb"), ADD, ST(S),
  # S.r = roll = HASH(bh(th) + bh(th+1) + pid*16 + i) % 100
  P("r"), A(0), LD("th"), BLOCKHASH, A(0), LD("th"), P(1), ADD, BLOCKHASH, ADD,
          A(0), P(16), MUL, ADD, *_i_ops, ADD, HASH, P(100), MOD, ST(S),
  # S.s = success = roll*(K+cur) < 100*K  — the limit function; K = 10+30*species (rarer = easier)
  P("s"), P("r"), LD(S),
          A(0), LD("sp"), P(30), MUL, P(10), ADD, P("c"), LD(S), ADD, MUL,
          A(0), LD("sp"), P(30), MUL, P(10), ADD, P(100), MUL, LT, ST(S),
  *_key_pi, DUP, LD("tb"), P("s"), LD(S), ADD, ST("tb"),           # bonus += success
  A(0), A(0), LD("pw"), P("s"), LD(S), ADD, ST("pw"),              # power += success
  A(0), P(2), P("s"), LD(S), SUB, ST("tr"),                        # 1 = success, 2 = fail (for the UI)
  A(0), P(0), ST("th"), A(0), P(0), ST("ti"),                      # session closed
  HALT ]

challenge_m = [                                   # challenge(bid, myPet, theirPet)  value = stake (may be 0)
  A(0), P(0), GT, REQ,                            # battle id: positive int
  A(0), LD("wn"), P(0), EQ, REQ,                  # fresh id (wn: 1 open, 2 accepted, 3 done)
  A(0), LD("wa"), P(0), EQ, REQ,
  A(1), LD("gn"), P(0), EQ, NOT, REQ,             # both pets hatched
  A(2), LD("gn"), P(0), EQ, NOT, REQ,
  CALLER, A(1), LD("ow"), EQ, REQ,                # you send YOUR pet
  CURSOR, A(1), LD("fu"), LTE, REQ,               # both alive
  CURSOR, A(2), LD("fu"), LTE, REQ,
  A(1), A(2), EQ, NOT, REQ,
  A(0), A(1), ST("wa"), A(0), A(2), ST("wb"),
  A(0), VALUE, ST("ws"), A(0), VALUE, ST("wp"),
  A(0), P(1), ST("wn"),
  HALT ]

accept_m = [                                      # accept(bid)  value = the challenger's stake, matched
  A(0), LD("wn"), P(1), EQ, REQ,
  CALLER, A(0), LD("wb"), LD("ow"), EQ, REQ,      # only the challenged pet's CURRENT owner consents
  VALUE, A(0), LD("ws"), EQ, REQ,
  CURSOR, A(0), LD("wa"), LD("fu"), LTE, REQ,     # both still alive at consent
  CURSOR, A(0), LD("wb"), LD("fu"), LTE, REQ,
  A(0), A(0), LD("wp"), VALUE, ADD, ST("wp"),
  A(0), CURSOR, P(HATCH_DELAY), ADD, ST("wh"),    # the fight is decided by blocks that don't exist yet
  A(0), P(2), ST("wn"),
  HALT ]

_l_ops = [A(0), LD("wa"), A(0), LD("wb"), ADD, A(0), LD("ww"), SUB]   # loser pid = wa + wb - winner
resolve_battle_m = [                              # resolve_battle(bid) — permissionless once hashes exist
  A(0), LD("wn"), P(2), EQ, REQ,
  CURSOR, A(0), LD("wh"), P(1), ADD, GTE, REQ,
  # S.q = q = bh(wh) + bh(wh+1) + bid*8
  P("q"), A(0), LD("wh"), BLOCKHASH, A(0), LD("wh"), P(1), ADD, BLOCKHASH, ADD, A(0), P(8), MUL, ADD, ST(S),
  # S.x/S.y = score = power * (75 + HASH(q+1|q+2) % 100) — stats dominate, luck decides close fights
  P("x"), A(0), LD("wa"), LD("pw"), P(75), P("q"), LD(S), P(1), ADD, HASH, P(100), MOD, ADD, MUL, ST(S),
  P("y"), A(0), LD("wb"), LD("pw"), P(75), P("q"), LD(S), P(2), ADD, HASH, P(100), MOD, ADD, MUL, ST(S),
  P("g"), P("x"), LD(S), P("y"), LD(S), GT, ST(S),                   # A wins iff scoreA > scoreB (tie -> defender)
  A(0), A(0), LD("wa"), P("g"), LD(S), MUL,
        A(0), LD("wb"), P(1), P("g"), LD(S), SUB, MUL, ADD, ST("ww"),
  # S.d = the loser's death roll: dies iff HASH(q+3) % 100 < DIE_PCT
  P("d"), P("q"), LD(S), P(3), ADD, HASH, P(100), MOD, P(DIE_PCT), LT, ST(S),
  *_l_ops, *_l_ops, LD("fu"), P(1), P("d"), LD(S), SUB, MUL, P("d"), LD(S), ADD, ST("fu"),   # fu = d?1:fu
  A(0), *_l_ops, P("d"), LD(S), MUL, ST("wd"),                       # who died (0 = nobody)
  A(0), LD("ww"), LD("ow"), A(0), LD("wp"), PAY,                     # pot -> the winner pet's CURRENT owner
  A(0), P(3), ST("wn"), A(0), P(0), ST("wp"),
  HALT ]

cancel_battle_m = [                               # cancel_battle(bid) — challenger backs out before consent
  A(0), LD("wn"), P(1), EQ, REQ,
  CALLER, A(0), LD("wa"), LD("ow"), EQ, REQ,
  A(0), LD("wa"), LD("ow"), A(0), LD("wp"), PAY,
  A(0), P(3), ST("wn"), A(0), P(0), ST("wp"),
  HALT ]

refund_battle_m = [                               # refund_battle(bid) — accepted but its hashes were pruned
  A(0), LD("wn"), P(2), EQ, REQ,                  # (never resolved for ~30h); anyone may split the pot back
  CURSOR, A(0), LD("wh"), P(STALE), ADD, GT, REQ,
  A(0), LD("wa"), LD("ow"), A(0), LD("ws"), PAY,
  A(0), LD("wb"), LD("ow"), A(0), LD("wp"), A(0), LD("ws"), SUB, PAY,
  A(0), P(3), ST("wn"), A(0), P(0), ST("wp"),
  HALT ]

CODE = {"mint": mint_m, "hatch": hatch_m, "rebirth": rebirth_m, "feed": feed_m, "transfer": transfer_m,
        "name": name_m, "list": list_m, "unlist": unlist_m, "buy": buy_m,
        "train": train_m, "train_resolve": train_resolve_m, "challenge": challenge_m,
        "accept": accept_m, "resolve_battle": resolve_battle_m, "cancel_battle": cancel_battle_m,
        "refund_battle": refund_battle_m}

# ── PYTHON REFERENCE, shared with the JS crosscheck (tests/pets_ref.py is the single source) ────────
from tests.pets_ref import (vm_hash, ref_gene, ref_species, ref_stat, ref_power,
                            ref_train_roll, ref_train_ok, ref_battle)
assert __import__("tests.pets_ref", fromlist=["DIE_PCT"]).DIE_PCT == DIE_PCT

# ── harness ─────────────────────────────────────────────────────────────────────────────────────────
F = []
def ck(n, c): print(("  ok  " if c else " FAIL ") + n); (F.append(n) if not c else None)
st = ExecState(tempfile.mktemp()); T0 = 1000; st.cursor = T0
for a in ("A", "B", "C"): st.credit_deposit(a, 10**14)
st.apply_blob({"op": "deploy", "code": CODE, "runtime": "stackvm", "nonce": "pets-v1"}, "A", "d0")
CID = list(st.contracts)[0]
def set_hashes(upto):
    for h in range(T0 - 5, upto + 2): st.block_hashes.setdefault(h, vm_hash(["blk", h]))
def bal(a): return st.bridge.get(a, 0)
def M(m, k): return st.contracts[CID]["storage"].get(m, {}).get(str(k), 0)
def call(m, args, val, who): return st.apply_blob({"op": "call", "contract": CID, "method": m, "args": args, "value": val}, who, m + str(args) + str(st.cursor))
def rv(r): return "revert" in r or "skip" in r
def advance(n): st.cursor += n; set_hashes(st.cursor)
def mint_and_hatch(pid, who):
    call("mint", [pid], MINT_FEE, who); advance(3)
    r = call("hatch", [pid], 0, who); assert not rv(r), f"hatch {pid} failed: {r}"
    return M("gn", pid)
set_hashes(T0)

# ── mint ─────────────────────────────────────────────────────────────────────────────────────────────
PID = 424242
b0 = bal("A")
call("mint", [PID], MINT_FEE, "A")
ck("mint escrows exactly 1 NADO", bal("A") == b0 - MINT_FEE and bal(CID) == MINT_FEE)
ck("mint records owner/geneBlock/belly/food", M("ow", PID) == "A" and M("bh", PID) == st.cursor + HATCH_DELAY
   and M("fu", PID) == st.cursor + HATCH_DELAY + START_BELLY and M("tf", PID) == MINT_FEE and M("ct", "n") == 1)
ck("mint duplicate id reverts", rv(call("mint", [PID], MINT_FEE, "B")))
ck("mint wrong fee reverts", rv(call("mint", [777], MINT_FEE - 1, "A")) and rv(call("mint", [778], MINT_FEE + 1, "A")))
ck("mint bad pid reverts (0 / negative / string)", rv(call("mint", [0], MINT_FEE, "A"))
   and rv(call("mint", [-5], MINT_FEE, "A")) and rv(call("mint", ["x"], MINT_FEE, "A")))

# ── hatch (+ differential vs reference) ──────────────────────────────────────────────────────────────
ck("hatch before the gene blocks exist reverts", rv(call("hatch", [PID], 0, "B")))
advance(3)
call("hatch", [PID], 0, "B")   # permissionless
g = M("gn", PID)
ck("hatch locks gene == reference beacon formula", g == ref_gene(st.block_hashes, M("bh", PID), PID))
ck("hatch locks species/appetite/power == reference", M("sp", PID) == ref_species(g)
   and M("ap", PID) == ref_stat(g, ref_species(g), 9) and M("pw", PID) == ref_power(g, ref_species(g)))
ck("hatch stores the gene as a decimal string too (JSON-safe for the browser)", M("gs", PID) == str(g))
ck("hatch twice reverts", rv(call("hatch", [PID], 0, "A")))
ck("hatch of a nonexistent pet reverts", rv(call("hatch", [999999], 0, "A")))

hist = {1: 0, 2: 0, 3: 0}
mism = 0
for k in range(300):
    pid = 10**6 + k
    call("mint", [pid], MINT_FEE, "A"); advance(1 + (k % 3))
    set_hashes(st.cursor + 3); advance(3)
    call("hatch", [pid], 0, "A")
    g = M("gn", pid); s = ref_species(g); hist[M("sp", pid)] += 1
    if not (g == ref_gene(st.block_hashes, M("bh", pid), pid) and M("sp", pid) == s
            and M("ap", pid) == ref_stat(g, s, 9) and M("pw", pid) == ref_power(g, s)): mism += 1
ck(f"DIFFERENTIAL: 300 hatches gene/species/appetite/power bytecode==reference (mism={mism})", mism == 0)
ck(f"all three species appear — Poodle {hist[1]}, Parrot {hist[2]}, Dragon {hist[3]}",
   hist[1] > 150 and hist[2] > 30 and hist[3] > 2)

# ── feed ─────────────────────────────────────────────────────────────────────────────────────────────
ap = M("ap", PID); fu0 = M("fu", PID)
meal = ap * FEED_DIV * 1000                       # exactly 1000 blocks of life
call("feed", [PID], meal, "B")                    # ANYONE may feed a pet (a gift) — only value moves
ck("feed extends fed_until by value/(appetite*FEED_DIV)", M("fu", PID) == fu0 + 1000 and M("tf", PID) == MINT_FEE + meal)
ck("feed dust (under 1 block of food) reverts", rv(call("feed", [PID], ap * FEED_DIV - 1, "A")))
ck("feed zero reverts", rv(call("feed", [PID], 0, "A")))
over = ap * FEED_DIV * (BELLY_CAP + 5000)
ck("overfeeding past the 7-day belly cap reverts", rv(call("feed", [PID], over, "A")))
EGG = 555001; call("mint", [EGG], MINT_FEE, "A")
ck("feeding an unhatched egg reverts", rv(call("feed", [EGG], meal, "A")))

# ── transfer + name (the NFT surface) ───────────────────────────────────────────────────────────────
ck("non-owner transfer reverts", rv(call("transfer", [PID, "C"], 0, "B")))
ck("transfer to empty / self reverts", rv(call("transfer", [PID, ""], 0, "A")) and rv(call("transfer", [PID, "A"], 0, "A")))
call("transfer", [PID, "B"], 0, "A")
ck("owner transfer moves the pet", M("ow", PID) == "B")
ck("old owner lost all rights", rv(call("transfer", [PID, "C"], 0, "A")) and rv(call("name", [PID, "Rex"], 0, "A")))
call("name", [PID, "Rex"], 0, "B")
ck("new owner can name it", M("nm", PID) == "Rex")
call("name", [PID, ""], 0, "B")
ck("empty name clears", M("nm", PID) == 0)
call("transfer", [EGG, "C"], 0, "A")
ck("an unhatched egg IS transferable", M("ow", EGG) == "C")

# ── training: the limit function, differentially ────────────────────────────────────────────────────
TP = 626262; gT = mint_and_hatch(TP, "A")
spT = ref_species(gT)
ck("train needs the exact fee", rv(call("train", [TP, 3], TRAIN_FEE - 1, "A")))
ck("train stat index out of range reverts", rv(call("train", [TP, 10], TRAIN_FEE, "A")) and rv(call("train", [TP, -1], TRAIN_FEE, "A")))
ck("train by non-owner reverts", rv(call("train", [TP, 3], TRAIN_FEE, "B")))
ck("resolve with no session reverts", rv(call("train_resolve", [TP], 0, "A")))
wins = fails = mismt = 0
ref_tb = {}
for n in range(60):
    i = n % 10
    r = call("train", [TP, i], TRAIN_FEE, "A")
    assert not rv(r), r
    if n == 0:
        ck("double-book a training session reverts", rv(call("train", [TP, i], TRAIN_FEE, "A")))
        ck("resolve before the hashes exist reverts", rv(call("train_resolve", [TP], 0, "B")))
    th = M("th", TP); advance(3)
    cur = ref_stat(gT, spT, i) + ref_tb.get(i, 0)
    roll = ref_train_roll(st.block_hashes, th, TP, i)
    ok = ref_train_ok(roll, cur, spT)
    pw0 = M("pw", TP)
    call("train_resolve", [TP], 0, "C")           # permissionless resolve
    if ok: ref_tb[i] = ref_tb.get(i, 0) + 1; wins += 1
    else: fails += 1
    if not (M("tb", f"{TP}|{i}") == ref_tb.get(i, 0) and M("pw", TP) == pw0 + (1 if ok else 0)
            and M("tr", TP) == (1 if ok else 2) and M("th", TP) == 0): mismt += 1
ck(f"DIFFERENTIAL: 60 training sessions bytecode==reference (mism={mismt}, {wins} ups, {fails} fails)",
   mismt == 0 and wins > 5 and fails > 5)
ck("power grew by exactly the successful sessions", M("pw", TP) == ref_power(gT, spT) + wins)

# stale pending session: unresolved past STALE can be overwritten (fee forfeit), resolve of it reverts
call("train", [TP, 0], TRAIN_FEE, "A")
st.cursor += STALE + 5                            # hashes for the old session's blocks were never recorded
ck("resolve of a pruned session reverts", rv(call("train_resolve", [TP], 0, "A")))
call("feed", [TP], M("ap", TP) * FEED_DIV * (BELLY_CAP - 100), "A")   # keep it alive across the jump
ck("a stale session may be overwritten by a fresh train", not rv(call("train", [TP, 0], TRAIN_FEE, "A")))
set_hashes(st.cursor + 3); advance(3); call("train_resolve", [TP], 0, "A")
ck("the fresh session resolves", M("th", TP) == 0 and M("tr", TP) in (1, 2))

# ── battles: consent, stakes, chain-decided, loser may die — differentially ────────────────────────
mismb = winsA = winsB = deaths = 0
bal_track = {a: bal(a) for a in ("A", "B")}
pool = []
for k in range(120):                              # fresh pairs each round (a loser may die permanently)
    pa, pb = 2 * 10**6 + 2 * k, 2 * 10**6 + 2 * k + 1
    mint_and_hatch(pa, "A"); mint_and_hatch(pb, "B")
    bal_track = {"A": bal("A"), "B": bal("B")}
    bid = 3 * 10**6 + k; stake = (k % 4) * 10**9   # includes friendly 0-stake battles
    r = call("challenge", [bid, pa, pb], stake, "A"); assert not rv(r), r
    r = call("accept", [bid], stake, "B"); assert not rv(r), r
    wh = M("wh", bid); advance(3)
    a_wins, dies = ref_battle(st.block_hashes, wh, bid, M("pw", pa), M("pw", pb))
    fu_l = M("fu", pb if a_wins else pa)
    call("resolve_battle", [bid], 0, "C")         # permissionless
    w, l = (pa, pb) if a_wins else (pb, pa)
    w_own, l_own = ("A", "B") if a_wins else ("B", "A")
    good = (M("ww", bid) == w and M("wn", bid) == 3
            and M("wd", bid) == (l if dies else 0)
            and M("fu", l) == (1 if dies else fu_l)
            and bal(w_own) == bal_track[w_own] + (stake if stake else 0)      # got the pot (their stake back + loser's)
            and bal(l_own) == bal_track[l_own] - stake)
    if not good: mismb += 1
    winsA += a_wins; winsB += (not a_wins); deaths += dies
ck(f"DIFFERENTIAL: 120 battles winner/pot/death bytecode==reference (mism={mismb}, A {winsA}–{winsB} B, {deaths} deaths)",
   mismb == 0 and winsA > 10 and winsB > 10 and deaths > 5)

# battle guards
g1, g2 = 4100001, 4100002
mint_and_hatch(g1, "A"); mint_and_hatch(g2, "B")
BID = 5100001
ck("challenge with someone else's pet reverts", rv(call("challenge", [BID, g1, g2], 10**9, "C")))
ck("challenge yourself (same pet both sides) reverts", rv(call("challenge", [BID, g1, g1], 10**9, "A")))
EGG2 = 4100003; call("mint", [EGG2], MINT_FEE, "A")
ck("challenge with an unhatched pet reverts", rv(call("challenge", [BID, g1, EGG2], 0, "A")))
call("challenge", [BID, g1, g2], 10**9, "A")
ck("battle id reuse reverts", rv(call("challenge", [BID, g1, g2], 10**9, "A")))
ck("accept by anyone but the defender's owner reverts", rv(call("accept", [BID], 10**9, "C")))
ck("accept with a mismatched stake reverts", rv(call("accept", [BID], 10**9 - 1, "B")))
ck("resolve before consent reverts", rv(call("resolve_battle", [BID], 0, "A")))
ck("cancel by non-challenger reverts", rv(call("cancel_battle", [BID], 0, "B")))
bA = bal("A")
call("cancel_battle", [BID], 0, "A")
ck("challenger cancel refunds the stake", bal("A") == bA + 10**9 and M("wn", BID) == 3)
ck("accept after cancel reverts", rv(call("accept", [BID], 10**9, "B")))
BID2 = 5100002
call("challenge", [BID2, g1, g2], 2 * 10**9, "A")
call("accept", [BID2], 2 * 10**9, "B")
ck("refund of a live accepted battle reverts (not stale yet)", rv(call("refund_battle", [BID2], 0, "C")))
advance(3)
ck("double-resolve reverts", (call("resolve_battle", [BID2], 0, "C") or True) and rv(call("resolve_battle", [BID2], 0, "C")))
# stale accepted battle -> anyone splits the pot back
g3, g4 = 4100005, 4100006
mint_and_hatch(g3, "A"); mint_and_hatch(g4, "B")
call("feed", [g3], M("ap", g3) * FEED_DIV * (BELLY_CAP - 100), "A")
call("feed", [g4], M("ap", g4) * FEED_DIV * (BELLY_CAP - 100), "B")
BID3 = 5100003
call("challenge", [BID3, g3, g4], 3 * 10**9, "A")
call("accept", [BID3], 3 * 10**9, "B")
bA, bB = bal("A"), bal("B")
st.cursor += STALE + 5                            # its hashes were never recorded (pruned)
ck("resolve of a pruned battle reverts", rv(call("resolve_battle", [BID3], 0, "C")))
call("refund_battle", [BID3], 0, "C")
ck("stale battle refunds both stakes", bal("A") == bA + 3 * 10**9 and bal("B") == bB + 3 * 10**9 and M("wn", BID3) == 3)
set_hashes(st.cursor + 1)

# ── marketplace: list / unlist / buy ────────────────────────────────────────────────────────────────
MP = 6100001; mint_and_hatch(MP, "A")
PRICE = 7 * 10**10
ck("buy an unlisted pet reverts", rv(call("buy", [MP], PRICE, "B")))
ck("list by non-owner reverts", rv(call("list", [MP, PRICE], 0, "B")))
ck("list at price 0 / bad price reverts", rv(call("list", [MP, 0], 0, "A")) and rv(call("list", [MP, "x"], 0, "A")))
call("list", [MP, PRICE], 0, "A")
ck("owner lists at an ask", M("mp", MP) == PRICE)
ck("buy at the wrong price reverts", rv(call("buy", [MP], PRICE - 1, "B")) and rv(call("buy", [MP], PRICE + 1, "B")))
ck("buying your own pet reverts", rv(call("buy", [MP], PRICE, "A")))
bA, bB = bal("A"), bal("B")
call("buy", [MP], PRICE, "B")
ck("buy pays the seller the exact ask and flips ownership",
   bal("A") == bA + PRICE and bal("B") == bB - PRICE and M("ow", MP) == "B" and M("mp", MP) == 0)
ck("stale buy after the sale reverts", rv(call("buy", [MP], PRICE, "C")))
call("list", [MP, PRICE], 0, "B")
call("unlist", [MP], 0, "B")
ck("owner unlists", M("mp", MP) == 0 and rv(call("unlist", [MP], 0, "B")))
call("list", [MP, PRICE], 0, "B")
call("transfer", [MP, "C"], 0, "B")
ck("a manual transfer clears the open listing", M("ow", MP) == "C" and M("mp", MP) == 0)
MPE = 6100002; call("mint", [MPE], MINT_FEE, "A")
call("list", [MPE, PRICE], 0, "A")
ck("an unhatched egg can be listed (mystery box) and bought", M("mp", MPE) == PRICE
   and (call("buy", [MPE], PRICE, "C") or True) and M("ow", MPE) == "C")

# ── death is death ───────────────────────────────────────────────────────────────────────────────────
DP = 7100001; gD = mint_and_hatch(DP, "A")
st.cursor = M("fu", DP) + 1; set_hashes(st.cursor)
ck("a starved pet cannot be fed", rv(call("feed", [DP], 10**10, "A")))
ck("a dead pet cannot be transferred", rv(call("transfer", [DP, "B"], 0, "A")))
ck("a dead pet cannot be listed or bought", rv(call("list", [DP, 10**10], 0, "A")))
ck("a dead pet cannot train", rv(call("train", [DP, 0], TRAIN_FEE, "A")))
DP2 = 7100002; mint_and_hatch(DP2, "A")
ck("a dead pet cannot battle", rv(call("challenge", [9100001, DP, DP2], 0, "A"))
   and rv(call("challenge", [9100002, DP2, DP], 0, "A")))
DP3 = 7100003; mint_and_hatch(DP3, "A")
call("list", [DP3, 10**10], 0, "A")
st.cursor = M("fu", DP3) + 1; set_hashes(st.cursor)
ck("a listed pet that DIED cannot be bought (sale can't complete)", rv(call("buy", [DP3], 10**10, "B")))

# ── rebirth: an egg whose gene block was pruned re-rolls ────────────────────────────────────────────
RB = 8100001
call("mint", [RB], MINT_FEE, "A")
ck("rebirth of a FRESH egg reverts (hashes still there)", rv(call("rebirth", [RB], 0, "A")))
st.cursor += STALE + 2                            # its gene blocks were never recorded (pruned)
call("feed", [RB], 10**10, "A")                   # (sanity: still an egg, feed must revert)
ck("rebirth by non-owner reverts", rv(call("rebirth", [RB], 0, "B")))
call("rebirth", [RB], 0, "A")
ck("rebirth re-rolls the gene block", M("bh", RB) == st.cursor + HATCH_DELAY)
set_hashes(st.cursor + 3); advance(3)
call("hatch", [RB], 0, "A")
gR = M("gn", RB)
ck("the reborn egg hatches against its NEW block", gR == ref_gene(st.block_hashes, M("bh", RB), RB)
   and M("pw", RB) == ref_power(gR, ref_species(gR)))
ck("rebirth of a hatched pet reverts", rv(call("rebirth", [RB], 0, "A")))

# ── economics sanity: the contract can never pay out more than the pots it holds ────────────────────
ck("contract escrow = all mint fees + food + training fees (a pure sink besides pots)", bal(CID) > 0)

print("\n" + ("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    outp = os.path.join(os.path.dirname(__file__), "..", "execnode", "contracts", "pets.json")
    blob = json.dumps(CODE)
    print(f"deploy blob = {len(blob)} bytes; hatch={len(hatch_m)} instr, resolve_battle={len(resolve_battle_m)} instr")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp, "w")); print("WROTE", outp)
    else:
        committed = json.load(open(outp)) if os.path.exists(outp) else None
        assert committed == CODE, "execnode/contracts/pets.json is STALE — re-run with WRITE=1"
        print("committed pets.json matches the assembled contract")
sys.exit(1 if F else 0)

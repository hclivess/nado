"""
Pets — zkVM port (doc/zk-execution-proofs.md). Tamagotchi NFTs on the execution layer: every pet is a
non-fungible on-chain asset whose ANIMAL, RARITY TIER and 10 BASE STATS are decided by chain randomness the
moment it hatches; it eats real NADO to stay alive, trains with an ever-diminishing success chance, trades
on a built-in marketplace (list/buy + escrowed offers), and fights consent-based turn-battles where the
winner's owner CLAIMS the loser. Fees (mint/food/train) are BURNED — accumulated on the contract's own
balance with no code path that can ever pay them out, publicly tallied in slot 1.

Chain-random formulas (field-native; the browser mirrors them via alghash.js — see static/pets-genes.js):
    gene    = H(bh(b) + bh(b+1) + pid)                        b = mint cursor + 2
    roll(x) = LO32(H(x))                                      (the 32-bit window every derived roll uses)
    tier sp = 1 + Σ(roll(gene+555) % 100000 >= T)  T ∈ {78000,95000,98900,99750,99960}   (6 tiers,
              odds 78/17/3.9/0.85/0.21/0.04 % — geometric ~4.5x decay)
    species si = TIER_BASE[sp] + roll(gene+777) % TIER_COUNT[sp]
    stat_i  = roll(gene+1000+i) % 60 + 1 + (sp-1)*6           i = 0..9, locked at hatch
    train   = roll(bh(th)+bh(th+1)+pid*16+i) % 100 ;  success ⟺ roll·(K+cur) < 100·K,  K = 10+30·sp
    battle  = the turn-based v2 duel (see _resolve_battle) over q = bh(wh)+bh(wh+1)+bid·8 — every stat
              fights: str damage · agi dodge · vit HP · int accuracy · wis mitigation · cha intimidation ·
              loy regen · luck crit · spd turn-share · app bulk+bite. Winner = higher remaining HP FRACTION
              (integer cross-multiply, tie -> defender); the loser dies iff roll(q+999999) % 100 < 10.

Pet fields (key = pid < 2^32): 1(slot: global burn tally) · 2 ow 3 bh 4 gn 5 gl 6 gh (gene + its lo/hi
  32-bit halves — JS floats can't hold a field element) 7 sp 8 si 9 ap 10 pw 11 fu 12 tf 13 ex 14 nm
  15 th 16 ti 17 tr 18 mp 19 wins 20 loss. Trained bonus per stat: field 30+i (i 0..9) keyed pid.
Offers (key = offerId): 40 ob 41 op 42 ov 43 os. Battles (key = bid): 50 wa 51 wb 52 ws 53 wp 54 wh
  55 wn 56 ww 57 wd. Indexes: pets (cnt slot 0, list field 60) · offers (cnt slot 2, list field 61) ·
  battles (cnt slot 3, list field 62). Battle scratch: 950+i keyed bid (scrubbed on success; a failed
  call reverts to a no-op).
Methods: mint(pid)[1 NADO] · hatch(pid) · rebirth(pid) · feed(pid)[meal] · transfer(pid,to) ·
  name(pid,name) · list(pid,price) · unlist(pid) · buy(pid)[price] · offer(oid,pid)[bid] ·
  accept_offer(oid) · cancel_offer(oid) · train(pid,stat)[0.5 NADO] · train_resolve(pid) ·
  challenge(bid,myPet,theirPet)[stake] · accept(bid)[stake] · resolve_battle(bid) · cancel_battle(bid) ·
  refund_battle(bid).
"""
from execnode import zkvmasm
from execnode.stark import alghash, field as F

# economic + game constants (mirrored by static/pets-genes.js and the reference functions below)
MINT_FEE = 10**10
TRAIN_FEE = 5 * 10**9
HATCH_DELAY = 2
START_BELLY = 432000
BELLY_CAP = 432000
FEED_DIV = 1400
STALE = 18000
EXHAUST = 3600
DIE_PCT = 10
CAP_BATTLE = 12
HP_OFF = 1024                 # HP values ride shifted by +1024 so a one-hit overshoot below zero stays
                              # field-positive (max damage < 1024) — branchless signed math in a prime field
TIER_CUM = [78000, 95000, 98900, 99750, 99960]                                     # tier odds (fixed forever)
TIER_BASE = {1: 1, 2: 205, 3: 571, 4: 840, 5: 965, 6: 1002}                        # first si of each tier band
TIER_COUNT = {1: 204, 2: 366, 3: 269, 4: 125, 5: 37, 6: 7}                         # species per tier (sum 1008)
STAT_TIER_BONUS = 6

BURN_SLOT = 1
OW, BH, GN, GL, GH, SP, SI, AP, PW, FU, TF, EX, NM = 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14
TH, TI, TR, MP, WINS, LOSS = 15, 16, 17, 18, 19, 20
TB_BASE = 30
OB, OP_, OV, OS = 40, 41, 42, 43
WA, WB, WS, WP, WH, WN, WW, WD = 50, 51, 52, 53, 54, 55, 56, 57
PLIST, OLIST, WLIST = 60, 61, 62
OCNT_SLOT, WCNT_SLOT = 2, 3
SC = 950
COMBINE_SALT = 888888         # fixed salt for combine()'s random stat pick (distinct from the 555/777/1000 rolls)
DEBUG_PROBE = False           # test-only: resolve_battle persists its combat scratch to field 990 slots
_2_32 = 1 << 32
_INV232 = pow(1 << 32, F.P - 2, F.P)      # field inverse of 2^32 — exact hi-half extraction after LO32


# ---- python reference (the single source of truth; pets-genes.js and the E2E mirror THESE) ----------
def roll32(x):
    return alghash.hashn([x % F.P]) & 0xFFFFFFFF


def ref_gene(bh0, bh1, pid):
    return alghash.hashn([(bh0 % F.P + bh1 % F.P + pid) % F.P])


def ref_tier(gene):
    rt = roll32(gene + 555) % 100000
    return 1 + sum(1 for t in TIER_CUM if rt >= t)


def ref_si(gene, sp):
    return TIER_BASE[sp] + roll32(gene + 777) % TIER_COUNT[sp]


def ref_stat(gene, sp, i):
    return roll32(gene + 1000 + i) % 60 + 1 + (sp - 1) * STAT_TIER_BONUS


def ref_power(gene, sp):
    return sum(ref_stat(gene, sp, i) for i in range(10))


def ref_train_roll(bh0, bh1, pid, i):
    return roll32((bh0 % F.P + bh1 % F.P + pid * 16 + i) % F.P) % 100


def ref_train_ok(roll, cur, sp):
    k = 10 + 30 * sp
    return roll * (k + cur) < 100 * k


def ref_same_species(gene_a, sp_a, gene_b, sp_b):
    # two pets are the same species iff same tier AND same species-roll within that tier's band
    if sp_a != sp_b:
        return False
    return roll32(gene_a + 777) % TIER_COUNT[sp_a] == roll32(gene_b + 777) % TIER_COUNT[sp_b]


def ref_combine_stat(gene_keep, gene_consume):
    # which of the 10 stats gets +1 when two duplicates are combined (deterministic from both genes)
    return roll32(gene_keep + gene_consume + COMBINE_SALT) % 10


def ref_battle_turns(bh0, bh1, bid, eff_a, eff_b):
    """The 12-turn duel, byte-matching the contract. eff = the 10 EFFECTIVE stats (base + trained bonus).
    Returns (a_wins, dies, h0, h1, log)."""
    q = (bh0 % F.P + bh1 % F.P + bid * 8) % F.P
    ha = 20 + eff_a[2] * 3 + eff_a[9]
    hb = 20 + eff_b[2] * 3 + eff_b[9]
    h0, h1 = ha, hb
    span = eff_a[8] + eff_b[8] + 120
    log = []
    for t in range(CAP_BATTLE):
        alive = 1 if (h0 > 0 and h1 > 0) else 0
        cur = 0 if roll32(q + t + 8192) % span < eff_a[8] + 60 else 1
        A, B = (eff_a, eff_b) if cur == 0 else (eff_b, eff_a)
        acc = 15 + 2 * A[3]
        hit = 1 if roll32(q + t) % 100 * (acc + B[1]) < 100 * acc else 0
        dmg = (50 + A[0] + A[9] // 4) * (60 + roll32(q + t + 4096) % 61) // 100 + 1
        crit = 1 if roll32(q + t + 12288) % 100 < A[7] else 0
        dmg = dmg + crit * dmg
        dmg = dmg * 90 // (90 + B[4])
        dmg = max(1, dmg - B[5] // 2)
        dmg = min(HP_OFF, dmg)        # cap at the +HP_OFF shift so a lethal hit can't underflow the shifted HP
        dmg = dmg * hit * alive
        if cur == 0:
            h1 -= dmg
        else:
            h0 -= dmg
        h0 = min(ha, h0 + alive * (eff_a[6] // 4))
        h1 = min(hb, h1 + alive * (eff_b[6] // 4))
        log.append({"t": t, "atk": cur, "hit": hit and alive, "crit": crit and hit and alive,
                    "dmg": dmg, "h0": h0, "h1": h1})
    a_wins = max(h0, 0) * hb > max(h1, 0) * ha
    dies = roll32(q + 999999) % 100 < DIE_PCT
    return a_wins, dies, h0, h1, log


# ---- asm helpers -------------------------------------------------------------------------------------
def _sl(field, key="r0"):
    return [f"slot r4 {field} {key}"]


def _sc(i):
    return (SC << 32) | i


def _roll32(src_reg, out):
    """out = LO32(H(src_reg)) — the shared 32-bit roll window. Clobbers r4."""
    return [f"hash {out} <- {src_reg}", f"lo32 {out}"]


def _alive_pid(pid_reg):
    """require pet alive: cursor <= fu[pid]. Clobbers r4/r5/r6."""
    return [f"slot r4 {FU} {pid_reg}", "sload r5 r4", "ctx r6 cursor",
            "lt r5 r6", "notb r5", "require r5"]


MINT = "\n".join(
    ["ctx r3 value", f"movi r5 {MINT_FEE}", "eq r3 r5", "require r3",
     "movi r2 0", "lt r2 r0", "require r2",
     f"movi r2 {_2_32}", "mov r5 r0", "lt r5 r2", "require r5"]
    + _sl(OW) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    # burn tally += fee (the NADO stays on the contract with no spend path — burned, publicly tallied)
    + [f"movi r4 {BURN_SLOT}", "sload r5 r4", f"movi r6 {MINT_FEE}", "add r5 r6", "sstore r4 r5"]
    + ["ctx r5 caller"] + _sl(OW) + ["sstore r4 r5"]
    + _sl(BH) + ["ctx r5 cursor", f"movi r6 {HATCH_DELAY}", "add r5 r6", "sstore r4 r5"]
    + _sl(FU) + ["ctx r5 cursor", f"movi r6 {HATCH_DELAY + START_BELLY}", "add r5 r6", "sstore r4 r5"]
    + _sl(TF) + [f"movi r5 {MINT_FEE}", "sstore r4 r5"]
    + ["movi r4 0", "sload r5 r4", f"slot r6 {PLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])


def _hatch():
    L = _sl(OW) + ["sload r5 r4", "require r5"]                                  # exists
    L += _sl(GN) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]            # not hatched
    L += _sl(BH) + ["sload r5 r4", "movi r6 1", "add r5 r6",
                    "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]        # gene blocks exist
    L += _alive_pid("r0")
    # gene = H(bh0 + bh1 + pid)
    L += _sl(BH) + ["sload r5 r4", "bhash r3 r5", "movi r6 1", "add r5 r6", "bhash r6 r5",
                    "add r3 r6", "add r3 r0", "hash r3 <- r3"]
    L += _sl(GN) + ["sstore r4 r3"]
    # gl/gh: exact 32-bit halves for the browser (JS floats can't carry a field element)
    L += ["mov r5 r3", "lo32 r5"] + _sl(GL) + ["sstore r4 r5"]
    L += ["mov r6 r3", "sub r6 r5", f"movi r4 {_INV232}", "mul r6 r4"] + _sl(GH) + ["sstore r4 r6"]
    # tier: rt = roll32(gn+555) % 100000 ; sp = 1 + Σ(rt >= T)
    L += ["mov r5 r3", "movi r6 555", "add r5 r6"] + _roll32("r5", "r5")
    L += ["movi r6 100000", "divmodw r5 r6", "mov r5 r7"]                        # rt
    L += ["movi r2 1"]
    for t in TIER_CUM:
        L += ["mov r6 r5", f"movi r4 {t}", "lt r6 r4", "notb r6", "add r2 r6"]
    L += _sl(SP) + ["sstore r4 r2"]
    # species band (values-driven, so ANY TIER_COUNT works — the counts need not decrease monotonically):
    #   count = Σ_{t=1..6} (sp==t)·COUNT[t]  ;  base = 1 + Σ_{t=2..6} (sp>=t)·COUNT[t-1]  (= TIER_BASE[sp])
    L += ["movi r1 0"]                                                           # r1 = count accumulator
    for t in range(1, 7):
        L += ["mov r5 r2", f"movi r6 {t}", "eq r5 r6",                           # sp == t
              f"movi r6 {TIER_COUNT[t]}", "mul r5 r6", "add r1 r5"]
    L += ["movi r6 1", f"movi r4 {_sc(0)}", "sstore r4 r6"]                      # SC0 = base = 1
    for t in range(2, 7):
        L += ["mov r5 r2", f"movi r6 {t}", "lt r5 r6", "notb r5",               # sp >= t
              f"movi r6 {TIER_COUNT[t - 1]}", "mul r5 r6",
              f"movi r4 {_sc(0)}", "sload r6 r4", "add r6 r5", "sstore r4 r6"]   # base += COUNT[t-1]·flag
    L += ["mov r5 r3", "movi r6 777", "add r5 r6"] + _roll32("r5", "r5")
    L += ["divmod r5 r1", f"movi r4 {_sc(0)}", "sload r6 r4", "add r6 r7"]       # si = base + roll%count
    L += _sl(SI) + ["sstore r4 r6"]
    # stats: ap = stat9 ; pw = Σ stats. stat_i = roll32(gn+1000+i)%60 + 1 + (sp-1)*6
    L += ["movi r1 0"]                                                           # r1 = power accumulator
    for i in range(10):
        L += ["mov r5 r3", f"movi r6 {1000 + i}", "add r5 r6"] + _roll32("r5", "r5")
        L += ["movi r6 60", "rem r5 r6", "movi r6 1", "add r5 r6",
              "mov r6 r2", "movi r4 1", "sub r6 r4", f"movi r4 {STAT_TIER_BONUS}", "mul r6 r4",
              "add r5 r6", "add r1 r5"]
        if i == 9:
            L += _sl(AP) + ["sstore r4 r5"]
    L += _sl(PW) + ["sstore r4 r1"]
    L += [f"movi r4 {_sc(0)}", "movi r5 0", "sstore r4 r5", "ret r0"]            # scrub scratch
    return L


REBIRTH = "\n".join(
    ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(GN) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _alive_pid("r0")
    + _sl(BH) + ["sload r5 r4", f"movi r6 {STALE}", "add r5 r6",
                 "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]           # gene block pruned
    + _sl(BH) + ["ctx r5 cursor", f"movi r6 {HATCH_DELAY}", "add r5 r6", "sstore r4 r5", "ret r0"])

FEED = "\n".join(
    ["ctx r3 value", "movi r2 0", "lt r2 r3", "require r2"]
    + _sl(GN) + ["sload r5 r4", "require r5"]                                    # hatched
    + _alive_pid("r0")
    + [f"movi r4 {BURN_SLOT}", "sload r5 r4", "add r5 r3", "sstore r4 r5"]       # burn the meal
    # gained blocks = value // (appetite * FEED_DIV) — a data-sized divisor: DIVMODW
    + _sl(AP) + ["sload r5 r4", f"movi r6 {FEED_DIV}", "mul r5 r6",
                 "mov r2 r3", "divmodw r2 r5",
                 "movi r6 0", "lt r6 r2", "require r6"]                          # gained > 0
    + _sl(FU) + ["sload r5 r4", "add r5 r2",
                 "ctx r6 cursor", f"movi r1 {BELLY_CAP}", "add r6 r1",
                 "mov r1 r6", "lt r1 r5", "notb r1", "require r1",               # belly cap
                 "sstore r4 r5"]
    + _sl(TF) + ["sload r5 r4", "add r5 r3", "sstore r4 r5", "ret r0"])

TRANSFER = "\n".join(
    ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _alive_pid("r0")
    + ["mov r5 r1", "nez r5", "require r5",                                      # a real recipient digest
       "ctx r5 caller", "mov r6 r1", "eq r6 r5", "notb r6", "require r6"]
    + _sl(OW) + ["sstore r4 r1"]
    + _sl(MP) + ["movi r5 0", "sstore r4 r5", "ret r0"])                         # hand-off clears the listing

NAME = "\n".join(
    ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(NM) + ["sload r5 r4", "nez r5", "notb r5", "require r5",               # named ONCE, for life
                 "mov r5 r1", "nez r5", "require r5", "sstore r4 r1", "ret r0"])

LIST_ = "\n".join(
    ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _alive_pid("r0")
    + ["movi r5 0", "lt r5 r1", "require r5"]
    + _sl(MP) + ["sstore r4 r1", "ret r0"])

UNLIST = "\n".join(
    ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(MP) + ["sload r5 r4", "require r5", "movi r5 0", "sstore r4 r5", "ret r0"])

BUY = "\n".join(
    _sl(MP) + ["sload r3 r4", "require r3"]                                      # it IS for sale
    + ["ctx r5 value", "eq r5 r3", "require r5"]                                 # exact ask
    + _alive_pid("r0")
    + ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "notb r6", "require r6"]
    + _sl(OW) + ["sload r5 r4", "pay r5 r3",                                     # price -> seller
                 "ctx r6 caller", "sstore r4 r6"]                                # pet -> buyer
    + _sl(MP) + ["movi r5 0", "sstore r4 r5", "ret r0"])

OFFER = "\n".join(
    ["movi r2 0", "lt r2 r0", "require r2",
     f"movi r2 {_2_32}", "mov r5 r0", "lt r5 r2", "require r5"]
    + _sl(OS) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]               # fresh offer id
    + ["ctx r3 value", "movi r2 0", "lt r2 r3", "require r2"]
    + [f"slot r4 {OW} r1", "sload r5 r4", "require r5"]                          # the pet exists
    + _alive_pid("r1")
    + ["ctx r5 caller", f"slot r4 {OW} r1", "sload r6 r4", "eq r6 r5", "notb r6", "require r6"]
    + ["ctx r5 caller"] + _sl(OB) + ["sstore r4 r5"]
    + _sl(OP_) + ["sstore r4 r1"] + _sl(OV) + ["sstore r4 r3"]
    + _sl(OS) + ["movi r5 1", "sstore r4 r5"]
    + [f"movi r4 {OCNT_SLOT}", "sload r5 r4", f"slot r6 {OLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])

ACCEPT_OFFER = "\n".join(
    _sl(OS) + ["sload r5 r4", "movi r6 1", "eq r5 r6", "require r5"]
    + _sl(OP_) + ["sload r1 r4"]                                                 # r1 = the offered pet
    + ["ctx r5 caller", f"slot r4 {OW} r1", "sload r6 r4", "eq r6 r5", "require r6"]
    + _alive_pid("r1")
    + ["ctx r5 caller"] + _sl(OV) + ["sload r3 r4", "pay r5 r3"]                 # escrow -> owner
    + _sl(OB) + ["sload r5 r4", f"slot r4 {OW} r1", "sstore r4 r5"]              # pet -> buyer
    + [f"slot r4 {MP} r1", "movi r5 0", "sstore r4 r5"]
    + _sl(OS) + ["movi r5 2", "sstore r4 r5", "ret r0"])

CANCEL_OFFER = "\n".join(
    ["ctx r5 caller"] + _sl(OB) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(OS) + ["sload r5 r4", "movi r6 1", "eq r5 r6", "require r5"]
    + ["ctx r5 caller"] + _sl(OV) + ["sload r3 r4", "pay r5 r3"]
    + _sl(OS) + ["movi r5 2", "sstore r4 r5", "ret r0"])

TRAIN = "\n".join(
    ["ctx r3 value", f"movi r5 {TRAIN_FEE}", "eq r3 r5", "require r3",
     "mov r5 r1", "movi r6 10", "lt r5 r6", "require r5"]                        # stat 0..9
    + ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(GN) + ["sload r5 r4", "require r5"]
    + _alive_pid("r0")
    # no pending session, or the pending one's hash is pruned (its fee is forfeit)
    + _sl(TH) + ["sload r5 r4", "nez r5", "notb r5",
                 "mov r6 r5"]                                                    # r6 = none-pending
    + _sl(TH) + ["sload r5 r4", f"movi r2 {STALE}", "add r5 r2", "ctx r2 cursor", "lt r5 r2",
                 "add r6 r5", "nez r6", "require r6"]
    + [f"movi r4 {BURN_SLOT}", "sload r5 r4", f"movi r6 {TRAIN_FEE}", "add r5 r6", "sstore r4 r5"]
    + _sl(TH) + ["ctx r5 cursor", f"movi r6 {HATCH_DELAY}", "add r5 r6", "sstore r4 r5"]
    + _sl(TI) + ["mov r5 r1", "movi r6 1", "add r5 r6", "sstore r4 r5"]          # 1-based
    + _sl(TF) + ["sload r5 r4", f"movi r6 {TRAIN_FEE}", "add r5 r6", "sstore r4 r5", "ret r0"])


def _eff_stat(pid_reg, i_sc, out):
    """out = effective stat: roll32(gn+1000+i)%60 + 1 + (sp-1)*6 + tb[pid,i]. The stat index comes from
    scratch slot i_sc (runtime). Clobbers r4/r5/r6/r7 (+ out)."""
    return ([f"slot r4 {GN} {pid_reg}", f"sload {out} r4",
             f"movi r5 {i_sc}", "sload r5 r5", "movi r6 1000", "add r5 r6", f"add {out} r5"]
            + _roll32(out, out)
            + ["movi r5 60", f"divmod {out} r5", f"mov {out} r7", "movi r5 1", f"add {out} r5",
               f"slot r4 {SP} {pid_reg}", "sload r5 r4", "movi r6 1", "sub r5 r6",
               f"movi r6 {STAT_TIER_BONUS}", "mul r5 r6", f"add {out} r5",
               # + trained bonus: field (TB_BASE + i) keyed pid
               f"movi r4 {TB_BASE}", f"movi r5 {i_sc}", "sload r5 r5", "add r4 r5",
               f"movi r5 {_2_32}", "mul r4 r5", f"add r4 {pid_reg}", "sload r5 r4", f"add {out} r5",
               # + GEAR: field (GB_BASE + i) keyed pid. Adding it HERE is the whole integration — every
               # place a stat is read (the arena's 20 effective stats, the card, the training preview)
               # picks equipment up for free, so a found sword actually makes the pet better rather than
               # being a number in a bag the combat code never sees.
               f"movi r4 {GB_BASE}", f"movi r5 {i_sc}", "sload r5 r5", "add r4 r5",
               f"movi r5 {_2_32}", "mul r4 r5", f"add r4 {pid_reg}", "sload r5 r4", f"add {out} r5"])


def _train_resolve():
    L = _sl(TH) + ["sload r5 r4", "require r5"]
    L += _sl(TH) + ["sload r5 r4", "movi r6 1", "add r5 r6",
                    "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    # i -> SC1 ; cur = eff stat -> r1
    L += _sl(TI) + ["sload r5 r4", "movi r6 1", "sub r5 r6", f"movi r4 {_sc(1)}", "sstore r4 r5"]
    L += _eff_stat("r0", _sc(1), "r1")
    # roll = roll32(bh(th)+bh(th+1)+pid*16+i) % 100 -> r2
    L += _sl(TH) + ["sload r5 r4", "bhash r2 r5", "movi r6 1", "add r5 r6", "bhash r6 r5", "add r2 r6",
                    "mov r5 r0", "movi r6 16", "mul r5 r6", "add r2 r5",
                    f"movi r5 {_sc(1)}", "sload r5 r5", "add r2 r5"]
    L += _roll32("r2", "r2") + ["movi r5 100", "rem r2 r5"]
    # success = roll*(K+cur) < 100*K ; K = 10 + 30*sp
    L += _sl(SP) + ["sload r5 r4", "movi r6 30", "mul r5 r6", "movi r6 10", "add r5 r6"]   # K
    L += ["mov r6 r5", "add r6 r1", "mul r2 r6",                                 # roll*(K+cur)
          "movi r6 100", "mul r5 r6",                                            # 100*K
          "lt r2 r5"]                                                            # r2 = success
    # tb[pid,i] += success ; pw += success ; tr = 2 - success ; session closed
    L += [f"movi r4 {TB_BASE}", f"movi r5 {_sc(1)}", "sload r5 r5", "add r4 r5",
          f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0", "sload r5 r4", "add r5 r2", "sstore r4 r5"]
    L += _sl(PW) + ["sload r5 r4", "add r5 r2", "sstore r4 r5"]
    L += _sl(TR) + ["movi r5 2", "sub r5 r2", "sstore r4 r5"]
    L += _sl(TH) + ["movi r5 0", "sstore r4 r5"] + _sl(TI) + ["movi r5 0", "sstore r4 r5"]
    L += [f"movi r4 {_sc(1)}", "movi r5 0", "sstore r4 r5", "ret r0"]
    return L


def _combine():
    """combine(keep=r0, consume=r1): merge two SAME-SPECIES pets you own — BURN consume and grant keep +1
    to a random trained stat (index from both genes). Species match = same tier AND same species-roll
    within that tier's band, both recomputed from the immutable gene (robust to any roster remap). A pure
    sink: no NADO minted or paid, the burned pet is the whole cost. (Modelled on FEH 'merge allies'.)"""
    L = ["movi r2 0", "lt r2 r0", "require r2", f"movi r2 {_2_32}", "mov r5 r0", "lt r5 r2", "require r5",
         "movi r2 0", "lt r2 r1", "require r2", f"movi r2 {_2_32}", "mov r5 r1", "lt r5 r2", "require r5"]
    L += ["mov r5 r0", "eq r5 r1", "notb r5", "require r5"]                       # keep != consume
    L += ["ctx r5 caller"]
    L += [f"slot r4 {OW} r0", "sload r6 r4", "mov r3 r5", "eq r6 r3", "require r6"]   # own keep
    L += [f"slot r4 {OW} r1", "sload r6 r4", "mov r3 r5", "eq r6 r3", "require r6"]   # own consume
    L += [f"slot r4 {GN} r0", "sload r5 r4", "require r5"]                        # keep hatched
    L += [f"slot r4 {GN} r1", "sload r5 r4", "require r5"]                        # consume hatched
    L += _alive_pid("r0")                                                        # keep alive
    L += [f"slot r4 {EX} r0", "sload r5 r4", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]   # keep rested
    L += [f"slot r4 {EX} r1", "sload r5 r4", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]   # consume rested
    # same tier (sp -> r2) then same species-roll within the band
    L += [f"slot r4 {SP} r0", "sload r2 r4", f"slot r4 {SP} r1", "sload r5 r4", "mov r6 r2", "eq r6 r5", "require r6"]
    L += ["movi r3 0"]                                                           # count = Σ (sp==t)·COUNT[t]
    for t in range(1, 7):
        L += ["mov r5 r2", f"movi r6 {t}", "eq r5 r6", f"movi r6 {TIER_COUNT[t]}", "mul r5 r6", "add r3 r5"]
    L += [f"slot r4 {GN} r0", "sload r5 r4", "movi r6 777", "add r5 r6"] + _roll32("r5", "r5")
    L += ["divmod r5 r3", f"movi r4 {_sc(2)}", "sstore r4 r7"]                    # rA = roll%count -> SC2
    L += [f"slot r4 {GN} r1", "sload r5 r4", "movi r6 777", "add r5 r6"] + _roll32("r5", "r5")
    L += ["divmod r5 r3", "mov r6 r7", f"movi r4 {_sc(2)}", "sload r5 r4", "eq r5 r6", "require r5"]   # rA == rB
    # reward: i = roll32(gn_keep + gn_consume + SALT) % 10 -> r2 ; tb[keep,i] += 1 ; pw[keep] += 1
    L += [f"slot r4 {GN} r0", "sload r5 r4", f"slot r4 {GN} r1", "sload r6 r4", "add r5 r6",
          f"movi r6 {COMBINE_SALT}", "add r5 r6"] + _roll32("r5", "r5") + ["movi r6 10", "divmod r5 r6", "mov r2 r7"]
    L += [f"movi r4 {TB_BASE}", "add r4 r2", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
          "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    L += _sl(PW, "r0") + ["sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    # burn consume: no owner, clear its listing
    L += [f"slot r4 {OW} r1", "movi r5 0", "sstore r4 r5"]
    L += [f"slot r4 {MP} r1", "movi r5 0", "sstore r4 r5"]
    L += [f"movi r4 {_sc(2)}", "movi r5 0", "sstore r4 r5", "ret r0"]             # scrub scratch
    return L


# release(pid): give up ANY pet or egg you own — a pure inventory-clear, no reward. Owner-only; blocked
# while the pet is in/just-out of a battle (EX) so a wagered pet can't be burned out from under its stake.
RELEASE = "\n".join(
    ["movi r2 0", "lt r2 r0", "require r2", f"movi r2 {_2_32}", "mov r5 r0", "lt r5 r2", "require r5"]
    + ["ctx r5 caller"] + _sl(OW) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(EX) + ["sload r5 r4", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    + _sl(OW) + ["movi r5 0", "sstore r4 r5"]
    + _sl(MP) + ["movi r5 0", "sstore r4 r5", "ret r0"])

CHALLENGE = "\n".join(
    ["movi r3 0", "lt r3 r0", "require r3",
     f"movi r3 {_2_32}", "mov r5 r0", "lt r5 r3", "require r5"]
    + _sl(WN) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + [f"slot r4 {GN} r1", "sload r5 r4", "require r5",                          # both hatched
       f"slot r4 {GN} r2", "sload r5 r4", "require r5"]
    + ["ctx r5 caller", f"slot r4 {OW} r1", "sload r6 r4", "eq r6 r5", "require r6"]   # mine
    + _alive_pid("r1") + _alive_pid("r2")
    + [f"slot r4 {EX} r1", "sload r5 r4", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6",  # rested
       f"slot r4 {EX} r2", "sload r5 r4", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    + ["mov r5 r1", "eq r5 r2", "notb r5", "require r5"]
    + _sl(WA) + ["sstore r4 r1"] + _sl(WB) + ["sstore r4 r2"]
    + ["ctx r3 value"] + _sl(WS) + ["sstore r4 r3"] + _sl(WP) + ["sstore r4 r3"]
    + _sl(WN) + ["movi r5 1", "sstore r4 r5"]
    + [f"movi r4 {WCNT_SLOT}", "sload r5 r4", f"slot r6 {WLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])

ACCEPT = "\n".join(
    _sl(WN) + ["sload r5 r4", "movi r6 1", "eq r5 r6", "require r5"]
    + _sl(WB) + ["sload r1 r4"] + _sl(WA) + ["sload r2 r4"]
    + ["ctx r5 caller", f"slot r4 {OW} r1", "sload r6 r4", "eq r6 r5", "require r6"]   # defender consents
    + ["ctx r3 value"] + _sl(WS) + ["sload r5 r4", "eq r5 r3", "require r5"]
    + _alive_pid("r1") + _alive_pid("r2")
    + [f"slot r4 {EX} r1", "sload r5 r4", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6",
       f"slot r4 {EX} r2", "sload r5 r4", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    + _sl(WP) + ["sload r5 r4", "add r5 r3", "sstore r4 r5"]
    + _sl(WH) + ["ctx r5 cursor", f"movi r6 {HATCH_DELAY}", "add r5 r6", "sstore r4 r5"]
    + [f"slot r4 {EX} r1", "ctx r5 cursor", f"movi r6 {HATCH_DELAY + EXHAUST}", "add r5 r6", "sstore r4 r5",
       f"slot r4 {EX} r2", "ctx r5 cursor", f"movi r6 {HATCH_DELAY + EXHAUST}", "add r5 r6", "sstore r4 r5"]
    + _sl(WN) + ["movi r5 2", "sstore r4 r5", "ret r0"])


# battle scratch slots (keyed by bid): 0..9 effA · 10..19 effB · then the combat registers
_Q, _M0, _M1, _H0, _H1, _SA, _SPAN, _IDX, _T1 = 20, 21, 22, 23, 24, 25, 26, 27, 28


def _bsl(i):
    return (SC << 32) | i


def _resolve_battle():
    """resolve_battle(bid): permissionless once wh, wh+1 are finalized — replays the whole 12-turn duel
    from the beacon, mirroring ref_battle_turns exactly (HP shifted +1024 for field-positive math)."""
    L = _sl(WN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
    L += _sl(WH) + ["sload r5 r4", "movi r6 1", "add r5 r6",
                    "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    # q = bh(wh)+bh(wh+1)+bid*8 -> scratch
    L += _sl(WH) + ["sload r5 r4", "bhash r3 r5", "movi r6 1", "add r5 r6", "bhash r6 r5", "add r3 r6",
                    "mov r5 r0", "movi r6 8", "mul r5 r6", "add r3 r5",
                    f"movi r4 {_bsl(_Q)}", "sstore r4 r3"]
    # the 20 effective stats -> scratch 0..19 (loop i over a scratch index)
    for side, (pid_field, base) in enumerate(((WA, 0), (WB, 10))):
        L += [f"slot r4 {pid_field} r0", "sload r1 r4"]                          # r1 = pid
        for i in range(10):
            L += [f"movi r4 {_bsl(_IDX)}", f"movi r5 {i}", "sstore r4 r5"]
            L += _eff_stat("r1", _bsl(_IDX), "r2")
            L += [f"movi r4 {_bsl(base + i)}", "sstore r4 r2"]
    # maxes + shifted HP + turn-share span
    def eff(side, i):
        return _bsl((0 if side == 0 else 10) + i)
    L += [f"movi r4 {eff(0, 2)}", "sload r5 r4", "movi r6 3", "mul r5 r6", "movi r6 20", "add r5 r6",
          f"movi r4 {eff(0, 9)}", "sload r6 r4", "add r5 r6",
          f"movi r4 {_bsl(_M0)}", "sstore r4 r5",
          f"movi r6 {HP_OFF}", "add r5 r6", f"movi r4 {_bsl(_H0)}", "sstore r4 r5"]
    L += [f"movi r4 {eff(1, 2)}", "sload r5 r4", "movi r6 3", "mul r5 r6", "movi r6 20", "add r5 r6",
          f"movi r4 {eff(1, 9)}", "sload r6 r4", "add r5 r6",
          f"movi r4 {_bsl(_M1)}", "sstore r4 r5",
          f"movi r6 {HP_OFF}", "add r5 r6", f"movi r4 {_bsl(_H1)}", "sstore r4 r5"]
    L += [f"movi r4 {eff(0, 8)}", "sload r5 r4", "movi r6 60", "add r5 r6",
          f"movi r4 {_bsl(_SA)}", "sstore r4 r5",
          f"movi r4 {eff(1, 8)}", "sload r6 r4", "add r5 r6", "movi r6 60", "add r5 r6",
          f"movi r4 {_bsl(_SPAN)}", "sstore r4 r5"]
    # ---- the 12 unrolled turns ----
    for t in range(CAP_BATTLE):
        # alive = (h0 > OFF) & (h1 > OFF)  -> r1
        L += [f"movi r4 {_bsl(_H0)}", "sload r5 r4", f"movi r6 {HP_OFF}", "lt r6 r5", "mov r1 r6",
              f"movi r4 {_bsl(_H1)}", "sload r5 r4", f"movi r6 {HP_OFF}", "lt r6 r5", "mul r1 r6"]
        # cu = !(roll32(q+t+8192) % span < sA)  -> r2
        L += [f"movi r4 {_bsl(_Q)}", "sload r5 r4", f"movi r6 {t + 8192}", "add r5 r6"]
        L += _roll32("r5", "r5")
        L += [f"movi r4 {_bsl(_SPAN)}", "sload r6 r4", "divmodw r5 r6", "mov r5 r7",
              f"movi r4 {_bsl(_SA)}", "sload r6 r4", "lt r5 r6", "notb r5", "mov r2 r5"]
        # attacker/defender stat s: att(i) = effA_i*(1-cu) + effB_i*cu ; def(i) = the other side
        def att(i, out):
            return [f"movi r4 {eff(0, i)}", f"sload {out} r4", "mov r5 r2", "notb r5", f"mul {out} r5",
                    f"movi r4 {eff(1, i)}", "sload r5 r4", "mul r5 r2", f"add {out} r5"]
        def dfn(i, out):
            return [f"movi r4 {eff(1, i)}", f"sload {out} r4", "mov r5 r2", "notb r5", f"mul {out} r5",
                    f"movi r4 {eff(0, i)}", "sload r5 r4", "mul r5 r2", f"add {out} r5"]
        # acc = 15 + 2*att(3) -> r3
        L += att(3, "r3") + ["movi r5 2", "mul r3 r5", "movi r5 15", "add r3 r5"]
        # hit: roll32(q+t)%100 * (acc + def(1)) < 100*acc  -> SC(_IDX) (temporary)
        # (att/dfn use r5 internally, so the roll is PARKED in scratch across the stat select)
        L += [f"movi r4 {_bsl(_Q)}", "sload r5 r4", f"movi r6 {t}", "add r5 r6"]
        L += _roll32("r5", "r5") + ["movi r6 100", "divmod r5 r6",
                                    f"movi r4 {_bsl(_T1)}", "sstore r4 r7"]      # park roll%100
        L += dfn(1, "r6") + ["add r6 r3",
                             f"movi r4 {_bsl(_T1)}", "sload r5 r4", "mul r5 r6",
                             "mov r6 r3", "movi r4 100", "mul r6 r4", "lt r5 r6",
                             f"movi r4 {_bsl(_IDX)}", "sstore r4 r5"]            # hit flag parked
        # dmg = (50 + att(0) + att(9)//4) * (60 + roll32(q+t+4096)%61) // 100 + 1  -> r3
        L += att(0, "r3") + ["movi r5 50", "add r3 r5"]
        L += att(9, "r6") + ["movi r5 4", "divmod r6 r5", "add r3 r6"]
        L += [f"movi r4 {_bsl(_Q)}", "sload r5 r4", f"movi r6 {t + 4096}", "add r5 r6"]
        L += _roll32("r5", "r5") + ["movi r6 61", "rem r5 r6", "movi r6 60", "add r5 r6",
                                    "mul r3 r5", "movi r5 100", "divmod r3 r5", "movi r5 1", "add r3 r5"]
        # crit: roll32(q+t+12288)%100 < att(7)  ->  dmg += crit*dmg   (roll parked across the stat select)
        L += [f"movi r4 {_bsl(_Q)}", "sload r5 r4", f"movi r6 {t + 12288}", "add r5 r6"]
        L += _roll32("r5", "r5") + ["movi r6 100", "divmod r5 r6",
                                    f"movi r4 {_bsl(_T1)}", "sstore r4 r7"]
        L += att(7, "r6") + [f"movi r4 {_bsl(_T1)}", "sload r5 r4",
                             "lt r5 r6", "mul r5 r3", "add r3 r5"]
        # wisdom mitigation: dmg = dmg*90 // (90 + def(4))
        L += ["movi r5 90", "mul r3 r5"] + dfn(4, "r6") + ["movi r5 90", "add r6 r5", "divmod r3 r6"]
        # charisma: dmg = max(1, dmg - def(5)//2) — compute (dmg-cha2)·(dmg>=cha2) (the field wrap of a
        # negative difference is killed by the ×0 gate), then bump an exact 0 to 1
        L += dfn(5, "r6") + ["movi r5 2", "divmod r6 r5",
                             "mov r5 r3", "lt r5 r6", "notb r5",                 # ge = dmg >= cha2
                             "sub r3 r6", "mul r3 r5",                           # (dmg-cha2)·ge
                             "mov r5 r3", "movi r6 1", "lt r5 r6",               # became 0 -> force 1
                             "add r3 r5"]
        # cap dmg at HP_OFF so a lethal hit can't underflow the +HP_OFF-shifted HP (trained str/app can push
        # raw dmg past 1024 -> the shifted HP wraps to ~p and every later LT reverts, bricking resolve_battle).
        # dmg -= (dmg - OFF)·(OFF < dmg); the field wrap of a negative diff is killed by the ×0 gate.
        L += ["mov r5 r3", f"movi r6 {HP_OFF}", "lt r6 r5", f"movi r4 {HP_OFF}", "sub r5 r4", "mul r5 r6", "sub r3 r5"]
        # dmg *= hit * alive ; apply to the defender's shifted HP
        L += [f"movi r4 {_bsl(_IDX)}", "sload r5 r4", "mul r3 r5", "mul r3 r1"]
        L += ["mov r5 r2", "mul r5 r3",                                          # B attacking -> A loses
              f"movi r4 {_bsl(_H0)}", "sload r6 r4", "sub r6 r5", "sstore r4 r6"]
        L += ["mov r5 r2", "notb r5", "mul r5 r3",
              f"movi r4 {_bsl(_H1)}", "sload r6 r4", "sub r6 r5", "sstore r4 r6"]
        # regen (alive-gated, capped at max): h += al*(loy//4) ; h -= (h - cap)·(h > cap)
        for side, (hs, ms) in enumerate(((_H0, _M0), (_H1, _M1))):
            L += [f"movi r4 {eff(side, 6)}", "sload r5 r4", "movi r6 4", "divmod r5 r6", "mul r5 r1",
                  f"movi r4 {_bsl(hs)}", "sload r6 r4", "add r6 r5",
                  f"movi r4 {_bsl(ms)}", "sload r5 r4", f"movi r3 {HP_OFF}", "add r5 r3",   # cap' = m + OFF
                  "mov r3 r5", "lt r3 r6",                                       # over = cap < h
                  "mov r5 r6", f"movi r4 {_bsl(ms)}", "sload r2 r4", f"movi r4 {HP_OFF}", "add r2 r4",
                  "sub r5 r2", "mul r5 r3",                                      # (h-cap)·over
                  "sub r6 r5", f"movi r4 {_bsl(hs)}", "sstore r4 r6"]
            if side == 0:
                # r2 (cu) was clobbered by the cap math — recompute is impossible; park/restore via scratch
                pass
        # NOTE: r2/cu is dead after the damage application; regen doesn't need it.
        pass
    # winner: clamp negatives (ha = (h0'-OFF)·(h0' > OFF)), a_wins = ha·m1 > hb·m0 (tie -> defender)
    L += [f"movi r4 {_bsl(_H0)}", "sload r5 r4", f"movi r6 {HP_OFF}", "lt r6 r5",     # pos0
          "mov r1 r5", f"movi r2 {HP_OFF}", "sub r1 r2", "mul r1 r6"]                 # ha
    L += [f"movi r4 {_bsl(_H1)}", "sload r5 r4", f"movi r6 {HP_OFF}", "lt r6 r5",
          "mov r2 r5", f"movi r3 {HP_OFF}", "sub r2 r3", "mul r2 r6"]                 # hb
    L += [f"movi r4 {_bsl(_M1)}", "sload r5 r4", "mul r1 r5",
          f"movi r4 {_bsl(_M0)}", "sload r5 r4", "mul r2 r5",
          "lt r2 r1"]                                                                 # r2 = a_wins
    # ww = wa·a + wb·(1-a) ; lo = wa+wb-ww
    L += _sl(WA) + ["sload r5 r4", "mul r5 r2", "mov r3 r5"]
    L += ["mov r5 r2", "notb r5"] + _sl(WB) + ["sload r6 r4", "mul r6 r5", "add r3 r6"]
    L += _sl(WW) + ["sstore r4 r3"]
    L += _sl(WA) + ["sload r1 r4"] + _sl(WB) + ["sload r5 r4", "add r1 r5", "sub r1 r3"]   # r1 = loser
    # records
    L += [f"slot r4 {WINS} r3", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5",
          f"slot r4 {LOSS} r1", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    # CLAIM: loser pet -> the winner's owner; clears its listing
    L += [f"slot r4 {OW} r3", "sload r5 r4", f"slot r4 {OW} r1", "sstore r4 r5",
          f"slot r4 {MP} r1", "movi r5 0", "sstore r4 r5"]
    # death: dies = roll32(q+999999)%100 < DIE_PCT ; fu[loser] = dies ? 1 : fu
    L += [f"movi r4 {_bsl(_Q)}", "sload r5 r4", "movi r6 999999", "add r5 r6"]
    L += _roll32("r5", "r5") + ["movi r6 100", "rem r5 r6",
                                f"movi r6 {DIE_PCT}", "lt r5 r6"]                     # r5 = dies
    L += [f"slot r4 {FU} r1", "sload r6 r4", "mov r2 r5", "notb r2", "mul r6 r2", "add r6 r5",
          "sstore r4 r6"]
    L += ["mul r5 r1"] + _sl(WD) + ["sstore r4 r5"]                                   # wd = dies·loser
    # pot -> the winner pet's owner
    L += [f"slot r4 {OW} r3", "sload r5 r4"] + _sl(WP) + ["sload r6 r4", "pay r5 r6"]
    L += _sl(WN) + ["movi r5 3", "sstore r4 r5"] + _sl(WP) + ["movi r5 0", "sstore r4 r5"]
    if DEBUG_PROBE:                                   # test-only: persist the combat scratch for inspection
        for i in list(range(20)) + [_Q, _M0, _M1, _H0, _H1, _SA, _SPAN]:
            L += [f"movi r4 {_bsl(i)}", "sload r5 r4", f"movi r4 {(990 << 32) + i}", "sstore r4 r5"]
    # scrub the battle scratch
    for i in list(range(20)) + [_Q, _M0, _M1, _H0, _H1, _SA, _SPAN, _IDX, _T1]:
        L += [f"movi r4 {_bsl(i)}", "movi r5 0", "sstore r4 r5"]
    L += ["ret r0"]
    return L


CANCEL_BATTLE = "\n".join(
    _sl(WN) + ["sload r5 r4", "movi r6 1", "eq r5 r6", "require r5"]
    + _sl(WA) + ["sload r1 r4"]
    + ["ctx r5 caller", f"slot r4 {OW} r1", "sload r6 r4", "eq r6 r5", "require r6"]
    + [f"slot r4 {OW} r1", "sload r5 r4"] + _sl(WP) + ["sload r6 r4", "pay r5 r6"]
    + _sl(WN) + ["movi r5 3", "sstore r4 r5"] + _sl(WP) + ["movi r5 0", "sstore r4 r5", "ret r0"])

REFUND_BATTLE = "\n".join(
    _sl(WN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
    + _sl(WH) + ["sload r5 r4", f"movi r6 {STALE}", "add r5 r6",
                 "ctx r6 cursor", "lt r5 r6", "require r5"]                      # cursor > wh + STALE
    + _sl(WA) + ["sload r1 r4", f"slot r4 {OW} r1", "sload r5 r4"]
    + _sl(WS) + ["sload r6 r4", "pay r5 r6"]                                     # stake back to challenger
    + _sl(WB) + ["sload r1 r4", f"slot r4 {OW} r1", "sload r5 r4"]
    + _sl(WP) + ["sload r6 r4"] + _sl(WS) + ["sload r3 r4", "sub r6 r3", "pay r5 r6"]
    + _sl(WN) + ["movi r5 3", "sstore r4 r5"] + _sl(WP) + ["movi r5 0", "sstore r4 r5", "ret r0"])

# ==== HOMESTEAD: trades, base building, resources and gear =========================================
# The tamagotchi loop only ever ran DOWN: every pet costs NADO to feed and dies without it. Homestead is
# the other half — pets that WORK. A pet has a TRADE it was born to (derived from its species, so it is a
# fact about the animal, not a choice), a building of that trade can be staffed with it, and the building
# produces a resource for as long as it is staffed. Fodder feeds the whole barn for free, which closes the
# upkeep loop; the other four resources build and upgrade the base. Work also turns up GEAR, which is where
# the Diablo part lives: items roll random affixes on real stats, scaled by the finder's rarity, and
# equipping one adds those points to the pet — so a found sword makes that pet measurably better in the
# arena rather than being a trophy in a bag.
#
# Everything accrues LAZILY: a building stores only WHEN it was last collected, and collect() pays out
# elapsed_blocks x rate. Nothing runs on a timer, nothing needs a keeper, and an idle base costs nothing to
# hold — the same shape the rest of these games use for anything time-based.
NJOBS = 5                     # trade / resource ids: 0 fodder · 1 timber · 2 stone · 3 ore · 4 essence
GB_BASE = 70                  # 70..79: GEAR bonus per stat index, keyed pid (parallel to TB_BASE)
BO, BT, BL, BP, BSI = 80, 81, 82, 83, 84    # building: owner · trade · level · operator pid · since-block
IO, IT, IR, IE = 90, 91, 92, 93             # item: owner · gear slot · rarity · equipped pid (0 = in the bag)
IA_BASE = 94                                # 94..96: three affixes, each = stat_index * AFFIX_MUL + points
BLIST, ILIST = 63, 64                       # index lists (mirrors PLIST/OLIST/WLIST)
BCNT_SLOT, ICNT_SLOT = 4, 5                 # their counters (field 0, like OCNT_SLOT/WCNT_SLOT)
TG_RES = 700                  # per-owner resource balance: HASH(TG_RES, owner, kind)
TG_GEAR = 701                 # pet's equipped item per gear slot: HASH(TG_GEAR, pid, slot)
BUILD_FEE = 5 * 10**9         # 0.5 NADO per level, paid on build/upgrade — burned, like the mint fee
MAX_LEVEL = 5
GEAR_SLOTS = 4                # 0 tool · 1 barding · 2 charm · 3 relic — one item per slot per pet
AFFIX_MUL = 256               # affix packing: stat_index * AFFIX_MUL + points (points < AFFIX_MUL)
AFFIX_CAP = 12                # max points one affix can roll at tier 1 (scales with the finder's rarity)
ACCRUE_CAP = 20000            # blocks of production a building banks unattended (~33h at 6s) — an idle
                              # base keeps earning, but not forever, so nobody farms a year in one call
RARITY_RATE = 6               # production points a worker's rarity adds (ADDITIVE — see _accrue)
RATE_DIV = 9000               # production divisor: units = elapsed x level x (10 + trade stat) x sp / this
FODDER_BLOCKS = 200           # blocks of life one unit of fodder buys. Deliberately NOT enough to retire the
                              # NADO food sink: a level-1 farm roughly feeds the pet working it, and only a
                              # heavily upgraded base with a rare worker feeds a barn. Unlike bought food it
                              # ignores appetite, which is the actual reward for farming.
UPG_TIMBER, UPG_STONE, UPG_ORE = 40, 30, 25   # per level of the NEW level; ore only from level 4 up
DROP_ONE_IN = 6               # roughly one collect in this many turns up an item
SCRAP_ESSENCE = 3             # essence returned for scrapping an item, x its rarity
REROLL_ESSENCE = 10           # essence to re-roll an item's affixes, x its rarity — SYMMETRIC with
                              # the three materials on purpose: every trade produces at the same
                              # rate, so the sinks have to drain at the same rate or whichever
                              # resource is under-demanded piles into the hundreds of thousands. — the sink that makes
                              # essence (and therefore Shrines and scrapping junk) worth anything
REROLL_TIMBER, REROLL_STONE, REROLL_ORE = 10, 10, 10   # ...and materials, x rarity. Upgrades alone are a FINITE sink
                              # (a building consumes 560 timber over its whole life and then never again), so
                              # without a repeatable one, timber and stone pile up worthless the moment every
                              # base is maxed — the dead-end that kills a resource economy.
FUSE_MAX_TIER = 4             # fuse lifts an item at most to here. The top two tiers stay gated behind
                              # FINDING them with a rare pet, which is what keeps the best gear scarce.
FUSE_TIMBER, FUSE_STONE, FUSE_ORE, FUSE_ESSENCE = 20, 20, 20, 25   # per tier to fuse, paid in flooded junk.
                              # Essence is the one resource with TWO faucets (Shrines produce it AND scrapping
                              # yields it), so it needs a second sink or it is the only thing that runs away —
                              # simulation had a whale sitting on 279k of it after a year. Fusing consuming it
                              # closes the junk loop: scrap the unwearable, spend the essence fusing the rest. Every endgame
                              # sink pulls on ALL the materials on purpose: simulation showed that when one
                              # resource was the only thing rerolling consumed, it became the binding
                              # constraint while ore, stone and essence piled into the millions unused.
# NADO burned by the endgame loop. Homestead REMOVES a sink — farmed fodder replaces bought food — and
# simulating a year showed a mid-size player burning 0.48x what they would have without it, a whale 0.31x.
# The fix is not to weaken farming but to MOVE the sink: feeding stops costing NADO, so the gear chase
# starts. At these values the same simulated players land at 1.07x and 1.08x — the currency is no worse off,
# and a casual with one base still gets a real subsidy (0.72x) because they cannot afford to chase rolls.
REROLL_FEE = 5 * 10**8        # 0.05 NADO, burned
FUSE_FEE = 10 * 10**8         # 0.10 NADO, burned


def _trade(pid_reg, out):
    """out = the pet's trade (0..NJOBS-1), derived from its SPECIES: si % NJOBS. Deriving it means every
    pet of a species shares a trade — "you need a miner for a mine" is a fact players can learn and trade
    on — and it costs no storage and no migration for the pets that already exist. Clobbers r4/r6/r7.

    `out` must not be r4/r6/r7. The divisor deliberately lives in r6 rather than r5: an earlier version
    took it in r5 while callers passed out="r5", so `divmod r5 r5` divided the species by itself and every
    pet read as trade 0 — which silently opened every building to every animal."""
    assert out not in ("r4", "r6", "r7"), f"_trade: {out} collides with its own scratch"
    return [f"slot r4 {SI} {pid_reg}", f"sload {out} r4",
            f"movi r6 {NJOBS}", f"divmod {out} r6", f"mov {out} r7"]


def _owned_alive(pid_reg):
    """require: caller owns this pet AND it is alive. The pair guards every job/gear action. Clobbers r4-r6."""
    return ([f"slot r4 {OW} {pid_reg}", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
            + _alive_pid(pid_reg))


def _res_slot(out, owner_reg, kind_reg):
    """out = the resource-balance slot for (owner, kind). Hash-keyed like every other per-user balance in
    these contracts, read back through the res_of view. Clobbers r4."""
    return [f"movi r4 {TG_RES}", f"hash {out} <- r4 {owner_reg} {kind_reg}"]


def _res_add(owner_reg, kind_reg, amt_reg):
    """credit `amt` of resource `kind` to `owner`. Clobbers r2/r4."""
    return _res_slot("r2", owner_reg, kind_reg) + ["sload r4 r2", f"add r4 {amt_reg}", "sstore r2 r4"]


def _res_take(kind, amt_reg):
    """REQUIRE the caller holds `amt` of resource `kind`, and spend it. Reverts the whole call when short —
    so a half-paid upgrade is impossible. Clobbers r2/r4/r5/r6."""
    return (["ctx r5 caller", f"movi r6 {kind}"] + _res_slot("r2", "r5", "r6")
            + ["sload r4 r2", f"mov r5 r4", f"lt r5 {amt_reg}", "notb r5", "require r5",
               f"sub r4 {amt_reg}", "sstore r2 r4"])


# ---- production ----------------------------------------------------------------------------------
# _accrue banks everything a building earned since it was last touched, and is shared by collect(), staff()
# and upgrade() — every path that changes what a building produces must first pay out what it already
# produced at the OLD terms, or the change would silently rewrite history.
def _accrue():
    """Pay out building r0's production and reset its clock. Produces nothing (and still resets the clock)
    when the building is unstaffed. Emits NO ret — the caller continues. Clobbers r1..r7."""
    L = _sl(BSI) + ["sload r1 r4"]                                          # r1 = since
    L += ["ctx r2 cursor", "mov r3 r2", "sub r3 r1"]                        # r3 = elapsed
    # cap the banked window, then re-anchor the clock to now
    L += [f"movi r5 {ACCRUE_CAP}", "mov r6 r3", "lt r6 r5", "notb r6",      # r6 = elapsed >= CAP
          "mul r5 r6", "notb r6", "mul r6 r3", "add r5 r6", "mov r3 r5"]    # r3 = min(elapsed, CAP)
    L += _sl(BSI) + ["ctx r5 cursor", "sstore r4 r5"]
    L += _sl(BP) + ["sload r1 r4", "nez r1"]                                # r1 = staffed?
    L += ["mul r3 r1"]                                                      # unstaffed -> nothing accrues
    # rate = level * (10 + operator's trade stat) * rarity
    L += _sl(BP) + ["sload r1 r4"]                                          # r1 = operator pid
    L += _sl(BT) + ["sload r5 r4", f"movi r4 {_sc(0)}", "sstore r4 r5"]     # scratch0 = trade index
    L += _eff_stat("r1", _sc(0), "r2") + ["movi r5 10", "add r2 r5"]        # r2 = 10 + trade stat
    # rarity is ADDITIVE, not another multiplier. Multiplying level x stat x rarity compounded to a 57x
    # spread: a maxed base with a top-tier worker fed FIFTY pets forever, which permanently destroys the
    # NADO food-burn sink for that whole herd in exchange for a one-time 7.5 NADO build. Additive keeps
    # rarity worth chasing (a top pet still roughly triples a base) without letting one player opt an
    # entire stable out of the economy.
    L += [f"slot r4 {SP} r1", "sload r5 r4", "movi r6 1", "sub r5 r6",
          f"movi r6 {RARITY_RATE}", "mul r5 r6", "add r2 r5"]               # + rarity bonus
    L += _sl(BL) + ["sload r5 r4", "mul r2 r5"]                             # x level
    L += ["mul r3 r2", f"movi r5 {RATE_DIV}", "divmod r3 r5"]               # r3 = units produced
    # credit the OWNER (not the caller — collect is permissionless, the yield is never the caller's)
    L += _sl(BO) + ["sload r6 r4"] + _sl(BT) + ["sload r5 r4"]
    L += _res_add("r6", "r5", "r3")
    return L


def _roll_affixes(iid_reg, rarity_reg, salt_reg):
    """Write item `iid`'s three affixes: a stat index (0..9) and points 1..AFFIX_CAP*rarity, each rolled off
    a distinct salt. Shared by the find and the reroll so a rerolled item is drawn from exactly the same
    distribution as a found one. Clobbers r3/r4/r6."""
    L = []
    for k in range(3):
        L += [f"mov r6 {salt_reg}", f"movi r4 {5000 + k}", "add r6 r4"] + _roll32("r6", "r6")
        L += ["mov r3 r6", "movi r4 10", "divmod r3 r4", "mov r3 r7"]       # r3 = stat index 0..9
        # points scale with rarity — that is what makes a legendary pet worth working a base
        L += [f"movi r4 {AFFIX_CAP}", f"mul r4 {rarity_reg}", "divmod r6 r4", "mov r6 r7",
              "movi r4 1", "add r6 r4"]                                     # r6 = 1..AFFIX_CAP*rarity
        L += [f"movi r4 {AFFIX_MUL}", "mul r3 r4", "add r3 r6",
              f"slot r4 {IA_BASE + k} {iid_reg}", "sstore r4 r3"]
    return L


def _item_drop():
    """Roll for a find and, on a hit, mint an item owned by the building's owner. The roll is the previous
    block's hash mixed with the building id and its clock — public, replayable, and not choosable by the
    caller (the block hash is fixed before collect() can be sent). Clobbers r1..r7."""
    L = ["ctx r5 cursor", "movi r6 1", "sub r5 r6", "bhash r2 r5"]          # r2 = last block hash
    L += _sl(BSI) + ["sload r5 r4", "add r2 r5", "mov r5 r0", "add r2 r5"]
    L += _roll32("r2", "r2")
    L += ["mov r3 r2", f"movi r5 {DROP_ONE_IN}", "divmod r3 r5", "mov r3 r7", "nez r3", "notb r3"]
    L += ["jnz r3 @drop", "ret r0", "drop:"]                                # r3 == 1 -> a find
    # item id = the next counter value, appended 0-INDEXED like every other list here (offers/battles) —
    # the storage view enumerates list[0..cnt-1], so an off-by-one hides the newest item from the client.
    # Ids themselves start at 1, because 0 is "no item" everywhere else in this contract.
    L += [f"movi r4 {ICNT_SLOT}", "sload r5 r4",                            # r5 = old count = the new index
          "mov r1 r5", "movi r6 1", "add r1 r6", "sstore r4 r1"]            # r1 = iid = old + 1
    L += [f"slot r4 {ILIST} r5", "sstore r4 r1"]
    L += _sl(BO) + ["sload r5 r4", f"slot r4 {IO} r1", "sstore r4 r5"]      # owner = the base's owner
    # gear slot = roll % GEAR_SLOTS ; rarity = the OPERATOR's tier (a rare pet finds rare things)
    L += ["mov r5 r2", f"movi r6 {GEAR_SLOTS}", "divmod r5 r6", f"slot r4 {IT} r1", "sstore r4 r7"]
    L += _sl(BP) + ["sload r6 r4", f"slot r4 {SP} r6", "sload r5 r4",
                    f"slot r4 {IR} r1", "sstore r4 r5"]                     # r5 = rarity
    L += [f"slot r4 {IE} r1", "movi r6 0", "sstore r4 r6"]                  # not equipped
    L += _roll_affixes("r1", "r5", "r2")
    # RET the new item id. Without this the drop path ran off the end of the program, which the VM treats
    # as a revert — so every collect that actually FOUND something silently failed and paid nothing, while
    # the (far more common) no-drop path returned fine and looked healthy.
    return L + ["ret r1"]
# ---- methods -------------------------------------------------------------------------------------
# build(bid, trade, builderPid)[value]: raise a building of `trade`. It costs NADO (burned, like minting)
# AND a pet born to that trade to raise it — a base is something you commit to, not something you spam.
BUILD = "\n".join(
    ["movi r5 0", "lt r5 r0", "require r5",
     f"movi r5 {_2_32}", "mov r6 r0", "lt r6 r5", "require r6"]
    + _sl(BO) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]              # fresh building id
    + [f"movi r5 {NJOBS}", "mov r6 r1", "lt r6 r5", "require r6"]               # a real trade
    + ["ctx r5 value", f"movi r6 {BUILD_FEE}", "eq r5 r6", "require r5"]
    + _owned_alive("r2")
    + _trade("r2", "r5") + ["mov r6 r1", "eq r5 r6", "require r5"]              # the builder's trade matches
    + [f"movi r4 {BURN_SLOT}", "sload r5 r4", f"movi r6 {BUILD_FEE}", "add r5 r6", "sstore r4 r5"]
    + ["ctx r5 caller"] + _sl(BO) + ["sstore r4 r5"]
    + _sl(BT) + ["sstore r4 r1"]
    + _sl(BL) + ["movi r5 1", "sstore r4 r5"]
    + _sl(BP) + ["movi r5 0", "sstore r4 r5"]
    + _sl(BSI) + ["ctx r5 cursor", "sstore r4 r5"]
    + [f"movi r4 {BCNT_SLOT}", "sload r5 r4", f"slot r6 {BLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])

# upgrade(bid, builderPid)[value]: +1 level, which multiplies output. Banks the old level's production
# FIRST — changing the rate without settling what the building already earned would rewrite history.
UPGRADE_B = "\n".join(
    _sl(BO) + ["sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + _sl(BL) + ["sload r5 r4", f"movi r6 {MAX_LEVEL}", "lt r5 r6", "require r5"]
    + _owned_alive("r1")
    + _trade("r1", "r5") + _sl(BT) + ["sload r6 r4", "eq r5 r6", "require r5"]
    # price is BUILD_FEE per level of the NEW level, so each step up costs more than the last
    + _sl(BL) + ["sload r5 r4", "movi r6 1", "add r5 r6", f"movi r6 {BUILD_FEE}", "mul r5 r6",
                 "ctx r6 value", "eq r5 r6", "require r5"]
    + [f"movi r4 {BURN_SLOT}", "sload r5 r4", "ctx r6 value", "add r5 r6", "sstore r4 r5"]
    # MATERIALS, scaled by the new level. Without this, timber/stone/ore are numbers nobody ever spends and
    # every base is an island; with it a Farm needs a Sawmill and a Quarry, which is the whole base game.
    + _sl(BL) + ["sload r3 r4", "movi r5 1", "add r3 r5"]                       # r3 = the new level
    + ["mov r1 r3", f"movi r5 {UPG_TIMBER}", "mul r1 r5"] + _res_take(1, "r1")
    + ["mov r1 r3", f"movi r5 {UPG_STONE}", "mul r1 r5"] + _res_take(2, "r1")
    # ore only from level 4 up: (new_level >= 4) x UPG_ORE x new_level
    + ["mov r1 r3", "movi r5 4", "lt r1 r5", "notb r1", "mul r1 r3",
       f"movi r5 {UPG_ORE}", "mul r1 r5"] + _res_take(3, "r1")
    + _accrue()
    + _sl(BL) + ["sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5", "ret r5"])

# staff(bid, pid): put a pet to work (pid 0 clocks the current one off). Banks first, for the same reason.
STAFF = "\n".join(
    _sl(BO) + ["sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    # _accrue needs r1 for its own bookkeeping, so the incoming pet is parked in scratch across the payout
    # and read back. (Without this, staff() re-assigned whatever the PREVIOUS operator was.)
    + [f"movi r4 {_sc(1)}", "sstore r4 r1"]
    + _accrue()
    + [f"movi r4 {_sc(1)}", "sload r1 r4"]
    + ["mov r5 r1", "nez r5", "notb r5", "jnz r5 @clear"]                       # pid 0 -> just clear it
    + _owned_alive("r1")
    + _trade("r1", "r5") + _sl(BT) + ["sload r6 r4", "eq r5 r6", "require r5"]  # trade must match
    + ["clear:"] + _sl(BP) + ["sstore r4 r1", "ret r1"])

# collect(bid): permissionless — anyone may settle a base, the yield always goes to its OWNER. That keeps
# a shared "collect all" possible without handing anyone else's harvest to the caller.
COLLECT = "\n".join(_accrue() + _item_drop())

# provision(pid, units): feed from the barn's own stores instead of from the wallet. This is the point of
# farming — fodder a farm produced costs nothing to use, so a working base feeds itself.
PROVISION = "\n".join(
    ["movi r5 0", "lt r5 r1", "require r5"]
    + [f"slot r4 {OW} r0", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + [f"slot r4 {GN} r0", "sload r5 r4", "nez r5", "require r5"]               # hatched pets only
    + ["ctx r5 caller", "movi r6 0"] + _res_slot("r2", "r5", "r6")              # kind 0 = fodder
    + ["sload r5 r2", "mov r6 r1", "lt r5 r6", "notb r5", "require r5"]         # enough in store
    + ["sload r5 r2", "sub r5 r1", "sstore r2 r5"]
    + [f"movi r5 {FODDER_BLOCKS}", "mul r1 r5"]                                 # units -> belly blocks
    + [f"slot r4 {FU} r0", "sload r5 r4", "add r5 r1",
       "ctx r6 cursor", f"movi r2 {BELLY_CAP}", "add r6 r2",                    # cap at cursor + BELLY_CAP
       "mov r2 r5", "lt r2 r6", "notb r2",                                      # r2 = over the cap
       "mul r6 r2", "notb r2", "mul r2 r5", "add r6 r2",
       "sstore r4 r6", "ret r6"])

# equip(itemId, pid): the Diablo half. An item's affixes are POINTS ON REAL STATS, so equipping it adds
# them to the pet's gear board and _eff_stat picks them up everywhere — the arena, the card, the previews.
# One item per gear slot per pet; the item remembers its own rolls, so unequip is exact.
EQUIP = "\n".join(
    [f"slot r4 {IO} r0", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + [f"slot r4 {IE} r0", "sload r5 r4", "nez r5", "notb r5", "require r5"]    # not already worn
    + _owned_alive("r1")
    + [f"slot r4 {IT} r0", "sload r2 r4"]                                       # r2 = gear slot
    + [f"movi r4 {TG_GEAR}", "hash r3 <- r4 r1 r2", "sload r5 r3", "nez r5", "notb r5", "require r5"]
    + ["sstore r3 r0"]                                                          # slot -> this item
    + [f"slot r4 {IE} r0", "sstore r4 r1"]
    + [op for k in range(3) for op in
       ([f"slot r4 {IA_BASE + k} r0", "sload r5 r4", f"movi r6 {AFFIX_MUL}", "divmod r5 r6",
         "mov r6 r7",                                                           # r5 = stat idx, r6 = points
         f"movi r4 {GB_BASE}", "add r4 r5", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r1",
         "sload r5 r4", "add r5 r6", "sstore r4 r5"])]
    + ["ret r0"])

# unequip(itemId): exact reverse — the item still holds the rolls that were added, so nothing drifts.
UNEQUIP = "\n".join(
    [f"slot r4 {IO} r0", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + [f"slot r4 {IE} r0", "sload r1 r4", "nez r1", "require r1"]
    + [f"slot r4 {IE} r0", "sload r1 r4"]                                       # r1 = the wearer
    + [f"slot r4 {IT} r0", "sload r2 r4",
       f"movi r4 {TG_GEAR}", "hash r3 <- r4 r1 r2", "movi r5 0", "sstore r3 r5"]
    + [f"slot r4 {IE} r0", "movi r5 0", "sstore r4 r5"]
    + [op for k in range(3) for op in
       ([f"slot r4 {IA_BASE + k} r0", "sload r5 r4", f"movi r6 {AFFIX_MUL}", "divmod r5 r6",
         "mov r6 r7",
         f"movi r4 {GB_BASE}", "add r4 r5", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r1",
         "sload r5 r4", "sub r5 r6", "sstore r4 r5"])]
    + ["ret r0"])

# scrap(itemId): inventory management with a floor — a bag full of junk converts to essence rather than
# needing a delete button. Must be off the pet first, so scrapping can never strip a pet mid-battle.
SCRAP = "\n".join(
    [f"slot r4 {IO} r0", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + [f"slot r4 {IE} r0", "sload r5 r4", "nez r5", "notb r5", "require r5"]
    + [f"slot r4 {IR} r0", "sload r1 r4", f"movi r5 {SCRAP_ESSENCE}", "mul r1 r5"]
    + ["ctx r5 caller", "movi r6 4"] + _res_add("r5", "r6", "r1")               # kind 4 = essence
    + [f"slot r4 {IO} r0", "movi r5 0", "sstore r4 r5", "ret r1"])              # owner 0 = gone

# reroll(itemId): spend essence to re-roll an item's affixes. The Diablo half needs a way to CHASE a roll,
# or a bag of near-misses is just clutter; this is also the only sink essence has, which is what gives
# Shrines and scrapping a point. The item keeps its slot and rarity — you are re-rolling the affixes, not
# gambling for a better item — and it must be off the pet, so the gear board can never drift.
REROLL = "\n".join(
    [f"slot r4 {IO} r0", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + [f"slot r4 {IE} r0", "sload r5 r4", "nez r5", "notb r5", "require r5"]
    + [f"slot r4 {IR} r0", "sload r5 r4"]                                       # r5 = rarity (kept)
    + ["mov r1 r5", f"movi r6 {REROLL_ESSENCE}", "mul r1 r6"] + _res_take(4, "r1")
    + [f"slot r4 {IR} r0", "sload r5 r4", "mov r1 r5", f"movi r6 {REROLL_TIMBER}", "mul r1 r6"] + _res_take(1, "r1")
    + [f"slot r4 {IR} r0", "sload r5 r4", "mov r1 r5", f"movi r6 {REROLL_STONE}", "mul r1 r6"] + _res_take(2, "r1")
    + [f"slot r4 {IR} r0", "sload r5 r4", "mov r1 r5", f"movi r6 {REROLL_ORE}", "mul r1 r6"] + _res_take(3, "r1")
    + ["ctx r5 value", f"movi r6 {REROLL_FEE}", "eq r5 r6", "require r5"]
    + [f"movi r4 {BURN_SLOT}", "sload r5 r4", f"movi r6 {REROLL_FEE}", "add r5 r6", "sstore r4 r5"]
    + [f"slot r4 {IR} r0", "sload r5 r4"]                                       # reload: _res_take clobbers r5
    # fresh entropy: last block's hash, mixed with the item and the block it is being rerolled in
    + ["ctx r2 cursor", "movi r6 1", "sub r2 r6", "bhash r2 r2",
       "mov r6 r0", "add r2 r6", "ctx r6 cursor", "add r2 r6"]
    + _roll_affixes("r0", "r5", "r2")
    + ["ret r0"])

# fuse(targetId, foodId): destroy one item to lift another's rarity by a tier. This is what the flood of
# common gear is FOR. An item economy with unbounded supply and bounded demand (four slots per pet) ends
# with everything worthless and the chase over — the Diablo 3 failure. Fusing gives junk a permanent use,
# gives ore a permanent sink, and keeps a goal after a pet is fully kitted. It stops at FUSE_MAX_TIER, so
# the best gear still has to be FOUND by a rare pet: the scarcity anchor is never craftable.
FUSE = "\n".join(
    ["mov r5 r0", "eq r5 r1", "notb r5", "require r5"]                          # not the same item
    + [f"slot r4 {IO} r0", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + [f"slot r4 {IO} r1", "sload r5 r4", "ctx r6 caller", "eq r5 r6", "require r5"]
    + [f"slot r4 {IE} r0", "sload r5 r4", "nez r5", "notb r5", "require r5"]    # neither is being worn
    + [f"slot r4 {IE} r1", "sload r5 r4", "nez r5", "notb r5", "require r5"]
    + [f"slot r4 {IT} r0", "sload r5 r4", f"slot r4 {IT} r1", "sload r6 r4",
       "eq r5 r6", "require r5"]                                                # same gear slot
    + [f"slot r4 {IR} r0", "sload r3 r4", f"movi r5 {FUSE_MAX_TIER}",
       "mov r6 r3", "lt r6 r5", "require r6"]                                   # r3 = target rarity < cap
    + [f"slot r4 {IR} r1", "sload r5 r4", "mov r6 r3", "lt r5 r6", "notb r5", "require r5"]  # food >= target
    + ["ctx r5 value", f"movi r6 {FUSE_FEE}", "eq r5 r6", "require r5"]
    + [f"movi r4 {BURN_SLOT}", "sload r5 r4", f"movi r6 {FUSE_FEE}", "add r5 r6", "sstore r4 r5"]
    # Price each material into r3, re-deriving the tier from storage every time. r0/r1 hold the two items
    # and _res_take clobbers r2/r4/r5/r6 — including r2, so caching the tier there silently priced the
    # second and third materials off garbage (the whole fuse then failed).
    + [op for kind, per in ((1, FUSE_TIMBER), (2, FUSE_STONE), (3, FUSE_ORE)) for op in
       ([f"slot r4 {IR} r0", "sload r3 r4", "movi r5 1", "add r3 r5",
         f"movi r5 {per}", "mul r3 r5"] + _res_take(kind, "r3"))]
    + [f"slot r4 {IO} r1", "movi r5 0", "sstore r4 r5"]                         # the food item is destroyed
    + [f"slot r4 {IR} r0", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5", "ret r5"])

# ---- views ---------------------------------------------------------------------------------------
RES_OF = "\n".join(_res_slot("r3", "r0", "r1") + ["sload r3 r3", "ret r3"])
GEAR_OF = "\n".join([f"movi r4 {TG_GEAR}", "hash r3 <- r4 r0 r1", "sload r3 r3", "ret r3"])
TRADE_OF = "\n".join(_trade("r0", "r3") + ["ret r3"])
# ==== end HOMESTEAD ================================================================================

SRC = {"mint": MINT, "rebirth": REBIRTH, "feed": FEED, "transfer": TRANSFER, "name": NAME,
       "list": LIST_, "unlist": UNLIST, "buy": BUY, "offer": OFFER, "accept_offer": ACCEPT_OFFER,
       "cancel_offer": CANCEL_OFFER, "train": TRAIN, "challenge": CHALLENGE, "accept": ACCEPT,
       "cancel_battle": CANCEL_BATTLE, "refund_battle": REFUND_BATTLE, "release": RELEASE,
       # homestead
       "build": BUILD, "upgrade": UPGRADE_B, "staff": STAFF, "collect": COLLECT, "provision": PROVISION,
       "equip": EQUIP, "unequip": UNEQUIP, "scrap": SCRAP, "reroll": REROLL, "fuse": FUSE,
       "res_of": RES_OF, "gear_of": GEAR_OF, "trade_of": TRADE_OF}

ABI = {
    "mint": {"args": ["petId"], "value": True},
    "hatch": {"args": ["petId"]},
    "rebirth": {"args": ["petId"]},
    "feed": {"args": ["petId"], "value": True},
    "transfer": {"args": ["petId", "to"]},
    "name": {"args": ["petId", "name"]},
    "list": {"args": ["petId", "price"]},
    "unlist": {"args": ["petId"]},
    "buy": {"args": ["petId"], "value": True},
    "offer": {"args": ["offerId", "petId"], "value": True},
    "accept_offer": {"args": ["offerId"]},
    "cancel_offer": {"args": ["offerId"]},
    "train": {"args": ["petId", "statIdx"], "value": True},
    "train_resolve": {"args": ["petId"]},
    "challenge": {"args": ["battleId", "myPet", "theirPet"], "value": True},
    "accept": {"args": ["battleId"], "value": True},
    "resolve_battle": {"args": ["battleId"]},
    "cancel_battle": {"args": ["battleId"]},
    "refund_battle": {"args": ["battleId"]},
    "combine": {"args": ["keepPet", "consumePet"]},
    "release": {"args": ["petId"]},
    # ---- homestead ----
    "build": {"args": ["buildingId", "trade", "builderPetId"], "value": True},
    "upgrade": {"args": ["buildingId", "builderPetId"], "value": True},
    "staff": {"args": ["buildingId", "petId"]},
    "collect": {"args": ["buildingId"]},
    "provision": {"args": ["petId", "units"]},
    "equip": {"args": ["itemId", "petId"]},
    "unequip": {"args": ["itemId"]},
    "scrap": {"args": ["itemId"]},
    "reroll": {"args": ["itemId"], "value": True},
    "fuse": {"args": ["targetItemId", "foodItemId"], "value": True},
    "res_of": {"args": ["addr", "kind"]},
    "gear_of": {"args": ["petId", "slot"]},
    "trade_of": {"args": ["petId"]},
    "_view": {
        "maps": {"ow": {"field": OW, "index": "pets"}, "bh": {"field": BH, "index": "pets"},
                 "gl": {"field": GL, "index": "pets"}, "gh": {"field": GH, "index": "pets"},
                 "sp": {"field": SP, "index": "pets"}, "si": {"field": SI, "index": "pets"},
                 "ap": {"field": AP, "index": "pets"}, "pw": {"field": PW, "index": "pets"},
                 "fu": {"field": FU, "index": "pets"}, "tf": {"field": TF, "index": "pets"},
                 "ex": {"field": EX, "index": "pets"}, "nm": {"field": NM, "index": "pets"},
                 "th": {"field": TH, "index": "pets"}, "ti": {"field": TI, "index": "pets"},
                 "tr": {"field": TR, "index": "pets"}, "mp": {"field": MP, "index": "pets"},
                 "wins": {"field": WINS, "index": "pets"}, "loss": {"field": LOSS, "index": "pets"},
                 "ob": {"field": OB, "index": "offers"}, "op": {"field": OP_, "index": "offers"},
                 "ov": {"field": OV, "index": "offers"}, "os": {"field": OS, "index": "offers"},
                 "bo": {"field": BO, "index": "bases"}, "bt": {"field": BT, "index": "bases"},
                 "bl": {"field": BL, "index": "bases"}, "bp": {"field": BP, "index": "bases"},
                 "bsi": {"field": BSI, "index": "bases"},
                 "io": {"field": IO, "index": "items"}, "it": {"field": IT, "index": "items"},
                 "ir": {"field": IR, "index": "items"}, "ie": {"field": IE, "index": "items"},
                 "wa": {"field": WA, "index": "battles"}, "wb": {"field": WB, "index": "battles"},
                 "ws": {"field": WS, "index": "battles"}, "wp": {"field": WP, "index": "battles"},
                 "wh": {"field": WH, "index": "battles"}, "wn": {"field": WN, "index": "battles"},
                 "ww": {"field": WW, "index": "battles"}, "wd": {"field": WD, "index": "battles"}},
        "indexes": {"pets": {"cnt": 0, "list": PLIST}, "offers": {"cnt": OCNT_SLOT, "list": OLIST},
                    "bases": {"cnt": BCNT_SLOT, "list": BLIST}, "items": {"cnt": ICNT_SLOT, "list": ILIST},
                    "battles": {"cnt": WCNT_SLOT, "list": WLIST}},
        "addr": ["ow", "nm", "ob", "bo", "io"],
        "board": {"name": "tb", "base": TB_BASE, "cells": 10, "stride": 10, "index": "pets"},
        # gear points per stat (parallel to tb) and each item's three rolled affixes
        "board2": {"name": "gb", "base": GB_BASE, "cells": 10, "stride": 10, "index": "pets"},
        "board3": {"name": "ia", "base": IA_BASE, "cells": 3, "stride": 3, "index": "items"},
    },
}


def build():
    src = dict(SRC)
    src["hatch"] = "\n".join(_hatch())
    src["train_resolve"] = "\n".join(_train_resolve())
    src["resolve_battle"] = "\n".join(_resolve_battle())
    src["combine"] = "\n".join(_combine())
    return zkvmasm.assemble_contract(src)

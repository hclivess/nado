"""
Battleship — zkVM port (doc/zk-execution-proofs.md). Trustless hidden-board naval combat: your fleet NEVER
leaves your browser. You commit a MERKLE-SUM root over your 128-cell board (10x10 grid = cells 0..99, cells
100..127 always water so the tree is a full 2^7); every shot is answered by revealing just that ONE cell +
its 7-node path, which the contract checks against your root — so nobody can lie about a hit/miss and
nobody can hide ships (the same proof binds the subtree ship-count, and the full count must equal 17).
17 proven hits sinks the fleet and wins the pot. The winner then proves their commitment WAS a legal fleet
(reveal-at-claim): claim() rebuilds the whole 128-leaf tree in-VM from the 5 ship placements + salt seed and
requires it to reproduce the committed root with exactly 17 ship cells — a scattered/overlapping cheat can
never claim (and the loser then takes the pot via forfeit()).

Field-native crypto (this port): hashes are alghash field elements, domain-separated by a leading tag —
    salt(seed, c)          = H(1, seed, c)
    leaf(c, isShip, salt)  = H(2, salt, 2c + isShip)
    node(L, R, sum)        = H(3, L, R, sum)        (ordered absorption -> position-binding)
Leaves sit at bit-reversed positions (pos = bitrev7(cell)) so a proof's sibling SUMS cover scattered cells,
leaking nothing about ship shapes. The browser mirrors these three lines with the same alghash (alghash.js).

This is the ARG-bus showcase: answer(g, isShip, salt, sib0,ss0..sib6,ss6) takes 17 args and
claim(g, a0,o0..a4,o4, seed) takes 12 — both impossible under the old 8-register ABI.

Game fields (key = game id): 1 p1 2 p2 3 r1 4 r2 5 st(stake) 6 pt(pot) 7 nn 8 sd(settled) 9 dl(move deadline)
  10 pc(pending cell) 11 pex 12 pf(who fired) 13 tf(whose turn to fire) 14 h1 15 h2 (hit counts) 16 wr
  17 dc(decided) 18 cd(claim deadline).
Boards (field = BASE+cell, key = g): fired-by-p1 100+, fired-by-p2 200+, p1's shot results 300+ (1 miss /
  2 hit), p2's 400+. Index: slot 0 count, field 500 list. Claim scratch: O occupancy 600+cell, tree stack
  SH 730+lvl / SS 740+lvl (cleaned on success; a failed claim reverts to a no-op).
Methods: open(g,root)[stake] · join(g,root)[stake] · fire(g,cell) · answer(g,…proof) · resign(g) ·
  timeout(g) · claim(g,…fleet,seed) · forfeit(g) · cancel(g).
"""
from execnode import zkvmasm
from execnode.games import _lib
from execnode.stark import alghash, field as F

P1, P2, R1, R2, ST, PT, NN, SD, DL = 1, 2, 3, 4, 5, 6, 7, 8, 9
PC, PEX, PF, TF, H1, H2, WR, DC, CD = 10, 11, 12, 13, 14, 15, 16, 17, 18
F1_BASE, F2_BASE, RS1_BASE, RS2_BASE = 100, 200, 300, 400
GLIST = 500
O_BASE, SH_BASE, SS_BASE, SC = 600, 730, 740, 900
TAG_SALT, TAG_LEAF, TAG_NODE = 1, 2, 3
LEVELS, SHIPS, CELLS128 = 7, 17, 128
FLEET_LENS = [5, 4, 3, 3, 2]
WINDOW = 600
_2_32 = 1 << 32
# --- free Daily Salvo board (provable practice, faucet-rewarded — doc/provable-practice.md) ---
# fields chosen well clear of the PvP set (bases <=900, _sc at field 900): bare count slots 1000/1001,
# entry fields 1010+, packed shots 1030.., day anchor 1050+.
DCNT_SLOT, ECNT_SLOT = 1000, 1001
E_DAY, E_ADDR, E_SCORE, E_N = 1010, 1011, 1012, 1013
E_TS = 1014                               # UTC-seconds post-time (board shows day + time)
ELIST, EW_BASE = 1020, 1030
A_H, A_V, DLIST = 1050, 1051, 1052
DAILY_WORDS = 6                                        # ceil(40 shots / 7 per word)


# ---- python reference (what the browser + tests mirror) --------------------------------------------
def salt_at(seed, c):
    return alghash.hashn([TAG_SALT, seed % F.P, c])


def leaf_at(c, is_ship, salt):
    return alghash.hashn([TAG_LEAF, salt % F.P, 2 * c + is_ship])


def node_at(l, r, s):
    return alghash.hashn([TAG_NODE, l % F.P, r % F.P, s])


def bitrev7(x):
    return int(format(x, "07b")[::-1], 2)


def build_root(board, salts):
    """board[128] 0/1 -> (root, total). Leaf for CELL c sits at tree position bitrev7(c)."""
    lvl = [None] * CELLS128
    for c in range(CELLS128):
        lvl[bitrev7(c)] = (leaf_at(c, board[c], salts[c]), board[c])
    while len(lvl) > 1:
        lvl = [(node_at(lvl[i][0], lvl[i + 1][0], lvl[i][1] + lvl[i + 1][1]), lvl[i][1] + lvl[i + 1][1])
               for i in range(0, len(lvl), 2)]
    return lvl[0]


def make_proof(board, salts, cell):
    """-> (isShip, salt, [sib0, ss0, .., sib6, ss6]) — the flat arg tail answer() takes."""
    lvl = [None] * CELLS128
    for c in range(CELLS128):
        lvl[bitrev7(c)] = (leaf_at(c, board[c], salts[c]), board[c])
    pos, flat = bitrev7(cell), []
    while len(lvl) > 1:
        sib = lvl[pos ^ 1]
        flat += [sib[0], sib[1]]
        lvl = [(node_at(lvl[j][0], lvl[j + 1][0], lvl[j][1] + lvl[j + 1][1]), lvl[j][1] + lvl[j + 1][1])
               for j in range(0, len(lvl), 2)]
        pos //= 2
    return board[cell], salts[cell], flat


def salts_from_seed(seed):
    return [salt_at(seed, c) for c in range(CELLS128)]


def ship_cells(anchor, orient, length):
    step = 1 + orient * 9
    return [anchor + k * step for k in range(length)]


def board_from_ships(ships):
    b = [0] * CELLS128
    for (a, o), ln in zip(ships, FLEET_LENS):
        for c in ship_cells(a, o, ln):
            b[c] = 1
    return b


# ---- asm helpers ------------------------------------------------------------------------------------
def _sl(field):
    return [f"slot r4 {field} r0"]


def _sc(i):
    return (SC << 32) | i


def _myslot(out):
    """out = 1 if caller==p1, 2 if caller==p2 (requires caller is a player). Clobbers r4/r5/r6."""
    return (["ctx r5 caller"] + _sl(P1) + ["sload r6 r4", "eq r6 r5"]           # r6 = (caller==p1)
            + _sl(P2) + ["sload r4 r4", "eq r4 r5",                             # r4 = (caller==p2)
                         f"mov {out} r6", "movi r5 2", "mul r5 r4", f"add {out} r5",
                         "mov r5 r6", "add r5 r4", "require r5"])               # a player at all


OPEN = "\n".join(
    ["ctx r3 value", "movi r2 0", "lt r2 r3", "require r2",
     "movi r2 0", "lt r2 r0", "require r2",
     f"movi r2 {_2_32}", "mov r5 r0", "lt r5 r2", "require r5"]
    + _sl(NN) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _sl(ST) + ["sstore r4 r3"] + _sl(PT) + ["sstore r4 r3"]
    + ["ctx r5 caller"] + _sl(P1) + ["sstore r4 r5"]
    + _sl(R1) + ["sstore r4 r1"]
    + _sl(NN) + ["movi r5 1", "sstore r4 r5"]
    + ["movi r4 0", "sload r5 r4", f"slot r6 {GLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])

JOIN = "\n".join(
    _sl(NN) + ["sload r5 r4", "movi r6 1", "eq r5 r6", "require r5"]
    + ["ctx r3 value"] + _sl(ST) + ["sload r5 r4", "eq r5 r3", "require r5"]
    + ["ctx r5 caller"] + _sl(P1) + ["sload r6 r4", "eq r6 r5", "notb r6", "require r6"]
    + _sl(PT) + ["sload r5 r4", "add r5 r3", "sstore r4 r5"]
    + ["ctx r5 caller"] + _sl(P2) + ["sstore r4 r5"]
    + _sl(R2) + ["sstore r4 r1"]
    + _sl(NN) + ["movi r5 2", "sstore r4 r5"]
    + _sl(TF) + ["movi r5 1", "sstore r4 r5"]
    + _sl(DL) + ["ctx r5 cursor", f"movi r6 {WINDOW}", "add r5 r6", "sstore r4 r5", "ret r0"])

FIRE = "\n".join(
    _sl(NN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
    + _sl(DC) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _sl(PEX) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _myslot("r2")                                                              # r2 = my slot
    + _sl(TF) + ["sload r5 r4", "eq r5 r2", "require r5"]
    + ["mov r5 r1", "movi r6 100", "lt r5 r6", "require r5"]                     # cell < 100
    # fired-flag slot = (100*slot + cell)*2^32 + g — must be 0, then set 1
    + ["movi r4 100", "mul r4 r2", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
       "sload r5 r4", "nez r5", "notb r5", "require r5", "movi r5 1", "sstore r4 r5"]
    + _sl(PC) + ["sstore r4 r1"]
    + _sl(PEX) + ["movi r5 1", "sstore r4 r5"]
    + _sl(PF) + ["sstore r4 r2"]
    + _sl(DL) + ["ctx r5 cursor", f"movi r6 {WINDOW}", "add r5 r6", "sstore r4 r5", "ret r0"])


def _answer():
    """answer(g, isShip, salt, sib0,ss0..sib6,ss6): prove the pending cell against MY committed root, credit
    the shooter, settle at 17 hits, hand the fire turn to me. isShip/salt preload r1/r2; sibs via ARG."""
    L = (_sl(NN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
         + _sl(DC) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
         + _sl(PEX) + ["sload r5 r4", "require r5"])
    L += _myslot("r3") + [f"movi r4 {_sc(0)}", "sstore r4 r3"]                   # SC0 = my slot
    L += _sl(PF) + ["sload r5 r4", "add r5 r3", "movi r6 3", "eq r5 r6", "require r5"]   # I answer THEIR shot
    # isShip must be a bit
    L += ["mov r5 r1", "movi r6 2", "lt r5 r6", "require r5"]
    # h = leaf(pc, isShip, salt) ; s = isShip ; pc -> SC1
    L += _sl(PC) + ["sload r3 r4", f"movi r4 {_sc(1)}", "sstore r4 r3"]
    L += ["mov r5 r3", "movi r6 2", "mul r5 r6", "add r5 r1",                    # 2*pc + isShip
          f"movi r4 {TAG_LEAF}", "hash r2 <- r4 r2 r5",                          # r2 = leaf (salt was r2)
          "mov r3 r1"]                                                           # r3 = running sum
    # climb 7 levels (unrolled): d = (pc >> (6-L)) & 1 ; a,b ordered by d ; h = H(TAG_NODE, a, b, s)
    for lv in range(LEVELS):
        sib_i, ss_i = 3 + 2 * lv, 4 + 2 * lv
        L += [f"movi r5 {ss_i}", "arg r6 r5", "add r3 r6"]                       # s += sibSum
        L += [f"movi r4 {_sc(1)}", "sload r5 r4",                                # pc
              f"movi r6 {1 << (6 - lv)}", "divmod r5 r6", "movi r6 2", "divmod r5 r6"]   # r7 = direction bit
        L += ["mov r6 r7"]                                                       # r6 = d
        L += [f"movi r5 {sib_i}", "arg r5 r5"]                                   # r5 = sibHash
        # a = h*(1-d) + sib*d -> SC2 ; b = h*d + sib*(1-d) -> r5
        L += ["mov r4 r6", "notb r4", "mul r4 r2",                               # h*(1-d)
              "mov r1 r6", "mul r1 r5", "add r4 r1",                             # + sib*d
              f"movi r1 {_sc(2)}", "sstore r1 r4"]
        L += ["mul r2 r6", "mov r4 r6", "notb r4", "mul r5 r4", "add r5 r2"]     # b = h*d + sib*(1-d)
        L += [f"movi r4 {_sc(2)}", "sload r6 r4",                                # a
              f"movi r4 {TAG_NODE}", "hash r2 <- r4 r6 r5 r3"]                   # h = H(tag, a, b, s)
    # h == MY committed root (r1 if slot 1 else r2)
    L += [f"movi r4 {_sc(0)}", "sload r6 r4", "movi r5 1", "eq r6 r5"]           # e1 = (slot==1)
    L += _sl(R1) + ["sload r5 r4", "mul r5 r6"]
    L += ["mov r1 r6", "notb r1"] + _sl(R2) + ["sload r4 r4", "mul r4 r1", "add r5 r4",
          "eq r5 r2", "require r5"]
    L += [f"movi r5 {SHIPS}", "eq r5 r3", "require r5"]                          # total ships == 17
    # credit the firer's hits; record the result; decide at 17
    L += ["movi r5 1", "arg r1 r5"]                                              # isShip again (r1 was clobbered)
    L += _sl(PF) + ["sload r3 r4"]                                               # r3 = firer slot
    for slot, hf in ((1, H1), (2, H2)):
        L += ["mov r5 r3", f"movi r6 {slot}", "eq r5 r6", "mul r5 r1"]           # hit if firer==slot
        L += _sl(hf) + ["sload r6 r4", "add r6 r5", "sstore r4 r6"]
    # res[firer][pc] = isShip+1  (field = 200 + 100*pf + pc)
    L += ["movi r4 200", "movi r5 100", "mul r5 r3", "add r4 r5"]
    L += [f"movi r5 {_sc(1)}", "sload r5 r5", "add r4 r5", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
          "mov r5 r1", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    # wr / dc
    L += _sl(H1) + ["sload r5 r4", f"movi r6 {SHIPS}", "eq r5 r6"]               # w1
    L += _sl(H2) + ["sload r2 r4", f"movi r6 {SHIPS}", "eq r2 r6"]               # w2
    L += ["mov r6 r2", "movi r4 2", "mul r6 r4", "add r6 r5"]                    # wr = w1 + 2*w2
    L += _sl(WR) + ["sstore r4 r6"]
    L += ["add r5 r2"] + _sl(DC) + ["sstore r4 r5"]                              # dc = w1+w2 (0/1)
    L += _sl(CD) + ["ctx r5 cursor", f"movi r6 {WINDOW}", "add r5 r6", "sstore r4 r5"]
    L += _sl(PEX) + ["movi r5 0", "sstore r4 r5"]
    L += [f"movi r5 {_sc(0)}", "sload r5 r5"] + _sl(TF) + ["sstore r4 r5"]       # my turn to fire now
    L += _sl(DL) + ["ctx r5 cursor", f"movi r6 {WINDOW}", "add r5 r6", "sstore r4 r5"]
    for i in (0, 1, 2):                                                          # scrub scratch (0 = delete)
        L += [f"movi r4 {_sc(i)}", "movi r5 0", "sstore r4 r5"]
    L += ["ret r0"]
    return L


RESIGN = "\n".join(
    _sl(NN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
    + _sl(DC) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _myslot("r2")
    + ["movi r5 3", "sub r5 r2"]                                                 # opponent wins
    + _sl(WR) + ["sstore r4 r5"]
    + _sl(DC) + ["movi r5 1", "sstore r4 r5"]
    + _sl(CD) + ["ctx r5 cursor", f"movi r6 {WINDOW}", "add r5 r6", "sstore r4 r5", "ret r0"])

# waiter = pex ? pf : 3-tf — whoever is being stalled on may claim the win past the deadline
TIMEOUT = "\n".join(
    _sl(NN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
    + _sl(DC) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _sl(DL) + ["sload r5 r4", "ctx r6 cursor", "lt r5 r6", "require r5"]       # cursor > dl
    + _myslot("r2")
    + _sl(PEX) + ["sload r3 r4"]                                                 # pex
    + _sl(PF) + ["sload r5 r4", "mul r5 r3"]                                     # pex*pf
    + ["mov r6 r3", "notb r6"] + _sl(TF) + ["sload r4 r4", "movi r1 3", "sub r1 r4", "mul r1 r6",
       "add r5 r1"]                                                              # + (1-pex)*(3-tf)
    + ["eq r5 r2", "require r5"]                                                 # caller IS the waiter
    + _sl(WR) + ["sstore r4 r2"]
    + _sl(DC) + ["movi r5 1", "sstore r4 r5"]
    + _sl(CD) + ["ctx r5 cursor", f"movi r6 {WINDOW}", "add r5 r6", "sstore r4 r5", "ret r0"])


def _claim():
    """claim(g, a0,o0..a4,o4, seed): the winner reveals the 5 placements + salt seed; the contract rebuilds
    the whole 128-leaf merkle-sum tree (streaming fold, in-VM loop) and requires root==commitment & sum==17.
    a0/o0 preload r1/r2; the rest via ARG. Scratch: SC3 pos · SC4 t · SC5 level · SC6 h · SC7 s · SC8 seed."""
    L = (_sl(NN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
         + _sl(DC) + ["sload r5 r4", "require r5"]
         + _sl(SD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"])
    # caller is the winner
    L += _myslot("r2") + _sl(WR) + ["sload r5 r4", "eq r5 r2", "require r5",
                                    f"movi r4 {_sc(0)}", "sstore r4 r2"]         # SC0 = winner slot
    # per-ship shape checks + occupancy writes (unrolled: 5 ships, 17 cells)
    for i, ln in enumerate(FLEET_LENS):
        ai, oi = 1 + 2 * i, 2 + 2 * i
        L += [f"movi r5 {ai}", "arg r1 r5", f"movi r5 {oi}", "arg r2 r5"]        # r1=a r2=o
        L += ["mov r5 r1", "movi r6 100", "lt r5 r6", "require r5"]              # a < 100
        L += ["mov r5 r2", "movi r6 2", "lt r5 r6", "require r5"]                # o in {0,1}
        # last = a + (ln-1)*(1+9o) ; require last < 100
        L += [f"movi r5 {9 * (ln - 1)}", "mul r5 r2", f"movi r6 {ln - 1}", "add r5 r6", "add r5 r1",
              "mov r6 r5", "movi r4 100", "lt r6 r4", "require r6"]
        # horizontal ships stay in one row: o==1 OR a//10 == last//10
        L += ["movi r4 10", "divmod r5 r4",                                      # r5 = last//10
              "mov r6 r1", "movi r4 10", "divmod r6 r4",                         # r6 = a//10
              "eq r5 r6", "add r5 r2", "nez r5", "require r5"]
        for k in range(ln):                                                      # O[a + k*(1+9o)] = 1
            L += ["movi r5 9", "mul r5 r2", "movi r6 1", "add r5 r6", f"movi r6 {k}", "mul r5 r6",
                  "add r5 r1",                                                   # cell
                  f"movi r4 {O_BASE}", "add r4 r5", f"movi r6 {_2_32}", "mul r4 r6", "add r4 r0",
                  "movi r6 1", "sstore r4 r6"]
    # seed -> SC8 ; pos = 0
    L += ["movi r5 11", "arg r5 r5", f"movi r4 {_sc(8)}", "sstore r4 r5",
          f"movi r4 {_sc(3)}", "movi r5 0", "sstore r4 r5"]
    # ---- the streaming tree fold: for pos in 0..127 push leaf(bitrev7(pos)), merging trailing levels ----
    L += ["tree_loop:",
          f"movi r4 {_sc(3)}", "sload r1 r4",                                    # r1 = pos
          "movi r5 128", "mov r6 r1", "lt r6 r5", "jnz r6 @tree_body", "jmp @tree_done",
          "tree_body:"]
    # cell = bitrev7(pos): extract 7 bits (LSB-first), reassemble reversed
    L += ["mov r2 r1", "movi r3 0"]                                              # r2 = shifting pos, r3 = cell
    for b in range(7):
        L += ["movi r5 2", "divmod r2 r5",                                       # bit -> r7
              f"movi r5 {1 << (6 - b)}", "mul r5 r7", "add r3 r5"]
    # o = O[cell] (absent = water) ; salt = H(TAG_SALT, seed, cell) ; leaf = H(TAG_LEAF, salt, 2c+o)
    L += [f"movi r4 {O_BASE}", "add r4 r3", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0", "sload r2 r4"]
    L += [f"movi r4 {_sc(8)}", "sload r5 r4", f"movi r4 {TAG_SALT}", "hash r6 <- r4 r5 r3"]
    L += ["mov r5 r3", "movi r4 2", "mul r5 r4", "add r5 r2",
          f"movi r4 {TAG_LEAF}", "hash r6 <- r4 r6 r5"]                          # r6 = h, r2 = s
    # merge while the trailing bit of t (= pos, consumed) is 1: h = H(TAG_NODE, SH[lvl], h, SS[lvl]+s)
    L += [f"movi r4 {_sc(4)}", "sstore r4 r1",                                   # t = pos
          f"movi r4 {_sc(5)}", "movi r5 0", "sstore r4 r5"]                      # level = 0
    L += ["merge_loop:",
          f"movi r4 {_sc(4)}", "sload r5 r4", "movi r1 2", "divmod r5 r1", "sstore r4 r5",  # t //= 2, bit -> r7
          "jnz r7 @do_merge", "jmp @merge_done",
          "do_merge:"]
    L += [f"movi r4 {_sc(5)}", "sload r1 r4",                                    # level
          f"movi r4 {SS_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
          "sload r5 r4", "add r2 r5"]                                            # s += SS[level]
    L += [f"movi r4 {SH_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
          "sload r5 r4",                                                         # left = SH[level]
          f"movi r4 {TAG_NODE}", "hash r6 <- r4 r5 r6 r2"]                       # h = H(tag, L, h, s)
    L += [f"movi r4 {_sc(5)}", "sload r1 r4", "movi r5 1", "add r1 r5", "sstore r4 r1",     # level++
          "jmp @merge_loop", "merge_done:"]
    # store (h, s) at the final level
    L += [f"movi r4 {_sc(5)}", "sload r1 r4",
          f"movi r4 {SH_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0", "sstore r4 r6",
          f"movi r4 {SS_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0", "sstore r4 r2"]
    L += [f"movi r4 {_sc(3)}", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5",     # pos++
          "jmp @tree_loop", "tree_done:"]
    # root = SH[7], total = SS[7]
    L += [f"movi r4 {(SS_BASE + LEVELS) << 32}", "add r4 r0", "sload r5 r4",
          f"movi r6 {SHIPS}", "eq r5 r6", "require r5"]
    L += [f"movi r4 {(SH_BASE + LEVELS) << 32}", "add r4 r0", "sload r2 r4"]     # rebuilt root
    L += [f"movi r4 {_sc(0)}", "sload r6 r4", "movi r5 1", "eq r6 r5"]           # winner==p1?
    L += _sl(R1) + ["sload r5 r4", "mul r5 r6", "mov r1 r6", "notb r1"]
    L += _sl(R2) + ["sload r4 r4", "mul r4 r1", "add r5 r4", "eq r5 r2", "require r5"]
    # pay the winner the pot
    L += [f"movi r4 {_sc(0)}", "sload r6 r4", "movi r5 1", "eq r6 r5"]           # e1
    L += _sl(P1) + ["sload r5 r4", "mul r5 r6", "mov r1 r6", "notb r1"]
    L += _sl(P2) + ["sload r4 r4", "mul r4 r1", "add r5 r4"]                     # winner addr digest
    L += _sl(PT) + ["sload r3 r4", "pay r5 r3"]
    L += _sl(SD) + ["movi r5 1", "sstore r4 r5"]
    L += _sl(PT) + ["movi r5 0", "sstore r4 r5"]
    # cleanup: the 17 occupancy cells + the 8+8 stack slots (zero = delete)
    for i, ln in enumerate(FLEET_LENS):
        ai, oi = 1 + 2 * i, 2 + 2 * i
        L += [f"movi r5 {ai}", "arg r1 r5", f"movi r5 {oi}", "arg r2 r5"]
        for k in range(ln):
            L += ["movi r5 9", "mul r5 r2", "movi r6 1", "add r5 r6", f"movi r6 {k}", "mul r5 r6",
                  "add r5 r1",
                  f"movi r4 {O_BASE}", "add r4 r5", f"movi r6 {_2_32}", "mul r4 r6", "add r4 r0",
                  "movi r6 0", "sstore r4 r6"]
    for lv in range(LEVELS + 1):
        L += [f"movi r4 {(SH_BASE + lv) << 32}", "add r4 r0", "movi r5 0", "sstore r4 r5",
              f"movi r4 {(SS_BASE + lv) << 32}", "add r4 r0", "movi r5 0", "sstore r4 r5"]
    for i in (0, 3, 4, 5, 8):                                                    # scrub scratch (0 = delete)
        L += [f"movi r4 {_sc(i)}", "movi r5 0", "sstore r4 r5"]
    L += ["ret r0"]
    return L


FORFEIT = "\n".join(
    _sl(NN) + ["sload r5 r4", "movi r6 2", "eq r5 r6", "require r5"]
    + _sl(DC) + ["sload r5 r4", "require r5"]
    + _sl(SD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _sl(CD) + ["sload r5 r4", "ctx r6 cursor", "lt r5 r6", "require r5"]       # past the claim deadline
    + _myslot("r2")
    + _sl(WR) + ["sload r5 r4", "add r5 r2", "movi r6 3", "eq r5 r6", "require r5"]   # caller is the LOSER
    + ["ctx r5 caller"] + _sl(PT) + ["sload r3 r4", "pay r5 r3"]
    + _sl(SD) + ["movi r5 1", "sstore r4 r5"]
    + _sl(PT) + ["movi r5 0", "sstore r4 r5", "ret r0"])

CANCEL = "\n".join(
    _sl(NN) + ["sload r5 r4", "movi r6 1", "eq r5 r6", "require r5"]
    + ["ctx r5 caller"] + _sl(P1) + ["sload r6 r4", "eq r6 r5", "require r6"]
    + _sl(SD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + ["ctx r5 caller"] + _sl(PT) + ["sload r3 r4", "pay r5 r3"]
    + _sl(SD) + ["movi r5 1", "sstore r4 r5"]
    + _sl(PT) + ["movi r5 0", "sstore r4 r5", "ret r0"])

# ---- free Daily Salvo: provable off-chain solo run + faucet rewards (static/battleship-daily.js) ----
POST = _lib.daily_post(ECNT_SLOT, E_DAY, E_ADDR, E_SCORE, E_N, ELIST, EW_BASE, DAILY_WORDS, max_n=40, max_score=2000, e_ts=E_TS)
ANCHOR = _lib.daily_anchor(A_H, A_V, DCNT_SLOT, DLIST)

SRC = {"open": OPEN, "join": JOIN, "fire": FIRE, "resign": RESIGN, "timeout": TIMEOUT,
       "forfeit": FORFEIT, "cancel": CANCEL, "post": POST, "anchor": ANCHOR}

ABI = {
    "open": {"args": ["gameId", "root"], "value": True},
    "join": {"args": ["gameId", "root"], "value": True},
    "fire": {"args": ["gameId", "cell"]},
    "answer": {"args": ["gameId", "isShip", "salt"] + [f"sib{i // 2}" if i % 2 == 0 else f"ss{i // 2}"
                                                       for i in range(2 * LEVELS)]},
    "resign": {"args": ["gameId"]},
    "timeout": {"args": ["gameId"]},
    "claim": {"args": ["gameId", "a0", "o0", "a1", "o1", "a2", "o2", "a3", "o3", "a4", "o4", "seed"]},
    "forfeit": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    "post": {"args": _lib.daily_post_abi(DAILY_WORDS)},
    "anchor": {"args": ["day"]},
    "_view": {
        "maps": {"p1": {"field": P1, "index": "games"}, "p2": {"field": P2, "index": "games"},
                 "r1": {"field": R1, "index": "games"}, "r2": {"field": R2, "index": "games"},
                 "st": {"field": ST, "index": "games"}, "pt": {"field": PT, "index": "games"},
                 "nn": {"field": NN, "index": "games"}, "sd": {"field": SD, "index": "games"},
                 "dl": {"field": DL, "index": "games"}, "pc": {"field": PC, "index": "games"},
                 "pex": {"field": PEX, "index": "games"}, "pf": {"field": PF, "index": "games"},
                 "tf": {"field": TF, "index": "games"}, "h1": {"field": H1, "index": "games"},
                 "h2": {"field": H2, "index": "games"}, "wr": {"field": WR, "index": "games"},
                 "dc": {"field": DC, "index": "games"}, "cd": {"field": CD, "index": "games"},
                 # Daily Salvo board: per-entry fields + packed shots + the day anchor
                 "eday": {"field": E_DAY, "index": "entries"}, "eaddr": {"field": E_ADDR, "index": "entries"},
                 "escore": {"field": E_SCORE, "index": "entries"}, "en": {"field": E_N, "index": "entries"},
                 "ets": {"field": E_TS, "index": "entries"},
                 **{f"ew{k}": {"field": EW_BASE + k, "index": "entries"} for k in range(DAILY_WORDS)},
                 "ah": {"field": A_H, "index": "days"}, "av": {"field": A_V, "index": "days"}},
        "indexes": {"games": {"cnt": 0, "list": GLIST}, "entries": {"cnt": ECNT_SLOT, "list": ELIST},
                    "days": {"cnt": DCNT_SLOT, "list": DLIST}},
        "addr": ["p1", "p2", "eaddr"],
        "board": {"name": "fd1", "base": F1_BASE, "cells": 100, "stride": 100, "index": "games"},
    },
}
ABI["_view"]["board2"] = {"name": "fd2", "base": F2_BASE, "cells": 100, "stride": 100, "index": "games"}
ABI["_view"]["board3"] = {"name": "rs1", "base": RS1_BASE, "cells": 100, "stride": 100, "index": "games"}
ABI["_view"]["board4"] = {"name": "rs2", "base": RS2_BASE, "cells": 100, "stride": 100, "index": "games"}


def build():
    src = dict(SRC)
    src["answer"] = "\n".join(_answer())
    src["claim"] = "\n".join(_claim())
    return zkvmasm.assemble_contract(src)

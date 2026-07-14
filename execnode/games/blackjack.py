"""
Blackjack — zkVM port (doc/zk-execution-proofs.md). Banked, dealer-less: a machine's bank covers a 5:2
natural, a player deals a hand, hits/stands, then the DEALER PLAYS ITSELF on-chain (stand on 17, "S17")
from L1 BLOCKHASH randomness — so the whole hand reconstructs from chain state with no house to trust.
Win pays 2×, push refunds, a natural (2 cards = 21) pays 5:2. Ported from the deleted stackvm contract with
identical rules; the card model matches static/cards.js:

  card c ∈ 0..51 = alghash([bh(gh)+bh(gh+1) + g*64 + offset + i]) % 52 ; rank r = c%13 ; value r≤8→r+2,
  9≤r≤11→10 (J/Q/K), r=12→1 (ace, counts 11 when hard+10≤21). offsets: player 0, dealer up 16, hit gn,
  dealer draws 32+j. Cards persist as value+1 in pc[g*16+k] / dk[g*16+j] (per-index board fields).

Seat: 7 gg 9 gs 10 ga 11 gh 12 gf(phase 1 dealt·2 acting·3 hit·4 settle) 13 gn 14 gd 15 gw 16 gr(dealer best)
  17 du(up+1) 18 php(player hard) 19 pac(player aces) 20 ge.  Table: 1 ta 2 tk 3 tp 4 tc 6 tz.
Board: PC_BASE(40)+k player cards, DK_BASE(60)+j dealer cards, keyed by g.  Scratch 30.  Index 0/21,1/22.
Methods: open(t)[bank] · deal(g,t)[stake] · reveal(g) · hit(g) · draw(g) · stand(g) · settle(g) · fund/close.
"""
from execnode import zkvmasm
from execnode.games import _lib
from execnode.stark import alghash, field as F

TA, TK, TP, TC, TZ = 1, 2, 3, 4, 6
GG, GS, GA, GH, GF, GN, GD, GW, GR, DU, PHP, PAC, GE = 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20
PC_BASE, DK_BASE, SC = 40, 60, 30
TLIST, GLIST = 21, 22


def card_at(bh0, bh1, salt, i):
    return (alghash.hashn([(bh0 % F.P + bh1 % F.P + salt + i) % F.P]) & 0xFFFFFFFF) % 52


def card_value(c):
    r = c % 13
    return 1 if r == 12 else (10 if r >= 9 else r + 2)


def hand_total(cards):
    """(total, soft, bust, natural) — the ace-soft blackjack total; matches cards.js bjTotal."""
    hard = sum(card_value(c) for c in cards)
    aces = sum(1 for c in cards if c % 13 == 12)
    soft = aces > 0 and hard + 10 <= 21
    total = hard + 10 if soft else hard
    return total, soft, total > 21, len(cards) == 2 and total == 21


def dealer_play(bh0, bh1, g, up):
    """Simulate S17 exactly as the contract will: draw dealer cards (offset 32) until total ≥ 17."""
    cards = [up]
    for j in range(16):
        t, _, bust, _ = hand_total(cards)
        if t >= 17:
            break
        cards.append(card_at(bh0, bh1, g * 64 + 32, j))
    return hand_total(cards)[0]


def _s(i):
    return (SC << 32) | i


def _card_val_asm(c_reg, val_out, ace_out):
    """From card in c_reg compute value -> val_out and ace flag -> ace_out (uses r4/r5; r7=rem after divmod)."""
    L = [f"mov r4 {c_reg}", "movi r5 13", "divmod r4 r5"]              # r7 = rank = c%13
    # ace = (rank==12)
    L += [f"mov {ace_out} r7", "movi r4 12", f"eq {ace_out} r4"]
    # value = (r+2)*(r<9) + 10*(r>=9)*(r<12) + 1*(r==12)
    L += [f"mov {val_out} r7", "movi r4 2", f"add {val_out} r4",       # r+2
          "mov r5 r7", "movi r4 9", "lt r5 r4", f"mul {val_out} r5"]   # *(r<9)
    L += ["mov r5 r7", "movi r4 9", "lt r5 r4", "notb r5",             # r>=9
          "mov r4 r7", "movi r6 12", "lt r4 r6", "mul r5 r4",          # *(r<12)
          "movi r4 10", "mul r5 r4", f"add {val_out} r5"]              # +10*(9<=r<12)
    L += [f"mov r5 {ace_out}", "movi r4 1", "mul r5 r4", f"add {val_out} r5"]   # + ace*1
    return L


def _seed_q():
    """q = bh(gh)+bh(gh+1)+g*64 -> SC0 (g in r0)."""
    return ["slot r4 11 r0", "sload r5 r4", "bhash r3 r5", "movi r6 1", "add r5 r6", "bhash r6 r5", "add r3 r6",
            "mov r5 r0", "movi r6 64", "mul r5 r6", "add r3 r5", f"movi r4 {_s(0)}", "sstore r4 r3"]


def _draw_player(offset, idx):
    """Draw player card at q+offset, store pc[idx]=c+1, add value/ace to php(SC1)/pac(SC2)."""
    L = [f"movi r4 {_s(0)}", "sload r3 r4", f"movi r5 {offset}", "add r3 r5",
         "hash r3 <- r3", "lo32 r3", "movi r5 52", "rem r3 r5"]            # r3 = card
    L += [f"movi r4 {(PC_BASE + idx) << 32}", "add r4 r0", "mov r5 r3", "movi r6 1", "add r5 r6", "sstore r4 r5"]
    L += _card_val_asm("r3", "r1", "r2")                                     # r1=value, r2=ace
    L += [f"movi r4 {_s(1)}", "sload r5 r4", "add r5 r1", "sstore r4 r5",    # php += value
          f"movi r4 {_s(2)}", "sload r5 r4", "add r5 r2", "sstore r4 r5"]    # pac += ace
    return L


def _player_total(php_reg, pac_reg, out):
    """out = php + 10*(pac>0 && php+10<=21)  (given php in php_reg, pac in pac_reg)."""
    return [f"mov {out} {php_reg}",
            f"mov r5 {pac_reg}", "nez r5",                                    # pac>0
            f"mov r6 {php_reg}", "movi r4 10", "add r6 r4", "movi r4 22", "lt r6 r4", "mul r5 r6",  # &&(php+10<22)
            "movi r4 10", "mul r5 r4", f"add {out} r5"]


REVEAL = f"""
    slot r4 12 r0
    sload r5 r4
    movi r6 1
    eq r5 r6
    require r5
    slot r4 11 r0
    sload r5 r4
    movi r6 1
    add r5 r6
    ctx r6 cursor
    lt r6 r5
    notb r6
    require r6
""" + "\n".join(
    _seed_q()
    # php=0, pac=0
    + [f"movi r4 {_s(1)}", "movi r5 0", "sstore r4 r5", f"movi r4 {_s(2)}", "movi r5 0", "sstore r4 r5"]
    + _draw_player(0, 0) + _draw_player(1, 1)
    # dealer up card at q+16 -> du = up+1
    + [f"movi r4 {_s(0)}", "sload r3 r4", "movi r5 16", "add r3 r5", "hash r3 <- r3", "lo32 r3", "movi r5 52",
       "divmod r3 r5", "mov r6 r7", "movi r5 1", "add r6 r5", "slot r4 17 r0", "sstore r4 r6"]
    # gn=2 ; store php/pac to seat
    + ["slot r4 13 r0", "movi r5 2", "sstore r4 r5",
       f"movi r4 {_s(1)}", "sload r5 r4", "slot r4 18 r0", "sstore r4 r5",
       f"movi r4 {_s(2)}", "sload r5 r4", "slot r4 19 r0", "sstore r4 r5"]
    # total -> r1 ; natural = total==21
    + ["slot r4 18 r0", "sload r2 r4", "slot r4 19 r0", "sload r3 r4"]      # php->r2, pac->r3
    + _player_total("r2", "r3", "r1")
    + ["mov r5 r1", "movi r4 21", "eq r5 r4"]                               # r5 = natural
    # if natural: pay stake*5/2, gd=1, gw=3(natural), release cover; else gf=2, gh=0
    + ["jnz r5 @natural", "slot r4 12 r0", "movi r6 2", "sstore r4 r6",     # gf=2
       "slot r4 11 r0", "movi r6 0", "sstore r4 r6", "ret r0",             # gh=0
       "natural:",
       "slot r4 9 r0", "sload r3 r4", "movi r6 5", "mul r3 r6", "movi r6 2", "divmod r3 r6",  # pay = stake*5/2
       "slot r4 10 r0", "sload r6 r4", "pay r6 r3",                         # pay player
       # bank: release cover tc -= stake*3/2 ; tp -= (pay - stake) ; tk -= (pay - stake)
       "slot r4 7 r0", "sload r1 r4",                                       # t
       "slot r4 9 r0", "sload r2 r4",                                       # stake
       "mov r5 r2", "movi r6 3", "mul r5 r6", "movi r6 2", "divmod r5 r6",  # cover=stake*3/2
       "slot r4 4 r1", "sload r6 r4", "sub r6 r5", "sstore r4 r6",          # tc -= cover
       "mov r5 r3", "sub r5 r2",                                            # net = pay - stake
       "slot r4 3 r1", "sload r6 r4", "sub r6 r5", "sstore r4 r6",          # tp -= net
       "slot r4 2 r1", "sload r6 r4", "sub r6 r5", "sstore r4 r6",          # tk -= net
       "slot r4 14 r0", "movi r5 1", "sstore r4 r5",                        # gd=1
       "slot r4 15 r0", "movi r5 3", "sstore r4 r5", "ret r0"])             # gw=3
"""FILLED"""


SETTLE = f"""
    slot r4 12 r0
    sload r5 r4
    movi r6 4
    eq r5 r6
    require r5
    slot r4 11 r0
    sload r5 r4
    movi r6 1
    add r5 r6
    ctx r6 cursor
    lt r6 r5
    notb r6
    require r6
""" + "\n".join(
    # dq = bh(gh)+bh(gh+1)+g*64+32 -> SC0 ; dealer hard(SC1)=val(up), aces(SC2)=ace(up), j(SC3)=0
    ["slot r4 11 r0", "sload r5 r4", "bhash r3 r5", "movi r6 1", "add r5 r6", "bhash r6 r5", "add r3 r6",
     "mov r5 r0", "movi r6 64", "mul r5 r6", "add r3 r5", "movi r6 32", "add r3 r6", f"movi r4 {_s(0)}", "sstore r4 r3"]
    + ["slot r4 17 r0", "sload r3 r4", "movi r5 1", "sub r3 r5"]            # up card = du-1 -> r3
    + _card_val_asm("r3", "r1", "r2")
    + [f"movi r4 {_s(1)}", "sstore r4 r1", f"movi r4 {_s(2)}", "sstore r4 r2", f"movi r4 {_s(3)}", "movi r5 0", "sstore r4 r5"]
    # loop: while dealer_total < 17 and j<16: draw dk[j], accumulate
    + ["ds_loop:",
       # dtotal = hard + 10*(aces>0 && hard+10<=21)
       f"movi r4 {_s(1)}", "sload r2 r4", f"movi r4 {_s(2)}", "sload r3 r4"]
    + _player_total("r2", "r3", "r1")                                       # r1 = dtotal
    + ["movi r5 17", "lt r1 r5",                                            # r1 = (dtotal<17)
       f"movi r4 {_s(3)}", "sload r5 r4", "movi r6 16", "lt r5 r6", "mul r1 r5",   # r1 &= (j<16)
       "jnz r1 @ds_body", "jmp @ds_done", "ds_body:",
       # draw dk[j]: c = HASH(dq+j)%52 ; store dk[j]=c+1 ; hard+=val, aces+=ace
       f"movi r4 {_s(0)}", "sload r3 r4", f"movi r4 {_s(3)}", "sload r5 r4", "add r3 r5",
       "hash r3 <- r3", "lo32 r3", "movi r5 52", "rem r3 r5",           # r3=card
       f"movi r4 {DK_BASE << 32}", "movi r5 4294967296", f"movi r6 {_s(3)}", "sload r6 r6", "mul r5 r6",
       "add r4 r5", "add r4 r0", "mov r5 r3", "movi r6 1", "add r5 r6", "sstore r4 r5"]  # dk[j]=c+1
    + _card_val_asm("r3", "r1", "r2")
    + [f"movi r4 {_s(1)}", "sload r5 r4", "add r5 r1", "sstore r4 r5",      # hard+=val
       f"movi r4 {_s(2)}", "sload r5 r4", "add r5 r2", "sstore r4 r5",      # aces+=ace
       f"movi r4 {_s(3)}", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5",  # j++
       "jmp @ds_loop", "ds_done:"]
    # dtotal -> store gr ; ptotal from seat
    + [f"movi r4 {_s(1)}", "sload r2 r4", f"movi r4 {_s(2)}", "sload r3 r4"]
    + _player_total("r2", "r3", "r1")                                       # dtotal -> r1
    + ["slot r4 16 r0", "sstore r4 r1", f"movi r4 {_s(4)}", "sstore r4 r1"]  # gr=dtotal, SC4=dtotal
    + ["slot r4 18 r0", "sload r2 r4", "slot r4 19 r0", "sload r3 r4"]
    + _player_total("r2", "r3", "r1")                                       # ptotal -> r1
    + [f"movi r4 {_s(5)}", "sstore r4 r1"]                                   # SC5=ptotal
    # win = (dtotal>21) || (ptotal>dtotal) ; push = ptotal==dtotal ; (ptotal>21 already lost at draw time)
    + [f"movi r4 {_s(4)}", "sload r1 r4", f"movi r4 {_s(5)}", "sload r2 r4",  # r1=dtotal r2=ptotal
       "movi r6 21", "lt r6 r1",                                            # dealer bust
       "mov r5 r1", "lt r5 r2", "add r6 r5", "nez r6",                      # || ptotal>dtotal -> win (r6)
       f"movi r4 {_s(6)}", "sstore r4 r6",                                  # SC6=win
       "mov r7 r1", "eq r7 r2", f"movi r4 {_s(7)}", "sstore r4 r7"]         # SC7=push
    # pay: win -> 2*stake ; push -> stake
    + ["slot r4 9 r0", "sload r3 r4",                                       # stake
       f"movi r4 {_s(6)}", "sload r5 r4", "mov r6 r3", "movi r7 2", "mul r6 r7", "mul r6 r5",  # win*2*stake
       f"movi r4 {_s(7)}", "sload r5 r4", "mov r7 r3", "mul r7 r5", "add r6 r7",  # + push*stake -> r6 payout
       f"movi r4 {_s(8)}", "sstore r4 r6",                                  # SC8=payout
       "slot r4 10 r0", "sload r4 r4", "pay r4 r6"]                         # pay player
    # bank: t ; tc -= cover(stake*3/2) ; tp += stake - payout ; tk += stake - payout
    + ["slot r4 7 r0", "sload r1 r4",                                       # t
       "slot r4 9 r0", "sload r3 r4",                                       # stake
       "mov r5 r3", "movi r6 3", "mul r5 r6", "movi r6 2", "divmod r5 r6",  # cover
       "slot r4 4 r1", "sload r6 r4", "sub r6 r5", "sstore r4 r6",          # tc -= cover
       f"movi r4 {_s(8)}", "sload r2 r4", "mov r5 r3", "sub r5 r2",         # stake - payout
       "slot r4 3 r1", "sload r6 r4", "add r6 r5", "sstore r4 r6",          # tp += (stake-payout)
       "slot r4 2 r1", "sload r6 r4", "add r6 r5", "sstore r4 r6",          # tk += (stake-payout)
       "slot r4 14 r0", "movi r5 1", "sstore r4 r5",                        # gd=1
       "slot r4 15 r0", f"movi r5 1", "sstore r4 r5", "ret r0"])            # gw=1 (resolved)
"""FILLED"""


SRC = {
    "open": _lib.open_table(TLIST),
    # deal(g, t)[stake]: reserve a 5:2 cover (tc += stake*3/2), start the hand awaiting the reveal blocks
    "deal": """
        ctx r3 value
        movi r4 0
        lt r4 r0
        require r4
        movi r4 0
        lt r4 r3
        require r4
        slot r4 7 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 1 r1
        sload r5 r4
        nez r5
        require r5
        slot r4 6 r1
        sload r5 r4
        nez r5
        notb r5
        require r5
        mov r5 r3
        movi r6 3
        mul r5 r6
        movi r6 2
        divmod r5 r6
        slot r4 4 r1
        sload r6 r4
        add r6 r5
        slot r4 2 r1
        sload r4 r4
        lt r4 r6
        notb r4
        require r4
        slot r4 4 r1
        sstore r4 r6
        slot r4 3 r1
        sload r5 r4
        add r5 r3
        sstore r4 r5
        slot r4 9 r0
        sstore r4 r3
        slot r4 7 r0
        sstore r4 r1
        ctx r6 caller
        slot r4 10 r0
        sstore r4 r6
        slot r4 12 r0
        movi r5 1
        sstore r4 r5
        slot r4 13 r0
        movi r5 0
        sstore r4 r5
        slot r4 11 r0
        ctx r5 cursor
        movi r6 2
        add r5 r6
        sstore r4 r5
        slot r4 20 r0
        ctx r5 cursor
        sstore r4 r5
        movi r4 1
        sload r5 r4
        slot r6 22 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    "reveal": REVEAL,
    # hit(g): request another player card
    "hit": """
        slot r4 12 r0
        sload r5 r4
        movi r6 2
        eq r5 r6
        require r5
        ctx r6 caller
        slot r4 10 r0
        sload r5 r4
        eq r5 r6
        require r5
        slot r4 12 r0
        movi r5 3
        sstore r4 r5
        slot r4 11 r0
        ctx r5 cursor
        movi r6 2
        add r5 r6
        sstore r4 r5
        slot r4 20 r0
        ctx r5 cursor
        sstore r4 r5
        ret r0
    """,
    "draw": None,
    "stand": """
        slot r4 12 r0
        sload r5 r4
        movi r6 2
        eq r5 r6
        require r5
        ctx r6 caller
        slot r4 10 r0
        sload r5 r4
        eq r5 r6
        require r5
        slot r4 12 r0
        movi r5 4
        sstore r4 r5
        slot r4 11 r0
        ctx r5 cursor
        movi r6 2
        add r5 r6
        sstore r4 r5
        slot r4 20 r0
        ctx r5 cursor
        sstore r4 r5
        ret r0
    """,
    "settle": SETTLE,
    "fund": _lib.fund_table(),
    "close": _lib.close_table(),
}


def _draw():
    """draw(g): the requested hit card; on bust the hand is lost immediately (bank keeps the stake)."""
    L = ["slot r4 12 r0", "sload r5 r4", "movi r6 3", "eq r5 r6", "require r5",   # gf==3
         "slot r4 11 r0", "sload r5 r4", "movi r6 1", "add r5 r6", "ctx r6 cursor", "lt r6 r5", "notb r6", "require r6"]
    L += _seed_q()
    # card at q + gn ; store pc[gn] = c+1 ; add to php/pac ; gn++
    L += [f"movi r4 {_s(0)}", "sload r3 r4", "slot r4 13 r0", "sload r5 r4", "add r3 r5",   # q+gn
          "hash r3 <- r3", "lo32 r3", "movi r5 52", "rem r3 r5"]                          # r3=card
    L += [f"movi r4 {PC_BASE << 32}", "movi r5 4294967296", "slot r6 13 r0", "sload r6 r6", "mul r5 r6",
          "add r4 r5", "add r4 r0", "mov r5 r3", "movi r6 1", "add r5 r6", "sstore r4 r5"]   # pc[gn]=c+1
    L += _card_val_asm("r3", "r1", "r2")
    L += ["slot r4 18 r0", "sload r5 r4", "add r5 r1", "sstore r4 r5",    # php += val
          "slot r4 19 r0", "sload r5 r4", "add r5 r2", "sstore r4 r5",    # pac += ace
          "slot r4 13 r0", "sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5"]  # gn++
    # total ; bust?
    L += ["slot r4 18 r0", "sload r2 r4", "slot r4 19 r0", "sload r3 r4"]
    L += _player_total("r2", "r3", "r1")
    L += ["movi r5 21", "lt r5 r1"]                                       # bust = total>21
    L += ["jnz r5 @bust",
          "slot r4 12 r0", "movi r6 2", "sstore r4 r6", "slot r4 11 r0", "movi r6 0", "sstore r4 r6", "ret r0",  # gf=2
          "bust:",
          # lose: release cover, bank keeps stake. t=gg ; tc -= cover ; tp += stake ; tk += stake
          "slot r4 7 r0", "sload r1 r4", "slot r4 9 r0", "sload r3 r4",
          "mov r5 r3", "movi r6 3", "mul r5 r6", "movi r6 2", "divmod r5 r6",   # cover
          "slot r4 4 r1", "sload r6 r4", "sub r6 r5", "sstore r4 r6",           # tc -= cover
          "slot r4 3 r1", "sload r6 r4", "add r6 r3", "sstore r4 r6",           # tp += stake
          "slot r4 2 r1", "sload r6 r4", "add r6 r3", "sstore r4 r6",           # tk += stake
          "slot r4 14 r0", "movi r5 1", "sstore r4 r5",                         # gd=1
          "slot r4 15 r0", "movi r5 2", "sstore r4 r5", "ret r0"]              # gw=2 (dealer/bust)
    return L


ABI = {
    "open": {"args": ["tableId"], "value": True},
    "deal": {"args": ["gameId", "tableId"], "value": True},
    "reveal": {"args": ["gameId"]},
    "hit": {"args": ["gameId"]},
    "draw": {"args": ["gameId"]},
    "stand": {"args": ["gameId"]},
    "settle": {"args": ["gameId"]},
    "fund": {"args": ["tableId"], "value": True},
    "close": {"args": ["tableId"]},
    "_view": {
        "maps": {**_lib.view_table_maps("tables"),
                 "gg": {"field": GG, "index": "games"}, "gs": {"field": GS, "index": "games"},
                 "ga": {"field": GA, "index": "games"}, "gh": {"field": GH, "index": "games"},
                 "gf": {"field": GF, "index": "games"}, "gn": {"field": GN, "index": "games"},
                 "gd": {"field": GD, "index": "games"}, "gw": {"field": GW, "index": "games"},
                 "gr": {"field": GR, "index": "games"}, "du": {"field": DU, "index": "games"},
                 "ge": {"field": GE, "index": "games"}},
        "indexes": {"tables": {"cnt": 0, "list": TLIST}, "games": {"cnt": 1, "list": GLIST}},
        "addr": ["ta", "ga"],
        "board": {"name": "pc", "base": PC_BASE, "cells": 16, "stride": 16, "index": "games"},
    },
}
# second board map (dealer) — decode_view supports board/board2/board3/board4
ABI["_view"]["board2"] = {"name": "dk", "base": DK_BASE, "cells": 16, "stride": 16, "index": "games"}


def build():
    src = dict(SRC)
    src["draw"] = "\n".join(_draw())
    return zkvmasm.assemble_contract(src)

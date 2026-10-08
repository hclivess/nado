"""
Coin Flip — zkVM port (doc/zk-execution-proofs.md). A fair 2-player flip, now decided by COMMIT-REVEAL:
each player commits C = HASH(secret) with their stake (open / join), both reveal, and the coin is

    winner = HASH(s1 + s2 + gameId) LO32 % 2        (0 -> p1 / heads, 1 -> p2 / tails)

The same formula the old code used with BLOCKHASH(sh) + BLOCKHASH(sh+1) in place of the two secrets — so the
client's chainResultAlg(s1, s2, g, 2) previews it byte-for-byte. Neither secret is known to the other player
when they commit, so neither can steer the sum, and no block producer is involved in the draw at all.

Withholding is the only lever a player has once they see the opponent's secret, so it is priced in: the reveal
window is REVEAL_WINDOW blocks from the join, and after it closes settle pays the WHOLE pot to a lone revealer
(the one who stayed silent forfeits). If NOBODY revealed, each player gets their own stake back.

Over the composite-integer slot model:   slot(field, gameId) = field*2^32 + gameId   (the `slot` asm macro)

Fields:   1 nn(state 0/1/2)  2 st(stake)  3 pt(pot)  4 p1  5 p2  6 sd(settled)  7 sh(legacy settle height)
          8 ws(winner slot; 0 on a refund/void)
          10 c1 / 11 c2 (commitments)  12 md (1 = commit-reveal game; 0 = a game opened by the old code)
          13 dl (reveal deadline: reveals land while cursor < dl; forfeit/refund settle once cursor >= dl)
          14 s1 / 15 s2 (revealed secrets)  16 v1 / 17 v2 (revealed flags — a secret of 0 is still "revealed")
Index:    slot 0 = cnt (open-game count);  slot(9, i) = the i-th gameId   (so the frontend can enumerate)

Methods: open(g, commit)[stake] · join(g, commit)[stake] · reveal(g, secret) · settle(g) · reclaim(g) · cancel(g).
gameId is a frontend int < 2^32. A game opened by the OLD code (md == 0, no commitment) keeps the old rule end to
end: join arms sh = cursor + 2, settle reads BLOCKHASH(sh) + BLOCKHASH(sh+1), reclaim voids it past the horizon.
"""
from execnode import zkvmasm
from execnode.games import _lib

NN, ST, PT, P1, P2, SD, SH, WS, LIST = 1, 2, 3, 4, 5, 6, 7, 8, 9
C1, C2, MD, DL, S1, S2, V1, V2 = 10, 11, 12, 13, 14, 15, 16, 17
# REVEAL_WINDOW: blocks from the join for BOTH reveals to land (~1 h at the measured ~6.8 s cadence). Long enough for
# a client that was closed to come back and auto-reveal; short enough that a silent loser cannot park the pot for
# long. INVARIANT: every commit-reveal game resolves by cursor >= join + REVEAL_WINDOW because settle needs no
# block hash and no player action past the deadline — so commit-reveal games never need reclaim.
REVEAL_WINDOW = 600

SRC = {
    # open(g, commit) with stake escrowed as call value: new commit-reveal game (md = 1), record p1 + stake +
    # p1's commitment, append to the index. INVARIANT: every game opened from now on has md == 1 and c1 != 0
    # because this is the only method that creates a game and it refuses a zero commitment.
    "open": """
        mov r7 r1
        mov r2 r7
        nez r2
        require r2
        ctx r1 value
        movi r2 0
        lt r2 r1
        require r2
        movi r2 0
        lt r2 r0
        require r2
        movi r2 4294967296
        mov r5 r0
        lt r5 r2
        require r5
        slot r4 1 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 2 r0
        sstore r4 r1
        slot r4 3 r0
        sstore r4 r1
        ctx r6 caller
        slot r4 4 r0
        sstore r4 r6
        slot r4 1 r0
        movi r5 1
        sstore r4 r5
        slot r4 10 r0
        sstore r4 r7
        slot r4 12 r0
        sstore r4 r5
        movi r4 0
        sload r5 r4
        slot r6 9 r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """,
    # join(g, commit): matching stake, different player. A commit-reveal game (md == 1) records c2 and opens
    # the reveal window (dl = cursor + REVEAL_WINDOW); a game opened by the OLD code (md == 0) keeps the old rule
    # — the commitment is ignored and settlement is armed two blocks out (sh = cursor + 2).
    "join": """
        mov r3 r1
        ctx r1 value
        slot r4 1 r0
        sload r5 r4
        movi r2 1
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 2 r0
        sload r5 r4
        eq r5 r1
        require r5
        ctx r6 caller
        slot r4 4 r0
        sload r5 r4
        eq r5 r6
        notb r5
        require r5
        slot r4 5 r0
        sstore r4 r6
        slot r4 3 r0
        sload r5 r4
        add r5 r1
        sstore r4 r5
        slot r4 1 r0
        movi r5 2
        sstore r4 r5
        slot r4 12 r0
        sload r5 r4
        jnz r5 @cr
        slot r4 7 r0
        ctx r5 cursor
        movi r6 2
        add r5 r6
        sstore r4 r5
        ret r0
    cr:
        mov r5 r3
        nez r5
        require r5
        slot r4 11 r0
        sstore r4 r3
        slot r4 13 r0
        ctx r5 cursor
        movi r6 %d
        add r5 r6
        sstore r4 r5
        ret r0
    """ % REVEAL_WINDOW,
    # settle(g), permissionless, on a joined unsettled game:
    #  * commit-reveal (md == 1): both revealed -> winner = HASH(s1 + s2 + g) LO32 % 2, pot to the winner (any
    #    time); otherwise only once cursor >= dl: exactly one revealed -> that player takes the pot (ws = their
    #    slot); none revealed -> each player gets their own stake back (ws stays 0).
    #    INVARIANT: a player who withholds a losing reveal cannot gain by it, because the lone revealer takes
    #    the whole pot at the deadline — withholding turns a loss into the same loss.
    #  * legacy (md == 0): once both settle-height blocks are final, derive the winner from BLOCKHASH exactly
    #    as before and pay the pot.
    "settle": """
        slot r4 1 r0
        sload r5 r4
        movi r2 2
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 12 r0
        sload r5 r4
        jnz r5 @cr
        slot r4 7 r0
        sload r5 r4
        movi r6 1
        add r5 r6
        ctx r6 cursor
        lt r6 r5
        notb r6
        require r6
        slot r4 7 r0
        sload r2 r4
        bhash r3 r2
        movi r6 1
        add r2 r6
        bhash r5 r2
        add r3 r5
        add r3 r0
        hash r3 <- r3
        lo32 r3
        movi r6 2
        divmod r3 r6
        movi r6 1
        add r7 r6
        slot r4 8 r0
        sstore r4 r7
        slot r4 3 r0
        sload r1 r4
        movi r5 2
        sub r5 r7
        mov r6 r1
        mul r6 r5
        slot r4 4 r0
        sload r2 r4
        pay r2 r6
        movi r5 1
        sub r7 r5
        mov r6 r1
        mul r6 r7
        slot r4 5 r0
        sload r2 r4
        pay r2 r6
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    cr:
        slot r4 3 r0
        sload r1 r4
        slot r4 16 r0
        sload r2 r4
        slot r4 17 r0
        sload r3 r4
        mov r5 r2
        mul r5 r3
        jnz r5 @both
        slot r4 13 r0
        sload r5 r4
        ctx r6 cursor
        lt r6 r5
        notb r6
        require r6
        movi r7 1
        jnz r2 @payw
        movi r7 2
        jnz r3 @payw
        slot r4 2 r0
        sload r1 r4
        slot r4 4 r0
        sload r6 r4
        pay r6 r1
        slot r4 5 r0
        sload r6 r4
        pay r6 r1
        jmp @done
    both:
        slot r4 14 r0
        sload r3 r4
        slot r4 15 r0
        sload r5 r4
        add r3 r5
        add r3 r0
        hash r3 <- r3
        lo32 r3
        movi r6 2
        divmod r3 r6
        movi r6 1
        add r7 r6
    payw:
        slot r4 8 r0
        sstore r4 r7
        slot r4 4 r0
        movi r6 1
        mov r5 r7
        eq r5 r6
        jnz r5 @pay
        slot r4 5 r0
    pay:
        sload r2 r4
        pay r2 r1
    done:
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
    # reveal(g, secret): a player of a joined commit-reveal game, while cursor < dl, discloses the secret behind
    # their commitment — once. INVARIANT: a revealed secret is the committed one because HASH(secret) must equal
    # the stored commitment; a second reveal is refused because the flag is checked before it is set. Reveals
    # need nn == 2, so the opener can never disclose before the joiner's commitment is fixed.
    "reveal": """
        slot r4 1 r0
        sload r5 r4
        movi r2 2
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 12 r0
        sload r5 r4
        require r5
        slot r4 13 r0
        sload r5 r4
        ctx r6 cursor
        lt r6 r5
        require r6
        hash r3 <- r1
        ctx r6 caller
        slot r4 4 r0
        sload r5 r4
        eq r5 r6
        jnz r5 @p1
        slot r4 5 r0
        sload r5 r4
        eq r5 r6
        require r5
        slot r4 17 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 11 r0
        sload r5 r4
        eq r5 r3
        require r5
        slot r4 15 r0
        sstore r4 r1
        slot r4 17 r0
        movi r5 1
        sstore r4 r5
        ret r0
    p1:
        slot r4 16 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 10 r0
        sload r5 r4
        eq r5 r3
        require r5
        slot r4 14 r0
        sstore r4 r1
        slot r4 16 r0
        movi r5 1
        sstore r4 r5
        ret r0
    """,
    # reclaim(g): a joined game (nn==2) settles from bhash(sh); once sh ages past the ~20000-height ring
    # (execnode/state.py) bhash reverts and settle can NEVER succeed — both stakes are locked forever, and
    # cancel only works pre-join (nn==1). Void it fairly: refund each player their own stake, mark settled,
    # zero the pot. Permissionless + bhash-free, gated on sh + 18000 < cursor so an in-window game is untouched.
    # LEGACY GAMES ONLY (md == 0): a commit-reveal game never reads a block hash, so settle always resolves it
    # past dl (REVEAL_WINDOW) and reclaim has nothing to rescue — refusing it keeps a forfeit from being
    # turned into a refund.
    "reclaim": """
        slot r4 1 r0
        sload r5 r4
        movi r2 2
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 12 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 7 r0
        sload r5 r4
        movi r6 18000
        add r5 r6
        ctx r6 cursor
        lt r5 r6
        require r5
        slot r4 2 r0
        sload r1 r4
        slot r4 4 r0
        sload r6 r4
        pay r6 r1
        slot r4 5 r0
        sload r6 r4
        pay r6 r1
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
    # cancel(g): only the opener, only while still waiting for a joiner — refund the stake
    "cancel": """
        ctx r1 caller
        slot r4 4 r0
        sload r5 r4
        eq r5 r1
        require r5
        slot r4 1 r0
        sload r5 r4
        movi r2 1
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 3 r0
        sload r6 r4
        pay r1 r6
        slot r4 6 r0
        movi r5 1
        sstore r4 r5
        slot r4 3 r0
        movi r5 0
        sstore r4 r5
        ret r0
    """,
}

ABI = {
    "open": {"args": ["gameId", "commit"], "value": True},
    "join": {"args": ["gameId", "commit"], "value": True},
    "reveal": {"args": ["gameId", "secret"]},
    "settle": {"args": ["gameId"]},
    "reclaim": {"args": ["gameId"]},
    "cancel": {"args": ["gameId"]},
    # _view: the exec node reconstructs these named maps from the flat slots, so coinflip.js reads them
    # exactly as it did under stackvm (only the cid changes). p1/p2 resolve digest -> L1 address.
    "_view": {"maps": {"nn": NN, "st": ST, "pt": PT, "p1": P1, "p2": P2, "sd": SD, "sh": SH, "ws": WS,
                       "c1": C1, "c2": C2, "md": MD, "dl": DL, "s1": S1, "s2": S2, "v1": V1, "v2": V2},
              "index": {"cnt": 0, "list": LIST}, "addr": ["p1", "p2"]},
}


def build():
    # C2 (security review 2026-09-23): every id-taking method refuses an id >= 2^32 before touching a slot;
    # see _lib.id_guard. The ABI, the field layout and every honest call are unchanged.
    ID_GUARDS = {m: ["r0"] for m in ("join", "reveal", "settle", "reclaim", "cancel")}
    return zkvmasm.assemble_contract(_lib.guard_ids(SRC, ID_GUARDS))

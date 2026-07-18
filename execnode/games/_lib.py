"""
Shared banked-table primitives for the zkVM game contracts (doc/zk-execution-proofs.md game model).

Every banked game (dice, roulette, slots, mines, blackjack, …) runs the SAME table lifecycle: a banker
`open`s a table with a bankroll, `fund`s it, and `close`s it to withdraw the pot; players commit an
at-risk "cover" against the bankroll and settle from L1 BLOCKHASH randomness. Before this module each game
re-emitted that skeleton in raw asm — five near-identical copies that drifted and had to be re-audited one by
one. They are byte-identical except for a single parameter (the table-list index field), so they live here
once. A future VM/opcode change now touches ONE place instead of every banked contract.

Table field convention (shared by all banked games; keep these fixed):
    1 ta(banker)  2 tk(bankroll)  3 tp(pot = banker-withdrawable)  4 tc(committed/at-risk)  6 tz(closed)
Index convention: slot 0 = table count, <tlist> field = table-id list. (Game index is game-specific.)

Each helper returns asm TEXT (assembled by zkvmasm). Register/scratch usage matches the hand-written originals
so the produced code is identical to what the audited contracts shipped — this is a de-duplication, not a
behaviour change. `id` (the table/game id) is always the method's first arg in r0.
"""

# The banked-table field ids — the fixed convention every banked game shares.
TA, TK, TP, TC, TZ = 1, 2, 3, 4, 6


def open_table(tlist):
    """open(tableId)[bankroll]: require value>0 and a fresh id, set ta=caller, tk=tp=bankroll, append id to
    the table index (slot 0 count + <tlist> field). `tlist` is the game's table-list field id."""
    return f"""
        ctx r1 value
        movi r2 0
        lt r2 r1
        require r2
        movi r2 0
        lt r2 r0
        require r2
        slot r4 1 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        ctx r6 caller
        slot r4 1 r0
        sstore r4 r6
        slot r4 2 r0
        sstore r4 r1
        slot r4 3 r0
        sstore r4 r1
        movi r4 0
        sload r5 r4
        slot r6 {tlist} r5
        sstore r6 r0
        movi r3 1
        add r5 r3
        sstore r4 r5
        ret r0
    """


def fund_table():
    """fund(tableId)[value]: banker-only, table open — add value to bankroll (tk) and pot (tp)."""
    return """
        ctx r1 value
        ctx r2 caller
        slot r4 1 r0
        sload r5 r4
        eq r5 r2
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        movi r5 0
        lt r5 r1
        require r5
        slot r4 2 r0
        sload r6 r4
        add r6 r1
        sstore r4 r6
        slot r4 3 r0
        sload r6 r4
        add r6 r1
        sstore r4 r6
        ret r0
    """


def close_table():
    """close(tableId): banker-only, not already closed, and NO OPEN BETS (tc==0) — pay out the pot (tp) and
    mark the table closed (tz). The tc==0 guard is a solvency invariant: without it a banker could close over
    unsettled bets, pay themselves the pot (which still holds those bets' committed cover) and strand the
    players — see the escrow-accounting fix (every banked game shares this close)."""
    return """
        ctx r1 caller
        slot r4 1 r0
        sload r5 r4
        eq r5 r1
        require r5
        slot r4 6 r0
        sload r5 r4
        nez r5
        notb r5
        require r5
        slot r4 4 r0
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
    """


def index_append(cnt_slot, list_field):
    """asm lines that append the id in r0 to an enumeration index: list[count]=r0 ; count++.
    Uses r3/r4/r5 as scratch (matches the hand-written game code). `cnt_slot` is a bare slot number, not a
    field*2^32 address; `list_field` is a field id (keyed by the running count)."""
    return [f"movi r4 {cnt_slot}", "sload r5 r4", f"slot r6 {list_field} r5", "sstore r6 r0",
            "movi r3 1", "add r5 r3", "sstore r4 r5"]


def view_table_maps(index="tables"):
    """The five banked-table _view map entries (ta/tk/tp/tc/tz), all keyed by the given index name."""
    return {"ta": {"field": TA, "index": index}, "tk": {"field": TK, "index": index},
            "tp": {"field": TP, "index": index}, "tc": {"field": TC, "index": index},
            "tz": {"field": TZ, "index": index}}


# =====================================================================================================
# PROVABLE DAILY BOARDS (static/provable.js model): the on-chain half of the free-practice leaderboard —
# a `post(day, score, n, w0..w{W-1})` method that records a claim (the packed move list) which every
# verifier replays through the game's real engine. The CONTRACT only gates the DAY against chain time
# (±1 UTC day) and the bounds; VERIFICATION IS REPLAY-SIDE (browsers + the faucet distributor drop
# entries whose replay doesn't reproduce the score — the chess-model trust shape; the tx fee caps spam).
# Parameterized by word count so any game gets a provable board from one audited source (scrapline
# predates this generator and keeps its historical two-range word layout — do not migrate a LIVE
# contract's storage layout).
# =====================================================================================================

def daily_post(ecnt_slot, e_day, e_addr, e_score, e_n, elist, ew_base, words, max_n, max_score=4096):
    """post(day, score, n, w0..w{words-1}): r0..r2 preload day/score/n; the claim words ride the ARG
    bus (indices 3..words+2). Entry fields keyed by the append-log entry id; word k at ew_base+k
    (serve them client-side as a _view board: base=ew_base, cells=words, index=entries)."""
    body = f"""
    movi r5 0
    lt r5 r0
    require r5              ; day > 0
    movi r5 {max_score}
    mov r6 r1
    lt r6 r5
    require r6              ; claimed score sane (the real check is the verifier's replay)
    movi r5 0
    lt r5 r2
    require r5              ; n > 0
    movi r5 {max_n + 1}
    mov r6 r2
    lt r6 r5
    require r6              ; n <= {max_n}
    ctx r5 time
    movi r6 86400
    divmodw r5 r6           ; r5 = today (UTC day index)
    mov r6 r5
    movi r7 1
    add r6 r7
    mov r7 r0
    lt r6 r7
    notb r6
    require r6              ; !(today+1 < day)
    mov r6 r0
    movi r7 1
    add r6 r7
    mov r7 r5
    lt r6 r7
    notb r6
    require r6              ; !(day+1 < today)
    movi r4 {ecnt_slot}
    sload r3 r4             ; r3 = e (entry id)
    slot r4 {e_day} r3
    sstore r4 r0
    ctx r5 caller
    slot r4 {e_addr} r3
    sstore r4 r5
    slot r4 {e_score} r3
    sstore r4 r1
    slot r4 {e_n} r3
    sstore r4 r2
"""
    for k in range(words):
        body += f"""    movi r5 {3 + k}
    arg r6 r5
    slot r4 {ew_base + k} r3
    sstore r4 r6
"""
    body += f"""    slot r4 {elist} r3
    sstore r4 r3            ; elist[e] = e (enum key)
    movi r4 {ecnt_slot}
    mov r5 r3
    movi r6 1
    add r5 r6
    sstore r4 r5            ; cnt++
    ret r3
"""
    return body


def daily_post_abi(words):
    """The matching ABI arg list for daily_post."""
    return ["day", "score", "n"] + [f"w{k}" for k in range(words)]

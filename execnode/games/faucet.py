"""
Faucet — the fixed-name SYSTEM contract (doc/faucet.md). Holds donations sent to the L1 reserved
address `faucet` (the exec node credits them to this contract's balance — its cid IS the literal
string "faucet", see execnode.state.FIXED_CIDS) and dispenses small free-play grants to players,
earmarked per enrolled game.

Registry (operator-curated, indexed — game cids are wider than a field word, so claims carry a small
index; the idx↔cid mapping ships in the ABI metadata and a 64-bit digest word is stored for binding):
  raw slot 0                 gcnt      registry slots ever used (idx < gcnt)
  gdig[idx]   field 10       low-64-bit digest word of the enrolled game's cid (informational binding)
  ggrant[idx] field 11       grant per claim, raw units (0 = paused/removed)
  gcap[idx]   field 12       max claims per DAY WINDOW (cursor / 14400 ≈ a day at 6s blocks)
  gpow[idx]   field 13       PoW target: claim needs alghash(caller, idx, nonce) < gpow
  gused       field 20       key idx·2^20 + window -> claims consumed in that window
  claimed     RAW key alghash(caller, idx) -> 1   (once per address per game; full-field key space)

claim(idx, nonce) checks, in order: enrolled+granting · PoW · first claim · window budget — then
marks, counts, and PAYs the caller the grant (the runtime reverts any payout beyond the contract's
balance, so an underfunded faucet fails closed). Sybil economics: the PoW binds the CLAIMER's address
and the game index, so nonces can't be stolen or replayed across games; grant sizes/caps bound the
worst-case drain to Σ grant·cap per window regardless of attacker effort (doc §6).
"""
from execnode import zkvmasm, runtimes

OPERATOR = "ndoebd27698662f14ee2389e509781d5ff57487f4289a2bf2"   # the game-fleet deployer key
OP_DIG = runtimes.zkvm_addr_digest(OPERATOR)

GDIG, GGRANT, GCAP, GPOW, GUSED = 10, 11, 12, 13, 20
DAY_BLOCKS = 14400            # budget window: ~one day at 6s blocks

# fund(): anyone may top the faucet up exec-side (the call's VALUE is escrowed to this contract by the
# call machinery itself before the method runs — this body only insists there IS a value).
FUND = """
    ctx r1 value
    movi r2 0
    lt r2 r1
    require r2              ; value > 0
    ret r0
"""

# set_game(idx, dig, grant, cap, pow): operator-only registry write; grant=0 pauses the slot.
SET_GAME = f"""
    ctx r5 caller
    movi r6 {OP_DIG}
    eq r5 r6
    require r5              ; operator only
    slot r6 {GDIG} r0
    sstore r6 r1
    slot r6 {GGRANT} r0
    sstore r6 r2
    slot r6 {GCAP} r0
    sstore r6 r3
    slot r6 {GPOW} r0
    sstore r6 r4
    movi r6 0
    sload r5 r6             ; r5 = gcnt (raw slot 0)
    mov r7 r0
    movi r2 1
    add r7 r2               ; r7 = idx + 1
    mov r2 r5
    lt r2 r7                ; r2 = (gcnt < idx+1)
    mov r1 r7
    sub r1 r5               ; r1 = idx+1 - gcnt   (mod P; only used when the flag is 1)
    mul r1 r2
    add r5 r1               ; gcnt = max(gcnt, idx+1), branchless
    sstore r6 r5
    ret r0
"""

# claim(idx, nonce): the player path. r0 = idx, r1 = ground nonce.
CLAIM = f"""
    slot r4 {GGRANT} r0
    sload r2 r4             ; r2 = grant
    movi r5 0
    lt r5 r2
    require r5              ; enrolled & granting
    ctx r3 caller
    hash r5 <- r3 r0 r1
    slot r4 {GPOW} r0
    sload r6 r4
    lt r5 r6
    require r5              ; proof of work: alghash(caller, idx, nonce) < target
    hash r6 <- r3 r0        ; the (caller, game) claimed-marker's raw storage key
    sload r5 r6
    nez r5
    notb r5
    require r5              ; first claim for this (address, game)
    movi r5 1
    sstore r6 r5            ; mark claimed
    ctx r5 cursor
    movi r6 {DAY_BLOCKS}
    divmodw r5 r6           ; r5 = day window (divisor < 2^31, quotient < 2^32: both in budget)
    movi r6 1048576
    mov r4 r0
    mul r4 r6
    add r4 r5               ; idx·2^20 + window
    movi r6 {GUSED << 32}
    add r4 r6               ; gused storage key
    sload r5 r4             ; r5 = used this window
    slot r6 {GCAP} r0
    sload r7 r6             ; r7 = cap
    mov r6 r5
    lt r6 r7
    require r6              ; used < cap
    movi r6 1
    add r5 r6
    sstore r4 r5            ; used++
    pay r3 r2               ; the grant — the runtime reverts the whole call if the faucet can't cover it
    ret r0
"""

SRC = {"fund": FUND, "set_game": SET_GAME, "claim": CLAIM}

ABI = {
    "fund": {"args": [], "value": True},
    "set_game": {"args": ["idx", "dig", "grant", "cap", "pow"]},
    "claim": {"args": ["idx", "nonce"]},
    "_view": {
        "maps": {"gdig": GDIG, "ggrant": GGRANT, "gcap": GCAP, "gpow": GPOW, "gused": GUSED},
        "index": {"cnt": 0, "range": True},
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)

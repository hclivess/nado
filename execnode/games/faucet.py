"""
Faucet — the fixed-name PRIZE BANK (doc/faucet.md). Holds donations sent to the L1 reserved address
`faucet` (the exec node credits them to this contract's balance — its cid IS the literal string
"faucet", see execnode.state.FIXED_CIDS) plus governance top-ups, and pays DAILY LEADERBOARD PRIZES
for airdrop play: the operator's distributor (_faucet_rewards.py) tallies each enrolled game's
scoreboard off-chain (a provable computation anyone can recompute from the game contracts' storage)
and calls `reward` per top finisher.

There is deliberately NO self-serve claim path — no PoW grind, no per-address grants, no enrollment
registry. Play the free airdrop games, place on the scoreboard, get paid.

Methods: fund()[value] · reward(idx, day, rank, addr, amount) — operator-only, at most once per
(game, day, rank) via the H(idx, day, rank) idempotency marker; an underfunded payout reverts ·
defund(amount) — operator-only, capped at the operator's OWN donations minus what was already taken
back (slots 7/8), so treasury money in the faucet can never be withdrawn by anyone.
"""
from execnode import zkvmasm, runtimes
from ops.address_ops import make_address

# The game-fleet deployer key, identified by its PUBLIC-KEY BODY rather than a pinned address string.
# This gate was previously a hardcoded "ndo…" address; the betanet-7 debrand moved the operator to
# "mldsa44…", so the digest baked into `reward` stopped matching the caller and EVERY prize payout
# reverted on the operator-only require — the faucet could not pay a single scoreboard winner. Deriving
# the address through make_address() means a future prefix change follows the one-constant rebrand point
# automatically instead of silently bricking payouts again. (Re-derivation is deterministic, so the
# assembled code is stable for a given prefix.)
OPERATOR_PUBKEY = "ebd27698662f14ee2389e509781d5ff57487f4289a"
OPERATOR = make_address(OPERATOR_PUBKEY)
OP_DIG = runtimes.zkvm_addr_digest(OPERATOR)

# fund(): anyone may top the prize bank up exec-side (the call's VALUE is escrowed to this contract by
# the call machinery itself before the method runs — this body only insists there IS a value).
# Slot 7 = DONATED: NADO the OPERATOR put in (exec-side fund() by the operator, and L1 donations the exec
# node mirrors); slot 8 = DEFUNDED: what defund() has taken back. Treasury top-ups touch neither, which is
# exactly what makes defund() unable to reach public money. Small integer keys cannot collide with the
# reward markers, which are alghash outputs.
DONATED, DEFUNDED = 7, 8

FUND = f"""
    ctx r1 value
    movi r2 0
    lt r2 r1
    require r2              ; value > 0
    ctx r5 caller
    movi r6 {OP_DIG}
    eq r5 r6
    jnz r5 @rec
    ret r0
rec:
    movi r6 {DONATED}
    sload r7 r6
    add r7 r1               ; DONATED += value (operator's own money, take-backable)
    sstore r6 r7
    ret r0
"""

# defund(amount): the OPERATOR takes back some of what the operator put in — never more than
# DONATED - DEFUNDED, so treasury payouts into the faucet (public money) can never leave through here.
# Auditable on chain: slot 7 is what went in, slot 8 what came back out.
DEFUND = f"""
    ctx r5 caller
    movi r6 {OP_DIG}
    eq r5 r6
    require r5              ; operator only
    movi r2 0
    lt r2 r0
    require r2              ; amount > 0
    movi r6 {DONATED}
    sload r3 r6             ; DONATED
    movi r6 {DEFUNDED}
    sload r4 r6             ; DEFUNDED
    add r4 r0               ; DEFUNDED' = DEFUNDED + amount
    gte r3 r4               ; DONATED >= DEFUNDED'
    require r3              ; never more than the operator's own donations
    movi r6 {DEFUNDED}
    sstore r6 r4
    movi r1 {OP_DIG}
    pay r1 r0               ; back to the operator (reverts if the faucet cannot cover it)
    ret r0
"""

# reward(idx, day, rank, addr, amount): pay a LEADERBOARD PLACEMENT prize from the faucet balance.
# Operator-only. IDEMPOTENT: a (game, day, rank) can be paid AT MOST ONCE — a re-run of the
# distributor reverts the already-paid ranks (no double payout). Underfunded → the runtime reverts
# the pay (fails closed).
REWARD = f"""
    ctx r5 caller
    movi r6 {OP_DIG}
    eq r5 r6
    require r5             ; operator only
    hash r6 <- r0 r1 r2    ; idempotency key = H(idx, day, rank)
    sload r5 r6
    nez r5
    notb r5
    require r5            ; not already paid for this (game, day, rank)
    movi r5 1
    sstore r6 r5          ; mark this placement paid
    pay r3 r4            ; pay the winner from the faucet balance (reverts if the faucet can't cover it)
    ret r0
"""

SRC = {"fund": FUND, "reward": REWARD, "defund": DEFUND}

ABI = {
    "fund": {"args": [], "value": True},
    "reward": {"args": ["idx", "day", "rank", "addr", "amount"]},
    "defund": {"args": ["amount"]},
    "_view": {"maps": {"donated": DONATED, "defunded": DEFUNDED}, "index": {"cnt": 0, "list": 0}},
}


def build():
    return zkvmasm.assemble_contract(SRC)

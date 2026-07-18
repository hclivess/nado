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
(game, day, rank) via the H(idx, day, rank) idempotency marker; an underfunded payout reverts.
"""
from execnode import zkvmasm, runtimes

OPERATOR = "ndoebd27698662f14ee2389e509781d5ff57487f4289a2bf2"   # the game-fleet deployer key
OP_DIG = runtimes.zkvm_addr_digest(OPERATOR)

# fund(): anyone may top the prize bank up exec-side (the call's VALUE is escrowed to this contract by
# the call machinery itself before the method runs — this body only insists there IS a value).
FUND = """
    ctx r1 value
    movi r2 0
    lt r2 r1
    require r2              ; value > 0
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

SRC = {"fund": FUND, "reward": REWARD}

ABI = {
    "fund": {"args": [], "value": True},
    "reward": {"args": ["idx", "day", "rank", "addr", "amount"]},
}


def build():
    return zkvmasm.assemble_contract(SRC)

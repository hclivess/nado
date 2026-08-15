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
set_operator(addr_digest) — hand the payout right to another key.

OPERATOR IS STATE, NOT CODE. The gate used to be a digest assembled into `reward` itself, which made the
key un-rotatable without an `upgrade`, invisible on-chain (you had to disassemble to see who could spend),
and — on a contract that was ever `lock`ed — bound to that one key permanently, with no way back even for
its owner. It now lives in a storage slot that `set_operator` rotates, so separating the operator key from
the node/staking key is an ordinary transaction rather than a code change. Contract OWNERSHIP was already
transferable (state.transfer_contract keeps cid + storage); this closes the matching gap for the SPENDING
right, so the two can be split and moved independently.

Unset reads as the deploy-time key, so an already-deployed faucet keeps working across the upgrade with no
migration step and no window where nobody can pay.
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
# Config slot for the operator digest. Payout markers live at H(idx, day, rank), so a small integer slot
# is only as safe as "no alghash output equals 1" — the same collision assumption the idempotency scheme
# already rests on (distinct triples must not share a slot), not a new one.
SLOT_OPERATOR = 1

# Resolve the operator into r5: the configured slot, or the deploy-time key when it was never set.
# Inlined into both methods — the VM has no calls, and eight instructions is cheaper than any alternative.
# r5 is free again the moment the caller check passes, so this costs no extra register (there are 8, and
# r7 is the DIVMOD remainder).
def _load_operator():
    return f"""
    movi r5 {SLOT_OPERATOR}
    sload r5 r5            ; r5 = configured operator digest (0 = never set)
    jnz r5 @have_op
    movi r5 {OP_DIG}       ; bootstrap: the key that deployed it
have_op:
"""

# reward(idx, day, rank, addr, amount): pay a LEADERBOARD PLACEMENT prize from the faucet balance.
# Operator-only. IDEMPOTENT: a (game, day, rank) can be paid AT MOST ONCE — a re-run of the
# distributor reverts the already-paid ranks (no double payout). Underfunded → the runtime reverts
# the pay (fails closed).
REWARD = _load_operator() + """
    ctx r6 caller
    eq r6 r5
    require r6             ; operator only
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

# set_operator(digest): hand the payout right to another key. Only the CURRENT operator may do it, so the
# deploy-time key can pass the role on once and never hold it again. Zero is REFUSED: storing it would read
# as "unset" and silently restore the bootstrap key, turning a handover into a takeback. The non-zero check
# is `nez` on a copy rather than `lt`, because `lt` RANGE-checks its operands below 2^62 and an address
# digest is a full-field element that can exceed that — a comparison would revert on legitimate keys.
SET_OPERATOR = _load_operator() + f"""
    ctx r6 caller
    eq r6 r5
    require r6             ; only the current operator may rotate
    mov r6 r0
    nez r6
    require r6             ; new digest must be non-zero (0 would read as "unset")
    movi r5 {SLOT_OPERATOR}
    sstore r5 r0
    ret r0
"""

SRC = {"fund": FUND, "reward": REWARD, "set_operator": SET_OPERATOR}

ABI = {
    "fund": {"args": [], "value": True},
    "reward": {"args": ["idx", "day", "rank", "addr", "amount"]},
    "set_operator": {"args": ["digest"]},
}


def build():
    return zkvmasm.assemble_contract(SRC)

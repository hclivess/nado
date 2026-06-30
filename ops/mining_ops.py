"""
mining_ops.py — bonded-registry producer selection + the commit-reveal RANDAO beacon (S4).

These are the consensus-critical CORE of the open/mobile mining redesign, written as pure,
deterministic, integer-only functions so they are trivially reproducible (including by a
browser light-miner) and unit-testable without any networking. The on-chain plumbing that
feeds them (recording bonds, commits and reveals in blocks; penalising withholders; wiring
select_producer into block production/verification) is the S4.3 integration layer.

Design (from the red-teamed "Option A" hybrid):
  - Sybil cost = locked refundable BOND, not a public IP. Selection weight is SPLIT-NEUTRAL:
    shares = min(bonded, BOND_CAP) // B_MIN, so sharding capital across many addresses gives
    exactly zero advantage, and the cap stops a whale from monopolising selection.
  - Randomness = a commit-reveal RANDAO beacon contributed by always-on bonded participants and
    CHAINED with the previous beacon, so it cannot be ground by the previous producer (the
    grindable parent_block_hash seed — audit M6 — is abandoned) and a single withholder gets at
    most one bit of influence (and is penalised at the integration layer). Entry (bond) must be
    committed BEFORE the epoch beacon is revealed, which also kills just-in-time bond grinding.
  - An Ed25519 signature is NEVER used as the randomness (Curve25519.verify accepts non-unique
    (R,S) and would be grindable); signing stays only for authenticating heartbeats/reveals.
"""
from hashing import blake2b_hash
from protocol import (B_MIN, BOND_CAP, EPOCH_LENGTH, FIDELITY_CAP,
                      K_OPEN, OPEN_BASE_FLOOR, OPEN_FID_BONUS, REGISTER_POW_BITS)


def epoch_of(block_number: int) -> int:
    return block_number // EPOCH_LENGTH


def selection_shares(bonded: int, fidelity=None) -> int:
    """Split-neutral, capped selection weight for a bonded identity.

    shares = min(bonded, BOND_CAP) // B_MIN  (0 if under the minimum bond).
    Optional fidelity ramp (anti-whale time dimension): a newcomer's weight ramps linearly to
    full over FIDELITY_CAP epochs of continuous presence, so an instant whale cannot buy its
    full proportional share on day one. fidelity=None disables the ramp (full weight)."""
    if bonded < B_MIN:
        return 0
    shares = min(bonded, BOND_CAP) // B_MIN
    if fidelity is not None and fidelity < FIDELITY_CAP:
        shares = shares * fidelity // FIDELITY_CAP
    return shares


def total_shares(registry: dict) -> int:
    return sum(selection_shares(info["bonded"], info.get("fidelity")) for info in registry.values())


def total_bonded_shares(bonded_registry: dict) -> int:
    """Fork-choice CHAIN-WEIGHT contribution of one block (#16/#17 step 2): the TOTAL bonded selection
    capacity of the registry as-of-the-block's-PARENT, summed as pure committed stake (NO fidelity
    ramp) so it is a stable, grind-proof, integer measure. Per identity: min(bonded,BOND_CAP)//B_MIN
    (== capped at MAX_SHARES). Deliberately the TOTAL registry weight, NOT the slot winner's share —
    that makes cumulative_weight BEACON-INDEPENDENT (a proposer cannot grind the beacon to inflate
    fork weight) and removes any self-bond-on-a-private-fork leverage. Browser-reproducible (integer
    only). fidelity is intentionally excluded so the weight does not drift with presence ramps."""
    return sum(selection_shares(info.get("bonded", 0)) for info in bonded_registry.values())


def select_producer(registry: dict, beacon: str, slot: int):
    """Deterministic split-neutral weighted draw of the producer for `slot`.

    registry: {address: {"bonded": int, "fidelity": int|absent}}
    beacon:   the epoch RANDAO beacon (hex string)
    Returns the winning address, or None if no eligible bonded identity exists.
    Integer-only and canonical (addresses walked in sorted order) so every node and a browser
    client compute the identical winner."""
    weighted = []
    total = 0
    for address in sorted(registry):
        shares = selection_shares(registry[address]["bonded"], registry[address].get("fidelity"))
        if shares > 0:
            weighted.append((address, shares))
            total += shares
    if total == 0:
        return None

    draw = int(blake2b_hash([beacon, slot]), 16) % total
    cumulative = 0
    for address, shares in weighted:
        cumulative += shares
        if draw < cumulative:
            return address
    return weighted[-1][0]  # unreachable (draw < total), defensive


# --- commit-reveal RANDAO beacon ---------------------------------------------------------

def beacon_commitment(reveal_secret: str) -> str:
    """commitment published in the commit phase; binds the secret without revealing it"""
    return blake2b_hash(["nado-randao-commit", reveal_secret])


def verify_reveal(commitment: str, reveal_secret: str) -> bool:
    return beacon_commitment(reveal_secret) == commitment


def compute_beacon(prev_beacon: str, revealed_secrets: list) -> str:
    """Combine the revealed secrets for an epoch into the next beacon, CHAINED with the previous
    beacon so a single party cannot dictate the outcome. Secrets are sorted for determinism;
    withheld (committed-but-not-revealed) secrets are simply absent here and are penalised at the
    integration layer. With zero reveals the beacon still advances deterministically off
    prev_beacon (liveness), at the cost of that one epoch being lower-entropy."""
    return blake2b_hash(["nado-randao-beacon", prev_beacon, sorted(revealed_secrets)])


# --- two-lane selection: OPEN (free) lane + BONDED (stake) lane -------------------------------

def lane_of(slot: int, beacon: str) -> str:
    """Which lane owns this slot: "open" or "bonded".

    The EPOCH_LENGTH slots of an epoch are split by a beacon-keyed permutation: the K_OPEN slots
    whose blake2b([beacon,"lane",j]) rank lowest are OPEN, the rest are BONDED. Because the split
    is a permutation of slot INDICES — not a per-identity weight — the open lane is EXACTLY K_OPEN
    slots/epoch no matter how many identities register, so a zero-capital Sybil/botnet can never
    win more than OPEN_BPS of blocks. Integer-only and canonical (browser-reproducible)."""
    i = slot % EPOCH_LENGTH
    order = sorted(range(EPOCH_LENGTH), key=lambda j: (int(blake2b_hash([beacon, "lane", j]), 16), j))
    return "open" if i in order[:K_OPEN] else "bonded"


def open_shares(fidelity) -> int:
    """OPEN-lane selection weight for a registered, present identity: a flat floor every newcomer
    gets (so a zero-coin miner is ALWAYS winnable, never scaled to 0) plus a diligence bonus that
    ramps to full over FIDELITY_CAP epochs of continuous presence. Range OPEN_BASE_FLOOR ..
    OPEN_BASE_FLOOR+OPEN_FID_BONUS (1..10). NOT money-weighted — this lane is capital-FREE, so no
    whale can buy advantage in it."""
    f = 0 if fidelity is None or fidelity < 0 else fidelity
    return OPEN_BASE_FLOOR + min(f, FIDELITY_CAP) * OPEN_FID_BONUS // FIDELITY_CAP


def _bonded_shares(info: dict) -> int:
    return selection_shares(info["bonded"], info.get("fidelity"))


def _open_weight(info: dict) -> int:
    return open_shares(info.get("fidelity"))


def _weighted_draw(registry: dict, weight_fn, beacon: str, slot: int):
    """Deterministic weighted draw shared by both lanes: walk addresses in canonical SORTED order,
    accumulate integer weights, pick the band the beacon/slot hash lands in. Returns the winning
    address, or None if no positive-weight identity exists. Identical on every node + browser."""
    weighted = []
    total = 0
    for address in sorted(registry):
        w = weight_fn(registry[address])
        if w > 0:
            weighted.append((address, w))
            total += w
    if total == 0:
        return None
    draw = int(blake2b_hash([beacon, slot]), 16) % total
    cumulative = 0
    for address, w in weighted:
        cumulative += w
        if draw < cumulative:
            return address
    return weighted[-1][0]  # unreachable (draw < total), defensive


def select_producer_two_lane(open_registry: dict, bonded_registry: dict, beacon: str, slot: int):
    """The live two-lane producer selector. Returns the winning address, or None if the slot is
    skipped (no eligible producer).

    lane_of(slot) decides which registry is drawn. Empty-lane policy is ONE-DIRECTIONAL and
    fail-closed for Sybil safety:
      - OPEN slot, open lane empty   -> fall back to the BONDED lane (only ever lets the safe
        capital lane over-produce; never a Sybil risk).
      - BONDED slot, bonded lane empty -> SKIP the slot. NEVER fall back to open, because letting
        the free lane absorb bonded slots would break the OPEN_BPS Sybil ceiling.
    The winner is credited by ADDRESS, so it need not be online (a relay builds the block for it)."""
    if lane_of(slot, beacon) == "open":
        winner = _weighted_draw(open_registry, _open_weight, beacon, slot)
        if winner is not None:
            return winner
        return _weighted_draw(bonded_registry, _bonded_shares, beacon, slot)  # one-directional fallback
    return _weighted_draw(bonded_registry, _bonded_shares, beacon, slot)


# --- open-lane registration proof-of-work (one-time, fee-substitute, phone-doable) -----------

def registration_pow_target() -> int:
    """Fixed difficulty: a valid hash must be below 2**(256 - REGISTER_POW_BITS)."""
    return 1 << (256 - REGISTER_POW_BITS)


def registration_pow_hash(address: str, nonce) -> int:
    return int(blake2b_hash(["nado-register", address, nonce]), 16)


def verify_registration_pow(address: str, nonce) -> bool:
    """A fresh, zero-balance address proves a one-time light PoW INSTEAD of paying the fee it
    cannot afford. Fixed difficulty (REGISTER_POW_BITS): a few seconds on a phone, ONCE ever. This
    is NOT an ongoing mining race — the lane cap, not this puzzle, is what bounds Sybils; the PoW
    only throttles free-registration bursts and substitutes for the unaffordable fee."""
    return registration_pow_hash(address, nonce) < registration_pow_target()


def solve_registration_pow(address: str, start: int = 0, limit: int = 1 << 30):
    """Helper for the wallet / browser light-miner and tests: find an integer nonce satisfying the
    registration PoW. Deterministic. Returns the nonce, or None if none found within `limit`."""
    target = registration_pow_target()
    nonce = start
    end = start + limit
    while nonce < end:
        if registration_pow_hash(address, nonce) < target:
            return nonce
        nonce += 1
    return None

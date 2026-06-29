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
from protocol import B_MIN, BOND_CAP, EPOCH_LENGTH, FIDELITY_CAP


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

"""
protocol.py — single source of truth for NADO protocol / economic / mining constants.

No live network exists, so these define the relaunch genesis behaviour DIRECTLY: there
are no fork-height activation gates. Everything here is consensus-critical and must be
identical on every node (and reproducible by a browser light-miner), so keep it to plain
ints/strings and pure functions with no imports from `ops` (this module must stay a leaf
so anything can import it without a cycle).
"""
from hashing import blake2b_hash  # leaf module (stdlib only) -> no import cycle

# Bound into every signed transaction and block body so a transaction/block from another
# chain (or the pre-relaunch chain) can never replay here (closes audit item M3).
CHAIN_ID = "nado-relaunch-1"

# 1 NADO in raw (smallest) units. All on-chain amounts are integers in raw units.
DENOMINATION = 10_000_000_000  # 1e10

GENESIS_TIMESTAMP = 1669852800

# --- Reserved, keyless protocol pseudo-addresses (no private key) ---
# "burn"        : destroys coins (burn-to-bribe / deflation), as today.
# "bond"/"unbond": pseudo-recipients used by the bonding transactions (see S4).
BURN_ADDRESS = "burn"
RESERVED_RECIPIENTS = frozenset({"burn", "bond", "unbond"})

# The TREASURY is the GENESIS address (project owner's decision): the 10% per-block cut accrues
# here and the genesis bootstrap allocation is minted here. It is a normal KEY-CONTROLLED address
# (the founder holds its key), derived here under the canonical (new) checksum from the genesis
# public-key body so it validates. NOTE: because it is key-controlled, the TREASURY_GENESIS seed
# below is effectively a founder allocation; set TREASURY_GENESIS = 0 for a pure no-coins start.
_GENESIS_BODY = "ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80"  # "ndo" + genesis public_key[:42]
GENESIS_ADDRESS = _GENESIS_BODY + blake2b_hash(_GENESIS_BODY, size=2)
TREASURY_ADDRESS = GENESIS_ADDRESS

# --- Block reward: fee-weighted elastic, split producer/treasury (no premine) ---
TREASURY_BPS = 1000          # treasury share of each block reward, in basis points (10.00%)
BPS_DENOM = 10000
REWARD_WINDOW = 100          # trailing blocks averaged for the elastic reward
REWARD_CAP = 5_000_000_000   # max reward per block (0.5 NADO), raw

# Bootstrap allocation minted to the keyless "treasury" address at genesis (NOT a personal
# premine). It seeds the onboarding faucet (starter bonds) so a brand-new bonded chain can
# start moving coins -> paying fees -> earning the fee-weighted reward. The treasury also
# accrues TREASURY_BPS of every block reward. Provisional; flagged for owner confirmation.
TREASURY_GENESIS = 1_000_000_000_000_000_000  # 1e18 raw = 100,000,000 NADO

# --- Fees ---
# Deterministic integer floor (anti-spam). Intentionally NOT the byte-size "base fee":
# get_byte_size() == sys.getsizeof(repr(x)) is non-deterministic across Python builds and
# would be a consensus hazard. Tunable; provisional pending economic simulation.
MIN_TX_FEE = 1000

# --- Mining: bonded registry + fidelity + split-neutral cap (PROVISIONAL — simulate before lock-in) ---
B_MIN = 1_000_000_000_000          # 100 NADO: capital per selection share
BOND_CAP = 100_000_000_000_000     # 10,000 NADO: max effective bond per identity
MAX_SHARES = BOND_CAP // B_MIN     # 100: variance cap so a whale can't monopolise selection
BOND_UNLOCK_DELAY = 1440           # blocks a bond stays locked after an unbond request
EPOCH_LENGTH = 60                  # slots per beacon (RANDAO) epoch
FAUCET_STARTER_BOND = B_MIN        # treasury-funded starter bond for a fresh address (S4)

# automated fidelity / continuity (signed software heartbeats — NO manual ceremony, NOT IDENA-style)
FIDELITY_CAP = 1000
FIDELITY_GAIN = 1                  # per epoch present
FIDELITY_DECAY = 2                 # per epoch absent (continuity costs more to fake than to keep)


def split_block_reward(reward: int):
    """Canonical 90/10 producer/treasury split. Returns (producer_cut, treasury_cut) that
    sum to EXACTLY `reward` (one floor + remainder — never two independent floors, which
    could lose a unit and desync incorporate vs rollback). Must be used by both the apply
    and the rollback paths so the two subtract identical integers."""
    producer_cut = reward * (BPS_DENOM - TREASURY_BPS) // BPS_DENOM
    treasury_cut = reward - producer_cut
    return producer_cut, treasury_cut

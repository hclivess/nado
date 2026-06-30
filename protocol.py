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
# "bond"/"unbond": pseudo-recipients used by the bonding transactions (see S4).
# (The "burn" mechanic was removed entirely: no burn address, no burned counter, no
#  burn-to-bribe. Fees are still destroyed — that is the separate fee mechanic, not "burn".)
# "bond"/"unbond": bonded-lane stake txs. "register"/"heartbeat": OPEN-lane (no-coin) mining txs
# (see the two-lane mining design in doc/mining.md). All are keyless protocol pseudo-recipients.
RESERVED_RECIPIENTS = frozenset({"bond", "unbond", "withdraw", "register", "heartbeat", "slash", "attest", "commit", "reveal"})

# The TREASURY is the GENESIS address (project owner's decision): the 10% per-block cut accrues
# here. It is a normal KEY-CONTROLLED address (the founder holds its key), derived here under the
# canonical (new) checksum from the genesis public-key body so it validates. It starts EMPTY —
# there is NO genesis allocation (TREASURY_GENESIS = 0 below); it only fills from the per-block cut.
_GENESIS_BODY = "ndo27f2870bb2969a4d2b9d4eea303bedea996b9ccc93"  # founder treasury (ML-DSA addr minus 4-hex checksum); owner-controlled
GENESIS_ADDRESS = _GENESIS_BODY + blake2b_hash(_GENESIS_BODY, size=2)
TREASURY_ADDRESS = GENESIS_ADDRESS

# --- Block reward: base subsidy + fee-weighted elastic, split producer/treasury (NO premine) ---
TREASURY_BPS = 1000          # treasury share of each block reward, in basis points (10.00%)
BPS_DENOM = 10000
REWARD_WINDOW = 100          # trailing blocks averaged for the elastic reward
REWARD_CAP = 5_000_000_000   # max reward per block (0.5 NADO), raw
# Flat per-block emission FLOOR, independent of fees. Without it a no-premine chain deadlocks:
# 0 coins -> 0 fees -> fee-weighted reward 0 forever -> no coins are ever minted. The base subsidy
# lets a zero-coin OPEN-lane miner earn real spendable coins from block 1; those circulate, pay
# fees, and the elastic component rises on top up to REWARD_CAP. This is the fair-launch emission
# (every fair-launch coin has a block subsidy). Tunable; a halving schedule is future work.
BASE_SUBSIDY = 1_000_000_000  # 0.1 NADO/block raw floor (~144 NADO/day at 60s blocks: 1440 blocks * 0.1)

# NO PREMINE (owner decision 2026-06-30): genesis mints ZERO coins. No founder allocation, no
# treasury seed. A fresh chain bootstraps purely through the OPEN mining lane (register for free,
# earn the BASE_SUBSIDY) — not a pre-funded balance. The treasury still accrues TREASURY_BPS of
# every block reward going forward; it just starts empty. (Set >0 only to reintroduce a premine.)
TREASURY_GENESIS = 0  # no premine — fair launch via the open lane + base subsidy

# --- Fees ---
# Deterministic integer floor (anti-spam). Intentionally NOT the byte-size "base fee":
# get_byte_size() == sys.getsizeof(repr(x)) is non-deterministic across Python builds and
# would be a consensus hazard. Tunable; provisional pending economic simulation.
MIN_TX_FEE = 1000

# --- Mining: TWO-LANE diligence selection (PROVISIONAL — simulate before lock-in) ---
# Each epoch's slots split into an OPEN lane (anyone, zero coins) and a BONDED lane (locked stake).
# The split is a beacon-keyed permutation over slot indices, so the open lane is EXACTLY OPEN_BPS
# of blocks regardless of how many identities exist -> a zero-capital Sybil/botnet is structurally
# bounded to OPEN_BPS of production. See doc/mining.md and ops/mining_ops.py.
EPOCH_LENGTH = 60                  # slots per epoch (also the beacon/RANDAO epoch)
OPEN_BPS = 2000                    # SECURITY DIAL: open-lane share of slots (20.00%); Sybil ceiling
K_OPEN = EPOCH_LENGTH * OPEN_BPS // BPS_DENOM  # open slots per epoch (rest bonded); =12 at defaults

# ENFORCED FINALITY (#17, security step 1): a block at height H finalizes everything at/below
# H - FINALITY_DEPTH; rollback_one_block REFUSES to cross the persisted monotonic finalized_height
# (raises FinalityViolation). The ordering max_rollbacks(10) < FINALITY_DEPTH < EPOCH_LENGTH(60) <
# PRESENCE_WINDOW*EPOCH_LENGTH(180) guarantees: an honest reorg (<= max_rollbacks deep) never hits
# the floor; a malicious/long-range reorg is capped below one epoch so the epoch-beacon anchor is
# un-reorgable; and the heartbeat-GC of pre-presence-window epochs is provably safe.
FINALITY_DEPTH = 30

# Bonded lane: locked refundable stake, split-neutral, per-identity capped.
B_MIN = 1_000_000_000_000          # 100 NADO: capital per bonded selection share
BOND_CAP = 100_000_000_000_000     # 10,000 NADO: max effective bond per identity
MAX_SHARES = BOND_CAP // B_MIN     # 100: variance cap so a whale can't monopolise the bonded lane
BOND_UNLOCK_DELAY = 1440           # blocks a bond stays locked after an unbond request
# SLASHING (#15/#16 step 5C/6): bonded stake burned from an identity proven to have EQUIVOCATED — two
# validly-signed blocks at the same height+parent (block authorship #15), or a double/surround vote
# in the FFG attestation set (#6). One share (B_MIN) per proven offence; validation requires the
# offender hold >= SLASH_BOND_PENALTY bonded so apply never floors (revert-symmetric). Burned, not
# paid to the reporter (the deterrent is the loss). One slash per (offender, height) — replay-guarded.
SLASH_BOND_PENALTY = B_MIN

# FFG-LITE OBJECTIVE FINALITY (#6): bonded validators ATTEST the first block of each epoch (the
# "checkpoint"). A checkpoint JUSTIFIES when the attesting bonded shares exceed FFG_NUM/FFG_DEN of the
# total bonded shares; it FINALIZES (with slashable stake backing) once it AND its child checkpoint are
# both justified (two-consecutive). This is ADDITIVE + OBSERVABLE: it records the stake-attested
# finalized checkpoint as /status.ffg_finalized but does NOT move the rollback-bounding finalized_height
# (that stays the deeper time-based floor, #17, which guarantees liveness) — so FFG can never stall the
# chain. On-chain UNIQUE(validator, target_epoch) — enforced by the attestation index — prevents on-chain
# double-voting, so only one attestation per validator per epoch ever counts. finalized_height stays
# monotonic (max of the time-based floor and the FFG height), so the advance needs no rollback logic.
FFG_NUM = 2
FFG_DEN = 3

# Open lane: free entry via a one-time light registration PoW; weight = floor + diligence ramp.
# NO auto-bond faucet: free presence must NEVER mint bonded stake (that pipe lets a Sybil swarm
# reach stake majority for ~0 capital — it broke the rejected fronted/faucet designs). The only
# free->capital path is the block reward an open-lane miner actually earns (itself OPEN_BPS-capped).
REGISTER_POW_BITS = 16             # one-time light registration puzzle (~1s in pure-JS blake2b on a phone;
                                   # 22 bits took tens of seconds in-browser). NOT the Sybil defense —
                                   # the lane cap is — this only throttles trivial mempool spam.
OPEN_BASE_FLOOR = 1                # every registered+present identity's minimum open weight (never 0)
OPEN_FID_BONUS = 9                 # max diligence bonus: open weight ranges OPEN_BASE_FLOOR..+9 (1..10)
PRESENCE_WINDOW = 3                # epochs: an open identity needs a heartbeat within this to stay weighted
GC_IDLE_EPOCHS = 1000              # prune registry rows idle this long (bounds state bloat)

# automated fidelity / continuity (signed software heartbeats — NO manual ceremony, NOT IDENA-style)
FIDELITY_CAP = 1000                # epochs of continuous presence to fully ramp the open bonus
FIDELITY_GAIN = 1                  # per epoch present
FIDELITY_DECAY = 1                 # per epoch absent (== gain: mobile-friendly; fidelity is only a
                                   # ~10x booster, NOT the Sybil bound, so harsh anti-churn is harmful)

# Seed for the per-epoch selection beacon (S4.3). Epochs 0-1 use this fixed constant directly
# (no finalized prior epoch exists yet); epoch>=2 chains it with the hash of the first block of
# the previous epoch (see block_ops.epoch_beacon). Replacing this with the full on-chain
# commit-reveal RANDAO is the hardening step (mining_ops.compute_beacon already implements it).
GENESIS_BEACON = blake2b_hash(["nado-genesis-beacon", CHAIN_ID])


def split_block_reward(reward: int):
    """Canonical 90/10 producer/treasury split. Returns (producer_cut, treasury_cut) that
    sum to EXACTLY `reward` (one floor + remainder — never two independent floors, which
    could lose a unit and desync incorporate vs rollback). Must be used by both the apply
    and the rollback paths so the two subtract identical integers."""
    producer_cut = reward * (BPS_DENOM - TREASURY_BPS) // BPS_DENOM
    treasury_cut = reward - producer_cut
    return producer_cut, treasury_cut

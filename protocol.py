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
# "bond"/"unbond": bonded-lane stake txs. "register": the OPEN-lane (no-coin) mining lease tx
# (see the two-lane mining design in doc/mining.md). All are keyless protocol pseudo-recipients.
RESERVED_RECIPIENTS = frozenset({"bond", "unbond", "withdraw", "register", "slash", "attest", "commit", "reveal", "alias", "blob", "settle", "bridge", "bridge_withdraw", "dividend", "dividend_withdraw", "htlc", "htlc_lock", "htlc_claim", "htlc_refund", "shield", "unshield", "treasury", "treasury_vote", "treasury_execute"})

# --- SHIELDED POOL (post-quantum zk-STARK privacy, doc/privacy.md) — L1 side of an EXECUTION-LAYER feature ---
# L1 never sees a note or verifies a proof; it only escrows the transparent coins that enter/leave the pool
# and orders the shielded data for the execution node (which maintains the pool + verifies proofs).
#   "shield":   DEPOSIT — move amount(+fee) from sender, LOCK `amount` in SHIELD_ESCROW, and carry the output
#               note commitments in tx.data (opaque to L1). The exec node adds them to the pool.
#   (private transfer): a plain "blob" tx carrying {op:"shielded_transfer", public, proof} — L1 just orders +
#               burns the DA fee; no L1 balance moves (coins stay in the pool). The exec node applies it.
#   "unshield": EXIT — prove (Merkle inclusion) a withdrawal {addr, amount, nonce} is in the bonded-quorum
#               SETTLED exec-state root; L1 verifies that ONE proof, checks the nullifier, and releases the
#               escrowed coins — identical trust-minimised path as the bridge/dividend exit.
SHIELD_ESCROW = "shield"          # keyless escrow pseudo-account holding all shielded (pooled) L1 coins

# --- HTLC (Hash Time-Locked Contracts) for trustless CROSS-CHAIN atomic swaps (doc/htlc.md) ---
# A lock escrows `amount` under a SHA-256 hashlock + an absolute block-height timelock:
#   "htlc_lock"   — move amount(+fee) from sender, lock `amount` in HTLC_ESCROW, record {claimant, hashlock,
#                   expiry}. The lock's txid is its HTLC id.
#   "htlc_claim"  — the claimant reveals `preimage`; iff sha256(preimage)==hashlock AND height < expiry, the
#                   escrow releases to the claimant. Revealing the preimage on-chain is the swap's linchpin.
#   "htlc_refund" — after `expiry`, the original sender reclaims an unclaimed lock from escrow.
# SHA-256 is the cross-chain lingua franca (BTC/ETH HTLCs use it), so the SAME hashlock works on both chains:
# claiming here publishes the preimage, which the counterparty uses to claim the mirrored lock on the other
# chain — an atomic swap with no bridge, no custodian, no trusted third party. The block-height timelock is
# deterministic across nodes; pick expiry so YOUR refund is strictly LATER than the counterparty's (so they
# can't refund-then-still-claim). Keyless escrow account holds every locked coin (supply stays accounted).
HTLC_ESCROW = "htlc"                  # reserved escrow pseudo-account holding all locked HTLC coins
HTLC_MIN_TIMELOCK = 10                # expiry must be >= lock height + this (room for the claimant to act)
HTLC_MAX_TIMELOCK = 1_000_000         # and <= lock height + this (bounds indefinitely-dangling escrow)

# --- Execution-layer BRIDGE (doc/execution-layer.md, Phase 2) ---
# "bridge": DEPOSIT — locks L1 coins in the keyless escrow account BRIDGE_ESCROW; an execution node reads
#   the deposit from the ordered block stream and credits the depositor's exec-side balance.
# "bridge_withdraw": EXIT — the user proves (Merkle inclusion) that a withdrawal of {addr, amount, nonce}
#   is in the bonded-quorum-SETTLED execution-layer state root; L1 verifies that ONE proof, checks the
#   nullifier, and releases the escrowed coins. This is the trust-minimized link: L1 never runs the VM,
#   it only verifies a Merkle proof against a root the bonded stake has settled (settlement_ops).
BRIDGE_ESCROW = "bridge"          # the escrow pseudo-account holding all bridged (locked) L1 coins

# --- Execution-layer SETTLEMENT (doc/execution-layer.md, Phase 2) ---
# "settle": a keyless reserved recipient. A BONDED validator that also runs an execution node attests an
# execution-layer checkpoint {exec_cursor, state_root} (fee-exempt duty, like `attest`). When the bonded
# shares attesting the SAME (exec_cursor, state_root) exceed SETTLE_NUM/SETTLE_DEN of total bonded shares,
# L1 treats that root as the CANONICAL SETTLED execution-layer state (objective, stake-backed) — upgrading
# the execution layer from sovereign (Phase 1) to SETTLED. This is the pluggable verifier seam: the
# bonded-quorum check here is Phase-2a; a single succinct VALIDITY PROOF (STARK) can replace the quorum in
# Phase-2b behind the same interface (settlement_ops.settlement_justified). 2/3 stake quorum, like FFG.
SETTLE_NUM = 2
SETTLE_DEN = 3

# --- Registration Proof of Sequential Work (doc/ip-spoofing-and-sybil.md, Appendix A) ---
# The one-time cost to register an OPEN-lane identity is a hash-based PoSW (ops/posw.py): a length-POSW_T
# sequential blake2b chain (NON-parallelizable, so a GPU can't mint identities in bulk the way it can with
# the old hashcash), verified cheaply via POSW_K Fiat-Shamir spot-checks over POSW_S-step segments. Post-
# quantum (only assumes blake2b). The challenge binds address‖anchor where anchor = hash of block
# (target_block − POSW_ANCHOR_OFFSET) — a FINALIZED, stable block, so the proof is un-precomputable far in
# advance and non-reusable across identities. Tuned so an honest phone spends ~1 s once.
POSW_T = 1_000_000           # total sequential hash steps (~1 s on a phone; single-core spam < ~1M/day)
POSW_S = 2_000               # steps per checkpoint segment -> C = T // S = 500 segments
POSW_K = 20                  # Fiat-Shamir spot-checks (soundness); verify ~ (K+1)·S hashes
POSW_ANCHOR_OFFSET = 30      # anchor block = target_block − this (>= FINALITY_DEPTH: finalized & stable)

# PERIODIC PRESENCE: registration is a renewable LEASE. A `register` (with a fresh PoSW) grants OPEN-lane
# eligibility for POSW_LEASE_EPOCHS; to stay present you renew (another PoSW) each period, else you lapse
# out of the open registry. This turns "pay once, farm forever" into "pay continuously to keep each
# identity alive" — a Sybil farm's cost scales with size × time. At ~8 min/epoch, ~180 epochs ≈ 1 day, so
# an honest phone spends ~1 s of PoSW per day; a renewal is due once the lease is RENEW_FRACTION spent.
POSW_LEASE_EPOCHS = 180      # a registration/recert keeps you eligible this many epochs (~1 day)

# --- Data-availability blobs for the separate execution layer (doc/execution-layer.md, Phase 1) ---
# "blob": a keyless reserved recipient whose tx carries an OPAQUE payload in tx["data"]. L1 ORDERS and
# STORES it (and burns a DA fee) but NEVER decodes it — programmability lives one layer up, in separate
# execution nodes that replay these blobs in block order. This is the entire L1 surface for Phase 1:
# a fee-metered, size-capped, opaque byte channel. Contracts, the VM, and their state never touch
# consensus, so phone-mining and the base ledger are unaffected.
BLOB_MAX_BYTES = 16 * 1024        # per-tx opaque payload cap (canonical bytes) — bounds block growth
# Per-BLOCK total-blob-bytes cap (doc/execution-layer.md §3.3): the sum of all blob payloads in one block
# is bounded so a single block cannot bloat data-availability beyond what phones download/relay. This is
# a CONSENSUS check (verify_block rejects an over-cap block; block assembly drops the excess).
MAX_BLOB_BYTES_PER_BLOCK = 256 * 1024

# --- Aliases (human-readable names -> address; register / transfer / unregister on-chain) ---
# An alias lets a user send to a short name instead of the 49-char ndo address. Names are a scarce
# global namespace: 3..32 chars, lowercase [a-z0-9_-], must start with a letter, and must NOT be a
# reserved word or look like an address ("ndo…"). Registration pays a higher fee (anti-squat); the
# owner can transfer or unregister it. See ops/alias_ops.py.
ALIAS_MIN_LEN = 3
ALIAS_MAX_LEN = 32
ALIAS_REGISTRATION_FEE = 10_000_000     # 0.001 NADO (10,000x MIN_TX_FEE): deters mass name-squatting

# The TREASURY is the GENESIS address (project owner's decision): the 10% per-block cut accrues
# here. It is a normal KEY-CONTROLLED address (the founder holds its key), derived here under the
# canonical (new) checksum from the genesis public-key body so it validates. It starts EMPTY —
# there is NO genesis allocation (TREASURY_GENESIS = 0 below); it only fills from the per-block cut.
_GENESIS_BODY = "ndo27f2870bb2969a4d2b9d4eea303bedea996b9ccc93"  # genesis producer address (ML-DSA addr minus 4-hex checksum)
GENESIS_ADDRESS = _GENESIS_BODY + blake2b_hash(_GENESIS_BODY, size=2)
# The TREASURY is a RESERVED, KEYLESS account (like "dividend"/"bridge") — NOT the founder's genesis address.
# No private key exists for it, so the ONLY way coins leave it is a quorum-approved treasury_execute
# (doc/treasury.md §3.3). This is what makes "spendable only through the bonded-stake quorum" actually true.
TREASURY_ADDRESS = "treasury"

# --- Block reward: base subsidy + fee-weighted elastic, split producer/treasury (NO premine) ---
TREASURY_BPS = 1000          # treasury share of each block reward, in basis points (10.00%)
BPS_DENOM = 10000
# PRESENCE DIVIDEND (doc/presence-dividend.md): an OPEN-lane block's reward is split three ways instead of
# 90/10 — the producer keeps a small tip (it still did the work of building the block), the treasury keeps
# its 10%, and the REST accrues to the DIVIDEND_POOL for fidelity-weighted redistribution to every present
# open miner (accounted off-L1 by the execution node, collected on demand). BONDED-lane blocks ALSO contribute
# a modest share (BONDED_DIVIDEND_BPS) so the passive-capital lane shares with the active, capital-free open
# miners — a fair-launch "everyone earns" tax kept small enough that staking stays clearly the more profitable
# use of capital (i.e. the security budget is preserved). This only changes how emission is PAID OUT — a
# jackpot becomes a stream — it does not enlarge any lane's share.
OPEN_TIP_BPS = 2000          # open producer's cut of an open-lane block (20%); treasury 10%; dividend = rest (70%)
BONDED_DIVIDEND_BPS = 2000   # bonded block's contribution to the dividend pool (20%); producer keeps 70%, treasury 10%
DIVIDEND_POOL = "dividend"   # reserved L1 account the dividend accrues to (O(1) on L1)

# --- Treasury governance (doc/treasury.md): stake-quorum spending. No multisig — the bonded lane IS the
# multisig. A `treasury_execute` pays out a proposal only once bonded validators attesting it (via
# `treasury_vote`) exceed SETTLE_NUM/SETTLE_DEN of total bonded shares — the identical 2/3 stake quorum as
# settlement/finality. TREASURY_MAX_SPEND_BPS caps any single proposal to a fraction of the CURRENT treasury
# balance so no one passing vote can drain the vault (drain-resistant; the deliberately simple, bug-resistant
# alternative to a trailing-average rate limit — see doc/treasury.md §5). Anti-hoard burn lands in a later change.
TREASURY_MAX_SPEND_BPS = 2500   # a single proposal may spend at most 25.00% of the current treasury balance
# Newly-bonded stake must AGE this many epochs before it counts toward a treasury vote — defeats a flash /
# exchange-custodied bond swung in to capture a spend (Hive's fix). The quorum electorate is ACTIVATED bonded
# stake only, so fresh stake neither approves nor dilutes; genesis stake (bond_since == 0) is already aged.
TREASURY_VOTE_ACTIVATION_EPOCHS = 180   # ~1 day at defaults (== POSW_LEASE_EPOCHS)
# Anti-hoard self-burn (doc/treasury.md §3.2): every TREASURY_SPEND_PERIOD blocks, burn TREASURY_BURN_BPS of
# the treasury balance ABOVE a floor so an un-deployed treasury actively shrinks (the Bismuth fix). Flat
# Polkadot-style burn; the floor protects a nascent treasury. Revert-symmetric (the burned amount is stored).
TREASURY_SPEND_PERIOD = 10800   # burn cadence in blocks (~1 day at ~8s blocks)
TREASURY_BURN_BPS = 100         # burn 1.00% of the balance above the floor each period
TREASURY_RUNWAY_FLOOR = 0       # balance at/below this is never burned (0 = burn from the first coin; tune up later)
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

# --- Auto-bond (NON-CONSENSUS client/operator convenience; never validated on-chain) ---
# A miner can opt to route a percentage of newly-mined spendable earnings straight into bonded stake
# (auto-compounding the bonded lane). It is implemented identically in the node loop (unattended),
# the desktop wallet, and the browser light-miner. AUTO_BOND_MIN_RAW is a dust floor: an auto-bond
# only fires once the accrued amount-to-bond reaches it, so each bond tx dwarfs its own fee instead of
# spamming tiny bonds. Purely a client default — nodes/clients may mirror or override it freely.
AUTO_BOND_MIN_RAW = 10_000_000     # 0.001 NADO: smallest worthwhile auto-bond (10,000x MIN_TX_FEE)
# Default auto-bond percentage applied when the operator/user has NOT chosen one (fresh node config,
# a browser with no saved preference, a new desktop wallet). 80 = route 80% of newly-mined spendable
# earnings into bonded stake out of the box, so miners join the capital-gated bonded lane hands-free
# without ever touching a setting. Still fully overridable (config / env / UI), and 0 explicitly = off.
AUTO_BOND_DEFAULT_PERCENT = 80

# --- Rolling mode / history retention (NON-CONSENSUS node-local policy; see doc/rolling-mode-and-da.md) ---
# A "rolling" (pruned) node keeps STATE + a window of recent block BODIES and drops older bodies, so the
# ledger stops growing unbounded (keeps phones viable under adoption). Pruning body files is safe ONLY
# above the deepest lookback that re-reads a historical BODY on the consensus path — the audit found that
# is get_block_reward, which reads cumulative_fees from the block at tip-REWARD_WINDOW (100). Hashes for
# the beacon/FFG come from the tiny number<->hash INDEX (always retained), NOT bodies. So the retention
# window MUST exceed REWARD_WINDOW (+ FINALITY_DEPTH for the rollback window). Default 300 gives margin;
# prune_block_bodies additionally floors it at REWARD_WINDOW+FINALITY_DEPTH so a misconfig can't corrupt
# the reward calc. This is a per-node choice (archive nodes keep everything); it changes NO block/hash.
# 10_000 blocks ~= 1 week of history at 60s blocks — generous recent-body window while still bounding
# a rolling node's disk (the unbounded->bounded win); archive nodes keep everything.
HISTORY_RETENTION_BLOCKS = 10_000

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
# (raises FinalityViolation). The ordering max_rollbacks(10) < FINALITY_DEPTH < EPOCH_LENGTH(60)
# guarantees: an honest reorg (<= max_rollbacks deep) never hits the floor, and a malicious/long-range
# reorg is capped below one epoch so the epoch-beacon anchor is un-reorgable. (The presence recert lease
# spans POSW_LEASE_EPOCHS, far beyond any rollback window, so a reorg can never strand a valid lease.)
FINALITY_DEPTH = 30

# Bonded lane: locked refundable stake, split-neutral, per-identity capped.
B_MIN = 1_000_000_000_000          # 100 NADO: capital per bonded selection share
BOND_CAP = 100_000_000_000_000     # 10,000 NADO: max effective bond per identity
MAX_SHARES = BOND_CAP // B_MIN     # 100: variance cap so a whale can't monopolise the bonded lane
# BONDED PRODUCER RAMP (anti-sudden-takeover): a newly-bonded identity's PRODUCER-SELECTION weight ramps
# linearly from 0 to full over BOND_RAMP_EPOCHS, tracked by a STAKE-WEIGHTED bond age (so a top-up re-ramps
# the new stake, closing the "age a cheap address then dump" loophole, while auto-bond's small top-ups barely
# move it). This ONLY affects who is drawn to PRODUCE blocks — it deliberately does NOT touch fork-choice
# chain weight or the FFG/settlement quorum (those keep the ramp-free total_bonded_shares), so finality is
# never made tenure-dependent. A sudden whale therefore cannot control the very next epoch; it must accrue
# weight over ~BOND_RAMP_EPOCHS, buying the network reaction time. It only DELAYS a patient whale — the hard
# bound stays real capital cost + the per-address cap + slashing/finality (doc/takeover-resistance.md).
BOND_RAMP_EPOCHS = 30              # epochs for a fresh bond's selection weight to ramp 0 -> full (~= FIDELITY_CAP)
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
GC_IDLE_EPOCHS = 1000              # prune registry rows idle this long (bounds state bloat)

# Continuity FIDELITY — now driven by the PoSW RECERT (the single presence signal; there is no separate
# heartbeat). Each continuous recert (gap <= POSW_LEASE_EPOCHS) adds FIDELITY_GAIN; a lapse RESETS the streak.
# So fidelity measures CONSECUTIVE recerts (≈ days of continuous presence). A churned/rotated Sybil cannot keep
# a ramp it stopped paying for. It is only a ~10x open-weight booster, NOT the Sybil bound (the 20% lane cap is).
FIDELITY_CAP = 30                  # consecutive recerts (~days) to fully ramp the open bonus
FIDELITY_GAIN = 1                  # per continuous recert

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


def split_bonded_block_reward(reward: int):
    """Three-way split for a BONDED-lane block: (producer, dividend, treasury) summing to EXACTLY `reward`.
    treasury + dividend are floors, producer is the exact remainder (same rounding discipline as the open
    split), so apply and rollback subtract identical integers. The bonded producer keeps the majority
    (BPS_DENOM - TREASURY_BPS - BONDED_DIVIDEND_BPS, = 70%), a modest slice funds the presence dividend, and
    the treasury keeps its 10% — the passive lane sharing with the capital-free open miners."""
    treasury_cut = reward * TREASURY_BPS // BPS_DENOM
    dividend_cut = reward * BONDED_DIVIDEND_BPS // BPS_DENOM
    producer_cut = reward - treasury_cut - dividend_cut
    return producer_cut, dividend_cut, treasury_cut


def split_open_block_reward(reward: int):
    """Three-way split for an OPEN-lane block (doc/presence-dividend.md): (tip, dividend, treasury) summing
    to EXACTLY `reward`. treasury + tip are floors (same rounding as the bonded split), dividend is the exact
    remainder — so the apply and rollback paths subtract identical integers and can never desync a unit."""
    treasury_cut = reward * TREASURY_BPS // BPS_DENOM
    tip_cut = reward * OPEN_TIP_BPS // BPS_DENOM
    dividend_cut = reward - treasury_cut - tip_cut
    return tip_cut, dividend_cut, treasury_cut

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
# relaunch-2: hardfork that removed the vestigial IP block_producers system (block_producers_hash +
# block_ip fields) from the block body — a block-format change, so the chain resets from a fresh genesis.
CHAIN_ID = "alphanet-1"

# 1 NADO in raw (smallest) units. All on-chain amounts are integers in raw units.
DENOMINATION = 10_000_000_000  # 1e10

GENESIS_TIMESTAMP = 1783209600  # 2026-07-05 00:00 UTC — relaunch-3 (weight hardfork + carried balances)

# --- Reserved, keyless protocol pseudo-addresses (no private key) ---
# "bond"/"unbond": pseudo-recipients used by the bonding transactions (see S4).
# (The "burn" mechanic was removed entirely: no burn address, no burned counter, no
#  burn-to-bribe. Fees are still destroyed — that is the separate fee mechanic, not "burn".)
# "bond"/"unbond": bonded-lane stake txs. "register": the OPEN-lane (no-coin) mining lease tx
# (see the two-lane mining design in doc/mining.md). All are keyless protocol pseudo-recipients.
RESERVED_RECIPIENTS = frozenset({"bond", "unbond", "withdraw", "register", "slash", "attest", "commit", "reveal", "alias", "blob", "settle", "bridge", "bridge_withdraw", "dividend", "dividend_withdraw", "htlc", "htlc_lock", "htlc_claim", "htlc_refund", "shield", "unshield", "treasury", "treasury_vote", "treasury_execute", "msgkey", "xmsg"})

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

# SETTLEMENT NAMESPACES (multi-rollup): a `settle`/`bridge_withdraw` tx may name a rollup namespace (`ns`)
# so many execution layers settle to L1 INDEPENDENTLY under the same bonded quorum — L1 keeps one settled
# pointer per `ns`. Omitting `ns` means DEFAULT_NS, so the single pre-namespace execution layer (and its
# bridge/dividend) is unchanged. `ns` is a short id: lowercase [a-z0-9._-], <= NS_MAX_LEN. `blob` payloads
# stay OPAQUE to L1, so their namespacing lives inside the bytes execnodes decode — no L1 blob change.
DEFAULT_NS = "default"
NS_MAX_LEN = 32
_NS_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789._-"


def valid_namespace(ns) -> bool:
    """True for a well-formed settlement namespace id (or None ⇒ caller substitutes DEFAULT_NS)."""
    return isinstance(ns, str) and 1 <= len(ns) <= NS_MAX_LEN and all(c in _NS_CHARS for c in ns)

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

# --- Registration-rate PoSW difficulty (doc/ip-spoofing-and-sybil.md): the required PoSW work SCALES with
# recent registration volume, so a sudden identity FLOOD gets progressively more expensive. CONSENSUS-BOUND —
# validate_transaction recomputes the requirement from the committed recert index (keyed off the FINALIZED PoSW
# anchor epoch, so every node agrees) and REJECTS an under-worked registration; a modified node that "removes
# the difficulty code" simply produces proofs that HONEST nodes reject. Self-scaling vs a trailing-average
# baseline (with a floor), so a normal-sized network is never penalized — only abnormal bursts are. ---
POSW_DIFF_WINDOW = 20        # recent-registration window (epochs) whose rate sets the difficulty
POSW_DIFF_TRAIL = 400        # longer trailing window defining the "normal" rate baseline (~2 days)
POSW_DIFF_FLOOR = 20         # min baseline registrations/window (prevents tiny-network over-sensitivity + div-by-0)
POSW_DIFF_MAX_MULT = 16      # cap: never require more than 16x the base PoSW (bounds honest-user cost)

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
# A proposal binds an EXPIRY block into its id; votes and the payout must land at/before it, and it may sit at
# most this many blocks past its target. Bounds stale execution (a long-dormant proposal can't be revived and
# paid) AND state growth (the Quorum tab skips expired proposals) — keeps the governance queue scalable.
TREASURY_PROPOSAL_MAX_TTL = 100800   # ~1 week of blocks at ~6 s (tune with block time)
# Newly-bonded stake must AGE this many epochs before it counts toward a treasury vote — defeats a flash /
# exchange-custodied bond swung in to capture a spend (Hive's fix). The quorum electorate is ACTIVATED bonded
# stake only, so fresh stake neither approves nor dilutes; genesis stake (bond_since == 0) is already aged.
TREASURY_VOTE_ACTIVATION_EPOCHS = 3     # ALPHA testing value (was 180 ≈ 1 day) — RAISE to ~180 for mainnet
# Anti-hoard self-burn (doc/treasury.md §3.2): every TREASURY_SPEND_PERIOD blocks, burn TREASURY_BURN_BPS of
# the treasury balance ABOVE a floor so an un-deployed treasury actively shrinks (the Bismuth fix). Flat
# Polkadot-style burn; the floor protects a nascent treasury. Revert-symmetric (the burned amount is stored).
TREASURY_SPEND_PERIOD = 10800   # burn cadence in blocks (~1 day at ~8s blocks)
TREASURY_BURN_BPS = 100         # burn 1.00% of the balance above the floor each period
TREASURY_RUNWAY_FLOOR = 0       # balance at/below this is never burned (0 = burn from the first coin; tune up later)
REWARD_WINDOW = 100          # retained as the prune/rollback safety window (block_ops.prune_block_bodies);
                             # no longer a reward average — emission is now FLAT base * bond-elastic multiplier.
# FLAT per-block emission, scaled only by the bond-elastic multiplier (see BOND_ELASTIC_MULT_BPS below and
# doc/bond-elastic-emission.md). There is NO fee-weighted upside and NO ceiling: fees are DESTROYED, so
# raising emission with fees would mint more exactly when more is burned — softening the deflation. Because
# the multiplier m(r) <= 1, the block reward is BASE_SUBSIDY at most (the MAX emission/block) and
# m_min*BASE_SUBSIDY (~0.024 NADO) at least — the perpetual tail, so production is never unincentivised (no
# hard cap, no security cliff). The base also lets a zero-coin OPEN-lane miner earn from block 1 (fair launch).
BASE_SUBSIDY = 1_000_000_000  # 0.1 NADO/block raw = MAX emission/block (~144 NADO/day at 60s blocks: 1440*0.1)

# --- BOND-ELASTIC EMISSION (super hard money — see doc/bond-elastic-emission.md) ---
# The block reward is scaled by a multiplier m(r) that shrinks as the bonded ratio r rises: the more the
# network locks up (conviction), the less it mints. Combined with fee destruction this makes NADO
# net-deflationary under real usage, while a perpetual tail (m never reaches 0) means block production is
# ALWAYS incentivised — no hard cap, no security cliff (Monero reasoning).
#   m(r) = M_MIN + (1-M_MIN)*exp(-k*r),  M_MIN=0.15, k=4,  applied uniformly to BOTH lanes.
# TUNED (final): M_MIN=0.15 gives a credible perpetual security tail (~0.0166 NADO/block ≈ 8,700 NADO/yr
# forever, never zero) while k=4 makes emission at the ~40% self-limiting equilibrium ~0.033/block (hard),
# with a responsive-but-not-violent early curve (10% bonded -> ~28% emission cut). MAX emission = BASE (m=1
# at r=0). CONSENSUS-SAFE: hardcoded INTEGER table in basis points, indexed by the bonded ratio in whole
# percent (0..100) — never a runtime float (a last-ULP math.exp diff across platforms could fork the chain).
#   reward = reward * BOND_ELASTIC_MULT_BPS[pct] // 10000.
# Regenerate on a param change:  [round((0.15+0.85*exp(-4*p/100))*10000) for p in range(101)]
BOND_ELASTIC_MULT_BPS = [
    10000, 9667, 9346, 9039, 8743, 8459, 8186, 7924, 7672, 7430,
    7198, 6974, 6760, 6553, 6355, 6165, 5982, 5806, 5637, 5475,
    5319, 5170, 5026, 4887, 4755, 4627, 4504, 4387, 4273, 4165,
    4060, 3960, 3863, 3771, 3682, 3596, 3514, 3435, 3359, 3286,
    3216, 3149, 3084, 3022, 2962, 2905, 2850, 2797, 2746, 2697,
    2650, 2605, 2562, 2520, 2480, 2442, 2405, 2369, 2335, 2303,
    2271, 2241, 2212, 2184, 2157, 2131, 2107, 2083, 2060, 2038,
    2017, 1997, 1977, 1958, 1940, 1923, 1907, 1891, 1875, 1861,
    1846, 1833, 1820, 1807, 1795, 1784, 1773, 1762, 1752, 1742,
    1732, 1723, 1714, 1706, 1698, 1690, 1683, 1676, 1669, 1662,
    1656,
]

# NO PREMINE (owner decision 2026-06-30): genesis mints ZERO coins. No founder allocation, no
# treasury seed. A fresh chain bootstraps purely through the OPEN mining lane (register for free,
# earn the BASE_SUBSIDY) — not a pre-funded balance. The treasury still accrues TREASURY_BPS of
# every block reward going forward; it just starts empty. (Set >0 only to reintroduce a premine.)
TREASURY_GENESIS = 0  # no premine — fair launch via the open lane + base subsidy

# --- Multisig (opt-in M-of-N accounts; see ops/multisig_ops.py) ---
# A multisig address = make_address(blake2b(["nado-msig-v1", threshold, members])) — the address IS
# the policy, nothing is registered in advance. Spends carry the descriptor in the signed body and a
# LIST of member signatures over the txid. Payment accounts only (reserved recipients are rejected),
# so validator-identity assumptions stay one-key-one-identity. Live since introduction (alphanet — no
# activation-height ceremony).
MULTISIG_MAX_MEMBERS = 16          # bounds descriptor size + per-tx signature verification work

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
OPEN_BPS = 3000                    # SECURITY DIAL: open-lane share of slots (30.00%); Sybil ceiling.
                                   # Bonded keeps the 70% majority — above the 2/3 settlement/finality quorum,
                                   # so fork-choice + finality stay stake-controlled. MUST stay <= 3333 (33.3%)
                                   # or bonded drops below 2/3. Widened 20%->30% to send more emission (and the
                                   # 70%-of-open presence dividend) to the capital-free lane. See doc/mining.md.
K_OPEN = EPOCH_LENGTH * OPEN_BPS // BPS_DENOM  # open slots per epoch (rest bonded); =18 at defaults

# RANDAO participation policy (consensus): when True, the bonded-lane producer draw for epoch E only
# admits validators that revealed their committed secret for E (no reveal -> no production rights that
# epoch). When False (current), revealing is OPTIONAL: reveals still feed the epoch beacon when present
# (and the beacon advances deterministically off the finalized anchor with zero reveals), but skipping
# the duty costs nothing and the draw runs over the FULL bonded registry. Chosen for scalability: with
# many bonded validators, forcing every one of them to land a commit+reveal tx every epoch adds
# O(validators) mandatory txs per epoch and makes rewards hinge on tx inclusion latency.
# NOTE: flipping this is a consensus change — only safe on a fresh chain or while the filter has never
# altered a historical draw (verified empty bonded registry at flip time, 2026-07-06, height 2671).
RANDAO_ENFORCED = False

# ENFORCED FINALITY (#17, security step 1): a block at height H finalizes everything at/below
# H - FINALITY_DEPTH; rollback_one_block REFUSES to cross the persisted monotonic finalized_height
# (raises FinalityViolation). The ordering max_rollbacks(10) < FINALITY_DEPTH < EPOCH_LENGTH(60)
# guarantees: an honest reorg (<= max_rollbacks deep) never hits the floor, and a malicious/long-range
# reorg is capped below one epoch so the epoch-beacon anchor is un-reorgable. (The presence recert lease
# spans POSW_LEASE_EPOCHS, far beyond any rollback window, so a reorg can never strand a valid lease.)
FINALITY_DEPTH = 30

# Bonded lane: locked refundable stake, split-neutral, per-identity capped.
B_MIN = 10_000_000_000_000         # 1,000 NADO: capital per bonded selection share (staking-lane entry).
                                   # Deliberately NOT tiny: grinding spending money is fast+fair (open lane),
                                   # but becoming a VALIDATOR is a real commitment — skin in the game, and
                                   # it stops the bonded lane from being trivially Sybil-able with dust.
BOND_CAP = 1_000_000_000_000_000   # 100,000 NADO: max effective bond per identity (scaled 10x with B_MIN)
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
OPEN_BASE_FLOOR = 2                # every registered+present identity's minimum open weight (never 0). Raised
                                   # 1->2 so a genuine newcomer earns 2/10 = 20% of a mature miner's rate on
                                   # day one (was 10%) — fairer to new phones, while keeping a 5x loyalty premium.
OPEN_FID_BONUS = 8                 # max diligence bonus: open weight ranges OPEN_BASE_FLOOR..+8 (2..10)
GC_IDLE_EPOCHS = 1000              # prune registry rows idle this long (bounds state bloat)

# Continuity FIDELITY — now driven by the PoSW RECERT (the single presence signal; there is no separate
# heartbeat). Each continuous recert (gap <= POSW_LEASE_EPOCHS) adds FIDELITY_GAIN; a lapse RESETS the streak.
# So fidelity measures CONSECUTIVE recerts (≈ days of continuous presence). A churned/rotated Sybil cannot keep
# a ramp it stopped paying for. It is only a ~5x open-weight booster, NOT the Sybil bound (the 30% lane cap is).
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

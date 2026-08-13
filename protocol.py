"""
protocol.py — single source of truth for NADO protocol / economic / mining constants.

No live network exists, so these define the relaunch genesis behaviour DIRECTLY: there
are no fork-height activation gates. Everything here is consensus-critical and must be
identical on every node (and reproducible by a browser light-miner), so keep it to plain
ints/strings and pure functions with no imports from `ops` (this module must stay a leaf
so anything can import it without a cycle).
"""
from hashing import blake2b_hash  # leaf module (stdlib only) -> no import cycle

# FAIL-CLOSED under `python -O` / PYTHONOPTIMIZE. The consensus signature/txid verification spine
# (validate_origin, validate_txid, verify_multisig_origin) signals rejection by raising AssertionError;
# with asserts stripped those checks fall through to `return True`, accepting UNSIGNED, malleable txs =
# universal forgery. Refuse to run rather than run silently unverified. protocol is imported by every
# consensus process, so this gate covers the node, the exec node, and the tools. (Set NADO_ALLOW_NO_ASSERT=1
# only for a deliberate non-consensus utility run.)
if not __debug__:
    import os as _os
    if _os.environ.get("NADO_ALLOW_NO_ASSERT") != "1":
        raise RuntimeError(
            "NADO refuses to start with assertions disabled (python -O / PYTHONOPTIMIZE): the consensus "
            "signature-verification spine rejects via `assert`, which -O strips, turning every rejection "
            "into a silent accept. Run without -O.")

# Bound into every signed transaction and block body so a transaction/block from another
# chain (or the pre-relaunch chain) can never replay here (closes audit item M3).
# relaunch-2: hardfork that removed the vestigial IP block_producers system (block_producers_hash +
# block_ip fields) from the block body — a block-format change, so the chain resets from a fresh genesis.
CHAIN_ID = "betanet-3"  # BETANET (gen 21): the CARRY-FORWARD reroll — balances, dividends and bridged
                        # coins fold forward from betanet-2 (genesis_data/genesis_alloc.dat)

# 1 NADO in raw (smallest) units. All on-chain amounts are integers in raw units.
DENOMINATION = 10_000_000_000  # 1e10

# ---- ADDRESS FORMAT (single source of truth — doc/address-format.md) -------------------------------
# address = first ADDRESS_BODY hex chars of the pubkey + 4-hex blake2b checksum. NO PREFIX.
# Changing ANY of these orphans every existing address string, so a change ships only with a
# CHAIN_GENERATION reroll whose genesis alloc is re-keyed by scripts/rekey_alloc.py.
#
# THE PREFIX IS GONE (alphanet-14), with no backwards compatibility. It never verified anything:
# validate_address() has always checked ONLY the 4-hex blake2b checksum over the rest, and never referenced
# the prefix at all. So "does this string belong to NADO" is still answered exactly as before — right length,
# valid checksum — and a random 46-hex string still passes with probability 2^-16, unchanged.
# What it DID do was serve as a cheap discriminator in a dozen `startswith(ADDRESS_PREFIX)` sniffs meaning
# "an address rather than a reserved name or an alias". Those are now address_ops.is_address(), a real check,
# because an empty prefix makes startswith() true for EVERY string — which would have silently reclassified
# every timing-critical reserved tx as flexibly-landing.
# MSIG_PREFIX survives and is what still distinguishes policy accounts from keyed ones.
ADDRESS_PREFIX = ""             # removed at alphanet-14; kept as a constant so the derivation stays one place
MSIG_PREFIX = "msig"           # policy accounts (M-of-N multisig) — the 1-vs-3 split; see doc/address-format.md
ADDRESS_BODY = 42              # hex chars of the pubkey carried in the address
ADDRESS_CHECKSUM = 2           # checksum bytes (4 hex chars), blake2b over prefix+body
ADDRESS_LENGTH = len(ADDRESS_PREFIX) + ADDRESS_BODY + ADDRESS_CHECKSUM * 2   # 49 today

# ---- DOMAIN-SEPARATION TAGS (consensus; brand-carrying) --------------------------------------------
# Renamed ONLY at a CHAIN_GENERATION reroll — everything re-derives from genesis there (see
# doc/address-format.md "Domain-separation tags"). One constant per tag; no other Python spells
# them. JS mirrors: static/interface.js DOMAIN_* block, static/stark/transcript.js DOMAIN_STARK.
DOMAIN_MSIG = "msig-v2"                       # multisig virtual-pubkey derivation (ops/multisig_ops)
DOMAIN_REGISTER = "register-v1"               # open-lane registration PoW binding (ops/mining_ops)
DOMAIN_RANDAO_COMMIT = "randao-commit-v1"     # RANDAO commitment preimage tag (ops/mining_ops)
DOMAIN_RANDAO_BEACON = "randao-beacon-v1"     # RANDAO beacon-fold preimage tag (ops/mining_ops)

GENESIS_TIMESTAMP = 1786617600  # betanet-3 (gen 21): the carry-forward reroll. New DISTINCT
                                # timestamp so no prior-generation block links in.
                                # Block 0's hash is blake2b_hash_link(timestamp, []), so a DISTINCT
                                # timestamp is what actually makes this a different chain — no
                                # prior-generation block can link in, and old-code nodes cannot keep
                                # winning fork choice against it (gens 7-9 reused alphanet-8's genesis
                                # and stranded exactly that way). Stamped ~1 min in the PAST so block
                                # production starts immediately at cutover.
                                # The tree DEPTH is frozen at 256 (saturates the hash's collision resistance),
                                # so no future change needs a deeper tree. But ADDING a committed leaf TYPE —
                                # gen 18 added a per-contract code leaf to the KV half — still changes every
                                # existing root, so it rides a generation bump like any other root change.

# Clock-skew allowance for block timestamps: a block may be stamped up to this many seconds in the
# FUTURE of the local clock and still validate. Zero tolerance rejected honest blocks whenever the
# producer's clock ran even 1 s ahead of a validator's — and the producer-side monotonic clamp
# (block_timestamp = max(now, parent_ts)) then PROPAGATED one fast clock's stamp to every following
# honest producer, so well-clocked nodes kept logging "Invalid block timestamp" with no attacker in
# sight. Bounded abuse: timestamps aren't hashed, but validation caps them at now+DRIFT, so a lying
# relay can push chain time at most this far ahead of real time (it can't compound block over block).
BLOCK_TIMESTAMP_DRIFT = 30

# CANONICAL BLOCK TIME (consensus). The per-node `block_time` in private/config.json is an operator PACING
# knob and is NOT consensus — two nodes may legitimately hold different values (this fleet ran 6 while the
# code default was 10). Anything consensus-visible that needs a notion of elapsed time must use THIS
# constant, never the config one, or it is node-local by construction. Used to derive the deterministic
# exec-layer clock (see CHAIN_CLOCK / execnode state.block_ts): block_timestamp itself is deliberately
# outside the block-hash preimage so honest clock skew cannot fork the chain, which makes it unusable as a
# consensus input — it varies between honest nodes for the SAME block.
BLOCK_TIME = 6


def chain_clock(block_number: int) -> int:
    """The DETERMINISTIC chain clock the execution layer exposes as TIME: a pure function of block height,
    so every node computes the identical value for a block and a contract reading TIME cannot fork exec
    state. Monotonic and approximately wall-clock (it tracks real time exactly while blocks land on
    schedule, and lags if they do not). Deliberately NOT block_timestamp, which is uncommitted and skews
    by up to BLOCK_TIMESTAMP_DRIFT between honest nodes."""
    return GENESIS_TIMESTAMP + int(block_number) * BLOCK_TIME

# INCLUSION DELAY (blocks): a flexibly-landing tx sets min_block = submit_tip + this, so no producer may
# include it until it has had this many blocks (~this * block_time seconds) to gossip to EVERY producer.
# All nodes then hold the identical mature tx set at each height and build byte-identical blocks, so the
# deterministic fast-forward (loops/core_loop) always hits and block time tracks block_time instead of
# lagging on transient mempool divergence. Enforced in block_ops (producer + verifier); absent min_block
# defaults to 0 (immediate), so historical blocks stay valid.
#
# RAISED 2->8 after the alphanet-13 h5924 split (2026-07-29). Three nodes built the winner's block with blob
# tx f2f8f14066 (min_block=5924, i.e. eligible at exactly that height); .131 built the same winner's block,
# same parent, same creator, same state_root, same weight, 4 seconds earlier and WITHOUT the tx. One block
# apart in eligibility is a coin flip on whether every producer holds the tx yet, and the two honest blocks
# then differ in nothing but their tx set. That is the same too-tight-window failure RESERVED_TX_MARGIN and
# DUTY_TX_MARGIN were raised for; this was the one remaining instance, on the ordinary flexibly-landing path.
#
# SUBMITTER-SIDE, so no reroll: the verifier enforces `block_number >= tx["min_block"]` against the tx's OWN
# committed field, and this constant only decides what a newly constructed tx stamps there. Old and new nodes
# interoperate; they just pick different earliest-landing heights for the txs they create.
#
# 8 blocks is ~48s at 6s/block — enough for several gossip rounds without pushing blob latency past a minute.
# HONEST RESIDUAL: a margin helps only if the tx eventually arrives. If .131 never received it at all, this
# buys more retry opportunities but is not a cure; the mempool-propagation path is the thing to instrument if
# a split recurs at a wider margin.
TX_INCLUSION_DELAY = 8

# TX LANDING (max_block is an EXPIRY DEADLINE, not a target). A flexibly-landing tx (value transfer, blob,
# bridge in/out, dividend_withdraw — see block_ops._lands_flexibly) may be mined in ANY block in
# [min_block, max_block]; only timing-critical txs (epoch-bounded RANDAO/attest, release-timed bond/unbond,
# PoW-anchored register/msgkey, settle, governance) still land at exactly max_block. TX_LANDING_WINDOW is the
# hard cap on how far ahead max_block may sit at admission (the mempool gate). TX_TARGET_MARGIN is the GENEROUS
# default a wallet/CLI/auto-tx aims max_block at for a flexibly-landing tx, so it has a wide landing window and
# does not expire (and re-gossip-flood "Target block too low") before a producer includes it. Kept well below
# the window so a tx admitted against a slightly-behind peer still fits (max_block <= their_tip + WINDOW).
TX_LANDING_WINDOW = 360
TX_TARGET_MARGIN = 300

# RESERVED-TX LANDING MARGIN — how far ahead the node aims max_block for the EXACT-LANDING txs it mints
# itself (bond, register, duty). These get no min_block inclusion delay (_lands_flexibly is False for them,
# by design: their timing invariants are tied to the landing height), so max_block IS their only
# propagation window: the tx must reach EVERY producer before the block it lands in is built. Blocks are
# deterministic, so a producer holding the tx assembles a different block than one that does not — and the
# chain forks on the spot.
#
# The old values were tip+2 (bond), tip+4 (register) and tip+5 (duty): ~12-30s at 6s/block. That forked
# alphanet-12 three times on 2026-07-28 — h12506 on an auto-bond emitted after a node restart, h12605 on a
# duty tx — splitting a 4-node fleet into three chains and collapsing FFG to 0. Every restart mints a bond
# and every epoch mints a duty, so this fires as a matter of course, not as an edge case.
#
# SUBMITTER-SIDE ONLY: max_block is chosen by the sender and consensus only checks max_block ==
# block_number, so raising these needs no reroll and old and new nodes interoperate (they just pick
# different landing heights for their own txs). Kept well under TX_LANDING_WINDOW so a tx admitted against
# a slightly-behind peer still fits.
RESERVED_TX_MARGIN = 30      # bond/register: ~3 min at 6s/block
DUTY_TX_MARGIN = 12          # duty: additionally clamped by the epoch and RANDAO-reveal deadlines

# --- Reserved, keyless protocol pseudo-addresses (no private key) ---
# "bond"/"unbond": pseudo-recipients used by the bonding transactions (see S4).
# (The "burn" mechanic was removed entirely: no burn address, no burned counter, no
#  burn-to-bribe. Fees are still destroyed — that is the separate fee mechanic, not "burn".)
# "bond"/"unbond": bonded-lane stake txs. "register": the OPEN-lane (no-coin) mining lease tx
# (see the two-lane mining design in doc/mining.md). All are keyless protocol pseudo-recipients.
RESERVED_RECIPIENTS = frozenset({"bond", "unbond", "withdraw", "register", "slash", "attest", "commit", "reveal", "duty", "alias", "blob", "settle", "bridge", "bridge_withdraw", "dividend", "dividend_withdraw", "htlc", "htlc_lock", "htlc_claim", "htlc_refund", "shield", "unshield", "treasury", "treasury_vote", "treasury_execute", "msgkey", "xmsg", "faucet"})

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
FAUCET_ESCROW = "faucet"          # keyless reserved account locking faucet donations (doc/faucet.md);
                                  # the exec layer mirrors each donation as balance of the `faucet` contract

# --- Execution-layer SETTLEMENT (doc/execution-layer.md, Phase 2) ---
# "settle": a keyless reserved recipient. A BONDED validator that also runs an execution node attests an
# execution-layer checkpoint {exec_cursor, state_root} (fee-exempt duty, like `attest`). When the bonded
# shares attesting the SAME (exec_cursor, state_root) exceed SETTLE_NUM/SETTLE_DEN of total bonded shares,
# L1 treats that root as the CANONICAL SETTLED execution-layer state (objective, stake-backed) — upgrading
# the execution layer from sovereign (Phase 1) to SETTLED. Phase-2b is now LIVE ALONGSIDE the quorum: a
# `settle` tx MAY carry a succinct recursion VALIDITY PROOF, which every node verifies deterministically at
# block-validation and records as an on-chain marker (kv_ops.settlement_proven); settlement_ops.settlement_
# justified accepts a root when that marker is set OR the bonded quorum is met (proof = trustless finality,
# quorum = liveness floor). Both are pure functions of committed on-chain state, so no node ever diverges.
# 2/3 stake quorum, like FFG.
SETTLE_NUM = 2
SETTLE_DEN = 3
# SETTLEMENT INACTIVITY LEAK (the participation-windowed quorum pattern, like the FFG duty committee): the quorum
# DENOMINATOR is the bonded shares of validators that have posted a settle attestation for the
# namespace within this many exec cursors of the highest attested cursor — bonded validators that do
# NOT run an exec+settle node leak out of the settlement quorum instead of blocking it forever.
# WHY: the original denominator was ALL bonded stake, so the moment non-settling validators bonded
# past 1/3 of shares, no root could EVER settle — every dividend/bridge/unshield claim on L1 failed
# with "no settled execution-layer root yet" while the exec side had already burned the balance into
# a withdrawal record (funds stuck, not lost). Same trust trade FFG accepted: going dark forfeits
# your say, and a hostile LONE settler only controls the root if every honest settler has been dark
# for the whole window (~2.4h at 6s blocks; systemd restarts make that an outage, not an accident).
# The optimistic fraud proof (doc/dividend-fraud-proof.md) is the planned trust upgrade on top.
SETTLE_ACTIVITY_CURSORS = 1440

# The exec-layer GENESIS state root every namespace's settled chain extends from. A settle-with-proof for a
# namespace with no prior settled tip must carry a proof whose pre_root is EXACTLY this — so the very first
# settlement cannot start from a fabricated pre-state (the same strict chaining every later settlement gets
# by extending the committed tip). It is the root of an EMPTY execution state
# (execnode/exec_root.state_root_hex({}, empty ExecState): rnode(empty KV half, records half holding only the
# empty shielded/field-pool digest records) over the two depth-256 sparse alghash2 trees).
# Hardcoded (protocol.py stays a leaf: no execnode import), so it is a SCHEME CANARY: if the exec-root
# scheme ever changes, this stops matching the recomputed empty-state root and the assertion in
# tests/test_exec_root.py fails loudly. That is exactly how the 2026-07-20 drift was found — the value below
# had silently desynced when alghash2 went 8 -> 54 rounds (db03a1f) and again at the alphanet-7 debrand,
# because the guard the comment PROMISED did not exist: test_exec_root only PRINTED the value. It asserts now.
# (The settle path no longer consumes this: a first settlement must come from the bonded quorum, so a proof
# always extends a real committed tip. Kept because the canary is worth more than the one call site was.)
EXEC_GENESIS_ROOT = "076885ee6a32444b8f3aeb99829c7f8994e6436ce69be7080af1ebaa4726a4a8"

# The FROZEN depth of the two sparse halves of the settled root (see exec_root.DEPTH — kept equal by test).
# 256 = the full alghash2 digest: position security saturates the hash itself, so this never changes.
EXEC_TREE_DEPTH = 256

# --- CONSENSUS-LOAD AGGREGATION (doc/consensus-aggregation.md — the O(N)-messages scaling fix) ---
# 1. MERGED DUTY TX: a bonded validator's whole per-epoch consensus participation — FFG attest(X) +
#    RANDAO commit(X+2) + reveal(X+1) — rides in ONE fee-exempt `duty` tx (one ~2.4KB ML-DSA
#    signature instead of three full txs; the three validation windows all overlap for the entire
#    epoch minus its last FINALITY_DEPTH+1 blocks). The legacy attest/commit/reveal recipients stay
#    CONSENSUS-VALID forever (historical blocks contain them; genesis sync must replay them) but the
#    mempool refuses new ones — honest emission is duty-only.
# 2. DUTY COMMITTEE: only DUTY_COMMITTEE_SEATS beacon-sampled stake-weighted seats per epoch may
#    post duties, so the per-epoch consensus load is O(seats) — CONSTANT in validator count — instead
#    of O(N). Sampling is the same deterministic weighted draw as producer selection, keyed
#    (beacon(X), "duty", seat), with replacement: a validator's expected seats are proportional to
#    its stake, and FFG quorum counts SEATS (attesting seats*3 > total seats*2), so the committee
#    quorum converges on the stake quorum. Security: for an adversary with < 1/3 of bonded stake,
#    P(>= 2/3 of 128 sampled seats) is cryptographically negligible (Chernoff) — the standard
#    committee argument. With few validators every share-holder lands seats and behavior matches
#    the full-set quorum. Epoch X's committee derives from beacon(X) (fixed before X starts and
#    grind-resistant), so membership is known exactly when the duties are due.
DUTY_COMMITTEE_SEATS = 128
# FFG committee-seat INACTIVITY LEAK: a checkpoint justifies when the committee seats attesting it
# exceed FFG_NUM/FFG_DEN of the seats held by RECENTLY-ACTIVE committee members — those with an
# attestation in the last INACTIVITY_WINDOW epochs. Seats of members dark for the whole window LEAK
# from the denominator (their bond stays; they just forfeit their finality say), so a live attesting
# supermajority always finalizes instead of being blocked by bonded-but-absent stake — the same
# liveness guarantee FFG had before the committee, now seat-quantized. Members active recently but
# idle THIS epoch still count in the denominator (they correctly dilute), so the threshold stays a
# real 2/3-of-participating-stake bar, not "one seat justifies."
INACTIVITY_WINDOW = 3

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
# (max_block − POSW_ANCHOR_OFFSET) — a FINALIZED, stable block, so the proof is un-precomputable far in
# advance and non-reusable across identities. Tuned so an honest phone spends ~1 s once.
POSW_T = 1_000_000           # total sequential hash steps (~1 s on a phone; single-core spam < ~1M/day)
POSW_S = 2_000               # steps per checkpoint segment -> C = T // S = 500 segments
POSW_K = 20                  # Fiat-Shamir spot-checks (soundness); verify ~ (K+1)·S hashes
POSW_ANCHOR_OFFSET = 150     # anchor block = max_block − this (>= FINALITY_DEPTH: finalized & stable)
# HOW LONG A PROVER ACTUALLY HAS. A `register` lands at EXACTLY max_block, and its anchor
# (max_block − POSW_ANCHOR_OFFSET) must already exist when proving STARTS — so a client targeting
# tip+M can only choose M <= POSW_ANCHOR_OFFSET, and M blocks is its entire proving budget.
#
# With the offset at 30 the budget was 30 blocks (180 s) and the anchor was the TIP itself (depth 0 at
# prove time — below FINALITY_DEPTH, contrary to the note above). That budget is not a function of the
# WORK the difficulty demands, and the two had drifted badly apart: an entry registration owes
# POSW_ENTRY_MULT × the rate multiplier = up to 512 × POSW_T = 512M sequential hashes. Measured with the
# hasher the browser miner actually ships (WASM blake2b, ~3.2M h/s on a desktop, ~4-10x slower on a
# phone), a mid-range phone needed ~121 s of a 180 s window at 96x and simply could not finish at all
# above that. It produced a VALID proof for a block the chain had already passed, and the submit came
# back as a flat rejection — reported by users as "the relay rejected the registration".
#
# Widening the offset fixes the binding constraint without touching the anti-Sybil COST by one hash.
# At offset 150 a client targets tip+90: the anchor is tip−60, which is 60 blocks deep at prove time
# (past FINALITY_DEPTH=45, so the note above becomes true) and 150 deep at landing. Budget: 90 blocks
# = 540 s, enough for the worst case on a slow phone.
#
# CONSENSUS. validate_transaction re-derives the anchor from max_block, so a node on a different offset
# computes a different challenge and rejects every honest registration. Flag day, no compat path.
POSW_TARGET_MARGIN = 90      # blocks a client may target ahead of the tip = its proving budget (540 s)

# PERIODIC PRESENCE: registration is a renewable LEASE. A `register` (with a fresh PoSW) grants OPEN-lane
# eligibility for POSW_LEASE_EPOCHS; to stay present you renew (another PoSW) each period, else you lapse
# out of the open registry. This turns "pay once, farm forever" into "pay continuously to keep each
# identity alive" — a Sybil farm's cost scales with size × time. At ~8 min/epoch, ~180 epochs ≈ 1 day, so
# an honest phone spends ~1 s of PoSW per day; a renewal is due once the lease is RENEW_FRACTION spent.
POSW_LEASE_EPOCHS = 240      # a registration/recert keeps you eligible this many epochs (~1 day: 240×60×6s = 24h)

# --- Registration-rate PoSW difficulty (doc/ip-spoofing-and-sybil.md): the required PoSW work SCALES with
# recent registration volume, so a sudden identity FLOOD gets progressively more expensive. CONSENSUS-BOUND —
# validate_transaction recomputes the requirement (v2: counted from the CHAIN's blocks over complete epochs
# strictly before the finalized PoSW anchor, so every node at any time computes the identical value) and
# REJECTS an under-worked registration; a modified node that "removes the difficulty code" simply produces
# proofs that HONEST nodes reject. Self-scaling vs a trailing-average baseline (with a floor), so a
# normal-sized network is never penalized — only abnormal bursts are. ---
POSW_DIFF_WINDOW = 20        # recent-registration window (epochs) whose rate sets the difficulty
POSW_DIFF_TRAIL = 400        # longer trailing window defining the "normal" rate baseline (~2 days)
POSW_DIFF_FLOOR = 20         # min baseline registrations/window (prevents tiny-network over-sensitivity + div-by-0)
POSW_DIFF_MAX_MULT = 16      # cap: never require more than 16x the base PoSW (bounds honest-user cost)

# ENTRY COST — the consensus-enforceable half of "one device may not onboard thousands of identities".
#
# The 64-per-IP cap (ops.ratelimit.allow_registration) is called from ONE place: nado.py's HTTP submission
# handler. It is admission policy on one door, not a rule of the chain — a registration submitted to a
# different node, from a different IP, or gossiped straight to peers is fully valid and every node accepts
# it. IT CANNOT BE MADE CONSENSUS: a transaction carries no IP (sender/pubkey/posw/signature only), and
# transactions arrive by GOSSIP, so the address a node observes is the RELAYING PEER, not the originator.
# Different nodes would compute different answers for the same block — the exact non-determinism class that
# has wedged this chain before. A self-declared IP field would be forgeable and free to vary.
#
# What IS consensus-checkable is the sender's OWN recert history. So the cost is moved to identity
# CREATION: a register from an address with no valid lease as of the anchor epoch (a new identity, or one
# that let its lease lapse) pays POSW_ENTRY_MULT x the base sequential work; an established identity
# RENEWING pays the base. That is the right shape for anti-Sybil — creation dear, presence cheap — and it
# leaves the open lane capital-free, which is the point of the lane.
#
# Sizing: at the measured honest weight (266 across 117 miners), 133 identities take half the open lane and
# half the presence dividend. At 32x that is ~71 core-minutes of one-time work instead of ~2, and it
# COMPOSES with the rate multiplier (up to 16x), so a burst pays up to 512x base each.
# It depends only on the sender's own history, which only the sender can extend and only once per epoch,
# so prover and validator cannot disagree between prove-time and land-time.
POSW_ENTRY_MULT = 32

# UNCONDITIONAL — this ships WITH a genesis reroll, so there are no pre-rule proofs to keep valid and no
# historical blocks to re-validate. It was briefly height-gated (epoch 862) while the plan was to activate
# on the running chain; a reroll makes that gate pure dead weight, and re-dating it would have left the
# hole open for the first ~3.5 days of the new chain.
# CHAIN GENERATION (genesis-reroll flag, ops/data_ops.py): each generation is ONE GENESIS LINEAGE —
# bump this in the SAME commit as a genesis reroll (nothing to do with the 60-block consensus epochs).
# Every node stamps the generation its on-disk data was built under; on boot after an update, a mismatch
# wipes all chain-derived data (blocks/index/peers/snapshots/exec state+DA — never private/) and the node
# regenesis/resyncs fresh. This makes one /update wave a COMPLETE reroll deployment. No compatibility:
# old generations are not carried, they are purged.
# 3 (2026-07-25): the STATE-ROOT-BINDING reroll. Blocks now commit an L1 state_root + the L2 settled
#   (exec_cursor, exec_root) INTO the hash, state application was made deterministic (reverse-order rollback,
#   revert journals out of the root, empty-account canonicalization), and the exec-layer wipe was made
#   authoritative. Ships as a fresh genesis lineage so L1 and L2 restart jointly at (block 0, EXEC_GENESIS_ROOT)
#   with no pre-reroll state to reconcile — one /update wave converges the fleet on a clean, self-consistent chain.
# 4 (2026-07-25): alphanet-8 — same reroll re-cut with a NEW CHAIN_ID + GENESIS_TIMESTAMP (distinct genesis
#   hash) AND the exec-layer stale-state race fixed (execnode resets to genesis when its cursor outruns L1's
#   finalized tip). Bumped past 3 because gen-3 was briefly deployed to the seed box; gen-4 re-purges every node.
# 5 (2026-07-25): DETERMINISM FIX — block storage (block_by_num/block_by_hash) is REMOVED from the L1 state
#   root. Those DBs are written on block ARRIVAL and depend on a node's height, history-retention/pruning and
#   orphan bodies from reorgs — NOT on the canonical block sequence — so a catching-up node computed a
#   different as-of-parent root than the producer and tripped the (correctly FATAL) state-root gate at ~h62
#   (the alphanet-8 fresh-sync wedge). The root is now the consensus subset only (all tx-derived), invariant
#   to block storage; blocks stay secured by their own hash chain. State-root formula change ⇒ old gen-4
#   blocks are incompatible ⇒ full re-purge. See tests/test_seed_divergence.py::test_block_stores_excluded.
# 6 (2026-07-25): DETERMINISM FIX (continued) — the gen-5 block-storage exclusion was INCOMPLETE. Two more
#   node-local rows in the `meta` sub-DB also polluted the root: finalized_height (the FFG floor, advanced by
#   PEER CORROBORATION — a producer at tip>=FINALITY_DEPTH persists tip-FINALITY_DEPTH while a catching-up
#   node keeps 0) and pruned_below (the block-body prune watermark, advanced by LOCAL retention). The instant
#   finality first advanced, a producer and a fresh synchronizer at the same tip committed different
#   as-of-parent roots, so the FATAL gate refused block 47 (= FINALITY_DEPTH+2). Both are now excluded from
#   the root (ROOT_EXCLUDED_META_KEYS) while still carried in snapshots; every OTHER meta row stays in the
#   root (block-derived). Formula change ⇒ gen-5 block 47 is incompatible ⇒ full re-purge. See
#   tests/test_seed_divergence.py::test_node_local_meta_excluded_from_root.
# 7 (2026-07-26): ROLLBACK-ASYMMETRY FIX. The determinism bug was NOT in block application (a canonical
#   forward replay 4001→4260 from the 4000 snapshot reproduced the network root byte-for-byte) — it was that
#   rollback_one_block is not the exact inverse of incorporate_block for two `meta` rows, so any node that
#   ROLLS BACK (emergency-mode re-sync) drifts its root away from a forward-only node and the FATAL gate then
#   permanently refuses it. (a) execsum:<h>: incorporate writes it AND retention-prunes execsum:<h-960>, but
#   rollback never restores the pruned row → a rolled-back node holds a different execsum set. Now EXCLUDED
#   from the root (retention/rollback-path dependent, same class as block storage — ROOT_EXCLUDED_META_PREFIXES).
#   (b) divinflow:<epoch>: reverting the first inflow of an epoch left a phantom `=0` row (present != absent in
#   the root); dividend_inflow_add now meta_del's on zero. The alphanet-8 fleet wedged at h4260 when an
#   emergency rollback storm dropped execsum:3301..3305 on the catching-up nodes. Root-formula change (execsum
#   out) ⇒ gen-6 blocks incompatible ⇒ full re-purge. See tests/test_seed_divergence.py::
#   test_execsum_excluded_from_root and ::test_rollback_root_roundtrip.
# 8 (2026-07-26): DEEP-AUDIT SWEEP. A multi-wave audit (rollback symmetry across live blocks; non-block root
#   writers; consensus-identity hash inputs; encoding/float; concurrency; replay guards; exec/L2) closed the
#   remaining determinism vars:
#     - treasury_proposals -> ROOT_EXCLUDED_DBS: a write-only display index (no consensus reader), first-
#       writer-wins with no _del, so a reverted first-vote left a GHOST root row — a latent FATAL fork.
#     - codec.pack canonical (sort_keys): ATTEMPTED then REVERTED — it re-serialized existing account docs
#       to different bytes, changing the GENESIS state root and forking the gen-8 fleet away from the
#       un-updatable stranded (old-codec) nodes, which outweigh it -> wedge at block 1. Float/NaN defense
#       kept at the tx-admission gate instead. Do not re-add sort_keys until the old-codec nodes are retired.
#     - tvprev* (treasury re-vote revert journal) -> ROOT_EXCLUDED_META_PREFIXES: rollback bookkeeping does
#       not belong in the root (unbounded 2-rows/vote bloat; every other journal is _LOCAL_DBS).
#     - dedupe_reserved canonical (lowest txid, not arrival order) — two nodes built different blocks at one
#       height on a validator restart re-mint (recoverable, but needless reorg + upcoming_block_hash desync).
#     - tx `data` rejects floats (browser-reproducibility + integer-only invariant).
#     - read_state single MVCC snapshot (a torn per-sub-DB read made /state_health false-alarm).
#     - exec: settle gated on ExecState.window_canonical() — a settler on a pruned L1 / failed bootstrap has
#       a raised beacon/blockhash floor and would attest a divergent exec_root.
#     - asserted the settle-with-proof retention invariant (EXEC_SUMMARY_RETENTION > SPAN + FINALITY_DEPTH).
#   Root-formula + serialization change ⇒ gen-7 incompatible ⇒ full re-purge. Regression: test_seed_divergence
#   (treasury/tvprev exclusion, codec canonical, dedup, float, bridge/divinflow round-trips).
# 9 (2026-07-26): re-reroll ONLY to force a clean purge of the stale gen-8 blocks that were produced under
#   the briefly-live codec.pack sort_keys (reverted in c6a3c86). Those blocks committed a sorted-codec genesis
#   root (dba6a24a) that the reverted codec no longer computes, so the gen-8 marker (no re-purge on restart)
#   left the fleet wedged at block 2. Gen-9 = identical code to gen-8-minus-sort_keys, fresh genesis.
# 10 (2026-07-26): CLEAN-BREAK reroll — NEW CHAIN_ID + GENESIS_TIMESTAMP, so the genesis hash is finally
#   DISTINCT. Diagnosis: gen 7/8/9 all reused alphanet-8's genesis (only CHAIN_GENERATION moved), so two
#   stranded, un-updatable old-code nodes (103.236.77.189/.178, protocol 6) that share genesis 92302805 but
#   hold a COMPLETELY different 12600-block chain kept out-weighing our fresh chain in fork choice. Our nodes
#   selected them as sync donors, chased an unadoptable heavier tip, rolled back, failed, and repeated —
#   ~22 rollbacks/3min, "Consensus OUTSIDE majority (20% / 5 peers)", finality dragging, with ZERO state
#   divergence (they never actually adopted the foreign blocks). A distinct genesis removes them from the
#   linkage AND the chain_id-gated peer/status pool, which is exactly why gen-4 re-cut both constants.
# 11 (2026-07-27): SECURITY + DETERMINISM reroll (protocol 7, new CHAIN_ID + GENESIS_TIMESTAMP). Ships the
#   full audit remediation: the exec DA binding and the VM TIME opcode stop reading the uncommitted
#   block_timestamp (chain_clock instead); settle bounds exec_cursor to the block height (closing a
#   10-NADO permanent settlement-oracle capture that drained every escrow); faucet donations escrow where
#   they are redeemed; apply_slash books its burn; the snapshot payload is canonicalized and re-anchor +
#   fresh-bootstrap require a quorum with seed anchoring; strike attribution no longer benches honest
#   peers. Exec state semantics change (TIME), so exec state is rebuilt from the new genesis too.
# 12 (2026-07-27): RECURSIVE-FOLD reroll — activated the K->1 settlement fold. Since RE-GATED
#   (SETTLE_PROOF_RECURSIVE=False): the recursion path is still base-field (~47 bits) while the main path
#   reached 112, so accepting folds would have made the fold the weakest link in consensus.
# 13 (2026-07-28): AUX-EXT reroll — the aux (LogUp) Fiat-Shamir challenges beta/gamma move from the BASE
#   field to GF(p^2), taking that term from ~44 bits to 109. It was the LAST base-field draw and therefore
#   the one that actually bound the system: every aux_spec circuit (vm_circuit — the exec/settlement path —
#   and logup_bind) inherited it, so an attacker would have targeted 44 bits, not 112.
#   WHY A REROLL: settle proofs are re-verified on block APPLY (ops/transaction_ops.verify_settlement_sparse),
#   not only when first accepted. Every settlement already on chain was proven under base-field challenges,
#   so after this change a fresh sync would reject those blocks and no new node could ever bootstrap. The
#   proof format is not backward compatible and cannot be made so — the challenge field is what changed.
#   The extension-valued aux columns also widen the exec trace (each logical aux column becomes a base-column
#   PAIR), so the AIR geometry differs too.
# 16 (2026-08-03): RECORDS-BOUND SETTLEMENT reroll — new CHAIN_ID + GENESIS_TIMESTAMP, SETTLE_PROOF_RECORDS
#   on. Until now settle-with-proof covered only the KV half: the L1 composition pinned the SAME records
#   half into the pre and post root, so ANY span carrying a bridge deposit, faucet donation or treasury
#   payout fell back to the bonded quorum however good its proof was.
#   WHY A REROLL, and why this one is not a hot toggle even by the usual standard: it changes what is
#   WRITTEN, not merely what is checked. incorporate_block now commits each block's records EFFECTS into
#   its exec summary — the only prune-safe source the settle branch may read, since reading block BODIES
#   made one tx validate differently on a pruned node than an archive node and forked the fleet. Those
#   summaries live in the `meta` sub-DB, which FEEDS THE L1 STATE ROOT, so an upgraded node with the flag
#   on computes a different root than an unupgraded peer applying the identical block. Flipping it live
#   would not risk a fork, it would guarantee one.
#   DISTINCT GENESIS on purpose (the generation-10 lesson): bumping CHAIN_GENERATION alone leaves the
#   genesis hash shared, and stranded old-code nodes then keep out-weighing the fresh chain in fork choice.
#   Coverage fails closed: bridge deposit, faucet donation, treasury->faucet mirror. A value>0 call escrows
#   sender->cid BEFORE the VM runs and is refunded on revert, so its net effect is not a function of the
#   calldata; such a block is marked non-derivable and keeps riding the quorum.
# 17 (2026-08-06): VALUE-CALL ESCROW reroll — new CHAIN_ID + GENESIS_TIMESTAMP,
#   SETTLE_PROOF_RECORDS_VALUE_CALLS on. Generation 16 made the RECORDS half provable but excluded the one
#   family that matters in practice: a contract call carrying value>0. MEASURED over a full day on
#   alphanet-15, that exclusion was 91 of 146 settle refusals — "the RECORDS half moved" (36) and "crosses a
#   dividend epoch boundary" (55), which are ONE gate, because a dividend accrues at every boundary block
#   and moves records for exactly the reason the records gate names. Every call on that chain carried value
#   (all 25 game contracts; zero zero-value calls), so proof-carrying settlement could only ever cover
#   CALL-FREE spans — a couple of windows a day.
#   WHAT CHANGES: records_bind now derives a native value call's escrow (sender -v, cid +v as two
#   T_BRIDGE_BAL positions) instead of returning non-derivable. THE PROOF IS THE VERDICT — zkvm.ZkVMRevert
#   states that the interpreter reverts exactly where the AIR would have no satisfying witness, so a VALID
#   PROOF over a span already establishes every call in it succeeded, hence every escrow stuck, which IS a
#   pure function of the calldata.
#   WHY A REROLL, same reason as 16 and not a hot toggle: the derived effects are committed into each
#   block's exec summary in the `meta` sub-DB, which FEEDS THE L1 STATE ROOT. An upgraded node emitting
#   effects where an unupgraded peer wrote derivable=0 computes a different root from the identical block.
#   Flipping it live would not risk a fork, it would guarantee one.
#   DISTINCT GENESIS again (the generation-10 lesson): a CHAIN_GENERATION bump alone leaves the genesis hash
#   shared and stranded old-code nodes keep out-weighing the fresh chain in fork choice.
#   PREREQUISITE, already in (1fbf4c35): the argument needs "provable => what the chain actually did", and
#   that did NOT hold — settlement_proofs._run_call credited the contract without debiting the sender or
#   checking affordability, so it would prove a call the chain had SKIPPED. L1 never recomputes the exec
#   root, so its only check is post_full == root against the tx's OWN claim, which a proof over the wrong
#   state satisfies self-consistently. _run_call now mirrors the live escrow on both the native and asset
#   paths.
#   STILL NOT COVERED: a call the VM REVERTS or the chain SKIPS gets its escrow derived anyway and is
#   marked derivable, which is WRONG for that block — sound only because no valid proof can exist over such
#   a span, so it fails closed (see the flag's own comment). Presence-dividend accrual also moves records on
#   an epoch boundary with NO transaction at all, so a span crossing one is still refused.
# 18 (2026-08-09): KV CODE + PER-CALL ASSET BINDING reroll — new CHAIN_ID + GENESIS_TIMESTAMP. Closes a
#   settle-with-proof soundness hole: the KV half bound contract STORAGE but never the contract CODE, though a
#   cid is H(deployer, code, nonce). A settle-with-proof supplies its own pre_contracts code and the exec proof
#   runs it, so a bonded settler could prove an ARBITRARY storage transition over COUNTERFEIT code for a real
#   cid — real cid + real storage (matching sparse_pre_root) + fake code — and settle a KV root every honest
#   node disagrees with, self-consistently. FIX: exec_root.kv_projection AND settlement_sparse.sparse_projection
#   now commit a code leaf per contract (exec_state_bind.code_key -> code_commitment), so the pre-state pin
#   (sparse_root(pre_contracts) == the settled tip's KV half) authenticates the prover-supplied code — fabricated
#   code changes the KV root and fails to extend the tip. Same class also closed for the per-call `asset`
#   context: it was a public input the exec proof runs over but was absent from calls_commit.call_leaf, so a
#   value==0 asset call (records-inert, proof-settleable) could be proven under a SWAPPED asset with the DA
#   commitment still matching; call_leaf now binds it.
#   WHY A REROLL: both change the L1 STATE ROOT — kv_projection feeds it directly, and call_leaf feeds the exec
#   summaries in the `meta` sub-DB which also feeds the root. An upgraded node computes a different root than an
#   unupgraded peer applying the identical block, so this MUST ride a generation bump, never a hot toggle.
#   DISTINCT GENESIS (the generation-10 lesson): a CHAIN_GENERATION bump alone leaves the genesis hash shared and
#   stranded old-code nodes keep out-weighing the fresh chain in fork choice.
#   OPERATIONAL: a reroll wipes exec state — redeploy the game-contract fleet in the SAME session
#   (execnode.games.redeploy), or the games silently vanish.
# 19 (2026-08-11): BETANET LAUNCH reroll — new CHAIN_ID ("betanet-1") + new GENESIS_TIMESTAMP, so the
#   genesis hash is DISTINCT (the generation-10 lesson). The project leaves alpha: this genesis resets
#   EVERY balance and bonded stake to ZERO (genesis_data/genesis_alloc.dat emptied to [], TREASURY_GENESIS
#   still 0) — a clean fair relaunch, no premine, no carry-forward. Betanet behaves like mainnet (balances
#   persist across ordinary /update waves) but MAY still be rerolled while consensus hardens. Ships the
#   pre-launch security remediation (pubkey-once revert journal, settle query-count pinning, contract id
#   bounds, DoS scoping, ML-DSA negative-vector self-test). OPERATIONAL: redeploy the game-contract fleet
#   in the SAME session (execnode.games.redeploy) — the reroll wipes exec state and their old cids.
# 20 (2026-08-11): RE-CUT after the gen-19 launch SPLIT. betanet-1 forked 3 ways within 13 blocks
#   (h13 / h12 / h94, one identical genesis) because GENESIS_QUIET_MIN_PEERS was 2: two nodes reached each
#   other, released the first-block gate and started the chain while the other three were still on the old
#   generation. Each minority then finalized its own fork, and a finality floor on a minority fork cannot
#   roll back — unrecoverable without a wipe. FIX (the reason this reroll exists): the gate now requires a
#   MAJORITY of the fleet (GENESIS_QUIET_MIN_PEERS 2 -> 4) and waits 30 min (GENESIS_QUIET_S 600 -> 1800),
#   so a minority can never start the chain. New CHAIN_ID + GENESIS_TIMESTAMP so the split gen-19 chains
#   cannot linger in fork choice. Balances remain ZERO (empty alloc); prefixless producer set unchanged.
#   OPERATIONAL: redeploy the game contracts after regenesis (the gen-19 deploys died with that chain).
CHAIN_GENERATION = 21

# --- Data-availability blobs for the separate execution layer (doc/execution-layer.md, Phase 1) ---
# "blob": a keyless reserved recipient whose tx carries an OPAQUE payload in tx["data"]. L1 ORDERS and
# STORES it (and burns a DA fee) but NEVER decodes it — programmability lives one layer up, in separate
# execution nodes that replay these blobs in block order. This is the entire L1 surface for Phase 1:
# a fee-metered, size-capped, opaque byte channel. Contracts, the VM, and their state never touch
# consensus, so phone-mining and the base ledger are unaffected.
BLOB_MAX_BYTES = 512 * 1024       # per-tx opaque payload cap (canonical bytes) — bounds block growth.
                                  # 64K->512K so genuinely complex game contracts (e.g. battleship's on-chain
                                  # merkle-sum fleet verifier) deploy in one blob. This is a CEILING, not the norm:
                                  # game MOVES are ~hundreds of bytes; only rare one-time DEPLOYS approach it, and
                                  # blob spam is bounded economically by the burned DA fee. For a contract larger
                                  # than a whole block, the scalable path is a CHUNKED multi-blob deploy that the
                                  # exec node reassembles — not an ever-bigger cap that bloats phone-side DA.
# Per-BLOCK total-blob-bytes cap (doc/execution-layer.md §3.3): the sum of all blob payloads in one block
# is bounded so a single block cannot bloat data-availability beyond what phones download/relay. This is
# a CONSENSUS check (verify_block rejects an over-cap block; block assembly drops the excess).
MAX_BLOB_BYTES_PER_BLOCK = 1024 * 1024

# --- Aliases (human-readable names -> address; register / transfer / unregister on-chain) ---
# An alias lets a user send to a short name instead of the 49-char ndo address. Names are a scarce
# global namespace: 3..32 chars, lowercase [a-z0-9_-], must start with a letter, and must NOT be a
# reserved word or look like an address (ADDRESS_PREFIX/MSIG_PREFIX). Registration pays a higher fee (anti-squat); the
# owner can transfer or unregister it. See ops/alias_ops.py.
ALIAS_MIN_LEN = 3
ALIAS_MAX_LEN = 32
ALIAS_REGISTRATION_FEE = 10_000_000     # 0.001 NADO (10,000x MIN_TX_FEE): deters mass name-squatting

# The TREASURY is the GENESIS address (project owner's decision): the 10% per-block cut accrues
# here. It is a normal KEY-CONTROLLED address (the founder holds its key), derived here under the
# canonical (new) checksum from the genesis public-key body so it validates. It starts EMPTY —
# there is NO genesis allocation (TREASURY_GENESIS = 0 below); it only fills from the per-block cut.
_GENESIS_BODY = "27f2870bb2969a4d2b9d4eea303bedea996b9ccc93"  # genesis producer address (ML-DSA addr minus 4-hex checksum)
# ^ ADDRESS LITERAL: re-derived at any address-format switch (doc/address-format.md cutover step 4).
# DE-PREFIXED at alphanet-14. The pubkey BODY is unchanged, so the same key still owns this account — only
# the string changed (49+4 -> 42+4). Leaving the "mldsa44" on here would have been silent and total: the
# founder's key derives make_address(pk) = 42 hex + checksum, which can never equal a 53-char literal, so
# the treasury's own genesis address would have belonged to nobody.
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
TREASURY_SPEND_PERIOD = 14400   # burn cadence in blocks (~1 day at 6s blocks)
TREASURY_BURN_BPS = 100         # burn 1.00% of the balance above the floor each period
TREASURY_RUNWAY_FLOOR = 0       # balance at/below this is never burned (0 = burn from the first coin; tune up later)
REWARD_WINDOW = 100          # retained as the prune/rollback safety window (block_ops.prune_block_bodies);
                             # no longer a reward average — emission is now FLAT base * bond-elastic multiplier.
# FLAT per-block emission, scaled only by the bond-elastic multiplier (see BOND_ELASTIC_MULT_BPS below and
# doc/bond-elastic-emission.md). There is NO fee-weighted upside and NO ceiling: fees are DESTROYED, so
# raising emission with fees would mint more exactly when more is burned — softening the deflation. Because
# the multiplier m(r) <= 1, the block reward is BASE_SUBSIDY at most (the MAX emission/block) and
# m_min*BASE_SUBSIDY (~0.0166 NADO) at least — the perpetual tail, so production is never unincentivised (no
# hard cap, no security cliff). The base also lets a zero-coin OPEN-lane miner earn from block 1 (fair launch).
BASE_SUBSIDY = 1_000_000_000  # 0.1 NADO/block raw = MAX emission/block (~1,440 NADO/day at 6s blocks)

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
# A multisig address = make_address(blake2b([DOMAIN_MSIG, threshold, members]), MSIG_PREFIX) — the address IS
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
# the desktop wallet, and the browser light-miner. The dust floors below are DERIVED FROM THE FEE the
# auto tx actually pays (MIN_TX_FEE — there is no fee market; every fee check is a flat floor), so an
# auto tx only fires once the amount moved dwarfs its own fee (fee <= 0.01% of the amount) and the
# profitability guarantee survives any retune of MIN_TX_FEE. Purely client defaults — overridable freely.
AUTO_MIN_FEE_MULTIPLE = 10_000     # each auto tx must move >= this many times its own fee
AUTO_BOND_MIN_RAW = AUTO_MIN_FEE_MULTIPLE * MIN_TX_FEE     # 0.001 NADO at defaults: smallest worthwhile auto-bond
# Same floor for the presence-dividend auto-sweep: a `collect_dividend` blob burns MIN_TX_FEE, so the node
# only sweeps once its accrued dividend (read from the local exec node) reaches this — below it, the
# accrual just keeps growing fee-free until it's worth a tx.
AUTO_COLLECT_MIN_RAW = AUTO_MIN_FEE_MULTIPLE * MIN_TX_FEE  # 0.001 NADO at defaults: smallest sweep-worthy dividend
# Default auto-bond percentage applied when the operator/user has NOT chosen one (fresh node config,
# a browser with no saved preference, a new desktop wallet). Route this % of newly-mined spendable
# earnings into bonded stake out of the box, so miners join the capital-gated bonded lane hands-free
# without ever touching a setting. Still fully overridable (config / env / UI), and 0 explicitly = off.
#
# WHY 99 AND NOT 80 — the percentage does not decide who leads, BOND_CAP does, and a HIGHER percentage
# reaches that equaliser sooner for everyone. Measured on betanet-2's distribution (leader 33 of 42
# shares), time to reach the 1000 NADO cap:
#
#     pct    leader     1-share node    fresh node
#     20%     6.0 d        294.6 d        5952 d
#     80%     1.5 d         73.7 d        1488 d
#     99%     1.2 d         59.5 d        1203 d
#
# The leader caps almost immediately at ANY setting — it out-earns the field 33x, so no dial stops it
# arriving first. What the dial actually controls is how fast EVERYONE ELSE reaches the same ceiling, and
# past the cap extra stake buys no weight at all. So the setting that most limits how long one node can
# run ahead is the highest one that still leaves a node able to pay its fees — hence 99, with the
# liquidity reserve in core_loop.maybe_auto_bond holding back what a node needs to keep transacting.
#
# Note this is a CLIENT DEFAULT, not consensus: wallets and operators override it freely.
AUTO_BOND_DEFAULT_PERCENT = 99

# --- Rolling mode / history retention (NON-CONSENSUS node-local policy; see doc/rolling-mode-and-da.md) ---
# A "rolling" (pruned) node keeps STATE + a window of recent block BODIES and drops older bodies, so the
# ledger stops growing unbounded (keeps phones viable under adoption). Pruning body files is safe ONLY
# above the deepest lookback that re-reads a historical BODY on the consensus path — today that is
# rollback (bodies within FINALITY_DEPTH of the tip); the old get_block_reward lookback at
# tip-REWARD_WINDOW is GONE (emission is flat * bond-elastic, computed from committed state), and
# REWARD_WINDOW survives purely as extra safety margin in the prune floor. Hashes for the beacon/FFG
# come from the tiny number<->hash INDEX (always retained), NOT bodies. prune_block_bodies floors the
# retention at REWARD_WINDOW+FINALITY_DEPTH+1 so even a misconfigured tiny value cannot break rollback. This is a per-node choice (archive nodes keep everything); it changes NO block/hash.
# 100_800 blocks ~= 1 week of history at 6s blocks (7×14,400) — generous recent-body window while still
# bounding a rolling node's disk (the unbounded->bounded win); archive nodes keep everything.
# TX-HISTORY PRUNING FLOOR (rolling mode, non-consensus). The at-most-once replay guard reads the tx
# index, and a tx mined at height H can never be replayed past H + TX_LANDING_WINDOW, because its
# max_block cannot reach further (memserver admits only max_block <= tip + TX_LANDING_WINDOW). So the
# retained window has to clear TX_LANDING_WINDOW, plus FINALITY_DEPTH for a reorg that re-applies blocks,
# plus generous margin. 5000 blocks (~8 h at 6 s) is ~12x the strict requirement — cheap insurance on the
# one index whose loss could allow a replay, while still cutting the term that dominates disk at scale.
TX_HISTORY_MIN_RETENTION = 5000

HISTORY_RETENTION_BLOCKS = 100_800

# --- Mining: TWO-LANE diligence selection (PROVISIONAL — simulate before lock-in) ---
# Each epoch's slots split into an OPEN lane (anyone, zero coins) and a BONDED lane (locked stake).
# The split is a beacon-keyed permutation over slot indices, so the open lane is EXACTLY OPEN_BPS
# of blocks regardless of how many identities exist -> a zero-capital Sybil/botnet is structurally
# bounded to OPEN_BPS of production. See doc/mining.md and ops/mining_ops.py.
EPOCH_LENGTH = 60                  # slots per epoch (also the beacon/RANDAO epoch)

# Largest span (in exec cursors == L1 heights) one settle-with-proof may cover. Defined HERE, not with the
# other SETTLE_* constants above, only because it derives from EPOCH_LENGTH — Python needs the definition
# first. Bounds the work the DA binding does inside validate_transaction: a settle tx is cheap to make and
# the binding folds one stored exec summary per block in the span, so an unbounded span is a free
# validation-cost amplifier on every node. Also keeps the required summary window small enough that a
# snapshot-synced node reliably has it. A settler posts every SETTLE_EVERY (5) blocks, so 4 epochs is
# generous headroom for a lagging settler; a genuinely larger gap rides the bonded quorum instead.
SETTLE_PROOF_MAX_SPAN = 4 * EPOCH_LENGTH

# TRUSTLESS SETTLEMENT MASTER SWITCH (doc/zk-settlement-completion.md). When True, a settle-with-proof whose
# STARK proof verified at block-validation JUSTIFIES the exec root with NO bonded-quorum attestation
# (settlement_ops.settlement_justified), and the exec-summary derivation becomes FAIL-STOP instead of
# fail-swallow (core_loop) so a non-deterministic summary failure can never leave one node accepting a proof
# its peers reject. FALSE keeps the chain byte-identical to the quorum-only path — a proof still verifies and
# records its marker, but the marker is not honoured, so nothing regresses and no live behaviour changes.
# This is a CONSENSUS RULE: flipping it changes which settlements are valid, so it ships only at a
# CHAIN_GENERATION reroll (the settled-root scheme is genesis-level), never as a hot toggle. ENABLED on
# alphanet-11 (CHAIN_GENERATION 12). The prover stays OPT-IN per exec node (NADO_EXEC_SETTLE_PROVE); until a
# node opts in, no proof is posted and settlement continues via the bonded quorum exactly as before — so the
# reroll turns the capability ON without forcing the (heavy) proving on anyone.
SETTLE_PROOF_TRUSTLESS = True

# RECURSIVE (K→1) settle-with-proof acceptance. When ON, verify_settlement_sparse verifies ONE recursion bundle
# (recursive_verify) in place of the K per-segment exec stark.verify calls when a proof carries a `recursive`
# field. This is a CONSENSUS RULE and MUST ride a CHAIN_GENERATION reroll, NOT a hot toggle: a node honouring
# `recursive` SKIPS the classic per-segment exec check, so if it were live while unupgraded peers still ignore
# the field, an attacker could staple a bogus `recursive` blob onto an otherwise-valid settle tx and split the
# fleet (a new node REJECTS it via recursive_verify, an old node ACCEPTS it via the K-path — deep-audit finding
# 2026-07-27). FALSE ⇒ the `recursive` field is IGNORED and every node verifies segments the classic K-way, so
# a folded proof is accepted identically by folded- and unfolded-code nodes (no version-skew fork). Flip to True
# only at a reroll, once the whole fleet runs the recursion-aware verifier from genesis.
SETTLE_PROOF_RECURSIVE = True    # ENABLED at the alphanet-14 reroll: the in-circuit recursion AIRs
                                 # (fri_verify, comp_verify, rowcomp_verify) now carry GF(p^3)
                                 # arithmetic, so a folded proof no longer carries the old ~47-bit
                                 # commit bound while the rest of the system claims far more. This is
                                 # a CONSENSUS RULE and rides the reroll rather than a hot toggle: a
                                 # node honouring `recursive` skips the classic per-segment check, so
                                 # flipping it while unupgraded peers ignore the field would let an
                                 # attacker staple a bogus blob onto a valid settle tx and split the
                                 # fleet.

# ---- SETTLEMENT FOLD FAN-IN (execnode/stark/recursive_verify_hetero.prove_hetero) -------------------
# How many inner FRI proofs ONE recursion node may fold. 0/None = the old single bundle: one prove_fold
# over ALL of them.
#
# WHY THIS EXISTS. The single bundle's PROVER trace is LINEAR IN K. Measured 2026-08-05 on the settlement
# aggregation path (depth 4, 4 inner queries): the recursion AIR spends ~65,536 rows per folded proof —
# 96 segments x 1088 rows at K=2 — because it re-hashes every Merkle path of every FRI query of every
# inner proof in-circuit:
#     K=2 -> T=131,072    K=4 -> T=262,144    K=8 -> T=524,288    (only 20.3% of that is 2^n padding)
# The "O(1) settlement crypto" in doc/zk-recursion.md is the VERIFIER's cost — one bundle instead of K
# proofs. The PROVER's trace was never O(1), and in production that is fatal: once the game contracts were
# deployed, 48 exec calls put K in the dozens and T in the millions, and the settle prove blew
# SETTLE_PROVE_TIMEOUT=1200s at 2.8 GB RSS and still climbing, so NO proof was produced at all.
#
# Folding through recursion_depth.fold_tree bounds each node's trace by the FAN-IN instead of by K, keeps
# memory bounded, and leaves the nodes within a level independent. The root is still ONE proof, so the
# verifier's cost is unchanged.
#
# CONSENSUS RULE: it changes the SHAPE of the bundle (a "tree" instead of a "fold"), so a node that folds
# as a tree while its peers expect a single fold produces a settle those peers cannot verify. The whole
# fleet must therefore carry this before it is used.
#
# BUT IT DOES NOT NEED A REROLL, unlike SETTLE_PROOF_RECURSIVE. That one rode a reroll because settle
# proofs are re-verified on block APPLY (ops/transaction_ops.verify_settlement_sparse), so a chain already
# CONTAINING proofs judged under the old rule would fail to resync under the new one. Here there is no such
# history: when this was written no settle proof had ever landed, so nothing on chain needed re-verifying
# under the new shape and a coordinated /update wave was sufficient.
# *** THAT ARGUMENT HAS NOW EXPIRED — IT SAID SO ITSELF, AND THE CONDITION IT NAMED HAS HAPPENED. ***
# alphanet-15 went on to carry proof-carrying settles (blocks 43153, 46766, 47078), so the chain DOES hold
# bundles of a given shape. From here, changing the fold/proof shape REQUIRES a reroll like any other
# apply-time verification rule. alphanet-16 starts clean, so the same clock restarts at its genesis.
SETTLE_FOLD_FAN_IN = 2

# ---- INLINE PROOF CEILING ---------------------------------------------------------------------------
# The largest transaction the network will accept, and therefore the largest settle proof that can ride
# INSIDE the tx instead of going through DA.
#
# WHY THIS EXISTS. A settle proof went to DA purely because it did not fit in a transaction, and the DA
# route then could not deliver it: measured 2026-08-05/06, a peer must pull the whole ~120 MiB from the
# ONLY node in the fleet that runs a DA store (the three peers run just `nado`, not `nado-exec`, so
# :9273 is dead on all of them) inside _fetch_da_proof's 8 s budget. It never arrived, every peer raised
# ProofUnavailable, and for the whole life of the DA route not one proof-carrying settle ever landed.
# Erasure coding k=4/n=8 cannot help when there is exactly one provider.
# INLINING FIXED IT, and then the proof stopped being large at all: row-committing the trace (1affffac)
# took it from 120.31 MiB to 8.92 MiB, so blocks 46766 and 47078 carried proofs in ~9.74 MiB blocks. The
# ceiling below is now enormous headroom rather than a binding limit — keep it, because the thing that made
# it necessary (a producer-side default) could return, and a cap that is never hit costs nothing.
#
# Inlining removes that entire failure mode: the proof travels with the tx over the gossip the fleet
# already runs, so there is no fetch, no budget, and no dependency on peers running a DA node.
#
# THE OLD CAPS WERE NOT A PROTOCOL FACT, despite the comment on SETTLE_INLINE_MAX saying so. The binding
# limit was MAX_TX_BODY = 1 MiB in ops/net_ops.py — aiohttp's default, chosen as a DoS bound — and it was
# already INCONSISTENT with SETTLE_INLINE_MAX = 7 MiB, which could never have been submitted. Nothing in
# consensus constrains transaction size; block_ops has no size rule at all.
#
# COST, stated plainly: blocks carrying a proof get large, so sync and gossip move real bytes. That is a
# deliberate alphanet trade — a proof that lands beats a smaller one that cannot. The fold (see
# SETTLE_FOLD_FAN_IN) is what brings the size back down; this ceiling is what stops size from being the
# thing that blocks settlement in the meantime.
MAX_INLINE_TX_BYTES = 192 << 20          # 192 MiB — comfortably over the ~120 MiB an UNFOLDED proof measures

# ---- RECORDS-BOUND SETTLEMENT (execnode/stark/records_bind.py) --------------------------------------
# A settle-with-proof has always covered only the KV half of the exec root; the L1 composition pins the
# SAME records half into the pre and post root, so a proven span REQUIRES records to be unchanged
# (calls_commit.block_records_inert enforces it). That is why any span carrying a bridge deposit, a
# faucet donation or a treasury payout falls back to the bonded quorum however good its proof is.
#
# TRUE ⇒ (a) incorporate_block commits each block's RECORDS-HALF EFFECTS into its exec summary, so a
# verifier can derive them WITHOUT reading a prunable body (the whole reason records_bind was unreachable
# — bodies made one tx validate differently on a pruned node than an archive node and forked the fleet);
# and (b) the settle branch accepts a proof whose records half MOVED, provided it carries a records
# transition proving exactly those committed effects (records_bind.bind_and_verify_records).
#
# THIS RIDES A REROLL, and unlike SETTLE_PROOF_RECURSIVE it is not merely a rule change — it changes what
# is WRITTEN. exec summaries live in the `meta` sub-DB, which FEEDS THE L1 STATE ROOT, so an upgraded node
# with the flag on computes a different root than an unupgraded peer applying the identical block. Flipping
# it on a live chain does not risk a fork, it GUARANTEES one. Every node must start from a fresh genesis
# with the same setting, which is what a CHAIN_GENERATION bump provides.
#
# Coverage is deliberately partial and FAILS CLOSED: only effects derivable from committed block data
# alone (bridge deposit, faucet donation, treasury->faucet mirror). A value>0 call escrows sender->cid
# BEFORE the VM runs and is refunded on revert, so its net effect is not a function of the calldata; that
# block is marked non-derivable and keeps riding the quorum, exactly as an unknown blob op does.
SETTLE_PROOF_RECORDS = True     # ENABLED at the alphanet-15 reroll — see generation 16 in the log below.

# ---- VALUE-CALL ESCROW DERIVATION (records_bind.block_records_effects) ------------------------------
# Extends the coverage above to the one family that actually matters in practice: a contract call carrying
# value>0.
#
# WHY IT WAS EXCLUDED, and why that is now solvable. The escrow (sender -> cid, two T_BRIDGE_BAL positions)
# happens BEFORE the VM runs and is REFUNDED if the call reverts, so its NET effect is not a function of
# the calldata — you need to know whether the call succeeded. records_bind says exactly this: "deriving it
# needs the exec proof's own verdict".
#
# THE PROOF *IS* THE VERDICT. zkvm.ZkVMRevert states the invariant: "the interpreter reverts exactly where
# the AIR constraints would have no satisfying witness, so 'provable' and 'executes successfully' are the
# same set of calls." So a VALID PROOF over a span already establishes that every call in it succeeded —
# hence every escrow stuck, with no refund, which IS a pure function of the calldata. And `derivable` is
# only ever CONSULTED while a settle proof is being validated (calls_commit.verify_calls_bound_to_summaries,
# guarded by `records_out is not None`), so a span that never gets a proof rides the bonded quorum exactly
# as before.
#
# THE PREREQUISITE IS ALREADY IN (1fbf4c35). The argument needs "provable => what the chain actually did",
# and that did NOT hold: settlement_proofs._run_call credited the contract without debiting the sender or
# checking affordability, so it would prove a call the chain had SKIPPED. L1 never recomputes the exec root
# (verifying the proof is what replaces re-execution), so its only check is `post_full == root` against the
# tx's OWN claim — a proof over the wrong state satisfies that self-consistently. _run_call now mirrors the
# live escrow rule for both the native and asset paths.
#
# WHY IT COSTS A REROLL, not a flag flip: exec summaries live in the `meta` sub-DB, which FEEDS THE L1 STATE
# ROOT. Emitting effects where we previously wrote `derivable=0` changes the root on upgraded nodes only,
# which does not risk a fork — it guarantees one. Same reasoning as SETTLE_PROOF_RECORDS above.
#
# WHAT IT BUYS, measured 2026-08-06 over a two-hour window: 14 of 18 skipped spans (78%) were refused for
# "the RECORDS half moved across the span", and every one of the chain's calls carries value (all 25 game
# contracts call with value; zero zero-value calls exist). So today the fold needs exactly the calls that
# make a span unprovable. This is what unblocks that.
#
# STILL NOT COVERED after this: presence-dividend accrual moves records on an EPOCH boundary with no
# transaction at all, so the separate refusal of any span crossing one remains.
#
# WHAT THE FLAG DOES NOT FIX, stated here so nobody reads it as more than it is. The derivation emits the
# escrow for EVERY value call, including one the VM REVERTS or the chain SKIPS — for those the chain
# refunds, so the derived effects are WRONG and the block is nonetheless marked derivable. That is sound
# only because of the same invariant the flag rests on: `provable` and `executes successfully` are the SAME
# set of calls (zkvm.ZkVMRevert), so NO valid proof exists over a span containing such a call —
# settlement_proofs._run_call raises and vm_circuit.prove_epoch_calls raises. The wrong derivation can
# therefore only ever cause a REFUSAL, never the acceptance of a false root. It fails closed.
# The consequence is that a reverting call still costs the whole span, which is NOT fixed here and cannot
# be fixed by a flag: it needs either an AIR that proves a reverting execution, or a verifier able to
# RE-DERIVE which calls were no-ops — and the L1 cannot, because it never executes contracts. Narrowing the
# span to the clean prefix (2d4bcccf's pre-flight) is the mitigation that ships today.
SETTLE_PROOF_RECORDS_VALUE_CALLS = True    # ENABLED at the alphanet-16 reroll — see generation 17 below.

# PAYOUTS IN-PROOF — ALWAYS ON, no switch. A PAY opcode moves bridge balances, and a payout is an
# EXECUTION outcome that never appears in the calldata, so block_records_effects (which runs at incorporate
# time on a node that does not execute contracts) is structurally blind to it. Every span containing one
# used to be refused outright and left to the bonded quorum.
#
# Both halves now derive it from the same reader (runtimes.split_io): the VERIFIER from the proof's own io
# log (records_bind.pay_effects_from_proof), which the STARK commits to and which
# settlement_proofs._run_call already raises on for revert/over-pay under the live rules; the PROVER from a
# dry-run of the same calls (settlement_proofs.span_payout_effects), so the records half it proves contains
# exactly what the verifier will expect.
#
# It shipped without a flag on purpose. A dormant switch is a second code path nobody exercises, and this
# one was introduced at the only moment it is free to enable: every settle-prove on alphanet-16 has run with
# calls=0, so no span on chain contains a payout for a mixed fleet to disagree about.

# ---- DEPTH-GATED PROOF VERIFICATION (doc/settle-proof-transport.md §4, option 1) --------------------
# A settle proof is ~97 MiB against a ~256 KiB block, so it cannot ride in the block and must be fetched.
# Re-fetching and re-verifying one per settle across all of history would make joining the network cost
# hundreds of GiB, so verification is gated to blocks still within FINALITY_DEPTH of the known tip; deeper
# blocks are accepted on accumulated weight.
#
# THE COST, stated rather than buried: a from-genesis sync no longer independently verifies historical
# settlements, it INHERITS them from whoever was online when the block was at the tip. That is the same
# weak-subjectivity the chain already accepts for snapshot bootstrap ("classic weak-subjectivity
# checkpoint"), now extended to settlement. It was chosen deliberately over three alternatives — a DA fetch
# inside consensus validation, leaning on the quorum path, and waiting for recursion — each of which is
# written up with its objection in the doc.
#
# IT CANNOT FORK THE FLEET: the gate only ever RELAXES, so two nodes disagreeing about depth disagree as
# "strict rejects / relaxed accepts" and diverge only on an INVALID proof — which cannot reach a deep block,
# because the nodes that saw it at the tip were strict and rejected it there.
#
# Setting this False restores unconditional verification (correct, and unusable at 97 MiB/settle).
SETTLE_PROOF_DEPTH_GATED = True

# ---- SIGNATURE AGGREGATION (doc/zk-signature-aggregation.md) ----------------------------------------
# The AUTHORIZATION COMMITMENT is unconditional from alphanet-14: every block commits (auth_root,
# auth_count) inside its hash preimage and every verifier recomputes both from the block's own
# transactions. That is a pure function of committed block data, so it costs nothing and can never
# disagree between honest nodes — it exists so an aggregate proof has a statement it cannot choose.
#
# SIGNATURE AGGREGATION WAS REMOVED (it never shipped; SIG_AGG_STARK was always False).
# The block-level auth COMMITMENT stays and is unaffected: every block still binds (auth_root, auth_count)
# into its hash preimage and every verifier recomputes both from the block's own transactions. That is a
# pure function of committed block data, costs nothing, and is what mldsa_block_auth provides.
#
# What went, and why, measured rather than argued: ONE ML-DSA-44 signature verifies natively in 120 us and
# occupies 2420 bytes. Proving the butterfly half of a single signature's w' took 7.11 min, produced a
# 1.87 MB proof and 6.98 s to verify -- ~770x the size and ~58,000x the verify time of what it replaced.
# Aggregation only pays by amortising, and break-even was ~116 signatures for size / ~12 for verify against
# a trace-row budget that capped a batch near 7. ZK earns its keep when CHECKING is far cheaper than DOING;
# signature verification is already cheap, so there was no asymmetry to exploit.
#
# The right shape was already built: settlement_proofs proves an entire epoch as ONE zkVM trace and L1
# verifies it in ~0.3 s INDEPENDENT of the call count, replacing RE-EXECUTION -- which is genuinely
# expensive. That is SETTLE_PROOF_RECURSIVE, enabled at the alphanet-14 reroll.


# How many recent heights keep an exec summary (kv_ops.exec_summary_*). These live in the `meta` sub-DB,
# which IS carried in SNAPSHOT_DBS, so without a bound they would grow with chain length AND bloat every
# snapshot. A settle-with-proof span is capped at SETTLE_PROOF_MAX_SPAN, so any span reaching further back
# than this is refused by the cap regardless of whether the summary survives — dropping below the window
# costs nothing a proof could have used. 4x the cap leaves generous room for a lagging settler; if
# settlement falls further behind than this, proof-settlement simply yields to the bonded quorum until it
# catches up (a liveness fallback, never a soundness question). Far below FINALITY_DEPTH's reorg reach, so
# a GC'd height can never be rolled back and rollback never needs to restore one.
EXEC_SUMMARY_RETENTION = 4 * SETTLE_PROOF_MAX_SPAN
# (a LOAD-BEARING invariant tying this to SETTLE_PROOF_MAX_SPAN + FINALITY_DEPTH is asserted below, once
#  FINALITY_DEPTH is defined — see the assert after FINALITY_DEPTH.)

# How often the node reconciles its conservation invariants (ops/invariants.py). Every block would rescan
# the whole account table; once an epoch is frequent enough that a mint is caught within minutes while
# costing one scan per EPOCH_LENGTH blocks. Purely a detector cadence — NOT consensus-critical, so nodes
# disagreeing on it cannot fork (nothing reads the result but the operator and /invariants).
INVARIANT_CHECK_BLOCKS = EPOCH_LENGTH

# DEAD-FORK ESCAPE (loops/core_loop._maybe_escape_dead_fork). A node whose FINALIZED prefix is on a
# minority fork cannot heal by any local route — finality refuses the rollback and re-anchor needs a
# snapshot above a floor that is itself wrong. The escape is purge+resync, which destroys chain-derived
# data, so the trigger is deliberately slow and needs corroboration: the tip must have been frozen this
# long, and this many INDEPENDENTLY-ASKED peers must report a different block at our finalized height with
# none agreeing. A healthy node never comes close; the live wedge sat frozen for 40+ minutes.
DEAD_FORK_STALL_S = 900          # 15 min of a completely frozen tip before the question is even asked
DEAD_FORK_COOLDOWN_S = 1800      # at most one purge attempt per 30 min
DEAD_FORK_QUORUM = 2             # distinct peers that must disagree at our finalized height
# How long a node must be CONTINUOUSLY isolated — stranded, measured DEAD_FORK, and not one peer agreeing —
# before that overrides the "heavier side does not yield" veto.
#
# Without this a lone forker can never heal. Measured live on alphanet-15 (2026-08-03), node .131:
# stranded=True, fork_state=dead_fork, agree=[], disagree=2 ... but peers_asked=3, so `unanimous` was False
# because ONE peer never answered, and being the heavy side (a lone miner always is — it wins every slot
# unopposed) the weight rule vetoed the purge. Both escape hatches were shut by a single silent peer, and
# the node forked indefinitely with its lead WIDENING.
#
# The symmetric-split storm this protects against cannot reach here: in a real split each side still has
# partners that AGREE with it, and the trigger requires agree == [] — genuinely alone among everyone who
# answered. A transient partition also clears well inside the window, whereas a true strand never does.
# And a wrong purge costs time, not safety: the resync validates every block it accepts.
DEAD_FORK_ALONE_S = 3600         # 1h continuously alone -> purge even if our branch is heavier
# GENESIS COLD-START QUIET PERIOD — the reroll race.
#
# THIS IS THE DEFECT THAT SPLIT alphanet-13. Every node purges and restarts at a reroll, but they do not
# restart together: on 2026-07-28 185.100.232.5 came back ~4 minutes before the rest, found an empty peer
# table, and started mining block 1 from the shared genesis on its own. By the time the others were up it
# sat at tip 273 / weight 88725 against their 217 / 70525 — already PAST the 45-block finality depth, so no
# rollback could reconcile the two branches and the fleet stayed split until it was rerolled again.
#
# Nothing in the ordinary gates catches this, because at a reroll every gate is trivially satisfied: the
# caught-up gate (peer_claims_heavier_tip) can see no heavier tip when every node is at height 0, and the
# peer-count gate passes vacuously wherever an operator has set min_peers = 0 for solo production — which is
# the live setting on more than one fleet node.
#
# So gate the one moment that matters: producing THE FIRST BLOCK of a chain. A node at height 0 that knows
# of seed peers but has reached none of them has no evidence it is alone — only evidence that it is early.
# Wait for the mesh, then start together.
#
# BOUNDED, so this can never brick a node: once GENESIS_QUIET_S has elapsed the node produces regardless.
# A genuinely standalone deployment (no seeds configured, or none reachable) pays this delay exactly once,
# at genesis, and never again — the gate is dead the instant the chain has a single block.
GENESIS_QUIET_S = 1800           # 30 min: a /update wave restarts nodes MINUTES apart and a node that is
                                 # merely slow to pull must not be left behind by a chain that already started.
# MIN_PEERS was 2, and 2 IS NOT A MAJORITY. On the betanet-1 launch two nodes reached each other, released
# the gate, and minted block 1 while the other three were still finishing the OLD chain — a 3-way split
# (h13 / h12 / h94) with each minority's finality floor locked onto its own fork, which is unrecoverable
# without a wipe. The gate must require a MAJORITY of the known fleet, not any two nodes: a minority that
# starts the chain IS the fork. Seed-peer count is the fleet size estimate every node shares (genesis_open
# is the same file everywhere), so a majority of it is a quorum every node computes identically.
GENESIS_QUIET_MIN_PEERS = 2      # 2 PEERS = 3 nodes incl. self = a majority of the 5-node fleet. (Raising
                                 # this to 3/4 was a mis-derivation: 4 demands EVERY other node be linked at
                                 # once and the fleet sat at 3/4 with block 1 never minted. What actually
                                 # split betanet-1 was the GENERATION stagger — nodes still on the old chain
                                 # while others regenesied — plus the seed list missing two operator anchors
                                 # (see peer_ops.DEFAULT_SEED_PEERS), not this threshold.)

# How long a measured fork state stays cached. The probe costs ~log2(depth) direct peer round-trips, so it
# must not run every ~1s pass; but it gates reorg/re-anchor decisions, so it must not go badly stale either.
FORK_STATE_TTL_S = 60
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
# (raises FinalityViolation). The ordering max_rollbacks < FINALITY_DEPTH < EPOCH_LENGTH(60)
# guarantees: an honest reorg (<= max_rollbacks deep) never hits the floor, and a malicious/long-range
# reorg is capped below one epoch so the epoch-beacon anchor is un-reorgable. (The presence recert lease
# spans POSW_LEASE_EPOCHS, far beyond any rollback window, so a reorg can never strand a valid lease.)
#
# WIDENED 12 -> 45 (2026-07-19). At 6s blocks a depth of 12 froze history after SEVENTY-TWO SECONDS: any
# partition lasting longer than that finalized both sides onto incompatible histories, after which no
# rollback could ever reconcile them and the only route back was a snapshot re-anchor. That is exactly how
# the network split three ways, each side producing its own chain from a common ancestor ~4000 blocks back.
# 45 gives a 4.5-minute window — long enough to ride out an ordinary network hiccup, still comfortably
# inside one epoch (60) so the epoch-beacon anchor stays un-reorgable and long-range reorgs stay capped.
FINALITY_DEPTH = 45

# LOAD-BEARING CONSENSUS INVARIANT (asserted): settle-with-proof validation (transaction_ops.validate_
# transaction) reads exec_summary_get(h) for every height in a proof's span, but `execsum:` rows are EXCLUDED
# from the state root (retention/rollback-path dependent). A node lacking a needed summary would REJECT a
# settle-with-proof block its peers accept — a FATAL validity fork. Safe ONLY while the retention window
# strictly covers the widest span a reorg can still expose: a proof span is capped at SETTLE_PROOF_MAX_SPAN
# and no reorg reaches deeper than FINALITY_DEPTH, so a summary a valid proof could need is never GC'd iff:
# NOTE: a bare `assert` is stripped by `python -O`, and this guard protects a FATAL validity fork — so it
# raises explicitly instead.
if not EXEC_SUMMARY_RETENTION > SETTLE_PROOF_MAX_SPAN + FINALITY_DEPTH:
    raise RuntimeError(
        f"exec-summary retention {EXEC_SUMMARY_RETENTION} must exceed settle-proof span "
        f"{SETTLE_PROOF_MAX_SPAN} + finality depth {FINALITY_DEPTH} — else settle-with-proof validation "
        f"reads a GC'd (root-excluded) summary and forks block validity")

# Bonded lane: locked refundable stake, split-neutral, per-identity capped.
B_MIN = 100_000_000_000            # 10 NADO: capital per bonded selection share (staking-lane entry).
                                   # LOWERED 100x from 1,000 NADO: on a fair launch nobody can grind 1,000
                                   # NADO to become a validator, which left the bonded lane empty and the
                                   # chain running on the zero-stake open-lane fallback. 10 NADO is reachable
                                   # by an ordinary miner yet still real skin-in-the-game (Sybil in the bonded
                                   # lane costs 10 NADO × shares, locked + slashable — unlike the free open lane).
BOND_CAP = 10_000_000_000_000      # 1,000 NADO: max effective bond per identity (100x B_MIN)
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
BOND_UNLOCK_DELAY = 14400          # blocks a bond stays locked after an unbond request = ONE DAY at the
                                   # 6s target. It was 1440, which reads like "a day" only if you assume
                                   # 60s blocks — at the real block time that is 2.4 hours, far too short
                                   # for the thing it exists to do (give the network time to react to a
                                   # validator pulling stake). CONSENSUS PARAMETER: every node must agree,
                                   # because the release_block it computes goes into account state.
                                   # Already-recorded pending unbonds store an ABSOLUTE release_block, so
                                   # nothing in flight is retroactively extended.
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

# --- Idle-account GC (CONSENSUS — deterministic in-block sweeps at epoch boundaries; ops/gc_ops.py) ---
# Fee-exempt `register` writes permanent account docs + recert rows — the unbounded state-growth vector
# the audits flagged. Two decoupled sweeps run INSIDE the first block of each epoch's write txn, so every
# node mutates state identically (a local sweep would fork snapshot state roots):
#   1. ACCOUNT sweep: delete the account DOC of an address whose lease lapsed > GC_IDLE_EPOCHS ago and
#      whose doc is trivially empty (balance=bonded=produced=0, no schemaless extras like public_key /
#      kem_pub). Its recert ROWS are kept (dividend-weight history) until sweep 2 catches them.
#   2. RECERT-ROW retention: drop whole epoch buckets of recert rows older than RECERT_HISTORY_EPOCHS.
#      Weight safety: fidelity saturates at FIDELITY_CAP, and a continuous run is broken by any gap
#      > POSW_LEASE_EPOCHS — so reconstructing open_shares(fidelity_at_epoch(E)) needs at most
#      SATURATION_LOOKBACK_EPOCHS = (FIDELITY_CAP+1) * POSW_LEASE_EPOCHS of rows behind E: any run that
#      spans the retention horizon must contain >= RECERT_HISTORY/POSW_LEASE (> FIDELITY_CAP) recerts and
#      is therefore capped identically with or without the pre-horizon rows. Ancient epochs beyond that
#      are NOT reconstructible — cold-starting exec nodes bootstrap from a SETTLED checkpoint instead of
#      replaying from genesis (execnode NADO_EXEC_BOOTSTRAP; /get_open_weights refuses unsafe epochs).
# Both sweeps advance meta watermarks (consensus state) and are bounded per boundary (GC_MAX_PER_EPOCH)
# so a boundary block can never stall; revert records live in the NODE-LOCAL gc_revert sub-DB so a
# rollback of the boundary block restores every deleted row/doc exactly.
GC_IDLE_EPOCHS = 1000                    # lease lapsed this long (~4 days) -> empty account doc is GC-able
RECERT_HISTORY_EPOCHS = 10_000           # recert rows retained (~6 weeks) — >> SATURATION_LOOKBACK_EPOCHS
GC_MAX_PER_EPOCH = 2000                  # per-boundary work bound (rows+accounts touched)

# Continuity FIDELITY — now driven by the PoSW RECERT (the single presence signal; there is no separate
# heartbeat). Each continuous recert (gap <= POSW_LEASE_EPOCHS) adds FIDELITY_GAIN; a lapse RESETS the streak.
# So fidelity measures CONSECUTIVE recerts (≈ days of continuous presence). A churned/rotated Sybil cannot keep
# a ramp it stopped paying for. It is only a ~5x open-weight booster, NOT the Sybil bound (the 30% lane cap is).
FIDELITY_CAP = 30                  # consecutive recerts (~days) to fully ramp the open bonus
FIDELITY_GAIN = 1                  # per continuous recert

# FIDELITY WAS FARMABLE, and this is the fix. The gain above is per RECERT, and the only spacing rule
# anywhere is validate's "one register per epoch" — an epoch being 6 minutes. So the ramp the comment
# describes as "≈ days of continuous presence" could be completed in 30 epochs = 3 HOURS by recerting
# every epoch, taking open weight from 2 to 10 (a 5x producer-selection AND presence-dividend multiplier)
# for nothing but a ~1 s sequential PoSW each time — `register` is fee-exempt. Reported by a user who saw
# their fidelity rise by 4 in one day and asked why the documentation said 1.
#
# The signal is meant to measure ELAPSED CONTINUOUS PRESENCE, so a gain now also requires the recert to be
# spaced at least this far from the previous one. A closer recert still RENEWS THE LEASE (presence is
# unaffected, nobody is dropped for renewing early) — it simply earns no ramp. 192 epochs is exactly the
# browser miner's own renewal trigger (80% of the 240-epoch lease) and the node renews at 230, so both
# honest paths are untouched; only recerting faster than the lease requires stops paying.
#
# This also makes the documented rule true. doc/become-a-validator.md already told users "renewing early
# just pays the sequential proof more often for nothing" — which was FALSE under the old code, because
# early renewal bought +1 fidelity. It is true now.
FIDELITY_MIN_GAP_EPOCHS = 192

# UNCONDITIONAL — and it is only safe to be, because this ships WITH a genesis reroll.
#
# The rule was height-gated (epoch 862) while it was going to activate on a running chain, because
# dividend_ops.fidelity_at_epoch REPLAYS an address's whole recert history to reconstruct its weight as of
# a past epoch, and that replay must stay byte-identical to what the live ramp actually applied — a
# dividend fraud proof checks exactly that reconstruction, so an ungated change silently rewrites every
# historical weight and FALSE-SLASHES an honest settler.
#
# A reroll leaves NO pre-rule recert history, so there is nothing for the gate to protect. Removing it is
# strictly correct here, and strictly better than re-dating it: an activation epoch carried into a fresh
# chain lands days in, leaving fidelity farmable for exactly the window where an early weight advantage
# compounds most. account_ops.apply_register and dividend_ops.fidelity_at_epoch must stay in lockstep.
# deepest recert-row lookback any WEIGHT reconstruction needs (see the idle-GC note above):
# a run longer than this is fidelity-capped, so pre-horizon rows can never change open_shares.
SATURATION_LOOKBACK_EPOCHS = (FIDELITY_CAP + 1) * POSW_LEASE_EPOCHS

# Seed for the per-epoch selection beacon (S4.3). Epochs 0-1 use this fixed constant directly
# (no finalized prior epoch exists yet); epoch>=2 chains it with the hash of the first block of
# the previous epoch (see block_ops.epoch_beacon). Replacing this with the full on-chain
# commit-reveal RANDAO is the hardening step (mining_ops.compute_beacon already implements it).
DOMAIN_GENESIS_BEACON = "genesis-beacon-v1"
GENESIS_BEACON = blake2b_hash([DOMAIN_GENESIS_BEACON, CHAIN_ID])


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

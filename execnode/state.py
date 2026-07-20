"""
NADO execution-layer STATE (Phase 1). Holds every contract's code + storage and applies `blob` payloads
in L1 block order. Because the VM is deterministic and blobs are consumed in the order L1 fixed, any two
execution nodes that replay the same blobs reach a byte-identical state_root — that is what makes this a
sovereign *layer* (re-derivable from L1) rather than one server's private database (doc/execution-layer.md).

A blob payload is JSON:
  {"op": "deploy", "code": {<method>: <bytecode>}, "nonce": <any>}      -> deploys a contract
  {"op": "call",   "contract": "<cid>", "method": "<m>", "args": [...]} -> runs a method

State never affects L1 consensus. A malformed blob is skipped, never fatal.
"""
import json
import os
import threading

from hashing import blake2b_hash, canonical_bytes
from execnode.zkvm import ZkVMError
from execnode import runtimes   # pluggable contract-runtime registry (zkvm is the only runtime)
from execnode.shielded import ShieldedPool, apply_transfer
import base64
import zstandard as _zstd

# Contract code may arrive zstd-compressed as `codez` (base64 of a zstd frame) instead of raw `code`. The
# verbose JSON-opcode format is ~16-26x compressible, so a big verifier fits a small blob (battleship 110K->4.3K).
# Deterministic across nodes (zstd decode + json parse are canonical), and cid still hashes the DECODED code dict,
# so compression is transparent to the contract id. Decompress is STREAMING + bounded (anti zstd-bomb).
CONTRACT_CODE_MAX_BYTES = 4 * 1024 * 1024
def _bounded_unzstd(body, cap):
    dctx = _zstd.ZstdDecompressor(); parts, total = [], 0
    with dctx.stream_reader(body) as r:
        while True:
            ch = r.read(65536)
            if not ch: break
            total += len(ch)
            if total > cap: raise ValueError("contract code decompresses beyond cap")
            parts.append(ch)
    return b"".join(parts)
def _decode_code(payload):
    cz = payload.get("codez")
    if cz is None: return payload.get("code")
    return json.loads(_bounded_unzstd(base64.b64decode(cz), CONTRACT_CODE_MAX_BYTES))

# Coin-amount ceiling for shielded values/exits — far below the Goldilocks field size (P ≈ 2^64). The
# join-split circuit only constrains public_value/fee MODULO P, so without an absolute bound a wraparound
# (e.g. public_value = -P) proves as "balanced" yet would record a P-coin exit (C-3). Any real amount is
# many orders of magnitude below this, so bounding to it blocks every P·k residue while passing legit exits.
#
# C-3b: this MUST match the in-circuit range bound (2^61, top-3-bits-zero in c_rng_top). The 2-output
# join-split conserves v_in + public_value == v_out1 + v_out2 + fee; the worst-case |LHS - RHS| across the
# range-bounded values is 2*2^61 (two outputs) + 2^61 (fee) + 2^61 (|public_value|) = 2^63 < P, so mod-P
# conservation equals INTEGER conservation and no -P wraparound assignment exists. At 2^62 it did (a 1-coin
# input could record a 2^62-coin exit and drain the escrow).
MAX_EXIT_VALUE = 1 << 61


def _normalize_bundle(bundle):
    """Coerce a BROWSER-generated joinsplit2 bundle's stringified big field ints back to Python ints, IN
    PLACE, everywhere the verifier expects numbers. JS can't carry BigInt in JSON, so it serializes them as
    strings; the on-device proof now rides the DA layer and is applied via apply_blob->apply_field_transfer
    (no HTTP handler in between), so normalization MUST live here, not in a route. Idempotent — int() on an
    already-int is a no-op, so Python-generated bundles pass through untouched. No-op for non-joinsplit2."""
    js = (bundle.get("stark") or {}).get("joinsplit2")
    if not js:
        return
    for k in ("root", "nf", "cm_out1", "cm_out2", "public_value", "fee"):
        if k in js and js[k] is not None:
            js[k] = int(js[k])
    p = js.get("proof") or {}
    for f in ("T", "W", "N", "blowup", "deg_bound", "D"):
        if f in p:
            p[f] = int(p[f])
    fr = p.get("fri") or {}
    if "offset" in fr:
        fr["offset"] = int(fr["offset"])
    if "pow" in fr and fr["pow"] is not None:
        fr["pow"] = int(fr["pow"])                 # C-1 grinding nonce (JSON number -> int)
    if "final" in fr:
        fr["final"] = [int(x) for x in fr["final"]]
    for q in fr.get("queries", []):
        for s in q.get("steps", []):
            s["lo"] = int(s["lo"]); s["hi"] = int(s["hi"])
    for op in p.get("openings", []):
        for c in op.get("cols", []):
            c["cur"] = int(c["cur"]); c["nxt"] = int(c["nxt"])




# Fixed-name SYSTEM contracts (doc/faucet.md §4): literal cid -> the ONLY address allowed to deploy it.
# The operator key that deployed the game-contract fleet; a constant, so the rule is identical on every
# exec node replaying the same blob stream.
# alphanet-7 debrand: the SAME operator key, re-derived under the current ADDRESS_PREFIX (mldsa44…). The
# old ndo… string was a leftover of the pre-cutover prefix and blocked (re)deploying these system contracts.
FIXED_CIDS = {"faucet": "mldsa44ebd27698662f14ee2389e509781d5ff57487f4289afd34",
              "sovereign": "mldsa44ebd27698662f14ee2389e509781d5ff57487f4289afd34"}

# ---- ASSETS (doc/assets.md) ------------------------------------------------------------------------
# A fungible asset other than native NADO. There is exactly ONE ledger for them, at the exec layer, so an
# asset composes with the zkVM the way the bridge balance already does — a contract can hold, receive, move,
# mint and burn assets, and every one of those is a public io entry the settlement machinery replays.
#
# The id is DERIVED, never assigned: asset_id = alghash.hashn([issuer_digest, seed]). Two consequences that
# are the whole point: an issuer knows its asset's id before creating it, and a CONTRACT can compute the id
# of its own assets IN-CIRCUIT with the ordinary `hash` macro (`hash aid <- me seed`) — no registry lookup,
# no oracle, no id passed in on trust. That is what makes an AMM able to own its LP token and a launchpad
# able to own the token it launches.
ASSET_SUPPLY_CAP = 1 << 62      # every balance is <= total supply, so this keeps ALL asset amounts inside the
                                # RANGE window (2^62) that makes an in-contract `lt` on them sound. Without it
                                # a big-supply asset would silently produce unprovable/forgeable comparisons.
ASSET_NAME_MAX, ASSET_SYM_MAX, ASSET_DEC_MAX = 64, 12, 18
ASSET_URI_MAX = 128             # a metadata/logo pointer (an https/ipfs/ar URL). Capped short ON PURPOSE: a
                                # link, not inline data — 128 chars fits any real URL while making a
                                # multi-KB data: URI (which would bloat every committed metadata leaf) impossible.


def asset_id(issuer, seed):
    """The deterministic id of `issuer`'s asset number `seed` — the same field element the contract computes
    in-circuit as `hash aid <- me seed`. `issuer` is an L1 address / cid string."""
    from execnode.stark import alghash, field as _F
    return alghash.hashn([runtimes.zkvm_addr_digest(issuer), int(seed) % _F.P]) % _F.P


# ---- asset ledger: the money rules, in ONE place (doc/assets.md §8) --------------------------------------
# These operate on plain dicts (`abal` = {str(aid): {holder: bal}}, `assets` = {str(aid): meta}), so BOTH
# the live apply path (ExecState, on self.abal/self.assets) and the epoch prover's SHADOW
# (settlement_proofs._run_call, on throwaway copies) validate asset moves through the identical code. That
# is the whole point: mint authority, the supply cap and holder solvency can never drift between "what the
# chain applies" and "what a validity proof will settle" — a drift would let the prover prove a transition
# the chain reverts. The VM/AIR enforces only holder-side solvency; issuer-only / mintable-only / cap live
# HERE and nowhere else.
def asset_credit_dict(abal, aid, holder, delta):
    """Move signed `delta` on `holder`'s row of `aid`, pruning to canonical absence at zero."""
    key = str(aid)
    row = abal.setdefault(key, {})
    v = int(row.get(holder, 0)) + int(delta)
    if v:
        row[holder] = v
    else:
        row.pop(holder, None)
    if not row:
        abal.pop(key, None)


def stage_asset_effects_pure(abal, assets, actor, effects):
    """Validate a call's asset intents as ONE atomic batch against the plain-dict ledgers. Returns
    (ok, reason, deltas, supply_deltas) and mutates NOTHING — the caller commits only if every effect is
    legal, so a call that pays three assets and overdraws the fourth moves none of them."""
    deltas, sup = {}, {}

    def bal(aid, who):
        return int(abal.get(str(aid), {}).get(who, 0)) + deltas.get((aid, who), 0)

    for kind, aid, to, amt in effects:
        aid, amt = str(aid), int(amt)
        meta = assets.get(aid)
        if kind == "bal":
            # The ABAL read the VM logged must equal what the ledger says. On the apply path the exec node
            # supplied that value itself; the check earns its keep on the PROOF path, where the log is a
            # stranger's claim about a balance.
            if bal(aid, actor) != amt:
                return False, f"asset {aid[:12]}… balance read {amt} != ledger", {}, {}
            continue
        if amt == 0:
            continue                                      # a zero move is a no-op, not an error (as PAY 0 is)
        if amt < 0 or amt >= ASSET_SUPPLY_CAP:
            return False, "asset amount out of range", {}, {}
        if meta is None:
            return False, f"no such asset {aid[:12]}…", {}, {}
        if kind == "pay":
            if to is None:
                return False, "unresolvable asset recipient", {}, {}
            if bal(aid, actor) < amt:
                return False, f"asset {meta['sym']} payout {amt} > holding", {}, {}
            deltas[(aid, actor)] = deltas.get((aid, actor), 0) - amt
            deltas[(aid, to)] = deltas.get((aid, to), 0) + amt
        elif kind == "mint":
            if meta["issuer"] != actor:
                return False, f"only {meta['sym']}'s issuer may mint", {}, {}
            if not meta["mintable"]:
                return False, f"{meta['sym']} minting was renounced", {}, {}
            if to is None:
                return False, "unresolvable mint recipient", {}, {}
            if meta["supply"] + sup.get(aid, 0) + amt > ASSET_SUPPLY_CAP:
                return False, f"{meta['sym']} supply cap exceeded", {}, {}
            deltas[(aid, to)] = deltas.get((aid, to), 0) + amt
            sup[aid] = sup.get(aid, 0) + amt
        elif kind == "burn":
            if bal(aid, actor) < amt:
                return False, f"asset {meta['sym']} burn {amt} > holding", {}, {}
            deltas[(aid, actor)] = deltas.get((aid, actor), 0) - amt
            sup[aid] = sup.get(aid, 0) - amt
        else:
            return False, f"unknown asset effect {kind!r}", {}, {}
    return True, "", deltas, sup


def commit_asset_effects_pure(abal, assets, deltas, sup):
    """Apply what stage_asset_effects_pure validated. Never called without that validation."""
    for (aid, who), d in deltas.items():
        asset_credit_dict(abal, aid, who, d)
    for aid, d in sup.items():
        assets[aid]["supply"] += d


class ExecState:
    def __init__(self, path):
        """Initialise every state component empty, then load() the last snapshot from `path` if one
        exists — so a restarted exec node resumes from its persisted cursor instead of re-replaying L1."""
        self.path = path
        self.contracts = {}        # cid -> {"code": {...}, "storage": {mapname: {key: int}}, "deployer": addr}
        self.cursor = -1           # highest L1 block height fully applied
        self.block_ts = 0          # wall-clock timestamp of that block (the TIME opcode). Transient: derived
                                   # from each applied block, NOT committed to state_root — every node sets it
                                   # from the same finalized block, so TIME stays deterministic without it being
                                   # a root leaf. Defaults to 0 for a cold view before the first block is applied.
        self.bridge = {}           # addr -> exec-side bridged balance (credited by L1 `bridge` deposits)
        # ASSET LEDGER (doc/assets.md) — the second value type this layer knows about. Both halves are
        # committed in state_root (exec_root.records_projection), so an asset balance is as provable as a
        # bridge balance; unlike the bridge there is no L1 exit for them (an asset exists only here).
        self.assets = {}           # str(asset_id) -> {issuer, seed, name, sym, dec, supply, mintable, uri}
        self.abal = {}             # str(asset_id) -> {holder(addr or cid) -> balance}
        # DELEGATED SPEND (doc/assets.md §7a): owner authorises a spender (an address OR a cid) to move up to
        # `amount` of an asset on their behalf — the ERC-20 approve/allowance/transferFrom primitive. A blob
        # `asset_transfer_from` spends it account-to-account; the VM `APULL` opcode lets a CONTRACT pull it,
        # which is what a router/AMM standing-authorization actually needs. Committed in the root like a
        # balance, absence == zero.
        self.allow = {}            # str(asset_id) -> {owner -> {spender -> amount}}
        self.withdrawals = {}      # nonce(str) -> {"addr":.., "amount":..} : provable exit records
        self.wd_nonce = 0          # monotonic withdrawal-nonce counter (deterministic)
        # CROSS-DOMAIN OUTBOX: messages emitted by this layer (via the `emit` blob op), each committed as a
        # Merkle leaf in state_root and provable via outbox_proof(seq). This is the sound foundation for
        # cross-rollup / L1-bound messaging; CONSUMPTION (verifying against the sender's SETTLED root) is a
        # separate step, see doc/rollups-and-settlement.md §7.4. Keyed by seq; a message is GC'd once its
        # finalized xmsg delivery burns the (from_ns, seq) L1 nullifier (drop_consumed_outbox).
        self.outbox = {}           # str(seq) -> {"seq":i, "from":addr, "to_ns":ns, "data":<any>}
        self.outbox_seq = 0        # monotonic next-seq counter — seqs stay unique after consumed-msg GC
        # CROSS-DOMAIN INBOX: messages DELIVERED to this rollup by an L1-verified `xmsg` (verified against the
        # sender namespace's SETTLED root on L1). Committed in state_root so every receiver node agrees.
        self.inbox = []            # [{"from_ns":ns, "seq":i, "data":<any>}]
        # PRESENCE DIVIDEND (doc/presence-dividend.md): off-L1 accrual of the OPEN-lane DIVIDEND_POOL to the
        # currently-present miners, fidelity-weighted. `collect_dividend` burns a balance into a provable
        # withdrawal (same machinery as the bridge), claimed on L1 against the settled root.
        self.dividend = {}         # addr -> accrued (uncollected) dividend, raw
        self.last_div_epoch = -1   # highest fully-completed epoch already accrued (deterministic watermark)
        self.div_carry = 0         # undistributed remainder carried to the next accrual (no dust lost)
        self.dividend_withdrawals = {}  # nonce(str) -> {"addr":.., "amount":..} : provable dividend claims
        self.dw_nonce = 0          # monotonic dividend-withdrawal nonce counter (deterministic)
        # SHIELDED POOL (doc/privacy.md): a Zerocash-style commitment tree + nullifier set built from L1
        # `shield` deposits + `shielded_transfer` blobs. Only the pool ROOT + a nullifier DIGEST are committed
        # in state_root (compact — not one leaf per note/nullifier), so this scales independently of pool size.
        self.shielded = ShieldedPool()
        self.unshield_withdrawals = {}  # nonce(str) -> {"addr":.., "amount":..} : provable unshield exits
        self.uw_nonce = 0          # monotonic unshield-withdrawal nonce counter (deterministic)
        # PHASE-2 FIELD-NATIVE POOL (doc/privacy.md): notes over the STARK-friendly hash; the exec node acts as
        # a DELEGATED PROVER (client sends the witness -> exec builds the path + proves the full join-split).
        from execnode.shielded_field import FieldShieldedPool
        self.field_pool = FieldShieldedPool()
        # Shielded aggregate supply — see _restore. Note VALUES are private; every CHANGE to their total is
        # public, so the pool's total is auditable without seeing into it (ops/invariants.py).
        self.pool_value = 0        # live total value of all notes in both pools
        self.pool_fees = 0         # cumulative fee burned inside the pool (leaves the notes, not the escrow)
        # M-10: the delegated-prover POST handlers apply field transfers in worker threads
        # (asyncio.to_thread), so the nullifier check->add and the state serialization can run concurrently.
        # This reentrant lock makes the double-spend check + the mutation atomic, and gives save() a
        # consistent snapshot, so two racing identical unshields can't both record an exit.
        self._mutate_lock = threading.RLock()
        # RANDAO beacon (#randao): the exec node collects per-epoch reveal secrets from the finalized L1
        # blocks it replays and chains them into the same beacon consensus uses (ops.mining_ops.compute_beacon).
        # This is an L1-DERIVED input (like cursor), not exec state — so it is persisted for restart but NOT
        # committed to state_root. The BEACON opcode reads self.beacons; a game settles objectively from it
        # with NO player secret-reveal. beacons[E] is final once the cursor has entered epoch E.
        self.randao_reveals = {}   # epoch(int) -> set(secret hex) accumulated from `reveal` txs
        self.beacons = {}          # epoch(int) -> beacon(int), cached
        self.beacon_floor = None   # first epoch we witness in full (set on first advance) — below it, unavailable
        # BLOCKHASH randomness (#randao): finalized L1 block hashes, height(int) -> hash(int). Like the beacon this
        # is an L1-DERIVED input (identical on every node once finalized), persisted for restart but NOT committed
        # to state_root. The BLOCKHASH opcode reads it so a game can pin its result to a FUTURE height whose hash
        # nobody can predict at bet time. Bounded ring (recent heights only).
        self.block_hashes = {}     # height(int) -> block hash(int)
        # zkVM ADDRESS REGISTRY (doc/zk-execution-proofs.md): field digest -> L1 address, accumulated from
        # every zkvm call boundary (sender + string args). PAY(digest) resolves through it back to a real
        # bridge address. Derivable from the ordered blob stream (deterministic on every node) — persisted
        # for restart, NOT committed to state_root (like beacons/block_hashes; payouts already reflect in
        # committed bridge leaves).
        self.zk_addrs = {}        # str(field digest) -> addr
        # STATE-ROOT CACHE: state_root() is a pure function of the root-committed state. The root is the
        # FROZEN alphanet-6 scheme (execnode/exec_root.py): rnode(kv half, records half), two persistent
        # depth-256 sparse alghash2 trees that are DIFF-APPLIED per recompute — O(changed·depth) hashing
        # per block, never a whole-state rebuild (the cold build happens once, at load/bootstrap). Every
        # root-affecting mutator calls _touch() (under _mutate_lock) to invalidate the cached hex; the
        # trees themselves persist across touches. _mut_gen versions the whole state so the provisional
        # rebuild can skip cloning when nothing changed.
        self._root_cache = None
        self._kv_store = None            # persistent KV half-tree (lazy cold build, then incremental)
        self._rec_store = None           # persistent RECORDS half-tree
        self._mut_gen = 0
        self.load()

    def _touch(self):
        """Invalidate the root cache and bump the state version. Called by every mutator that can change
        the committed root (and by _restore). Safe on a bare instance (clone()) — the half-trees persist
        across touches and are diff-applied on the next state_root()."""
        self._root_cache = None
        self._mut_gen = getattr(self, "_mut_gen", 0) + 1
        if not hasattr(self, "_kv_store"):
            self._kv_store = None
            self._rec_store = None

    # --- persistence -----------------------------------------------------------------------------
    def _restore(self, d):
        """Populate every field from a payload dict (what load() does after json.load). Every key is
        optional with an empty default, so old snapshots (pre-dividend/shielded/…) still load AND it works
        on a bare (un-__init__'d) instance — see clone()."""
        from execnode.shielded_field import FieldShieldedPool
        self.contracts = d.get("contracts", {})
        self.cursor = d.get("cursor", -1)
        self.bridge = d.get("bridge", {})
        self.assets = d.get("assets", {})
        self.abal = {a: dict(h) for a, h in d.get("abal", {}).items()}
        self.allow = {a: {o: dict(s) for o, s in owners.items()} for a, owners in d.get("allow", {}).items()}
        self.withdrawals = d.get("withdrawals", {})
        self.wd_nonce = d.get("wd_nonce", 0)
        ob = d.get("outbox", {})
        if not isinstance(ob, dict):
            # NO legacy shapes on alphanet: a pre-dict outbox snapshot must not half-load — fail
            # loudly; the operator re-bootstraps from a settled checkpoint (NADO_EXEC_BOOTSTRAP).
            raise ValueError("exec state has a legacy outbox shape — re-bootstrap this node")
        self.outbox = ob
        # floor the counter at max(seq)+1 so seqs can never be reused after consumed-message GC
        self.outbox_seq = max(int(d.get("outbox_seq", 0)),
                              max((int(k) for k in ob), default=-1) + 1)
        self.inbox = d.get("inbox", [])
        self.dividend = d.get("dividend", {})
        self.last_div_epoch = d.get("last_div_epoch", -1)
        self.div_carry = d.get("div_carry", 0)
        self.dividend_withdrawals = d.get("dividend_withdrawals", {})
        self.dw_nonce = d.get("dw_nonce", 0)
        self.shielded = ShieldedPool.from_dict(d["shielded"]) if "shielded" in d else ShieldedPool()
        self.unshield_withdrawals = d.get("unshield_withdrawals", {})
        self.uw_nonce = d.get("uw_nonce", 0)
        self.field_pool = FieldShieldedPool.from_dict(d["field_pool"]) if "field_pool" in d else FieldShieldedPool()
        # SHIELDED SUPPLY (ops/invariants.py). Individual note VALUES are private, but every CHANGE to the
        # pool's total is public by construction — a deposit carries its L1 amount, and a transfer's
        # public_value/fee are public inputs. So the pool's aggregate value is auditable even though its
        # contents are not (the Zcash turnstile property). pool_value is the live note total; pool_fees is
        # the cumulative fee burned INSIDE the pool (value that leaves the notes but never leaves escrow).
        # Derived bookkeeping only — deliberately NOT in exec_root.records_projection, so it cannot change
        # the state root. Recomputed exactly on replay, so an old snapshot without it starts at 0 and is
        # re-derived from the blocks that follow.
        self.pool_value = int(d.get("pool_value", 0))
        self.pool_fees = int(d.get("pool_fees", 0))
        self.randao_reveals = {int(e): set(v) for e, v in d.get("randao_reveals", {}).items()}
        self.beacons = {int(e): int(v) for e, v in d.get("beacons", {}).items()}
        self.beacon_floor = d.get("beacon_floor")
        self.block_hashes = {int(h): int(v) for h, v in d.get("block_hashes", {}).items()}
        self.zk_addrs = d.get("zk_addrs", {})
        self._touch()          # also (re)creates the cache fields on a bare clone() instance

    def _snapshot(self):
        """The full serializable payload (identical to what save() writes), taken UNDER the mutate lock so a
        concurrent thread-apply can't tear it. Shared by save() and clone()."""
        with self._mutate_lock:
            return {"contracts": self.contracts, "cursor": self.cursor, "bridge": self.bridge,
                    "assets": self.assets, "abal": self.abal, "allow": self.allow,
                    "withdrawals": self.withdrawals, "wd_nonce": self.wd_nonce,
                    "outbox": self.outbox, "outbox_seq": self.outbox_seq, "inbox": self.inbox,
                    "dividend": self.dividend, "last_div_epoch": self.last_div_epoch,
                    "div_carry": self.div_carry, "dividend_withdrawals": self.dividend_withdrawals,
                    "dw_nonce": self.dw_nonce, "shielded": self.shielded.to_dict(),
                    "unshield_withdrawals": self.unshield_withdrawals, "uw_nonce": self.uw_nonce,
                    "field_pool": self.field_pool.to_dict(),
                    "pool_value": self.pool_value, "pool_fees": self.pool_fees,
                    "randao_reveals": {str(e): sorted(v) for e, v in self.randao_reveals.items()},
                    "beacons": {str(e): str(v) for e, v in self.beacons.items()}, "beacon_floor": self.beacon_floor,
                    "block_hashes": {str(h): str(v) for h, v in self.block_hashes.items()},
                    "zk_addrs": self.zk_addrs}

    def clone(self):
        """A deep, independent, DISK-FREE copy for provisional/speculative apply (the unfinalized L1 tail).
        The RLock is rebuilt fresh (locks aren't copyable) and __init__ is skipped so it never reads disk.
        Operations on the clone NEVER touch the finalized state — settlement/state_root/save stay exact."""
        import copy
        snap = copy.deepcopy(self._snapshot())
        c = ExecState.__new__(ExecState)
        c.path = self.path + "#prov"       # sentinel: a clone is display-only and must never be save()d
        c._mutate_lock = threading.RLock()
        c._restore(snap)
        return c

    def load(self):
        """Restore the last save()d snapshot from self.path, if any. A torn/empty file — e.g. a crash between
        os.replace and the data reaching disk — is treated as NO snapshot: the exec state is fully re-derivable
        by replaying L1, so re-bootstrap instead of crash-looping on json.load every start."""
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    d = json.load(f)
            except (ValueError, OSError):
                return
            self._restore(d)

    def save(self):
        """Atomically persist the whole state: snapshot under the mutate lock (consistent vs concurrent
        thread-applies), then write sorted-key JSON to a tmp file and os.replace it — a crash mid-write
        can never leave a torn state file."""
        # M-10: _snapshot() holds the mutate lock while building the payload so a concurrent thread-apply
        # can't mutate the nullifier set / commitment list mid-serialization (torn snapshot / "set changed
        # size during iteration").
        payload = self._snapshot()
        # '~tmp' (not '.tmp'): a namespace state path is STATE_PATH + '.' + ns and ns excludes '~', so this
        # temp can never equal another namespace's persistent path (a ns literally named 'tmp' would have
        # collided a '.tmp' temp and corrupted its state on every default save).
        tmp = self.path + "~tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())              # data on disk BEFORE the rename (os.replace is atomic, not durable)
        os.replace(tmp, self.path)
        try:                                  # fsync the directory so the rename itself survives a power loss
            dfd = os.open(os.path.dirname(self.path) or ".", os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass

    def _sparse_stores(self):
        """The two persistent depth-256 half-trees of the FROZEN root scheme (execnode/exec_root.py),
        diff-applied to the CURRENT state: contract storage in the KV half; bridged/dividend balances,
        withdrawal records, pool digests and cross-domain messages in the RECORDS half. Every honest node
        derives identical projections → identical root. Called ONLY under _mutate_lock (state_root), so a
        concurrent thread-apply can never tear the diff. First call is the cold build; afterwards each
        recompute hashes only what changed (O(changed·depth))."""
        from execnode import exec_root as ER
        from execnode.stark import storage_tree as SST
        kv_p = ER.kv_projection(self.contracts)
        rec_p = ER.records_projection(self)
        if self._kv_store is None:
            self._kv_store = SST.SparseStore(ER.DEPTH, kv_p)
            self._rec_store = SST.SparseStore(ER.DEPTH, rec_p)
        else:
            ER.apply_projection(self._kv_store, kv_p)
            ER.apply_projection(self._rec_store, rec_p)
        return self._kv_store, self._rec_store

    def unshields_for(self, addr):
        """Pending unshield exits recorded for an L1 address — a wallet uses this to find the nonce(s) of its
        own unshields, then fetches unshield_withdrawal_proof(nonce) to claim once the root is settled."""
        return [{"nonce": n, "amount": w["amount"]} for n, w in sorted(self.unshield_withdrawals.items())
                if w["addr"] == addr]

    def shielded_note_proof(self, cm):
        """Locate a note commitment in the pool and return its position + Merkle authentication path against
        the current root — what a wallet needs to SPEND the note (build the input witness). Commitments are
        public, so this leaks nothing about value/owner. None if the commitment isn't in the pool."""
        try:
            pos = self.shielded.commitments.index(cm)
        except ValueError:
            return None
        from execnode.shielded import merkle_path
        return {"pos": pos, "path": merkle_path(self.shielded.commitments, pos), "root": self.shielded.root()}

    def unshield_withdrawal_proof(self, nonce):
        """(addr, amount, nonce, proof) for a recorded unshield exit, provable against state_root; None if absent."""
        from execnode import exec_root as ER
        w = self.unshield_withdrawals.get(str(nonce))
        if not w:
            return None
        return {"addr": w["addr"], "amount": w["amount"], "nonce": str(nonce),
                "proof": self._record_proof(ER.T_UNSHIELD_WD, w["addr"], str(nonce))}

    def dividend_withdrawal_proof(self, nonce):
        """(addr, amount, nonce, proof) for a recorded dividend collection, provable against state_root."""
        from execnode import exec_root as ER
        w = self.dividend_withdrawals.get(str(nonce))
        if not w:
            return None
        return {"addr": w["addr"], "amount": w["amount"], "nonce": str(nonce),
                "proof": self._record_proof(ER.T_DIV_WD, w["addr"], str(nonce))}

    def accrue_dividend_epoch(self, inflow, weights):
        with self._mutate_lock:
            try:
                return self._accrue_dividend_epoch_inner(inflow, weights)
            finally:
                self._touch()

    def _accrue_dividend_epoch_inner(self, inflow, weights):
        """DETERMINISTIC per-epoch accrual. Distribute `inflow` — the TOTAL DIVIDEND_POOL inflow credited
        during one epoch (from L1 `dividend_inflow_get(E)`, revert-safe) — plus the carried remainder among
        `weights` = weights_at_epoch(E) (fidelity-weighted, from L1), pro-rata and integer-only. This is a
        PURE FUNCTION of (inflow, weights): every node that accrues the same epoch reaches the identical
        `dividend` map, so the committed state_root can't diverge (the old accrue_dividend read a LIVE pool
        balance + LIVE current-epoch weights per poll batch — non-deterministic, which broke settlement of
        the default layer). No present miners this epoch → the whole inflow carries forward (no raw lost).
        Returns the amount distributed. The caller advances last_div_epoch and never re-accrues an epoch."""
        pot = int(inflow) + self.div_carry
        total_w = sum(max(1, int(w)) for w in weights.values()) if weights else 0
        if pot <= 0 or total_w <= 0:
            self.div_carry = max(0, pot)                         # carry forward until there's a present set
            return 0
        distributed = 0
        for addr, w in sorted(weights.items()):                  # sorted -> deterministic across nodes
            share = pot * max(1, int(w)) // total_w
            if share:
                self.dividend[addr] = self.dividend.get(addr, 0) + share
                distributed += share
        self.div_carry = pot - distributed                       # keep the sub-unit remainder for next time
        return distributed

    def state_root(self):
        """THE settled execution-layer root (frozen alphanet-6 scheme, execnode/exec_root.py):
        rnode(kv half, records half) of the two depth-256 sparse alghash2 trees, 64-hex — identical on
        every honest node at the same cursor. This is the root the bonded quorum settles on L1 and every
        bridge/dividend/unshield/xmsg exit is proven against. Cached; invalidated by _touch."""
        root = self._root_cache
        if root is None:
            with self._mutate_lock:
                if self._root_cache is None:
                    from execnode import exec_root as ER
                    kv, rec = self._sparse_stores()
                    self._root_cache = ER.full_root_hex(kv.root(), rec.root())
                root = self._root_cache
        return root

    def _record_proof(self, tag, *parts):
        """Sparse exit proof {"kv": hex, "path": packed} for the record at record_key(tag, *parts) —
        the wire format L1's exec_root.verify_record checks against the settled root."""
        from execnode import exec_root as ER
        with self._mutate_lock:
            kv, rec = self._sparse_stores()
            return ER.record_proof(kv.root(), rec, ER.record_key(tag, *parts))

    def withdrawal_proof(self, nonce):
        """(addr, amount, nonce, proof) for a recorded withdrawal, provable against state_root; None if absent."""
        from execnode import exec_root as ER
        w = self.withdrawals.get(str(nonce))
        if not w:
            return None
        return {"addr": w["addr"], "amount": w["amount"], "nonce": str(nonce),
                "proof": self._record_proof(ER.T_BRIDGE_WD, w["addr"], str(nonce))}

    def outbox_proof(self, seq):
        """(msg, proof) for outbox message `seq`, provable against state_root; None if absent. Mirrors
        withdrawal_proof: a consumer verifies exec_root.verify_outbox_msg(proof) against the sender
        rollup's SETTLED root (from L1 /get_settled?ns=) to accept the message trust-minimized."""
        from execnode import exec_root as ER
        try:
            msg = self.outbox[str(int(seq))]
        except (KeyError, ValueError, TypeError):
            return None
        dg = ER.leaf_digest(ER.msg_outbox_leaf(msg))
        return {"message": msg, "proof": self._record_proof(ER.T_DIGEST, "outbox", dg)}

    def apply_xmsg(self, from_ns, message):
        """Deliver an L1-VERIFIED cross-domain message into this rollup's inbox. L1 already verified the
        message against `from_ns`'s SETTLED root and burned its (from_ns, seq) nullifier, so the exec node
        just records it (committed in state_root). Deterministic: every receiver node reads the same `xmsg`
        from the finalized stream and appends the identical inbox entry."""
        with self._mutate_lock:
            self.inbox.append({"from_ns": from_ns, "seq": message.get("seq"), "data": message.get("data")})
            self._touch()
        return f"deliver from ns={from_ns} seq={message.get('seq')}"

    def drop_claimed(self, kind, nonce):
        """GC a withdrawal/dividend/unshield record whose CLAIM tx finalized on L1 (the nullifier is
        burned there, so the exit can never be claimed again and its proof is never needed) — bounds
        state_root cost, which otherwise grew one leaf per exit forever. Deterministic: every exec
        node reads the same finalized claim from the L1 stream. No-op on an unknown nonce."""
        m = {"bridge_withdraw": self.withdrawals,
             "dividend_withdraw": self.dividend_withdrawals,
             "unshield": self.unshield_withdrawals}.get(kind)
        if m is None:
            return
        with self._mutate_lock:
            if m.pop(str(nonce), None) is not None:
                self._touch()

    def drop_consumed_outbox(self, seq):
        """GC an outbox message whose `xmsg` delivery finalized on L1 (its (from_ns, seq) nullifier
        is burned — it can never deliver again). Bounds the one-leaf-per-message outbox growth.
        Deterministic for the same reason as drop_claimed. No-op on an unknown seq."""
        with self._mutate_lock:
            try:
                key = str(int(seq))
            except (TypeError, ValueError):
                return
            if self.outbox.pop(key, None) is not None:
                self._touch()

    def credit_deposit(self, addr, amount):
        """Credit an exec-side bridge balance from an L1 `bridge` deposit (read from the ordered stream)."""
        with self._mutate_lock:
            self.bridge[addr] = self.bridge.get(addr, 0) + int(amount)
            self._touch()

    # --- RANDAO beacon (#randao) -----------------------------------------------------------------
    def record_reveal(self, target_epoch, secret):
        """Accumulate one RANDAO reveal secret for target_epoch, from a finalized L1 `reveal` tx."""
        try:
            e = int(target_epoch)
            if e >= 0 and isinstance(secret, str) and secret:
                self.randao_reveals.setdefault(e, set()).add(secret)
        except Exception:
            pass

    @staticmethod
    def exec_beacon_int(epoch, reveals):
        """The exec-layer beacon for `epoch` as the BEACON opcode reads it, BEFORE the VM's mod-P reduction:
        int(compute_beacon(GENESIS_BEACON, reveals + [str(epoch)]), 16). `reveals` is the epoch's revealed
        secrets (any iterable; compute_beacon re-sorts, so order is irrelevant). The `+[str(epoch)]` sentinel
        makes every epoch's beacon distinct even with zero reveals.

        SINGLE SOURCE OF TRUTH: this is the ONLY definition of the exec beacon. advance_beacons (the exec
        node) and the L1 settle-with-proof chain-read cross-check (ops/transaction_ops) both call it, so the
        value a proof claims for BEACON and the value L1 authoritatively recomputes can never drift. NOTE it
        differs from L1's RANDAO-eligibility beacon (block_ops mixes the anchor hash, not str(epoch))."""
        from protocol import GENESIS_BEACON
        from ops.mining_ops import compute_beacon
        return int(compute_beacon(GENESIS_BEACON, list(reveals) + [str(int(epoch))]), 16)

    def advance_beacons(self, cursor):
        """Cache every epoch beacon now FINAL at `cursor`. Each beacon depends ONLY on that epoch's finalized
        reveals — beacon(E) = compute_beacon(GENESIS_BEACON, sorted(reveals[E]) + [E]) — NOT a cross-epoch chain,
        so it is a pure function of finalized L1 data: any node that witnessed all of epoch E-1 (where E's
        reveals land) computes the identical beacon(E), regardless of when it started. `beacon_floor` is the
        first epoch we witnessed in full (this node began mid-flight, so earlier epochs are marked unavailable
        rather than computed from partial reveals). Prunes ancient epochs to bound memory."""
        from protocol import EPOCH_LENGTH
        if cursor is None or cursor < 0:
            return
        cur_epoch = int(cursor) // EPOCH_LENGTH
        if self.beacon_floor is None:
            # E's reveals are submitted during E-1; starting mid-flight, E = cur_epoch+2 is the first epoch
            # whose ENTIRE preceding epoch we are guaranteed to witness from here on.
            self.beacon_floor = cur_epoch + 2
        start = max(self.beacon_floor, (max(self.beacons) + 1) if self.beacons else 0)
        for e in range(start, cur_epoch + 1):
            self.beacons[e] = self.exec_beacon_int(e, self.randao_reveals.get(e, set()))
        keep = cur_epoch - 4000
        if keep > 0:
            for e in [e for e in self.beacons if e < keep]:
                self.beacons.pop(e, None); self.randao_reveals.pop(e, None)

    def record_block_hash(self, height, block_hash):
        """Record one finalized L1 block hash for the BLOCKHASH opcode. `block_hash` is the block's hex hash;
        it becomes readable only once the cursor has reached `height` (a game can pin a FUTURE settle height
        whose hash nobody can predict while bets are open). Bounded ring — keeps the most recent ~20000 heights
        (~1.4 days at 6s), far more than any table's bet-to-settle window needs."""
        try:
            h = int(height)
            if h < 0 or not isinstance(block_hash, str) or not block_hash:
                return
            self.block_hashes[h] = int(block_hash, 16)
            if len(self.block_hashes) > 20000:
                for k in sorted(self.block_hashes)[:len(self.block_hashes) - 20000]:
                    self.block_hashes.pop(k, None)
        except Exception:
            pass

    def apply_field_shield(self, amount, owner, rho):
        """Add a field-native note for an L1 field-shield deposit. C-2: the note value is BOUND to the L1
        escrow — the exec node computes the commitment itself as commit(amount, owner, rho) from the
        authoritative on-chain `amount`, rather than trusting a client-supplied `cm` (which let a 1-coin
        deposit mint a note "worth" anything). The depositor supplies only (owner, rho); they know `amount`
        from their own tx, so they can still reconstruct and spend the note."""
        from execnode.stark import alghash, field as _F
        try:
            amount = int(amount)
            if not (0 < amount < MAX_EXIT_VALUE):     # note values must be < 2^61 to satisfy the range gadget
                return f"skip field-shield: amount out of range ({amount})"
            cm = alghash.commit(amount, int(owner) % _F.P, int(rho) % _F.P)
            with self._mutate_lock:                       # M-10: serialize field_pool mutation vs thread-applies
                self.field_pool.append(cm)
                self.pool_value += amount                 # shielded supply (ops/invariants): escrow-backed entry
                self._touch()
            return f"field-shield {amount} -> field note #{len(self.field_pool.commitments)}"
        except Exception as e:
            return f"skip field-shield: {e}"

    def apply_field_transfer(self, bundle):
        """Apply a Phase-2 STARK transfer: verify the join-split proof, reject a double-spend, then record the
        nullifier + append the output commitment. public_value<0 records a provable unshield exit."""
        from execnode import shielded
        _normalize_bundle(bundle)   # browser bundles carry big ints as strings (JS can't JSON BigInt) -> ints
        stark_b = bundle.get("stark") or {}
        if "joinsplit2" in stark_b:                     # 2-output transfer (send + change)
            js = stark_b["joinsplit2"]
            cm_outs = [int(js["cm_out1"]), int(js["cm_out2"])]
        else:                                           # 1-output transfer / unshield
            js = stark_b.get("joinsplit") or {}
            cm_outs = [int(js["cm_out"])]
        public = {"root": js.get("root"), "nullifiers": [js.get("nf")], "out_commitments": [str(c) for c in cm_outs],
                  "public_value": js.get("public_value"), "fee": js.get("fee")}
        ok, reason = shielded.verify_transfer(public, bundle, self.field_pool.knows_root)
        if not ok:
            return f"skip field-transfer: {reason}"
        from execnode.stark import field as _F
        # C-3: the circuit constrains only public_value % P and fee % P, but the exit payout below uses the
        # RAW signed value — so public_value = -P proves as "balanced" yet would record a P-coin exit. Bound
        # both to a real coin range BEFORE any state mutation, so no field residue can be inflated into a P·k
        # payout. (Note VALUES are field elements mod P; the only realizable exit is via public_value.)
        pv, fee = int(js["public_value"]), int(js["fee"])
        # UNBACKED-MINT FENCE: public_value > 0 means coins ENTER the pool, and the ONLY thing that may
        # authorise that is an L1 `shield` tx whose escrowed amount drives apply_field_shield. A transfer
        # blob is user-supplied and escrow-free, so a positive public_value here would let anyone conjure
        # notes from nothing (the circuit happily proves 0 + pv == v_out + fee — `pv` is a PUBLIC INPUT the
        # prover chooses, not a fact about escrow) and unshield them back out against SHIELD_ESCROW,
        # draining every other depositor. Entry is escrow-driven; a transfer may only be neutral or exiting.
        if not (-MAX_EXIT_VALUE <= pv <= 0) or not (0 <= fee <= MAX_EXIT_VALUE):
            return "skip field-transfer: public_value/fee out of range"
        # Validate the exit destination BEFORE any mutation: the old order added the nullifier + appended the
        # outputs and only then rejected a missing withdraw_addr, burning the note for a malformed unshield.
        addr = None
        if pv < 0:
            addr = bundle.get("withdraw_addr")
            if not addr:
                return "skip field-transfer: unshield missing withdraw_addr"
        nf = int(js["nf"]) % _F.P
        # M-10: the check->add->append must be atomic vs concurrent thread-applies (two racing identical
        # unshields could otherwise both pass has_nullifier and each record an exit for one spent note).
        with self._mutate_lock:
            if self.field_pool.has_nullifier(nf):
                return "skip field-transfer: nullifier already spent (double-spend)"
            self.field_pool.nullifiers.add(nf)
            for c in cm_outs:
                self.field_pool.append(c)
            # shielded supply: pv is <=0 (fenced above), so this only ever DECREASES the live note total.
            # fee leaves the notes but never leaves escrow, so it is tracked separately.
            self.pool_value += pv - fee
            self.pool_fees += fee
            if pv < 0:
                self.uw_nonce += 1
                nonce = str(self.uw_nonce)
                self.unshield_withdrawals[nonce] = {"addr": addr, "amount": -pv}
            self._touch()
        if pv < 0:
            return f"field-unshield {-pv} -> {addr[:12]}… nonce {nonce}"
        return "field-transfer ok"

    def apply_shield(self, amount, out_commitments, outputs):
        """Add the output notes of an L1 `shield` deposit (read from the ordered stream). A shield is a
        join-split with NO inputs and public_value = the escrowed `amount`, so the verifier enforces
        sum(output values) == amount (transparent phase). Never raises; a malformed shield is skipped (the
        depositor's escrowed coins are then simply unspendable — their own risk)."""
        try:
            public = {"root": self.shielded.root(), "nullifiers": [], "out_commitments": list(out_commitments),
                      "public_value": int(amount), "fee": 0}
            proof = {"inputs": [], "outputs": list(outputs)}
            with self._mutate_lock:
                ok, reason = apply_transfer(self.shielded, public, proof, self.shielded.knows_root)
                if ok:
                    self.pool_value += int(amount)        # shielded supply (ops/invariants)
                self._touch()
            return f"shield {amount} -> {len(out_commitments)} note(s)" if ok else f"skip shield: {reason}"
        except Exception as e:
            return f"skip shield: {e}"

    @staticmethod
    def _rt_run(rt, *a, **kw):
        """Call a runtime and normalise its result to (ok, ret, storage, payouts, effects).

        The registry is a SEAM for other execution engines (execnode/runtimes.py), and its documented
        result was 4-tuple `(ok, ret, storage, payouts)` before assets existed. Widening it to 5 broke
        every implementation that is not the built-in zkVM — which is precisely the thing the seam exists
        to allow. A runtime that knows nothing about assets should not have to return an empty effects
        list to stay compatible, so BOTH arities are valid and a 4-tuple simply means "no asset effects".
        Anything shorter is a broken runtime and still raises."""
        r = rt.run(*a, **kw)
        if len(r) == 4:
            return (*r, [])
        return r

    # --- asset ledger (doc/assets.md) ------------------------------------------------------------
    def asset_balance(self, aid, holder):
        """`holder`'s balance of asset `aid` (int or str id). 0 for an asset nobody has ever held — an
        absent row and a zero row are the same balance, which is what keeps the ledger canonical."""
        return int(self.abal.get(str(aid), {}).get(holder, 0))

    def holder_assets(self, holder):
        """A lazy {asset_id(int) -> balance} view of ONE holder, for the VM's ABAL opcode. A dict would be
        O(#assets on the chain) to build per call; this is O(1) per read and identical on every node."""
        st, h = self, holder

        class _View:
            def get(self, aid, default=0):
                return int(st.abal.get(str(int(aid)), {}).get(h, default))
        return _View()

    def _asset_credit(self, aid, holder, delta):
        """Move `delta` (signed) of asset `aid` on `holder`'s row, pruning to absence at zero. Callers have
        already validated solvency — this is the commit half of a staged, all-or-nothing settlement."""
        asset_credit_dict(self.abal, aid, holder, delta)

    def asset_allowance(self, aid, owner, spender):
        """How much of `aid` `spender` may move on `owner`'s behalf. Absent == 0, same canonical rule as a
        balance: a never-set allowance and a revoked one are indistinguishable."""
        return int(self.allow.get(str(aid), {}).get(owner, {}).get(spender, 0))

    def _allow_set(self, aid, owner, spender, amount):
        """Write an allowance to an EXACT value (approve overwrites, ERC-20 style), pruning empty rows so two
        nodes with the same authorizations commit the same root."""
        key = str(aid)
        owners = self.allow.setdefault(key, {})
        row = owners.setdefault(owner, {})
        if int(amount) > 0:
            row[spender] = int(amount)
        else:
            row.pop(spender, None)
        if not row:
            owners.pop(owner, None)
        if not owners:
            self.allow.pop(key, None)

    def stage_asset_effects(self, actor, effects):
        """Validate a call's asset intents against THIS state's ledgers — a thin delegate to the module-level
        `stage_asset_effects_pure`, which is the single source of the money rules shared with the epoch
        prover's shadow (doc/assets.md §8). Mutates nothing; the caller commits only what it validates."""
        return stage_asset_effects_pure(self.abal, self.assets, actor, effects)

    def commit_asset_effects(self, deltas, sup):
        """Apply what stage_asset_effects validated. Never called without that validation."""
        commit_asset_effects_pure(self.abal, self.assets, deltas, sup)

    def contract_id(self, deployer, code, nonce):
        """Deterministic contract id H(deployer, code, nonce) (truncated) — identical on every exec node,
        so a deployer can know its cid before the blob even lands (submit_blob echoes it)."""
        return blake2b_hash(["deploy", deployer, code, nonce])[:32]

    # --- applying blobs --------------------------------------------------------------------------
    def apply_blob(self, payload, sender, txid):
        with self._mutate_lock:
            try:
                return self._apply_blob_inner(payload, sender, txid)
            finally:
                self._touch()

    def _apply_blob_inner(self, payload, sender, txid):
        """Apply ONE blob payload from sender (the blob tx's L1 sender). Returns a short human string.
        Never raises: a malformed or reverting blob is a no-op ('skip'/'revert')."""
        try:
            if not isinstance(payload, dict):
                return "skip: payload not an object"
            op = payload.get("op")

            if op == "deploy":
                code = _decode_code(payload)              # raw `code` or zstd `codez`
                rt_name = payload.get("runtime", runtimes.DEFAULT_RUNTIME)   # pluggable: which VM runs it
                rt = runtimes.get(rt_name)
                if rt is None:
                    return f"skip: unknown runtime {rt_name!r}"
                rt.validate_code(code)                    # raises ZkVMError on bad code (caught below)
                # FIXED-NAME deploy (doc/faucet.md §4): a SYSTEM contract may claim a well-known literal
                # cid instead of the derived hash, so the L1 reserved recipient, the exec ledger key and
                # the contract address are all the same word. Allowlisted per name to a sole deployer —
                # deterministic on every exec node, and the reserved-name namespace can't be squatted.
                at = payload.get("at")
                if at is not None:
                    if FIXED_CIDS.get(at) != sender:
                        return f"skip: fixed-name deploy {at!r} not authorized for {sender[:12]}…"
                    cid = at
                else:
                    cid = self.contract_id(sender, code, payload.get("nonce", txid))
                if cid in self.contracts:
                    return f"skip: contract {cid} already exists"
                storage = {}
                if "constructor" in code:
                    kw = {"registry": self.zk_addrs} if getattr(rt, "wants_registry", False) else {}
                    ok, _ret, storage, _pay, _fx = self._rt_run(rt, code, "constructor", sender, [], {}, cursor=self.cursor, timestamp=self.block_ts, beacons=self.beacons, block_hashes=self.block_hashes, selfd=runtimes.zkvm_addr_digest(cid), abal=self.holder_assets(cid), **kw)
                    if not ok:
                        storage = {}                      # constructor reverted -> deploy with empty state
                abi = payload.get("abi")   # optional, non-consensus UX metadata {method:{args,doc}}
                # UPGRADABILITY (per-contract, opt-out): a contract is upgradable by its deployer unless it
                # deploys with {"upgradable": false}. A stable contract can later renounce upgradability
                # permanently via the `lock` op. This keeps mainnet safe (lockable/immutable) while letting a
                # deployer iterate freely until they lock. Default True preserves the alphanet workflow.
                upgradable = payload.get("upgradable", True) is not False
                self.contracts[cid] = {"code": code, "storage": storage, "deployer": sender,
                                       "runtime": rt_name, "abi": abi if isinstance(abi, dict) else {},
                                       "upgradable": upgradable}
                return f"deploy {cid} ({rt_name}{'' if upgradable else ', LOCKED'}) by {sender[:12]}…"

            if op == "call":
                cid = payload.get("contract")
                method = payload.get("method")
                args = payload.get("args", [])
                value = payload.get("value", 0)
                c = self.contracts.get(cid)
                if not c:
                    return f"skip: no contract {cid}"
                if not isinstance(args, list):
                    return "skip: args must be a list"
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    return "skip: bad call value"
                # ASSET-DENOMINATED CALL VALUE (doc/assets.md): `asset` names WHICH value is escrowed. Absent
                # or 0 means native NADO and every existing contract is untouched; otherwise the same `value`
                # is a quantity of that asset, escrowed from the caller's asset row instead of their bridge.
                # One `value` field, two ledgers — so a contract reads the amount through CTX_VALUE either
                # way and only has to consult ACTX_ASSET when it cares which currency arrived.
                in_asset = payload.get("asset") or 0
                if in_asset:
                    in_asset = str(in_asset)
                    if in_asset not in self.assets:
                        return f"skip: no such asset {str(in_asset)[:12]}…"
                rt = runtimes.get(c.get("runtime", runtimes.DEFAULT_RUNTIME))
                if rt is None:
                    return f"skip: unknown runtime for {cid}"
                # VALUE ESCROW: debit the caller's bridge INTO the contract (keyed by cid) BEFORE running, so the
                # VALUE opcode reflects it and PAY can draw on it. A revert refunds exactly — no NADO created or lost.
                if value > 0:
                    if in_asset:
                        if self.asset_balance(in_asset, sender) < value:
                            return f"skip: insufficient {self.assets[in_asset]['sym']} for call value ({sender[:12]}…)"
                        self._asset_credit(in_asset, sender, -value)
                        self._asset_credit(in_asset, cid, value)
                    else:
                        if self.bridge.get(sender, 0) < value:
                            return f"skip: insufficient bridge balance for call value ({sender[:12]}…)"
                        self.bridge[sender] -= value
                        if self.bridge[sender] == 0:
                            del self.bridge[sender]
                        self.bridge[cid] = self.bridge.get(cid, 0) + value
                kw = {"registry": self.zk_addrs} if getattr(rt, "wants_registry", False) else {}
                ok, _ret, new_storage, payouts, effects = self._rt_run(
                    rt, c["code"], method, sender, args, c["storage"],
                    value=value, cursor=self.cursor, timestamp=self.block_ts, beacons=self.beacons,
                    block_hashes=self.block_hashes, asset=int(in_asset or 0),
                    selfd=runtimes.zkvm_addr_digest(cid), abal=self.holder_assets(cid), **kw)
                def _refund():
                    if value > 0:
                        if in_asset:
                            self._asset_credit(in_asset, cid, -value)
                            self._asset_credit(in_asset, sender, value)
                            return
                        self.bridge[cid] = self.bridge.get(cid, 0) - value
                        if self.bridge.get(cid, 0) == 0:
                            self.bridge.pop(cid, None)
                        self.bridge[sender] = self.bridge.get(sender, 0) + value
                if not ok:
                    _refund()
                    return f"call {cid}.{method} by {sender[:12]}… -> revert (no-op)"
                # A contract can only pay out what it HOLDS: reject (revert + refund) an over-pay so its balance
                # can never go negative and no NADO is minted.
                total_pay = sum(a for _t, a in payouts)
                if total_pay > self.bridge.get(cid, 0):
                    _refund()
                    return f"call {cid}.{method} -> revert (payout {total_pay} > contract balance)"
                # The same rule for the asset ledger, staged so it is ALL-OR-NOTHING with the native half:
                # nothing is written until every asset move in the call is known legal.
                a_ok, a_why, a_deltas, a_sup = self.stage_asset_effects(cid, effects)
                if not a_ok:
                    _refund()
                    return f"call {cid}.{method} -> revert ({a_why})"
                c["storage"] = new_storage
                for to, amt in payouts:
                    self.bridge[cid] = self.bridge.get(cid, 0) - amt
                    if self.bridge.get(cid, 0) == 0:
                        self.bridge.pop(cid, None)
                    self.bridge[to] = self.bridge.get(to, 0) + amt
                self.commit_asset_effects(a_deltas, a_sup)
                moved = sum(1 for k, *_ in effects if k != "bal")
                tag = ((f" value={value}" + (f" {self.assets[in_asset]['sym']}" if in_asset else "")) if value else "") \
                    + (f" paid={total_pay}" if payouts else "") + (f" assetfx={moved}" if moved else "")
                return f"call {cid}.{method} by {sender[:12]}…{tag} -> ok"

            # ---- assets (doc/assets.md) -------------------------------------------------------------
            # The USER-facing half of the asset layer: what a person does from a wallet, as opposed to what a
            # contract does through ASEL/AMINT/ABURN. Same ledger, same rules, no privileged path — an asset
            # created here and one created by a contract are indistinguishable afterwards.
            if op == "asset_create":
                seed = payload.get("seed", 0)
                if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
                    return "skip: asset seed must be a non-negative int"
                name = payload.get("name", "")
                sym = payload.get("sym", "")
                dec = payload.get("dec", 0)
                supply = payload.get("supply", 0)
                if not (isinstance(name, str) and 0 < len(name) <= ASSET_NAME_MAX):
                    return f"skip: asset name must be 1..{ASSET_NAME_MAX} chars"
                if not (isinstance(sym, str) and 0 < len(sym) <= ASSET_SYM_MAX):
                    return f"skip: asset symbol must be 1..{ASSET_SYM_MAX} chars"
                if not isinstance(dec, int) or isinstance(dec, bool) or not (0 <= dec <= ASSET_DEC_MAX):
                    return f"skip: asset decimals must be 0..{ASSET_DEC_MAX}"
                if (not isinstance(supply, int) or isinstance(supply, bool)
                        or not (0 <= supply < ASSET_SUPPLY_CAP)):
                    return "skip: asset supply out of range"
                # Optional metadata pointer (logo/details). A LINK only — no privileged meaning, no
                # on-chain fetch; the wallet/explorer render it. Empty is fine and is the default.
                uri = payload.get("uri", "")
                if not isinstance(uri, str) or len(uri) > ASSET_URI_MAX:
                    return f"skip: asset uri must be a string of 0..{ASSET_URI_MAX} chars"
                # CONTRACT-ISSUED ASSETS (`for`: a cid). A contract cannot submit a blob — a blob sender is
                # an L1 address derived from a pubkey, and a cid is a 32-hex hash, so no transaction can
                # ever carry sender == cid. Without this branch a contract could therefore never BE an
                # issuer, which would make AMINT unreachable in production and the whole point of
                # in-circuit derived ids ("an AMM owns its LP token") a dead letter.
                #
                # The contract's DEPLOYER creates it on the contract's behalf. That grants no new power:
                # they already control the code. Note carefully what it does NOT grant — the issuer is the
                # CID, and `asset_mint`/`asset_transfer`/`asset_burn` all act as `sender`, so the deployer
                # can never mint the token or move the contract's holdings. Creating and renouncing belong
                # to the deployer; minting and moving belong to the contract's code alone.
                issuer = sender
                for_cid = payload.get("for")
                if for_cid is not None:
                    c = self.contracts.get(for_cid)
                    if not c:
                        return f"skip: no contract {str(for_cid)[:16]}… to issue for"
                    if c.get("deployer") != sender:
                        return "skip: only a contract's deployer may issue an asset for it"
                    issuer = for_cid
                aid = str(asset_id(issuer, seed))
                if aid in self.assets:
                    return f"skip: asset {aid[:12]}… already exists"
                # MINT AUTHORITY is opt-IN and renounceable, never implicit: an asset created with
                # mintable=false (the default) can never grow past this supply, and the guarantee is
                # readable from the ledger by anyone before they buy a single unit.
                self.assets[aid] = {"issuer": issuer, "seed": seed, "name": name, "sym": sym, "dec": dec,
                                    "supply": supply, "mintable": payload.get("mintable", False) is True,
                                    "uri": uri}
                if supply:
                    # to the ISSUER, not the sender: a contract-issued asset's initial supply belongs to
                    # the contract. Crediting the deployer instead would hand them free units of a token
                    # the contract is supposed to own — the rug this layer exists to make impossible.
                    self._asset_credit(aid, issuer, supply)
                return (f"asset_create {sym} ({aid[:12]}…) supply={supply} "
                        f"{'mintable' if self.assets[aid]['mintable'] else 'fixed'} "
                        f"for {issuer[:12]}… by {sender[:12]}…")

            if op == "asset_transfer":
                aid = str(payload.get("asset") or "")
                to = payload.get("to")
                amount = payload.get("amount", 0)
                if aid not in self.assets:
                    return f"skip: no such asset {aid[:12]}…"
                if not isinstance(to, str) or not to:
                    return "skip: asset_transfer needs a `to` address"
                if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                    return "skip: asset_transfer amount must be positive"
                if self.asset_balance(aid, sender) < amount:
                    return f"skip: insufficient {self.assets[aid]['sym']} ({sender[:12]}…)"
                self._asset_credit(aid, sender, -amount)
                self._asset_credit(aid, to, amount)
                return f"asset_transfer {amount} {self.assets[aid]['sym']} {sender[:12]}… -> {to[:12]}…"

            if op == "asset_approve":
                # Owner (sender) authorises `spender` to move up to `amount` on their behalf. ERC-20
                # semantics: this OVERWRITES any prior allowance (it is not additive), and 0 revokes. No
                # balance check — you may approve more than you hold; the pull is bounded by your balance at
                # spend time, not now. `spender` is any string identity: an address (a person delegating) OR
                # a cid (authorising a contract to pull — see the APULL opcode).
                aid = str(payload.get("asset") or "")
                spender = payload.get("spender")
                amount = payload.get("amount", 0)
                if aid not in self.assets:
                    return f"skip: no such asset {aid[:12]}…"
                if not isinstance(spender, str) or not spender:
                    return "skip: asset_approve needs a `spender`"
                if spender == sender:
                    return "skip: cannot approve yourself"
                if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0 or amount >= ASSET_SUPPLY_CAP:
                    return "skip: asset_approve amount out of range"
                self._allow_set(aid, sender, spender, amount)
                return f"asset_approve {amount} {self.assets[aid]['sym']} {sender[:12]}… -> {spender[:12]}…"

            if op == "asset_transfer_from":
                # Spender (sender) moves `amount` from `owner` to `to`, consuming the allowance `owner`
                # granted them. Both gates apply: the standing allowance AND `owner`'s live balance — an
                # allowance is a ceiling, never a promise the tokens are there. The allowance decrements by
                # exactly what moved (no infinite-approval special case: exactness over a gas micro-saving).
                aid = str(payload.get("asset") or "")
                owner = payload.get("from")
                to = payload.get("to")
                amount = payload.get("amount", 0)
                if aid not in self.assets:
                    return f"skip: no such asset {aid[:12]}…"
                if not isinstance(owner, str) or not owner or not isinstance(to, str) or not to:
                    return "skip: asset_transfer_from needs `from` and `to`"
                if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                    return "skip: asset_transfer_from amount must be positive"
                if self.asset_allowance(aid, owner, sender) < amount:
                    return f"skip: allowance too low for {self.assets[aid]['sym']} ({sender[:12]}… on {owner[:12]}…)"
                if self.asset_balance(aid, owner) < amount:
                    return f"skip: insufficient {self.assets[aid]['sym']} ({owner[:12]}…)"
                self._allow_set(aid, owner, sender, self.asset_allowance(aid, owner, sender) - amount)
                self._asset_credit(aid, owner, -amount)
                self._asset_credit(aid, to, amount)
                return f"asset_transfer_from {amount} {self.assets[aid]['sym']} {owner[:12]}… -> {to[:12]}… by {sender[:12]}…"

            if op == "asset_burn":
                aid = str(payload.get("asset") or "")
                amount = payload.get("amount", 0)
                if aid not in self.assets:
                    return f"skip: no such asset {aid[:12]}…"
                if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                    return "skip: asset_burn amount must be positive"
                if self.asset_balance(aid, sender) < amount:
                    return f"skip: insufficient {self.assets[aid]['sym']} to burn ({sender[:12]}…)"
                self._asset_credit(aid, sender, -amount)
                self.assets[aid]["supply"] -= amount
                return f"asset_burn {amount} {self.assets[aid]['sym']} by {sender[:12]}…"

            if op == "asset_mint":
                aid = str(payload.get("asset") or "")
                to = payload.get("to")
                amount = payload.get("amount", 0)
                meta = self.assets.get(aid)
                if meta is None:
                    return f"skip: no such asset {aid[:12]}…"
                if meta["issuer"] != sender:
                    return f"skip: only {meta['sym']}'s issuer may mint"
                if not meta["mintable"]:
                    return f"skip: {meta['sym']} minting was renounced"
                if not isinstance(to, str) or not to:
                    return "skip: asset_mint needs a `to` address"
                if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                    return "skip: asset_mint amount must be positive"
                if meta["supply"] + amount > ASSET_SUPPLY_CAP:
                    return f"skip: {meta['sym']} supply cap exceeded"
                self._asset_credit(aid, to, amount)
                meta["supply"] += amount
                return f"asset_mint {amount} {meta['sym']} -> {to[:12]}…"

            if op == "asset_renounce":
                # PERMANENT, one-way, exactly like `lock` on a contract: after this the supply can only ever
                # fall. It is the difference between a token you can hold and one whose issuer can dilute you
                # at will, so it is a first-class op rather than a convention.
                aid = str(payload.get("asset") or "")
                meta = self.assets.get(aid)
                if meta is None:
                    return f"skip: no such asset {aid[:12]}…"
                if meta["issuer"] != sender:
                    # A contract-issued asset is renounced by the contract's DEPLOYER, for the same reason
                    # they create it: the contract itself can never send a blob. Safe to grant, because
                    # renouncing only ever REMOVES power — there is no way to abuse the ability to make a
                    # supply permanently fixed. (A contract that wants to renounce autonomously — a
                    # launchpad sealing its token at graduation — needs an opcode; see doc/assets.md.)
                    c = self.contracts.get(meta["issuer"])
                    if not (c and c.get("deployer") == sender):
                        return f"skip: only {meta['sym']}'s issuer may renounce minting"
                meta["mintable"] = False
                return f"asset_renounce {meta['sym']} ({aid[:12]}…) — supply fixed at {meta['supply']}"

            if op == "asset_set_uri":
                # Update the metadata/logo pointer. Issuer-only (or the contract's deployer, mirroring
                # renounce), because the uri is committed in the metadata digest — it is state, not a hint.
                # It carries NO privileged meaning: it cannot touch supply or balances, so unlike renounce
                # this is intentionally reversible (a logo host or IPFS pin changes over a token's life).
                aid = str(payload.get("asset") or "")
                uri = payload.get("uri", "")
                meta = self.assets.get(aid)
                if meta is None:
                    return f"skip: no such asset {aid[:12]}…"
                if not isinstance(uri, str) or len(uri) > ASSET_URI_MAX:
                    return f"skip: asset uri must be a string of 0..{ASSET_URI_MAX} chars"
                if meta["issuer"] != sender:
                    c = self.contracts.get(meta["issuer"])
                    if not (c and c.get("deployer") == sender):
                        return f"skip: only {meta['sym']}'s issuer may set its uri"
                meta["uri"] = uri
                return f"asset_set_uri {meta['sym']} ({aid[:12]}…) -> {uri[:40]!r}"

            if op == "lock":
                # RENOUNCE UPGRADABILITY (permanent): the deployer of an upgradable contract locks it forever
                # (immutability is a one-way switch — this is the mainnet trust primitive). No-op if already
                # locked. Storage/code/cid unchanged; only future `upgrade`s are refused.
                cid = payload.get("contract")
                c = self.contracts.get(cid)
                if not c:
                    return f"skip: no contract {cid}"
                if c.get("deployer") != sender:
                    return "skip: only the deployer can lock this contract"
                c["upgradable"] = False
                return f"lock {cid} by {sender[:12]}… — now immutable"

            if op == "upgrade":
                # Contracts are UPGRADABLE by their deployer UNLESS deployed with {"upgradable": false} or later
                # `lock`ed. The cid + storage are preserved; the code (and optional abi/runtime) are replaced.
                # A LOCKED contract is permanently immutable (the mainnet-safe path); an upgradable one lets the
                # deployer iterate. Legacy contracts (no flag) default upgradable.
                cid = payload.get("contract")
                code = _decode_code(payload)              # raw `code` or zstd `codez`
                c = self.contracts.get(cid)
                if not c:
                    return f"skip: no contract {cid}"
                if c.get("deployer") != sender:
                    return "skip: only the deployer can upgrade this contract"
                if c.get("upgradable", True) is False:
                    return f"skip: contract {cid} is locked (immutable)"
                rt_name = payload.get("runtime", c.get("runtime", runtimes.DEFAULT_RUNTIME))
                rt = runtimes.get(rt_name)
                if rt is None:
                    return f"skip: unknown runtime {rt_name!r}"
                try:
                    rt.validate_code(code)
                except Exception as e:
                    return f"skip: invalid code ({e})"
                c["code"] = code
                c["runtime"] = rt_name
                if isinstance(payload.get("abi"), dict):
                    c["abi"] = payload["abi"]
                return f"upgrade {cid} by {sender[:12]}… (code replaced, storage kept)"

            if op == "transfer_contract":
                # CONTRACT TRANSFERENCE: hand a contract's OWNERSHIP (the deployer right — who may upgrade /
                # transfer it) to another address. Only the current owner (deployer) may transfer; code, storage
                # and cid are unchanged. Lets a contract be handed to a new maintainer without redeploying.
                cid = payload.get("contract")
                to = payload.get("to")
                c = self.contracts.get(cid)
                if not c:
                    return f"skip: no contract {cid}"
                if c.get("deployer") != sender:
                    return "skip: only the current owner (deployer) can transfer this contract"
                if not isinstance(to, str) or not to:
                    return "skip: transfer_contract needs a non-empty 'to' address"
                c["deployer"] = to
                return f"transfer_contract {cid} owner {sender[:12]}… -> {to[:12]}…"

            if op == "emit":
                # Emit a cross-domain MESSAGE: append {seq, from, to_ns, data} to the outbox, committed in
                # state_root as an outbox leaf and provable via outbox_proof(seq). This blob only COMMITS the
                # message; a consumer (another rollup / L1) verifies + delivers it against this rollup's
                # SETTLED root separately (doc/rollups-and-settlement.md §7.4). Append-only, seq == index.
                to_ns = payload.get("to_ns")
                if not isinstance(to_ns, str) or not to_ns:
                    return "skip: emit needs a non-empty string to_ns"
                seq = self.outbox_seq
                self.outbox[str(seq)] = {"seq": seq, "from": sender, "to_ns": to_ns, "data": payload.get("data")}
                self.outbox_seq = seq + 1
                return f"emit #{seq} -> ns={to_ns} by {sender[:12]}…"

            if op == "bridge_withdraw":
                # burn the sender's exec-side bridge balance and record a provable withdrawal leaf; once
                # the state_root carrying it is SETTLED on L1, the sender claims the L1 coins with its proof.
                amt = payload.get("amount")
                if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
                    return "skip: bad withdraw amount"
                if self.bridge.get(sender, 0) < amt:
                    return f"skip: insufficient bridge balance for {sender[:12]}…"
                self.bridge[sender] -= amt
                if self.bridge[sender] == 0:
                    del self.bridge[sender]
                self.wd_nonce += 1
                nonce = str(self.wd_nonce)
                self.withdrawals[nonce] = {"addr": sender, "amount": amt}
                return f"bridge_withdraw {amt} by {sender[:12]}… -> nonce {nonce}"

            if op == "collect_dividend":
                # COLLECT (doc/presence-dividend.md): burn the sender's whole accrued dividend into a provable
                # withdrawal leaf; once the carrying state_root is SETTLED on L1, the sender claims the L1
                # coins from the DIVIDEND_POOL with its proof (fee-exempt dividend_withdraw tx).
                amt = int(self.dividend.get(sender, 0))
                if amt <= 0:
                    return f"skip: no accrued dividend for {sender[:12]}…"
                del self.dividend[sender]
                self.dw_nonce += 1
                nonce = str(self.dw_nonce)
                self.dividend_withdrawals[nonce] = {"addr": sender, "amount": amt}
                return f"collect_dividend {amt} by {sender[:12]}… -> nonce {nonce}"

# (native coin-flip ops removed — Coin Flip is now the on-chain CONTRACT at runtime 'zkvm', staked via
            # the VALUE/PAY escrow primitive; see doc/exec-instructions.md)

            if op == "field_transfer":
                # PHASE-2: a full join-split STARK proof (delegated-prover output). The bundle rides as an
                # OPAQUE JSON STRING so its big field ints survive JSON (JS would lose >2^53 precision).
                bj = payload.get("bundle_json")
                if bj is not None:
                    try:
                        bundle = json.loads(bj)
                    except Exception:
                        return "skip: bad bundle_json"
                else:
                    bundle = payload.get("bundle")
                if not isinstance(bundle, dict):
                    return "skip: bad field_transfer"
                return self.apply_field_transfer(bundle)

            if op == "shielded_transfer":
                # PRIVATE transfer / UNSHIELD (doc/privacy.md): apply a join-split to the pool (double-spend +
                # value-conservation checked by the verifier). If public_value < 0 the coins LEAVE the pool ->
                # record a provable unshield exit for L1 to release from SHIELD_ESCROW against the settled root.
                public = payload.get("public")
                proof = payload.get("proof")
                if not isinstance(public, dict) or not isinstance(proof, dict):
                    return "skip: bad shielded_transfer"
                # UNBACKED-MINT FENCE (see apply_field_transfer): coins may only ENTER the pool via an L1
                # `shield` tx, whose escrowed amount drives apply_shield. A transfer blob is user-supplied
                # and escrow-free, so public_value > 0 here would mint notes backed by nothing. Checked
                # BEFORE apply_transfer so a rejected blob never mutates the pool.
                pv = int(public.get("public_value", 0))
                if pv > 0:
                    return "skip shielded_transfer: public_value > 0 (coins enter only via an L1 shield)"
                ok, reason = apply_transfer(self.shielded, public, proof, self.shielded.knows_root)
                if not ok:
                    return f"skip shielded_transfer: {reason}"
                _fee = int(public.get("fee", 0) or 0)
                self.pool_value += pv - _fee              # shielded supply (ops/invariants)
                self.pool_fees += _fee
                if pv < 0:
                    addr = public.get("withdraw_addr")
                    if not addr:
                        return "skip: unshield missing withdraw_addr"
                    self.uw_nonce += 1
                    nonce = str(self.uw_nonce)
                    self.unshield_withdrawals[nonce] = {"addr": addr, "amount": -pv}
                    return f"unshield {-pv} -> {addr[:12]}… nonce {nonce}"
                return f"shielded_transfer ok ({len(public.get('out_commitments', []))} out)"

            return f"skip: unknown op {op!r}"
        except ZkVMError as e:
            return f"skip: bad contract ({e})"
        except Exception as e:
            return f"skip: {e}"

    def decode_view(self, c):
        """Present a zkVM contract's flat slot storage as the NAMED MAPS its frontend expects, using the
        optional view schema in its abi["_view"] (doc/zk-execution-proofs.md game model). This is the ONE
        place the slot model is translated back, so ported game frontends change only their cid.

        Simple schema (single key set, e.g. coinflip):
            {"maps": {"<name>": <field_id>, ...}, "index": {"cnt": <slot>, "list": <field_id>}, "addr": [...]}
        Rich schema (several key sets, e.g. dice tables + games):
            {"maps": {"<name>": {"field": <id>, "index": "<idxname>"}, ...},
             "indexes": {"<idxname>": {"cnt": <slot>, "list": <field_id>}, ...}, "addr": [...]}
        Returns {name: {str(key): value}} — byte-compatible with the old stackvm storage. Missing schema (or a
        non-zkVM contract) returns raw storage unchanged."""
        view = (c.get("abi") or {}).get("_view")
        if not view or c.get("runtime") != "zkvm":
            return c.get("storage", {})
        slots = (c.get("storage") or {}).get("slots") or {}
        def sv(s):
            return int(slots.get(str(s), 0))
        def enum(idx):                                     # the key set of one index (cnt slot + list field)
            cnt = sv(idx["cnt"]) if "cnt" in idx else 0
            if idx.get("range"):                           # keys ARE 0..cnt-1 (indexed registries, e.g. faucet)
                return list(range(cnt))
            lf = idx.get("list")
            return [sv((lf << 32) + i) for i in range(cnt)] if lf is not None else []
        indexes = view.get("indexes")
        default_keys = enum(view["index"]) if "index" in view else []
        key_cache = {name: enum(idx) for name, idx in (indexes or {}).items()}
        addr_fields = set(view.get("addr") or [])
        out = {}
        for name, spec in (view.get("maps") or {}).items():
            if isinstance(spec, dict):
                field, keys = spec["field"], key_cache.get(spec.get("index"), default_keys)
            else:
                field, keys = spec, default_keys
            m = {}
            for k in keys:
                val = sv((field << 32) + k)
                if val == 0:
                    continue
                if name in addr_fields:                    # resolve the stored digest back to its L1 address
                    val = self.zk_addrs.get(str(val), val)
                m[str(k)] = val
            if m:
                out[name] = m
        # board maps: per-cell fields (base+cell keyed by game) presented as bd[game*stride + cell].
        # Any number of them: "board" (one) plus "board2", "board3", … (e.g. blackjack's pc + dk).
        for bkey in ("board", "board2", "board3", "board4"):
            bd = view.get(bkey)
            if not bd:
                continue
            keys = key_cache.get(bd.get("index"), default_keys)
            m = {}
            for g in keys:
                for cell in range(bd["cells"]):
                    val = sv(((bd["base"] + cell) << 32) + g)
                    if val:
                        m[str(g * bd["stride"] + cell)] = val
            if m:
                out[bd["name"]] = m
        return out

    def view(self, cid, method, args):
        """Read-only call: run a method WITHOUT persisting storage; return its RETURN value (or None).
        caller is the sentinel 'view'. Used by the query API (e.g. balanceOf)."""
        c = self.contracts.get(cid)
        if not c:
            return None
        rt = runtimes.get(c.get("runtime", runtimes.DEFAULT_RUNTIME))
        if rt is None:
            return None
        kw = {"registry": dict(self.zk_addrs)} if getattr(rt, "wants_registry", False) else {}
        ok, ret, _, _, _ = self._rt_run(rt, c["code"], method, "view", args or [], c["storage"], cursor=self.cursor, timestamp=self.block_ts, beacons=self.beacons, block_hashes=self.block_hashes, selfd=runtimes.zkvm_addr_digest(cid), abal=self.holder_assets(cid), **kw)
        return ret if ok else None

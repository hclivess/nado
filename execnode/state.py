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

from hashing import (blake2b_hash, merkle_root, merkle_proof, withdrawal_leaf, dividend_leaf,
                     unshield_leaf, canonical_bytes, outbox_leaf)
from execnode.vm import validate_code, run, VMError
from execnode import runtimes   # pluggable contract-runtime registry (stackvm is the default plugin)
from execnode.shielded import ShieldedPool, apply_transfer

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


def _outbox_leaf(msg):
    """Canonical Merkle leaf for one outbox message — the SHARED hashing.outbox_leaf, so the leaf L1 verifies
    an `xmsg` delivery against is byte-identical to what the exec node commits + proves."""
    return outbox_leaf(msg["seq"], msg["from"], msg["to_ns"], msg.get("data"))


def _inbox_leaf(i, msg):
    """Canonical Merkle leaf for one DELIVERED (received) cross-domain message. Committed in state_root so
    every receiver node agrees on B's state after a delivery (they all read the same L1-verified `xmsg`)."""
    return canonical_bytes(["inbox", int(i), msg.get("from_ns"), int(msg.get("seq", -1)), msg.get("data")])


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



FLIP_REVEAL_WINDOW = 1000   # exec-cursor blocks a player has to reveal before the pot can be CLAIMED by forfeit

class ExecState:
    def __init__(self, path):
        """Initialise every state component empty, then load() the last snapshot from `path` if one
        exists — so a restarted exec node resumes from its persisted cursor instead of re-replaying L1."""
        self.path = path
        self.contracts = {}        # cid -> {"code": {...}, "storage": {mapname: {key: int}}, "deployer": addr}
        self.cursor = -1           # highest L1 block height fully applied
        self.bridge = {}           # addr -> exec-side bridged balance (credited by L1 `bridge` deposits)
        self.withdrawals = {}      # nonce(str) -> {"addr":.., "amount":..} : provable exit records
        self.wd_nonce = 0          # monotonic withdrawal-nonce counter (deterministic)
        # CROSS-DOMAIN OUTBOX: messages emitted by this layer (via the `emit` blob op), each committed as a
        # Merkle leaf in state_root and provable via outbox_proof(seq). This is the sound foundation for
        # cross-rollup / L1-bound messaging; CONSUMPTION (verifying against the sender's SETTLED root) is a
        # separate step, see doc/rollups-and-settlement.md §7.4. Append-only; seq == index.
        self.outbox = []           # [{"seq":i, "from":addr, "to_ns":ns, "data":<any>}]
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
        # M-10: the delegated-prover POST handlers apply field transfers in worker threads
        # (asyncio.to_thread), so the nullifier check->add and the state serialization can run concurrently.
        # This reentrant lock makes the double-spend check + the mutation atomic, and gives save() a
        # consistent snapshot, so two racing identical unshields can't both record an exit.
        self._mutate_lock = threading.RLock()
        # STAKED COIN FLIP: a native 2-player commit-reveal betting game. Stakes are ESCROWED from the bridged
        # balance into the game pot (committed in state_root), and the winner's pot is credited back to their
        # bridge balance (claimable on L1 like any bridge withdrawal). A cursor-based reveal DEADLINE lets a
        # griefed player CLAIM by forfeit, so a sore loser who withholds their reveal only loses their stake.
        self.games = {}            # gid(str) -> {stake, pot, settled, deadline, players:{addr:{commit,slot,secret}}}
        self.load()

    # --- persistence -----------------------------------------------------------------------------
    def _restore(self, d):
        """Populate every field from a payload dict (what load() does after json.load). Every key is
        optional with an empty default, so old snapshots (pre-dividend/shielded/…) still load AND it works
        on a bare (un-__init__'d) instance — see clone()."""
        from execnode.shielded_field import FieldShieldedPool
        self.contracts = d.get("contracts", {})
        self.cursor = d.get("cursor", -1)
        self.bridge = d.get("bridge", {})
        self.withdrawals = d.get("withdrawals", {})
        self.wd_nonce = d.get("wd_nonce", 0)
        self.outbox = d.get("outbox", [])
        self.inbox = d.get("inbox", [])
        self.dividend = d.get("dividend", {})
        self.last_div_epoch = d.get("last_div_epoch", -1)
        self.div_carry = d.get("div_carry", 0)
        self.dividend_withdrawals = d.get("dividend_withdrawals", {})
        self.dw_nonce = d.get("dw_nonce", 0)
        self.shielded = ShieldedPool.from_dict(d["shielded"]) if "shielded" in d else ShieldedPool()
        self.unshield_withdrawals = d.get("unshield_withdrawals", {})
        self.uw_nonce = d.get("uw_nonce", 0)
        self.games = d.get("games", {})
        self.field_pool = FieldShieldedPool.from_dict(d["field_pool"]) if "field_pool" in d else FieldShieldedPool()

    def _snapshot(self):
        """The full serializable payload (identical to what save() writes), taken UNDER the mutate lock so a
        concurrent thread-apply can't tear it. Shared by save() and clone()."""
        with self._mutate_lock:
            return {"contracts": self.contracts, "cursor": self.cursor, "bridge": self.bridge,
                    "withdrawals": self.withdrawals, "wd_nonce": self.wd_nonce,
                    "outbox": self.outbox, "inbox": self.inbox,
                    "dividend": self.dividend, "last_div_epoch": self.last_div_epoch,
                    "div_carry": self.div_carry, "dividend_withdrawals": self.dividend_withdrawals,
                    "dw_nonce": self.dw_nonce, "shielded": self.shielded.to_dict(),
                    "unshield_withdrawals": self.unshield_withdrawals, "uw_nonce": self.uw_nonce,
                    "field_pool": self.field_pool.to_dict(), "games": self.games}

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
        """Restore the last save()d snapshot from self.path, if any."""
        if os.path.exists(self.path):
            with open(self.path) as f:
                d = json.load(f)
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
        os.replace(tmp, self.path)

    def _leaves(self):
        """Every piece of execution-layer state as a canonical Merkle leaf: contract storage, bridged
        balances, and withdrawal records. The set is identical on every honest node → identical root."""
        out = []
        for cid, c in self.contracts.items():
            for m, kv in c.get("storage", {}).items():
                for k, v in kv.items():
                    out.append(canonical_bytes(["kv", cid, m, k, v]))
        for addr, amt in self.bridge.items():
            out.append(canonical_bytes(["bridge_bal", addr, amt]))
        for addr, amt in self.dividend.items():
            out.append(canonical_bytes(["div_bal", addr, amt]))   # commit dividend balances so nodes must agree
        for nonce, w in self.withdrawals.items():
            out.append(withdrawal_leaf(w["addr"], w["amount"], nonce))
        for nonce, w in self.dividend_withdrawals.items():
            out.append(dividend_leaf(w["addr"], w["amount"], nonce))
        # SHIELDED POOL — bound the whole pool to just TWO leaves (root + nullifier digest), so the exec
        # state_root stays O(1) in pool size; plus one leaf per pending unshield exit (provable, GC-able).
        out.append(canonical_bytes(["shield_root", self.shielded.root()]))
        out.append(canonical_bytes(["shield_nfset", self.shielded.nullifier_digest()]))
        out.append(canonical_bytes(["field_root", str(self.field_pool.root())]))
        out.append(canonical_bytes(["field_nfset", *sorted(str(n) for n in self.field_pool.nullifiers)]))
        for nonce, w in self.unshield_withdrawals.items():
            out.append(unshield_leaf(w["addr"], w["amount"], nonce))
        for gid in sorted(self.games):                           # STAKED coin-flip games (escrowed pots + state)
            g = self.games[gid]
            players = sorted([a, p["slot"], p["commit"], p["secret"]] for a, p in g["players"].items())
            out.append(canonical_bytes(["flip_game", gid, g["stake"], g["pot"], bool(g["settled"]), g["deadline"], players]))
        for msg in self.outbox:                                  # cross-domain messages emitted (append-only)
            out.append(_outbox_leaf(msg))
        for i, msg in enumerate(self.inbox):                     # cross-domain messages delivered (append-only)
            out.append(_inbox_leaf(i, msg))
        return out

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
        w = self.unshield_withdrawals.get(str(nonce))
        if not w:
            return None
        proof = merkle_proof(self._leaves(), unshield_leaf(w["addr"], w["amount"], str(nonce)))
        return {"addr": w["addr"], "amount": w["amount"], "nonce": str(nonce), "proof": proof}

    def dividend_withdrawal_proof(self, nonce):
        """(addr, amount, nonce, proof) for a recorded dividend collection, provable against state_root."""
        w = self.dividend_withdrawals.get(str(nonce))
        if not w:
            return None
        proof = merkle_proof(self._leaves(), dividend_leaf(w["addr"], w["amount"], str(nonce)))
        return {"addr": w["addr"], "amount": w["amount"], "nonce": str(nonce), "proof": proof}

    def accrue_dividend_epoch(self, inflow, weights):
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
        """MERKLE root over all execution-layer state — identical on every honest node at the same cursor.
        This is the root the bonded quorum settles on L1; a bridge withdrawal is proven against it."""
        return merkle_root(self._leaves())

    def withdrawal_proof(self, nonce):
        """(addr, amount, nonce, proof) for a recorded withdrawal, provable against state_root; None if absent."""
        w = self.withdrawals.get(str(nonce))
        if not w:
            return None
        proof = merkle_proof(self._leaves(), withdrawal_leaf(w["addr"], w["amount"], str(nonce)))
        return {"addr": w["addr"], "amount": w["amount"], "nonce": str(nonce), "proof": proof}

    def outbox_proof(self, seq):
        """(msg, proof) for outbox message `seq`, provable against state_root; None if absent. Mirrors
        withdrawal_proof: a consumer verifies merkle_proof(leaf, proof, settled_root) against the sender
        rollup's SETTLED root (from L1 /get_settled?ns=) to accept the message trust-minimized."""
        try:
            msg = self.outbox[int(seq)]
        except (IndexError, ValueError, TypeError):
            return None
        return {"message": msg, "proof": merkle_proof(self._leaves(), _outbox_leaf(msg))}

    def apply_xmsg(self, from_ns, message):
        """Deliver an L1-VERIFIED cross-domain message into this rollup's inbox. L1 already verified the
        message against `from_ns`'s SETTLED root and burned its (from_ns, seq) nullifier, so the exec node
        just records it (committed in state_root). Deterministic: every receiver node reads the same `xmsg`
        from the finalized stream and appends the identical inbox entry."""
        self.inbox.append({"from_ns": from_ns, "seq": message.get("seq"), "data": message.get("data")})
        return f"deliver from ns={from_ns} seq={message.get('seq')}"

    def credit_deposit(self, addr, amount):
        """Credit an exec-side bridge balance from an L1 `bridge` deposit (read from the ordered stream)."""
        self.bridge[addr] = self.bridge.get(addr, 0) + int(amount)

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
        if not (-MAX_EXIT_VALUE <= pv <= MAX_EXIT_VALUE) or not (0 <= fee <= MAX_EXIT_VALUE):
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
            if pv < 0:
                self.uw_nonce += 1
                nonce = str(self.uw_nonce)
                self.unshield_withdrawals[nonce] = {"addr": addr, "amount": -pv}
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
            ok, reason = apply_transfer(self.shielded, public, proof, self.shielded.knows_root)
            return f"shield {amount} -> {len(out_commitments)} note(s)" if ok else f"skip shield: {reason}"
        except Exception as e:
            return f"skip shield: {e}"

    def contract_id(self, deployer, code, nonce):
        """Deterministic contract id H(deployer, code, nonce) (truncated) — identical on every exec node,
        so a deployer can know its cid before the blob even lands (submit_blob echoes it)."""
        return blake2b_hash(["deploy", deployer, code, nonce])[:32]

    # --- applying blobs --------------------------------------------------------------------------
    def apply_blob(self, payload, sender, txid):
        """Apply ONE blob payload from sender (the blob tx's L1 sender). Returns a short human string.
        Never raises: a malformed or reverting blob is a no-op ('skip'/'revert')."""
        try:
            if not isinstance(payload, dict):
                return "skip: payload not an object"
            op = payload.get("op")

            if op == "deploy":
                code = payload.get("code")
                rt_name = payload.get("runtime", runtimes.DEFAULT_RUNTIME)   # pluggable: which VM runs it
                rt = runtimes.get(rt_name)
                if rt is None:
                    return f"skip: unknown runtime {rt_name!r}"
                rt.validate_code(code)                    # raises VMError on bad code (caught below)
                cid = self.contract_id(sender, code, payload.get("nonce", txid))
                if cid in self.contracts:
                    return f"skip: contract {cid} already exists"
                storage = {}
                if "constructor" in code:
                    ok, _ret, storage = rt.run(code, "constructor", sender, [], {})
                    if not ok:
                        storage = {}                      # constructor reverted -> deploy with empty state
                abi = payload.get("abi")   # optional, non-consensus UX metadata {method:{args,doc}}
                self.contracts[cid] = {"code": code, "storage": storage, "deployer": sender,
                                       "runtime": rt_name, "abi": abi if isinstance(abi, dict) else {}}
                return f"deploy {cid} ({rt_name}) by {sender[:12]}…"

            if op == "call":
                cid = payload.get("contract")
                method = payload.get("method")
                args = payload.get("args", [])
                c = self.contracts.get(cid)
                if not c:
                    return f"skip: no contract {cid}"
                if not isinstance(args, list):
                    return "skip: args must be a list"
                rt = runtimes.get(c.get("runtime", runtimes.DEFAULT_RUNTIME))
                if rt is None:
                    return f"skip: unknown runtime for {cid}"
                ok, _ret, new_storage = rt.run(c["code"], method, sender, args, c["storage"])
                if ok:
                    c["storage"] = new_storage
                    return f"call {cid}.{method} by {sender[:12]}… -> ok"
                return f"call {cid}.{method} by {sender[:12]}… -> revert (no-op)"

            if op == "upgrade":
                # ALPHANET: contracts are UPGRADABLE by their deployer. The cid + storage are preserved; the code
                # (and optional abi/runtime) are replaced. Only the original deployer may upgrade. This deliberately
                # breaks strict immutability — a mainnet contract would gate this behind on-chain governance / a
                # timelock, but on alphanet the deployer owns their contract outright.
                cid = payload.get("contract")
                code = payload.get("code")
                c = self.contracts.get(cid)
                if not c:
                    return f"skip: no contract {cid}"
                if c.get("deployer") != sender:
                    return "skip: only the deployer can upgrade this contract"
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

            if op == "emit":
                # Emit a cross-domain MESSAGE: append {seq, from, to_ns, data} to the outbox, committed in
                # state_root as an outbox leaf and provable via outbox_proof(seq). This blob only COMMITS the
                # message; a consumer (another rollup / L1) verifies + delivers it against this rollup's
                # SETTLED root separately (doc/rollups-and-settlement.md §7.4). Append-only, seq == index.
                to_ns = payload.get("to_ns")
                if not isinstance(to_ns, str) or not to_ns:
                    return "skip: emit needs a non-empty string to_ns"
                seq = len(self.outbox)
                self.outbox.append({"seq": seq, "from": sender, "to_ns": to_ns, "data": payload.get("data")})
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

            # ---- STAKED COIN FLIP (native betting module) ------------------------------------------------
            if op in ("flip_bet", "flip_reveal", "flip_settle", "flip_claim"):
                from execnode.vm import _hash_value
                gid = str(payload.get("game"))

                if op == "flip_bet":
                    commit, stake = payload.get("commit"), payload.get("stake")
                    if not isinstance(commit, int) or isinstance(commit, bool) or commit < 0:
                        return "skip: bad commit"
                    if not isinstance(stake, int) or isinstance(stake, bool) or stake <= 0:
                        return "skip: bad stake"
                    g = self.games.get(gid)
                    if g is None:                                   # open a new game as player 1
                        if self.bridge.get(sender, 0) < stake:
                            return f"skip: insufficient bridge balance for {sender[:12]}…"
                        self.bridge[sender] -= stake
                        if self.bridge[sender] == 0: del self.bridge[sender]
                        self.games[gid] = {"stake": stake, "pot": stake, "settled": False,
                                           "deadline": self.cursor + FLIP_REVEAL_WINDOW,
                                           "players": {sender: {"commit": commit, "slot": 1, "secret": None}}}
                        return f"flip_bet open {gid} stake {stake} by {sender[:12]}…"
                    if g["settled"]:            return "skip: game already settled"
                    if sender in g["players"]:  return "skip: already in this game"
                    if len(g["players"]) >= 2:  return "skip: game full"
                    if stake != g["stake"]:     return "skip: stake must match the opener's"
                    if self.bridge.get(sender, 0) < stake:
                        return f"skip: insufficient bridge balance for {sender[:12]}…"
                    self.bridge[sender] -= stake
                    if self.bridge[sender] == 0: del self.bridge[sender]
                    g["pot"] += stake
                    g["players"][sender] = {"commit": commit, "slot": 2, "secret": None}
                    g["deadline"] = self.cursor + FLIP_REVEAL_WINDOW   # reveal window opens when both are in
                    return f"flip_bet join {gid} by {sender[:12]}…"

                if op == "flip_reveal":
                    secret = payload.get("secret")
                    if not isinstance(secret, int) or isinstance(secret, bool):
                        return "skip: bad secret"
                    g = self.games.get(gid)
                    if not g or g["settled"]:        return "skip: no open game"
                    if len(g["players"]) < 2:        return "skip: need two players first"
                    pl = g["players"].get(sender)
                    if not pl:                       return "skip: not a player in this game"
                    if pl["secret"] is not None:     return "skip: already revealed"
                    if _hash_value(secret) != pl["commit"]:
                        return "skip: secret does not open your commit"
                    pl["secret"] = secret
                    return f"flip_reveal {gid} by {sender[:12]}…"

                if op == "flip_settle":
                    g = self.games.get(gid)
                    if not g or g["settled"]:        return "skip: nothing to settle"
                    if len(g["players"]) == 2 and all(p["secret"] is not None for p in g["players"].values()):
                        s1 = next(p["secret"] for p in g["players"].values() if p["slot"] == 1)
                        s2 = next(p["secret"] for p in g["players"].values() if p["slot"] == 2)
                        result = int(blake2b_hash([s1, s2]), 16) % 2   # 0 -> slot1 wins, 1 -> slot2 wins
                        wslot = 1 if result == 0 else 2
                        winner = next(a for a, p in g["players"].items() if p["slot"] == wslot)
                        self.bridge[winner] = self.bridge.get(winner, 0) + g["pot"]
                        g["pot"] = 0; g["settled"] = True
                        return f"flip_settle {gid} -> slot{wslot} ({winner[:12]}…) wins"
                    return "skip: both must reveal first (or flip_claim after the deadline)"

                if op == "flip_claim":
                    g = self.games.get(gid)
                    if not g or g["settled"]:        return "skip: nothing to claim"
                    if self.cursor <= g["deadline"]: return "skip: reveal deadline not passed yet"
                    revealed = [a for a, p in g["players"].items() if p["secret"] is not None]
                    if len(revealed) == 1:                          # opponent withheld -> revealer takes the pot
                        w = revealed[0]
                        self.bridge[w] = self.bridge.get(w, 0) + g["pot"]
                        g["pot"] = 0; g["settled"] = True
                        return f"flip_claim {gid} -> {w[:12]}… wins by forfeit"
                    if len(revealed) == 2:                          # already resolvable -> settle instead
                        return "skip: both revealed — use flip_settle"
                    for a, p in g["players"].items():               # nobody revealed / no opponent -> refund stakes
                        self.bridge[a] = self.bridge.get(a, 0) + g["stake"]
                    g["pot"] = 0; g["settled"] = True
                    return f"flip_claim {gid} -> refunded (no result)"

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
                ok, reason = apply_transfer(self.shielded, public, proof, self.shielded.knows_root)
                if not ok:
                    return f"skip shielded_transfer: {reason}"
                pv = int(public.get("public_value", 0))
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
        except VMError as e:
            return f"skip: bad contract ({e})"
        except Exception as e:
            return f"skip: {e}"

    def view(self, cid, method, args):
        """Read-only call: run a method WITHOUT persisting storage; return its RETURN value (or None).
        caller is the sentinel 'view'. Used by the query API (e.g. balanceOf)."""
        c = self.contracts.get(cid)
        if not c:
            return None
        rt = runtimes.get(c.get("runtime", runtimes.DEFAULT_RUNTIME))
        if rt is None:
            return None
        ok, ret, _ = rt.run(c["code"], method, "view", args or [], c["storage"])
        return ret if ok else None

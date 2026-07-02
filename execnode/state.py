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

from hashing import (blake2b_hash, merkle_root, merkle_proof, withdrawal_leaf, dividend_leaf,
                     unshield_leaf, canonical_bytes)
from execnode.vm import validate_code, run, VMError
from execnode.shielded import ShieldedPool, apply_transfer


class ExecState:
    def __init__(self, path):
        self.path = path
        self.contracts = {}        # cid -> {"code": {...}, "storage": {mapname: {key: int}}, "deployer": addr}
        self.cursor = -1           # highest L1 block height fully applied
        self.bridge = {}           # addr -> exec-side bridged balance (credited by L1 `bridge` deposits)
        self.withdrawals = {}      # nonce(str) -> {"addr":.., "amount":..} : provable exit records
        self.wd_nonce = 0          # monotonic withdrawal-nonce counter (deterministic)
        # PRESENCE DIVIDEND (doc/presence-dividend.md): off-L1 accrual of the OPEN-lane DIVIDEND_POOL to the
        # currently-present miners, fidelity-weighted. `collect_dividend` burns a balance into a provable
        # withdrawal (same machinery as the bridge), claimed on L1 against the settled root.
        self.dividend = {}         # addr -> accrued (uncollected) dividend, raw
        self.dividend_pool_seen = 0  # last L1 DIVIDEND_POOL balance already distributed (delta = new dividend)
        self.div_carry = 0         # undistributed remainder carried to the next accrual (no dust lost)
        self.dividend_withdrawals = {}  # nonce(str) -> {"addr":.., "amount":..} : provable dividend claims
        self.dw_nonce = 0          # monotonic dividend-withdrawal nonce counter (deterministic)
        # SHIELDED POOL (doc/privacy.md): a Zerocash-style commitment tree + nullifier set built from L1
        # `shield` deposits + `shielded_transfer` blobs. Only the pool ROOT + a nullifier DIGEST are committed
        # in state_root (compact — not one leaf per note/nullifier), so this scales independently of pool size.
        self.shielded = ShieldedPool()
        self.unshield_withdrawals = {}  # nonce(str) -> {"addr":.., "amount":..} : provable unshield exits
        self.uw_nonce = 0          # monotonic unshield-withdrawal nonce counter (deterministic)
        self.load()

    # --- persistence -----------------------------------------------------------------------------
    def load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                d = json.load(f)
            self.contracts = d.get("contracts", {})
            self.cursor = d.get("cursor", -1)
            self.bridge = d.get("bridge", {})
            self.withdrawals = d.get("withdrawals", {})
            self.wd_nonce = d.get("wd_nonce", 0)
            self.dividend = d.get("dividend", {})
            self.dividend_pool_seen = d.get("dividend_pool_seen", 0)
            self.div_carry = d.get("div_carry", 0)
            self.dividend_withdrawals = d.get("dividend_withdrawals", {})
            self.dw_nonce = d.get("dw_nonce", 0)
            if "shielded" in d:
                self.shielded = ShieldedPool.from_dict(d["shielded"])
            self.unshield_withdrawals = d.get("unshield_withdrawals", {})
            self.uw_nonce = d.get("uw_nonce", 0)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"contracts": self.contracts, "cursor": self.cursor, "bridge": self.bridge,
                       "withdrawals": self.withdrawals, "wd_nonce": self.wd_nonce,
                       "dividend": self.dividend, "dividend_pool_seen": self.dividend_pool_seen,
                       "div_carry": self.div_carry, "dividend_withdrawals": self.dividend_withdrawals,
                       "dw_nonce": self.dw_nonce, "shielded": self.shielded.to_dict(),
                       "unshield_withdrawals": self.unshield_withdrawals, "uw_nonce": self.uw_nonce},
                      f, sort_keys=True)
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
        for nonce, w in self.unshield_withdrawals.items():
            out.append(unshield_leaf(w["addr"], w["amount"], nonce))
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

    def accrue_dividend(self, pool_balance, weights):
        """Distribute the DIVIDEND_POOL growth since the last call among the CURRENTLY-PRESENT open miners,
        pro-rata by their open-lane WEIGHT (fidelity 1..10). `weights` = {addr: weight} for THIS epoch's
        present set; absent miners aren't in it and accrue nothing. The remainder carries so no raw is lost.
        Returns the amount distributed. (Off-L1; the resulting balances are committed in state_root.)"""
        pool_balance = int(pool_balance)
        delta = pool_balance - self.dividend_pool_seen
        if delta <= 0 or not weights:
            self.dividend_pool_seen = max(self.dividend_pool_seen, pool_balance)
            return 0
        pot = delta + self.div_carry
        total_w = sum(max(1, int(w)) for w in weights.values())
        if total_w <= 0:
            return 0
        distributed = 0
        for addr, w in sorted(weights.items()):                  # sorted -> deterministic across nodes
            share = pot * max(1, int(w)) // total_w
            if share:
                self.dividend[addr] = self.dividend.get(addr, 0) + share
                distributed += share
        self.div_carry = pot - distributed                       # keep the sub-unit remainder for next time
        self.dividend_pool_seen = pool_balance
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

    def credit_deposit(self, addr, amount):
        """Credit an exec-side bridge balance from an L1 `bridge` deposit (read from the ordered stream)."""
        self.bridge[addr] = self.bridge.get(addr, 0) + int(amount)

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
                validate_code(code)                       # raises VMError on bad bytecode
                cid = self.contract_id(sender, code, payload.get("nonce", txid))
                if cid in self.contracts:
                    return f"skip: contract {cid} already exists"
                storage = {}
                if "constructor" in code:
                    ok, _ret, storage = run(code, "constructor", sender, [], {})
                    if not ok:
                        storage = {}                      # constructor reverted -> deploy with empty state
                self.contracts[cid] = {"code": code, "storage": storage, "deployer": sender}
                return f"deploy {cid} by {sender[:12]}…"

            if op == "call":
                cid = payload.get("contract")
                method = payload.get("method")
                args = payload.get("args", [])
                c = self.contracts.get(cid)
                if not c:
                    return f"skip: no contract {cid}"
                if not isinstance(args, list):
                    return "skip: args must be a list"
                ok, _ret, new_storage = run(c["code"], method, sender, args, c["storage"])
                if ok:
                    c["storage"] = new_storage
                    return f"call {cid}.{method} by {sender[:12]}… -> ok"
                return f"call {cid}.{method} by {sender[:12]}… -> revert (no-op)"

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
        ok, ret, _ = run(c["code"], method, "view", args or [], c["storage"])
        return ret if ok else None

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

from hashing import blake2b_hash, merkle_root, merkle_proof, withdrawal_leaf, canonical_bytes
from execnode.vm import validate_code, run, VMError


class ExecState:
    def __init__(self, path):
        self.path = path
        self.contracts = {}        # cid -> {"code": {...}, "storage": {mapname: {key: int}}, "deployer": addr}
        self.cursor = -1           # highest L1 block height fully applied
        self.bridge = {}           # addr -> exec-side bridged balance (credited by L1 `bridge` deposits)
        self.withdrawals = {}      # nonce(str) -> {"addr":.., "amount":..} : provable exit records
        self.wd_nonce = 0          # monotonic withdrawal-nonce counter (deterministic)
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

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"contracts": self.contracts, "cursor": self.cursor, "bridge": self.bridge,
                       "withdrawals": self.withdrawals, "wd_nonce": self.wd_nonce}, f, sort_keys=True)
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
        for nonce, w in self.withdrawals.items():
            out.append(withdrawal_leaf(w["addr"], w["amount"], nonce))
        return out

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

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

from hashing import blake2b_hash                 # repo-shared canonical hashing (deterministic)
from execnode.vm import validate_code, run, VMError


class ExecState:
    def __init__(self, path):
        self.path = path
        self.contracts = {}        # cid -> {"code": {...}, "storage": {mapname: {key: int}}, "deployer": addr}
        self.cursor = -1           # highest L1 block height fully applied
        self.load()

    # --- persistence -----------------------------------------------------------------------------
    def load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                d = json.load(f)
            self.contracts = d.get("contracts", {})
            self.cursor = d.get("cursor", -1)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"contracts": self.contracts, "cursor": self.cursor}, f, sort_keys=True)
        os.replace(tmp, self.path)

    def state_root(self):
        """Canonical hash of ALL contract state — identical on every honest execution node at the same
        cursor. This is what a Phase-2 settlement proof would attest to L1."""
        return blake2b_hash({"contracts": self.contracts})

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

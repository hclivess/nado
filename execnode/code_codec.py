"""Contract code as it travels in a blob, and the two pure rules a code event's ADMISSION depends on.

Lives outside execnode/state.py so the L1 side (calls_commit.block_calls, which runs inside block
incorporation and must never import the exec state) and the settlement verifier (exec_state_bind.apply_event)
can share ONE implementation with the chain (S1, EXEC_ROOT_V2_HEIGHT): the decoder, the cid derivation and
the fixed-name allowlist. Pure: no state, no network, no disk."""
import base64
import json

import zstandard as _zstd

from hashing import blake2b_hash

CONTRACT_CODE_MAX_BYTES = 4 * 1024 * 1024

# FIXED-NAME deploys (doc/faucet.md §4): a SYSTEM contract may claim a well-known literal cid instead of the
# derived hash, so the L1 reserved recipient, the exec ledger key and the contract address are all the same
# word. Allowlisted per name to a sole deployer — deterministic on every exec node, and the reserved-name
# namespace can't be squatted.
FIXED_CIDS = {"faucet": "ebd27698662f14ee2389e509781d5ff57487f4289a4d67",
              "sovereign": "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"}


def bounded_unzstd(body, cap):
    dctx = _zstd.ZstdDecompressor(); parts, total = [], 0
    with dctx.stream_reader(body) as r:
        while True:
            ch = r.read(65536)
            if not ch:
                break
            total += len(ch)
            if total > cap:
                raise ValueError("contract code decompresses beyond cap")
            parts.append(ch)
    return b"".join(parts)


def decode_code(payload):
    """The code map a deploy/upgrade payload carries: raw `code`, or zstd+base64 `codez` decoded under the
    size cap. Raises on an undecodable `codez` — the chain skips such a blob, and so must every mirror."""
    cz = payload.get("codez")
    if cz is None:
        return payload.get("code")
    return json.loads(bounded_unzstd(base64.b64decode(cz), CONTRACT_CODE_MAX_BYTES))


def contract_id(deployer, code, nonce):
    """Deterministic contract id H(deployer, code, nonce) (truncated) — identical on every exec node, so a
    deployer can know its cid before the blob even lands (submit_blob echoes it). ExecState.contract_id
    delegates here; the settlement verifier derives a deploy event's cid through the same line."""
    return blake2b_hash(["deploy", deployer, code, nonce])[:32]

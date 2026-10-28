"""The block auth root is a BLAKE2s chain at every height.

auth_root (a block-header field: the ordered authorization entries of the block's transactions) was an alghash chain
over leaves reduced mod the Goldilocks prime on generation 28. On generation 29, block 0 included, it is a BLAKE2s chain
over the same entries (Goldilocks retirement G2; BLAKE_EXEC_HEIGHT inlined in G9):
  1. (generation 28's alghash root, run under its dormant gate, retired in G9)
  2. LIVE: the root is the BLAKE2s chain (recomputed independently), as an int; block 0's
     empty root is 0 (the chain starts from 32 zero bytes); a reordered, dropped or altered entry moves it; the
     leaf and node personalizations are disjoint from the exec root's;
  3. evidence: raw evidence still checks against a BLAKE2s root (compared exactly, not mod P); stark evidence is
     refused for it (no Goldilocks validity proof of a BLAKE2s root, option R).

Run: python3 tests/test_the_block_auth_root_is_blake2s_from_the_exec_gate.py
"""
import _harness
HOME = _harness.isolate("nado-test-auth-root-b2-")
import hashlib

from ops import mldsa_block_auth as M
from hashing import canonical_bytes

T = _harness.Report()


def block(h, n=3):
    return {"block_number": h, "parent_hash": "p" * 64,
            "block_transactions": [{"sender": f"ndo{i}" + "x" * 44, "txid": f"{i:064x}", "signature": f"s{i}"}
                                   for i in range(n)]}


def b2_chain(blk):
    node = bytes(32)
    for e in M.auth_entries(blk):
        leaf = hashlib.blake2s(canonical_bytes(["nado-auth-v1", 1, e["height"], e["index"], e["txid"], e["sender"], e["kind"],
                                                e["sig_count"]]), digest_size=32, person=b"NADOauL1").digest()
        node = hashlib.blake2s(node + leaf, digest_size=32, person=b"NADOauR1").digest()
    return int.from_bytes(node, "big")


# ---- 1: dormant — generation 28's alghash auth root — retired in G9: generation 28's rules (BLAKE_EXEC_HEIGHT inlined;
# mldsa_block_auth.auth_leaf, the field leaf, was deleted with it)

# ---- 2, 3: live, at every height (block 0's header included)
raw = {"type": "raw", "witnesses": ["s0", "s1", "s2"]}
b = block(5)
r, c = M.auth_commitments(b)
T.check("2a. live: the auth root is the BLAKE2s chain over the same entries, as an int",
        (r, c) == (b2_chain(b), 3) and isinstance(r, int))
T.check("2a'. live at every height: block 0 and a far height chain the same way",
        all(M.auth_commitments(block(h)) == (b2_chain(block(h)), 3) for h in (0, 1, 273000, 1 << 62)))
T.check("2b. live: block 0's empty root is 0 (the chain starts from 32 zero bytes)", M.auth_root([], 0) == 0)
swapped = dict(b, block_transactions=list(reversed(b["block_transactions"])))
dropped = dict(b, block_transactions=b["block_transactions"][:2])
altered = dict(b, block_transactions=[dict(b["block_transactions"][0], txid="f" * 64)] + b["block_transactions"][1:])
T.check("2c. live: a reordered, dropped or altered entry moves the root",
        len({r, M.auth_commitments(swapped)[0], M.auth_commitments(dropped)[0], M.auth_commitments(altered)[0]}) == 4)
from execnode import exec_root_b2 as R2
T.check("2d. the auth personalizations are disjoint from the exec root's",
        not ({M.AUTH_PERSON_LEAF, M.AUTH_PERSON_NODE} & {R2.PERSON_SLOT, R2.PERSON_CODE, R2.PERSON_META, R2.PERSON_KVX,
                                                          R2.PERSON_REC, R2.PERSON_CODEV, R2.PERSON_ROOT}))
b["auth_root"], b["auth_count"] = r, c
T.check("3a. live: raw evidence checks against the BLAKE2s root", M.evidence_ok(raw, b)[0])
T.check("3b. live: the root is compared exactly, not mod P", not M.evidence_ok(raw, dict(b, auth_root=r + 0xFFFFFFFF00000001))[0])
ok, why = M.evidence_ok({"type": "stark"}, b)
T.check("3c. live: stark evidence is refused for a BLAKE2s root", not ok and "raw evidence only" in why, why)
T.done("ALL PASS — the block auth root is BLAKE2s at every height")

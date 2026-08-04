"""
A proof must verify the SAME after a JSON round trip. It is the only state a proof is ever used in.

WHY THIS EXISTS. A settle proof is produced in memory, where alghash2 digests and GF(p^2) elements are
TUPLES. It is then transmitted — inline in a transaction, or published to DA and fetched back — and
transmission is JSON, where `json.loads` turns every tuple into a LIST. The prover self-checks its
in-memory copy and passes; the verifier works from the transmitted copy.

Four separate places assumed "tuple" and therefore broke on the transmitted form:

    backend._Alghash2._enc   isinstance(x, tuple)  -> int(<list>)  : the Fiat-Shamir transcript could not
                                                                     even be BUILT
    extf.lift                type(v) is tuple      -> <list> % P   : "the normalisation funnel", so this
                                                                     broke every ext-field path at once
    merkle.verify            h == root             -> (1,2,3,4) != [1,2,3,4]
    merkle.verify_digest     h == root             -> same, on the ext layers

The consequence was that NO alghash2-backend proof could ever verify after transmission — which is the
only thing a proof is for. It stayed invisible for the entire life of the feature because a settle proof
is ~118 MiB against an 8 MiB submit cap: all 89 historical attempts were refused for SIZE before a
verifier ever ran. The first proof to reach verification (2026-08-04, once DA transport worked) failed
immediately, and each fix merely exposed the next one.

THE INVARIANT, and why it is stated on the primitives rather than on a whole proof: building a real proof
requires proving, which is Rust-only on a node and minutes long. These four primitives are where the
tuple/list distinction actually bites, so pinning them here is both cheap and precise. A whole-proof check
lives in the settle prover sim.

Run: python3 tests/test_proof_json_roundtrip.py
"""
import json
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_rtrip_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def jrt(x):
    """Exactly what transmission does to a value: tuples become lists."""
    return json.loads(json.dumps(x))


from execnode.stark import backend as _backend, extf as ext2, merkle, alghash2 as A2, field as F  # noqa: E402

B = _backend.ALGHASH2

# ---- 1. THE TRANSCRIPT ENCODER -----------------------------------------------------------------------
digest = A2.hashn([1, 2, 3])
items = [7, digest, "label", 99]
check("a digest is a tuple in memory (the premise)", isinstance(digest, tuple))
check("_enc(list-form) == _enc(tuple-form)", B._enc(jrt(items)) == B._enc(items))
check("t_absorb is identical across the round trip",
      B.t_absorb(B.t_init("x"), jrt(items)) == B.t_absorb(B.t_init("x"), items))

# ---- 2. THE EXT-FIELD NORMALISATION FUNNEL -----------------------------------------------------------
e = ext2.lift(12345)
check("an ext element is a tuple in memory", isinstance(e, tuple))
check("lift(list-form) == lift(tuple-form)", ext2.lift(jrt(e)) == ext2.lift(e))
check("lift is idempotent on its own output", ext2.lift(ext2.lift(e)) == ext2.lift(e))
check("lift still embeds a bare scalar", ext2.lift(5)[0] == 5 % ext2.P)
over = tuple([1] * (ext2.DEGREE + 1))
raised = False
try:
    ext2.lift(list(over))
except ValueError:
    raised = True
check("a too-long LIST is still rejected, exactly as a too-long tuple is", raised)

# ---- 3. MERKLE OPENINGS ------------------------------------------------------------------------------
# NO CONDITIONAL SKIPS HERE. An earlier draft guarded these on `hasattr(merkle, "layers")`, which does not
# exist — so three assertions silently did not run and the section "passed" without testing anything.
leaves = [i * 7 + 1 for i in range(8)]
root, layers = merkle.commit(leaves, B)
idx = 3
path = merkle.open_at(layers, idx)
check("verify holds with in-memory tuples", merkle.verify(root, idx, leaves[idx], path, B))
check("verify holds after the root and path are round-tripped",
      merkle.verify(jrt(root), idx, leaves[idx], jrt(path), B))
check("a WRONG leaf is still rejected after the round trip",
      not merkle.verify(jrt(root), idx, leaves[idx] + 1, jrt(path), B))
check("a TAMPERED path is still rejected after the round trip",
      not merkle.verify(jrt(root), idx, leaves[idx], jrt(merkle.open_at(layers, (idx + 1) % 8)), B))

# verify_digest (the ext-layer opening helper) takes a PRECOMPUTED leaf digest
ld = B.leaf(leaves[idx])
check("verify_digest holds with in-memory tuples", merkle.verify_digest(root, idx, ld, path, B))
check("verify_digest holds after the round trip",
      merkle.verify_digest(jrt(root), idx, jrt(ld), jrt(path), B))
check("verify_digest still rejects a wrong leaf digest after the round trip",
      not merkle.verify_digest(jrt(root), idx, jrt(B.leaf(leaves[idx] + 1)), jrt(path), B))

# same_digest is the shared comparison the two verify helpers use
d = A2.hashn([9, 9])
check("same_digest: tuple vs its list form compares EQUAL", merkle.same_digest(d, list(d)))
check("same_digest: differing digests still compare UNEQUAL",
      not merkle.same_digest(d, list(A2.hashn([9, 8]))))
check("same_digest: different lengths are unequal", not merkle.same_digest(d, list(d)[:-1]))
check("same_digest: hex-string digests (blake2b) fall through unchanged",
      merkle.same_digest("ab" * 32, "ab" * 32) and not merkle.same_digest("ab" * 32, "cd" * 32))

# ---- 4. THE TUPLE PATH IS BYTE-IDENTICAL — nothing that worked before may change ----------------------
# Every fix accepts lists IN ADDITION to tuples; none of them alters what a tuple produces. If this fails,
# the change is consensus-visible and must not ship.
check("_enc on tuples is unchanged by the fix", B._enc([digest]) == [int(x) % F.P for x in digest])
check("lift on a tuple returns that tuple normalised", ext2.lift(e) == e)
check("same_digest on two identical tuples is True", merkle.same_digest(d, d))

print()
print("ALL PASS — a transmitted proof encodes, lifts and compares exactly like an in-memory one"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

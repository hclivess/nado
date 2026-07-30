"""THE usehint SUB-CIRCUIT PRODUCES OVER-DEGREE PROOFS FOR ~HALF OF ALL SIGNATURES.

MEASURED: 24 fresh signatures — usehint's inner proof fails the FRI low-degree acceptance test in 12 of them,
always at coefficient index 1. norm_z, proved by the same code with the same geometry and the same
MAX_DEGREE = 2, fails 0 of 24. It is a coin flip on the witness, confined to one sub-circuit.

WHAT THIS MEANS. prove_fold refuses to fold an inner proof that does not verify — correctly; that is the
verifier doing its job. So SIG_AGG_STARK cannot be enabled: roughly half of all signatures would yield an
unfoldable proof. This is a CIRCUIT defect (the usehint composition exceeds its declared degree bound for some
inputs), not a flag decision and not a performance problem.

WHY IT WAS NEVER SEEN. tests/test_block_auth_wiring.py under NADO_HEAVY has NEVER completed: two attempts were
OOM-killed mid-proving and one timed out, all before this assertion was reached. And
tests/test_mldsa_hint_air.py passes ALL its checks — the AIR is semantically right (decompose / UseHint /
hint-weight match Dilithium); it is the PROOF of it that is over-degree. A semantic test cannot catch this.

WHY IT IS NOT THE RUST PORT. A port bug would be deterministic, and norm_z shares the entire prover path.
tests/test_fri_blowup2_parity.py separately shows the Rust FRI is byte-identical to fri.prove at blowup=2,
which is this circuit's geometry.

This runs in ~5 minutes because it skips the fold entirely: _items() (the per-sub-circuit STARK proofs) costs
~10-25s per signature, while prove_fold/prove_comp cost HOURS for witnesses that succeed. It applies exactly
the check fri_verify.py:137 applies.

FIXED. The cause was NOT a degree declaration: constraint #60 asserted `r == q-1`, while Dilithium's wrap
case is `r - r0 == q-1` — a different quantity that coincides only at one point. So for ~half of all
signatures the TRACE violated its own AIR, C/Z was a rational function rather than a polynomial, and FRI
correctly refused the final layer. Every layer behaved properly; the input was invalid.

Now 24 clean / 24. This file stays as the regression: it is the only test that exercises the wrap branch
across enough witnesses to hit it, and the AIR's own semantic tests cannot catch a valid circuit with an
invalid witness.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import mldsa_sig_proof as SP, mldsa_verify as MV, fri, field as F, extf
from signatures import generate_keydict, sign, unhex


def lowdeg_ok(fp):
    """The exact check: interpolate the final layer on its own coset, require coefficients >= deg_bound to
    vanish. The coset offset squares once per committed layer, mirroring fri.prove's loop."""
    off = int(fp["offset"]) % F.P
    for _ in range(len(fp["roots"])):
        off = F.mul(off, off)
    final = fp["final"]
    coeffs = fri._coset_interpolate_ext(final, off) if fp.get("ext") else fri._coset_interpolate(final, off)
    bound = max(1, len(final) // fp["blowup"])
    zero = extf.ZERO if fp.get("ext") else 0
    bad = [i for i, c in enumerate(coeffs[bound:], start=bound) if c != zero]
    return (not bad), bound, len(coeffs), bad[:3]


def main():
    clean = badcount = 0
    for i in range(24):
        keys = generate_keydict()
        txid = ("%02x" % (i + 1)) * 32
        sig_hex = sign(private_key=keys["private_key"], message=unhex(txid))
        pk, msg, sig = bytes.fromhex(keys["public_key"]), unhex(txid), bytes.fromhex(sig_hex)
        if not MV.verify(pk, msg, sig):
            print(f"trial {i:2d} SKIP — reference verify failed (bad fixture)", flush=True)
            continue
        t0 = time.time()
        pl = SP.plan(pk, msg, sig)
        if pl is None:
            print(f"trial {i:2d} SKIP — plan() returned None", flush=True)
            continue
        items, _airs = SP._items(pl, ("norm_z", "usehint"), 2)
        parts = []
        allok = True
        for j, it in enumerate(items):
            good, bound, ncoef, badix = lowdeg_ok(it["proof"]["fri"])
            parts.append(f"p{j}={'ok' if good else 'BAD@' + str(badix)}")
            if not good:
                allok = False
                badcount += 1
        clean += 1 if allok else 0
        print(f"trial {i:2d} {time.time() - t0:6.1f}s  " + "  ".join(parts), flush=True)
    print(f"\nRESULT: {clean} clean trials, {badcount} bad inner proofs out of 24 signatures", flush=True)
    print("ANY BAD => data-dependent AIR defect (pre-existing). ALL OK => the ~75s failure was something "
          "else; re-run the full NADO_HEAVY test and read the actual error.", flush=True)


if __name__ == "__main__":
    main()

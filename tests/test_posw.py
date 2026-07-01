"""
Hash-based Proof of Sequential Work (ops/posw): a valid proof verifies, verification is deterministic and
cheap, and proofs that skipped the sequential work are rejected. Small parameters for a fast test.

Run: python3 tests/test_posw.py
"""
import os, sys, copy, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import posw

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T, S, K = 1000, 10, 16                       # C = 100 segments; fast
CH = posw.challenge_bytes("ndoalice", "0" * 64)


def t1_valid_proof_verifies():
    p = posw.prove(CH, T, S, K)
    assert posw.verify(CH, p, T, S, K), "honest proof must verify"

def t2_deterministic():
    assert posw.prove(CH, T, S, K)["root"] == posw.prove(CH, T, S, K)["root"], "chain is deterministic"

def t3_verify_is_cheap():
    # verification must touch only ~(k+1) segments, never the full T chain (soundness of the cost claim)
    p = posw.prove(CH, T, S, K)
    assert len(p["openings"]) <= K + 1, "verifier only checks the opened segments"

def t4_wrong_challenge_rejected():
    p = posw.prove(CH, T, S, K)
    other = posw.challenge_bytes("ndobob", "0" * 64)
    assert not posw.verify(other, p, T, S, K), "a proof for a different challenge must be rejected"

def t5_tampered_opening_rejected():
    p = posw.prove(CH, T, S, K)
    bad = copy.deepcopy(p)
    # flip the endpoint of the first opening — its segment recompute now mismatches
    o = bad["openings"][0]
    o["cj1"] = ("f" * 64) if o["cj1"] != "f" * 64 else ("e" * 64)
    assert not posw.verify(CH, bad, T, S, K), "a tampered opening must be rejected"

def t6_no_work_rejected():
    # a prover that does NO sequential work (all checkpoints after c_0 are garbage) is caught deterministically
    # because segment 0 is ALWAYS opened and binds c_1 = H^S(c_0).
    C = T // S
    cps = [posw._h(CH)] + [posw._h(b"fake" + m.to_bytes(4, "big")) for m in range(1, C + 1)]
    layers = posw._merkle_layers(cps)
    root = layers[-1][0]
    segs = sorted(set([0] + posw._fiat_shamir(root, C, K)))
    forged = {"root": root.hex(), "openings": [{
        "j": j, "cj": cps[j].hex(), "cj1": cps[j + 1].hex(),
        "pj": [x.hex() for x in posw._merkle_proof(layers, j)],
        "pj1": [x.hex() for x in posw._merkle_proof(layers, j + 1)],
    } for j in segs]}
    assert not posw.verify(CH, forged, T, S, K), "a no-work proof must be rejected"

def t7_partial_work_rejected():
    # 20% real work, 80% garbage: some opened segment lands in the garbage region -> rejected
    C = T // S
    cps = [posw._h(CH)]
    h = cps[0]; honest = C // 5
    for m in range(1, C + 1):
        if m <= honest:
            for _ in range(S): h = posw._h(h)
            cps.append(h)
        else:
            cps.append(posw._h(b"g" + m.to_bytes(4, "big")))
    layers = posw._merkle_layers(cps); root = layers[-1][0]
    segs = sorted(set([0] + posw._fiat_shamir(root, C, K)))
    forged = {"root": root.hex(), "openings": [{
        "j": j, "cj": cps[j].hex(), "cj1": cps[j + 1].hex(),
        "pj": [x.hex() for x in posw._merkle_proof(layers, j)],
        "pj1": [x.hex() for x in posw._merkle_proof(layers, j + 1)],
    } for j in segs]}
    assert not posw.verify(CH, forged, T, S, K), "an 80%-skipped proof must be rejected"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)

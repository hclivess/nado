"""
ML-DSA-44 verify AIR — sub-circuit 7: the SHAKE SPONGE (execnode/stark/mldsa_sponge_air.py), composed from the
proven Keccak-f[1600] permutation. Validated against hashlib (OpenSSL). See doc/zk-signature-aggregation.md.

Run: python3 tests/test_mldsa_sponge_air.py            (schedule/reference checks — fast)
     NADO_HEAVY=1 python3 tests/test_mldsa_sponge_air.py   (+ a real proven single-block SHAKE, minutes)
"""
import os, sys, hashlib, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_sponge_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_sponge_air as SP, mldsa_keccak_air as K

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def t_reference_matches_openssl():
    for name, f, h, rate in (("shake128", SP.shake128, hashlib.shake_128, SP.RATE_128),
                             ("shake256", SP.shake256, hashlib.shake_256, SP.RATE_256)):
        for msg, out in ((b"", 32), (b"abc", 64), (os.urandom(200), 32), (os.urandom(1000), 200)):
            check(f"{name} len={len(msg)} out={out} matches hashlib", f(msg, out) == h(msg).digest(out))


def t_padding_is_public_and_canonical():
    """pad10*1 + the SHAKE domain byte, derived from the message length alone."""
    for rate in (SP.RATE_128, SP.RATE_256):
        for n in (0, 1, rate - 2, rate - 1, rate, rate + 1):
            p = SP.pad(b"\x00" * n, rate)
            check(f"pad(rate={rate}, len={n}) is a whole number of blocks", len(p) % rate == 0)
            check(f"pad(rate={rate}, len={n}) sets the final bit", p[-1] & 0x80 == 0x80)
            check(f"pad(rate={rate}, len={n}) starts with the domain byte", p[n] & 0x1F == 0x1F)


def t_schedule_structure():
    """The schedule must have one permutation step per absorbed block, plus one per extra squeeze chunk."""
    for rate, f in ((SP.RATE_256, SP.shake256), (SP.RATE_128, SP.shake128)):
        msg = os.urandom(3 * rate)                     # forces 4 absorb blocks after padding
        steps, out = SP.schedule(msg, 32, rate)
        check(f"rate={rate}: absorb-only schedule has one step per block ({len(steps)} steps)",
              len(steps) == len(SP.blocks(msg, rate)))
        # a long output forces extra squeeze permutations
        steps2, out2 = SP.schedule(msg, 3 * rate, rate)
        check(f"rate={rate}: long squeeze adds permutations", len(steps2) > len(steps))
        check(f"rate={rate}: schedule output == reference", out2 == f(msg, 3 * rate))
    # every step's output really is keccak_f of its input
    steps, _ = SP.schedule(b"nado", 32, SP.RATE_256)
    check("every schedule step is a real keccak_f", all(post == K.keccak_f(pre) for pre, post in steps))


def t_chaining_is_verifier_derived():
    """Changing the message changes the schedule — the verifier derives states from public data, so a proof
    for one message cannot be replayed for another."""
    s1, _ = SP.schedule(b"message-one", 32, SP.RATE_256)
    s2, _ = SP.schedule(b"message-two", 32, SP.RATE_256)
    check("different messages yield different sponge states", s1[0][0] != s2[0][0])


def t_proven_sponge():
    """HEAVY: a real single-block SHAKE256 proven end-to-end (one permutation proof) and verified against the
    public message + output; a tampered message is rejected."""
    if os.environ.get("NADO_HEAVY") != "1":
        print("SKIP  proven sponge (one full Keccak-f proof, ~2 min) — set NADO_HEAVY=1 to run it")
        return
    msg = b"nado-sponge-air"
    proofs, out = SP.prove(msg, 32, SP.RATE_256, num_queries=2)
    check("proven sponge output matches hashlib", out == hashlib.shake_256(msg).digest(32))
    check("single-block absorb is one permutation proof", len(proofs) == 1)
    ok, why = SP.verify(proofs, msg, 32, SP.RATE_256, num_queries=2)
    check(f"proven SHAKE256 verifies ({why})", ok)
    ok2, _ = SP.verify(proofs, b"different-message", 32, SP.RATE_256, num_queries=2)
    check("a proof cannot be replayed for a different message", not ok2)


if __name__ == "__main__":
    try:
        t_reference_matches_openssl()
        t_padding_is_public_and_canonical()
        t_schedule_structure()
        t_chaining_is_verifier_derived()
        t_proven_sponge()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — the sponge chains proven permutations and matches OpenSSL"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)

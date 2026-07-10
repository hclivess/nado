# tests/test_crypto_threadsafe.py — regression: the ML-DSA backend (signatures.sign/verify/keygen) MUST be
# safe under concurrent calls. The node verifies signatures on many threads at once (HTTP executor validating
# submitted/gossiped txs while the core loop validates a block); the pure-Python dilithium-py backend mutates
# module-level NTT buffers in place, so without serialization a VALID signature spuriously failed verify()
# ~1 in 5 under load -> the intermittent "Could not merge remote transaction: Invalid signature" 403. This
# pins the fix (a process-wide crypto lock): concurrent keygen+sign+verify must yield ZERO false failures.
import sys, threading
sys.path.insert(0, "/root/nado")
from signatures import generate_keydict, sign, verify

F = []
def ck(n, c): print(("  ok  " if c else " FAIL ") + n); (F.append(n) if not c else None)

# 1) concurrent verify of pre-made valid signatures — must never false-reject
N = 32
vecs = []
for i in range(N):
    kd = generate_keydict(); msg = bytes([i % 256]) * 32
    vecs.append((sign(kd["private_key"], msg), msg, kd["public_key"]))
bad = [0]
def vworker(rounds):
    for _ in range(rounds):
        for sig, msg, pub in vecs:
            if not verify(signed=sig, message=msg, public_key=pub):
                bad[0] += 1
ts = [threading.Thread(target=vworker, args=(4,)) for _ in range(8)]
for t in ts: t.start()
for t in ts: t.join()
ck(f"concurrent verify: {bad[0]}/{8 * 4 * N} false rejections (must be 0)", bad[0] == 0)

# 2) concurrent keygen + sign + verify together — the full mix the node runs
bad2 = [0]
def mworker(rounds):
    for _ in range(rounds):
        kd = generate_keydict(); m = b"nado" * 8
        s = sign(kd["private_key"], m)
        if not verify(signed=s, message=m, public_key=kd["public_key"]):
            bad2[0] += 1
ts = [threading.Thread(target=mworker, args=(40,)) for _ in range(8)]
for t in ts: t.start()
for t in ts: t.join()
ck(f"concurrent keygen+sign+verify: {bad2[0]}/{8 * 40} failures (must be 0)", bad2[0] == 0)

# 3) a genuinely bad signature is STILL rejected (the lock didn't turn verify into a rubber stamp)
kd = generate_keydict(); m = b"hello"
good = sign(kd["private_key"], m)
tampered = ("0" if good[0] != "0" else "1") + good[1:]
ck("a tampered signature is rejected", not verify(signed=tampered, message=m, public_key=kd["public_key"]))
ck("wrong message is rejected", not verify(signed=good, message=b"other", public_key=kd["public_key"]))

print("\n" + ("ALL CRYPTO THREAD-SAFETY CHECKS PASSED" if not F else f"{len(F)} FAILED: {F}"))
sys.exit(1 if F else 0)

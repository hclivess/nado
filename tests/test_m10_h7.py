"""
M-10 + H-7 regressions for the field-native shielded pool exec path.

M-10: the delegated-prover POST handlers apply field transfers in worker threads, so the nullifier
check->add must be atomic — two racing identical unshields must NOT both record an exit for one spent note.

H-7: stark.verify must reject a proof whose declared LDE size (N / T) is oversized BEFORE it allocates
F.domain(N) — otherwise an unauthenticated single request (N = 2^32) OOMs the process.

Run: python3 tests/test_m10_h7.py   (slow — generates a real STARK proof)
"""
import os, sys, tempfile, threading, traceback, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_m10_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.stark import alghash, stark
from execnode import shielded_field as SF, shielded

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _unshield_bundle(st):
    """A valid 1-output unshield of a 1000-coin note to ndoAttacker (public_value=-1000, fee=0)."""
    nsk, value, rho = 0x1111, 1000, 0x2222
    st.field_pool.append(alghash.commit(value, alghash.owner_of(nsk), rho))
    pos = st.field_pool.position(alghash.commit(value, alghash.owner_of(nsk), rho))
    out_owner = alghash.owner_of(0x3333)
    bundle, public = SF.prove_transfer(st.field_pool, nsk, value, rho, pos,
                                       0, out_owner, 0x4444, public_value=-1000, fee=0,
                                       withdraw_addr="ndoAttackerAddress")
    bundle["withdraw_addr"] = "ndoAttackerAddress"
    return bundle, public


def t_m10_concurrent_double_unshield_records_one():
    st = ExecState(path=os.path.join(os.environ["HOME"], "m10.json"))
    bundle, _ = _unshield_bundle(st)
    K = 8
    results, barrier = [], threading.Barrier(K)
    lock = threading.Lock()
    def worker():
        barrier.wait()                                   # release all threads at once to maximise contention
        r = st.apply_field_transfer(copy.deepcopy(bundle))
        with lock: results.append(r)
    threads = [threading.Thread(target=worker) for _ in range(K)]
    for t in threads: t.start()
    for t in threads: t.join()
    successes = [r for r in results if "field-unshield" in r]
    dupes = [r for r in results if "double-spend" in r]
    assert len(successes) == 1, f"exactly ONE unshield must record, got {len(successes)}: {results}"
    assert len(dupes) == K - 1, f"the other {K-1} must be double-spend rejects, got: {results}"
    assert st.uw_nonce == 1 and len(st.unshield_withdrawals) == 1, \
        f"one spent note must yield exactly one exit record (uw_nonce={st.uw_nonce}, recs={len(st.unshield_withdrawals)})"


def t_h7_oversized_N_rejected_no_alloc():
    st = ExecState(path=os.path.join(os.environ["HOME"], "h7.json"))
    bundle, public = _unshield_bundle(st)
    ok, _ = shielded.verify_transfer(public, bundle, st.field_pool.knows_root)
    assert ok, "sanity: the untampered proof must verify"
    # N = 2^32 would build a ~34GB F.domain(N). It must be rejected on geometry, instantly, not allocated.
    huge = copy.deepcopy(bundle)
    huge["stark"]["joinsplit"]["proof"]["N"] = 1 << 32
    ok, why = shielded.verify_transfer(public, huge, st.field_pool.knows_root)
    assert not ok, "an oversized N must be rejected"
    # A consistent but over-cap trace length (T beyond MAX_TRACE_ROWS, N=16*T) must also be rejected.
    bigT = copy.deepcopy(bundle)
    T2 = stark.MAX_TRACE_ROWS << 1
    bigT["stark"]["joinsplit"]["proof"]["T"] = T2
    bigT["stark"]["joinsplit"]["proof"]["N"] = 16 * T2
    ok, why = shielded.verify_transfer(public, bigT, st.field_pool.knows_root)
    assert not ok, "a trace length beyond MAX_TRACE_ROWS must be rejected"


check("t_m10_concurrent_double_unshield_records_one", t_m10_concurrent_double_unshield_records_one)
check("t_h7_oversized_N_rejected_no_alloc", t_h7_oversized_N_rejected_no_alloc)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)

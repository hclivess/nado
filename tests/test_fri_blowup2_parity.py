"""FRI PARITY AT blowup=2 — the geometry every earlier differential test missed.

sp_fri_prove was verified against fri.prove over several sizes, but ALL of them used blowup=4. The ML-DSA
sub-circuits use blowup=2, and that is not a cosmetic difference: fri_verify's acceptance test is

    deg_bound = max(1, len(final) // blowup)

so at blowup=2 the two final values must interpolate to a CONSTANT, while at blowup=4 four values may carry a
degree-1 term. A fold that is subtly wrong in the last layer passes the looser bound and fails the tighter one.

This was written while diagnosing a real sig-agg failure ("final layer is not low-degree (bound 1 of 2)") to
answer whether the Rust FRI port had broken blowup=2. It had not — but the coverage gap was real, and a gap
that has to be discovered during an incident should become a test.

Exits non-zero on any mismatch; prints one line per case.
"""
import ctypes, random, sys
sys.path.insert(0,"/srv/nado-dev")
from execnode.stark import stark_native as SN, fri, field as F, extf, backend as B
from execnode.stark.transcript import Transcript
SN.available(); lib = SN._LIB
D = extf.DEGREE; bk = B.RECURSION
random.seed(99); bad = 0; checked = 0
for (N, DEG, blowup) in ((64,32,2),(128,64,2),(256,128,2),(128,32,4)):
    for trial in range(2):
        c = [random.randrange(F.P) for _ in range(DEG)] + [0]*(N-DEG)
        off = F.GENERATOR
        ev = [F.poly_eval(c, x) for x in F.domain(N, off)]
        py = fri.prove(ev, off, blowup=blowup, num_queries=2, transcript=Transcript("fri",backend=bk), backend=bk)
        lib.sp_reset(N, N, off)
        col = (ctypes.c_uint64*N)(*[int(v)%F.P for v in ev])
        cid = lib.sp_load_col(ctypes.cast(col, ctypes.c_void_p), N)
        ids = (ctypes.c_size_t*1)(cid); st = (ctypes.c_uint64*4)()
        lib.sp_tr_init(sum(bytearray(b"fri"))%F.P, ctypes.cast(st, ctypes.c_void_p))
        nl = lib.sp_fri_prove(ctypes.cast(ids,ctypes.c_void_p),1,off,blowup,2,fri.GRIND_BITS,
                              ctypes.cast(st,ctypes.c_void_p),0,D,1)
        sz = lib.sp_fri_size(); buf=(ctypes.c_uint64*sz)(); lib.sp_fri_serialize(ctypes.cast(buf,ctypes.c_void_p))
        h=[buf[i] for i in range(8)]; nlv=h[0]; fl=h[7]
        o=8+2*nlv+nlv*4
        n_final = h[1] >> nlv
        rfin=[tuple(buf[o+i*fl+k] for k in range(fl)) for i in range(n_final)]
        pfin=[tuple(int(x) for x in extf.lift(v)) for v in py['final']]
        checked += 1
        if nlv != len(py['roots']) or rfin != pfin:
            bad += 1
            print(f"  MISMATCH N={N} blowup={blowup} t={trial}: layers rust={nlv} py={len(py['roots'])} "
                  f"n_final rust={n_final} py={len(py['final'])} final_eq={rfin==pfin}", flush=True)
        else:
            print(f"  ok N={N} blowup={blowup} t={trial} layers={nlv} final={n_final}", flush=True)
print(f"RESULT: {checked} cases, {bad} mismatches", flush=True)
import ctypes, random, sys
sys.path.insert(0,"/srv/nado-dev")
from execnode.stark import stark_native as SN, fri, field as F, extf, backend as B
from execnode.stark.transcript import Transcript
SN.available(); lib = SN._LIB
D = extf.DEGREE; bk = B.RECURSION
random.seed(99); bad = 0; checked = 0
for (N, DEG, blowup) in ((64,32,2),(128,64,2),(256,128,2),(128,32,4)):
    for trial in range(2):
        c = [random.randrange(F.P) for _ in range(DEG)] + [0]*(N-DEG)
        off = F.GENERATOR
        ev = [F.poly_eval(c, x) for x in F.domain(N, off)]
        py = fri.prove(ev, off, blowup=blowup, num_queries=2, transcript=Transcript("fri",backend=bk), backend=bk)
        lib.sp_reset(N, N, off)
        col = (ctypes.c_uint64*N)(*[int(v)%F.P for v in ev])
        cid = lib.sp_load_col(ctypes.cast(col, ctypes.c_void_p), N)
        ids = (ctypes.c_size_t*1)(cid); st = (ctypes.c_uint64*4)()
        lib.sp_tr_init(sum(bytearray(b"fri"))%F.P, ctypes.cast(st, ctypes.c_void_p))
        nl = lib.sp_fri_prove(ctypes.cast(ids,ctypes.c_void_p),1,off,blowup,2,fri.GRIND_BITS,
                              ctypes.cast(st,ctypes.c_void_p),0,D,1)
        sz = lib.sp_fri_size(); buf=(ctypes.c_uint64*sz)(); lib.sp_fri_serialize(ctypes.cast(buf,ctypes.c_void_p))
        h=[buf[i] for i in range(8)]; nlv=h[0]; fl=h[7]
        o=8+2*nlv+nlv*4
        n_final = h[1] >> nlv
        rfin=[tuple(buf[o+i*fl+k] for k in range(fl)) for i in range(n_final)]
        pfin=[tuple(int(x) for x in extf.lift(v)) for v in py['final']]
        checked += 1
        if nlv != len(py['roots']) or rfin != pfin:
            bad += 1
            print(f"  MISMATCH N={N} blowup={blowup} t={trial}: layers rust={nlv} py={len(py['roots'])} "
                  f"n_final rust={n_final} py={len(py['final'])} final_eq={rfin==pfin}", flush=True)
        else:
            print(f"  ok N={N} blowup={blowup} t={trial} layers={nlv} final={n_final}", flush=True)
print(f"RESULT: {checked} cases, {bad} mismatches", flush=True)

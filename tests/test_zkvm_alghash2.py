"""
alghash2 INSIDE the zkVM (execnode/stark/zkvm_alghash2.py) — bit-identity. The recursion fold's in-VM STARK
verifier (doc/zk-recursion.md §4 Option A) reruns the inner-proof verifier as a zkVM program; its dominant
work is alghash2 hashing (Merkle paths + transcript). This guards that the in-VM permutation and sponge
produce EXACTLY the digests execnode/stark/alghash2.py does — a divergence would make the in-VM verifier
accept proofs the native verifier rejects (or vice-versa). Runs the program on the VM (no proof needed for
the identity check) across 1- and 2-chunk inputs. Run: python3 tests/test_zkvm_alghash2.py
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import zkvm_alghash2 as Z, alghash2 as a2, field as F
from execnode import zkvm

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t_permute_in_vm():
    """One width-12 permutation in the VM == alghash2.permute, on random inputs."""
    from execnode import zkvmasm
    src = "\n".join(
        [("mov r1 r0" if i == 0 else f"movi r1 {i}") for i in range(1)] +  # placeholder; rebuilt below
        [])
    # build a tiny 'perm' contract: load 12 args into state slots, permute, ret
    L = []
    for i in range(a2.WIDTH):
        L += (["mov r1 r0"] if i == 0 else [f"movi r1 {i}", "arg r1 r1"])
        L += [f"movi r4 {Z._slot(i)}", "sstore r4 r1"]
    L += Z.permute_asm() + ["ret r0"]
    code = zkvmasm.assemble_contract({"perm": "\n".join(L)})
    zkvm.validate_code(code)
    random.seed(0)
    for _ in range(3):
        inp = [random.randrange(F.P) for _ in range(a2.WIDTH)]
        res = zkvm.run(code, "perm", inp[0], list(inp), {}, witness=False)
        ok, _ret, ns, _io = res[:4]
        assert ok, "perm reverted"
        got = [ns.get(Z._slot(i), 0) for i in range(a2.WIDTH)]
        assert got == a2.permute(inp), "in-VM permute != alghash2.permute"


def t_hashn_in_vm():
    """alghash2.hashn in the VM == alghash2.hashn, across 1-chunk and 2-chunk element counts."""
    random.seed(1)
    for n in (1, 3, 7, 8, 9, 12):
        code = Z.build_hashn_contract(n)
        zkvm.validate_code(code)
        els = [random.randrange(F.P) for _ in range(n)]
        res = zkvm.run(code, "h", els[0], list(els), {}, witness=False)
        ok, _ret, ns, _io = res[:4]
        assert ok, f"hashn n={n} reverted"
        got = tuple(ns.get(s, 0) for s in Z.digest_slots())
        assert got == a2.hashn(els), f"in-VM hashn n={n} != alghash2.hashn"


if __name__ == "__main__":
    check("alghash2 permutation in the zkVM == alghash2.permute", t_permute_in_vm)
    check("alghash2 hashn in the zkVM == alghash2.hashn (1- & 2-chunk)", t_hashn_in_vm)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)

"""THE STWO JOIN-SPLIT LIBRARY IS LOADED ON THE FIRST VERIFY, NEVER AT IMPORT (execnode/stark/stwo_js_native.py).

A node whose build of native/stwo_js failed (no cargo, a compiler too old) must keep running everything else. So
importing the wrapper with the library absent raises nothing and maps nothing; only a verify (or aux_digest / config)
call raises, and what it raises is native_guard.NativeMissing, which every verifier treats as a node-local fact
(native_guard.NODE_LOCAL_ERRORS: defer, never reject), not as a verdict on the proof. NADO_ALLOW_PYTHON_KERNELS (set by
scripts/run_tests.sh) does not turn it into a silent pass: there is no Python fallback to run.

Run: python3 tests/test_stwo_js_library_loads_on_first_verify_and_never_at_import.py
"""
import os
import sys
import tempfile

_T = tempfile.mkdtemp(prefix="nado-test-stwo-js-lazy-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
os.environ["NADO_STWO_JS_LIB"] = os.path.join(_T, "absent", "libnado_stwo_js.so")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


try:
    from execnode.stark import stwo_js_native as SJ
    imported, err = True, ""
except Exception as e:                         # noqa: BLE001 — the property IS "nothing raises here"
    imported, err = False, repr(e)
check("importing the wrapper with the library absent raises nothing", imported, err)
if not imported:
    sys.exit(1)
check("the import mapped no library", SJ._lib is None)

from execnode.stark.native_guard import NODE_LOCAL_ERRORS, NativeMissing

D = "11" * 32
for name, call in (("verify", lambda: SJ.verify(b"\x00" * 64, D, D, D, D, 0, 0, "")),
                   ("aux_digest", lambda: SJ.aux_digest("")),
                   ("config", lambda: SJ.config())):
    try:
        call()
        got = "returned"
    except NativeMissing as e:
        got = "NativeMissing" if "stwo_js" in str(e) else f"NativeMissing without the crate's name: {e}"
    except Exception as e:                     # noqa: BLE001
        got = repr(e)
    check(f"{name} with the library absent raises NativeMissing naming the crate (even with NADO_ALLOW_PYTHON_KERNELS)",
          got == "NativeMissing", got)
check("NativeMissing is a node-local error (callers defer, never reject)", NativeMissing in NODE_LOCAL_ERRORS)

# a file at the path that is not a loadable library is the same node-local failure, not a crash
bogus = os.path.join(_T, "bogus.so")
open(bogus, "wb").write(b"not an ELF")
os.environ["NADO_STWO_JS_LIB"] = bogus
try:
    SJ.verify(b"\x00", D, D, D, D, 0, 0, "")
    got = "returned"
except NativeMissing:
    got = "NativeMissing"
except Exception as e:                         # noqa: BLE001
    got = repr(e)
check("an unloadable file at the library path raises NativeMissing", got == "NativeMissing", got)

print("ALL PASS — the stwo_js library loads on first verify, never at import" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

"""THE FIELD NAMES THE KERNEL EMITS ARE THE ONES PYTHON READS.

native/attest is Rust, its callers are Python, and nothing between them checks that they agree on a
spelling. They did not: the kernel emits `ek_identity`, four call sites read `identity`, and every one
of them raised KeyError on the first real endorsement certificate — in production, on a user's machine,
after the hard parts all worked.

No test caught it because the tests STUBBED verify_ek, and a stub is written from the caller's side, so
it used the caller's spelling. A stub can only ever confirm that the caller agrees with itself.

This reads the Rust source and the Python wrapper and checks they name the same things, which is the
one check a stub cannot fake.

Run: python3 tests/test_attest_kernel_contract.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-contract-"))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    lib = open(os.path.join(ROOT, "native", "attest", "src", "lib.rs")).read()

    # What nado_ek_verify actually puts in its success object.
    body = lib[lib.index("pub extern \"C\" fn nado_ek_verify"):]
    body = body[:body.index("\n}\n")]
    emitted = set(re.findall(r'"([a-z_0-9]+)":', body))
    check("the kernel's EK verdict was found in the source", emitted, emitted)

    from ops import attest_native
    wrapper = open(os.path.join(ROOT, "ops", "attest_native.py")).read()

    # Every field the callers read must be one the kernel emits, or one the wrapper maps.
    mapped = set(re.findall(r'verdict\["([a-z_0-9]+)"\] = verdict\["([a-z_0-9]+)"\]', wrapper))
    mapped_names = {a for a, _ in mapped} | {b for _, b in mapped}
    available = emitted | mapped_names
    check("the wrapper maps the kernel's ek_identity onto identity",
          "ek_identity" in emitted and "identity" in available,
          f"emitted={sorted(emitted)} available={sorted(available)}")

    # THE CHECK THAT WOULD HAVE CAUGHT IT: every literal key a caller reads off a verify_ek verdict.
    readers = {}
    for rel in ("nado.py", "ops/transaction_ops.py", "ops/account_ops.py", "loops/core_loop.py"):
        src = open(os.path.join(ROOT, rel)).read()
        for var in ("ek", "verdict"):
            for key in re.findall(rf'\b{var}\["([a-z_0-9]+)"\]', src):
                readers.setdefault(key, set()).add(rel)
            for key in re.findall(rf'\b{var}\.get\("([a-z_0-9]+)"\)', src):
                readers.setdefault(key, set()).add(rel)

    # `ok`/`reason` come from the failure object; the WebAuthn verdict has its own wider field set, so
    # only the names this EK path depends on are asserted here.
    ek_path_keys = {"identity", "ek_identity", "manufacturer", "root_sha256"}
    for key in sorted(ek_path_keys & set(readers)):
        check(f"callers may read {key!r}", key in available,
              f"read by {sorted(readers[key])} but the kernel emits {sorted(emitted)}")

    # And the live call agrees: a REFUSAL still carries a reason, and the normaliser does not invent one.
    v = attest_native.verify_ek([b"\x30\x82not a certificate"], 1757548800)
    check("a junk chain is refused with a reason", v.get("ok") is False and v.get("reason"))
    check("a refusal carries no endorsement identity", "identity" not in v, sorted(v))

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())

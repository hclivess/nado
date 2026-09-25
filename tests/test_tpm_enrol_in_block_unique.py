"""A block carries at most one challenge / commit / reveal per (sender, enrolment) (ops/transaction_ops
reserved_uniqueness_key).

Each enrolment message validates against the PARENT record, so a challenger loop's retry could put two copies in one
candidate; the second always raised at apply and the node built a block it could not apply. Pins: the builder keeps one
copy, a block carrying both is refused, distinct enrolments and distinct senders do not collide, and tpm_enrol stays
unkeyed (a second enrolment of one chip applies today, so keying it would change which blocks are valid).

Run: python3 tests/test_tpm_enrol_in_block_unique.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-enrol-unique-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import transaction_ops as T

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def tx(recipient, sender, eid, n):
    return {"recipient": recipient, "sender": sender, "txid": f"{n:064x}", "data": {"id": eid, "blob": "aa"}}


A, B = "a" * 46, "b" * 46
E1, E2 = "01" * 16, "02" * 16
for r in ("tpm_challenge", "tpm_commit", "tpm_reveal"):
    dup = [tx(r, A, E1, 1), tx(r, A, E1, 2)]
    kept = T.dedupe_reserved(dup)
    check(f"{r}: the builder keeps one copy of a duplicate", len(kept) == 1, kept)
    try:
        T.assert_unique_reserved(dup)
        check(f"{r}: a block carrying both copies is refused", False)
    except ValueError:
        check(f"{r}: a block carrying both copies is refused", True)
    check(f"{r}: distinct enrolments and senders do not collide",
          len(T.dedupe_reserved([tx(r, A, E1, 1), tx(r, A, E2, 2), tx(r, B, E1, 3)])) == 3)
check("tpm_enrol stays unkeyed", T.reserved_uniqueness_key(tx("tpm_enrol", A, E1, 1)) is None)

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

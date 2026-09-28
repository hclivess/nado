"""Only device bindings carry across a reroll as device bindings — never the enrolment, eviction or lease rows that share
their table (kv_ops.devbind_rows).

WHY (measured 2026-09-28, the gen-28 rehearsal). The devbind sub-DB also holds "tpmek:<identity>" (the chip's open
enrolment, a packed STRING), "evict:<address>" and "lease:<address>:<epoch>". devbind_rows indexed the string character by
character and returned the marker as a binding of address "3"; the gen-27 carry had already seeded 7 of them into
genesis, and the gen-28 carry refused ("a device binding names 3, which has no recorded key").

Pins, on real tables (throwaway HOME):
  1. real bindings of every shape (leased, permanent, a "tpm:<ek>" class) are returned;
  2. an open-enrolment marker, an enrolment record, an eviction row and a lease-grant row are not;
  3. the carry reads its device bindings from devbind_rows.

Run: python3 tests/test_carry_devices_only.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carrydev-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
from ops import kv_ops

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A1, A2, A3 = "a" * 50, "b" * 50, "c" * 50
kv_ops.devbind_set("android-key:01", A1, 5)
kv_ops.devbind_set("ledger:02", A2, 0, "perm")
kv_ops.devbind_set("tpm:" + "d" * 40, A3, 0)
kv_ops.tpm_enrol_open_set("e" * 40, "3" * 40)                  # the marker: a packed string
# an enrolment record ("tpm:<enrol id>", 13 fields), with an ek that is all digits so int() alone would not skip it
kv_ops.tpm_enrol_set("f" * 40, {"state": "open", "ek": "12345", "ekpub": "", "name": "", "pub": "", "owner": A1, "h": 10,
                                "challengers": [], "blobs": [], "commit": "", "hc": 0, "reveals": [], "hp": 0})
kv_ops.devevict_set(A1, [(3, 2)])
kv_ops.devevict_set(A2, [(3, 2), (7, 6)])
kv_ops.lease_grant_put(A1, 4, 2520)

rows = kv_ops.devbind_rows()
keys = sorted(r[0] for r in rows)
# 1
check("real bindings are returned, each with its account and mode",
      sorted((r[0], r[1], r[3]) for r in rows) == [("android-key:01", A1, "lease"), ("ledger:02", A2, "perm"),
                                                  ("tpm:" + "d" * 40, A3, "lease")], rows)
# 2
check("an open-enrolment marker is not a device (it once carried as a binding of address '3')",
      not any(k.startswith("tpmek:") for k in keys), keys)
check("an enrolment record, an eviction row and a lease-grant row are not devices",
      not any(k.startswith(("evict:", "lease:")) or k == "tpm:" + "f" * 40 for k in keys), keys)
check("every returned address is a whole address, never one character", all(len(r[1]) > 1 for r in rows), rows)
# 3
src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
check("the carry reads its device bindings from devbind_rows", "kv_ops.devbind_rows()" in src)

kv_ops.close_all()
print("ALL PASS — only devices carry as devices" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

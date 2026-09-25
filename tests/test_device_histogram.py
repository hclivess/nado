"""THE DEVICE SPLIT COUNTS WHAT VOUCHES TODAY, AND REMEMBERS WHAT THE CHAIN HAS SEEN.

"/stats should display types of mining devices and their representation" (operator 2026-09-13).

The account rows cannot answer this — the account->device reverse index is stamped only for permanent
classes — so /device_stats reads the devbind table, whose keys carry the class consensus binds on, and
folds it with device_histogram(). That function is pure, so these checks drive it with a list.

Run: python3 tests/test_device_histogram.py
"""
import os, sys, tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_devh_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.node_attest import device_histogram  # noqa: E402
from protocol import LEASE_EPOCHS_BY_CLASS    # noqa: E402
# a chip's lease is its class's grant (per-class leases hold at every epoch since gen 26; gen 25's LEASE_V2_EPOCH gate
# is deleted) — 7 days for "ek", not the historical POSW_LEASE_EPOCHS
EK_LEASE = LEASE_EPOCHS_BY_CLASS["ek"]

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


NOW = 10000
rows = [
    ("ek:aaa",          "A", NOW - 1,                     "lease"),   # chip, fresh lease, present -> live
    ("ek:bbb",          "B", NOW - EK_LEASE - 1,         "lease"),   # chip, lease ran out -> not live
    ("android-key:ccc", "C", NOW - 3,                     "lease"),   # phone, present -> live
    ("android-key:ddd", "D", NOW - 3,                     "lease"),   # phone, NOT present -> not live
    ("ledger:eee",      "E", NOW - 5000,                  "perm"),    # hardware wallet, old statement, present -> live for life
    ("trezor:fff",      "F", NOW - 5000,                  "perm"),    # hardware wallet, not present -> not live
    ("weird",           "G", NOW,                         "lease"),   # no class prefix -> unknown
    ("tpmek:aaa",       "A", NOW,                         "lease"),   # enrolment bookkeeping in the same table -> NOT a device
]
present = {"A", "B", "C", "E", "G"}
h = device_histogram(rows, NOW, present)
c = h["classes"]

check(c["ek"] == {"total": 2, "live": 1}, f"a chip whose lease ran out is counted but not live ({c.get('ek')})")
check(c["android-key"] == {"total": 2, "live": 1}, f"a phone whose account is not present is not live ({c.get('android-key')})")
check(c["ledger"] == {"total": 1, "live": 1}, "a permanent binding is live regardless of how old its statement is")
check(c["trezor"] == {"total": 1, "live": 0}, "...but only while its account is present")
check(c["unknown"] == {"total": 1, "live": 1}, "a key without a class prefix is 'unknown', never dropped")
check("tpmek" not in c, "tpmek:<identity> rows are enrolment bookkeeping, not devices — never a slice")
check(h["live_total"] == 4 and h["bound_total"] == 7, f"totals add up (live {h['live_total']}, bound {h['bound_total']})")

e = device_histogram([], NOW, set())
check(e == {"classes": {}, "live_total": 0, "bound_total": 0}, "no bindings -> empty, zero, zero (never an error)")

# the lease boundary is inclusive: exactly the class's grant old still vouches
b = device_histogram([("ek:x", "X", NOW - EK_LEASE, "lease")], NOW, {"X"})
check(b["classes"]["ek"]["live"] == 1, "a lease exactly the class's grant old is still live (inclusive)")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)

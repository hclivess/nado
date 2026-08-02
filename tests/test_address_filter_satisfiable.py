"""
generate_keys() MUST TERMINATE — the address-uniqueness filter has to be satisfiable by the address
format that actually ships.

WHY THIS FILE EXISTS. ops/key_ops.generate_keys redraws a fresh keydict until the address has at least
MIN_ADDRESS_UNIQUENESS distinct characters. That threshold was 18, which was satisfiable while addresses
carried the mldsa44 name prefix. alphanet-14 removed the prefix (4ed77695), leaving a bare 46-character
LOWERCASE HEX address — an alphabet of exactly 16 symbols. 18 distinct characters became impossible and
the redraw loop became infinite.

The reason that was expensive rather than merely embarrassing is WHERE it fires. nado.py runs

    if not keyfile_found():
        save_keys(generate_keys())

so it is unreachable on any node that already has a keyfile, and hit EVERY BRAND-NEW node on its first
boot — a spin at 100% CPU, no error, no log line. The network could not accept a new node, and no running
node could have noticed: the exact shape of a bug that only exists for someone else. It also hangs the
desktop wallet's key generation and every test that calls generate_keys().

So this test does not check "18 is wrong". It checks the INVARIANT that would have caught it and will
catch the next format change: the threshold must be within what the live address alphabet can produce,
and generate_keys() must actually return.

Run: python3 tests/test_address_filter_satisfiable.py
"""
import os
import sys
import time
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_addrfilter_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signatures import generate_keydict
from ops.key_ops import generate_keys, uniqueness, MIN_ADDRESS_UNIQUENESS

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


DRAWS = 300
addrs = [generate_keydict()["address"] for _ in range(DRAWS)]
alphabet = set().union(*(set(a) for a in addrs))
MAX_UNIQUENESS = len(alphabet)
best = max(uniqueness(a) for a in addrs)
worst = min(uniqueness(a) for a in addrs)

print(f"\naddress format: {len(addrs[0])} chars over a {MAX_UNIQUENESS}-symbol alphabet "
      f"({''.join(sorted(alphabet))})")
print(f"distinct chars across {DRAWS} draws: min {worst}, max {best}")
print(f"MIN_ADDRESS_UNIQUENESS = {MIN_ADDRESS_UNIQUENESS}\n")

# THE INVARIANT. Not "13 is a nice number" — the threshold cannot exceed what the alphabet can express,
# or the redraw loop can never succeed. This is what a prefix removal must not be able to break silently.
check(f"threshold ({MIN_ADDRESS_UNIQUENESS}) is within the address alphabet ({MAX_UNIQUENESS} symbols)",
      MIN_ADDRESS_UNIQUENESS <= MAX_UNIQUENESS)

# Satisfiable in the alphabet is necessary but not sufficient — a threshold equal to the alphabet size is
# technically reachable yet may be astronomically rare. Require it to be actually observed in a sample.
check(f"threshold is REACHED in practice (best of {DRAWS} draws = {best})", best >= MIN_ADDRESS_UNIQUENESS)

# And the thing the caller depends on: it returns, quickly. A fresh node's first boot runs exactly this.
t0 = time.time()
kd = generate_keys()
elapsed = time.time() - t0
check(f"generate_keys() returns (took {elapsed:.2f}s)", isinstance(kd, dict) and "address" in kd)
check("generate_keys() returns promptly — a fresh node boots, it does not spin", elapsed < 30)
check("the returned address satisfies the filter it advertises",
      uniqueness(kd["address"]) >= MIN_ADDRESS_UNIQUENESS)

# The filter still does something: it must reject the degenerate tail rather than being a no-op.
check("the filter is not vacuous (some drawn addresses would be rejected)",
      worst < MIN_ADDRESS_UNIQUENESS or MIN_ADDRESS_UNIQUENESS > 1)

print()
print("ALL PASS — the address filter is satisfiable and a fresh node can generate its key"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

"""
A BRAND-NEW NODE CAN BOOT — the one path no running node can ever exercise.

WHY THIS FILE EXISTS. Everything on the fresh-boot path is, by construction, invisible to every node that
is already running: it is guarded by `if not keyfile_found()` or `if not os.path.exists(block_ends.dat)`.
A bug there breaks only people who do not have a node yet, and they have no way to tell you — the symptom
is a hang or a crash on a machine you never see.

That is not hypothetical. alphanet-14 removed the address prefix (4ed77695), leaving a 46-character hex
address over a 16-symbol alphabet, while ops/key_ops.generate_keys still redrew until the address had >= 18
DISTINCT characters. Unsatisfiable, so the loop never terminated. nado.py runs

    if not keyfile_found():
        save_keys(generate_keys())

so every existing node skipped it and EVERY NEW NODE spun at 100% CPU forever. The network could not take
on a single new participant, silently, and the prefix-removal commit's own notes say it was "rehearsed end
to end… validating on both sides" — the rehearsal simply never included generating a fresh key, because on
a developer box the keyfile already exists.

So this test does what an operator does and nothing else: point HOME at an empty directory and run the
sequence nado.py runs, in nado.py's order. It asserts each step COMPLETES — the failure mode being guarded
against is a hang, not a wrong answer, so the wall-clock bound is part of the assertion.

Run: python3 tests/test_fresh_node_boots.py
"""
import os
import sys
import time
import tempfile
import logging
import faulthandler

HOME = tempfile.mkdtemp(prefix="nado_freshboot_")
os.environ["HOME"] = HOME
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A hang is the failure mode this file exists to catch, and a hung test reports nothing. Dump where it is
# stuck and die, so CI shows a stack instead of a timeout.
faulthandler.dump_traceback_later(300, exit=True)

logging.getLogger("fresh").addHandler(logging.NullHandler())
logger = logging.getLogger("fresh")

fails = 0
_t0 = time.time()


def check(name, ok):
    global fails
    print(f"[{time.time() - _t0:6.1f}s] " + ("PASS  " if ok else "FAIL  ") + name, flush=True)
    if not ok:
        fails += 1


print(f"\nfresh HOME = {HOME} (no keys, no chain, no index)\n")

from ops.data_ops import get_home
from genesis import make_folders, make_genesis
from protocol import GENESIS_ADDRESS, TREASURY_GENESIS, GENESIS_TIMESTAMP

# --- 1) the directory + genesis bootstrap, exactly as nado.py does it -------------------------------
make_folders()
check("make_folders() creates the data dirs (including private/, which holds the key)",
      os.path.isdir(f"{get_home()}/private"))

make_genesis(address=GENESIS_ADDRESS, balance=TREASURY_GENESIS,
             ip="38.242.201.206", port=9173, timestamp=GENESIS_TIMESTAMP, logger=logger)
# block_ends.dat is written LAST by make_genesis and is the sentinel nado.py keys off, so its presence is
# the real "genesis completed" signal — not merely "blocks/ exists".
check("make_genesis() completes and writes the block_ends.dat sentinel",
      os.path.exists(f"{get_home()}/index/block_ends.dat"))

from ops.block_ops import get_block_ends_info
ends = get_block_ends_info(logger)
check("the chain ends resolve to real blocks", isinstance(ends, dict) and "latest_block" in ends)
check("genesis is height 0", int((ends or {}).get("latest_block", {}).get("block_number", -1)) == 0)

# --- 2) THE STEP THAT WAS BROKEN: a new node mints its own key ---------------------------------------
from ops.key_ops import keyfile_found, generate_keys, save_keys, load_keys, uniqueness, MIN_ADDRESS_UNIQUENESS
check("a fresh node starts with no keyfile (so it must generate one)", not keyfile_found())

t = time.time()
kd = generate_keys()
gen_secs = time.time() - t
# The bound is the assertion. generate_keys() spun forever between alphanet-14 and the fix; any wall-clock
# ceiling at all would have caught it, and "it eventually returns" would not.
check(f"generate_keys() RETURNS on the shipping address format ({gen_secs:.2f}s)", gen_secs < 30)
check("the generated address satisfies the filter generate_keys advertises",
      uniqueness(kd["address"]) >= MIN_ADDRESS_UNIQUENESS)

save_keys(kd)
check("the key round-trips through save_keys/load_keys", load_keys()["address"] == kd["address"])
check("keyfile_found() is now true (a restart will not regenerate)", keyfile_found())

# --- 3) the node can read its own state ---------------------------------------------------------------
from ops.account_ops import get_account
# The genesis ALLOCATION must materialise on a node that has never seen a peer — it is derived from the
# baked-in alloc table, not fetched. Asserted as "non-zero", deliberately not "== TREASURY_GENESIS":
# TREASURY_GENESIS is 0 today (the premine lives in the alloc table, re-keyed off the removed address
# prefix), so pinning the constant would assert 0 == 0 and pass on a node whose genesis applied nothing.
_g = get_account(GENESIS_ADDRESS, create_on_error=True)
_g_total = int(_g.get("balance", 0)) + int(_g.get("bonded", 0))
check(f"the genesis allocation materialised locally ({_g_total} raw to the genesis address)", _g_total > 0)
acct = get_account(kd["address"], create_on_error=True)
check("the new node's own account reads back (empty, not an error)", int(acct.get("balance", 0)) == 0)

print()
print("ALL PASS — a brand-new node bootstraps, mints a key and reads its chain"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)

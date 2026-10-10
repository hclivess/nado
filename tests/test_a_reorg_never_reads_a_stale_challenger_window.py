"""A reorg inside a challenger-pool window is never answered from the cache (ops/transaction_ops._window_key).

_recent_producers, _proven_challengers and _duty_presence scan a window of committed blocks and cache the answer; the
answer reaches the state root (the pool is written into the enrolment record). A reorg of up to FINALITY_DEPTH blocks
can replace blocks inside the window, so the caches key on the hash of the window's last block as well as its bounds
(block hashes chain, so that hash names the whole window), as _agreed_time already does.

  * same blocks: the second call is served from the cache (no rescan);
  * the window's last block replaced (new hash, different content): rescanned, and the new answer reflects the new blocks.

Run: python3 tests/test_a_reorg_never_reads_a_stale_challenger_window.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-window-key-")       # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.block_ops as B                                              # noqa: E402
import ops.transaction_ops as T                                        # noqa: E402

FAILED = []
L = P.EPOCH_LENGTH


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


CHAIN = {"fork": "a"}
READS = [0]


def block(n):
    READS[0] += 1
    # on fork "b" the last 10 blocks of every window carry duties from a different validator
    who = "valB" if (CHAIN["fork"] == "b" and n % L >= L - 10) else "valA"
    return {"block_transactions": [{"recipient": "duty", "sender": who + "q" * 46}]}


T.get_block_number = block
B.get_block_hash_by_number = lambda n: "%064x" % (n * 7 + (0 if CHAIN["fork"] == "a" else 10 ** 9))

for name, fn in (("_recent_producers", T._recent_producers), ("_duty_presence", T._duty_presence)):
    T._tpm_producer_cache[0] = None; T._tpm_presence_cache[0] = None; T._tpm_proven_cache[0] = None
    CHAIN["fork"] = "a"
    H = 400 * L + 5
    first = fn(H)
    READS[0] = 0
    again = fn(H)
    check(f"{name}: same blocks are served from the cache", again == first and READS[0] == 0, READS[0])
    CHAIN["fork"] = "b"                                  # a reorg replaced the window's last blocks
    READS[0] = 0
    after = fn(H)
    check(f"{name}: a reorg into the window rescans", READS[0] > 0, READS[0])
    check(f"{name}: and answers from the new blocks", after != first and any(k.startswith("valB") for k in after), sorted(after))

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)

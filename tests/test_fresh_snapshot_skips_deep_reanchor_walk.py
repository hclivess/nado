import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-fresh-snapshot-")
"""A fresh rolling snapshot joiner fetches its rollback window, never a fictitious fork back to genesis.

Measured live 2026-10-12: 185.100.232.5 imported the fleet's valid h178000 checkpoint, then remained at
that height for more than 75 minutes while the fleet moved 700+ blocks ahead. Its status still had
``earliest_block_height=0`` and ``recovery=null``: before either field could advance, canonical restore
treated the expected no-overlap between a fresh node's genesis-only index and the checkpoint's windowed
index as a deep established-node reorg, then fetched parent hashes toward genesis one request at a time.

Run: python3 tests/test_fresh_snapshot_skips_deep_reanchor_walk.py
"""
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"

import atexit
import shutil
import sys

atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for directory in ("index", "blocks", "logs", "peers", "snapshots"):
    os.makedirs(os.path.expanduser(f"~/nado/{directory}"), exist_ok=True)

from ops import kv_ops, snapshot_ops
from ops.block_ops import get_block_number, save_block
import loops.core_loop as core


class Log:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def block(height, parent):
    return {"block_number": height, "block_hash": f"b{height:08x}".ljust(64, "0"),
            "parent_hash": parent, "block_transactions": [], "chain_id": "test"}


# A fresh node knows genesis. The imported snapshot replaces its index with only a recent canonical window;
# absence of an overlap is normal and says nothing about a fork.
genesis = block(0, "0" * 64)
save_block(genesis, logger=Log())
kv_ops.block_index_put_many([(0, genesis["block_hash"])])
old_index = dict(kv_ops.block_by_num_items())

canonical = []
parent = genesis["block_hash"]
for height in range(1, 301):
    item = block(height, parent)
    canonical.append(item)
    parent = item["block_hash"]
donor = {item["block_hash"]: item for item in canonical}


def wipe_index(txn):
    for name in ("block_by_num", "block_by_hash"):
        txn.drop(kv_ops._dbs()[name], delete=False)


kv_ops._write(wipe_index)
kv_ops.block_index_put_many((item["block_number"], item["block_hash"])
                            for item in canonical if item["block_number"] >= 20)
anchor = canonical[-1]
save_block(anchor, logger=Log())


class Memserver:
    archive = False
    port = 0
    earliest_block = genesis


class Node:
    memserver = Memserver()
    logger = Log()


for method in ("_restore_canonical_chain", "_start_tx_reindex"):
    setattr(Node, method, getattr(core.CoreClient, method))
node = Node()

fetched = []


async def fake_fetch(_source, _port, block_hash):
    item = donor.get(block_hash)
    if item:
        fetched.append(item["block_number"])
    return item


snapshot_ops.fetch_block = fake_fetch
core.snapshot_ops.fetch_block = fake_fetch

earliest = node._restore_canonical_chain(old_index, anchor, "donor", fresh_bootstrap=True)

assert fetched, "the rollback window was not fetched"
rollback_floor = anchor["block_number"] - (core.REWARD_WINDOW + 2 * core.EPOCH_LENGTH + core.FINALITY_DEPTH)
assert min(fetched) == rollback_floor, \
    f"fresh bootstrap fetched {min(fetched)} instead of stopping at rollback floor {rollback_floor}"
assert max(fetched) == 299, f"rollback window did not reach the anchor's parent: {max(fetched)}"
assert len(fetched) == 300 - rollback_floor, \
    f"expected exactly the missing rollback-window bodies, got {len(fetched)}"
assert earliest["block_number"] == rollback_floor, earliest
assert get_block_number(rollback_floor) and get_block_number(299), "fetched rollback window is not readable"

# Pin the caller distinction: only a fresh bootstrap may skip. The established reanchor executor test calls
# the default False path and proves its deep history walk remains intact.
source = open(os.path.join(ROOT, "loops", "core_loop.py"), encoding="utf-8").read()
bootstrap = source[source.index("def snapshot_bootstrap"):source.index("def _mesh_height_median")]
assert "fresh_bootstrap=not force_reanchor" in bootstrap

thread = getattr(node, "_tx_reindex_thread", None)
if thread:
    thread.join(timeout=10)

print("ALL PASS — fresh snapshot bootstrap skips the deep reanchor walk")

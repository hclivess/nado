"""mining_history: a tip DIP is not a reorg. Only an anchor mismatch drops the index; the maintainer passes
the finalized floor, so an ordinary rollback never invalidates an indexed height (2026-09-06: every
emergency rollback rescanned 60k full block bodies from genesis and starved the relay)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import mining_history as mh

CHAIN = {}          # height -> (hash, block)


def _mk(h, creator="addr1"):
    return {"block_number": h, "block_timestamp": 1_700_000_000 + h * 6, "block_reward": 100,
            "block_creator": creator, "block_transactions": []}


def _install(n):
    CHAIN.clear()
    for h in range(n):
        CHAIN[h] = (f"h{h:04x}", _mk(h))
    mh.get_block_number = lambda h: CHAIN[h][1] if h in CHAIN else False
    mh.hash_by_number = lambda h: CHAIN[h][0] if h in CHAIN else None
    mh._credit = lambda b: (b["block_creator"], "open", b["block_reward"])
    mh._save = lambda: None
    mh._load = lambda: False
    mh._loaded = True


def main():
    _install(200)
    mh._reset()
    info = mh.catch_up(150, block_time=6, days=1, budget_s=10)
    assert info["upto"] == 150 and not info["building"], info
    days_before = {k: dict(v) for k, v in mh._IDX["days"].items()}

    # 1. the floor dips (a rollback at the tip, above every indexed height): index kept, nothing rescanned
    reads = []
    real = mh.get_block_number
    mh.get_block_number = lambda h: (reads.append(h), real(h))[1]
    info = mh.catch_up(140, block_time=6, days=1, budget_s=10)
    assert info["upto"] == 150 and reads == [], (info, reads)
    assert mh._IDX["days"] == days_before
    mh.get_block_number = real

    # 2. the floor advances: only the new heights are folded in
    reads.clear()
    mh.get_block_number = lambda h: (reads.append(h), real(h))[1]
    info = mh.catch_up(160, block_time=6, days=1, budget_s=10)
    assert info["upto"] == 160 and reads == list(range(151, 161)), (info, reads)
    mh.get_block_number = real

    # 3. a reorg BELOW the indexed height (anchor no longer matches): the index is rebuilt
    CHAIN[160] = ("h_fork", _mk(160, "addr2"))
    info = mh.catch_up(160, block_time=6, days=1, budget_s=10)
    assert info["upto"] == 160 and info["start"] == 0, info
    assert mh._IDX["anchor"] == "h_fork"

    # source pins: the maintainer feeds the finalized floor, never the bare tip, and the reset condition
    # is the anchor alone
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "nado.py")).read()
    body = src[src.index("async def _mining_history_maintainer"):src.index("async def mining_history_handler")]
    assert "get_finalized_height" in body and 'min(memserver.latest_block["block_number"], floor)' in body
    msrc = open(os.path.join(root, "ops", "mining_history.py")).read()
    assert 'tip < _IDX["upto"]' not in msrc
    print("ALL OK")


if __name__ == "__main__":
    main()

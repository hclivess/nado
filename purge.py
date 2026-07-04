"""
purge.py — wipe local chain state so the node resyncs from scratch.

Removes the chain-state directories under the node's data home (get_home() == $HOME/nado,
or <--home>/nado):

  blocks/  — the block store
  index/   — the LMDB key-value state (accounts, producer sets, finality, indices)
  logs/    — node logs

Your keys (private/) and known peers (peers/) are KEPT. On the next start the node rebuilds
genesis — which re-seeds the public bootstrap peer (38.242.201.206) — and resyncs the chain
from the network. Use this when a node is stuck (e.g. can't find peers, wrong/forked chain).

Stop the node FIRST (systemctl stop nado, or CTRL+C / http://127.0.0.1:9173/terminate).
Run from the repo root:  python purge.py         (asks for confirmation)
                         python purge.py -y      (no prompt)
"""
import os
import shutil
import sys

from ops.data_ops import get_home

# Chain state only. private/ (keys) and peers/ (known peers) are deliberately NOT wiped.
TO_WIPEOUT = ["blocks", "index", "logs"]


def purge(assume_yes=False):
    home = get_home()
    present = [d for d in TO_WIPEOUT if os.path.exists(f"{home}/{d}")]

    if not present:
        print(f"Nothing to purge under {home} — chain state already clean.")
        return

    print(f"Data home: {home}")
    print("This will DELETE (node will resync from genesis):")
    for d in present:
        print(f"  - {home}/{d}")
    print(f"Kept: {home}/private (keys), {home}/peers (peers).")

    if not assume_yes:
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted — nothing removed.")
            return

    for d in present:
        path = f"{home}/{d}"
        shutil.rmtree(path)
        print(f"Removed {path}")

    print("Done. Start the node to rebuild genesis and resync from the network.")


if __name__ == "__main__":
    purge(assume_yes=("-y" in sys.argv or "--yes" in sys.argv))

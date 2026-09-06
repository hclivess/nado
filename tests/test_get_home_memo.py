"""data_ops.get_home is memoized per HOME value: same answer as a fresh Path.home() derivation, and it
follows a HOME change (test harnesses and the loopback testnet set HOME per process/phase)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import data_ops


def main():
    a = data_ops.get_home()
    assert a == f"{Path.home()}/nado" and data_ops.get_home() is a
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        b = data_ops.get_home()
        assert b == f"{d}/nado", b
        assert data_ops.get_home() == b
    print("ALL OK")


if __name__ == "__main__":
    main()

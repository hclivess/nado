"""find_common_ancestor answers a merely-SHORT node after ONE probe round: when the peer majority matches our
hash at our own tip, the answerable-range search must not run (27-28 probes per verdict before 2026-09-06)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import fork_resolution as fr


def main():
    ours = {h: f"h{h}" for h in range(0, 1001)}
    peers = [f"p{i}" for i in range(4)]
    calls = []
    def probe(peer, h):
        calls.append((peer, h))
        return (f"h{h}", 1)                       # every peer agrees with us everywhere: we are just short
    anc, probes = fr.find_common_ancestor(lambda h: ours.get(h), tip=1000, peers=peers, probe=probe, floor=500)
    assert anc == 1000 and probes == 1, (anc, probes)
    assert {h for _, h in calls} == {1000}, "only the tip was probed"
    # a real fork below the tip still goes through the full search and lands on the divergence height
    calls.clear()
    def probe2(peer, h):
        return (f"h{h}" if h <= 730 else f"x{h}", 1)
    anc, probes = fr.find_common_ancestor(lambda h: ours.get(h), tip=1000, peers=peers, probe=probe2, floor=500)
    assert anc == 730, anc
    assert probes > 1
    print("ALL OK")


if __name__ == "__main__":
    main()

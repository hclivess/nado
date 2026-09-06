"""transaction_ops.verify_register_device — the consensus attestation rule behind DEVICE_ATTEST_HEIGHT: a
register tx must carry a hardware attestation over blake2b([chain_id, sender, anchor_hash, max_block]) whose
chain ends at a pinned root, evaluated at the ANCHOR block's timestamp. Uses the real native kernel with a
synthetic chain and a test root injected as the pinned set."""
import base64
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _attest_fixtures as FX
from ops import attest_native as AN
from ops import transaction_ops as TO
import protocol as P


def main():
    sender = "ab" * 23
    anchor_hash = "11" * 32
    max_block = 64674
    chal = TO.register_device_challenge(sender, anchor_hash, max_block)
    assert len(chal) == 32
    att, cdj, root_der = FX.build_apple("get.nadochain.com", chal)
    AN.pinned_roots_der = lambda: [root_der]
    AN._roots_blob = None
    now = int(time.time()) + 120
    TO.get_block_number = lambda n: {"block_number": n, "block_hash": anchor_hash, "block_timestamp": now}
    b64 = lambda b: base64.b64encode(b).decode()
    tx = {"sender": sender, "max_block": max_block, "device": {"att": b64(att), "cdj": b64(cdj), "rp": "get.nadochain.com"}}
    v = TO.verify_register_device(tx, anchor_hash)
    assert v["ok"] and v["fmt"] == "apple", v
    for bad, why in (({"sender": sender, "max_block": max_block}, "Missing device"),
                     ({**tx, "max_block": max_block + 1}, "challenge mismatch"),
                     ({**tx, "sender": "cd" * 23}, "challenge mismatch"),
                     ({**tx, "device": {**tx["device"], "att": "!!"}}, "base64"),
                     ({**tx, "device": {**tx["device"], "rp": "evil.example"}}, "rpIdHash")):
        try:
            TO.verify_register_device(bad, anchor_hash)
            raise AssertionError(f"accepted: {why}")
        except AssertionError as e:
            assert why in str(e), (why, str(e))
    # the anchor's own hash must match (a different anchor = a different challenge, but also refused up front)
    try:
        TO.verify_register_device(tx, "22" * 32); raise AssertionError("accepted a foreign anchor")
    except AssertionError as e:
        assert "anchor" in str(e) or "challenge" in str(e), str(e)
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    seg = src[src.index('elif recipient == "register":'):src.index('elif recipient == "msgkey":')]
    assert "if DEVICE_ATTEST_HEIGHT and block_height >= DEVICE_ATTEST_HEIGHT:" in seg and "verify_register_device(transaction, anchor)" in seg
    assert "native/attest" in open(os.path.join(ROOT, "ops", "self_update.py")).read(), "fleet updater must build the crate"
    assert P.DEVICE_ATTEST_HEIGHT == 0
    print("ALL OK")


if __name__ == "__main__":
    main()

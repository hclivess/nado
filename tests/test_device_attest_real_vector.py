"""A REAL phone's attestation (tests/vectors/device_attest_android_key.json) must verify with the production
pinned roots through the native kernel, at the sample's own timestamp, and fail on a foreign challenge."""
import base64
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import attest_native as AN


def _b64d(x):
    x = x.replace("-", "+").replace("_", "/"); return base64.b64decode(x + "=" * (-len(x) % 4))


def main():
    v = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_android_key.json")))
    att, cdj, chal = _b64d(v["att"]), _b64d(v["cdj"]), _b64d(v["challenge_b64url"])
    r = AN.verify(att, cdj, chal, v["now_unix"], rp_ids=[v["rp"]])
    e = v["expect"]
    assert r["ok"] and r["fmt"] == e["fmt"] and r["security_level"] == e["security_level"], r
    assert r["chain"][-1] == e["chain_last"], r["chain"]
    assert not AN.verify(att, cdj, b"\0" * 32, v["now_unix"], rp_ids=[v["rp"]])["ok"]
    assert not AN.verify(att, cdj, chal, v["now_unix"], roots=[], rp_ids=[v["rp"]])["ok"], "no roots -> no verdict"
    print("ALL OK")


if __name__ == "__main__":
    main()

"""ops/identity_log — every register tx seen at /submit leaves one JSON line (node-local, purge-proof), and the audit
groups them into the views that expose a non-individual identity. Operator (2026-09-07): "we should keep logging
identities to make sure they are really individual" — enforcement retired at gen 25, observation kept.
Run: python3 tests/test_identity_log.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-idlog-")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    from ops import identity_log as IL
    from ops.data_ops import get_home

    check("the log lives OUTSIDE <home>/index so a generation purge keeps it",
          IL.log_path() == os.path.join(get_home(), "identity_log.jsonl") and "/index/" not in IL.log_path())
    check("a non-register tx writes nothing", IL.record("1.2.3.4", {"type": "transaction", "sender": "x"}, True) is None
          and not os.path.exists(IL.log_path()))

    # a REAL Android statement (the repo's test vector) parses to its linkage fields
    vec = json.load(open(os.path.join(ROOT, "tests", "vectors", "device_attest_android_key.json")))
    dev = {"att": vec["att"], "cdj": vec["cdj"], "rp": vec.get("rp", "get.nadochain.com")}
    a, b, c = "a" * 46, "b" * 46, "c" * 46
    r1 = IL.record("9.9.9.9", {"type": "register", "sender": a, "max_block": 500, "device": dev}, True)
    check("a register tx is recorded with the device summary",
          r1 and r1["device"]["fmt"] == "android-key" and r1["device"]["leaf_sha256"] and r1["device"]["root_sha256"]
          and r1["device"]["aaguid"] and r1["kind"] == "entry" and r1["accepted"] is True, r1)
    IL.record("9.9.9.9", {"type": "register", "sender": b, "max_block": 500, "device": dev}, True)
    IL.record("9.9.9.9", {"type": "register", "sender": c, "max_block": 500, "device": {"att": "!!", "cdj": "!!"}}, False)
    IL.record("5.5.5.5", {"type": "register", "sender": c, "max_block": 500, "device": {"att": "!!", "cdj": "!!"}}, True)
    check("a malformed statement still leaves a line (parse_error), never raises",
          any(r.get("device", {}).get("parse_error") for r in IL.iter_records()))
    # a torn line must not hide the rest
    with open(IL.log_path(), "a") as f:
        f.write('{"ts": 1, "truncated')
    recs = list(IL.iter_records())
    check("four records survive a torn trailing line", len(recs) == 4, len(recs))

    rep = IL.audit(recs)
    check("audit: 3 distinct accepted identities (a rejected line is not counted)", rep["identities"] == 3, rep["identities"])
    check("audit: by_ip puts the 2-identity address first", rep["by_ip"][0] == ("9.9.9.9", [a, b]), rep["by_ip"])
    check("audit: two senders behind one leaf certificate are grouped (the same-device signal)",
          rep["by_leaf"] and rep["by_leaf"][0][1] == [a, b], rep["by_leaf"])
    check("audit: by_fmt counts identities per device class", dict(rep["by_fmt"]).get("android-key") == 2, rep["by_fmt"])
    check("audit: a window excludes old records", IL.audit(recs, window_s=1.0, now=recs[0]["ts"] + 10)["identities"] == 0)

    # wiring: the /submit ingress records every register tx with the mempool verdict
    nado = open(os.path.join(ROOT, "nado.py")).read()
    seg = nado[nado.index("def _work(body, ip):"):nado.index("def _work(body, ip):") + 1500]
    check("/submit records the register tx after the mempool verdict", "identity_log.record(ip, transaction," in seg)
    kv_ops.close_all()


if __name__ == "__main__":
    main()
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)

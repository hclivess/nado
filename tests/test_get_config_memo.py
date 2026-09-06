"""config.get_config is memoized per file version: a rewrite (update_config's atomic rename, or an in-place
edit) is seen on the next call, and callers always get their own copy."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg


def main():
    d = tempfile.mkdtemp(); p = os.path.join(d, "config.json")
    json.dump({"ip": "1.1.1.1", "port": 1}, open(p, "w"))
    a = cfg.get_config(p); b = cfg.get_config(p)
    assert a == b == {"ip": "1.1.1.1", "port": 1} and a is not b
    a["ip"] = "mutated"
    assert cfg.get_config(p)["ip"] == "1.1.1.1", "callers must not see each other's mutations"
    cfg.update_config({"ip": "2.2.2.2"}, p)
    assert cfg.get_config(p)["ip"] == "2.2.2.2", "atomic rename seen"
    time.sleep(0.01)
    json.dump({"ip": "3.3.3.3", "port": 1}, open(p, "w"))
    assert cfg.get_config(p)["ip"] == "3.3.3.3", "in-place edit seen"
    print("ALL OK")


if __name__ == "__main__":
    main()

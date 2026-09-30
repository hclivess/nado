import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-csprng-")   # BEFORE any node import (CLAUDE.md rule 4)
"""THE SERVER KEY AND EVERY NONCE COME FROM THE OS CSPRNG (bandit B311 triage, 2026-09-30; audit M-12, 2026-07-02).

hashing.create_nonce() minted the config server_key (length 64 — the secret that authorizes /terminate and /force_sync
from anywhere) with `random.choice`, the Mersenne Twister, and the same process stream stamps a nonce into every
transaction the node signs, i.e. publishes its outputs on chain. MT state is recoverable from enough outputs and MT
runs backwards, so the key was derivable from public data. It now uses `secrets.choice`: identical alphabet, length
and distribution.
Pins: (1) seeding `random` does not make create_nonce reproducible; (2) format is unchanged (lowercase ASCII, the
requested length, default 8); (3) hashing.py does not import `random` at all and create_nonce draws from `secrets`;
(4) config.py still mints server_key through create_nonce(length=64).
Run: python3 tests/test_nonces_and_server_key_come_from_the_os_csprng.py
"""
import ast
import random
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import hashing                                                   # noqa: E402  (leaf module: json/secrets/hashlib)

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def t1_seeding_random_does_not_reproduce_a_key():
    random.seed(1234)
    a = hashing.create_nonce(length=64)
    random.seed(1234)
    b = hashing.create_nonce(length=64)
    check("seeding `random` does not reproduce a 64-char server key (not the Mersenne Twister)", a != b, (a, b))


def t2_format_is_unchanged():
    ks = [hashing.create_nonce(length=64) for _ in range(50)]
    ns = [hashing.create_nonce() for _ in range(50)]
    ok = (all(len(k) == 64 and set(k) <= set(string.ascii_lowercase) for k in ks)
          and all(len(n) == 8 and set(n) <= set(string.ascii_lowercase) for n in ns))
    check("format unchanged: lowercase ASCII, requested length (default 8)", ok, (ks[0], ns[0]))
    check("50 fresh 64-char keys are all distinct", len(set(ks)) == 50)


def t3_source_uses_secrets_not_random():
    tree = ast.parse(open(os.path.join(ROOT, "hashing.py"), encoding="utf-8").read())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    check("hashing.py does not import `random`", "random" not in imported, imported)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_nonce")
    attrs = {(getattr(c.func.value, "id", None), c.func.attr) for c in ast.walk(fn)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    check("create_nonce draws with secrets.choice", ("secrets", "choice") in attrs, attrs)


def t4_server_key_is_minted_by_create_nonce():
    src = open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
    check("config.py mints server_key via create_nonce(length=64)", '"server_key": create_nonce(length=64)' in src)


if __name__ == "__main__":
    t1_seeding_random_does_not_reproduce_a_key()
    t2_format_is_unchanged()
    t3_source_uses_secrets_not_random()
    t4_server_key_is_minted_by_create_nonce()
    print("ALL PASS" if not _fails else f"FAILED: {len(_fails)}: {_fails}")
    sys.exit(1 if _fails else 0)

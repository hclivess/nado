"""THE RUST CLIENT'S TRANSACTIONS MUST BE THE CHAIN'S TRANSACTIONS.

apps/nado-tpm-attest signs and submits real transactions from a user's PC. Two encodings decide whether
any of them is ever accepted, and both fail SILENTLY when wrong — the relay just refuses the
transaction, which presents to a user as "the network rejected me" rather than as an encoding bug:

  canonical_bytes  sorted keys, compact separators, ASCII-escaped
  txid             blake2b-256 over that, with public_key removed

So the chain, not the Rust crate, gets to say whether the client is right. This builds transactions
with the node's own code, runs them through the client binary, and checks that the txid matches
byte-for-byte and that the node's own verify() accepts the client's signature.

The signature is hedged ML-DSA, so it is deliberately NOT byte-reproducible — verify() is the only
meaningful check, which is also exactly how consensus treats it.

Run: python3 tests/test_tpm_client_tx.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-clienttx-"))
_fails = []
BIN = os.path.join(ROOT, "apps", "nado-tpm-attest", "target", "release", "nado-tpm-attest")


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    if not os.path.exists(BIN):
        print(f"SKIP  client binary not built ({BIN})")
        print("      cd apps/nado-tpm-attest && cargo build --release")
        return 0
    from hashing import canonical_bytes
    from ops.key_ops import generate_keys
    from ops.transaction_ops import create_txid
    from signatures import verify

    def run(seed, tx):
        out = subprocess.run([BIN, "selftest-tx"], input=json.dumps({"seed": seed, "tx": tx}),
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "selftest-tx failed")
        return json.loads(out.stdout)

    kd = generate_keys()
    seed = kd["private_key"]

    # The four shapes the client actually sends, plus an ordinary transfer as a control. Nested objects
    # and lists are in here on purpose: `data` is an object for three of the four messages, and a list
    # of hex strings inside it for the first, which is where a non-recursive key sort would diverge.
    cases = {
        "tpm_enrol": {"ek": ["30820" + "ab" * 8, "3082" + "cd" * 8], "pub": "00" * 40},
        "tpm_challenge": {"id": "a" * 32, "blob": "bb" * 70, "enc": "cc" * 256},
        "tpm_commit": {"id": "a" * 32, "commit": "d" * 64},
        "tpm_reveal": {"id": "a" * 32, "secret": "e" * 64, "seed": "f" * 64},
    }
    for recipient, data in cases.items():
        tx = {"sender": kd["address"], "recipient": recipient, "amount": 0, "data": data,
              "nonce": 123456789, "max_block": 45900, "min_block": 45850, "timestamp": 1757548800,
              "chain_id": "nado-betanet-7", "fee": 0, "public_key": kd["public_key"]}
        got = run(seed, tx)
        check(f"{recipient}: canonical encoding matches the chain",
              got["canonical"].encode() == canonical_bytes({k: v for k, v in tx.items()
                                                            if k != "public_key"}),
              got["canonical"][:120])
        check(f"{recipient}: txid matches the chain", got["txid"] == create_txid(tx),
              f'{got["txid"]} != {create_txid(tx)}')
        check(f"{recipient}: the node's verify() accepts the client's signature",
              verify(got["signature"], got["public_key"], bytes.fromhex(got["txid"])))
        check(f"{recipient}: the client derives the same public key", got["public_key"] == kd["public_key"])

    # A REGISTER CARRYING A DEVICE OBJECT — the shape that finally claims the identity, and the one with
    # the deepest nesting.
    tx = {"sender": kd["address"], "recipient": "register", "amount": 0, "data": "",
          "device": {"ek": "1" * 64, "id": "2" * 32, "certinfo": "3" * 200, "sig": "4" * 512},
          "nonce": 7, "max_block": 45900, "timestamp": 1757548800,
          "chain_id": "nado-betanet-7", "fee": 0, "public_key": kd["public_key"]}
    got = run(seed, tx)
    check("register: txid matches the chain", got["txid"] == create_txid(tx))
    check("register: the node's verify() accepts the client's signature",
          verify(got["signature"], got["public_key"], bytes.fromhex(got["txid"])))

    # NON-ASCII AND ESCAPES: never sent by this client, which is exactly why it is worth pinning — an
    # encoding only exercised by accident is one that diverges unnoticed.
    tx = {"sender": kd["address"], "recipient": "blob", "amount": 0,
          "data": {"note": "kučera \"quoted\" \\ back\nline\tтаб 😀"},
          "nonce": 1, "max_block": 45900, "timestamp": 1757548800,
          "chain_id": "nado-betanet-7", "fee": 0, "public_key": kd["public_key"]}
    got = run(seed, tx)
    check("non-ASCII and escapes encode identically", got["txid"] == create_txid(tx),
          f'{got["txid"]} != {create_txid(tx)}')

    # AND A SIGNATURE FROM A DIFFERENT KEY MUST NOT VERIFY, so the check above is not vacuous.
    other = generate_keys()
    check("a signature does not verify under another key",
          not verify(got["signature"], other["public_key"], bytes.fromhex(got["txid"])))

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())

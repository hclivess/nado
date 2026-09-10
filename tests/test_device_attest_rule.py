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
    import hashlib
    P.DEVICE_ATTEST_ROOT_FINGERPRINTS = frozenset(P.DEVICE_ATTEST_ROOT_FINGERPRINTS | {hashlib.sha256(root_der).hexdigest()})
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
    # per-device-class constraints: tpm needs the Windows Hello hardware AAGUID, the Microsoft root and a physical
    # manufacturer; packed needs the AAGUID's OWN root. Exercised with fake verdicts (the kernel is tested elsewhere).
    calls = {}
    def fake_verify(att_, cdj_, chal_, now_, rp_ids=None, roots=None):
        return dict(calls)
    real_verify = AN.verify
    AN.verify = fake_verify
    try:
        P.DEVICE_ATTEST_FIDO_AAGUID_ROOTS["cc" * 16] = frozenset({"r" * 64})
        base = {"ok": True, "aaguid": "08987058cadc4b81b6e130de50dcbe96", "root_sha256": next(iter(P.DEVICE_ATTEST_ROOT_FINGERPRINTS)), "tpm_manufacturer": "49465800"}
        calls.update(base, fmt="tpm"); assert TO.verify_register_device(tx, anchor_hash)["ok"]
        calls.update(base, fmt="tpm", tpm_manufacturer="4D534654")
        try: TO.verify_register_device(tx, anchor_hash); raise AssertionError("virtual TPM accepted")
        except AssertionError as e: assert "physical" in str(e), str(e)
        # THE PROOF DECIDES, NOT THE AAGUID, from DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT (2026-09-10). A real Intel-PTT PC
        # produced kernel-valid TPM statements under the "VBS" AAGUID and the old rule threw them away; below the gate
        # the historical refusal must still replay byte-identically.
        calls.update(base, fmt="tpm", aaguid="9ddd1817af5a4672a2b93e3dd95000a9")
        old = {**tx, "max_block": P.DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT - 1}
        try: TO.verify_register_device(old, anchor_hash); raise AssertionError("VBS AAGUID accepted below the gate")
        except AssertionError as e: assert "hardware authenticator" in str(e), str(e)
        assert max_block >= P.DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT, "fixture must land at or above the gate"
        assert TO.verify_register_device(tx, anchor_hash)["ok"], "a TPM-certified statement is judged by its proof at the gate"
        # ...but the proof itself still has to hold: a virtual TPM stays refused at any height
        calls.update(base, fmt="tpm", aaguid="9ddd1817af5a4672a2b93e3dd95000a9", tpm_manufacturer="4D534654")
        try: TO.verify_register_device(tx, anchor_hash); raise AssertionError("virtual TPM accepted above the gate")
        except AssertionError as e: assert "physical" in str(e), str(e)
        calls.update(base, fmt="packed", aaguid="cc" * 16, root_sha256="r" * 64); assert TO.verify_register_device(tx, anchor_hash)["ok"]
        calls.update(base, fmt="packed", aaguid="cc" * 16, root_sha256="s" * 64)
        try: TO.verify_register_device(tx, anchor_hash); raise AssertionError("foreign root accepted for this AAGUID")
        except AssertionError as e: assert "own root" in str(e), str(e)
        calls.update(base, fmt="packed", aaguid="dd" * 16, root_sha256="r" * 64)
        try: TO.verify_register_device(tx, anchor_hash); raise AssertionError("unknown AAGUID accepted")
        except AssertionError as e: assert "AAGUID" in str(e), str(e)
        calls.update(base, fmt="none")
        try: TO.verify_register_device(tx, anchor_hash); raise AssertionError("format none accepted")
        except AssertionError as e: assert "format" in str(e), str(e)
    finally:
        AN.verify = real_verify
        P.DEVICE_ATTEST_FIDO_AAGUID_ROOTS.pop("cc" * 16, None)
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    seg = src[src.index('elif recipient == "register":'):src.index('elif recipient == "msgkey":')]
    # gen 25: the register branch calls the rule UNCONDITIONALLY (no height gate survives the reroll — every register
    # tx from block 1 must attest), and the gate constant reads 1 for the wallet/status paths that ask.
    assert "verify_register_device(transaction, anchor)" in seg and "if DEVICE_ATTEST_HEIGHT and" not in seg
    assert "native/attest" in open(os.path.join(ROOT, "ops", "self_update.py")).read(), "fleet updater must build the crate"
    assert P.DEVICE_ATTEST_HEIGHT == 1
    print("ALL OK")


if __name__ == "__main__":
    main()

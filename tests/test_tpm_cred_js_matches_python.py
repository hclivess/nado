"""The wallet's TPM2_MakeCredential (static/tpmcred.js) is the node's (ops/tpm_aik.make_credential), byte for byte.

WHY THIS IS THE TEST THAT MATTERS. A bonded browser wallet drawn as a TPM-enrolment challenger seals its secret
with the JS port. On the reveal, EVERY NODE re-derives the credential blob from (secret, seed) with the Python and
compares it to the one the wallet published (ops/tpm_enrol.apply_reveal). One differing byte — a KDFa counter
width, a missing NUL in a label, a CFB feedback slip — and the reveal is refused at the very last step, after the
stranger's chip did everything right, and the enrolment dies. Nothing but a cross-language comparison sees that.

And the half consensus never compares — the RSA-OAEP-wrapped seed — still has to be something a REAL chip opens,
so the Python software chip (activate_credential, the test oracle of tests/test_tpm_aik.py) must recover the
secret from exactly what the wallet would send.

Pinned here, over several endorsement keys (RSA-2048, RSA-3072, and an EK lifted from a TPMT_PUBLIC the way a
chip-sourced key arrives, through tpm_aik.pub_area_spki) and several (name, secret, seed):
  - the JS blob equals make_credential(...)[0];
  - with the OAEP seed pinned, the JS wrapped seed equals tpm2b(rsa_oaep_encrypt(...)) — same hash, label, MGF;
  - a chip holding the EK recovers the secret from the JS (blob, enc) with its RANDOM OAEP seed;
  - the four-message state machine accepts the JS challenge and proves the enrolment on the reveal.
Run: python3 tests/test_tpm_cred_js_matches_python.py   (needs node and `cryptography`, the oracle)
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-tpmcredjs-")     # ASSIGN, never setdefault (CLAUDE.md rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import json
import struct
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


NODE_RUNNER = r"""
import { makeCredential, credentialBlob, hexToBytes as h, bytesToHex as x } from %s;
let raw = ""; process.stdin.on("data", (c) => raw += c); process.stdin.on("end", () => {
  const out = JSON.parse(raw).map((c) => {
    const pinned = makeCredential(h(c.spki), h(c.name), h(c.secret), h(c.seed), h(c.oaep));
    const random = makeCredential(h(c.spki), h(c.name), h(c.secret), h(c.seed));
    return { blob: x(pinned.blob), enc_pinned: x(pinned.enc), blob_random: x(random.blob), enc_random: x(random.enc),
             blob_only: x(credentialBlob(h(c.name), h(c.secret), h(c.seed))) };
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def ek_pub_area(n: int) -> bytes:
    """A TPMT_PUBLIC for an RSA endorsement key the way a chip reports it: AES-128-CFB symmetric, NULL scheme,
    exponent 0 (= 65537). pub_area_spki turns it into the SubjectPublicKeyInfo the node stores as `ekpub`."""
    mod = n.to_bytes((n.bit_length() + 7) // 8, "big")
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x000300B2) + b"\x00\x00"
    b += struct.pack(">HHH", 0x0006, 128, 0x0043)              # symmetric AES-128-CFB
    b += struct.pack(">H", 0x0010)                              # scheme NULL (a decryption key)
    b += struct.pack(">H", 2048) + struct.pack(">I", 0)         # keyBits, exponent 0 == 65537
    return b + struct.pack(">H", len(mod)) + mod


def main():
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes, serialization
    from ops import tpm_aik
    from ops import tpm_enrol as E

    def spki_of(k):
        return k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    def decryptor(k):
        return lambda ct: k.decrypt(ct, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(),
                                                     label=b"IDENTITY\x00"))

    k2048 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    k3072 = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    keys = [("RSA-2048 SPKI", k2048, spki_of(k2048)),
            ("RSA-3072 SPKI", k3072, spki_of(k3072)),
            ("EK from a TPMT_PUBLIC (pub_area_spki)", k2048,
             tpm_aik.pub_area_spki(ek_pub_area(k2048.public_key().public_numbers().n)))]
    check("the chip-shaped EK decodes to the same RSA key",
          tpm_aik.rsa_public_numbers_from_spki(keys[2][2]) == (k2048.public_key().public_numbers().n, 65537))

    cases = []
    for label, key, spki in keys:
        for secret_len in (32, 1, 16, 33, 64):                  # 32 is what the wallet sends; the rest cross block edges
            name = tpm_aik.aik_name(os.urandom(280 + secret_len))
            cases.append({"label": f"{label}, secret {secret_len} B", "key": key, "spki": spki.hex(),
                          "name": name.hex(), "secret": os.urandom(secret_len).hex(), "seed": os.urandom(32).hex(),
                          "oaep": os.urandom(32).hex()})
    # a non-standard Name length too: the blob binds whatever bytes the record's `name` holds
    cases.append(dict(cases[0], label="RSA-2048 SPKI, odd 7-byte name", name=os.urandom(7).hex()))

    runner = os.path.join(os.environ["HOME"], "runner.mjs")
    with open(runner, "w") as f:
        f.write(NODE_RUNNER % json.dumps("file://" + os.path.join(ROOT, "static", "tpmcred.js")))
    payload = json.dumps([{k: v for k, v in c.items() if k not in ("label", "key")} for c in cases])
    p = subprocess.run(["node", runner], input=payload, capture_output=True, text=True, timeout=120)
    check("the JS module runs under node", p.returncode == 0, p.stderr[-400:])
    if p.returncode != 0:
        return
    js = json.loads(p.stdout)

    for c, r in zip(cases, js):
        spki, name = bytes.fromhex(c["spki"]), bytes.fromhex(c["name"])
        secret, seed = bytes.fromhex(c["secret"]), bytes.fromhex(c["seed"])
        py_blob, _ = tpm_aik.make_credential(spki, name, secret, seed=seed)
        check(f"blob is byte-identical to Python ({c['label']})", r["blob"] == py_blob.hex(),
              f"js {r['blob'][:40]}… py {py_blob.hex()[:40]}…")
        check(f"the blob does not depend on the OAEP randomness ({c['label']})",
              r["blob_random"] == r["blob"] == r["blob_only"])
        n, e = tpm_aik.rsa_public_numbers_from_spki(spki)
        py_enc = tpm_aik.tpm2b(tpm_aik.rsa_oaep_encrypt(n, e, seed, b"IDENTITY\x00", rand=bytes.fromhex(c["oaep"])))
        check(f"pinned-OAEP wrapped seed is byte-identical to Python ({c['label']})", r["enc_pinned"] == py_enc.hex())
        try:
            got = tpm_aik.activate_credential(decryptor(c["key"]), bytes.fromhex(r["blob"]),
                                              bytes.fromhex(r["enc_random"]), name)
        except Exception as ex:
            got = f"{type(ex).__name__}: {ex}"
        check(f"a chip holding the EK opens what the wallet sends ({c['label']})", got == secret, str(got)[:80])
        check(f"every node's reveal replay accepts the wallet's blob ({c['label']})",
              tpm_aik.verify_credential_reveal(spki, name, secret, seed, bytes.fromhex(r["blob"]),
                                               tpm_aik.credential_commitment(secret)))

    # THE WHOLE STATE MACHINE, with the wallet as one of three drawn challengers: challenge with the JS blob, the
    # client commits to what its chip recovered (from the JS enc), the wallet reveals, and the enrolment is PROVEN.
    c = cases[0]
    spki, name_hex = bytes.fromhex(c["spki"]), c["name"]
    secrets = {"wallet": bytes.fromhex(c["secret"])}
    seeds = {"wallet": bytes.fromhex(c["seed"])}
    blobs = {"wallet": (bytes.fromhex(js[0]["blob"]), bytes.fromhex(js[0]["enc_random"]))}
    for other in ("nodeA", "nodeB"):
        secrets[other], seeds[other] = os.urandom(32), os.urandom(32)
        blobs[other] = tpm_aik.make_credential(spki, bytes.fromhex(name_hex), secrets[other], seed=seeds[other])
    rec = E.new_record("ab" * 32, spki, name_hex, b"\x00" * 8, "owner1", 100, ["wallet", "nodeA", "nodeB"])
    for ch in ("wallet", "nodeA", "nodeB"):
        rec = E.apply_challenge(rec, ch, blobs[ch][0], blobs[ch][1], 101)
    order = [r[0] for r in rec["blobs"]]
    recovered = b"".join(tpm_aik.activate_credential(decryptor(k2048), blobs[ch][0], blobs[ch][1],
                                                     bytes.fromhex(name_hex)) for ch in sorted(order))
    rec = E.apply_commit(rec, "owner1", tpm_aik.credential_commitment(recovered), 102)
    try:
        for ch in ("wallet", "nodeA", "nodeB"):
            rec = E.apply_reveal(rec, ch, secrets[ch], seeds[ch], 103)
        state = rec["state"]
    except AssertionError as ex:
        state = f"refused: {ex}"
    check("an enrolment with the wallet as a drawn challenger is PROVEN by consensus", state == E.STATE_PROVEN, state)


if __name__ == "__main__":
    main()
    if _fails:
        print(f"\n{len(_fails)} FAILED")
        sys.exit(1)
    print("\nall passed")

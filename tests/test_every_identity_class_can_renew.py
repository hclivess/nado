"""EVERY KIND OF IDENTITY CAN ALWAYS RENEW ITS PRESENCE LEASE — the wallet builds the renewal the node accepts.

Renewal broke for real users at least three times, and each fix came with a test of its own piece:
  * 78fe55ff  the renewal path never looked for the proof the enrolment helper had just dropped (Hello prompt instead);
  * d1af4cfb  the bundled /wallet_view read omitted `devbind`, so a permanently-bound identity got a Hello prompt;
  * 0f48a4e3  the wallet saved a credential id the chain never stored and signed every renewal with it, forever.
Every one of them passed its own tests. What failed was the JOURNEY: the wallet's choice of renewal path, for that class,
against what the node's validation accepts for that class. This test walks that journey for every class, through:
  * the REAL node: transaction_ops.validate_transaction (mempool height AND landing height), the native attestation
    kernel (statements and WebAuthn assertions), account_ops.reflect_transaction (apply + revert), the lease grant, and
    both presence readers (account_ops.get_open_registry, dividend_ops.present_at_epoch);
  * the REAL relay enrichment: nado._enrich_account, lifted out of nado.py (which cannot be imported — it starts a node)
    and run against this test's own database, so the wallet sees exactly the `devbind` the relay would send;
  * the REAL wallet: computeRegisterTx, bindIsPermanent, helperDrops, assertCredential, buildRegisterTx,
    storedCredentialId / rememberCredentialId / acceptedRegisterTx / healSignatureRenewal, maybeRenewLease,
    broadcastLeaseRenewal, leaseEpochsOf and the wallet's own blake2bHash, lifted out of static/interface.js and run in
    node with only the browser and the network stubbed (navigator.credentials, fetch, localStorage).

THE CLASSES (protocol.LEASE_EPOCHS_BY_CLASS, permanent_classes_at, LEASE_ASSERT_CLASSES):
  android-key  phone (Android 12+)      leased 360 epochs   renews with a FRESH statement (a prompt on the phone)
  tpm          Windows Hello PC         leased 1680         renews with a SIGNATURE by the credential the chain holds
                                                            (no attestation), falling back to a fresh statement
  ledger       Ledger (WebHID)          bound for life      renews with NO statement (account key only, no prompt)
  trezor       Trezor Safe (WebUSB)     bound for life      renews with NO statement
  ek           chip enrolled by the     bound for life      renews with NO statement; the node's own self-enrolled
               helper / node self-enrol                     identity (core_loop) renews with a fresh certify too
  vouched-for  any wallet another device attested for (4b1f70d7): renews through the voucher's dropped statement when
               the voucher's class is leased, statement-free when it is a hardware wallet.
Per class it pins: the wallet's automatic trigger falls inside the lease; at that height the wallet builds a renewal
(this exact path, prompt or no prompt) that the node accepts at mempool and at landing height; applying it extends the
lease by the class's own grant (absent at the old expiry before, present after); a LATE renewal (lease lapsed) is
accepted too and restores presence; a revert is exact; and the paths the node refuses for that class are the ones the
wallet never chose. Cross-cutting: a bundle that omits devbind never turns a bound-for-life identity into a prompt
(d1af4cfb); the helper's dropped proof is used before any prompt (78fe55ff); a renewal never signs with a credential the
chain does not hold, and a wallet that already does is not stuck — the node's refusal heals it, the lease loop retries
with a statement in the same call, and the credential that statement creates renews by signature next time (0f48a4e3);
every refusal of a signature renewal that comes from chain state is one the wallet's healer recognises; a node bound
for life renews itself (ops/node_attest.renew_without_statement through a mempool that runs the real validation).

WHAT IS NOT EXERCISED END TO END OFFLINE, and the strongest property pinned instead:
  * android-key: there is no way to mint an Android Key Attestation chain offline (it needs Google's hardware-backed
    root); the repo's one real phone statement (tests/vectors/device_attest_android_key.json) is used for every
    statement, so register_device_challenge is pinned to that vector's challenge FOR THE PHONE'S SENDER ONLY and the
    certificate clock to the vector's capture time. Everything else — kernel chain walk to the real pinned Google root,
    rp, binding key, one-device rule, apply, lease grant — is real. The wallet's prompt itself (create() on a phone) is
    stubbed; what is pinned is the challenge the wallet asks it to sign (sender/anchor/max_block) equals the node's.
  * tpm, ledger, trezor statements are SYNTHETIC devices (openssl / coincurve) under test roots added to the pinned set,
    verified by the real kernel and the real consensus per-format rules. The WebHID/WebUSB transport (hwattest.js) and
    navigator.credentials are stubbed: the stub returns exactly what the authenticator would sign for the credential
    the wallet ASKED for, and the challenge the wallet computed is compared to the node's.
  * ek needs swtpm (a software TPM, local socket only): with it, the helper path is real end to end (four-message
    enrolment against the chip, a fresh TPM2_Certify for the register); without it the ek class is seeded with
    apply_register and only its statement-free renewal is exercised — printed as a SKIP line, never silently.
  * the transaction signature: the wallet's draft (real buildRegisterTx; finalizeTransaction stubbed) is re-signed
    with the throwaway key by the node's own _seal, so field set and device passthrough are the wallet's, the ML-DSA
    signature is the node's (wallet<->node signing parity is tests/selftest_vectors_crosscheck.mjs's job).
  * the anchor block: the throwaway chain has no blocks, so block lookups return a deterministic hash per height —
    the same function on both sides (wallet rpcJSON and node get_block_hash_by_number / get_block_number).

Run: NADO_TESTNET=1 NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_every_identity_class_can_renew.py
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-renew-every-class-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _os.environ["HOME"], ignore_errors=True)
import ast
import base64
import hashlib
import json
import logging
import os
import socket
import struct
import subprocess
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)
HOME = os.environ["HOME"]
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{HOME}/nado/{d}", exist_ok=True)

import _harness                                                     # noqa: E402
import _attest_fixtures as FX                                       # noqa: E402
atexit.register(shutil.rmtree, FX.D, ignore_errors=True)           # the fixtures' openssl scratch dir
from genesis import create_indexers                                 # noqa: E402
create_indexers()
import protocol as P                                                # noqa: E402
from ops import kv_ops, attest_native as AN, block_ops              # noqa: E402
from ops import transaction_ops as TO                               # noqa: E402
from ops import dividend_ops                                        # noqa: E402
from ops.account_ops import create_account, get_account, get_open_registry, reflect_transaction, apply_register  # noqa: E402
from signatures import generate_keydict                             # noqa: E402

R = _harness.Report()
check = R.check
logger = logging.getLogger("renew-every-class"); logger.addHandler(logging.NullHandler())
L = P.EPOCH_LENGTH
RP = "get.nadochain.com"
NOW = int(time.time()) + 600            # the synthetic chains are minted now by openssl: judge them now


def b64(b):
    return base64.b64encode(b).decode()


def b64url(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


# ---- the anchor: one deterministic hash per height, the same function on the wallet side (JS harness below) ----------
def anchor(n):
    return hashlib.blake2b(b"nado-renew-anchor:%d" % int(n), digest_size=32).hexdigest()


block_ops.get_block_hash_by_number = lambda n: anchor(n)
TO.get_block_number = lambda n: {"block_number": int(n), "block_hash": anchor(n), "block_timestamp": NOW}

# ---- the phone: the repo's one real Android statement (see the docstring) ---------------------------------------------
VEC = json.load(open(os.path.join(TESTS, "vectors", "device_attest_android_key.json")))
VEC_CHAL = base64.urlsafe_b64decode(VEC["challenge_b64url"] + "=" * (-len(VEC["challenge_b64url"]) % 4))
PHONE_SENDERS = set()
_real_challenge = TO.register_device_challenge
TO.register_device_challenge = lambda s, a, m: VEC_CHAL if s in PHONE_SENDERS else _real_challenge(s, a, m)
# agreed time: this chain holds no duty clocks; the phone's certificate is judged at its capture time
TO._anchor_time = lambda tx, h: int(VEC["now_unix"]) if tx.get("sender") in PHONE_SENDERS else NOW


def challenge(sender, max_block):
    return TO.register_device_challenge(sender, anchor(max_block - P.POSW_ANCHOR_OFFSET), max_block)


# ---- synthetic devices under test roots, added to the PINNED set the consensus rule reads -------------------------------
FX.self_signed("renew_root", "/CN=Test TPM Root")
TPM_ROOT = FX.der("renew_root")
P.DEVICE_ATTEST_ROOT_FINGERPRINTS = frozenset(P.DEVICE_ATTEST_ROOT_FINGERPRINTS | {hashlib.sha256(TPM_ROOT).hexdigest()})
_EXTRA_ROOTS = [TPM_ROOT]
_real_pinned = AN.pinned_roots_der
AN.pinned_roots_der = lambda: _real_pinned() + list(_EXTRA_ROOTS)
AN._roots_blob = None


def _pin_reset():
    AN._roots_blob = None


class TpmPC:
    """A Windows Hello PC: one AIK certificate (the binding key) and any number of WebAuthn credentials made in it."""

    def __init__(self, name):
        self.n = name
        self.creds = {}                                   # cred name -> rawId bytes
        FX.key(f"{name}_aik")
        conf = os.path.join(FX.D, f"{name}_aik.ext")
        with open(conf, "w") as f:
            f.write("[ext]\nbasicConstraints=CA:FALSE\nextendedKeyUsage=2.23.133.8.3\n")
            f.write("subjectAltName=ASN1:SEQUENCE:san\n[san]\ndn=EXPLICIT:4,SEQUENCE:rdns\n[rdns]\nr1=SET:rdn1\nr2=SET:rdn2\nr3=SET:rdn3\n")
            f.write("[rdn1]\na=SEQUENCE:atv1\n[atv1]\noid=OID:2.23.133.2.1\nval=UTF8:id:49465800\n")
            f.write("[rdn2]\na=SEQUENCE:atv2\n[atv2]\noid=OID:2.23.133.2.2\nval=UTF8:TestTPM\n")
            f.write("[rdn3]\na=SEQUENCE:atv3\n[atv3]\noid=OID:2.23.133.2.3\nval=UTF8:id:00010000\n")
        FX.sh("openssl", "req", "-new", "-key", f"{name}_aik.key", "-subj", "/", "-out", f"{name}_aik.csr")
        FX.sh("openssl", "x509", "-req", "-in", f"{name}_aik.csr", "-CA", "renew_root.pem", "-CAkey", "renew_root.key",
              "-CAcreateserial", "-days", "365", "-sha256", "-extfile", conf, "-extensions", "ext", "-out", f"{name}_aik.pem")
        self.aik_der = FX.der(f"{name}_aik")

    def statement(self, cred, chal):
        """create(): a NEW credential `cred` attested by this PC's AIK over `chal`. -> device {att, cdj, rp}."""
        kn = f"{self.n}_{cred}"
        FX.key(kn)
        raw_id = hashlib.sha256(kn.encode()).digest()[:16]
        self.creds[cred] = raw_id
        x, y = FX.pub_xy(kn)
        ad = FX.auth_data(RP, x, y, aaguid=bytes.fromhex("08987058cadc4b81b6e130de50dcbe96"), cred=raw_id)
        cdj = FX.client_data(chal)
        pub_area = (struct.pack(">HHI", 0x0023, 0x000b, 0x00050072) + struct.pack(">H", 0) + struct.pack(">H", 0x0010)
                    + struct.pack(">H", 0x0010) + struct.pack(">H", 0x0003) + struct.pack(">H", 0x0010)
                    + struct.pack(">H", len(x)) + x + struct.pack(">H", len(y)) + y)
        name = struct.pack(">H", 0x000b) + hashlib.sha256(pub_area).digest()
        extra = hashlib.sha256(ad + hashlib.sha256(cdj).digest()).digest()
        cert_info = (struct.pack(">IH", 0xff544347, 0x8017) + struct.pack(">H", 0) + struct.pack(">H", len(extra)) + extra
                     + struct.pack(">QIIB", 1, 0, 0, 1) + struct.pack(">Q", 0) + struct.pack(">H", len(name)) + name
                     + struct.pack(">H", 0))
        sig = FX.sh("openssl", "dgst", "-sha256", "-sign", f"{self.n}_aik.key", inp=cert_info)
        st = [("ver", "2.0"), ("alg", -7), ("sig", sig), ("x5c", [self.aik_der, TPM_ROOT]), ("certInfo", cert_info),
              ("pubArea", pub_area)]
        att = (bytes([0xa3]) + FX.cbor("fmt") + FX.cbor("tpm") + FX.cbor("attStmt") + FX.cbor_map(st)
               + FX.cbor("authData") + FX.cbor(ad))
        return {"att": b64(att), "cdj": b64(cdj), "rp": RP}

    def raw_id_b64(self, cred):
        return b64(self.creds[cred])

    def assertion(self, cred, chal):
        """get(): `cred` signs authData || sha256(clientData) over `chal`. -> {ad, cdj, sig} (base64)."""
        ad = hashlib.sha256(RP.encode()).digest() + bytes([0x05]) + (7).to_bytes(4, "big")
        cd = json.dumps({"type": "webauthn.get", "challenge": b64url(chal), "origin": "https://" + RP}).encode()
        sig = FX.sh("openssl", "dgst", "-sha256", "-sign", f"{self.n}_{cred}.key", inp=ad + hashlib.sha256(cd).digest())
        return {"ad": b64(ad), "cdj": b64(cd), "sig": b64(sig)}


def hw_cdj(chal):
    return json.dumps({"type": "nado.hw", "challenge": b64url(chal), "origin": "https://" + RP}).encode()


class Trezor:
    def __init__(self, name):
        n = self.n = name
        for k in ("root", "ca", "dev"):
            FX.sh("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", f"{n}_{k}.key")
        FX.sh("openssl", "req", "-x509", "-new", "-key", f"{n}_root.key", "-sha256", "-days", "3650", "-subj", "/CN=Trezor Root Test", "-out", f"{n}_root.pem")
        open(os.path.join(FX.D, f"{n}_ca.ext"), "w").write("basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign\n")
        FX.sh("openssl", "req", "-new", "-key", f"{n}_ca.key", "-subj", "/CN=Trezor CA Test", "-out", f"{n}_ca.csr")
        FX.sh("openssl", "x509", "-req", "-in", f"{n}_ca.csr", "-CA", f"{n}_root.pem", "-CAkey", f"{n}_root.key", "-CAcreateserial",
              "-sha256", "-days", "3650", "-extfile", f"{n}_ca.ext", "-out", f"{n}_ca.pem")
        open(os.path.join(FX.D, f"{n}_dev.ext"), "w").write("basicConstraints=critical,CA:FALSE\n")
        FX.sh("openssl", "req", "-new", "-key", f"{n}_dev.key", "-subj", "/CN=T3T1 ABCDEF123456", "-out", f"{n}_dev.csr")
        FX.sh("openssl", "x509", "-req", "-in", f"{n}_dev.csr", "-CA", f"{n}_ca.pem", "-CAkey", f"{n}_ca.key", "-CAcreateserial",
              "-sha256", "-days", "3650", "-extfile", f"{n}_dev.ext", "-out", f"{n}_dev.pem")
        root_point = FX.sh("openssl", "ec", "-in", f"{n}_root.key", "-pubout", "-outform", "DER")[-65:]
        P.DEVICE_ATTEST_TREZOR_ROOTS = {**P.DEVICE_ATTEST_TREZOR_ROOTS,
                                        "T3T1": tuple(P.DEVICE_ATTEST_TREZOR_ROOTS.get("T3T1", ())) + (root_point.hex(),)}
        _pin_reset()
        self.x5c = [FX.sh("openssl", "x509", "-in", f"{n}_{c}.pem", "-outform", "DER") for c in ("dev", "ca")]

    def statement(self, chal):
        msg = bytes([19]) + b"AuthenticateDevice:" + bytes([len(chal)]) + chal
        sig = FX.sh("openssl", "dgst", "-sha256", "-sign", f"{self.n}_dev.key", inp=msg)
        att = FX.cbor({"fmt": "trezor", "attStmt": {"x5c": self.x5c, "sig": sig}, "authData": b""})
        return {"att": b64(att), "cdj": b64(hw_cdj(chal)), "rp": RP}


class Ledger:
    def __init__(self):
        from coincurve import PrivateKey
        self.issuer, self.device = PrivateKey(), PrivateKey()
        P.DEVICE_ATTEST_LEDGER_ISSUER_KEYS = tuple(P.DEVICE_ATTEST_LEDGER_ISSUER_KEYS) + (
            self.issuer.public_key.format(compressed=False).hex(),)
        _pin_reset()

    def statement(self, chal):
        from coincurve import PrivateKey
        eph = PrivateKey()
        dev_pub, eph_pub = self.device.public_key.format(compressed=False), eph.public_key.format(compressed=False)
        hdr = bytes([0x01])
        sig0 = self.issuer.sign(bytes([0x02]) + hdr + dev_pub)
        cert0 = bytes([len(hdr)]) + hdr + bytes([65]) + dev_pub + bytes([len(sig0)]) + sig0
        dnonce = os.urandom(8)
        sig1 = self.device.sign(bytes([0x12]) + dnonce + chal[:8] + eph_pub)
        cert1 = bytes([0]) + bytes([65]) + eph_pub + bytes([len(sig1)]) + sig1
        st = {"target_id": bytes.fromhex("31100004"), "batch": bytes.fromhex("00000001"), "host_nonce": chal[:8],
              "device_nonce": dnonce, "cert0": cert0, "cert1": cert1}
        att = FX.cbor({"fmt": "ledger", "attStmt": st, "authData": b""})
        return {"att": b64(att), "cdj": b64(hw_cdj(chal)), "rp": RP}


def phone_statement():
    return {"att": VEC["att"], "cdj": VEC["cdj"], "rp": VEC["rp"]}


# ---- the node side --------------------------------------------------------------------------------------------------
def ident():
    kd = generate_keydict()
    create_account(kd["address"], balance=0)
    return kd


def sealed(kd, draft_or_mb, device=None):
    """A signed register: from the wallet's draft (re-sealed with the throwaway key), or built by the node's builder."""
    if isinstance(draft_or_mb, dict):
        tx = {k: v for k, v in draft_or_mb.items() if k not in ("txid", "signature")}
        assert tx["sender"] == kd["address"] and tx["public_key"] == kd["public_key"], "the draft is this wallet's"
        TO._seal(tx, kd)
        return tx
    return TO.construct_register_tx(kd, draft_or_mb, device=device)


def verdict(tx, h):
    """None when validate_transaction accepts at height h, else the refusal."""
    try:
        TO.validate_transaction(tx, logger, block_height=h)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def admit_and_land(tx):
    """The mempool judges a register at the tip it is submitted on (target - REG_TARGET_MARGIN); the block at max_block."""
    mb = int(tx["max_block"])
    return verdict(tx, mb - WALLET_MARGIN) or verdict(tx, mb)


def land(tx, revert=False):
    reflect_transaction(tx, logger, block_height=int(tx["max_block"]), revert=revert)


def present(addr, e):
    return addr in get_open_registry(e) and addr in dividend_ops.present_at_epoch(e)


def absent(addr, e):
    return addr not in get_open_registry(e) and addr not in dividend_ops.present_at_epoch(e)


# nado._enrich_account, the ONE function behind /get_account and /wallet_view, run against this database
_nado_src = open(os.path.join(ROOT, "nado.py")).read()
_fn = next(n for n in ast.parse(_nado_src).body if isinstance(n, ast.FunctionDef) and n.name == "_enrich_account")
_ENRICH_NS = {"memserver": types.SimpleNamespace(latest_block={"block_number": 0}),
              "LEASE_ASSERT_CLASSES": P.LEASE_ASSERT_CLASSES}
exec(compile(ast.Module(body=[_fn], type_ignores=[]), "nado.py:_enrich_account", "exec"), _ENRICH_NS)


def relay_account(addr, tip):
    _ENRICH_NS["memserver"].latest_block = {"block_number": int(tip)}
    acc = dict(get_account(addr, create_on_error=False) or {})
    return json.loads(json.dumps(_ENRICH_NS["_enrich_account"](addr, acc)))


# ---- the wallet side: real functions out of static/interface.js, run in node ----------------------------------------
JS = r"""
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
const input = JSON.parse(readFileSync(0, "utf8"));
const src = readFileSync(join(input.root, "static", "interface.js"), "utf8");
const { blake2b, bytesToHex } = await import(pathToFileURL(join(input.root, "static", "vendor", "nado-crypto.js")).href);
function grab(name) {
  let at = src.indexOf("\nasync function " + name + "(");
  if (at < 0) at = src.indexOf("\nfunction " + name + "(");
  if (at < 0) throw new Error("interface.js has no function " + name);
  let i = src.indexOf("{", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(at + 1, i + 1);
  }
  throw new Error("unbalanced " + name);
}
const anchorHex = (n) => bytesToHex(blake2b(new TextEncoder().encode("nado-renew-anchor:" + n), { dkLen: 32 }));
const fromB64 = (s) => Uint8Array.from(Buffer.from(s, "base64")).buffer;
const storage = new Map(Object.entries(input.storage || {}));
const logs = [];
const state = Object.assign({ wallet: { address: input.sender, publicKey: input.public_key }, mining: true,
                              registering: false, regSubmitted: null }, input.state || {});
let cur = null;                      // the op being run: its accounts, drops, prompt, assertions
const env = {
  state, CHAIN_ID: input.chain_id, POSW_ANCHOR_OFFSET: input.anchor_offset, EPOCH_LENGTH: input.epoch_length,
  POSW_LEASE_EPOCHS: input.posw_lease, LEASE_BY_CLASS: input.lease_by_class, blake2b, bytesToHex,
  log: (lvl, m) => logs.push([lvl, m]),
  i18: (k, en) => k + "|" + en,
  nowSeconds: () => 1_800_000_000,
  randNonce: () => "abcdefgh",
  registerData: () => "",
  finalizeTransaction: (body, _w, fee) => ({ ...body, fee }),
  localStorage: { getItem: (k) => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v)),
                  removeItem: (k) => storage.delete(k) },
  btoa: (s) => Buffer.from(s, "binary").toString("base64"),
  atob: (s) => Buffer.from(s, "base64").toString("binary"),
  RelayUnreachable: class extends Error {},
  readDeviceStatus: () => null, deviceHint: () => "",
  relayBase: () => "https://relay.invalid",
  getAccount: async () => (cur.accs.length > 1 ? cur.accs.shift() : cur.accs[0]),
  rpcJSON: async (url) => ({ data: { block_hash: anchorHex(Number(url.split("number=")[1])) } }),
  fetch: async (url) => ({ json: async () => (String(url).includes("/node_attest_pickup")
    ? { tip: cur.tip, drops: cur.drops || [] } : {}) }),
  attestDevice: async (sender, anchorHash, maxBlock) => {        // the device prompt (create() / hardware ceremony)
    cur.prompt = { sender, anchorHash, maxBlock };
    const p = cur.promptDevice;
    if (!p) return null;
    if (p.rawId) W.rememberCredentialId(sender, fromB64(p.rawId), p.device.att);   // as the real attestDevice does
    return p.device;
  },
  window: { PublicKeyCredential: function () {} },
  location: { hostname: "get.nadochain.com" },
  navigator: { credentials: { get: async ({ publicKey }) => {      // the authenticator: signs only for a credential it holds
    const id = Buffer.from(publicKey.allowCredentials[0].id).toString("base64");
    cur.get = { credId: id, chalHex: Buffer.from(publicKey.challenge).toString("hex"), rpId: publicKey.rpId };
    const a = (cur.assertions || {})[id];
    if (!a) throw new Error("NotAllowedError: no such credential on this device");
    return { response: { authenticatorData: fromB64(a.ad), clientDataJSON: fromB64(a.cdj), signature: fromB64(a.sig) } };
  } } },
  getLatestBlock: async () => ({ block_number: cur.tip }),
  registrationDifficulty: async () => ({ reqT: 0 }),
  submitTransaction: async (tx) => {                              // the relay: the verdict the REAL node gave this shape
    const k = kindOf(tx);
    cur.submitted.push(k);
    const v = (cur.verdicts || {})[k] || { result: false, message: "unexpected renewal shape " + k };
    return { data: v };
  },
};
function kindOf(tx) {
  if (!tx || !tx.device) return "none";
  if (tx.device.sig && tx.device.ad) return "assert";
  return cur && cur.prompt ? "statement" : "drop";
}
const REG_TARGET_MARGIN = Number(src.match(/const REG_TARGET_MARGIN = (\d+);/)[1]);
const PRE = "const {state, CHAIN_ID, POSW_ANCHOR_OFFSET, EPOCH_LENGTH, LEASE_BY_CLASS, blake2b, bytesToHex, log, i18, " +
  "nowSeconds, randNonce, registerData, finalizeTransaction, localStorage, btoa, atob, RelayUnreachable, readDeviceStatus, " +
  "deviceHint, relayBase, getAccount, rpcJSON, fetch, attestDevice, window, location, navigator, getLatestBlock, " +
  "registrationDifficulty, submitTransaction} = env;\n let POSW_LEASE_EPOCHS = env.POSW_LEASE_EPOCHS;\n" +
  "const REG_TARGET_MARGIN = " + REG_TARGET_MARGIN + ";\nconst RENEW_RETRY_MS = 5 * 60 * 1000;\n" +
  "let _pendingCred = null, _renewingLease = false, _renewSubmitted = null, _renewFailedAt = 0;\n" +
  "const _enc = new TextEncoder();\n";
const WALLET = ["jsonEscapeAscii", "canonicalize", "canonicalBytes", "blake2bHash", "leaseEpochsOf", "bindIsPermanent",
  "helperDrops", "computeRegisterTx", "storedCredentialId", "rememberCredentialId", "acceptedRegisterTx",
  "healSignatureRenewal", "assertCredential", "buildRegisterTx", "maybeRenewLease", "broadcastLeaseRenewal"];
const W = new Function("env", PRE + WALLET.map(grab).join("\n") +
  "\nreturn {" + WALLET.join(", ") + ", reset: () => { _renewingLease = false; _renewSubmitted = null; _renewFailedAt = 0; }};")(env);
// the TRIGGER probe: the real maybeRenewLease, with the broadcast replaced by a recorder
let fired = null;
const T = new Function("env", "rec", PRE + ["leaseEpochsOf", "maybeRenewLease"].map(grab).join("\n") +
  "\nasync function broadcastLeaseRenewal(r) { rec(r); return true; }\nreturn { maybeRenewLease };")(env, (r) => { fired = r; });

const results = [];
for (const op of input.ops) {
  cur = { accs: op.accs || [{}], tip: op.tip, drops: op.drops, promptDevice: op.prompt, assertions: op.assertions,
          verdicts: op.verdicts, submitted: [], prompt: null, get: null };
  const out = { op: op.op };
  try {
    if (op.op === "compute") {
      const tx = await W.computeRegisterTx(op.target, null, 0);
      Object.assign(out, { kind: kindOf(tx), tx, prompt: cur.prompt, get: cur.get });
    } else if (op.op === "remember") {
      W.rememberCredentialId(input.sender, fromB64(op.rawId), op.att);
    } else if (op.op === "accepted") {
      W.acceptedRegisterTx(op.tx);
    } else if (op.op === "heal") {
      out.healed = W.healSignatureRenewal(op.tx, op.message);
    } else if (op.op === "trigger") {
      fired = null;
      for (let e = op.from; e <= op.to && fired === null; e++) {
        state.latest = e * input.epoch_length;
        await T.maybeRenewLease(op.accs[0]);
        if (fired !== null) out.epoch = Math.floor((state.latest + 8) / input.epoch_length);
      }
    } else if (op.op === "loop") {
      W.reset();
      out.ok = await W.broadcastLeaseRenewal(op.reg_epoch);
      Object.assign(out, { submitted: cur.submitted, prompt: cur.prompt, get: cur.get });
    }
  } catch (e) { out.error = String(e && e.message || e); out.prompt = cur.prompt; }   // a prompt that opened, then threw
  out.stored = storage.get("nado_cred_" + input.sender) || null;
  results.push(out);
}
process.stdout.write(JSON.stringify({ results, storage: Object.fromEntries(storage), devbind: state.devbind || null, logs }));
"""
JS_PATH = os.path.join(HOME, "renew_wallet_harness.mjs")
open(JS_PATH, "w").write(JS)
WALLET_MARGIN = None                 # REG_TARGET_MARGIN, read from interface.js below


class Wallet:
    """One browser profile: its localStorage and its last-known devbind survive between calls, like a real tab."""

    def __init__(self, kd, attest_via=None):
        self.kd, self.storage, self.state = kd, {}, {}
        if attest_via:
            self.state["attestVia"] = attest_via

    def run(self, *ops):
        inp = {"root": ROOT, "sender": self.kd["address"], "public_key": self.kd["public_key"], "chain_id": P.CHAIN_ID,
               "anchor_offset": P.POSW_ANCHOR_OFFSET, "epoch_length": L, "posw_lease": P.POSW_LEASE_EPOCHS,
               "lease_by_class": dict(P.LEASE_EPOCHS_BY_CLASS), "storage": self.storage, "state": self.state,
               "ops": list(ops)}
        p = subprocess.run(["node", JS_PATH], input=json.dumps(inp), capture_output=True, text=True, timeout=120)
        if p.returncode:
            raise RuntimeError("wallet harness failed: " + p.stderr[-2000:])
        out = json.loads(p.stdout)
        self.storage = out["storage"]
        self.state["devbind"] = out["devbind"]
        return out["results"] if len(ops) > 1 else out["results"][0]


js_src = open(os.path.join(ROOT, "static", "interface.js")).read()
import re                                                           # noqa: E402
WALLET_MARGIN = int(re.search(r"const REG_TARGET_MARGIN = (\d+);", js_src).group(1))


# ---- the walk, per class ----------------------------------------------------------------------------------------------
E0 = 1000                            # the binding statement's epoch (every class)


def walk(label, kd, cls, perm, first_device, wallet, renew_prompt=None, assertions=None, expect_kind=None,
         expect_prompt=None, drops=None, late_expect_kind=None):
    """Bind at E0, then let the wallet renew at its own trigger and again after a lapse. `first_device(mb)` is the
    statement that binds; `renew_prompt(mb)` -> (prompt dict for the wallet stub, or None); `assertions(mb)` -> the
    authenticator's answers by credential id; `drops(mb, tip)` -> the relay's drop store for this address."""
    addr = kd["address"]
    lease = P.LEASE_EPOCHS_BY_CLASS[cls]
    h0 = E0 * L + WALLET_MARGIN
    tx0 = sealed(kd, h0, first_device(h0))
    v = admit_and_land(tx0)
    check(f"{label}: the binding statement is accepted (mempool and landing height)", v is None, v)
    if v:
        return
    land(tx0)
    if wallet.state.get("_remember_first"):
        cred = wallet.state.pop("_remember_first")
        wallet.run({"op": "remember", "rawId": cred, "att": tx0["device"]["att"]}, {"op": "accepted", "tx": tx0})
    acc_row = get_account(addr) or {}
    check(f"{label}: the chain stamps the device class ({cls}) and its binding mode",
          str(acc_row.get("devkey", "")).startswith(cls + ":")
          and (kv_ops.devbind_get(acc_row["devkey"]) or (None, None, None))[2] == ("perm" if perm else "lease"),
          (acc_row.get("devkey"), kv_ops.devbind_get(acc_row.get("devkey") or "")))
    check(f"{label}: the statement grants this class's own lease ({lease} epochs)", kv_ops.lease_of(addr, E0) == lease,
          kv_ops.lease_of(addr, E0))
    check(f"{label}: present inside the lease, absent once it runs out", present(addr, E0 + lease - 1) and absent(addr, E0 + lease))

    # 1. WHEN: the wallet's own automatic trigger, on what the relay sends
    acc = relay_account(addr, E0 * L)
    db = acc.get("devbind") or {}
    check(f"{label}: the relay reports mode/class/lease the chain holds",
          db.get("mode") == ("perm" if perm else "lease") and db.get("cls") == cls and db.get("live") == perm
          and db.get("lease_epochs") == lease and db.get("assert_ok") == (cls in P.LEASE_ASSERT_CLASSES), db)
    trig = wallet.run({"op": "trigger", "accs": [acc], "from": E0, "to": E0 + lease + 2}).get("epoch")
    check(f"{label}: the wallet's automatic renewal fires inside the lease (epoch {trig}, lease {E0}..{E0 + lease})",
          isinstance(trig, int) and E0 < trig and trig + 1 < E0 + lease and (trig * L + WALLET_MARGIN) // L < E0 + lease, trig)
    if not isinstance(trig, int):
        return

    def renew_at(e, what):
        tip = e * L
        mb = tip + WALLET_MARGIN
        acc_now = relay_account(addr, tip)
        op = {"op": "compute", "target": mb, "tip": tip, "accs": [acc_now]}
        if renew_prompt:
            op["prompt"] = renew_prompt(mb)
        if assertions:
            op["assertions"] = assertions(mb)
        if drops:
            op["drops"] = drops(mb, tip)
        r = wallet.run(op)
        if r.get("error"):
            check(f"{label}: {what}: the wallet builds a renewal", False, r["error"])
            return None, r
        k = r["kind"]
        if expect_kind:
            exp = expect_kind if what == "on time" or not late_expect_kind else late_expect_kind
            check(f"{label}: {what}: the wallet takes the {exp} path", k == exp, k)
        if expect_prompt is not None:
            check(f"{label}: {what}: " + ("a device prompt opens (this class renews with the device)" if expect_prompt
                                         else "NO device prompt opens"), bool(r["prompt"]) == expect_prompt, r["prompt"])
        if r.get("get"):
            check(f"{label}: {what}: the credential is asked to sign the node's own challenge",
                  r["get"]["chalHex"] == _real_challenge(addr, anchor(mb - P.POSW_ANCHOR_OFFSET), mb).hex(), r["get"])
        if r.get("prompt"):
            check(f"{label}: {what}: the prompt is for this sender, the node's anchor and the landing block",
                  r["prompt"] == {"sender": addr, "anchorHash": anchor(mb - P.POSW_ANCHOR_OFFSET), "maxBlock": mb}, r["prompt"])
        tx = sealed(kd, r["tx"])
        v = admit_and_land(tx)
        check(f"{label}: {what}: the node accepts the renewal the wallet built ({k})", v is None, v)
        return (tx if v is None else None), r

    # 2. ON TIME
    tx1, r1 = renew_at(trig, "on time")
    if not tx1:
        return
    land(tx1)
    if r1.get("prompt") and wallet.state.get("_cred_wallet"):
        wallet.run({"op": "accepted", "tx": tx1})
    e1 = int(tx1["max_block"]) // L
    check(f"{label}: applying it records the recert and grants the class's lease again",
          kv_ops.recert_latest(addr) == e1 and kv_ops.lease_of(addr, e1) == lease, (kv_ops.recert_latest(addr), kv_ops.lease_of(addr, e1)))
    check(f"{label}: the lease is EXTENDED: present at the old expiry, absent only after the new one",
          present(addr, E0 + lease) and present(addr, e1 + lease - 1) and absent(addr, e1 + lease))

    # 3. LATE: the lease lapsed (wallet closed for a while) — renewing must still work and restore presence
    e2 = e1 + lease + 7
    check(f"{label}: (late) the lease has lapsed", absent(addr, e2))
    tx2, _r2 = renew_at(e2, "after the lease lapsed")
    if not tx2:
        return
    land(tx2)
    check(f"{label}: a late renewal restores presence for a fresh lease", present(addr, e2) and present(addr, e2 + lease - 1))
    land(tx2, revert=True)
    check(f"{label}: reverting the renewal is exact (recert, grant, presence)",
          kv_ops.recert_latest(addr) == e1 and kv_ops.lease_grant_get(addr, e2) is None and absent(addr, e2))
    land(tx2)

    # 4. THE PATHS THIS CLASS MUST NOT TAKE are refused by the node (so the wallet's choice above is the one that works)
    e3 = e2 + 3
    mb = e3 * L + WALLET_MARGIN
    if not perm:
        v = admit_and_land(sealed(kd, mb, None))
        check(f"{label}: a statement-free renewal is refused for a leased class", v is not None and "Missing device attestation" in v, v)
    if cls not in P.LEASE_ASSERT_CLASSES:
        fake = {"ad": b64(hashlib.sha256(RP.encode()).digest() + b"\x05" + bytes(4)), "cdj": b64(b"{}"), "sig": b64(b"\x30\x00"), "rp": RP}
        v = admit_and_land(sealed(kd, mb, fake))
        check(f"{label}: a signature renewal is refused for a {cls} binding", v is not None and "signature renewal" in v, v)
    return e2


# ---- android-key: a phone ----------------------------------------------------------------------------------------------
def t_phone():
    kd = ident()
    PHONE_SENDERS.add(kd["address"])
    w = Wallet(kd)
    w.storage["nado_cred_" + kd["address"]] = b64(b"phone-credential")      # a phone's browser keeps an id too
    walk("android-key (phone)", kd, "android-key", False, lambda mb: phone_statement(), w,
         renew_prompt=lambda mb: {"device": phone_statement()}, expect_kind="statement", expect_prompt=True)


# ---- tpm: Windows Hello --------------------------------------------------------------------------------------------------
def t_windows_hello():
    pc = TpmPC("hello")
    kd = ident()
    addr = kd["address"]
    w = Wallet(kd)
    dev0 = pc.statement("Y", challenge(addr, E0 * L + WALLET_MARGIN))
    w.state["_remember_first"] = pc.raw_id_b64("Y")
    w.state["_cred_wallet"] = True
    n = {"i": 0}

    def prompt(mb):                                     # a create() makes a NEW credential every time
        n["i"] += 1
        c = f"Z{n['i']}"
        d = pc.statement(c, challenge(addr, mb))
        return {"device": d, "rawId": pc.raw_id_b64(c)}

    def answers(mb):                                    # the PC answers for every credential it holds
        return {pc.raw_id_b64(c): pc.assertion(c, challenge(addr, mb)) for c in pc.creds}

    e2 = walk("tpm (Windows Hello)", kd, "tpm", False, lambda mb: dev0, w, renew_prompt=prompt, assertions=answers,
              expect_kind="assert", expect_prompt=False)
    if e2 is None:
        return
    check("tpm (Windows Hello): the browser still holds the credential the chain holds",
          w.storage.get("nado_cred_" + addr) == pc.raw_id_b64("Y"), w.storage)

    # 0f48a4e3: a create() whose statement never landed must not become the credential renewals sign with
    e = e2 + 200
    tip, mb = e * L, e * L + WALLET_MARGIN
    stray = pc.statement("X", challenge(addr, mb))      # made, then refused by the pre-flight / never landed
    w.run({"op": "remember", "rawId": pc.raw_id_b64("X"), "att": stray["att"]})
    r = w.run({"op": "compute", "target": mb, "tip": tip, "accs": [relay_account(addr, tip)], "assertions": answers(mb)})
    check("a credential whose statement never landed is NOT what the renewal signs with (0f48a4e3)",
          r.get("get", {}) and r["get"]["credId"] == pc.raw_id_b64("Y"), r.get("get"))
    tx = sealed(kd, r["tx"]) if r.get("tx") else None
    v = admit_and_land(tx) if tx else "no tx"
    check("...and the signature renewal it built is accepted", v is None, v)
    land(tx)

    # A WALLET THAT ALREADY HOLDS A CREDENTIAL THE CHAIN DOES NOT (the bug's victims, or a statement accepted by a relay
    # but never incorporated) is not stuck: the node refuses, the healer recognises the refusal, the lease loop retries
    # with a statement in the SAME call, and that statement's credential renews by signature next time.
    w.storage["nado_cred_" + addr] = pc.raw_id_b64("X")
    e = e + 200
    tip, mb = e * L, e * L + WALLET_MARGIN
    acc = relay_account(addr, tip)
    bad = w.run({"op": "compute", "target": mb, "tip": tip, "accs": [acc], "assertions": answers(mb)})
    bad_tx = sealed(kd, bad["tx"])
    msg = admit_and_land(bad_tx)
    check("the node refuses a signature by a credential it does not hold", bad["kind"] == "assert" and msg is not None, (bad["kind"], msg))
    pr = prompt(mb)
    stmt_tx = sealed(kd, {**bad["tx"], "device": pr["device"]})
    sv = admit_and_land(stmt_tx)
    check("...the statement fallback for the same block is accepted", sv is None, sv)
    loop = w.run({"op": "loop", "reg_epoch": kv_ops.recert_latest(addr), "tip": tip, "accs": [acc],
                  "assertions": answers(mb), "prompt": pr,
                  "verdicts": {"assert": {"result": False, "message": "Could not merge remote transaction: " + (msg or "").split(": ", 1)[-1]},
                               "statement": {"result": True}}})
    check("the lease loop recovers in ONE call: refused signature -> heal -> statement accepted",
          loop.get("ok") is True and loop.get("submitted") == ["assert", "statement"], loop)
    check("...and the browser now holds the credential of the statement that landed",
          loop.get("stored") == pr["rawId"], loop.get("stored"))
    land(stmt_tx)
    e = e + 200
    tip, mb = e * L, e * L + WALLET_MARGIN
    r = w.run({"op": "compute", "target": mb, "tip": tip, "accs": [relay_account(addr, tip)], "assertions": answers(mb)})
    v = admit_and_land(sealed(kd, r["tx"])) if r.get("tx") else r.get("error")
    check("...and the NEXT renewal is a signature by that credential, accepted (no prompt)",
          r.get("kind") == "assert" and not r.get("prompt") and v is None, (r.get("kind"), v))

    # every refusal of a signature renewal that comes from CHAIN STATE is one the wallet's healer recognises, or the
    # wallet would retry the same refused signature until the lease lapsed
    e = e + 200
    mb = e * L + WALLET_MARGIN
    good = pc.assertion("Y", challenge(addr, mb))
    msgs = {}
    kd_new = ident()                                    # never made a statement: no credential on chain
    msgs["no credential on chain"] = admit_and_land(sealed(kd_new, mb, {**good, "rp": RP}))
    msgs["a signature that does not verify"] = admit_and_land(sealed(kd, mb, {**pc.assertion("X", challenge(addr, mb)), "rp": RP}))
    other = ident()                                     # the same PC now vouches for another account
    mv = sealed(other, (e - 1) * L + 5, pc.statement("W", challenge(other["address"], (e - 1) * L + 5)))
    v = admit_and_land(mv)
    check("(setup) the Windows Hello PC may move to another account", v is None, v)
    land(mv)
    msgs["the device moved to another account"] = admit_and_land(sealed(kd, mb, {**pc.assertion(sorted(pc.creds)[-1], challenge(addr, mb)), "rp": RP}))
    for why, m in msgs.items():
        healed = w.run({"op": "heal", "tx": {"sender": addr, "device": {"ad": "a", "cdj": "c", "sig": "s", "rp": RP}},
                        "message": "Could not merge remote transaction: " + (m or "")}).get("healed")
        check(f"a signature renewal refused for '{why}' is refused by the node AND healed by the wallet", m is not None and healed, (m, healed))


# ---- ledger / trezor: bound for life -----------------------------------------------------------------------------------
def t_hardware_wallets():
    for label, cls, dev in (("ledger", "ledger", Ledger()), ("trezor", "trezor", Trezor("renewtz"))):
        kd = ident()
        w = Wallet(kd, attest_via=cls)
        walk(f"{label} (bound for life)", kd, cls, True, lambda mb, d=dev, a=kd["address"]: d.statement(challenge(a, mb)), w,
             renew_prompt=lambda mb: None, expect_kind="none", expect_prompt=False)
        if label == "ledger":
            LEDGER_KD.append(kd)


LEDGER_KD = []


def t_bundle_without_devbind():
    """d1af4cfb: /wallet_view omitted devbind; missing is not unbound — a known permanent binding stays permanent."""
    kd = LEDGER_KD[0] if LEDGER_KD else None
    if not kd:
        check("bundle without devbind: a ledger identity exists", False)
        return
    addr = kd["address"]
    w = Wallet(kd, attest_via="ledger")
    e = kv_ops.recert_latest(addr) + 2
    tip, mb = e * L, e * L + WALLET_MARGIN
    full = relay_account(addr, tip)
    bundle = {k: v for k, v in full.items() if k != "devbind"}
    rs = w.run({"op": "compute", "target": mb, "tip": tip, "accs": [full], "prompt": None},
               {"op": "compute", "target": mb, "tip": tip, "accs": [bundle], "prompt": None})
    check("a bound-for-life identity renews with no prompt on a full read", rs[0].get("kind") == "none" and not rs[0].get("prompt"), rs[0])
    check("...and STILL with no prompt when the next read (the bundle) omits devbind (d1af4cfb)",
          rs[1].get("kind") == "none" and not rs[1].get("prompt"), {k: rs[1].get(k) for k in ("kind", "prompt", "error")})
    v = admit_and_land(sealed(kd, rs[1]["tx"])) if rs[1].get("tx") else rs[1].get("error")
    check("...and the node accepts that statement-free renewal", v is None, v)


# ---- vouched for by another device (4b1f70d7) and the helper's dropped proof (78fe55ff) ---------------------------------
def t_vouched():
    pc = TpmPC("voucher")
    kd = ident()
    addr = kd["address"]
    w = Wallet(kd, attest_via="remote")
    # the vouching PC attests THIS address on its own wallet and drops the statement; this wallet registered with it
    n = {"i": 0}

    def drop(mb, tip):
        n["i"] += 1
        return [{"max_block": mb, "device": pc.statement(f"V{n['i']}", challenge(addr, mb))}]

    walk("vouched for by a Windows PC", kd, "tpm", False, lambda mb: pc.statement("V0", challenge(addr, mb)), w,
         renew_prompt=lambda mb: None, assertions=lambda mb: {}, drops=drop, expect_kind="drop", expect_prompt=False)
    acc = relay_account(addr, kv_ops.recert_latest(addr) * L)
    check("vouched: the chain says assert_ok for the voucher's credential, yet this browser holds none, so it never "
          "asks for a signature", (acc.get("devbind") or {}).get("assert_ok") is True and not w.storage.get("nado_cred_" + addr))
    # a hardware wallet vouching renews statement-free with no voucher involved at all
    tz = Trezor("vouchtz")
    kd2 = ident()
    w2 = Wallet(kd2, attest_via="remote")
    walk("vouched for by a Trezor", kd2, "trezor", True, lambda mb: tz.statement(challenge(kd2["address"], mb)), w2,
         renew_prompt=lambda mb: None, expect_kind="none", expect_prompt=False)


# ---- ek: the chip enrolled by the helper / the node's own self-enrolment (c3682b21) -------------------------------------
class MsSim:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)

    def transmit(self, cmd):
        self.sock.sendall(struct.pack(">IBI", 8, 0, len(cmd)) + cmd)
        n = struct.unpack(">I", self._recv(4))[0]
        rsp = self._recv(n)
        self._recv(4)
        return rsp

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            c = self.sock.recv(n - len(buf))
            if not c:
                raise IOError("simulator closed")
            buf += c
        return buf


def _swtpm():
    """(tpm, cleanup) over a fresh swtpm on a local socket, or (None, None)."""
    if not shutil.which("swtpm"):
        return None, None
    state = _tempfile.mkdtemp(prefix="swtpm-renew-", dir=HOME)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    proc = subprocess.Popen(["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={state}", "--server", f"type=tcp,port={port}",
                             "--ctrl", f"type=tcp,port={port + 1}", "--flags", "startup-clear", "--log", "level=0"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sim = None
    for _ in range(100):
        if proc.poll() is not None:
            break
        try:
            sim = MsSim(port); break
        except OSError:
            time.sleep(0.05)
    if sim is None:
        proc.terminate()
        return None, None
    from ops.tpm_linux import LinuxTpm
    tpm = LinuxTpm.__new__(LinuxTpm)
    tpm.transmit = sim.transmit

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    return tpm, cleanup


def t_ek_and_node():
    from ops import tpm_aik, tpm_enrol as E, node_attest
    from ops.tpm_linux import ek_template, aik_template, RH_ENDORSEMENT
    kd = ident()
    addr = kd["address"]
    tpm, cleanup = _swtpm()
    try:
        if tpm is not None:
            ek_h, ek_pub, _ = tpm.create_primary(RH_ENDORSEMENT, ek_template())
            aik_h, aik_pub, _ = tpm.create_primary(RH_ENDORSEMENT, aik_template())
            ek_spki = tpm_aik.pub_area_spki(ek_pub)
            ek_id = hashlib.sha256(ek_spki).hexdigest()
            name = tpm_aik.aik_name(aik_pub)
            challengers = [f"chal{i}" for i in range(P.DEVICE_ATTEST_EK_CHALLENGERS)]
            eid = E.enrol_id(P.CHAIN_ID, ek_id, name.hex())
            rec = E.new_record(ek_id, ek_spki, name.hex(), aik_pub, addr, 100, challengers)
            secrets, seeds = {}, {}
            for i, c in enumerate(challengers):
                secrets[c], seeds[c] = os.urandom(32), os.urandom(32)
                blob, enc = tpm_aik.make_credential(ek_spki, name, secrets[c], seed=seeds[c])
                sess = tpm.start_policy_session()
                try:
                    tpm.policy_secret_endorsement(sess)
                    got = tpm.activate_credential(aik_h, ek_h, sess, blob, enc)
                finally:
                    tpm.flush(sess)
                assert got == secrets[c], "the chip opens every challenge"
                rec = E.apply_challenge(rec, c, blob, enc, 101 + i)
            rec = E.apply_commit(rec, addr, tpm_aik.credential_commitment(b"".join(secrets[c] for c in sorted(challengers))), 110)
            for i, c in enumerate(challengers):
                rec = E.apply_reveal(rec, c, secrets[c], seeds[c], 111 + i)
            kv_ops.tpm_enrol_set(eid, rec)

            def certify(mb):
                ci, sg = tpm.certify(aik_h, aik_h, challenge(addr, mb))
                return {"ek": ek_id, "id": eid, "certinfo": ci.hex(), "sig": sg.hex()}
            first = certify
        else:
            print("SKIP  ek: swtpm is not installed — the helper's four-message enrolment and the certify register are NOT "
                  "exercised; the chip binding is seeded with apply_register and only its statement-free renewal is walked")
            certify = None
            first = None
        w = Wallet(kd)
        if first:
            walk("ek (helper-enrolled chip)", kd, "ek", True, first, w, renew_prompt=lambda mb: None,
                 expect_kind="none", expect_prompt=False)
        else:
            apply_register(addr, E0, logger, device_key="ek:" + "ab" * 32, permanent=True, height=E0 * L + 5)
            e = E0 + 1300
            tip, mb = e * L, e * L + WALLET_MARGIN
            r = w.run({"op": "compute", "target": mb, "tip": tip, "accs": [relay_account(addr, tip)]})
            v = admit_and_land(sealed(kd, r["tx"])) if r.get("tx") else r.get("error")
            check("ek (seeded): the wallet renews statement-free and the node accepts it", r.get("kind") == "none" and v is None, v)
            land(sealed(kd, r["tx"]))

        # 78fe55ff: a read that has never carried devbind (state.devbind unknown) must still not prompt when the helper
        # left a proof: the renewal path reads the drop before any ceremony
        e = kv_ops.recert_latest(addr) + 250
        tip, mb = e * L, e * L + WALLET_MARGIN
        bare = {k: v for k, v in relay_account(addr, tip).items() if k != "devbind"}
        if certify:
            dr = [{"max_block": mb, "device": certify(mb)}]
            r = Wallet(kd).run({"op": "compute", "target": mb, "tip": tip, "accs": [bare], "drops": dr, "prompt": None})
            check("helper drop: a renewal with no devbind known uses the helper's proof, no prompt (78fe55ff)",
                  r.get("kind") == "drop" and not r.get("prompt"), {k: r.get(k) for k in ("kind", "prompt", "error")})
            v = admit_and_land(sealed(kd, r["tx"])) if r.get("tx") else r.get("error")
            check("...and the node accepts the helper's certify as a renewal", v is None, v)
            # the self-enrolled node renews with a fresh certify of its own (core_loop.maybe_tpm_self_enrol)
            e = e + 1
            v = admit_and_land(sealed(kd, e * L + WALLET_MARGIN, certify(e * L + WALLET_MARGIN)))
            check("node self-enrolment: a fresh certify renews the chip's identity", v is None, v)

        # c3682b21 / 139ed6ab: the NODE bound for life renews ITSELF, through a mempool that runs the real validation
        e = kv_ops.recert_latest(addr) + 300
        tip = e * L
        seen = []

        class Mem:
            keydict, address, peers, transaction_pool = kd, addr, [], []
            latest_block = {"block_number": tip}

            def merge_transaction(self, tx, user_origin=False):
                seen.append(tx)
                m = verdict(tx, tip)
                return {"result": m is None, "message": m}

            def enqueue_gossip(self, tx):
                pass

        st = node_attest.lease_state(addr, tip)
        check("node: its own lease state says bound for life and renewable", st["bind_mode"] == "perm" and st["bind_live"] and st["wants"], st)
        res = node_attest.renew_without_statement(Mem(), tip)
        check("node: renew_without_statement is admitted by the real validation", res.get("result") is True, res)
        if seen:
            v = verdict(seen[0], int(seen[0]["max_block"]))
            check("node: ...and accepted at its landing height", v is None, v)
            land(seen[0])
            ee = int(seen[0]["max_block"]) // L
            check("node: ...and applying it extends the node's lease by the class's grant",
                  kv_ops.recert_latest(addr) == ee and kv_ops.lease_of(addr, ee) == P.LEASE_EPOCHS_BY_CLASS["ek"] and present(addr, ee + 1))
    finally:
        if cleanup:
            cleanup()


def t_constants():
    """Timing holds for every class: the node starts wanting a renewal (FIDELITY_MIN_GAP_EPOCHS after the last recert)
    and the wallet triggers (80 % of the grant) well inside every class's lease; every class has a grant; every
    permanent class is bindable; the signature-renewal classes are leased (a permanent class needs no signature)."""
    for cls, lease in P.LEASE_EPOCHS_BY_CLASS.items():
        check(f"timing: {cls} — the node and the wallet both start renewing before its {lease}-epoch lease ends",
              P.FIDELITY_MIN_GAP_EPOCHS < lease and int(lease * 0.8) + 1 < lease)
    check("every bindable class has its own grant", set(P.DEVICE_BIND_CLASSES) <= set(P.LEASE_EPOCHS_BY_CLASS), P.DEVICE_BIND_CLASSES)
    check("every permanent class has a grant (the statement-free renewal writes one)",
          set(P.permanent_classes_at(None)) <= set(P.LEASE_EPOCHS_BY_CLASS))
    check("signature renewals are only for leased classes", not (set(P.LEASE_ASSERT_CLASSES) & set(P.permanent_classes_at(None))))
    check("the wallet's target margin is inside what the node accepts", 0 < WALLET_MARGIN <= P.POSW_TARGET_MARGIN, WALLET_MARGIN)


if __name__ == "__main__":
    kv_ops.close_all(); kv_ops.init_env()
    for name, fn in (("timing constants", t_constants), ("android-key", t_phone), ("tpm", t_windows_hello),
                     ("ledger / trezor", t_hardware_wallets), ("bundle without devbind", t_bundle_without_devbind),
                     ("vouched-for", t_vouched), ("ek + node self-renewal", t_ek_and_node)):
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()
            check(f"{name}: ran to the end", False)
    R.done("ALL PASS — every kind of identity can renew its presence lease, by the path the node accepts")

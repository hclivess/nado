"""TPM 2.0 from a Linux node, in-process — so a node attests itself with no operator and no shipped binary.

WHY THIS EXISTS SEPARATELY FROM apps/nado-tpm-attest. That binary is for wallet-only users on Windows, whose
browser cannot reach a chip. A NODE is already a Linux process with /dev/tpmrm0 in front of it, and shipping
an executable to every node would be a build-artifact and update problem we do not need. The command bytes are
the same either way — a TPM speaks TCG Part 3 regardless of who hands it the bytes — so this is transport plus
the same templates, not a second design.

The point is that after the consensus rule goes live, every node with a TPM enrols and registers ITSELF, on
startup and before its lease lapses. No tap, no drop store, no operator.

PREFER /dev/tpmrm0. That is the kernel's resource manager: it virtualises transient handles so our primaries
and policy sessions cannot collide with another process's, and it cleans up what we leak if we crash.
/dev/tpm0 is the raw device — exclusive-open, no virtualisation, and one leaked transient handle wedges the
chip for everything else on the machine until reboot.
"""
import os
import struct
import threading

# TPM2_CC_*, from tpm2-tss's tss2_tpm2_types.h rather than memory (MakeCredential is 0x168, not 0x167).
CC_CREATE_PRIMARY = 0x00000131
CC_ACTIVATE_CREDENTIAL = 0x00000147
CC_CERTIFY = 0x00000148
CC_POLICY_SECRET = 0x00000151
CC_FLUSH_CONTEXT = 0x00000165
CC_READ_PUBLIC = 0x00000173
CC_START_AUTH_SESSION = 0x00000176
CC_GET_CAPABILITY = 0x0000017A
CC_NV_READ = 0x0000014E
CC_NV_READ_PUBLIC = 0x00000169

ST_NO_SESSIONS = 0x8001
ST_SESSIONS = 0x8002

RH_NULL = 0x40000007
RS_PW = 0x40000009
RH_ENDORSEMENT = 0x4000000B
RH_OWNER = 0x40000001

# THE ENDORSEMENT CERTIFICATE LIVES IN THE CHIP'S OWN NV. The vendor's signature over the endorsement key is
# what the whole vendor-endorsed path rests on, and on a Linux box there is no service to fetch it from —
# TCG reserves these indices for it (EK Credential Profile §2.2.1.4), and a machine with a firmware TPM has
# the RSA one populated at manufacture. A machine holding no certificate here cannot use this path at all,
# which is the correct outcome and not a case to work around: without the vendor's signature the design
# degrades to "some TPM somewhere said yes", which a software TPM says just as convincingly.
NV_EK_CERT_RSA = 0x01C00002
NV_EK_CERT_ECC = 0x01C0000A

# TPM_PT_NV_BUFFER_MAX is 512 on some parts and 1024 on others. Reading in 512-byte chunks is correct on
# both, and an EK certificate is ~1-2 KiB, so the extra round trip costs nothing worth optimising.
NV_CHUNK = 512

ALG_RSA = 0x0001
ALG_SHA256 = 0x000B
ALG_NULL = 0x0010
ALG_RSASSA = 0x0014

RC_OBJECT_MEMORY = 0x902

# The TCG EK Credential Profile L-1 template. REPRODUCE IT EXACTLY: a primary is DERIVED from its template, so
# one byte different yields a different key, and the vendor's endorsement certificate then belongs to a key
# this machine does not hold. Attributes and authPolicy are fixed by that profile, not chosen by us.
EK_ATTRS = 0x000300B2   # fixedTPM|fixedParent|sensitiveDataOrigin|adminWithPolicy|restricted|decrypt
EK_POLICY_SHA256 = bytes.fromhex("837197674484b3f81a90cc8d46a5d724fd52d76e06520b64f2a1da1b331469aa")

# A restricted RSA-2048 signing key. `restricted` is the load-bearing attribute: such a key signs ONLY
# structures the TPM itself generated, so a signature from it cannot be an arbitrary message the host chose.
# That is what makes TPM2_Certify evidence rather than merely a signature.
AIK_ATTRS = 0x00050472  # fixedTPM|fixedParent|sensitiveDataOrigin|userWithAuth|noDA|restricted|sign


def tpm2b(b: bytes) -> bytes:
    return struct.pack(">H", len(b)) + b


def ek_template() -> bytes:
    return (struct.pack(">HHI", ALG_RSA, ALG_SHA256, EK_ATTRS)
            + tpm2b(EK_POLICY_SHA256)
            + struct.pack(">HHH", 0x0006, 128, 0x0043)      # symmetric AES-128-CFB
            + struct.pack(">H", ALG_NULL)                   # scheme: none, it is a decryption key
            + struct.pack(">HI", 2048, 0)
            + tpm2b(b"\x00" * 256))                         # the profile's unique


def aik_template() -> bytes:
    return (struct.pack(">HHI", ALG_RSA, ALG_SHA256, AIK_ATTRS)
            + tpm2b(b"")                                    # no authPolicy
            + struct.pack(">H", ALG_NULL)                   # symmetric: none, it is a signing key
            + struct.pack(">HH", ALG_RSASSA, ALG_SHA256)    # RSASSA/SHA-256 -> the statement is COSE -257
            + struct.pack(">HI", 2048, 0)
            + tpm2b(b""))


class TpmError(Exception):
    def __init__(self, code, where=""):
        self.code = code
        super().__init__(f"{where} failed: TPM 0x{code:08x}"
                         + (" (out of transient object slots — something leaked handles)"
                            if code == RC_OBJECT_MEMORY else ""))


class LinuxTpm:
    """One command in flight at a time: the device is a request/response channel, and interleaving two
    commands on one descriptor mixes their replies."""

    def __init__(self, path=None):
        self.path = path or self.device()
        if not self.path:
            raise TpmError(0, "no TPM device")
        self._fd = os.open(self.path, os.O_RDWR)
        self._lock = threading.Lock()

    @staticmethod
    def device():
        for p in ("/dev/tpmrm0", "/dev/tpm0"):
            if os.path.exists(p):
                return p
        return None

    @staticmethod
    def present():
        return LinuxTpm.device() is not None

    def close(self):
        try:
            os.close(self._fd)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def transmit(self, cmd: bytes) -> bytes:
        with self._lock:
            if os.write(self._fd, cmd) != len(cmd):
                raise TpmError(0, "short write")   # a partial command is not a command
            return os.read(self._fd, 4096)

    # --- commands ---------------------------------------------------------------------------------------

    def _call(self, tag, code, handles=b"", auth=None, params=b"", where=""):
        body = handles + (struct.pack(">I", len(auth)) + auth if auth is not None else b"") + params
        cmd = struct.pack(">HII", tag, 10 + len(body), code) + body
        rsp = self.transmit(cmd)
        if len(rsp) < 10:
            raise TpmError(0, where + " (truncated response)")
        size, rc = struct.unpack(">I", rsp[2:6])[0], struct.unpack(">I", rsp[6:10])[0]
        if rc != 0:
            raise TpmError(rc, where)
        return rsp[10:size]

    @staticmethod
    def _pw_auth():
        return struct.pack(">I", RS_PW) + b"\x00\x00" + b"\x00" + b"\x00\x00"

    def create_primary(self, hierarchy, template):
        """Returns (handle, pubArea, name)."""
        params = tpm2b(tpm2b(b"") + tpm2b(b"")) + tpm2b(template) + tpm2b(b"") + struct.pack(">I", 0)
        r = self._call(ST_SESSIONS, CC_CREATE_PRIMARY, struct.pack(">I", hierarchy),
                       self._pw_auth(), params, "CreatePrimary")
        handle = struct.unpack(">I", r[:4])[0]
        o = 8                                        # skip parameterSize
        pub, o = _take2b(r, o)
        _cd, o = _take2b(r, o)                       # creationData
        _ch, o = _take2b(r, o)                       # creationHash
        o += 2 + 4                                   # creation ticket: tag + hierarchy
        _tk, o = _take2b(r, o)
        name, o = _take2b(r, o)
        return handle, pub, name

    def start_policy_session(self):
        params = tpm2b(b"\x00" * 16) + tpm2b(b"") + b"\x01" + struct.pack(">HH", ALG_NULL, ALG_SHA256)
        r = self._call(ST_NO_SESSIONS, CC_START_AUTH_SESSION,
                       struct.pack(">II", RH_NULL, RH_NULL), None, params, "StartAuthSession")
        return struct.unpack(">I", r[:4])[0]

    def policy_secret_endorsement(self, session):
        """The EK is adminWithPolicy, so a plain password authorization is refused however empty the
        endorsement auth happens to be. This is what satisfies its policy."""
        params = tpm2b(b"") + tpm2b(b"") + tpm2b(b"") + struct.pack(">i", 0)
        self._call(ST_SESSIONS, CC_POLICY_SECRET,
                   struct.pack(">II", RH_ENDORSEMENT, session), self._pw_auth(), params, "PolicySecret")

    def activate_credential(self, activate, key, session, credential_blob, secret):
        """The proof: the chip returns the sealed secret ONLY because both objects live inside it."""
        auth = (self._pw_auth()
                + struct.pack(">I", session) + b"\x00\x00" + b"\x01" + b"\x00\x00")
        r = self._call(ST_SESSIONS, CC_ACTIVATE_CREDENTIAL, struct.pack(">II", activate, key),
                       auth, credential_blob + secret, "ActivateCredential")
        out, _ = _take2b(r, 4)                       # skip parameterSize
        return out

    def certify(self, obj, signer, qualifying_data):
        """certInfo is signed by `signer` — the key whose certificate goes in x5c — over qualifying data WE
        choose, which is where the verifier looks for hash(authData || clientDataHash)."""
        auth = self._pw_auth() + self._pw_auth()
        params = tpm2b(qualifying_data) + struct.pack(">HH", ALG_RSASSA, ALG_SHA256)
        r = self._call(ST_SESSIONS, CC_CERTIFY, struct.pack(">II", obj, signer), auth, params, "Certify")
        o = 4                                        # parameterSize
        cert_info, o = _take2b(r, o)
        o += 4                                       # TPMT_SIGNATURE: sigAlg + hashAlg
        sig, o = _take2b(r, o)
        return cert_info, sig

    def flush(self, handle):
        try:
            self._call(ST_NO_SESSIONS, CC_FLUSH_CONTEXT, struct.pack(">I", handle), None, b"", "FlushContext")
        except TpmError:
            pass

    def transient_handles(self):
        params = struct.pack(">III", 1, 0x80000000, 32)     # TPM_CAP_HANDLES over the transient range
        r = self._call(ST_NO_SESSIONS, CC_GET_CAPABILITY, b"", None, params, "GetCapability")
        # moreData is ONE byte (TPMI_YES_NO), then the capability word, then TPML_HANDLE's count.
        n = struct.unpack(">I", r[5:9])[0]
        return [struct.unpack(">I", r[9 + 4 * i:13 + 4 * i])[0] for i in range(min(n, 32))]

    def nv_read_public(self, index):
        """TPMS_NV_PUBLIC for an NV index as (attributes, data size), or None when it is not defined. The
        SIZE is why this exists: NV_Read must be told how much to read, and asking past the end is an error
        rather than a short read."""
        try:
            r = self._call(ST_NO_SESSIONS, CC_NV_READ_PUBLIC, struct.pack(">I", int(index)),
                           None, b"", "NV_ReadPublic")
        except TpmError:
            return None
        pub, _ = _take2b(r, 0)
        attrs = struct.unpack(">I", pub[6:10])[0]
        o = 10 + 2 + struct.unpack(">H", pub[10:12])[0]          # skip authPolicy
        return attrs, struct.unpack(">H", pub[o:o + 2])[0]

    def nv_read(self, index, size, auth_handle=None):
        """Read `size` bytes from an NV index, in chunks the chip will accept.

        AUTHORISED AS THE OWNER by default, which is what the endorsement certificate indices expect and
        what `tpm2_nvread -C o` does. On a machine whose owner hierarchy carries a password this raises
        rather than returning a truncated certificate — a half-read certificate would fail chain
        verification later with a message pointing at the wrong thing entirely."""
        auth = RH_OWNER if auth_handle is None else auth_handle
        out = b""
        while len(out) < size:
            n = min(NV_CHUNK, size - len(out))
            r = self._call(ST_SESSIONS, CC_NV_READ, struct.pack(">II", auth, int(index)),
                           self._pw_auth(), struct.pack(">HH", n, len(out)), "NV_Read")
            chunk, _ = _take2b(r, 4)                              # skip parameterSize
            if not chunk:
                raise TpmError(0, "NV_Read returned nothing")
            out += chunk
        return out

    def ek_certificate(self):
        """The chip's endorsement certificate (DER), or None if it holds none. RSA first: that is the index
        populated on the firmware TPMs this path exists for."""
        for index in (NV_EK_CERT_RSA, NV_EK_CERT_ECC):
            nv = self.nv_read_public(index)
            if nv and nv[1]:
                try:
                    return self.nv_read(index, nv[1])
                except TpmError:
                    continue
        return None

    def flush_all_transient(self):
        """A crashed run leaves its primaries loaded and a TPM has only a handful of object slots, so the next
        attempt dies with TPM_RC_OBJECT_MEMORY for reasons unrelated to what it is doing."""
        handles = self.transient_handles()
        for h in handles:
            self.flush(h)
        return len(handles)


def _take2b(buf, off):
    n = struct.unpack(">H", buf[off:off + 2])[0]
    return buf[off + 2:off + 2 + n], off + 2 + n


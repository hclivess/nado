# nado-tpm-attest — making a Windows TPM usable when Windows Hello will not

`apps/nado-tpm-attest` is a small, dependency-free Windows binary, cross-compiled from the Linux fleet host
(`cargo build --release --target x86_64-pc-windows-gnu`). It exists because **Windows Hello is the only way a
web page can reach a TPM, and on many PCs it refuses to attest.**

## The problem it works around

Measured over 202 stored Windows Hello samples (`index/device_attest`, AAGUIDs 08987058 / 9ddd1817 /
6028b017), and reproduced live on 2026-09-10:

- Hello returns `fmt: "none"` (no attestation at all), or a `packed` statement with **no x5c** —
  self-attestation, no chain, refused by the kernel — on a machine whose TPM 2.0 is healthy and whose
  `certreq -enrollaik` **succeeds**.
- `certreq -enrollaik -config ""` enrols a **TestAIK in the Local System context**. Windows Hello runs in the
  signed-in user's context and never gets it, so "EnrollDone" proves the AIK *service* answers for that TPM
  and nothing more. Do not read it as a fix.
- On other machines Microsoft's AIK service returns **404** — `The authority "<vendor>-keyid-….microsoftaik.
  azure.net" does not exist` — meaning their backend has no CA registered for that TPM's KeyId. Microsoft has
  confirmed this is service-side and that KeyIds cannot be registered by end users (Microsoft Q&A 5985657).

Nothing a browser sends changes any of this. The credential key type does not either: forcing RS256 on a
failing machine yields self-attestation rather than a chain (tried and reverted the same hour — see the note
at the `pubKeyCredParams` call site in interface.js).

## What it does

Enrols its own **named** AIK the way Microsoft's own sample does (`certreq -enrollaik -f -machine -config ""
<name>`, per their EnrollAik.ps1), creates the credential key in the TPM through the Microsoft Platform Crypto
Provider, has the AIK certify it, and emits exactly the `tpm` statement `native/attest` already verifies —
then drops it on a relay through the existing `/node_attest_drop` path, so the wallet picks it up like a phone
attestation. **Phase 1 changes no consensus rule.**

The current build is a **probe**: it reports what the machine can do and dumps the shape of
`NCryptCreateClaim`'s output (scanning for the `\xffTCG` `TPM_GENERATED` magic to locate the `TPMS_ATTEST`),
because the claim blob layout is the one piece Microsoft does not publicly specify and must not be guessed.
It submits nothing.

## The claim blob, decoded (measured 2026-09-10 — none of this is documented by Microsoft)

`NCryptCreateClaim(subject, authority, NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT = 0x03, params, ...)` returns:

```
KAST header, 28 bytes
  0x00 "KAST"   0x04 version=1   0x08 field8=2   0x0c cbHeader=28
  0x10 cbSection1   0x14 cbSection2   0x18 cbSection3      (28 + the three = total length)

  section 1  a TPMS_ATTEST of type 0x801a  TPM_ST_ATTEST_CREATION
  section 2  "KADS": header 24 bytes, then cbCertifyInfo @+12, cbSignature @+16, cbKeyBlob @+20,
             followed by certInfo || signature || keyBlob back to back.
             certInfo is the TPMS_ATTEST of type 0x8017  TPM_ST_ATTEST_CERTIFY  <- what WebAuthn wants
  section 3  (unused by us)

  keyBlob is a PCP blob: "PCPM", cbHeader=56, cbPublic @+16, cbPrivate @+20, cbPolicyDigestList @+32.
             The credential key's TPM2B_PUBLIC — the `pubArea` — starts at cbHeader.
```

Worked example, a real 2853-byte claim: sections 834 / 1221 / 770 (28+834+1221+770 = 2853); KADS at 862;
certInfo at 886, 173 bytes; signature at 1059, 256 bytes; keyBlob at 1315, 768 bytes; and 24+173+256+768 = 1221.

**The nonce constant is the whole game.** A claim made with no parameter list has `extraData` EMPTY, and
`native/attest` requires `certInfo.extraData == hash(authData || clientDataHash)` — the anti-replay binding that
ties a statement to one wallet and one landing block. Pass the challenge through `pParameterList` as:

| buffer type | value | where the nonce lands |
|---|---|---|
| `NCRYPTBUFFER_CLAIM_KEYATTESTATION_NONCE` | **49** | the **0x8017 CERTIFY** attest — **this is the one** |
| `NCRYPTBUFFER_CLAIM_IDBINDING_NONCE` | 48 | the 0x801a CREATION attest — binds nothing we verify |

Values that cost a round trip each by being guessed rather than read out of the SDK header: 20/21 are
`SSL_CLIENT_RANDOM`/`SSL_SERVER_RANDOM` (answer: `NTE_INVALID_PARAMETER`), and `AUTHORITY_AND_SUBJECT` is 0x03,
not 0x02 — 0x02 is `SUBJECT_ONLY`, which silently produces a claim with no authority half at all.

So the client flow is: build `authData` and `clientDataJSON`, compute `sha256(authData || sha256(cdj))`, pass
those 32 bytes as buffer type 49, then lift `certInfo`, `sig` and `pubArea` straight out of the blob.

**Still open:** `x5c`. The AIK certificate exists only where Microsoft will certify the chip, which is precisely
the machine class this tool was written for. On a 404 machine the chip signs a perfectly good certify with an
AIK that has no certificate — hence phase 2. Every `PCP_EK*CERT` property answers 8 bytes (a pointer) on both a
provider and a key handle, while `PCP_EKPUB` returns a real 283-byte RSA1 blob, so the endorsement certificate
needs a different route: `TPM2_NV_Read` of the TCG index over TBS. Both keys' TPM handles are readable via
`PCP_PLATFORMHANDLE` (measured: 0x80fffffd and 0x80fffff2), so a raw-TPM path is open if it is ever needed.

## Threat model — a patched binary must buy nothing

**The security does not live in this program.** It is a courier. Every step it performs is checked by
something it does not control, so replacing or patching it gains an attacker nothing:

| hostile helper tries | why it fails |
|---|---|
| forge `certInfo` or its signature | signed inside the TPM by the AIK; the private key is non-exportable and the helper never sees it |
| mint its own AIK certificate | phase 1: only Microsoft issues one. phase 2: only we do, and only after `ActivateCredential` proves the AIK shares a TPM with a vendor-certified EK |
| reuse a statement for another wallet | the challenge is `blake2b(chain_id, sender, anchor_hash, max_block)` — bound to that sender, anchor and landing block |
| replay an old statement | same binding; the anchor block and `max_block` expire it |
| skip the TPM and self-sign | that is `packed` with no `x5c`, refused by the kernel |
| run N times for N identities | every key from one TPM shares one AIK certificate, so all collapse to ONE `device_binding_key`; `devbind` refuses a second sender while the binding is live |

The last row is the load-bearing one and it is enforced **on chain**, never here.

### The rule phase 2 must not break

Phase 2 (accepting a vendor EK chain, so a TPM Microsoft declines still counts) makes NADO the AIK issuer.
**The binding key must then derive from the EK, never from an AIK we issued.** Otherwise a farm enrols N AIKs
from one chip and gets N identities — exactly the "print identities" attack. The AIK certificate we mint has
to carry the EK's identity in a fixed extension and consensus must derive the binding from that: N AIKs, one
EK, one identity. Two costs that are new and real:

- **our CA key becomes a single point of failure** — whoever holds it can assert any EK id, i.e. unlimited
  identities. Microsoft's key carries that weight today;
- **the human gesture disappears** — WebAuthn requires a tap per credential, a headless helper does not. The
  per-TPM binding cap is the only thing that makes that acceptable, so that rule must never regress.

## Vendor EK roots (phase 2 groundwork, verified 2026-09-10)

An AMD fTPM EK certificate from a real machine chains publicly, with no Microsoft involvement:

```
EK cert (per device, 2021 -> 2046, EKU 2.23.133.8.1, keyUsage keyEncipherment, CA:FALSE,
         SAN TPMManufacturer id:414D4400 / TPMModel AMD / TPMVersion id:00030001)
  -> CN=PRG-RN, O=Advanced Micro Devices   (CA:TRUE, pathlen:0)   http://ftpm.amd.com/pki/aia/...
    -> CN=AMDTPM, O=Advanced Micro Devices (self-signed root, 2014 -> 2039)
       sha256 67bd2472a546751caca5f358a78f80727531671338960a9bcfdfbe6a34d0c6a1
```

`openssl verify -CAfile <root> -untrusted <intermediate> <ek>` → OK. `OU=Engineering` is AMD's naming, not a
test hierarchy: the PKI publishes AIA, CRL, OCSP and a CPS at `ftpm.amd.com`. Pinning that root admits every
AMD fTPM, exactly as the Google, Apple and Microsoft roots admit their vendors' devices — it is a vendor rule,
never a per-device one.

## Building and serving

```
cd apps/nado-tpm-attest && cargo build --release --target x86_64-pc-windows-gnu
```

The binary is NOT committed: the source is, and the relay serves a built copy from `static/` as an untracked
file, so no node carries an executable in its git history (and never track a build product at its generated
path — see the fleet fast-forward incident).

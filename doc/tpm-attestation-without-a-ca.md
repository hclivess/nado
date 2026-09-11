# Attesting a TPM without a certificate authority

**Status: core proven end to end against a real TPM 2.0 (2026-09-10). Endpoints, consensus rule and vendor
root policy are not built.**

This is how a machine proves it holds a genuine, vendor-certified TPM — without Microsoft, and without anyone
holding a signing key that could mint identities.

## The problem it solves

26.8% of every device-attestation attempt on this chain is a Windows PC whose TPM is healthy and whose Windows
Hello returns nothing. Measured over 664 samples:

| | share |
|---|---|
| works today (phone / hardware wallet) | 47.9% |
| **Windows Hello refuses to attest** | **26.8%** |
| user-fixable (a password manager took the ceremony) | 18.8% |
| works today (Windows Hello attests) | 6.5% |

The dominant cause is that Microsoft's AIK service has no certificate authority registered for the chip's
KeyId and answers HTTP 404 — `The authority "<vendor>-keyid-….microsoftaik.azure.net" does not exist`.
Microsoft has confirmed this as service-side, with KeyIds unregisterable by end users and no supported way to
change their trust database. No client-side change fixes it. On Linux the situation is simpler and worse:
there is no Windows Hello and no AIK service at all, so there has never been a path.

Those machines are not short of evidence. They carry a **vendor-signed endorsement certificate** — AMD's
chains to `CN=AMDTPM`, Intel's through the CSME EICAs the chip keeps in its own NV. The hardware proof exists
and is verifiable without Microsoft. What is missing is one statement: *this attestation key lives in that
certified chip*.

## Why the obvious shortcuts do not work

**"Create the attestation key as a child of the endorsement key and have it certify its own creation."**
Tried and retracted 2026-09-11, in a single day, for two independent reasons. It is forgeable: nothing
vendor-signed reaches the key doing the signing, so `parentName` is a claim inside a blob signed by the
claimant, and a software RSA key passes every check with no TPM at all
(`tests/test_certify_creation_is_forgeable.py`). And the hardware refuses it: an AMD firmware TPM
answers `TPM2_Create` under the endorsement key with `TPM_RC_HANDLE`, rejecting the parent handle before
authorisation is even evaluated. See `doc/tpm-attestation-architecture-review.md`.

**"Just send the EK certificate."** It is public data — anyone who has seen a machine's certificate can copy
it. And the endorsement key **cannot sign**: `Key Usage: critical, Key Encipherment`, no `digitalSignature`.
TCG defines it as a restricted decryption key. A WebAuthn `tpm` statement requires `certInfo` to be signed by
the key in `x5c[0]`, so an EK certificate can never occupy that slot.

**"Derive the challenge from chain data, so it needs no round trip."** Anything every node can recompute, the
client can recompute too. The proof would prove nothing.

Proving possession of a decrypt-only key has exactly one shape: send it something only it can decrypt and see
it come back. That is `TPM2_ActivateCredential`, and it is inherently interactive — which is why TCG invented
the AIK-plus-Privacy-CA model, and why Microsoft runs the service that is failing.

## The construction

A CA turns the interactive proof into a durable artifact by signing it. That works, and it is expensive: a
long-lived key able to assert any endorsement identity is a key able to mint identities, guarded forever.

There is a cheaper way, using machinery this chain already runs for RANDAO. **`TPM2_MakeCredential`'s
credentialBlob is deterministic in (seed, name, secret)** — only the OAEP-wrapped seed is randomised, and no
verifier needs that half. Measured: two calls with the same seed produce an identical blob and different
encrypted seeds. So a challenge issued once can be **replayed by everyone afterwards**.

```
1. challenger  seals secret S under seed R:  blob = make_credential(EKpub, aikName, S, seed=R)
2. client      TPM2_ActivateCredential -> recovers S          (only possible inside the chip)
               publishes H(S)                                  <- commitment
3. challenger  reveals (S, R)
4. every node  recomputes the blob from (S, R), checks it equals the published blob,
               and checks the commitment is to that S          <- verify_credential_reveal()
```

The client can only learn `S` by holding the chip, and must commit **before** the reveal, so it cannot read
the answer off the chain. **Nothing is signed and no key persists** — nothing to steal, rotate or guard, and
no node holds minting power.

### The residual attack, and the shape of the fix

A challenger could privately leak `S` so a client commits without a TPM. Therefore there must be **several
independent challengers**, with the client required to recover every one of their secrets. Forgery then needs
all of them to collude — a property consensus can observe, rather than a key someone promises to protect.

## What binds an identity

**The endorsement key, never an attestation key we accept.** A chip holds unlimited AIKs; binding to one would
hand a single machine an identity per enrolment. `ek_identity()` derives from the endorsement key's own
SubjectPublicKeyInfo. Enrol ten AIKs and they collapse to one identity.

Regenerating the endorsement seed to fake a new chip changes the EK, and the vendor's certificate no longer
matches it — so it cannot enrol at all.

## What is checked, and why each check is load-bearing

`verify_ek_chain()` — the vendor signature is the entire basis for trusting hardware. Refuses a certificate
that is not `tcg-kp-EKCertificate`, that is a CA, or that claims signing capability. Client-supplied
intermediates are a routing hint; only pinned roots are trust input.

`validate_aik_pub_area()` — we are about to vouch for a public area the client chose. Certify an
**unrestricted** signing key and that chip can afterwards sign anything the host asks, including a forged
`TPMS_ATTEST` for a key that never lived in the TPM. Required: `restricted`, `sign`, not `decrypt`,
`fixedTPM`/`fixedParent` (else duplicable to another chip), `sensitiveDataOrigin` (else the private half could
have been imported), and a real signing scheme rather than `TPM_ALG_NULL`.

## Verified end to end

Against swtpm, driving our own command bytes and our own challenger:

```
EK        pubArea 314 B          TCG EK Credential Profile L-1 template derives
AIK       pubArea 280 B          restricted RSASSA/SHA-256 signing key derives
challenge credentialBlob 70 B    our MakeCredential, accepted by a real TPM
activate  recovered the sealed secret — EK and AIK proven to share a chip
replay    an independent node re-derived the challenge: VERIFIED
certify   extraData carries our challenge — the binding the verifier checks
```

**What this does not prove:** that particular silicon behaves the same. swtpm accepts templates a vendor fTPM
may reject and carries no endorsement certificate at all.

## Honest limits

- **Automation removes an ongoing cost.** WebAuthn needs a human tap per lease; this needs none, which is
  required for headless nodes and also means a farm's chips cost nothing to keep running. Identity *count* is
  unchanged — one chip, one identity — but the Sybil question collapses onto the price of a chip.
- **Which roots we pin is the real dial.** Discrete TPM modules are ~£15; a CPU-vendor fTPM implies a whole
  machine at ~£150. Pinning CPU vendors only is reversible in the widening direction and not the other way.
- **We inherit AMD's and Intel's factories.** Mis-issuance or a leaked vendor CA lands on us. The same trust
  already extended to the Google and Apple roots we pin.
- **Attestation proves authorisation, not presence.** The chip authorises an identity at registration and
  renewal; mining happens wherever the wallet is. True of the phone path too.

## Known gap before this can run on real hardware

Python `cryptography` **refuses to parse a real AMD endorsement certificate**:
`ParseError { kind: EncodedDefault, ["Certificate::tbs_cert", "TbsCertificate::raw_extensions", 1,
"Extension::critical"] }` — AMD encodes `critical: FALSE` explicitly where strict DER requires it omitted.
openssl accepts it. Real vendor certificates are not strictly DER, so EK parsing must move to a lenient parser
(`x509-parser`, already used by `native/attest`).

## Where the code is

| | |
|---|---|
| `ops/tpm_aik.py` | KDFa, MakeCredential, commit-reveal, EK chain and AIK attribute validation |
| `apps/nado-tpm-attest/src/tpm.rs` | TPM 2.0 commands, platform-independent |
| `apps/nado-tpm-attest/src/tbs.rs` | Windows transport |
| `apps/nado-tpm-attest/src/devtpm.rs` | Linux transport (`/dev/tpmrm0`) |
| `protocol_roots/ek/` | vendor endorsement roots |
| `tests/test_tpm_aik.py`, `apps/nado-tpm-attest/tests/` | including the swtpm end-to-end |

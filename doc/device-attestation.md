# Device attestation — a registered identity is a real device

Status: DESIGN + phase 0 (2026-09-07). Operator decision: the open lane keeps free entry, no capital
gate, and Sybil resistance must not be automatable. Every per-identity rule so far (sequential work,
probation, per-IP budgets, the ingress identity cap) is linear in identity count, so a farm pays it
1,000 times the same way 1,000 phones would. Measured 2026-09-06: ~1,000 of 1,191 registered identities
belong to two or three operators running browser farms on Linux/Windows servers.

The one thing a server cannot fake is genuine hardware's secure element. Four device classes expose it
to a web page through WebAuthn *attestation* — the device creates a non-exportable key in hardware and
returns a statement, signed inside that hardware, that chains to a vendor attestation root:

| class | statement format | hardware | pinned root(s) |
|---|---|---|---|
| iPhone / iPad | `apple` | Secure Enclave | Apple WebAuthn Root CA |
| Android phone | `android-key` | TEE / StrongBox (locked bootloader) | Google Hardware Attestation roots, Key Attestation CA1 |
| Windows PC | `tpm` | a physical TPM 2.0 (Windows Hello) | Microsoft TPM Root Certificate Authority 2014 |
| Linux / any PC | `packed` | a FIDO2 security key with full attestation | that authenticator's own root from the FIDO metadata snapshot |

A cloud VM, a desktop browser without hardware, an emulator, a software authenticator, a virtual TPM or a
rooted/unlocked phone cannot produce a valid chain.

## What it proves, and what it does not

- PROVES: this registration was created on a genuine iOS or Android device (model class visible), by a
  key that lives in that device's hardware, over a challenge the chain chose (fresh, unpredictable).
- PROVES on renewal: the same device key signed the new beacon-derived challenge — the phone was present.
- ROOTING IS NOT THE LOOPHOLE. Android key attestation reports the boot state from the secure element
  (bootloader locked, verified boot); the kernel requires TEE/StrongBox security levels, and phase 2 also
  requires `deviceLocked` + `verifiedBootState == Verified` from the RootOfTrust field, so rooted and
  unlocked phones are rejected outright. A rooted phone is exactly what would automate the tap, and it
  cannot attest.
- DOES NOT prove one identity per device: vendors expose no per-device identifier (privacy). A genuine,
  locked phone can create as many credentials as a HUMAN taps — one tap per identity per lease, since
  WebAuthn requires user activation for every signature and a rooted device cannot attest. That is the
  operator's criterion: the cost is non-automatable human work on genuine hardware, not CPU or capital.

## Roots are consensus constants

`protocol_roots/*.pem` carry the vendor roots and `protocol.DEVICE_ATTEST_ROOT_FINGERPRINTS` pins their
SHA-256 over DER: Apple WebAuthn Root CA, four Google hardware-attestation roots (2034/2036/2042 and Key
Attestation CA1), Microsoft TPM Root Certificate Authority 2014. `protocol_roots/fido_mds_roots.json` is
a SNAPSHOT of the FIDO Alliance metadata (blob no. 279): the 240 attestation roots of the 332 FIDO2
authenticators with full attestation and no compromise/revocation status, and — the part that matters —
each AAGUID mapped to ITS OWN roots (`DEVICE_ATTEST_FIDO_AAGUID_ROOTS`), so a key from vendor A can never
claim vendor B's identity.

A chain is valid only if it ends at a pinned root; roots are never fetched, never learned from a peer, and
change only through a gated protocol commit (refresh the metadata snapshot the same way). Revocation
lists are not consulted at validation time (non-deterministic); a compromised intermediate or vendor is
handled like a root change, by a commit.

## Transaction shape

`register` gains an optional `device` field:

```
"device": {
  "fmt": "apple" | "android-key",
  "att": <base64 CBOR attestationObject>,        # authData + attStmt (x5c chain, sig)
  "cdj": <base64 clientDataJSON>,                 # type, challenge, origin
  "rp": <relying-party id the wallet was served from>
}
```
(`fmt` is read from the CBOR; the credential id is inside `att`.)

The challenge inside `cdj` MUST equal `blake2b(chain_id || sender || anchor_block_hash || max_block)`,
the same anchor the PoSW already binds, so an attestation cannot be replayed for another identity or
another lease. `origin` must be one of the protocol's accepted wallet origins OR any origin when the
relay is reached over plain http (the relay recipe), because origin is a phishing control, not a Sybil
control — the secure-element chain is the Sybil control.

## Validation (native kernel `native/attest`)

`nado_attest_verify(att, cdj, challenge, roots, rp_ids, now) -> {ok, fmt, aaguid, cred_id, reason, chain,
security_level, root_sha256, tpm_manufacturer}`. Layout: `chain.rs` (chain + signatures), `authdata.rs`
(authenticator data + COSE keys), `tpm.rs` (TPM 2.0 structures), `formats/{apple,android_key,packed,tpm}.rs`.

Common: CBOR shape; authData flags user-present + attested credential; `rpIdHash` ∈ accepted rp ids;
`clientDataJSON.type == webauthn.create` and its `challenge` == the chain's challenge; `x5c` walked to a
pinned root with every link's signature verified using the hash the signed certificate names (ECDSA
P-256 / P-384, RSA PKCS#1 v1.5; SHA-1/256/384/512 — real Google chains mix P-256/SHA-256 leaves with
P-384/SHA-384 intermediates), validity against `now` (the ANCHOR block's timestamp, never wall time),
CA constraints on every non-leaf. The root reached is reported as `root_sha256`.

- `apple`: nonce extension 1.2.840.113635.100.8.2 == sha256(authData || sha256(cdj)); leaf key == credential key.
- `android-key`: attStmt.sig by the leaf key over authData || sha256(cdj); key-description extension
  1.3.6.1.4.1.11129.2.1.17 carries clientDataHash and TrustedEnvironment/StrongBox for both levels
  (phase 2: RootOfTrust `deviceLocked` + `verifiedBootState == Verified`).
- `packed`: attStmt.sig by the leaf key (alg from attStmt); leaf X.509 v3, subject OU "Authenticator
  Attestation", not a CA; AAGUID extension 1.3.6.1.4.1.45724.1.1.4 (when present) == authData AAGUID.
  Self-attestation (no x5c) is refused up front.
- `tpm` (ver 2.0): pubArea (TPMT_PUBLIC, RSA or ECC) key == credential key; certInfo is a TPMS_ATTEST of
  type TPM_ST_ATTEST_CERTIFY whose extraData == hash_alg(authData || sha256(cdj)) and whose attested name
  == nameAlg(pubArea); sig over certInfo by the AIK certificate; AIK certificate v3, empty subject, not a
  CA, EKU tcg-kp-AIKCertificate (2.23.133.8.3), SAN directoryName with tcg-at-tpmManufacturer
  (2.23.133.2.1), returned as `tpm_manufacturer`.

Consensus constraints on top of the verdict (`transaction_ops.verify_register_device`): `tpm` only for the
Windows Hello HARDWARE authenticator AAGUID (08987058-cadc-4b81-b6e1-30de50dcbe96 — the VBS and software
variants are not a TPM), only chains ending at Microsoft's TPM root, and only physical TPM manufacturers
(`DEVICE_ATTEST_TPM_MANUFACTURERS`; Microsoft's own id 4D534654 is the Hyper-V/Azure virtual TPM and is
refused); `packed` only for an AAGUID in the metadata snapshot AND a chain ending at that AAGUID's own root;
`apple`/`android-key` a chain ending at a pinned vendor root.

Pure Rust (`ciborium`, `x509-parser`, `p256`, `p384`, `rsa`, `sha1`/`sha2`), no network, deterministic,
bound through ctypes (`ops/attest_native.py`, no Python fallback). Tests: openssl-built chains for all
four formats with negatives for every constraint (tests/test_device_attest_kernel.py,
test_device_attest_formats_pc.py), the consensus rule (test_device_attest_rule.py), and a REAL Android
phone's statement as a vector (tests/vectors/, test_device_attest_real_vector.py).

## Consensus rule (gated: `DEVICE_ATTEST_HEIGHT`)

From the gate height (`transaction_ops.verify_register_device`, called from the register branch):
- EVERY register tx — entry or renewal — must carry a valid `device` attestation over the anchor-bound
  challenge, or it is invalid. Presence (a recert within the lease) therefore implies attestation, and
  the dividend weight derivation needs no new state.
- Identities registered before the gate keep their lease until it expires; their next renewal must attest.
- Same-credential binding across renewals (`cid`) is phase 2: phase 1 accepts any genuine device per
  renewal, so a user who changes phones is never locked out.

## Wallet

`navigator.credentials.create({publicKey: {challenge, rp, user, pubKeyCredParams: [ES256, RS256],
authenticatorSelection: {residentKey: "discouraged", userVerification: "preferred"}, attestation: "direct"}})`
at every registration/renewal — no attachment restriction, so the browser offers the platform
authenticator (phone secure element, Windows Hello TPM) or a plugged-in security key. One tap per lease
(36 h). The setup step attests right after the key is stored, the Mining page shows what the device
proved, Settings keeps a preview that talks to `/device_attest_probe`.

## What the reroll retires (operator decision 2026-09-07: "remove any other redundant measures")

Every one of these existed to make identities expensive without a device proof; with one, they are
redundant, and each is a barrier or a cap on honest newcomers:

- the sequential-work registration proof (PoSW) and its difficulty machinery (flood multiplier, entry
  multiplier, the 14-day baseline): the attestation challenge already binds the anchor block;
- the per-IP entry budget and the per-IP identity cap at ingress (`allow_registration`, `allow_identity`):
  identities now cost devices, not IPs, and IP keys penalise CGNAT households;
- probation (no dividend before the first timely renewal): it existed against mint-and-discard identities,
  which now each cost a device tap;
- the generation-24 gate constants (`POSW_ENTRY_COUNT_HEIGHT`, `DIV_CARRY_METER_EPOCH`) — gate hygiene.

Kept: the fidelity ramp (a continuity reward, not a Sybil brake), the lease itself, the lane split.

## Account state

Nothing is written to the account: from the gate every register tx is attested, so "present at epoch E"
(a recert within the lease, from the recert history) already implies "attested", and the epoch weight
derivation stays replayable from the recert index alone. The wallet shows the attestation from the tx.

## Phases

0. (this commit) Design; wallet "Verify device" capture; relay `/device_attest_probe` that parses the
   statement and logs fmt / AAGUID / chain subjects, so real phone samples exist before anything is
   gated. No consensus change.
1. (shipped, gate at 0) `native/attest` kernel with pinned roots (apple + android-key, ECDSA P-256 and
   RSA links, Apple nonce, Android key description + security levels), `device` field validation behind
   `DEVICE_ATTEST_HEIGHT` at the anchor block's timestamp, wallet attaches the attestation to every
   registration where a platform authenticator exists, fleet updater builds the crate.
2. Renewal re-attestation over the beacon challenge (reachability), device class in /mining_status
   and the network panel ("phones", not "miners").

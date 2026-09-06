# Device attestation — a registered identity is a real phone

Status: DESIGN + phase 0 (2026-09-07). Operator decision: the open lane keeps free entry, no capital
gate, and Sybil resistance must not be automatable. Every per-identity rule so far (sequential work,
probation, per-IP budgets, the ingress identity cap) is linear in identity count, so a farm pays it
1,000 times the same way 1,000 phones would. Measured 2026-09-06: ~1,000 of 1,191 registered identities
belong to two or three operators running browser farms on Linux/Windows servers.

The one thing a server cannot fake is a genuine phone's secure element. Both mobile platforms expose it
to a web page through WebAuthn *attestation*: the phone creates a non-exportable key in hardware and
returns a statement, signed inside the secure element, that chains to the platform vendor's attestation
root. A cloud VM, a desktop browser, an emulator, or a software authenticator cannot produce that chain.

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

`protocol.DEVICE_ATTEST_ROOTS` pins the DER bytes and SHA-256 fingerprints of the accepted roots:

- Apple WebAuthn Root CA (attestation format `apple`)
- Google Hardware Attestation Root(s) (attestation format `android-key`)

A chain is valid only if it ends at a pinned root; roots are never fetched, never learned from a peer,
and change only through a gated protocol commit. Revocation lists are not consulted at validation time
(non-deterministic); a compromised intermediate is handled the same way as a root change, by a gate.

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

`verify_attestation(att, cdj, challenge, roots) -> (ok, fmt, aaguid, model_hint, cred_pubkey_hash)`:

1. Parse CBOR; `fmt` in the accepted set; authData flags: user-present, attested-credential-data present.
2. `rpIdHash` matches the accepted RP ids; `clientDataJSON.challenge` == expected challenge.
3. Verify the attestation signature over `authData || sha256(clientDataJSON)` with the leaf certificate.
4. Walk `x5c` to a pinned root: signatures, validity windows against the block timestamp, basic
   constraints. Apple: the nonce extension (1.2.840.113635.100.8.2) must equal
   `sha256(authData || sha256(cdj))`. Android: the key-description extension
   (1.3.6.1.4.1.11129.2.1.17) must carry the challenge, `attestationSecurityLevel` and
   `keymasterSecurityLevel` = TrustedEnvironment or StrongBox, and `origin` = GENERATED.
5. AAGUID / security level returned in the verdict (informational — nothing is written to the account).

Pure Rust (`p256`, `x509-parser`, `ciborium`), no network, deterministic, bound through ctypes like
`nado_pq_native`. Every node verifies the same bytes against the same pinned roots.

## Consensus rule (gated: `DEVICE_ATTEST_HEIGHT`)

From the gate height (`transaction_ops.verify_register_device`, called from the register branch):
- EVERY register tx — entry or renewal — must carry a valid `device` attestation over the anchor-bound
  challenge, or it is invalid. Presence (a recert within the lease) therefore implies attestation, and
  the dividend weight derivation needs no new state.
- Identities registered before the gate keep their lease until it expires; their next renewal must attest.
- Same-credential binding across renewals (`cid`) is phase 2: phase 1 accepts any genuine device per
  renewal, so a user who changes phones is never locked out.

## Wallet

`navigator.credentials.create({publicKey: {challenge, rp, user, pubKeyCredParams: [ES256],
authenticatorSelection: {authenticatorAttachment: "platform", residentKey: "discouraged"},
attestation: "direct"}})` at registration; `navigator.credentials.get` with the beacon challenge at
renewal. One tap per lease (36 h). Desktop browsers with a platform authenticator (TPM, Touch ID on a
Mac) are rejected by AAGUID/format unless the operator decides otherwise.

## Sequential work (PoSW) after the gate

Once every register tx binds the anchor block through the attestation challenge, the sequential-work
proof's remaining role is a weak spam brake that a phone pays in ~1 s and a farm in CPU. It is retired
at the reroll that activates the gate (the entry/renewal difficulty machinery with it); until then it
stays, so nodes on either side of the gate validate the same transactions.

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

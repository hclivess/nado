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
- DOES NOT prove one identity per device: a rooted phone can create many credentials. What it changes is
  the unit of cost: identities need physical genuine phones that stay online, not browser tabs.
  A 1,000-identity farm needs racks of phones (~$30-50 each) plus automation that survives vendor
  integrity checks. That is the strongest decentralized barrier available without a central issuer.
- Uniqueness per device is deliberately NOT exposed by the vendors (privacy). Per-device capacity is
  bounded instead by the existing sequential work per lease and the tap-gated signature (WebAuthn
  requires user activation for every signature, so silent bulk signing is not possible in a browser).

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
  "cid": <base64 credentialId>
}
```

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
5. AAGUID (Apple) / device model fields (Android) recorded on the account as `device_class`.

Pure Rust (`p256`, `x509-parser`, `ciborium`), no network, deterministic, bound through ctypes like
`nado_pq_native`. Every node verifies the same bytes against the same pinned roots.

## Consensus rule (gated: `DEVICE_ATTEST_HEIGHT`)

From the gate height:
- an ENTRY registration without a valid `device` is rejected;
- a RENEWAL must carry a fresh attestation signed by the SAME credential (`cid` matches the account's
  stored credential hash) over the new challenge;
- `dividend_weight` is 0 for an identity whose account carries no `device_class` (existing identities get
  one lease to attest; the epoch-weight derivation reads the flag from committed state, replayable);
- the open-lane draw keeps free entry for production: an unattested identity may still win blocks at
  the probation weight, so a newcomer without a supported phone can still mine — it simply earns no
  dividend, which is where 87 % of the open-lane value lives.

## Wallet

`navigator.credentials.create({publicKey: {challenge, rp, user, pubKeyCredParams: [ES256],
authenticatorSelection: {authenticatorAttachment: "platform", residentKey: "discouraged"},
attestation: "direct"}})` at registration; `navigator.credentials.get` with the beacon challenge at
renewal. One tap per lease (36 h). Desktop browsers with a platform authenticator (TPM, Touch ID on a
Mac) are rejected by AAGUID/format unless the operator decides otherwise.

## Phases

0. (this commit) Design; wallet "Verify device" capture; relay `/device_attest_probe` that parses the
   statement and logs fmt / AAGUID / chain subjects, so real phone samples exist before anything is
   gated. No consensus change.
1. `native/attest` kernel with pinned roots, `device` field validation behind `DEVICE_ATTEST_HEIGHT`,
   `device_class` on the account, dividend weight rule, wallet flow, testnet, fleet update.
2. Renewal re-attestation over the beacon challenge (reachability), device class in /mining_status
   and the network panel ("phones", not "miners").

# Apple devices: the App Attest bridge (`apple-appattest`, `apple-assertion`) — 2026-09-07

Status: BUILT, UNVERIFIED, DISABLED ON CHAIN. Written on Linux; no Xcode, no Apple developer account, no device.
Kernel + node + wallet handoff + app source exist and are tested against synthetic vectors only. The chain refuses
both formats until `protocol.DEVICE_ATTEST_APPLE_APP_IDS` carries a real App ID and `DEVICE_ATTEST_APPLE_HEIGHT`
gates them in. Never report Apple support before a real iPhone statement verified end to end.

## Why an app

Apple passkeys return `fmt: none` (iOS 16+, macOS 13+): the web has nothing to verify. Apple's only attestation
for third parties is **App Attest** (DeviceCheck framework): the app asks the Secure Enclave for a key, Apple's
service attests it, and the attestation object chains to the **Apple App Attestation Root CA** (pinned:
`protocol_roots/apple_app_attest_root_ca.pem`, SHA-256 `1cb9823b…c932`, valid to 2045). The same key can then
sign challenges (assertions) for the life of the install.

## What the statements are

`apple-appattest` — Apple's attestation object as returned by `attestKey`, unmodified:
`{fmt: "apple-appattest", attStmt: {x5c: [credCert, caCert], receipt}, authData}`. The kernel checks, after the chain
walk to the pinned root: nonce extension `1.2.840.113635.100.8.2` == sha256(authData ‖ sha256(clientDataJSON))
(the app passes `clientDataHash = sha256(clientDataJSON)`, so this is the WebAuthn `apple` computation verbatim);
`rpIdHash` ∈ the PINNED App IDs (`<TEAMID>.com.nadochain.attest`) — never the tx's declared rp, because every
developer's app chains to the same Apple root; aaguid == `appattest` + 7×0x00 (the development environment is
refused); counter == 0; credentialId == sha256(leaf public key, X9.62 uncompressed); the COSE credential key ==
the leaf key; `clientDataJSON.type == "nado.app"` and its challenge == the chain's. No user-presence flag (there is
no gesture; Apple sets none).

`apple-assertion` — a later statement by the SAME key: `{fmt: "apple-assertion", attStmt: {sig, authData, pub}}`
where `sig`/`authData` are what `generateAssertion` returned and `pub` is the key's 65-byte point (taken from the
attestation's authData at first use). Kernel: rpIdHash ∈ App IDs, type `nado.app`, challenge match, ECDSA-P256 over
nonce = sha256(authData ‖ sha256(cdj)) verifies under `pub`. No chain — genuineness was proven by the attestation,
and consensus requires the key's `devbind` row to exist (an assertion can only renew or rebind an attested key).

Binding key for both: `"apple-appattest:" + sha256(public key point)`. Class: PERMANENT (the key lives in the Secure
Enclave, the key id in the device-only keychain that survives app deletion; only "Erase All Content and Settings"
rotates it — the same reset class that rotates an Android or TPM key). So an Apple identity attests once, renews
statement-free like a Ledger, and moves to another account with an assertion after one lease (cooldown as for
every permanent class). The receipt (server-to-server fraud metric) is deliberately unused: a network call cannot be
consensus.

## Delivery to the wallet

No new wallet plumbing: the app is a phone-side attester like "Attest another wallet or node". The wallet's
*Attest with the NADO app* button (hidden until `APPLE_APP_LIVE` in interface.js) puts the wallet in remote mode
and shows `nadoattest://attest?addr=<address>&relay=<relay>`; the app computes the chain's challenge from the relay
(tip + 30, anchor = target − 150, blake2b of `[chain_id, address, anchor_hash, target]` — `Blake2b.swift`,
`Envelope.swift`), makes the statement, and `POST /node_attest_drop`s it; the wallet picks it up and registers.
A node is attested the same way (paste the node's address).

## The app (`apps/nado-attest-ios`)

SwiftUI, ~400 lines: `Config.swift` (chain constants — must track protocol.py), `Blake2b.swift` (RFC 7693),
`Envelope.swift` (challenge, clientDataJSON, CBOR wrap/unwrap), `Relay.swift`, `AttestService.swift`
(DCAppAttestService + keychain, one key per device), `ContentView.swift`, `NadoAttestApp.swift`, entitlements and
Info additions. README.md has the Xcode steps. What only a Mac with a paid team can do: sign, run on a device,
TestFlight/App Store. What the chain needs back: the App ID string, then a gated commit.

## Open questions until the first real sample

- Whether Apple's production authData carries the COSE key and trailing extensions exactly as documented (the
  kernel's `parse_auth_data` takes everything after credentialId as the COSE key; ciborium reads one item and
  ignores trailing bytes, so the documented `extensions` dictionary is tolerated — to be confirmed).
- Whether `attestKey` may be called twice for one key (the app never does; assertions cover every later statement).
- Jailbroken devices: App Attest still answers; only Apple's server-side receipt flags them, and it is unused.

# NADO Attest — the Apple device bridge (iPhone, iPad, Mac)

Apple passkeys carry no attestation, so an Apple device cannot vouch through a web page. This app does it
natively: Apple's **App Attest** service attests a Secure-Enclave key (`apple-appattest`) and that key later signs
fresh chain challenges (`apple-assertion`). The statement travels to the wallet through the relay exactly like
"Attest from another device" — the app is a phone-side attester, it holds no coins and no account key.

Design: `doc/apple-app-attest.md`. Kernel: `native/attest/src/formats/apple_appattest.rs`, `apple_assertion.rs`.
Consensus: `protocol.DEVICE_ATTEST_APPLE_APP_IDS`, `DEVICE_ATTEST_APPLE_HEIGHT`.

## Status (2026-09-07)

UNVERIFIED. Written on Linux without Xcode, an Apple developer account or a device. The kernel and node side are
tested against synthetic vectors only. The chain refuses both formats until a real team signs the app and a
gated commit pins its App ID (`DEVICE_ATTEST_APPLE_APP_IDS`) and sets `DEVICE_ATTEST_APPLE_HEIGHT`. Never claim
Apple support until a real iPhone statement has verified end to end (the 2026-09-07 lesson).

## What you need (all on a Mac)

1. Xcode 15+ and an Apple Developer Program membership (the team's 10-character **Team ID**).
2. In Xcode: File → New → Project → iOS App, product name `NadoAttest`, bundle identifier `com.nadochain.attest`,
   SwiftUI, Swift. Delete the generated `ContentView.swift` and `NadoAttestApp.swift`; add every file from
   `NadoAttest/` to the target.
3. Signing & Capabilities: your team; add the **App Attest** capability (this writes the entitlement in
   `NadoAttest.entitlements`, keep `production` for the environment).
4. Info: add the URL scheme `nadoattest` (`Info.plist` snippet in `Info-additions.plist`), and the
   `NSAppTransportSecurity` exception ONLY if you point it at a plain-http relay while testing.
5. The App ID is `<TEAMID>.com.nadochain.attest`. Send that string to the chain maintainer: it goes into
   `protocol.DEVICE_ATTEST_APPLE_APP_IDS` and the formats are enabled at a height gate. Until then every statement
   the app produces is refused ("not enabled on this chain yet").
6. TestFlight or App Store distribution; App Attest works on real devices only (not the simulator).
7. Mac: the same source builds as a Mac Catalyst / "Designed for iPad" app; App Attest is available on macOS 14+.

## How it works

1. The wallet (Safari on the phone, or any wallet on Linux/Mac) presses *Attest with the NADO app* — it goes into
   "attest from another device" mode and shows `nadoattest://attest?addr=<address>&relay=<relay url>`.
2. The app (opened by that link, or with the address pasted) asks the relay for the tip, targets `tip + 30`,
   fetches the anchor block (`target − 150`) and computes the chain's challenge
   `blake2b([chain_id, address, anchor_hash, target])` — the same bytes every node recomputes.
3. `clientDataJSON = {"type":"nado.app","challenge":<base64url>,"origin":<App ID>}`;
   `clientDataHash = sha256(clientDataJSON)`.
4. First time on this device: `DCAppAttestService.generateKey()` → key id stored in the keychain
   (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`, survives app reinstall) → `attestKey(keyId, clientDataHash)`
   → the attestation object (already CBOR `fmt: apple-appattest`).
   Later: `generateAssertion(keyId, clientDataHash)` → wrapped as `{fmt: "apple-assertion", attStmt: {sig, authData,
   pub}}` where `pub` is the key's X9.62 point, taken from the attestation's authData at first use.
5. `POST <relay>/node_attest_drop {sender, max_block, device: {att, cdj, rp: <App ID>}}`. The wallet picks the
   drop up and registers with it; the phone's App Attest key is the device bound (for life; rebind after one lease).

## One key per device

The app keeps exactly one App Attest key: it never offers a "new key" button, the key id lives in the device-only
keychain (which iOS keeps across app deletion), and only an app signed by the pinned team can produce a valid
`rpIdHash`. A new key therefore needs "Erase All Content and Settings" — the same class of reset that rotates an
Android or TPM key. Jailbroken devices: App Attest still runs; Apple's server-side fraud receipt is the only
signal about them and it is deliberately NOT used (a network call cannot be consensus).

## Release checklist (the parts only a Mac + a paid team can do)

1. **Enroll**: developer.apple.com/programs → Apple Developer Program (US$99/year, 1–2 days for approval).
   Note the 10-character **Team ID** (Membership details).
2. **Generate the project** on the Mac: `brew install xcodegen && cd apps/nado-attest-ios && xcodegen generate`,
   open `NadoAttest.xcodeproj`, Signing & Capabilities → your team. App Attest and the URL scheme are already in
   the spec (`project.yml`); the icon and the privacy manifest are in place; export compliance is answered
   (`ITSAppUsesNonExemptEncryption = NO`, only Apple CryptoKit + TLS).
3. **First real statement**: run on a physical iPhone (App Attest does not exist in the simulator), paste any
   wallet address, press Attest. The app POSTs the statement to the relay's `/device_attest_probe`, which keeps
   the sample; the maintainer verifies it against the kernel from there. Send the App ID string
   (`<TEAMID>.com.nadochain.attest`) at the same time.
4. **Enable on chain** (maintainer): pin the App ID in `protocol.DEVICE_ATTEST_APPLE_APP_IDS`, set
   `DEVICE_ATTEST_APPLE_HEIGHT` a few hundred blocks ahead, flip `APPLE_APP_LIVE` in the wallet, fleet wave.
5. **TestFlight**: Product → Archive → Distribute → App Store Connect → TestFlight. Internal testers need no
   review; external testers need Apple's beta review (a day or two).
6. **App Store**: App Store Connect → new app, category Utilities, privacy "Data Not Collected", screenshots
   from the phone, description below, submit for review.

Suggested store description: "NADO Attest lets an iPhone, iPad or Mac vouch for a NADO mining identity. Apple's
App Attest proves the device is genuine; the app sends that proof to your wallet through the NADO network. It holds
no coins and no keys to your account — one device, one identity."

## iPad without a Mac: Swift Playgrounds

`NadoAttest.swiftpm` (generated by `make_playground.py`, committed) opens in **Swift Playgrounds 4** on an iPad:
clone the repo with the Working Copy app (or AirDrop the folder), open `apps/nado-attest-ios/NadoAttest.swiftpm`,
press Run, paste an address, press Attest. The log line answers a question nobody can answer from Linux:

- "attested this device's key" + "relay parsed it: fmt apple-appattest" → App Attest worked WITHOUT the paid
  entitlement, the relay now holds the first real sample, and the maintainer verifies it from there;
- "App Attest is not available on this device" → the capability really is provisioning-gated, and the paid
  membership + Xcode path is the only one.

With a paid developer account signed into Playgrounds, the same project can be uploaded to App Store Connect from
the iPad (Playgrounds → app settings → upload), though the App Attest capability still has to be enabled for the
App ID in the developer portal.

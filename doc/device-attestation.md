# PoSEA — Proof of Secure Element Attestation (pronounced "posee"): a registered identity is a real device

Status: DESIGN + phase 0 (2026-09-07). Operator decision: the open lane keeps free entry, no capital
gate, and Sybil resistance must not be automatable. Every per-identity rule so far (sequential work,
probation, per-IP budgets, the ingress identity cap) is linear in identity count, so a farm pays it
1,000 times the same way 1,000 phones would. Measured 2026-09-06: ~1,000 of 1,191 registered identities
belong to two or three operators running browser farms on Linux/Windows servers.

The one thing a server cannot fake is genuine hardware's secure element. Four device classes expose it
to a web page through WebAuthn *attestation* — the device creates a non-exportable key in hardware and
returns a statement, signed inside that hardware, that chains to a vendor attestation root:

| class | statement format | hardware | pinned root(s) | one identity per device? |
|---|---|---|---|---|
| Android phone | `android-key` | TEE / StrongBox (locked bootloader) | Google Hardware Attestation roots, Key Attestation CA1 | YES on remotely-provisioned devices (Android 12+): x5c[1] is a per-device attestation certificate (≈2-week validity, see below) |
| Windows PC | `tpm` | a physical TPM 2.0 (Windows Hello) | Microsoft TPM Root Certificate Authority 2014 | YES: the AIK certificate is per (TPM, Windows account) |
| Linux / any PC / iPhone | `packed` | a FIDO2 security key with full attestation (USB, NFC) | that authenticator's own root from the FIDO metadata snapshot | NO: FIDO privacy rules issue one batch certificate per ≥100k units |
| iPhone / iPad / Mac | `apple` | Secure Enclave | Apple WebAuthn Root CA | the format is pinned but **passkeys return no attestation** (`fmt: none`, iOS 16+ / macOS 13+), so Apple devices cannot attest through a web page today — confirmed live 2026-09-07. An iPhone mines with a FIDO2 key (NFC/Lightning/USB-C); a native App Attest bridge is the only way to make the phone itself count |

A cloud VM, a desktop browser without hardware, an emulator, a software authenticator, a virtual TPM or a
rooted/unlocked phone cannot produce a valid chain.

**What "one identity per device" can and cannot mean.** Vendors expose no device serial (privacy), so the only
per-device handle is what the chain itself carries: on Android with remote key provisioning the attestation key
certificate `x5c[1]` (subject `O=TEE, CN=<device id>`, issued by `Droid CA3`, ~13-day validity in the live
sample) is unique to the device and reused for every credential it creates until it rotates; on Windows the AIK
certificate is unique to (TPM, account). Apple gives nothing (and gives no attestation at all through passkeys);
FIDO2 keys give a batch certificate shared by ≥100k units. So "no double attestation" is enforceable at the lease
scale for Android-RKP and TPM — bind the device certificate hash to the sender for POSW_LEASE_EPOCHS — and NOT
enforceable for FIDO2 keys or batch-attested (pre-RKP) Android, where the only limit is one physical touch per
identity per lease. That policy line (which classes are accepted at all) is the operator's decision.

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
  which now each cost a device tap. The dividend curve is therefore ONE clean line over every fidelity level,
  `min(fidelity, 30)`: the first lease pays weight 1, no level is skipped, and the open-lane draw weight is the
  plain 2..10 floor+bonus curve from the first lease (`protocol.dividend_weight`, `mining_ops.open_shares`;
  pinned by tests/test_sybil_rules.py and tests/test_dividend_rules.py);
- the generation-24 gate constants (`POSW_ENTRY_COUNT_HEIGHT`, `DIV_CARRY_METER_EPOCH`) — gate hygiene.

Kept: the fidelity ramp (a continuity reward, not a Sybil brake), the bond unlock delay, the lease itself,
the lane split.

## Account state

Nothing is written to the account: from the gate every register tx is attested, so "present at epoch E"
(a recert within the lease, from the recert history) already implies "attested", and the epoch weight
derivation stays replayable from the recert index alone. The wallet shows the attestation from the tx.

## One device, one identity (`DEVICE_BIND_HEIGHT`, 2026-09-07)

The point of attestation: "using one device to attest 100,000 wallets must be impossible". A tap alone does not
give that — on a genuine, unrooted Android `adb input tap` automates the tap. The device CERTIFICATE does:

- `ops/device_attest.device_binding_key(device)` → `android-key:sha256(x5c[1])` (the device's remotely-provisioned
  attestation-key certificate; a certificate valid longer than `DEVICE_BIND_MAX_CERT_SECS` = 90 days is a shared
  batch certificate and the statement is REFUSED) or `tpm:sha256(x5c[0])` (the AIK certificate). `packed`, `apple`
  and anything else are refused: they carry no per-device certificate, so the property cannot be enforced for them.
- Consensus table `devbind` (kv_ops): key → (address, recert epoch). Written by `apply_register` from the gate,
  journaled in `devbind_revert` and restored exactly on rollback; snapshot-carried and in the state root.
- Rule (`transaction_ops`, register branch, after the kernel verdict, at the block's own height): if the key is
  bound to a DIFFERENT sender and `epoch < bound_epoch + POSW_LEASE_EPOCHS`, the tx is invalid — "this device already
  vouches for another identity until epoch N". The same sender renews freely; after the lease the device may move.
- Gate hygiene: `DEVICE_BIND_HEIGHT` is a height ahead of the fleet's adoption on the live betanet-7 chain
  (registrations below it carry no binding and replay unchanged); it becomes 1 at the next reroll.
- `DEVICE_BIND_STRICT_HEIGHT` (review 2026-09-07, two confirmed holes): the kernel's CBOR keeps the FIRST of
  duplicate map keys and the consensus Python parser kept the LAST, so one statement could verify as chain A and
  bind as chain B — from this height the consensus parser refuses duplicate keys (`cbor_decode(strict=True)`, used
  identically by validation and apply). And because the binding is checked against parent state, N senders could
  bind one device inside one block — from this height a register tx also occupies the in-block uniqueness key
  `("devbind", key)` (`reserved_uniqueness_keys`, consumed by assembly and verification alike; the gate is the tx's
  `max_block`, which is the landing height of a register). Both become 1 at the next reroll.

What this bounds: one Android device (per ~2-week certificate rotation, which is far longer than a lease) or one
Windows account on one TPM holds ONE open-lane identity at a time. Tests: tests/test_device_binding.py (real
Android chain binds on x5c[1]; batch/packed/apple refused; apply/revert symmetry; the rule's arithmetic).

## Hardware wallets: `trezor` and `ledger` (2026-09-07)

A hardware wallet's FIDO2 mode is refused (batch certificate), but both vendors also expose a PER-DEVICE key
certified at the factory through their own genuineness protocol — exactly what one-device-one-identity binds. The
wallet speaks those protocols directly from the browser (`static/hwattest.js`, Chrome / Edge / Brave on a
computer) and packs the result into the same `{att, cdj, rp}` envelope: a CBOR attestationObject with `fmt`
`trezor` or `ledger`, `clientDataJSON.type = "nado.hw"`, the usual anchor-bound challenge. The hardware wallet
vouches for the wallet address; it never holds the NADO key.

| | Trezor Safe 3 / 5 / 7 | Ledger Nano S / S Plus / X, Stax, Flex |
|---|---|---|
| transport | WebUSB, protocol v1 (`?##` framing) | WebHID, channel 0x0101 / tag 0x05 |
| protocol | `AuthenticateDevice{challenge}` → `AuthenticityProof` (trezorlib.authentication) | secure-channel genuineness handshake (ledgerblue.checkGenuine): E0 04 / 50 / 51 / 52 |
| what is signed | `compact_size(19) ‖ "AuthenticateDevice:" ‖ compact_size(32) ‖ challenge`, ECDSA P-256/SHA-256 by the secure element's per-device key | cert0: issuer over `0x02 ‖ header ‖ devicePub`; cert1: device key over `0x12 ‖ deviceNonce ‖ hostNonce ‖ ephemeralPub`, secp256k1/SHA-256, with `hostNonce = challenge[0..8]` |
| chain / root | X.509 device cert (CN `<model> <serial>`, serialNumber) → Trezor CA → signed by a bare P-256 ROOT KEY per model, pinned in `DEVICE_ATTEST_TREZOR_ROOTS` | device key certified by Ledger's ISSUER key, pinned in `DEVICE_ATTEST_LEDGER_ISSUER_KEYS` |
| the tap | the device asks for confirmation on screen | the device asks to allow the "unsafe manager" (our self-signed host certificate) |
| binding key | `trezor:sha256(device certificate)` | `ledger:sha256(device public key)` |
| refused | Trezor One / Model T (no secure element: no chain, kernel refuses the CN) | firmware without secure channel v2 |

Kernel: `formats/trezor.rs`, `formats/ledger.rs`; the vendor keys travel in the roots blob as tagged entries
(`0x01‖SEC1` P-256, `0x02‖SEC1` secp256k1) and certificate walks skip them. Consensus (`verify_register_device`):
a `trezor` root must be one of the pinned keys of the model the certificate names; a `ledger` root must be the
pinned issuer. Tests: tests/test_device_attest_hw.py (synthetic devices with negatives for every check). The
first REAL statements from a Nano S and a Safe are captured through the wallet pre-flight (`/device_attest_probe`)
and become vectors before either is called supported.

## Attesting a node (`ops/node_attest`, 2026-09-07)

A headless node has no secure element and nobody to tap, so from gen 25 it never auto-registers; a node with no
bond earned nothing. Its OPERATOR attests it instead, at the same price every miner pays: one tap per lease.

Why the statement travels through a relay: WebAuthn runs only on an HTTPS page, a fresh node has no TLS, so the
phone can neither open the node's wallet nor post to it (mixed content). The challenge binds only (chain id,
sender, anchor block hash, max_block) — nothing node-specific — so the wallet on ANY HTTPS relay attests for the
node's address and drops the statement there:

1. Wallet, Mining page, *Attest a node you run*: paste the node's address; the wallet picks `max_block = tip +
   margin`, fetches the anchor block, calls `attestDevice(nodeAddress, anchorHash, maxBlock)` (the same function
   and challenge derivation as its own registration) and `POST /node_attest_drop {sender, max_block, device}`.
2. Relay: shape-checks and keeps the drop in memory until `max_block` passes the tip (bounded, rate-limited),
   forwards it ONE hop to its peers (`hop: 1` is never re-forwarded).
3. Node (peer loop, every 20 s, only while it wants a lease — no lease, or `FIDELITY_MIN_GAP_EPOCHS` since the
   last recert): `GET /node_attest_pickup?sender=<own address>` on its peers, then `construct_register_tx(keydict,
   max_block, device=...)`, signs, merges through the normal mempool validation (kernel included) and gossips.
   `GET /node_attest_status` shows the lease state and whether a drop is waiting.

Nobody else can use a drop: the register tx must be signed by the sender's key, and the attestation is bound to
that sender, anchor and max_block. A stranger dropping a valid statement for someone else's node only spends
their own device's lease on that node's behalf. The node's own registrations land in the identity log with ip `self`.

The same path serves ANY wallet without a bindable device of its own (Linux, Mac, iPhone): the wallet sets
`attestVia = "remote"`, the poll loop reads `/node_attest_pickup?sender=<own address>` on its relay, and the first
statement whose `max_block` is still ahead is wrapped in the wallet's own signed register tx and submitted through the
kept-tx path. The attesting device is the one bound (`devbind`), so it still holds one identity per lease; the wallet
that receives the statement is the sender the kernel verified the challenge for.

## Binding modes: leased and permanent (`DEVICE_BIND_PERMANENT_HEIGHT`, 2026-09-07)

Operator decision (2026-09-07): a hardware wallet attests ONCE and stays bound; a phone or a TPM keeps renewing
with a statement; the wallet shows which of the two it is before the tap; a permanently bound device can be moved
to another account without the old account's key.

### Why two modes

The binding key is only as durable as the certificate behind it, and that differs per class:

| class | binding key | the key changes when |
|---|---|---|
| `ledger` | sha256(factory device public key) | never — provisioned in the secure element at the factory |
| `trezor` | sha256(per-device certificate) | never — issued at the factory |
| `tpm` | sha256(AIK certificate) | a new Windows account is created, or the TPM is cleared |
| `android-key` | sha256(remotely-provisioned attestation certificate) | the OS rotates it (≈ 2 weeks in the live sample, ≤ 90 days by rule), or a factory reset |

A binding that outlives its key is worthless: after every rotation the same phone looks like a new device and
could bind a fresh identity while the old binding still stands. That is why the leased classes must
RE-ATTEST: a lease shorter than the fastest rotation means one device holds at most one identity at any moment,
and the renewal statement is the proof that the same key is still the one bound. For a factory-fixed key the
lease adds nothing — the device cannot become another device — so it binds once, for life.

`DEVICE_BIND_PERMANENT_CLASSES = {ledger, trezor}`; every other bindable class is leased. Height-gated
(`DEVICE_BIND_PERMANENT_HEIGHT`) on the live chain; becomes 1 at the next reroll.

### Consensus state

- `devbind` rows gain a third element: `[address, epoch, mode]`, `mode ∈ {"lease", "perm"}`. Rows written before
  the gate are two elements and decode as `lease`. `epoch` is the epoch of the LAST STATEMENT that bound the
  device — statement-free renewals never touch it (see rebinding).
- The account doc of a permanently bound identity carries `devkey` (the device key string). It is the reverse
  index a statement-free renewal needs (given the sender, which row must point back at it) and is consensus
  state like every other account field: deterministic, in the root, snapshot-carried.
- `devbind_revert` records grow to `[key, prev_address, prev_epoch, prev_mode, prev_sender_devkey]`; legacy
  three-element records decode with `prev_mode = lease`, `prev_sender_devkey = None`. Rollback restores the row
  (or deletes it) AND the sender's `devkey` (or deletes it) — the exact inverse, as always.

### The register rule from the gate

A `register` tx is one of two shapes:

1. **With a statement** (`device` present) — verified by the kernel as before, then bound:
   - leased class: the existing rule (a different sender is refused while `epoch_now < bound_epoch + POSW_LEASE_EPOCHS`).
   - permanent class: the same cooldown rule decides whether the device may MOVE (below), and on success the
     row is written with `mode = perm` and the sender's `devkey` is set. An identity that already has a live
     permanent device (its `devkey` row points back at it) is refused a SECOND permanent device: one hardware
     wallet per identity; a replaced or lost hardware wallet means a new account (or the old device rebinding).
   - the in-block uniqueness key `("devbind", key)` is occupied as before.
2. **Without a statement** (`device` absent) — accepted ONLY when the sender's account has `devkey` and
   `devbind[devkey] == (sender, *, perm)`. This is the hardware identity's presence renewal: it records the
   recert, moves the lease and earns fidelity exactly like a statement renewal, and writes NOTHING to `devbind`.
   The wallet signs it with the account key alone — no cable, no tap; the mining loop sends it while the page
   is open. Before the gate, or for any other sender, a statement-free register is invalid ("Missing device
   attestation").

### Rebinding: instant, by eviction (`DEVICE_REBIND_INSTANT_HEIGHT`, 2026-09-07 evening)

A rebind is shape 1 from a NEW sender with a statement from an already-bound device. It needs no signature from the
old account — a lost key, a sold Ledger and a wallet migration all look the same to the chain. From
`DEVICE_REBIND_INSTANT_HEIGHT` it is legal in ANY block, because the move EVICTS the identity the device leaves:

- apply writes an eviction row for the old address (`devbind` key `evict:<address>`, a list of
  `[evict_epoch, voided_recert_epoch]`) naming the recert epoch it voids; the row is consensus state in the existing
  `devbind` DB (no new DB, so pre-gate roots are untouched) and is journaled/restored on rollback like every write;
- presence, in BOTH readers — `get_open_registry` (live) and `dividend_ops.present_at_epoch` (the epoch-weight
  reconstruction a fraud proof replays) — requires a recert strictly newer than the newest voided one at or before the
  epoch being computed. The evicted identity is out of the producer draw and out of the epoch's weights from the block
  of the move, and back the moment it registers again (with any device).
- so at every instant exactly one identity is backed by the device; hopping A→B→C earns nothing — each hop kills the
  previous identity and the new one starts at fidelity 1. Whoever holds the device wins immediately: a borrowed Ledger
  evicts its owner's wallet the moment it is rebound. The device is the identity.

Before the gate the old rule stands and replays unchanged: a different sender was refused for `POSW_LEASE_EPOCHS`
after the device's last statement (the "cooldown"), because without eviction a move left the old lease running.
Leased classes (phone, TPM) get the same instant move: their old identity is evicted the same way.

### Wallet and node

- `/get_account` returns `devbind: {mode, cls, live}` next to `devkey`, so the wallet knows before any prompt
  whether this identity renews for free. The identity card shows the mode as its own line ("Bound for life to
  this Ledger" / "Leased — renews every 36 h with a statement from this phone").
- A wallet whose identity is live-permanent renews without opening any prompt (automatic and manual path alike).
- Before submitting a hardware statement the wallet asks the relay (`POST /devbind_lookup {att}`) what the
  device currently vouches for; if it is another account it says so and asks for an explicit confirmation
  ("this Ledger vouches for another account — rebind it here? The other account stops mining"), or reports the
  cooldown end when the device moved less than a lease ago.
- A node attested by a hardware wallet (the drop path) becomes permanent too: the operator attests once; the
  node's poller renews statement-free while its `devbind` row is live. `/node_attest_status` reports `bind_mode`.
- The identity log records `bind: lease|perm|renew` per register so the audit tool can tell the three apart.

### What this does NOT change

Presence semantics (the 36 h lease, `FIDELITY_MIN_GAP_EPOCHS`, `dividend_weight = min(fidelity, 30)`), the
open-lane draw, the one-register-per-epoch rule, the strict CBOR parse and the in-block uniqueness key. A
permanent identity that stops renewing lapses like any other; the binding stays, so when it returns it renews
without a statement.

## Savings-lane cap per attested device (`BOND_DEVICE_CAP_HEIGHT`, 2026-09-07)

Operator decision: "cap the PoS acceleration at 1,000 NADO per attested device; if savings-lane nodes are online, one
attestation should be enough for them (has to be a unique device)."

The old bond cap (1,000 NADO per KEY, removed 2026-08-25) never bound a whale — a second key restored linear weight.
A cap per DEVICE is different in kind: the device is the one thing a farm cannot mint, and `devbind` already holds
one identity per device. So from `BOND_DEVICE_CAP_HEIGHT` the bonded PRODUCER draw runs over
`mining_ops.bonded_producer_registry`:

- an identity is in it only while ATTESTED — present in the open registry as of the same parent state, i.e. it holds
  a live device lease (every lease is a statement, or a statement-free renewal of a permanent binding);
- its stake counts at most `BOND_DEVICE_CAP` (1,000 NADO → 100 shares at `B_MIN`);
- unattested stake weighs ZERO in the draw. Anything softer is dodged by splitting keys.
- LIVENESS: if no attested bonded identity exists at all, the draw falls back to the whole registry, uncapped —
  the same rule as the tenure ramp's fallback. The cap protects an attested set; it must never stall a bonded slot.

**The curve (`BOND_WEIGHT_CURVE_HEIGHT`, 2026-09-08, chosen by simulation).** The cliff `min(stake, 1,000)` became a knee
and a bounded tail: knee = max(1,000 NADO, 5 % of the OTHER attested devices' stake) — a device's own stake never lifts
its own knee — and above it weight = K·(1.5 − 0.5·K/stake), continuous with slope 1 at the knee, saturating at 1.5·K.
Simulated with the chain's own draw over the live lane plus a single 50,000 NADO device, the same split over 20
devices, a 40-phone farm and a 100-device lane: caps relative to the lane's TOTAL let a whale lift its own cap (53 % of
blocks), median-relative caps handed the farm 60 %, the hybrid holds the single whale at ~24 %, keeps the farm at its
stake share, moves the honest lane by ~2 points, and at scale holds the biggest device to ~7 % of blocks while 85 % of
stake still counts. Pools are no longer bounded by 1,000: a pool's `max` is its operator's choice (up to
`POOL_MAX_TOTAL`), its weight is the curve of own + delegated stake, so a full pool pays each delegator less per coin
and capital spreads to emptier pools by itself. `/mining_status` reports `my_bonded_effective` and `bond_knee`.

What it does NOT touch: `total_bonded_shares` (fork-choice weight), the FFG/settlement quorum and the duty committee
stay uncapped and attestation-free — finality never depends on how many devices exist. The tenure ramp applies on top
of the capped shares. `/mining_status` mirrors the draw (`bond_cap_active`, `bonded_producing`, `my_bonded_raw`,
`bond_device_cap`), and the wallet's Mining page says whether the stake counts.

Consequence at the gate on betanet-7: every bonded identity without an open-lane lease (the relay fleet included)
stops being drawn for bonded slots until its operator attests it (Mining → *Attest another wallet or node*; a Ledger
or Trezor does it once for life, a phone or TPM every 36 h). With a hardware wallet: bond, attest once, and the node
keeps producing on its own with up to 1,000 NADO counting.

## Apple devices

Not an accepted class (decision 2026-09-07). Passkeys carry no attestation. Apple's App Attest bridge was built,
verified end to end against a real iPad statement (a Swift Playgrounds build — Apple attests without a paid team) and
withdrawn the same evening: its statement carries no per-device certificate (one CA for every iPhone), so one-key-per-
device would rest on app code, and a jailbroken checkm8-class iPhone would farm identities the chain cannot see. No block
ever carried one; everything was removed from the tree (git history: `apps/nado-attest-ios`, `doc/apple-app-attest.md`).
Apple users mine via a hardware wallet on a Mac, or attest from another device.

## Staking pools (`POOL_HEIGHT`, 2026-09-07 night)

Operator decision after the Mac complaints ("no way to continue mining"): capital without a device may RENT a device.
A holder points their bonded stake at an attested identity; the pool produces with own + delegated stake under the
same per-device cap, and the chain splits every win at apply. Nothing about the Sybil surface changes — every unit of
producing weight still sits on one real attested device with the 1,000 NADO cap; a whale still needs one device per
1,000 NADO, only now it may be someone else's, for a fee, and that trade-off was accepted knowingly.

- **Transactions** (fee-exempt, zero amount, one per sender per block): `pool` — the sender's terms
  `{fee_bps 0..10000, open 0|1, min >= B_MIN, max <= BOND_DEVICE_CAP, label <= 32 ASCII}`; `delegate {to}` — the sender's
  stake produces through `to` (must be an open pool with bonded stake, not itself delegating, with room under `max`
  and fewer than 100 members; the sender must hold >= `min`); `undelegate`. A delegator cannot run a pool.
- **Closing**: `pool {close: 1}` removes the terms and releases every delegator (their `pool_to` cleared) in that block,
  journaled and reverted exactly; the operator's own stake keeps producing alone. Terms change with another `pool` tx.
- **State**: schemaless account fields — the pool's `pool_fee_bps/pool_open/pool_min/pool_max/pool_label/pool_members`
  (sorted list), the delegator's `pool_to`. Consensus (in the root); every change journals its exact previous values
  by txid in the node-local `pool_revert` DB and rollback restores them.
- **Registry**: `bonded_pool_map` reads `bonded` and `pool_to` from the account bytes in one pass; each entry carries
  `pooled` (stake delegated into it). `total_bonded_shares` (fork weight, FFG) keeps reading each account's OWN
  `bonded` — pooling moves producer weight only. `bonded_producer_registry`: a delegator has no weight of its own; a
  pool weighs `min(own + pooled, BOND_DEVICE_CAP)`, attested only, as before.
- **Reward**: when a pool wins a bonded block, `reward_ops._pool_split` pays the delegators
  `producer_cut * pooled // total` minus the pool's fee, pro rata by stake in sorted-address order (deterministic
  rounding), IN THAT BLOCK; the pool keeps its own share + fee + dust. The split is journaled per height and reverted
  integer-for-integer. Below the gate, or with nothing delegated, the whole cut is the producer's (byte-identical).
- **Wallet**: the Stake card's "Staking pools" panel — my status, the picker (open, attested pools, cheapest first, room,
  member count), Delegate / Undelegate, and "Run a pool" with fee, name, min, max, open. `GET /pools` lists them.

## Lanes per device, dividend per device (`OPEN_LANE_EXCLUDE_BONDED_HEIGHT`, 2026-09-08)

Operator decisions: (1) "exclude >10 NADO miners from the free lane" — an attested identity with `bonded >= B_MIN` is
not drawn for OPEN slots from the gate (`mining_ops.open_lane_draw_registry`); it produces in the bonded lane. Per
device, so no second free-lane wallet without a second device. The attested set (`get_open_registry`) is unchanged and
still gates the bonded producer cap and statement-free renewals; the registry entries carry `bonded` for the draw
filter. (2) "the dividend remains clickable", "available for everyone" — the presence dividend's membership, accrual
and claim are untouched: every attested device is weighted by fidelity. (3) "improve the gradient" —
`dividend_weight = min(fidelity, 15)` from `DIVIDEND_WEIGHT_CAP_V2_EPOCH` (30 before), gated inside the one function
both the live commit and the fraud-proof replay call.

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

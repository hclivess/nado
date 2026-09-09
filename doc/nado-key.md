# NADO Key — a NADO-issued attestation device

Status: **design, feasibility proved, no hardware ordered, no consensus code written.**
Decision owner: operator. This file records what a NADO-issued device would be, what it costs us in trust, and the
exact change surface — so the decision is made on numbers, not on enthusiasm.

## What it is

A small USB device that speaks **WebAuthn**, containing one key pair generated on the device at the provisioning line
and never leaving it, plus an **attestation certificate for that unit** signed by a NADO root we hold offline. Its
only job is to answer "yes, a distinct physical NADO Key participated in this registration". It holds no coins, signs
no transactions, and knows nothing about a wallet. The user's spending key stays where it is today.

This is the same shape as a Ledger or Trezor as far as the chain is concerned — a per-device certificate under a
pinned root — except the root is ours.

## Why it is worth considering

Today the open lane needs a *real phone* (Android with remote key provisioning), a *physical TPM* (Windows Hello), or
a *hardware wallet* (Ledger, Trezor). That excludes: every Apple user without a hardware wallet, every Linux desktop,
every older Android, and anyone who owns no phone they will attest with. Commercial FIDO2 keys are accepted for
attestation but **cannot bind** (see below), so they do not open the lane. A NADO-issued device closes that gap with
a device we can price at cost.

## The kernel needs no change — proved

`native/attest/src/formats/packed.rs` already verifies exactly what such a device would emit. A synthetic NADO root +
per-device leaf + `packed` statement, run through `ops.attest_native.verify()` unmodified:

```
ok: true   fmt: packed   aaguid: 4e41444f4b4559…
chain: [ C=CZ, O=NADO, OU=Authenticator Attestation, CN=NADO Key 000000001
         C=CZ, O=NADO, CN=NADO Device Root CA ]
root_sha256: 54e6c5d6…d344      == sha256(our root DER), so it pins like any vendor root
```

The kernel already rejects a CA leaf, requires X.509 v3 and `OU=Authenticator Attestation`, and checks the AAGUID
extension (`1.3.6.1.4.1.45724.1.1.4`) against authData. Nothing in Rust moves.
(Spike: scratchpad `nadokey_spike.py`, `nadokey_bind.py`.)

## The one thing that makes it safe: bind the CERTIFICATE, not the credential

A WebAuthn credential is fresh per registration. Binding on it would let one dongle print unlimited identities — the
exact Sybil failure that [[sybil-per-identity-rules-are-linear]] cost us. Binding on the per-device leaf does not:

```
identity-A: ok  credential=88cf7132…  bind=nado:f0abfbd72a243fa8…
identity-B: ok  credential=f81a1bbd…  bind=nado:f0abfbd72a243fa8…   <- same handle
```

Two registrations, two credentials, **one** binding handle, so `devbind` refuses the second identity. This is why
`packed` is refused for binding today (`DEVICE_BIND_CLASSES`): a commercial FIDO2 key ships a *batch* certificate
shared by up to 100k units, so its leaf identifies a model, not a unit. Ours identifies a unit — because we write it.

That property is not a protocol guarantee, it is a **manufacturing** guarantee. If the provisioning line ever flashes
the same key to two units, the chain cannot tell. See "what we owe" below.

## Change surface (all Python, all gated)

1. `protocol.py`: `DEVICE_ATTEST_NADO_AAGUID` (one per hardware model) + `DEVICE_ATTEST_NADO_ROOTS` (sha256 of the
   root DER) + `NADO_KEY_HEIGHT` gate + a lane-share cap constant.
2. `ops/transaction_ops.py`, the `packed` branch: if the AAGUID is ours, the chain must end at *our* root; and our
   root must be refused for any other AAGUID (so vendor A's key cannot claim our AAGUID, and ours cannot claim theirs).
3. `ops/device_attest.py` `device_binding_key()`: a `packed` branch returning `"nado:" + sha256(x5c[0])`, **only** when
   both the AAGUID and the root are ours; every other `packed` statement keeps today's refusal verbatim.

Leased, not permanent: `DEVICE_BIND_PERMANENT_CLASSES` stays `{ledger, trezor}` until the device has a field history.

## Copying a certificate does NOT create an identity — it takes one

Worth stating plainly because it corrects the obvious intuition. Copies of one certificate all hash to the same
binding handle (`sha256(leaf DER)`), so the second registration is refused, in a later block or the same one
(`DEVICE_BIND_STRICT_HEIGHT`). A cloned certificate is never a second identity.

**So hardware does not lower the identity ceiling.** The ceiling is the number of certificates we sign — the same
whether the key lives in a secure element, in a Pico's flash, or in a file. Anyone reasoning that silicon caps the
supply has it backwards: issuance discipline caps the supply, and silicon is irrelevant to it.

What a copy DOES buy, since `DEVICE_REBIND_INSTANT_HEIGHT` (live from block 5400): the copier registers a fresh
address, presents the certificate, and the legitimate holder is EVICTED in that block — lease voided, out of the open
registry and the epoch weights at once (`ops/account_ops.py`, `instant and prev_bind[0] != address`). The victim can
re-register and evict the thief straight back, and the thief can re-register again. Neither can hold it; the thief can
automate it and the owner cannot, and `fidelity_step`'s anti-farm spacing means the owner's rapid recerts renew the
lease but earn no fidelity. A copied certificate is a hostage, not a duplicate.

That splits the security argument in two, and only one half is about hardware:

- **The network** is protected by the issuance log and the lane-share cap below. Identical for files, Picos and secure
  elements. Hardware contributes nothing.
- **The holder** is protected by unextractability, and that is the ONLY thing the silicon buys. Malware sweeps keyfiles
  off disk at scale; it cannot sweep a secure element. At ~4.8 NADO/day per permit, a keyfile format is worth writing
  malware for.

So the question is not "is a certificate file cryptographically sufficient" — it is. The question is whether we are
willing to sell an identity that malware can take from its owner.

## What the hash actually counts

Uniqueness IS enforced mathematically: the chain hashes the device certificate and refuses a second identity for the
same handle, provably, with no trust involved. What the math does not check is the CORRESPONDENCE — the hash counts
**certificates**, and counts **devices** only under an assumption nobody verifies. Two ways that comes apart, both
invisible to hashing, which is doing its job perfectly in each:

- **One certificate, two devices** — the line flashes the same key into two units. Chain sees one identity, two exist.
- **One certificate, zero devices** — a leaf signed over a keypair in a file on a server, no stick ever built. Chain
  sees a perfectly distinct hash.

Proof of work is the real counterexample to "physics cannot be verified by math": energy burned is a physical fact
checkable by arithmetic alone, with no authority anywhere. A certificate is not that. Work leaves **evidence**; a chip
leaves **testimony** — an unforgeable, exactly-countable signed statement that a distinct device exists. Cryptography
makes the statement tamper-proof and the counting exact; it cannot make the statement true.

So there is no protocol fix here and we should stop looking for one. Everything that improves the situation happens at
issuance or at manufacturing — the public issuance log, and the chip.

## Why the chip choice is not just about price

A **PUF** (physically unclonable function) derives the key from transistor variation during fabrication. It is not
stored on the die and does not exist while the device is unpowered. Nobody chooses it, the factory included, so the
factory cannot clone a unit even if it wanted to. That shrinks the testimony from "I put a distinct key in each unit"
to "I enrolled N chips" — and the issuance log can audit exactly that number.

| tier | uniqueness comes from | factory can clone | key extractable |
|---|---|---|---|
| certificate file | our signature | yes | trivially, remotely at scale |
| Pico (RP2040/RP2350) | on-board RNG written to flash | yes | yes, with the stick in hand |
| LPC55S69 (SRAM PUF) | fabrication variation | **no** | no |

The RP2040 has no PUF, which is the honest reason it is a prototype and not a product. The LPC55S69 (the class of part
in open-source keys such as the Nitrokey 3 line, optionally alongside an SE050) does. That is the argument for spending
more than four dollars, and it is a better one than unit economics.

## Prior art: does anything reach past a central issuer?

Asked because the decentralized-identity literature reads as though it does. It largely answers a different question.

- **DIDs / verifiable credentials / EAS / web-of-trust** decentralize *whose word you take* — the verifier picks the
  attestors instead of inheriting a root store. Genuine progress, and irrelevant to us: all of them are free to mint.
  Anyone can create a million DIDs or write a million attestations. They inherit scarcity from whichever issuer was
  trusted; the problem moves rather than dissolving.
- **ZK identity** changes what is REVEALED, not who attests — a proof of "I hold a valid passport" still verifies a
  passport authority's signature inside the circuit. A privacy technology, often mismarketed as a decentralization one.
- **TLSNotary / zkTLS** is the cleverest of them and still roots in the target site's TLS certificate, i.e. a CA. It
  reuses an authority rather than removing one.
- **PGP web of trust** is the cautionary case: trust is not transitive, revocation was never solved, and it placed no
  bound on identity count at all.

Authority-free Sybil resistance has three known shapes: burn something scarce (work or stake — NADO already uses stake
for the savings lane), a synchronized human ceremony (Idena; genuinely authority-free, paid for in brutal UX), or
pluralism — many independent attestors, so no one of them can inflate supply.

**We are already the pluralist design**: Apple, Google, Microsoft, Trezor, Ledger and the FIDO MDS snapshot, six roots,
none of which we control. That frames the strongest argument against this whole project. A NADO Key does not remove
pluralism — every existing option stays — but it adds **the one root with a financial interest in over-issuing**. Every
other root we pin belongs to a company that gains nothing from printing NADO identities. We would be the exception,
which is precisely what the issuance log and the lane cap exist to contain, and why neither is optional.

Worth noting where the best-funded attempt landed: World ID's orb is a custom device with per-device attestation keys
and the foundation is the CA — the same design, arrived at independently.

**The reachable improvement is not removing the issuer, it is hiding it.** Today the chain stores sha256(leaf) in the
clear, a stable public handle per device. A ZK nullifier scheme would let a device prove "I am a distinct member of an
attested set" and emit a nullifier enforcing one-identity-per-device WITHOUT revealing which device. It keeps all six
roots, needs no new authority, adds no centralization, and we already run STARKs. That is a better use of the same
effort than a dongle.

## Provisioning: how a certificate actually reaches a device

The certificate is NOT in the firmware image. It is uploaded to the device over USB after flashing, which means one
firmware image for the whole run and a per-unit certificate — no per-unit build. Verified by reading the pico-fido
source, not from documentation (the README does not cover attestation at all).

Per unit at the bench:

1. Flash `pico_fido.uf2` once — hold BOOTSEL while plugging in, drop the file on the USB volume that appears. The
   same image on every unit.
2. On first boot the device generates its OWN key from its own entropy and self-signs a placeholder certificate
   (`src/fido/fido.c:427-453`). The private key never leaves the chip.
3. Read that public key back out of the self-signed certificate over CTAP.
4. Our offline root signs a NADO leaf over it: `OU=Authenticator Attestation`, `CN=NADO Key <serial>`, AAGUID
   extension `1.3.6.1.4.1.45724.1.1.4`. The root key lives on an HSM and never touches the bench machine.
5. Push the DER back with the vendor config command `CTAP_CONFIG_EA_UPLOAD` (`0x0002a674c29a8dcf`,
   `src/fido/cbor_config.c:230`). It lands in `EF_EE_DEV_EA`, the End-Entity Enterprise Attestation Certificate.
6. Append serial + leaf fingerprint to the public issuance log.

Steps 3-6 are a script. Note that step 2 is the good part: we never generate or hold anyone's device key, we only
sign a certificate over a public key the device made for itself.

Two things this procedure is NOT. **The certificate needs no secure storage** — it is public. What must never leave
the device is the private key, and the device generates that itself (step 2), so the certificate's requirement is
integrity, not secrecy: load another unit's NADO certificate onto your device and your key will not match the public
key inside it, so the signature fails at our kernel. It self-defends. And **`CTAP_CONFIG_EA_UPLOAD` is not portable** —
that 64-bit magic constant is a command pico-fido invented, not standard CTAP. Standard CTAP 2.1 `authenticatorConfig`
offers only small-integer subcommands (`enableEnterpriseAttestation`, `toggleAlwaysUv`, `setMinPINLength`) and NONE of
them uploads a certificate; the standard assumes the factory did it. So this exact procedure works on pico-fido and
nowhere else: a Nitrokey 3 runs Trussed (Rust) and ships signed with secure boot, so we can neither call such a command
nor flash a build that adds one. That is why "custom attestation / per-organization identity" is on their paid
Enterprise list — it buys factory provisioning, not an upload.

Note also what putting our certificate on someone else's hardware does and does not buy: it outsources MANUFACTURING,
never TRUST. We remain the sole witness for that device class, the one root with a financial interest in over-issuing,
and the issuance log and lane cap remain mandatory.

### Firmware changes we would have to make

Three, in our own fork (the community edition is AGPLv3, so the fork gets published — fine for us):

- `src/fido/cbor.c:35` — the AAGUID is a compile-time constant, currently the first 16 bytes of SHA256("Pico FIDO2").
  Ours replaces it.
- `src/fido/cbor_make_credential.c:787` — the uploaded certificate is emitted ONLY when `enterpriseAttestation == 2`,
  and Chrome gates `attestation: "enterprise"` behind enterprise policy, so a public website cannot request it. The
  usable path is the known-app table (`src/fido/known_apps.c`, `use_self_attestation = pfalse` keyed on the RP-ID
  hash) — but that path currently emits the device's SELF-SIGNED certificate. One-line change to select
  `EF_EE_DEV_EA` there too.
- Same block: `x5c` is encoded as a ONE-element array, leaf only. Our validation reads the root as
  `sha256(x5c[-1])`, so with a single certificate the "root" is the leaf and nothing pins. Emit leaf + NADO root.

### Three things that will bite

- **A factory reset destroys the identity permanently.** `src/fido/cbor_reset.c` clears `EF_KEY_DEV` AND
  `EF_EE_DEV_EA`. The device key is gone, so the same certificate can never be reissued: the binding handle is dead
  and the user's identity with it. This needs a loud warning in the wallet, not a footnote.
- **The upload is PIN-protected** (`pinUvAuthParam` required), so provisioning sets a PIN. Changing the PIN later is
  safe; only a reset kills the certificate.
- **No secure element on RP2040/RP2350.** Flash is readable; a thief holding the stick extracts the key, and under
  `DEVICE_REBIND_INSTANT_HEIGHT` that is an instant takeover of the identity.

Licensing: the primitive we need is in the AGPL source, so a prototype costs nothing. But the project explicitly sells
"custom attestation / per-organization identity ... anti-cloning / unique device identity for OEM and fleet use" as a
paid Enterprise component, so a production fleet is a commercial conversation, not just a fork.

## Neighbours: Worldcoin, Idena, and what we are not

Worth writing down because "isn't this just Worldcoin" is the first question anyone will ask.

**We count devices. They count humans.** That single difference produces almost every other one:

| | World ID | NADO |
|---|---|---|
| unit of scarcity | one human | one attested device |
| how uniqueness is established | iris biometric, deduped against a global database | certificate hash compared on chain |
| personal data collected | biometric template | none |
| who holds the device | the project and its operators (visit an orb) | the user |
| roots of trust | one, the foundation | six, none of which we control |
| what it is sold as | personhood, to third-party apps | nothing — it allocates our own emission |
| privacy of a proof | unlinkable, ZK nullifier (Semaphore) | a plaintext device hash on chain |

So they are not a competitor in any market sense: nobody chooses between us, and one human may legitimately hold
several NADO identities by owning several attested devices. **NADO is not proof-of-personhood and should never claim
to be.** If a marketing line ever implies it, that line is wrong.

What the comparison is genuinely worth:

- **As precedent.** The best-funded attempt at this problem independently concluded that a self-issued hardware root
  with per-device keys is the reachable design. That is reassuring about the shape of a NADO Key.
- **As a warning about biometrics, which we dodge entirely.** Spain's AEPD ordered collection stopped in March 2024
  and deletion in December 2024; Bavaria's regulator ordered outright deletion and a GDPR rebuild in December 2024;
  Kenya suspended operations in 2023 and a High Court order in May 2025 forced deletion of all Kenyan data. Every one
  of those actions is about biometric personal data. We collect none — a certificate hash is not personal data — so
  we get most of the Sybil benefit with essentially none of that regulatory surface. This is a real and underrated
  advantage of counting devices instead of people, and it argues for never drifting toward biometrics.
- **As a warning about a single root.** Their sustained criticism is that one foundation is the sole issuer. Our six
  independent roots are defensible in a way that cannot be; a NADO Key erodes that margin and nothing else about the
  project does.
- **As a hint about the privacy gap.** They already do the ZK nullifier we do not. On that specific axis their design
  is better than ours today, and it is the improvement worth copying.

**Idena** is the nearer neighbour philosophically: synchronized human ceremonies, genuinely authority-free, paying for
it in UX so demanding it caps growth. It is already cited in the README's identity-management argument for exactly
that reason — it is the honest example of what removing the issuer actually costs.

## Why a stock FIDO2 key cannot be the answer (checked, not assumed)

"Just add Nitrokey 3 support" is the obvious idea and it does not work, for a structural reason worth writing down.

A Nitrokey 3 ALREADY ATTESTS TODAY: `Nitrokey 3 AM` (aaguid 2cd2f727f6ca44da8f485c2e5da000a2) is in our pinned
`protocol_roots/fido_mds_roots.json` snapshot, along with two Solo AAGUIDs. Nothing needs adding for attestation.

What it cannot do is BIND, and that is not our choice. FIDO's privacy rules require the attestation certificate be
shared across at least 100k units, exactly so a key cannot be tracked between websites — so its leaf names a MODEL,
never a unit. `device_binding_key()` therefore refuses `packed`, correctly.

Adding `packed` to `DEVICE_BIND_CLASSES` would not create unlimited identities; it would cause the INVERSE failure.
Every Nitrokey 3 on earth hashes to ONE binding handle: the first Nitrokey holder on the network takes the single
identity, every other one is refused, and under `DEVICE_REBIND_INSTANT_HEIGHT` they evict each other in perpetuity.

**A PUF does not fix this.** The LPC55S69's SRAM PUF makes the device key unextractable; it says nothing about whether
the certificate over that key is unique. A Nitrokey 3's key genuinely IS one-per-unit — the uniqueness exists in the
silicon, it is simply NOT WITNESSED. Someone has to sign a statement naming that specific unit, and no FIDO2 vendor
will, by design. A witness is a CA. That is the whole reason this document exists.

So the four classes that bind today are precisely the ones whose per-device certificate is witnessed by somebody who
is not us — Android with remote key provisioning, a physical Windows TPM, Ledger, Trezor. That IS the "without our own
CA" answer, and it is already shipped. A Nitrokey 3 adds nothing over a Trezor Safe 3 unless we sign the certificates,
at which point we are the CA and every cost in this document applies again.

## What we owe the network if we do this

NADO would be the first attestation vendor that also holds the coin. Two guardrails are non-negotiable and ship in the
same commit as the gate, not later:

- **A consensus cap on this device class's share of the open lane.** If we over-issue, by accident or on purpose, the
  chain limits the damage without a governance vote. Per-key rules are void ([[per-key-rules-are-void]]); this is a
  lane-level dial, which is the kind that works.
- **A public append-only issuance log** — every serial and leaf fingerprint we sign, published as issued, so anyone can
  compare the number of NADO-Key identities on chain against the number of units we admit to having made. Without it,
  "we did not print ourselves 10,000 identities" is a claim nobody can check.

An offline root, an HSM at the provisioning line, and per-unit key generation *on* the device are the minimum
manufacturing bar. If we cannot meet that bar, we should not issue: a device class we sign badly is worse than one we
never shipped, because it is indistinguishable on chain from the honest one.

## What you would actually buy

**To prove it end to end: one Raspberry Pi Pico, about $4.**

`pico-fido` (github.com/polhenarejos/pico-fido) is open-source FIDO2 firmware for the RP2040 / RP2350. It is the
only readily available stack that lets the operator issue the attestation certificate: edit `attestation-cert.conf`,
the build generates the certificate into `src/cert.c`, and `cert-master-key.pem` is the root. The AAGUID is set in
firmware. Flash it, plug it in, and it emits a `packed` statement signed by our own certificate — the same bytes the
spike faked. Total spend to find out whether this works against the live chain: one board and an afternoon.

RP2040/RP2350 has **no secure element**: the device key lives in flash and comes out with physical access. Demo only.

**To ship units: an OEM order, not a shopping cart.**

No vendor sells a stick with a customer's attestation certificate off the shelf. Token2 ships its RP2350 key with
attestation disabled precisely because it cannot hand over the attestation private key; provisioning a certificate is
a manufacturing act. The realistic route is an OEM conversation with a maker of open-source keys with a secure
element (Nitrokey 3 uses an NXP SE050, Common Criteria EAL 6+) to flash our certificate per unit. Their terms are not
public — that is a call to make, not a number to look up.

**What we do NOT need:** FIDO Alliance certification or MDS listing. Ordinary vendors must publish their roots to the
MDS or attestation fails everywhere; we pin our own root in `protocol.py`. No membership, no certification, no fee.

**The expensive part is not the board.** Every unit needs its OWN leaf certificate. One firmware image flashed onto a
hundred sticks gives a hundred sticks one leaf, the chain collapses them to a single identity, and the product is
worthless. Per-unit key generation on the device plus per-unit signing from an offline root IS the provisioning line,
and it is where the cost and the trust both sit.

**Do NOT buy an LPC55S69-EVK.** Checked 2026-09-10 because it looks like the obvious way to get the PUF chip. It is
an evaluation board for chip bring-up — 222 g, four USB ports, microSD, Pmod, mikroBUS, two 3.5 mm jacks — not a
dongle, and `pico-fido` cannot run on it: the build targets the Pico SDK (RP2040/RP2350) or ESP32 and has no NXP/LPC
support at all, so every step of the provisioning section above is RP2040-specific. FIDO2 on an LPC55S69 means a
different codebase entirely (Trussed / nitrokey-3-firmware, Rust). At TME it was 1246.70 CZK (~EUR 50), zero in stock,
19 weeks manufacturer lead.

**And do not buy a Nitrokey 3 to experiment with either.** It is the right chip in the right form factor, but there is
no experiment it enables: it already attests to our chain (it is in the MDS snapshot), it structurally cannot bind, and
we cannot put our own certificate on it — no standard CTAP command uploads one and its firmware is signed with secure
boot. It is a SUPPLIER, not a purchase: relevant only after a commercial agreement in which their factory does the
provisioning, at which point the order is a batch. Nothing about it is testable by buying a single unit.

**The alternative that costs nothing.** A Trezor Safe 3 is around EUR 79, is already a permanent bind class, and
covers the same Apple and Linux users a NADO Key would. The only argument for our own device is beating that price at
volume. If a NADO Key lands anywhere near EUR 79, it should not be built.

## Open questions before hardware money is spent

- Unit cost at a realistic run, against the ~4.8 NADO/day a permit currently earns — the device must not be a
  better investment than the thing it attests for.
- Who runs the provisioning line, and what happens to the root if that relationship ends.
- Whether an off-the-shelf FIDO2 board with our own firmware and certificate is enough, or whether it needs a secure
  element. Without a secure element the per-device key is extractable, and one extracted key is one stolen identity
  (not N — the chain checks uniqueness — but still a theft).

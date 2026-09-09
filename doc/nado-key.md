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

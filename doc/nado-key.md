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

## Open questions before hardware money is spent

- Unit cost at a realistic run, against the ~4.8 NADO/day a permit currently earns — the device must not be a
  better investment than the thing it attests for.
- Who runs the provisioning line, and what happens to the root if that relationship ends.
- Whether an off-the-shelf FIDO2 board with our own firmware and certificate is enough, or whether it needs a secure
  element. Without a secure element the per-device key is extractable, and one extracted key is one stolen identity
  (not N — the chain checks uniqueness — but still a theft).

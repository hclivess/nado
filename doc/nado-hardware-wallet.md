# NADO hardware wallet — design note

Status: **design only. Nothing built, no code, no hardware ordered.**
Companion to `doc/nado-key.md`, which covers the attestation token. This is a different project with a different
threat model: that device proves a distinct machine exists, this one holds money.

## Why this is newly interesting

Because there is no hardware wallet for NADO at all. Ledger and Trezor are **attestation** classes here
(`DEVICE_BIND_PERMANENT_CLASSES`) — they prove a distinct device to open the open lane, and neither holds NADO or signs
a NADO transaction. So the honest baseline is not "a Trezor". It is **a key in a browser**, and often a `keys.dat` on
disk (`ops/key_ops.py`).

That reverses the usual reasoning about secure elements. A secure element defends against **physical** theft. A browser
keyfile's weakness is **remote** theft — malware sweeping key material off thousands of machines, the same
mass-harvesting objection `doc/nado-key.md` raises against certificate files, and the realistic attack. A device with no
secure element still defeats it completely: the key never exists on the PC, so there is nothing to sweep. The worst a
compromised host can do is *ask* the device to sign, and a screen plus a button is exactly what refuses.

So a ~300 CZK device would be a large improvement on what NADO users have today, while being clearly worse than a
Trezor holding Bitcoin. Both halves of that sentence are true and neither should be dropped when describing it.

## What it must actually do

NADO signs **ML-DSA-44** (FIPS 204 internal mode). Sizes: private key 2560 B, public key 1312 B, signature 2420 B — all
comfortable on the flash and USB HID of any modern microcontroller.

The signer itself is **not** the hard part. `native/mldsa44` is a thin wrapper over the RustCrypto `ml-dsa` crate, so a
device implementation is a cross-compile for `thumbv8m.main-none-eabi` (RP2350 / Cortex-M33, 520 KB SRAM) rather than an
implementation of Dilithium. Address derivation is equally cheap: `ADDRESS_PREFIX` + the first `ADDRESS_BODY` hex chars
of the public key + a 4-hex blake2b checksum (`ops/address_ops.make_address`).

### The hard part, and it is not the crypto

What gets signed is a **hash**:

```python
tx["txid"] = create_txid(tx)          # blake2b over the CANONICAL (sorted-keys) body, public_key EXCLUDED
tx["signature"] = sign(private_key, unhex(tx["txid"]))
```

A device that accepts a 32-byte digest and signs it is **blind signing**, and its screen is decoration — the host can
display one transaction and hand over the hash of another. So the device must receive the **whole transaction body**,
recompute the canonical encoding and the blake2b itself, and only then render the amount and recipient and ask for
confirmation. The signature must cover a hash the device derived, never one it was given.

That means NADO's canonical serialization has to exist, byte-exact, in C on a microcontroller. `create_txid`'s own
docstring says any encoding divergence forks txids across nodes, and this repo has already reverted a `sort_keys` change
for altering the genesis root. A second implementation of that encoder is therefore the single largest risk in this
project — larger than the signer, larger than the display, larger than the hardware.

Two consequences worth deciding early:

- The device should reject any field it does not recognise rather than sign a body containing it. Signing an unknown key
  it cannot render is the same blind-signing failure wearing a hat.
- The renderer needs a test vector suite generated from `create_txid` on the Python side, run against the firmware, for
  every transaction shape the wallet can produce — not a handful of examples.

## Combining it with attestation

Technically clean: `pico-fido` already exposes FIDO2 over USB HID, and NADO signing would be either a CTAP vendor
command or a second HID interface. The existing vault machinery (`CTAP_VENDOR_VAULT`, `EF_VAULT_KEY`) is scaffolding in
roughly the right shape. One device could hold the attestation certificate from `doc/nado-key.md` AND the spending key.

The cost is blast radius. `doc/nado-key.md` deliberately gives the attestation token no coins, so that losing the stick
loses an identity worth ~4.8 NADO/day rather than a balance. Combining them removes that separation. That is the same
trade every hardware wallet makes and it is defensible — a Ledger holds keys and attests — but it should be a decision,
not a side effect of using one board.

If combined, the recovery story must cover both: a lost device means a lost balance AND a dead binding handle, and
`doc/nado-key.md` records that a factory reset already destroys the identity permanently.

## Parts

For the combined device, all orderable, roughly 300 CZK (~EUR 12) total:

| part | why | approx |
|---|---|---|
| Raspberry Pi **Pico 2** (RP2350) | Cortex-M33 for the ML-DSA cross-compile, 520 KB SRAM, secure-boot support. NOT the original Pico: RP2040 is Cortex-M0+ with no secure boot | ~150 CZK |
| SSD1306 0.96" I2C OLED | the confirmation display, 4 wires | ~60 CZK |
| 2x tactile switch | confirm and reject as DISTINCT actions; one button forces short/long-press, which is a bad idea for money | ~5 CZK |
| breadboard + jumpers | avoids soldering while prototyping | ~80 CZK |

Buttons are not strictly required to *start*: `pico-fido` takes user presence from a button and on a bare board that is
BOOTSEL, so attestation works with nothing attached. They become necessary the moment the device signs value.

## Staged plan

1. Attestation only, no screen — that is `doc/nado-key.md`'s spike. Proves the device path end to end.
2. Add the display and the two buttons; show the RP ID and (via WebAuthn's `user.name`) the NADO address on
   registration. Still no key custody, still no funds at risk. Optional step 11 of the other doc.
3. Port `create_txid`'s canonical encoding to the firmware and build the test-vector suite against the Python
   implementation. **No signing key on the device yet.** If this step is not convincingly finished, stop here.
4. ML-DSA-44 signing with a throwaway key and dust amounts on a loopback testnet.
5. Seed backup, recovery, and a firmware-signing story. Only then does anyone else's money touch it.

## What would make this a bad idea

- **Step 3 not landing cleanly.** A renderer that can diverge from `create_txid` is worse than no device, because it
  looks like verification and is not.
- **Taking custody with no audit.** We would be handing people a wallet with no third-party review. The blast radius is
  their balance, not an identity.
- **Recovery.** Seed backup is where hardware wallets actually lose people's money, and it is a product problem rather
  than a firmware one. No secure element also means a stolen device is a drained device, so backup quality is the only
  thing standing between a lost stick and a lost balance.
- **Scope.** This is a bigger project than the attestation token and shares only the board with it.

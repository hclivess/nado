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

The complete bill of materials for the combined attestation + wallet device. Everything is off the shelf; nothing needs
a custom PCB. Roughly **525 CZK (~EUR 21)**.

| part | exact variant matters | why | approx |
|---|---|---|---|
| Raspberry Pi **Pico 2 H** (RP2350) | the **H** — headers pre-soldered. Without it you are soldering 40 pins. NOT the original Pico: RP2040 is Cortex-M0+ with no secure boot | Cortex-M33 is what makes the ML-DSA cross-compile (`thumbv8m.main-none-eabi`) sane; 520 KB SRAM; RP2350 supports secure boot | ~150 CZK |
| **SSD1306** 0.96" 128x64 OLED | the **4-pin I2C** module, not the 7-pin SPI one | the confirmation display. I2C address `0x3C` | ~60 CZK |
| **Microchip ATECC608B** breakout (Adafruit / SparkFun) | **blank / TrustCustom**, NOT `-TNGTLS` (ships locked with Microchip's own certificates). Buy **three**: the config and data zones lock PERMANENTLY, so a provisioning mistake bricks one | holds the P-256 **attestation** key: `GenKey` generates the pair inside the chip and the private half is unreadable even by our firmware. Cannot hold the ML-DSA spending key — see below. I2C address `0x60` | ~200 CZK for 3 |
| 2x **tactile switch** | any 6 mm through-hole part | confirm and reject as DISTINCT actions. One button forces short/long-press, a bad idea for money | ~5 CZK |
| **breadboard + jumper wires** | 400-point board, male-male jumpers | no soldering while prototyping | ~80 CZK |
| **micro-USB cable** | micro-USB B — the Pico 2 did NOT move to USB-C | power, flashing, and the CTAP/HID link to the browser | ~30 CZK |
| **Qwiic / STEMMA QT to male-jumper cable** | JST SH 4-pin to 4 male pins | only if the ATECC breakout uses a Qwiic/STEMMA QT connector: the Pico has no such socket, and this avoids soldering headers to the board's 0.1" pads | ~60 CZK |

**ATECC608B package trap.** The order code has two independent parts and only one of them is the variant. `…DA…`
is what you want — TrustCustom, blank and customer-configurable, as opposed to `-TNGTLS`. But the package code decides
whether you can physically use it: `ATECC608B-MAHDA-S` is **UDFN-8**, a 2 x 3 mm leadless part needing hot air and
realistically a stencil, which fits neither a breadboard nor a 2.54 mm perfboard, and unlike SOIC has no cheap DIP
adapter. Use either a ready **breakout module** (Adafruit #4314, SparkFun's Cryptographic Co-processor — that one carries
the older ATECC608**A**, functionally identical for `GenKey` + P-256 `Sign`) for zero soldering, or
**`ATECC608B-SSHDA`**, the same TrustCustom config in hand-solderable **SOIC-8**, with a ~20 CZK SOIC-8 to DIP-8 adapter.

A Qwiic / STEMMA QT breakout is fine — that connector is plain I2C (3.3 V, GND, SDA, SCL) and such boards normally
carry 0.1" pads as well. **Check the lock state before wiring anything**: the config and data zones lock PERMANENTLY, and
a board that ships already locked can never take our slot configuration. Read the config zone's lock bytes over I2C —
`0x55` unlocked, `0x00` locked. Adafruit's #4314 is documented as configurable; generic clones are unknown, so buy two or
three and check on arrival. `608A` versus `608B` does not matter for `GenKey` + P-256 `Sign`.

Related trap on the prototyping board: a "prototypová univerzální deska / perfboard (2,54 mm, SMD/THT)" is bare copper
pads and must be soldered. Male jumper wires need a SOLDERLESS breadboard (the plastic one with spring contacts). Buy
both if you want a prototype now and a permanent build later.

**Wiring is trivial because both I2C devices share one bus.** The OLED (`0x3C`) and the ATECC608B (`0x60`) sit on the
same SDA/SCL pair, so the whole build is **two GPIO pins** plus power and the two buttons. No level shifters, no pull-up
resistors beyond what the breakout boards already carry, no bus conflict.

**Bring-up order**, so a failure tells you which part broke:

1. Patched firmware on a bare Pico, nothing attached — attestation works, using BOOTSEL as the user-presence button.
2. Add the OLED. Display only; still no key custody.
3. Add the ATECC608B and move the attestation key into it.
4. Only then the buttons and the signing path.

Buttons are not required to *start*: `pico-fido` takes user presence from a button and on a bare board that is BOOTSEL.
They become necessary the moment the device signs value.

## Secure elements: what one can and cannot hold

Checked 2026-09-10, because "add a secure element" sounds like it should close the extractable-key hole and only half
does.

First, a category error worth avoiding: **an STM32 is not a secure element.** It is a microcontroller family, the same
category as the RP2350. Some variants carry TrustZone and secure boot, which is not a certified tamper-resistant chip.
Changing MCU buys nothing. A secure element is a SEPARATE chip, and it attaches to a Pico 2 over I2C with four wires,
sharing the bus with the display — no board redesign.

Then the part that matters: **the mainstream secure elements cannot hold a NADO key.** Microchip ATECC608B (~EUR 2),
Infineon OPTIGA Trust M and NXP SE05x (the Nitrokey part) are ECC/RSA only. None implements ML-DSA. So:

- **For the attestation token** (`doc/nado-key.md`), a secure element works properly. WebAuthn `packed` signs with
  ES256, which is exactly P-256 ECDSA, so a ~EUR 2 ATECC608B can hold the attestation key such that it never leaves the
  chip. That removes most of the "RP2040 flash is dumpable" objection for two euros, and is the cheapest real
  improvement available anywhere in these two documents.
- **For the spending key**, the best available is **key wrapping**: the secure element holds an AES secret, flash holds
  the ML-DSA private key encrypted, and plaintext exists only in RAM for the duration of a signature. Dumping flash
  yields ciphertext. Better than nothing, weaker than a key that never leaves the chip.

Accepting the weaker property is defensible here, because the threat this device exists to defeat is REMOTE key theft,
and that is already defeated completely by the key not living on the PC. The secure element would be defending against
physical possession, which is the rarer attack.

**PQ silicon is arriving and is too early to build on.** SEALSQ's QS7001 claims to be the first secure chip embedding
ML-KEM and ML-DSA in hardware, explicitly aimed at cryptocurrency wallets, with a QVault TPM variant announced for
H1 2026; STMicroelectronics has announced a secure chip with ML-KEM/ML-DSA hardware acceleration, certification targeted
July 2026. Neither has an open toolchain or unrestricted small-volume availability. Worth re-checking before any board
is committed — "no secure element does ML-DSA" is true today and has a shelf life.

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

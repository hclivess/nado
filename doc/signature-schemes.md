# User-selectable signature schemes

Status: **built 2026-10-25, dormant on generation 28, live from block 1 on generation 29** (`SIG_SCHEMES_HEIGHT`,
inlined in G9: the rule holds from block 1). The operator asked for it on 2026-10-25: *"i would like multiple (pluggable) scheme options for NADO ...
let users pick"*. It supersedes the design in ROADMAP.md Track G (2026-08-10), which predates format-2 addresses.

## What a user gets

Every account can sign with one of these schemes, all post-quantum and all final NIST standards:

| scheme | standard | public key | signature | fee floor | why pick it |
|---|---|---|---|---|---|
| **ML-DSA-44** (default) | FIPS 204 | 1,312 B | 2,420 B | x1 | smallest, and the only scheme for mining, messaging, key rotation and multisig |
| ML-DSA-65 | FIPS 204 | 1,952 B | 3,309 B | x2 | NIST category 3 instead of 2 |
| ML-DSA-87 | FIPS 204 | 2,592 B | 4,627 B | x2 | NIST category 5 |
| SLH-DSA-SHA2-128s | FIPS 205 | 32 B | 7,856 B | x3 | hash-based: it survives a break of lattice cryptography, which ML-DSA does not |

**FN-DSA-512 (Falcon)** is built and tested (native/pqsig, id 4) but **not offered**. FIPS 206 is still a draft, and its
key encodings, message pre-hashing and domain separation may change. The operator chose on 2026-10-25 to build the plugin
now and switch it on once FIPS 206 is final. No user should hold a key in a pre-standard format.

Turning it on means three things:
1. Add `"fndsa512"` to `SIG_SCHEMES_OFFERED`. This is a consensus change, so it ships as a gated release.
2. Check `fn-dsa` against NIST's FIPS 206 test vectors.
3. Give the browser the same crate compiled to wasm. noble's `falcon.js` implements round-3 Falcon, not FN-DSA, so the
   two would not cross-verify.

In the wallet, **Main** (the account the wallet creates, which mines) is always ML-DSA-44. A scheme is chosen when an
account is added: **Account → + Add** opens a picker once the gate is live. The scheme is part of the address and cannot
change later.

## How it works

**One field, absent by default.** A transaction may carry a top-level `alg` (`protocol.TX_TOP_KEYS`):
- **Absent means ML-DSA-44**, and absence is the only way to say it. `"alg": "mldsa44"` is refused, so one transaction
  has one byte string (the rule `excluded_witness_check` exists for).
- **No existing transaction, txid or block hash changes.**
- **The txid hashes `alg`**, so the signature binds it.

**The address commits to the scheme.** Format-2 addresses (`ops/address_ops.address_body_v2`) are built two ways:
- An ML-DSA-44 key gives `blake2b([DOMAIN_ADDRESS_V2, pubkey])`, as before.
- Any other scheme gives `blake2b([DOMAIN_ADDRESS_V2, alg, pubkey])`. A three-element canonical list never encodes like a
  two-element one, so no address moves.

This binding is why no account record grows a field:
- `proof_sender(sender, key, alg)` already recomputes the address from the key, so it binds address, scheme and key in
  one check.
- A key presented under the wrong `alg` derives a different address.
- So does a later key-less transaction that names the wrong scheme: its stored key derives the sender's address only
  under the scheme it was made with.
- **There is no new state.** Nothing enters the state root, there is no revert path to write, and the carry has nothing
  to move.

**Validation order** (`ops/transaction_ops.validate_transaction`):
1. `tx_shape_check`.
2. `sig_scheme_check`, which refuses `alg` if:
   - the gate is not live;
   - the scheme is not offered, or is the default;
   - the signature is an entry list or a multisig;
   - the kind is one the chain verifies off the transaction with ML-DSA-44 only (`SIG_ML44_ONLY_RECIPIENTS`).
3. `excluded_witness_check`, now sized by the transaction's scheme (`SIG_SCHEME_SIZES`).
4. The fee floor. A paying transaction pays `MIN_TX_FEE` times the scheme's multiplier. A fee-exempt kind stays exempt:
   those are once-only claims from escrow.
5. `validate_origin`, which runs `proof_sender` and `verify` under the transaction's scheme.

**ML-DSA-44-only kinds** (`SIG_ML44_ONLY_RECIPIENTS`), refused for every other scheme. These are the transactions whose
key the chain later checks with ML-DSA-44:
- `register`, `bond` and the duty family (`duty`, `attest`, `commit`, `reveal`), because a validator signs blocks and
  status attestations;
- the TPM ceremony (`tpm_*`), which enrols a validator;
- `msgkey`, because messaging verifies through `key_authorized`;
- `auth`, because auth configs hold ML-DSA-44 keys;
- `legacy_claim`, because a format-1 address is a slice of an ML-DSA-44 key.

Multisig members are also ML-DSA-44: a member signature is checked against the member's address as an ML-DSA-44 key.
Widening any of these is a feature per surface, never a one-line change.

**The block auth leaf** (`ops/mldsa_block_auth.py`) declares the scheme in its `kind` (3 to 6). An untagged
transaction keeps kind 1, so no existing leaf, `auth_root` or block hash moves. Raw evidence verifies each signature
under its own transaction's scheme.

## Keys: one 32-byte seed for every scheme

A recovery phrase is a 32-byte seed, for every scheme. Each scheme expands it its own way
(`native/pqsig/src/lib.rs`, mirrored in `static/interface.js schemeKeygen`):

- **ML-DSA-44/65/87:** the seed is FIPS 204's ξ.
- **SLH-DSA-128s:** `(SK.seed, SK.prf, PK.seed)` = `SHAKE256("NADO/sig/slh-dsa-sha2-128s/keygen" ‖ seed)[0..48]`.
- **FN-DSA-512:** the keygen RNG is `SHAKE256("NADO/sig/fn-dsa-512/keygen" ‖ seed)`.

**Derived accounts.** A derived wallet account of another scheme takes its seed from
`blake2b([DOMAIN_HD_ACCOUNT, master, index, alg])`. So no seed serves two schemes, and an ML-DSA-44 child keeps exactly
the seed it always had. The wallet keeps the scheme of each index in `localStorage` (`nado_hd_algs`), and the key file
carries it (`hd_algs`). A user restoring from the phrase alone adds each account again with the same scheme, which the
picker tells them.

**Signing is hedged and in internal mode** (FIPS 204/205 `*_internal`, no context), the convention ML-DSA-44 already
signs in:
- ML-DSA draws its own randomness;
- SLH-DSA's `opt_rand` is 16 fresh bytes;
- FN-DSA's sampler is seeded from 32 fresh bytes.

Consensus checks `verify() == true`, never signature bytes.

## Implementations, and what checks them

| stack | ML-DSA-44 | the others |
|---|---|---|
| node | native/mldsa44 (unchanged) | **native/pqsig**: RustCrypto `ml-dsa` 0.1 and `slh-dsa` 0.1, pornin's `fn-dsa` 0.4, one C ABI keyed by id (`nado_pqsig.py`) |
| browser | noble 0.2.0 `ml_dsa44` | noble 0.2.0 `ml_dsa65`, `ml_dsa87`, `slh_dsa_sha2_128s` (+ `shake256`), in the rebuilt `static/vendor/nado-crypto.js` |

- **`Cargo.lock` must stay committed.** `slh-dsa` 0.1.0 compiles only against `signature 2.3.0-pre.4`, which the lock
  pins, and a fresh resolve takes pre.7 and fails.
- **The browser bundle must stay on noble 0.2.0.** Newer noble signs in external (context) mode, which would not verify
  on the node, so the bundle header says never to upgrade it without the interop test.
- **The bundle rebuilds byte-identically from its recipe.** This was checked before the extension.

**What checks the implementations:**
- **`signatures._scheme_selftest`**, the first time a non-default scheme is used. It checks a known-answer public-key
  digest per scheme, the FIPS 204 reference (dilithium-py) for ML-DSA-65/87, a round trip, and the five forgeries the
  ML-DSA-44 self-test rejects. A library that fails is never trusted: `verify()` returns False.
- **`tests/test_an_account_signs_with_the_scheme_its_address_commits_to.py`**: consensus under both rule sets.
- **`tests/test_every_signature_scheme_derives_one_key_in_every_stack.py`** runs the wallet's own code and checks that:
  - each scheme's key and address are identical in the browser and the node;
  - a wallet transaction validates in the node;
  - a node signature verifies in the browser;
  - the wallet refuses an ML-DSA-44-only kind;
  - the derived-account seeds are as described above.
- **`native/pqsig` `cargo test`**: round trip and forgery refusal per scheme, including verifying under the wrong scheme.

## Deployment

1. **This commit (gen 28):** everything is dormant, and `native/pqsig` is an optional crate (`ops/self_update`). Every
   node builds it on update and needs it for nothing.
2. **The gen-29 reroll commit:** `SIG_SCHEMES_HEIGHT` becomes 1 through the `else 1` branch, and that commit moves
   `native/pqsig` into `_CRATES`. After that, a node without the library would refuse a valid tagged transaction, which
   is a fork, so it must be required. Whole-fleet adoption comes before the first tagged transaction, because the reroll
   restarts every node on one commit.
3. **The user walk** (add an account of each scheme, send from it, restore it from the key file and from the phrase)
   belongs to the G7 rehearsal on the gen-29 tree, where the gate is 1. A gen-28 loopback testnet never reaches 2^62.

## Not done, deliberately

- **No scheme for the chain's own signatures** (blocks, attestations, duties). A validator stays ML-DSA-44.
- **No per-key schemes in auth configs or multisig yet.** Each needs its own shape (a key entry with an `alg`), its own
  canonical spelling in `excluded_witness_check`, and its own pop and tests.
- **No messaging or forum sign-in for other schemes.** Both verify an account key through `key_authorized`, and
  `static/messaging.js` sizes its envelope for ML-DSA-44.

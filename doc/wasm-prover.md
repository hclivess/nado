# On-device STARK prover — scope + status

> **TIER A (JS/BigInt) is DONE and LIVE.** The full prover is ported to the browser (static/stark/*.js) and
> byte-matches Python: a transfer proof generated in JS is accepted by the unchanged verifier. The "Prove on
> this device" tick uses it (window.nadoProve2) — the node never sees the witness. ~2s in node (down from ~22s, ~11x)
> via a **WASM BLAKE2b** (wasm/blake2b/, ~50x faster hashing), **Montgomery batch inversion**, **cached NTT
> twiddles**, a **cached periodic LDE**, and a **WASM Goldilocks field/NTT** (wasm/goldilocks/), and a **whole-tree WASM Merkle** (one wasm call per
> column instead of ~16k JS hashes).
>
> **The node's delegated prover is bound to the SAME Rust.** wasm/goldilocks also compiles to a native shared
> library that execnode/stark/goldilocks_native.py loads via ctypes (no new deps), so /exec/prove_transfer2
> dropped from ~20s to ~3.8s (pure-Python fallback with just batch inversion: ~6.3s). One Rust codebase
> accelerates both the in-browser (WASM) and the node (native) prover; scripts/install.sh --exec builds it.

> **Goal:** generate the shielded-pool join-split STARK **in the user's browser**, so the exec node never sees
> the witness. This is the privacy endgame — it closes the one remaining gap ("the prover sees your amounts,
> unless you run your own node"). The UI hook already exists: the *"Prove on this device"* tick calls
> `window.nadoProve` / `window.nadoProve2`; this doc is the plan to make those real.

## 1. What the prover actually computes (measured)

Per proof (2-output transfer, tree depth 12): a **512 × 16 trace** → **8192-point LDE** (16× blowup), then:
- 16 column iNTTs (size 512) + 16 coset evaluations (size 8192),
- the **composition**: 17 constraints (each with x⁷ S-boxes) evaluated at all 8192 points — the hot loop,
- FRI over 8192 (fold + Merkle-commit each layer),
- Merkle commitments of every column + CP + FRI layers, and query openings.

In CPython (C-backed bignums) this is **~17–19 s**; the proof is **~1 MB** (verified in ms, stays off-L1).

Rough op budget: ~3 M field multiplications + ~150 k BLAKE2b compressions per proof.

## 2. What must be ported — and the hard constraint

The browser proof must be accepted by the **existing, unchanged Python verifier** (`verify_transfer` →
`joinsplit2.verify_transfer`). So every byte that feeds a hash must match Python **exactly**:

| piece | status |
|---|---|
| Goldilocks field add/mul/pow | ✅ in `alghash.js` (BigInt, byte-verified) |
| round constants / IV / domain tags | ✅ `alghash.js` == Python (cross-checked) |
| BLAKE2b + canonical JSON (transcript, Merkle leaves) | ✅ `blake2bHash` byte-verified |
| **NTT/iNTT + roots of unity + coset eval** | ⏳ port |
| **Merkle over field vectors** (`merkle.py`) | ⏳ port (uses `blake2bHash`) |
| **Fiat–Shamir transcript** (`transcript.py`) | ⏳ port (uses `blake2bHash`) |
| **FRI prover** (`fri.py`) | ⏳ port |
| **STARK prover** (`stark.py`: interpolate → LDE → composition w/ periodic cols → openings) | ⏳ port |
| **circuit** (`joinsplit2` trace builder + constraints + periodic) | ⏳ port (trace builder is straight-line) |

The transcript + Merkle already match, so the risk concentrates in the NTT / composition / FRI producing the
same field values and the same proof structure (same query indices, same layer order).

## 3. Two speed tiers

**Tier A — JS/BigInt.** Reuse `alghash.js`'s field + port NTT/FRI/STARK/circuit in plain BigInt. Works on every
device, no toolchain. Estimate: **~tens of seconds to ~1–2 min on a phone** (BigInt mul overhead + ~3 M muls).
Slow, but *real* on-device privacy — acceptable behind a "proving on your device… (~Ns)" progress bar.

**Tier B — WASM field.** Goldilocks has a *special* fast reduction (p = 2⁶⁴−2³²+1), so a u64 mul + reduce is a
few ns in WASM — ~50–100× faster than BigInt. Put the field, NTT, and the composition hot loop in WASM
(Rust→wasm or AssemblyScript); keep orchestration + BLAKE2b in JS (or also WASM). Estimate: **~1–3 s/proof**.
This is the phone-grade target.

## 4. Build phases (each independently cross-checked against the Python verifier)

1. **field/NTT in JS** — `evaluate`/`interpolate`/coset-eval; cross-check vs Python vectors (round-trip + a
   known poly). *(small)*
2. **Merkle + transcript + FRI prover in JS** — produce a JS FRI proof, verify it with Python `fri.verify`.
   *(medium — the first byte-match milestone)*
3. **STARK prover in JS** — interpolate cols → LDE → composition (periodic columns) → openings; prove a simple
   AIR (Fibonacci/squaring) and verify with Python `stark.verify`. *(medium-large)*
4. **Circuit + `window.nadoProve2`** — port `joinsplit2.build_trace` + `_transitions` + `_periodic`; prove a
   real transfer in the browser and verify with the **live Python `verify_transfer`**. This is the acceptance
   test; when it passes, the tick is real. *(medium)*
5. **Tier B: WASM field** — swap the field + NTT + composition inner loops to WASM for phone speed; the proof
   is identical, so phases 1–4's cross-checks still hold. *(medium, + build toolchain)*

## 5. Risks & mitigations
- **Byte-mismatch → rejected proof.** Mitigate with a cross-check harness per phase (the pattern already used
  for `alghash.js` / `shielded.js`): prove in JS, verify in Python, assert acceptance.
- **Proof size (~1 MB) in the browser.** It's POSTed to the exec node only to *verify+apply* (ms); no L1
  blob. Fine over local HTTP; consider gzip.
- **Phone speed (Tier A).** Ship with a progress bar + let the user keep the delegated option; Tier B removes
  the pain.
- **BigInt determinism.** No `Math.random`/floats anywhere in the prover; all randomness is Fiat–Shamir.

## 6. Recommendation
Ship **Tier A first** — it makes on-device proving genuinely private on every device (slow but real), behind
the existing tick with a progress bar. Then **Tier B (WASM)** for phone-grade speed. Effort: Tier A ≈
600–800 lines of JS + cross-check harnesses (bulk of the work, concentrated risk in NTT/FRI/composition
byte-matching); Tier B adds a WASM field + toolchain. Nothing here changes the on-chain verifier or the pool —
it's purely a client-side proof generator dropping into the `window.nadoProve*` hooks.

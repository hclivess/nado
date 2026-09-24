# Security review 2026-09-24: the zero-knowledge stack

Five parallel reviews, one per trust boundary:

- the STARK core and its zero-knowledge mode;
- the zkVM circuit and the settlement binding;
- the shielded pool circuits;
- proof recursion and folding;
- the Rust and browser provers.

Every finding marked **reproduced** was run against the code. Every finding marked **read** was traced end to end
through the code without running it. Status is as of the commits that closed each finding.

Settle-with-proof was already closed on generation 25 when this review ran: the REVIEW_R2 canonical-key check refused
every honest proof over live state (the `faucet` regression, fixed the same day). `PROOF_FIXED_CID_HEIGHT`, which would
have reopened it at 225000, was moved to the reroll before it fired. The reason is below.

## Order of response

1. **`dd2865e1`:** `PROOF_FIXED_CID_HEIGHT` moved to the reroll before block 225000. Otherwise forged settle proofs
   (finding 1) would have become landable.
2. **`38eb39fd`:** `PRIVACY_PAUSE_HEIGHT = 226400`. This closes every live value path a forged or malformed privacy
   proof could reach. It went out with a deliberately vague message because the verifier flaw was still unfixed.
3. **After 226400 fired:** the verifier fixes and everything else below, gated at `PROOF_QUERY_FULL_HEIGHT = 228500`
   where a validation rule changes.

## Findings

### 1. CRITICAL, reproduced: query checks bound only half the evaluation domain, so any STARK proof could be forged

`stark.verify` opened the trace at `idx mod N/2` and compared the recomputed composition with FRI layer 0 only there.
FRI tests degree < N/2, and N/2 points always interpolate a polynomial of that degree. So a prover could:

1. commit the columns honestly;
2. take the true composition's values on the lower half;
3. interpolate them;
4. run an honest FRI on that interpolant.

Every spot-check then passed. A counter AIR "proved" its last row was 999 under all five rules then live, on the
blake2b and alghash2 backends. The same flaw sat in the native prover, the browser prover and both recursion
verifiers.

This reached settle proofs, merkle updates and the records half; shielded transfers (joinsplit / joinsplit2); and
shielded-contract notes.

**Fixed:** `PROOF_QUERY_FULL_HEIGHT` (`stark.query_pos`, `stark.fri_claim`). The trace is opened at `idx` itself,
uniform over the whole domain, and compared with whichever half `idx` lands in. The fix is mirrored in `stark_native`
and `static/stark/stark.js`. `tests/test_proof_query_full.py` shows the forgery verifying at 228499 and refused at
228500.

### 2. HIGH, reproduced: the P1 trace batch bounded columns only to deg < next_pow2(md)·T

For max_degree ≥ 3, a column of degree N/4 could make a degree-4 constraint vanish on the whole LDE coset while the
trace it denotes violates it. An AIR demanding w⁴ = 1 with w(0) = λ, where λ⁴ ≠ 1, verified. Every live circuit has
degree 7 or 8.

**Fixed:** at the same gate, each column enters the batch as x^(deg_bound − T)·f(x). FRI's bound then forces
deg f < T. This is `stark.trace_batch_shift`, the native export `sp_batch_add_shift` (the old `sp_batch_add` is
unchanged for replay), and the wallet's `stark.js`.

### 3. CRITICAL, reproduced: a shielded-contract deposit minted value

`appnote_circuit` never pinned VIN. A 1-unit `private_call` deposit committed a note worth 1,000,000 and drained the
contract's whole bridge balance. `private_call` reaches any contract, including `faucet`, whose 99.4 NADO was exposed.
The 2026-09-23 review had filed this as A5, MEDIUM.

**Fixed:** `private_call` is refused from `PRIVACY_PAUSE_HEIGHT`, and the deposit boundary `(0, VIN, 0)` is now
unconditional (`tests/test_appnote_deposit_vin.py`). Shielded contract notes stay off at the reroll until they move
to the wide hash with zero knowledge.

### 4. HIGH, reproduced: an unshield could be rewritten into a burned fee

The circuit binds only `fee − public_value`, so `(pv + k, fee + k)` verified with the same proof. Anyone reading DA
could land a rewrite first and burn a victim's exit into pool fees.

**Fixed:**

- The legacy pool is paused.
- The wide pool binds address, value and fee into the transcript (`joinsplit3.bind_aux`, `joinsplit3.js bindAux`,
  `tests/test_shielded_wide.py`).

### 5. HIGH, read: legacy field transfers lacked the round-2 capacity and duplicate-output checks

Beyond 4,096 leaves the pool silently dropped leaves, which locked funds. A payer could also create a note identical to
one the payee already held.

**Closed by the pause.** The legacy pool never held a leaf and is replaced at the reroll.

### 6. HIGH, read, reroll-gated: the wide pool's spend key was one field element and reused the legacy key

Two problems:

- Every public owner id was a 2^64 key search, and less than that multi-target.
- Every legacy proof, which is not zero-knowledge, had published the same key the wide pool would use.

**Fixed:** the key is four lanes (`znote.nsk_lanes`, joinsplit3 `NSK..NSK+3`) and is derived from its own domain
(`shield-nsk-v2`). The wallet keeps the two pools' notes apart.

### 7. CRITICAL latent, reproduced: K→1 fold forgeries

- The state-transition bundle path passed the prover's own boundaries to the fold. A swapped post root verified.
- `recursive_verify` never pinned N == blowup·T. With T=8, blowup=4, N=64, an x² chain "ended" at any value.

`SETTLE_PROOF_RECURSIVE` is **True**; several documents said off. Only the refusal under the trace low-degree rule kept
folds out of consensus.

**Fixed:** boundaries are rebuilt from public data, inner geometry is pinned (`max_degree` passed by every caller), and
io_replay's outer query count is pinned. The refusal is extended to the full-query rule, the documents are corrected,
and `SCHEDULED_CLEANUPS.md` lists what must precede lifting the refusal (`tests/test_fold_hardening.py`).

### 8. MEDIUM, reproduced: a missing or stale native kernel became a memoised "invalid" verdict

`stark.verify` and `fri.verify` swallowed `NativeMissing`. `fri.verify` also swallowed `MemoryError`, so the 2026-09-23
S5 fix was incomplete. A node mid-update could reject a block every peer accepted.

**Fixed:** `native_guard.NODE_LOCAL_ERRORS` is re-raised on every verify path, and the settle branch turns it into
`ProofUnavailable`, which defers the block instead of rejecting it.

### 9. MEDIUM/LOW, read: settle binding gaps

- `IO_ABAL` reads were unauthenticated.
- The records-frozen guard refused PAY but not the other asset io kinds.
- `_cid_io` silently dropped io beyond the last VM unit.
- Exit claims verified `amount % P`.

**Fixed:**

- From `PROOF_QUERY_FULL_HEIGHT`, no settle proof may carry asset io (none can honestly: the prover threads no asset
  state).
- `_cid_io` requires exactly one io segment per VM unit.
- Exit claims must be below 2^61 (`exit_amount_check`).

### 10. LOW

| Item | Fix |
|---|---|
| The transparent `shielded_transfer` op accepted a stark bundle it cross-wired | refused from the pause |
| `recursive_verify_hetero` had no production caller and lacked every live pin | now refuses under any live rule |
| `deep_eval` left the FRI domain and offset unpinned | pinned |
| `sp_compose` returned validation errors as positive codes that the wrapper read as column ids | now negative |
| The wallet asked the relay about the exact note it was claiming | now searches every leaf locally |

## Found while fixing (ours)

- **The L1 field-shield branch read an unbound `h`.** From `a8a720f1` every field-shield deposit raised and was
  refused, wide ones included. It is now a pure function, `field_shield_check`, judged at the block's height. A test
  pinned the old branch by source text, which is how the bug stayed green; that test now calls the function.
- **`tests/test_no_undefined_names.py` passed a production module that did not parse.** pyflakes reports syntax
  errors, and the test filtered only for undefined names. It now fails on any file pyflakes cannot parse.
- **Nine tests imported `execnode.execnode` from the live checkout.** Its state and DA paths are relative to the
  working directory, so those tests read the live stash and re-stamped the live `.gen` marker.
  `tests/test_tests_never_touch_live_exec_state.py` now pins the isolation.

## Accepted, documented

- Note randomness `rho` is one field element.
- Notes sit in plaintext in the browser's localStorage; the spend key does not.
- Settle-with-proof stays closed on generation 25. The code-binding flaw (S1, 2026-09-23) is fixed only behind the
  reroll gate, and reopening proofs before then would let a bonded settler settle a root that omits a deploy and stall
  settlement. At the reroll every fix above is live from block 1.

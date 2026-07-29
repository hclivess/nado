# alphanet-14 — release notes

**Status:** DRAFT. Numbers marked `⟨TBD⟩` are filled in from the final green run; nothing here is final
until the heavy K→1 fold has passed end-to-end and the fleet is deployed. If you are reading this and those
markers are still present, the release was not cut.

---

## What this release is

Three things that had to land together, plus the fleet fixes found while landing them.

1. **The challenge field moves to GF(p³).** Every algebraic challenge in the system — the FRI folding
   challenge, the DEEP point, the constraint alphas, the LogUp bus challenges β/γ — is now drawn from a
   degree-3 extension of Goldilocks.
2. **K→1 recursive folding is activated** (`SETTLE_PROOF_RECURSIVE = True`), so L1 verifies **one** proof
   per settlement instead of K segment proofs.
3. **Blocks commit their signature workload** (`auth_root`, `auth_count`) inside the hash preimage, which
   is the statement an aggregate signature proof has to attest and cannot choose.

This is a **clean-break reroll**: new `CHAIN_ID`, new `GENESIS_TIMESTAMP`, `CHAIN_GENERATION 15`. Nothing
from alphanet-13 carries over, and that is deliberate — items 1 and 3 both change bytes that are inside a
hash.

---

## 1. GF(p³)

### Why

FRI soundness is a **minimum** over the query phase and the commit phase. `NUM_QUERIES` buys query-phase
bits; nothing buys commit-phase bits except a bigger field. The binding term before this release was the
LogUp bus at **109 bits**, and — this is the part that mattered — it **decays one bit per doubling of the
trace**, because the bus term is `log2|F| − log2(buses × rows)`.

At degree 3 that term becomes **173 bits** and the bound passes to the query phase at **150.8**, which does
not move with trace size until ~2³⁹ rows. So the system stops getting weaker as it gets busier.

| term | GF(p²) | GF(p³) |
|---|---|---|
| LogUp / aux bus (2¹⁷ rows) | 109.0 | **173.0** |
| constraint alphas | 126.0 | 189.0 |
| query phase (udr) | 150.8 | 150.8 |
| **provable total** | **109.0** | **156.0** |

Read it yourself: `python3 -m execnode.stark.soundness`. That calculator now reads `extf.DEGREE` rather than
a hardcoded constant, so it describes the live system instead of the field it was written against.

### How

The degree lives in **one** constant (`execnode/stark/extf.py`). The previous module hardcoded degree 2 in
24 places, and the migration turned up **118 degree-2 assumptions across 16 files**. Five of them were
silent — wrong answer, no error. So every operation is written for arbitrary D, and the irreducibility of
`X³ − 3` is *checked at import* rather than asserted in a comment: a reducible modulus does not fail
loudly, it gives the ring zero divisors and makes `inv()` return plausible garbage for exactly the elements
an attacker would search for.

**Both Rust crates moved with it.** `native/starkprove` (the LDE/composition arena) and `native/alghash2`
(the hash and Merkle builds) are degree-generic, and the Python side refuses to touch the arena unless it
answers with the **same degree and the same non-residue** — two libraries can agree on the degree and still
be different fields. A degree-mismatched arena does not crash; it composes a well-formed polynomial over
the wrong field, and the only symptom is a verification failure far from the cause.

### Performance

Extension FRI layers were committing every Merkle leaf and node in Python — the base-field whole-tree builds
were native and the extension ones simply did not exist. That was the dominant cost of an extension proof
and it landed on the fold. `merkle_commit_ext` / `rmerkle_commit_ext` fixed it: **5.5×** on the sponge path,
and one in-circuit fold test went from **45+ minutes to 127 seconds**.

Prove/verify on a fixed statement at D=3: **0.208 s / 0.023 s**. The field change did not cost throughput.

---

## 2. K→1 folding

`SETTLE_PROOF_RECURSIVE` flips to `True`. It has been `False` since 2026-07-28 for a stated reason — the
in-circuit recursion AIRs were still base-field, so a folded proof carried the old ~47-bit commit bound
while the rest of the system claimed 111, making the fold the weakest link in consensus. That reason is now
gone: `fri_verify`, `comp_verify` and `rowcomp_verify` all carry extension arithmetic.

This is a **consensus rule** and rides the reroll rather than a hot toggle. A node honouring `recursive`
skips the classic per-segment check, so enabling it while unupgraded peers ignore the field would let an
attacker staple a bogus blob onto a valid settle tx and split the fleet.

⟨TBD: heavy fold timing, peak RSS, proof size⟩

---

## 3. Block authorization commitment

Every block now commits `(auth_root, auth_count)` inside its hash preimage, and every verifier recomputes
both from the block's own transactions. `auth_root` is a field-native fold over the ordered authorization
entries; `auth_count` is the exact number of signature checks the block demands.

The leaf carries **no public key**, deliberately. Under PUBKEY-ONCE a transaction may omit `public_key`, so
resolving it means reading as-of-parent account state — and the block hash would then depend on state. NADO
already enforces exactly one state-dependent header field (`state_root`) and treats a mismatch as fatal;
a second one buys nothing, because `sender` *is* the address derived from the key and `proof_sender()` ties
the two natively on every transaction.

Genesis carries the fields too, for uniformity. It costs nothing — block 0's hash is
`blake2b_hash_link(timestamp, [])` and does not cover that dict.

### What is NOT enabled

`SIG_AGG_STARK = False`, and the reason is physics rather than wiring. One ML-DSA-44 verification is **103
Keccak-f permutations**, and the sub-circuits currently take the signature as a **public** input — so an
aggregate envelope replaces the *verification arithmetic* of K signatures, not their *bytes*. Moving the
signature into the witness (so a block can actually drop it) is an AIR change, not a configuration flag.

The path is live and verified end to end, not dormant: `verify_block_authorizations` checks a real folded
bundle against a statement the **verifier** builds, and `tests/test_block_auth_wiring.py` exercises it with
a real ML-DSA keypair.

---

## Fleet fixes found along the way

**A lone forker could corroborate its own finality floor.** `_depth_floor_corroborated` asked "is the
heaviest advertised tip on our canonical chain?", and a node alone on a fork mines every slot unopposed —
so its own tip *is* the heaviest and it agreed with itself. It then advanced an *enforced, un-crossable*
floor past the fork point and could no longer roll back to rejoin, leaving only the data-destroying
dead-fork purge. Corroboration now requires an **independent** peer. Failing the check merely freezes the
floor, which is the safe direction. Observed live at alphanet-13 h5924.

**`TX_INCLUSION_DELAY` 2 → 8.** The h5924 split was caused by a blob tx whose `min_block` was that very
height: three nodes held it, one did not, and two otherwise-identical blocks differed in nothing but their
transaction set. One block of eligibility margin is a coin flip on propagation. Submitter-side — the
verifier checks the tx's own committed `min_block` — so no reroll was needed for this part.

---

## The recurring defect, named

Every bug this migration produced has **one shape**: prover and verifier disagreeing about which field the
challenges came from, because the field was recorded in one place and read from another.

- `recursive_verify._fs` defaulted to `ext=False`; four call sites relied on the default and all broke at
  once the day the recursion backend stopped being base-field.
- `recursion_depth._fold_proof_fs` hardcoded base for *both* of its independent field questions.
- `settlement_sparse` verified folds with `transitions()` + `NUM_AUX` while the prover used
  `transitions(ext=…)` + `NUM_AUX_EXT` — a different circuit and a different width.
- `comp_verify`/`rowcomp_verify` derived "are the alphas extension" from `bool(ext_pairs)`, which asks about
  *constraints*. A base-valued AIR under an extension field has no ext pairs and extension alphas.
- `public_part` put `ext`/`ext0` at the top level but built `fri_public` **without** them — and `fri_public`
  is what three modules hand to the FRI replay. That one broke `recursive_verify`, `recursive_verify_hetero`
  and `recursion_authdepth` simultaneously.
- `recursive_verify.verify` coerced the layer-0 seam with `int()`; the hetero copy already used `canon`.

**The structural answer**: the field now travels *inside* the FRI public statement, where `prove_fold`
already put it, and every consumer reads it from there. `extf.canon` is the single spelling of "this value
follows the challenge field". Where a mismatch is still possible, it is now **refused with a message naming
the missing argument** instead of raising `int() argument must be … not 'tuple'` several frames away.

Diagnostics that came out of this, because the failures were all silent:

- `fri_verify` records **why** it rejected a proof. It used to answer with a bare `None` that conflated
  "the proof is invalid" with "our replay is broken", so the error blamed the proof. That cost hours.
- `NADO_TRACE_RECURSION=1` prints the traceback the four recursion verifiers swallow. They must not raise —
  that is correct for consensus — but discarding the frame made a wiring bug look like a corrupt proof.
- `NADO_STRICT_NATIVE=1` turns the native-prover fallback into an error. That `except: pass` hid a real
  wiring bug for days, and two "native" timings were the Python path mislabelled.

---

## Upgrade

Clean break. Purge and resync; there is no migration path from alphanet-13 and none is wanted.

- `CHAIN_ID = "alphanet-14"`, `GENESIS_TIMESTAMP = ⟨TBD⟩`, `CHAIN_GENERATION = 15`
- Both native crates must be rebuilt: `native/starkprove` **and** `native/alghash2`. A stale degree-2 `.so`
  against degree-3 Python is rejected by the handshake, which is the intended behaviour — but a stale
  library from *before* the handshake existed only checks that the symbols are present, and would call the
  new ABI. Rebuild both.

## Known dead code

`recursion.py`'s original demonstration fold (`prove_recursive` / `verify_recursive` / `extract_fri` /
`_prove_fri` / `_comp_step_air`) is superseded by `fri_verify.prove_fold`, which authenticates openings
against the layer roots. It is base-field only and therefore accepts nothing the system now produces, so
`tests/test_recursion.py` exercises a path production cannot take — false confidence. Its low-level gadgets
(`_permute_snapshots`, `_blocks_for`, `rmerkle_commit`, `_round_transitions`) are live and shared. The
intent is to delete the dead layer once its real coverage is folded into the `fri_verify`/`comp_verify`
tests; it was not done in this release to avoid a large deletion mid-migration.

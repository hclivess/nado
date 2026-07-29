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

Prove/verify on a fixed statement at D=3: **0.208 s / 0.023 s**. The field change did not cost throughput on
the ordinary path.

**Heterogeneous folds are the expensive case**, and it is worth naming the mechanism rather than filing it as
"slow". `comp_verify`/`rowcomp_verify` allocate D periodic columns per alpha and one per limb of the layer-0
target, and every periodic column is interpolated to the trace length — so the composition half of a fold
grows with the degree in a way the trace itself does not. Observed on this branch: a two-part ML-DSA bundle
exceeded 3600 s, and `test_settlement_aggregate` ran ~1 h at ~8 GB resident.

Stated as an observation, not a regression: no like-for-like GF(p²) baseline was measured for those two
tests in this cycle, so the honest claim is "this is where the time goes", not "this got N× worse".

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

### Keccak batching

The obstacle to proving a whole signature was never trace size — it was **boundaries**. One permutation pins
1600 input bits and 1600 output bits, composition costs O(N) per boundary, so R *independent* permutations in
one trace cost 3200·R and get quadratically worse.

In a SHAKE squeeze chain the permutations are not independent: `state_out` of j **is** `state_in` of j+1. So
they are chained in-circuit and only the **first input and last output** need pinning — **3200 boundaries at
any R**. The chain rides machinery the AIR already had: a block's padding rows already repeat the final
state, so holding `A` across the tail costs nothing on an honest trace and makes the next block's row 0
adjacent to a row carrying this block's output.

The subtlety: transition constraints **wrap**, so the hold selector must exclude the final row — otherwise it
forces the last output to equal the first input, which no honest trace can satisfy.

Measured at R = 1, 2, 4: exact reproduction of R applications of `keccak_f`, 3200 boundaries at every R
(against 12800 for four separate proofs), zero constraint violations. Constraints grow 11520 → 13120 (+14%)
against a 103× reduction in proof count.

### What is NOT enabled

`SIG_AGG_STARK = False`, and the reason is **throughput, not wiring**. The sub-circuits currently take the
signature as a **public** input, so an aggregate envelope replaces the *verification arithmetic* of K
signatures, not their *bytes*. Moving the signature into the witness — so a block can actually drop it — is
an AIR change, not a configuration flag.

The cost is concrete and worth recording: proving a **two-part subset** of one signature and folding it into
a heterogeneous bundle **exceeded an hour** at GF(p³) on a loaded box. At this degree the composition AIR
carries D periodic columns per alpha and every one is interpolated to the trace length. A full 103-permutation
bundle is a proving-farm job, and no flag changes that.

The path is live and verified end to end, not dormant: `verify_block_authorizations` checks a real folded
bundle against a statement the **verifier** builds. That end-to-end proof is gated behind `NADO_HEAVY` in
`tests/test_block_auth_wiring.py` — the consensus-guarding checks in the same file run in about a second and
must not be hidden behind an hour-long proof, or a timeout reports them all as failed and tells you nothing.

---

## 4. The address prefix is gone

An address is now **42 hex chars of the pubkey + a 4-hex blake2b checksum — 46 characters, no prefix.**
`mldsa44` is removed with **no backwards compatibility**; every pre-existing address string is orphaned,
which is why this could only ship with a `CHAIN_GENERATION` reroll.

### Can you still tell an address belongs to NADO?

Yes — and by exactly the same means as before, because **the prefix never verified anything.**
`validate_address()` has always checked only the trailing 4-hex blake2b checksum over the rest, and never
referenced `ADDRESS_PREFIX` at all. So the test is what it always was: correct length, valid checksum. A
random 46-hex string passes with probability 2⁻¹⁶ ≈ 1/65536 — *unchanged*, since the prefix was never part
of the check.

What is genuinely lost is the **eyeball and tooling marker** — the thing that said "this hex is NADO's and
not some other chain's". Nothing cryptographic ever rested on it; an address is a hash of a public key, and
membership in NADO is established by the address existing in NADO's state, not by its spelling.

### What the prefix was actually load-bearing for

This is the part that made the change dangerous, and it has nothing to do with verification. A dozen sites
asked `x.startswith(ADDRESS_PREFIX)` to mean *"is this recipient an address, rather than a reserved protocol
name or an alias?"*. With an empty prefix, `startswith("")` is **True for every string** — and not one of
these would have raised:

- **`block_ops._lands_flexibly`** would classify `bond`, `register`, `attest` and `settle` as
  flexibly-landing, silently discarding the exact-landing timing invariant those transactions depend on.
  A consensus change with no error and no traceback.
- **`alias_ops.valid_alias_name`** would reject the entire alias namespace.
- The **HTLC / faucet / wallet** recipient checks, and `pets.js`'s, would go vacuous — accepting anything.

All of them now call `ops.address_ops.is_address()`: exact length, lowercase hex, matching checksum. That is
strictly better than what it replaced, because the sniff was never a test — `"mldsa44"` followed by garbage
passed it. Multisig accounts keep `MSIG_PREFIX` and are deliberately **excluded**, so a caller that means
"any account" now has to say so; the prefix sniff blurred that distinction.

`tests/test_address_format.py` pins the discriminator rather than the format: all 28 reserved names rejected,
the exact-landing routing asserted directly, and the unchanged typo/truncation rejection kept honest.

Python and JS derive the **identical** 46-char address — verified, because a mismatch would mean browser
wallets build addresses the chain rejects.

### Display

Shortened addresses were `mldsa44e…af34`: seven constant characters and one distinguishing one. A user
reported that every address looked the same, and they were right. With the prefix gone the whole budget goes
to entropy, and `shortAddr()` in the SDK renders truncations like `96381e…d9e7e` that differ from the first character.

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

### The two the test suite could never have caught

An adversarial audit (six independent lenses, findings then handed to skeptics whose job was to *refute*
them) found two defects that a green suite had been hiding. Both are worth stating plainly, because the
reason each survived is more instructive than the fix.

**1. CRITICAL — the chain would not have started.** `construct_block` hashes the block preimage;
`block_content_hash` re-derives it; `save_block` **raises** on mismatch. `auth_root`/`auth_count` went into
the first and not the second, so this was never a subtle mismatch somewhere — **every block was
unpersistable** and alphanet-14 would have halted on block 1. There *was* a test asserting the commitment is
inside the hash, and it passed: it compared two `construct_block` outputs to each other and never against the
re-derivation, so it was structurally incapable of seeing it. Two dicts holding one definition is the defect;
the missing field was only its symptom.

**2. HIGH — a prover could pick its own security level.** `recursive_verify.verify` and
`fri_verify.verify_fold` read the challenge field *out of the proof* and used it unpinned, where
`stark.verify` pins `expected_ext` and rejects a mismatch. A prover shipping base-field inner proofs would
have had the settled state root attested at **~47 bits instead of ~156** — and the identical proof handed to
`stark.verify` is rejected, which is what makes it a *policy* hole rather than an arithmetic one. Reachable
on the **live block-apply path**, not merely behind `SETTLE_PROOF_RECURSIVE`:
`verify_settlement_sparse → verify_bound_epoch → bind_and_verify → verify_transition`, which branches on
`if "bundle" in tr` — an **attacker-controlled key**.

This one left the suite green *because* it is a downgrade: honest proofs still verify, nothing fails, the
system merely checks a weaker statement. That is the failure mode tests cannot see, and the reason "green" is
not "sound". `recursive_verify_hetero` had already got it right — two sibling verifiers, same job, opposite
answers, which is exactly the drift `extf.py`'s docstring warns about.

Both fixes were verified with the auditor's own proof-of-concept (`True → False` on both exploit paths) and
against honest folds, not merely by re-running the suite.

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

## Two things deliberately NOT in this release

**The finality-floor corroboration fix is not cherry-picked to `main` ahead of the release.** It ships *in*
the release. It fixes a real wedge (a node alone on a fork corroborates its own depth floor, advances an
un-crossable barrier past its own fork point, and can then only escape by a data-destroying purge), and it bit
twice in one day. But it arrives within hours either way, and landing it separately means restarting every
production node **twice** instead of once, on a `main` that carries someone else's active work. The observed
cost of waiting is bounded: every fork on 2026-07-29 — four of them — healed unassisted, and the remedy the
machinery reaches for (purge + resync) destroys chain-derived data but never funds or keys. Two restarts to
save a few hours of a self-healing failure is the worse trade.

**Reserved-tx landing stays an exact block, not a range.** This is the single root cause of every fork
observed on 2026-07-29 — h5924 (`blob`, `min_block`), h6424 (`register`), h7692 (`duty`). Timing-critical
reserved transactions must land at *exactly* `max_block`, so `RESERVED_TX_MARGIN` (30) and `DUTY_TX_MARGIN`
(12) buy propagation **time** but not landing **tolerance**: any producer that has not received the tx by
precisely that height builds without it, the two honest blocks differ in nothing but their tx set, and the
chain forks. alphanet-14 inherits this unchanged.

It is not fixed here on purpose. Changing where a transaction may land is a **consensus rule change on the
validation path**, entirely unrelated to the proof system this release is about — and bolting it onto a
release whose headline feature (K→1 folding) is still unproven at the time of writing compounds risk on the
wrong surface. The evidence says it is a **liveness** defect, not a safety one: no fork produced a state
divergence, an invalid block, or a loss, and all four self-healed. So it earns its own focused change and its
own reroll, where it can be tested for what it is instead of riding along with a field migration.

The fix, when it is made, is to give timing-critical txs a landing *window* `[max_block - W, max_block]`
rather than a point, so a producer that receives the tx late still includes it at the same height everyone
else does.

## Known dead code

`recursion.py`'s original demonstration fold (`prove_recursive` / `verify_recursive` / `extract_fri` /
`_prove_fri` / `_comp_step_air`) is superseded by `fri_verify.prove_fold`, which authenticates openings
against the layer roots. It is base-field only and therefore accepts nothing the system now produces, so
`tests/test_recursion.py` exercises a path production cannot take — false confidence. Its low-level gadgets
(`_permute_snapshots`, `_blocks_for`, `rmerkle_commit`, `_round_transitions`) are live and shared. The
intent is to delete the dead layer once its real coverage is folded into the `fri_verify`/`comp_verify`
tests; it was not done in this release to avoid a large deletion mid-migration.

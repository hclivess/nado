# Rust-only proving — why a hybrid prover is not a prover

**Status: binding. 2026-07-30.**

A proof that takes 72 hours is not a slow proof. It is a proof that does not exist, because nothing in the
release process can wait for it, so it never gets run, so the thing it was supposed to establish stays
unestablished. This document exists because that was learned expensively.

## What actually happened

Over roughly seventeen hours of one session, the K→1 fold gate was run four times and **completed zero times**:

| attempt | outcome |
|---|---|
| first heavy gate | 6h34m, passed its substantive claims, failed on a bug in the test's own tamper helper |
| re-run | killed at ~5h by the project owner |
| `NADO_HEAVY` signature bundle | OOM-killed at 1h33m against a 16 GiB cap |
| settlement aggregate | OOM-killed at 1h46m against the same cap |

Three heavy verifications were required for the release. None finished. The release did not move.

The instinct throughout was to re-run with a bigger budget. That instinct was wrong, and the owner's
correction — *"stop the python folding and GO RUST"* — was right. Re-running a six-hour job is a decision to
learn nothing for six hours.

## Where the time actually went

This is the part that matters, because it was counter-intuitive and it took measurement to see.

**Every kernel was already native.** `sp_fold`, `sp_fold_ext`, `sp_compose`, `sp_compose_ext`,
`sp_commit_col`, `sp_open`, `sp_grind`, the whole persistent LDE arena — all Rust, for a long time. The
composition, the Merkle builds, the NTTs: native.

What stayed in Python was the **orchestration**, and orchestration is not glue when it sits in the inner loop:

- **`fri.prove`** absorbed a root, crossed the FFI boundary for a challenge, crossed back to fold, crossed
  back to open — once per layer and once per each of 320 queries.
- **`recursion._permute_snapshots`** was the worst of it: the in-circuit hash AIR constrains one permutation
  *round* per trace row, so witness generation needs every intermediate state, not the digest `permute()`
  returns. 54 rounds of a full 12×12 MDS matmul — 7,776 field multiplies — **per call**, called once per
  Merkle block, with 2W openings per point and path_len+1 blocks each. At W=352 that is order 10⁸ field
  multiplications per comp proof, and a K→1 fold builds six comp proofs.
- **`_blocks_for`** crossed the boundary once per block: ~12,700 crossings per point.
- **`_fill_trace`** wrote the witness as a Python list-of-lists — ~5.8M cell writes for the carry spans alone
  — and then `stark_native.prove` rebuilt every column with `[trace[i][c] for i in range(T)]`, paying T×W
  index operations to undo the layout that had just been produced.

The permutation had been native the whole time. What was missing was the ability to **see inside it**, so
witness generation kept re-deriving in Python precisely what Rust already computed.

## Measured, not asserted

| change | before | after |
|---|---|---|
| `_permute_snapshots` | 4.137 ms | 0.028 ms (**146×**) |
| `_blocks_for`, 17-block path | ~74 ms | 1.9 ms |
| FRI layer loop | one FFI crossing per layer and per query | one call |
| Merkle path generation | ~12,700 crossings per point | 1 |

## The rule

**Where a Rust variant exists, it is the only production implementation.** A missing or stale `.so` is a hard
failure at load, never a quiet downgrade — see `execnode/stark/native_guard.py`.

The fallback was defended for years as *"bit-identical, consensus-safe, just slower"*. Every word of that is
true, and that is exactly what makes it dangerous. **A degraded node never fails.** It returns correct
answers, so nothing raises, and the only symptom is throughput nobody is watching.

That is not hypothetical. During this same session `/srv/nado-dev` was found running:

- pure-Python ML-DSA (`dilithium-py`) while production ran `native:nado_pq_native`,
- pure-Python Goldilocks — the **base field** — because `libgoldilocks.so` had never been built there,
- no `starkcompose` at all.

Nothing reported any of it. Four signature tests hit their timeouts and were indistinguishable from real
defects. Heavy-proof timings about to be written into release notes had been measured under an ~84× handicap
that nobody knew was there. Right answers, wrong conclusions, for hours.

## What is still Python, and why that is not a hybrid seam

The sweep that removed the Python *oracle* was scoped by grep first and by evidence second, and the evidence
moved it. Two geometries still run the Python prove body, and neither is a fallback — each is the **only**
implementation of its case:

| geometry | why the arena cannot take it | live? |
|---|---|---|
| **`BLAKE2B` backend** (`backend.DEFAULT`) | the arena's Merkle speaks only the alghash2 family (`hmode` 0 `rleaf`/`rnode`, 1 `hashn`); blake2b leaves are a different hash entirely | **YES** — `joinsplit2.prove_transfer` calls `stark.prove` with no backend, and `shielded_field.py` ships that proof. The shielded pool proves here. |
| **`commit_periodic`** | committed periodic columns must absorb their roots *before* the trace commitment, but the arena assigns periodic column ids *after* the aux phase — transcript order and arena id layout disagree | no live caller; used by `bound_epoch_o1` (succinct verify) |

### Closing the BLAKE2B gap — measured, and not the way it looked

The obvious shortcut was to switch the shielded pool to the ALGHASH2 backend, which the arena already covers.
Since betanet-14 is a reroll the format break is free, so the only question was cost. Measured on the real
join-split circuit (`T=2048`, `W=21`, `D=8`, 8 queries):

| backend | prove | verify |
|---|---|---|
| `BLAKE2B` — Python prove body, today | **35.1s** | 0.2s |
| `ALGHASH2` — arena / Rust | **46.4s** | 0.8s |

**The shortcut is a 32% regression on the money path.** The arena's advantage is memory and wide traces; this
circuit is narrow, and blake2b's raw cheapness beats an algebraic sponge even with Rust underneath it. Being
in Rust is not the same as being fast — *which hash you are computing* dominates here, and the prediction that
Rust would win outright was simply wrong.

The real fix is therefore to teach the arena blake2b as **hash mode 2**, keeping blake2b's cheapness *and*
native LDE/Merkle/FRI. The framing is small (`backend.py` `_Blake2b`): leaf = `b2b32(\x00 || x_le64)`, node =
`b2b32(\x01 || a || b)`, ext leaf = `b2b32(\x02 || limbs_le64)`. The work is not the hash but the plumbing —
the arena stores digests as u64 lanes while blake2b digests are 32 raw bytes, and a fully native blake2b prove
also needs the transcript (`t_init`/`t_absorb`/`t_challenge`/`t_index`/`t_grind_hash`) in Rust.

**Deliberately not done before the betanet-14 tag.** Introducing an unverified hash implementation on the
live shielded path immediately before a release inverts the risk order, and rule 4 above applies: the Python
blake2b body is the natural differential oracle for that port, so it must be verified byte-for-byte *first*
and retired *after*. It is the next port, not this one.

This distinction is the whole point and it is easy to lose:

> A **fallback** is a second implementation of a path the fast one already covers, chosen silently on failure.
> A **sole implementation** of an uncovered geometry is just code.

The first is forbidden. The second is ordinary, and deleting it because it is written in Python would have
broken the shielded pool — the money path — in the name of a policy about speed. The plan for this sweep did
say "delete stark.py's Python prove body"; that plan was written from a grep and was wrong.

What *was* removed is the part that had actually expired: the `NADO_NO_HOLISTIC` env route and
`tests/test_holistic_wired.py`, which existed to prove every AIR twice and compare bytes. Those compared the
Rust against an implementation being retired, which establishes compatibility, not correctness.

The guarantee that remains, and it is the one that matters: **for every geometry the arena covers, there is no
second path.** A native failure raises; a `.so` predating the extension port raises rather than quietly
emitting a base-field proof. Selection is by the CALL (backend, `commit_periodic`), never by an env var and
never by an exception handler.

## Consequences for anyone working here

1. **Do not add a Python fallback to a path that has a Rust implementation.** Raise `NativeMissing` instead.
   `NADO_ALLOW_PYTHON_KERNELS=1` exists for *building* and for the Python-vs-Rust conformance tests. Nothing
   in a node sets it; if you find it set on a validator, that is the bug.
2. **A hybrid seam is a bug, not a stepping stone.** `stark.prove` kept the arena for LDE/Merkle/composition
   and handed FRI back to Python; the comment at that seam priced itself — *"what made every proof pure-Python
   and turned a 3-circuit fold into ~50 minutes"*. Seams get written once and live for years.
3. **Port the shape, not just the kernel.** If the answer to "why is this slow" is "it calls a fast function
   many times", the fix is to move the loop, not to optimise the function.
4. **Keep the Python as a differential oracle until the replacement is verified, then delete it.** Every port
   in this effort was checked byte-for-byte against the original over several geometries, including base *and*
   extension values. Deleting an oracle before its replacement is proven leaves the Rust unchecked and the
   tests passing vacuously.
5. **If a verification cannot finish, it is not a verification.** Do not report a timeout as a pass, and do
   not report an unfinished run as evidence. A cut-off run was never observed to succeed — it is a coverage
   gap wearing a green label.
6. **Scope a deletion by call sites, not by grep.** Every candidate here was checked for a live caller before
   removal, and that check changed the plan twice: `_fill_block` / `_junk_absorb` / `_blocks_for` looked dead
   and are not (`rowcomp_verify` 290-335, `fri_verify` 458, `recursion.py` 413/576), and the Python prove body
   was slated for deletion until `backend.DEFAULT = BLAKE2B` turned up on the shielded pool's prove call.

## The corollary that made all of this worth it

A faster prover is not only a convenience — **it changes which bugs are findable.** `SIG_AGG_STARK` was
blocked by a defect in the ML-DSA `usehint` AIR: constraint #60 asserted `r == q-1` where Dilithium's wrap
case is `r - r0 == q-1`, so roughly half of all signatures produced a trace violating its own AIR, and FRI
correctly refused the resulting non-polynomial composition. The test that catches it,
`test_block_auth_wiring` under `NADO_HEAVY`, had **never once completed** — two OOM-kills and a timeout. The
semantic test (`test_mldsa_hint_air.py`) passed throughout, because the AIR *is* semantically right; it was
the PROOF that was invalid, which no semantic test can see.

A proof that takes 72 hours does not merely delay a release. It hides defects, because the check that would
expose them never runs to completion.

**Epilogue: the feature was removed anyway, and the speed-up is why we could tell.** Signature aggregation
was deleted on 2026-07-31 once it could be measured end to end: 7.11 min to prove and 1.87 MB for the
butterfly half of ONE signature, against a 2420-byte signature that verifies natively in 120.4 µs. Making
proving fast did not save the feature — it made the feature *falsifiable*, which is worth as much. It also
surfaced two forgery-class bugs on the way (`doc/zk-signature-aggregation.md`), and the kernel work it
motivated stayed: the alghash2 permute went 54.11 µs → 28.71 µs by deleting two u128 divisions, on the hot
path of every proof the chain makes.

## Related

- `execnode/stark/native_guard.py` — the policy, and the reasoning, in code.
- `doc/zk-recursion.md` — the fold this was blocking.
- `native/starkprove/src/lib.rs` — `sp_tr_*`, `sp_fri_prove`, `sp_permute_snapshots`, `sp_blocks_for`,
  `sp_fill_path`, `sp_fill_carries`, `sp_lde_trace_flat`.

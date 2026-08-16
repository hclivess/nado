# Shielded contracts — private application state

> **Status: PHASE 2 BUILT.** The state machine, the settled-root binding, the `private_call` op, the
> turnstile and the **transition circuit** are implemented and tested. A private state change proves and
> verifies as one STARK; `CONSENSUS_ALLOW_TRANSPARENT` stays `False` and the transparent witness path is
> dev-only scaffolding. Merging changes no root and no snapshot on a chain that holds no private state.
> What remains is DA transport for the proof, a worked example contract, and client-side proving.

## 1. What this is, and what it is not

`doc/privacy.md`'s pool hides **values**: a note is `(value, owner, rho)` and the single invariant its
circuit knows is value conservation. Every contract deployed today is the opposite — public bytecode over
public storage with public inputs. This is the missing middle: **private state with public code**.

It is *not* private *logic*. Hiding what a program **is** needs indistinguishability obfuscation, which
`doc/obfuscation-diamond-io.md` assesses honestly and does not recommend building on. Keep the two apart:
this document is about state, and it is buildable; that one is about code, and it is research.

## 2. Why it is cheap here

Because the pipeline already exists and already carries traffic. A private contract transition is the
**same** proof → DA → commitment → L1-order → verify loop a shielded transfer runs; only the statement
inside the proof changes. Of everything a private call touches, exactly two components are new: the typed
note, and the kernel circuit that will prove a transition over it.

```
     private, on the device                    public, on every node

  wallet ──proof (1–4 MB)──▶ DA layer ──fetch by commitment──▶ exec node ──▶ note tree + nullifiers ─┐
     │                                                              ▲                                ├─▶ settled
     └──blob: commitments + nullifiers + DA ref (~300 B)──▶ L1 ──────┘        public zkVM + storage ──┘     root
```

## 3. The note

```
note  = (cid, kind, fields…, owner, rho)
cm    = hashn([DOM_APPCM, cid, kind, arity, *fields, owner, rho])
nf    = hashn([DOM_APPNF, nsk, cm])
owner = alghash.owner_of(nsk)                 # the pool's own derivation — one key serves both
```

Three things differ from a value note, each for a reason:

- **`cid` scopes it.** A note belongs to exactly one contract and can never be moved between apps. It also
  makes cross-contract nullifier collisions impossible for free, since `cid` is inside `cm`, which is
  inside `nf`.
- **Arity is bound.** The sponge absorbs a flat sequence, so binding the field count makes a note's
  *shape* part of what its commitment commits to, and gives the circuit a public handle on how many
  absorptions a kind performs.
- **The nullifier binds the commitment, not the randomness.** The value pool derives `nf = H(nsk, rho)`,
  and its own docstring records the consequence: *"the SENDER, who chose rho, can also compute this — a
  minor spend-detection leak"*. Binding `cm` closes it. A sender does not hold `nsk`, so they cannot
  recognise the spend of a note they created.

## 4. Two statements, because a deposit has nothing to spend

| statement | shape | trace | prove | what it proves |
|---|---|---|---|---|
| **deposit** | 0-in / 1-out, `delta > 0` | 256 | ~5 s | this commitment commits to exactly the escrowed value |
| **transition** | 1-in / 1-out | 2048 | ~31 s | membership, nullifier derivation, and the kind's predicate |

The deposit is not an optimisation, it is a prerequisite: with the transparent path off, a 1-in/1-out
circuit alone means **no note can ever be created** and the feature cannot bootstrap. That was found by
trying to write the worked example, which is what worked examples are for.

A deposit still needs a proof even though its amount is public. The value that entered is visible — the
coins left the ledger in plain sight — but the *owner* must not be, so the opening cannot simply be
published: revealing `owner` and `rho` would let anyone recompute `cm` and follow that note forever. The
proof attests one thing (this commitment commits to exactly the escrowed value) while hiding whose it is.
That is Zcash's shielding property: the amount entering is public, the recipient is not.

**One AIR serves both.** The deposit reuses `transitions()` unchanged rather than adding a second
constraint set — every constraint it does not need is satisfied trivially, because the unused absorb and
capture selectors are zero columns, so the capture registers hold at 0 and `c_cons` still reads
`CONS = VIN - VOUT` with `VIN = 0`. A second AIR would be a second thing to audit.

## 5. What a private call does NOT do — the honest limit

**A private call does not execute contract code.** `private_call` never enters the zkVM. The contract is
the *scope* a note belongs to; the rule enforced is the note **kind's** predicate, drawn from a shared
library and built into the AIR. So the accurate description of what is built today is "private state,
scoped per contract, governed by a shared kind library" — not yet "arbitrary private functions".

That is a real gap and it is the one the zkVM-with-a-private-tape route was meant to close: a kernel that
binds a *specific contract method* to the private transition, so a contract can impose its own rules on
its own private state. Everything below it — notes, trees, nullifiers, the turnstile, DA, the settled-root
binding — is indifferent to which route supplies the predicate, which is why that can land later without
disturbing any of it.

## 6. Transition rules are per-kind predicates

This is the extension point, and the reason this is not simply a second pool. A predicate answers one
question — given the fields of the notes a transition spends and creates, plus its public delta, is this a
legal move for this kind? It never sees owners, randomness or positions; those are the pool's business,
not the app's.

| kind | fields | predicate |
|---|---|---|
| `KIND_VALUE` | `[amount]` | `Σ in + public_delta = Σ out`, every amount in `[0, 2^61)` |

A new private app is a new kind plus a predicate. Conservation is one possible rule, not the law: a
hidden-hand note in a card game conserves nothing and only has to be well-formed.

**The bound is 2^61, and it is now DERIVED rather than restated.** `RNG_TOP_BITS = 3` is the one number:
`c_rng_top` sums exactly that many bit columns, and `RANGE_BOUND = 1 << (4·RNG_NIBBLES − RNG_TOP_BITS)` is
computed from it, with `VALUE_MAX` importing it. A constant that mirrors a constraint should come from the
constraint — testing them for agreement afterwards catches drift, but not having two of them is better. `c_rng_top` sums THREE bit columns of the MSB nibble, so a bound value is
< 2^61 — verified by building honest traces (2^61 − 1 satisfies the AIR, 2^61 does not). Note that
`joinsplit_circuit`'s *module docstring* says "top 2 bits pinned to 0 … [0, 2^62)" and is **wrong**; its own
inline comment on that constraint says 2^61 and is right. `VALUE_MAX` here was 2^62 because it was taken
from that docstring, which made the transparent verifier LOOSER than the circuit — and Phase 1 exists to be
the specification the circuit is diffed against. A note above 2^61 would have been creatable on the dev
path and unspendable by any proof. Total supply is ~2^41, so 2^61 leaves twenty doublings of headroom.

The range bound is not decoration. Conservation over the field is conservation **mod P**, and Goldilocks
`P ≈ 2^64` is barely above the coin range — without it, an output near `P` balances mod P and mints value
from nothing. It is the same attack the pool's C-3 in-circuit range gadget exists to stop.

## 7. A commitment is unique, and that is a fund-lock guard

Found by attacking the finished system rather than by any of the 86 checks that existed when it was
"done" — every one of those exercised it working, not an adversary reusing a valid artefact.

A deposit is 0-in/1-out: it has **no nullifier**, because there is nothing to spend. Nothing about its
proof or public statement is therefore consumed, so both are **infinitely replayable**. Each replay
appended the same commitment again — and since `nf = H(nsk, cm)` depends only on the note, every copy
shares ONE nullifier. Spend either and the rest are permanently unspendable while their value still sits
in the contract's escrow: coins locked forever, and the turnstile broken with them (escrow counted value
that could never be claimed).

The fix is one rule, checked before either verifier runs: **a commitment is unique**, exactly as a
nullifier is. It therefore covers deposits and transitions alike rather than only the path that exposed
it, and an honest depositor pays nothing for it — fresh `rho` gives a fresh commitment.

### The public delta is bound to an integer, not a residue

The circuit pins `CONS = -public_delta` as a **field element**, so every delta congruent mod P satisfies
the same boundary: a proof for `-1000` is equally a proof for `-1000 - P`. Without a bound, the proof
attests to `delta mod P` — not to the delta the ledger then moves.

**Honest severity: not exploitable in practice.** Total supply (~2.3e12 raw) is nine orders of magnitude
below P (~1.8e19), so the op's solvency checks would always have refused an aliased amount. It is fixed
anyway, because "an unreachable amount stops it" is a property of today's supply and of the order the
checks happen to run in — not a property of the proof, and the proof is what is supposed to be doing the
work. `|delta| < VALUE_MAX` together with the in-circuit range bound on both note values makes the mod-P
equation coincide with the integer one, so exactly one integer delta satisfies a given proof. It is the
C-3 argument applied to the one public value the range gadget does not cover.

### The withdrawal destination must be a spendable account

Unlike the pool's unshield — which records an exit for L1 to release and lets L1 check the address — a
private withdrawal credits an exec-layer balance **directly**. Whatever string lands there *is* the
account. Unvalidated, two things followed, both reachable by any user:

- a destination that is not an address (a typo, a truncation) created a balance under a key no
  `bridge_withdraw` can ever move — a silent burn;
- a destination that was a **contract id** credited that contract's escrow while it held no matching
  notes, breaking the turnstile invariant this document states (`bridge[cid]` == that contract's private
  total) and stranding the coins, since spending contract escrow requires a note under that cid.

The destination is now checked as a real, non-reserved account, and contract ids are excluded explicitly —
a cid passes the checksum with probability ~1/65536, which is not a guarantee.

### The anchor window — measured, not widened

`knows_root` decides whether a transition is accepted, yet the anchor list is **not** committed by
`exec_root`. A divergence there would fork the fleet with no root mismatch to signal it, so it is pinned by
test rather than assumed: the anchor set is a pure function of the applied sequence and survives a
snapshot.

MEASURED: exactly `ANCHOR_WINDOW` (128) appends **to one contract** evict a root. A transition proof takes
~31 s to build (~5 blocks) and blob inclusion runs at roughly one per block, so the margin is ~25x. Trees
and windows are per contract, so a busy vault cannot invalidate a quiet one's in-flight proofs — which is
the reason the trees were split per contract rather than pooled.

Left at 128 deliberately. It is a liveness property to watch if a single contract ever sustains high
append throughput, not a live problem, and it gates acceptance — so it cannot be changed on one node.

### The proof's declared shape must match the kind's

The circuit is **arity-parametric by design** — that is what makes a new note type a new predicate rather
than a new circuit. It will therefore happily prove a two-field `KIND_VALUE` note, and it is right to.

The binding between shape and kind can only be made by the state machine, and it has to be, because a
predicate is written against a fixed number of fields: `_predicate_value` reads `fields[0]` as the amount.
A `KIND_VALUE` note with a second field is a note that rule was never written for, and nothing would
govern the extra field. The transparent verifier catches it by inspecting the openings; the proof path
never sees them. `KIND_ARITY` closes it, and a check asserts every provable kind declares one — a kind
that could be proved but had no declared shape would slip past entirely.

Depth is pinned the same way. A membership proof at any depth but the pool's could only fold to a known
root by hash collision, but "collision-resistance stops it" is the wrong argument for something the
verifier can simply check, and it would silently become the *only* argument the day `TREE_DEPTH` changed.

### The verifier bounds the geometry it is handed

`verify` reads arity and depth from the **proof** and builds `NPER` periodic columns of length
`trace_len(arity, D)` from them. Computed, not allocated:

| declared | trace | periodic cells | implied |
|---|---|---|---|
| arity 1, depth 18 | 2 048 | 53 248 | — |
| arity 10⁶, depth 18 | 67 108 864 | 1 744 830 464 | ~49 GB |
| arity 1, depth 10⁶ | 134 217 728 | 3 489 660 928 | ~98 GB |

Not reachable through `private_call` — the state machine pins arity against `KIND_ARITY` and depth against
`TREE_DEPTH` before calling. But **that guard lives in the caller and the allocation happens in the
callee**, so any other user of the circuit gets no protection from a check it does not run. `MAX_FIELDS`
and `MAX_DEPTH` are now enforced in the verifier itself, before a single column is built; the refusal takes
0.000 s. `MAX_FIELDS` also had two definitions and now has one — a bound that exists twice is a bound that
can disagree with itself.

### A contract upgrade cannot strand or re-govern private state

An upgrade preserves the cid, notes are scoped by cid, and the rules come from the note **kind** rather
than the contract's code. So upgrading a contract can neither invalidate its private state nor change how
existing notes behave. That is worth stating as a property rather than leaving implicit: the alternative —
an upgrade silently invalidating everyone's notes — would be a rug pull with no attacker in it.

If a contract ever did vanish, the notes stay in the tree and the escrow stays in the ledger. The failure
mode is *frozen*, never *silently gone*, and there is a check for that too.

## 8. What the chain commits

`execnode/exec_root.py` tags **11** (`T_APP_ROOT`, per contract) and **12** (`T_APP_NULL`, the spent-set
digest). Both are digests **in the position**, value 1 — a note root is a 64-bit field element, and
putting it in the value would bound binding far below the position's 256 bits.

**Appending is the whole state-binding cost.** Tags 1–10 do not move, so no historical root is invalidated
and no `CHAIN_GENERATION` reroll is needed — exactly the forward-compatibility `exec_root`'s own header
promises.

**Empty is absent**, and this is load-bearing. A record emitted unconditionally — even the digest of an
empty nullifier set — would move every node's root the instant the code shipped, and a fleet that upgrades
over minutes rather than atomically would split. This project has been there twice: a codec `sort_keys`
change altered the genesis root and wedged the fleet, and a prune watermark leaking into the root split it
at h10047. A chain with no private state therefore projects byte-identically, on disk and in the root.

## 9. Transport: the proof rides DA, L1 carries a commitment

MEASURED: a transition proof is **24.7 MiB**; the public statement it proves is **183 bytes**. The blob cap
is 64 KiB, so the proof cannot ride L1 and does not try to. The blob carries the public statement plus a DA
commitment; the bytes travel Reed-Solomon k-of-n with a PQ Merkle commitment, and any k shards
reconstruct trustlessly — every `(shard, proof)` self-verifies, so a set salted with bad shards needs k
GOOD ones rather than being corrupted by the bad.

This is not a new mechanism. Shielded transfers already ride exactly this path, and `private_call` was
added to the **same** op table (`_DA_BLOB_OPS` in `execnode/execnode.py`) rather than given its own
resolver:

```
_DA_BLOB_OPS = {"field_transfer": "bundle_json", "private_call": "proof_json"}
```

The property that table protects is **all-or-nothing**: `_apply_block` resolves every DA-carried proof in a
block BEFORE mutating anything, and an unavailable proof stalls the block in L1 order rather than
half-applying it. Every honest node fetches the identical bundle by commitment, so all of them apply the
same thing or none of it. A per-op difference there would be a fork, which is precisely why there is one
table and not two branches.

L1 admission already validates `proof_da` for **any** blob payload, op-agnostically, so private calls
inherit the path-traversal guard for free.

## 10. `op: private_call`, and why it is not `op: call`

`calls_commit.block_calls` collects only `op == "call"` into the settlement calls list, and a call the
chain skips or reverts makes the **whole span unprovable** (ROADMAP, 2026-08-06). A private call is
rejected whenever its proof does not verify — something any user can cause at will. Routing it through the
zkVM call path would therefore hand every user a lever to switch the chain off validity proofs, one bad
proof per span. As its own op it is invisible to `block_calls`, so a rejection is a pure no-op.

`tests/test_shielded_state_exec.py` builds a real block carrying a `private_call` blob and asserts
`block_calls` ignores it. Do not "simplify" this into a contract call.

**The turnstile.** `public_delta` is the only way value crosses between the public ledger and a
contract's private state, and every unit of it is escrowed on the public side by the contract itself — so
`bridge[cid]` equals, at every height, the total of that contract's private notes. Individual note values
stay private; the aggregate is public by construction, the same auditability the pools have.

```
delta > 0   DEPOSIT    debit the blob's sender, escrow into the contract
delta < 0   WITHDRAW   release from the contract's escrow to a NAMED destination
```

Solvency is checked *before* the transition and the funds move *after* it succeeds. Both halves matter:
checking afterwards would let a transition apply that the ledger then could not fund, and moving first
would have to be unwound on a verification failure. A blob is user-supplied and escrow-free, so without
this the delta would create or destroy value nothing on the other side accounts for — the hole
`apply_field_transfer` fences with *"coins enter only via an L1 shield"*.

`withdraw_addr` is bound into `transition_sighash` unconditionally. That is the pool's H-4 fix, inherited
rather than rediscovered: with the destination outside the proven message, a front-runner could copy a
victim's blob, swap only the address for their own, land it first, and the proof would still verify
because the address was not in what it committed to.

## 11. Phased, like the pool it extends

- **Phase 1 — built.** `verify_transition` re-checks openings, membership, nullifier and commitment
  derivation in the clear. Sound — no double-spend, no forged membership, no predicate violation — but not
  private, because the witness carries `nsk`. It is scaffolding: it freezes the state machine and its
  soundness suite *before* the circuit, so the AIR can be diffed against a specification that already
  exists. `CONSENSUS_ALLOW_TRANSPARENT = False` keeps it off any chain.
- **Phase 2 — built.** `execnode/stark/appnote_circuit.py` proves the whole statement and the verifier
  sees only `public`. The state machine did not change; only what sits behind the seam did. Note the route
  taken differs from the original plan: rather than the zkVM AIR with a private tape, this generalises the
  join-split's own AIR to a typed note, because the statement a KIND_VALUE transition makes is exactly the
  join-split's plus three public absorptions. The zkVM route is still the right answer for kinds whose
  predicate is arbitrary program logic; this one covers every kind whose rule is expressible as
  constraints, which is where the useful cases start. `STARK_KINDS` is the gate: a kind whose predicate the
  AIR does not enforce cannot take the proof path at all, because it would then be checked by nobody.
- **Phase 3 — the real bar.** Client-side proving. Today `shielded_field.py` hands the exec node the
  witness, so the pool is private from the chain but **not from whoever runs the exec node**. Until a WASM
  prover ships, the honest phrasing is "private except from the operator". The kernels are already native
  Rust, so this is a target and a witness-generation path, not a new prover.

## 12. Measured, 2026-08-16

Taken on this box against `joinsplit_circuit` — the circuit the private-transition AIR generalises — so
these are the numbers the design is built on rather than guesses.

| depth | trace `T` | backend | prove | note |
|---|---|---|---|---|
| 12 | 2048 | blake2b | 24.2 s | the default, and **not natively provable** |
| 12 | 2048 | alghash2 | 13.8 s | the arena covers this one |
| 20 | 2048 | blake2b | 25.3 s | |
| 20 | 2048 | alghash2 | 12.9 s | |

**Three findings, in order of how much they change the plan.**

**1. The join-split path cannot prove on a node at all.** `stark.prove`'s native arena covers only the
`alghash2` and `recursion` backends; everything else falls through to `require_native_prover`, which
refuses outside a build or a conformance test. All three join-split modules — `joinsplit.py`,
`joinsplit_circuit.py`, `joinsplit2.py` — call `stark.prove` **without a backend**, so they take
`backend.DEFAULT`, which is `blake2b`. On a node that raises `NativeMissing`; the measurement above needed
`NADO_ALLOW_PYTHON_KERNELS=1` to run at all. This is not a shielded-contracts problem — it means the
**pool's own Phase-2 delegated prover is inoperable in production today**, and it predates this work.

*Consequence here:* the private-transition circuit passes `backend=alghash2` from birth. A circuit that
inherits the default would be born unprovable on the machines meant to run it.

**2. Tree depth — and a correction.** That row was measured against the JOIN-SPLIT's geometry and then
applied to this circuit, which is not the same shape: this one spends `(arity+6)·R` on COMMIT *and* on
OUTPUT, three extra public absorptions each, so its total is larger and it crosses to `T = 4096` two levels
sooner. Measured against the right circuit:

| depth | trace | prove | capacity |
|---|---|---|---|
| 18 | 2048 | 21.1 s | 262,144 notes |
| 20 | 4096 | 30.7 s | 1,048,576 notes |

`TREE_DEPTH = 18` — 31% off every transition proof for a quarter of the capacity, which is per-contract and
still ample. It also explains prove times earlier in this document that were put down to machine load: they
were a doubled trace. The test recomputes the maximum from the circuit's own geometry, so the constant
cannot drift away from the circuit the way it drifted in from the wrong one.

**3. ~13 s per proof on a server core.** That is the delegated-prover figure, and it is the honest input
to the client-side question: a phone is not this box. The Phase-3 decision (WASM prover vs. a blind
delegated one) should be made against a measured phone number, not this one.

## 13. What would sink it

Proving cost, not cryptography. Putting a private call through the VM AIR multiplies the trace by every
step of the call, and this chain has already met the ceiling from the other side — a settle span of 119
record updates was declined on 2026-08-16 because the proof would have been ~1 794 MiB against
`SETTLE_INLINE_MAX` and taken ~5 355 s to build. The 13 s above is for a ONE-note transition with a fixed
statement; a general private call is strictly more.

## 14. Running the tests from a clean checkout

```
bash scripts/build_native_all.sh     # once — builds the five crates a node builds for itself
python3 tests/test_shielded_state.py # …and the rest
```

A NODE never needs this: `ops/self_update.py` rebuilds missing or stale crates as part of advancing, so
the fleet self-heals. A CHECKOUT does. The only build script shipped `mldsa44`, yet every `NativeMissing`
message — for any of the five — points the reader at it, so a fresh clone follows the instruction it is
given and is still missing four libraries. `build_native_all.sh` reads the crate list from
`ops/self_update.py` rather than restating it, and delegates `mldsa44` to `build_pq_native.sh`, which is
what knows that its loader wants the library at the crate root rather than in `target/release`.

Verified by checking the branch out fresh and running it: one command, then every suite green.

## 15. Are the tests load-bearing?

A passing test is evidence only if it would fail when the thing it tests is broken. This branch found the
counter-example the hard way: a test that hashed two statements and asserted the digests differed, claiming
to prove the withdrawal destination was bound. It passed, it proved nothing, and the helper it exercised
was dead code.

`tests/mutation_check.py` breaks each guard in turn and requires the suite that covers it to go red:

| guard broken | suite | result |
|---|---|---|
| duplicate-commitment guard | replay | CAUGHT |
| delta bound | replay | CAUGHT |
| arity pin | replay | CAUGHT |
| depth pin | replay | CAUGHT |
| destination validation | replay | CAUGHT |
| empty-is-absent projection | root | CAUGHT |
| nullifier-set absence | root | CAUGHT |
| geometry bound (circuit) | replay | CAUGHT |
| transparent-path switch | state | CAUGHT |
| no-mutation-on-rejection | atomicity | CAUGHT |

Ten for ten, working tree clean afterwards. Every one of those guards exists because of a specific defect
found on this branch; this establishes that removing any of them is noticed.

**The AIR gets the same treatment, and initially failed it.** Dropping any of eight constraints probed left
the circuit suite green, because the tamper checks asserted only that *something* objected — so the
remaining constraints covered for whichever was missing. Each tamper now names the constraint that must
catch it, and a table supplies one tamper per constraint with a bookkeeping check that none is left
unpinned. Verified by neutering each constraint **in place** (body replaced by a constant zero, list length
untouched, so the length guard cannot be what notices): **24 of 24 caught**.

## 16. Files

| | |
|---|---|
| `execnode/shielded_state.py` | notes, per-contract trees, nullifier set, predicates, the verifier seam |
| `execnode/exec_root.py` | tags 11/12 and the records projection |
| `execnode/state.py` | `ExecState.app_state`, persistence, `op: private_call` |
| `execnode/execnode.py` | `GET /exec/private_state` |
| `tests/test_shielded_state.py` | 24 soundness checks — the specification the circuit gets diffed against |
| `tests/test_shielded_state_root.py` | 10 checks, three of which pin the compatibility invariant |
| `tests/test_shielded_state_exec.py` | integration checks, including the turnstile |
| `tests/test_shielded_state_seam.py` | the proof-only path: 12 checks, one real proof |
| `tests/test_shielded_state_da.py` | a real 24.7 MiB proof through Reed-Solomon k-of-n |
| `tests/test_shielded_state_replay.py` | the adversarial suite — replay, aliasing, bounds, geometry |
| `tests/test_shielded_state_atomicity.py` | every rejection path leaves the pool untouched |
| `tests/test_shielded_vault_e2e.py` | **the worked example** — deposit, private transfer, withdrawal |

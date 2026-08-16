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
| `KIND_VALUE` | `[amount]` | `Σ in + public_delta = Σ out`, every amount in `[0, 2^62)` |

A new private app is a new kind plus a predicate. Conservation is one possible rule, not the law: a
hidden-hand note in a card game conserves nothing and only has to be well-formed.

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

**2. Tree depth 12 → 20 is free, and 20 is exactly the ceiling.** Trace length is
`next_pow2(385 + 81·D + 1)`, so every depth up to 20 lands on `T = 2048`; depth 21 gives 2086 and crosses
to `T = 4096`, doubling the prove. `TREE_DEPTH = 20` (1,048,576 notes per contract) is therefore the
largest tree that costs nothing extra — chosen by measurement, not by taste. Do not raise it to 21.

**3. ~13 s per proof on a server core.** That is the delegated-prover figure, and it is the honest input
to the client-side question: a phone is not this box. The Phase-3 decision (WASM prover vs. a blind
delegated one) should be made against a measured phone number, not this one.

## 13. What would sink it

Proving cost, not cryptography. Putting a private call through the VM AIR multiplies the trace by every
step of the call, and this chain has already met the ceiling from the other side — a settle span of 119
record updates was declined on 2026-08-16 because the proof would have been ~1 794 MiB against
`SETTLE_INLINE_MAX` and taken ~5 355 s to build. The 13 s above is for a ONE-note transition with a fixed
statement; a general private call is strictly more.

## 14. Files

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
| `tests/test_shielded_vault_e2e.py` | **the worked example** — deposit, private transfer, withdrawal |

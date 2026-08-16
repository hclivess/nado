# Shielded contracts — private application state

> **Status: PHASE 1 BUILT, INERT.** The state machine, its binding into the settled root and the
> `private_call` op are implemented and tested. `CONSENSUS_ALLOW_TRANSPARENT` is `False`, so every
> transition is refused today — the feature starts doing work when the Phase-2 circuit lands. Merging it
> changes no root and no snapshot on a chain that holds no private state.

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

## 4. Transition rules are per-kind predicates

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

## 5. What the chain commits

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

## 6. `op: private_call`, and why it is not `op: call`

`calls_commit.block_calls` collects only `op == "call"` into the settlement calls list, and a call the
chain skips or reverts makes the **whole span unprovable** (ROADMAP, 2026-08-06). A private call is
rejected whenever its proof does not verify — something any user can cause at will. Routing it through the
zkVM call path would therefore hand every user a lever to switch the chain off validity proofs, one bad
proof per span. As its own op it is invisible to `block_calls`, so a rejection is a pure no-op.

`tests/test_shielded_state_exec.py` builds a real block carrying a `private_call` blob and asserts
`block_calls` ignores it. Do not "simplify" this into a contract call.

**Unbacked-mint fence.** `public_delta` must be `0`. A blob is user-supplied and escrow-free, so a nonzero
delta would create or destroy value nothing on the other side accounts for — the hole
`apply_field_transfer` fences with *"coins enter only via an L1 shield"*. Private state may be rearranged
today; funding and draining it against the contract's own balance is its own slice, because it must move
that balance in the same mutation to be sound.

## 7. Phased, like the pool it extends

- **Phase 1 — built.** `verify_transition` re-checks openings, membership, nullifier and commitment
  derivation in the clear. Sound — no double-spend, no forged membership, no predicate violation — but not
  private, because the witness carries `nsk`. It is scaffolding: it freezes the state machine and its
  soundness suite *before* the circuit, so the AIR can be diffed against a specification that already
  exists. `CONSENSUS_ALLOW_TRANSPARENT = False` keeps it off any chain.
- **Phase 2 — next.** `proof` becomes a STARK over the same statement and the verifier sees only `public`.
  The state machine does not change; only what sits behind the seam does. Route: the zkVM AIR
  (`vm_circuit.py`) with a private input tape, rather than per-contract circuits — one VM, one circuit,
  one thing to get right. Per-contract AIRs are an optimisation for hot paths once cost is measured.
- **Phase 3 — the real bar.** Client-side proving. Today `shielded_field.py` hands the exec node the
  witness, so the pool is private from the chain but **not from whoever runs the exec node**. Until a WASM
  prover ships, the honest phrasing is "private except from the operator". The kernels are already native
  Rust, so this is a target and a witness-generation path, not a new prover.

## 8. What would sink it

Proving cost, not cryptography. Putting a private call through the VM AIR multiplies the trace by every
step of the call, and this chain has already met the ceiling from the other side — a settle span of 119
record updates was declined on 2026-08-16 because the proof would have been ~1 794 MiB against
`SETTLE_INLINE_MAX` and taken ~5 355 s to build. The number that decides this is **proving seconds per
private call on a phone**, and nobody has measured it. That measurement belongs before the circuit work,
not after it.

## 9. Files

| | |
|---|---|
| `execnode/shielded_state.py` | notes, per-contract trees, nullifier set, predicates, the verifier seam |
| `execnode/exec_root.py` | tags 11/12 and the records projection |
| `execnode/state.py` | `ExecState.app_state`, persistence, `op: private_call` |
| `execnode/execnode.py` | `GET /exec/private_state` |
| `tests/test_shielded_state.py` | 24 soundness checks — the specification the circuit gets diffed against |
| `tests/test_shielded_state_root.py` | 10 checks, three of which pin the compatibility invariant |
| `tests/test_shielded_state_exec.py` | 9 integration checks |

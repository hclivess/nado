# Program obfuscation on NADO — a research goal

**Status:** research goal. Nothing in this document is implemented, scheduled, or promised. It exists to
state precisely *what* we would be chasing, *why* it would matter for this chain specifically, and — most
importantly — *what would have to be true* for it to be worth chasing. The honest summary is at the end of
§6: the assumptions this rests on are young and have already been broken in neighbouring formulations, so
the correct posture today is to track, reproduce and measure, not to build on.

---

## 1. The one-sentence goal

**Put a program on-chain that anyone can run but nobody can read.**

NADO can already do the first half of that sentence's opposite: `execnode/` proves *what a program did*
without re-executing it (STARKs over the exec VM, `execnode/stark/vm_circuit.py`). What it cannot do is
*hide what the program is* while still letting the network run it. Every contract deployed today is public
bytecode; every input to it is public; the privacy work in `doc/privacy.md` hides **values** (notes,
nullifiers, Merkle exits), never **logic**.

Obfuscation is the primitive that closes that gap.

---

## 2. What "obfuscation" means here, exactly

Not minification. Not anti-tamper. The cryptographic notion:

> **Indistinguishability obfuscation (iO).** An efficient algorithm `iO` such that for any two circuits
> `C₀`, `C₁` of the *same size* that compute the *same function*, the distributions `iO(C₀)` and `iO(C₁)`
> are computationally indistinguishable.

That definition looks weak — it only says you cannot tell two functionally identical programs apart — and
it is famously much stronger than it looks. iO implies functional encryption, deniable encryption, witness
encryption, non-interactive multiparty key exchange, and a long list of primitives with no other known
construction. It is the closest thing cryptography has to a universal tool.

The reason nobody uses it is cost. The 2020 line of work (Jain–Lin–Sahai, "iO from well-founded
assumptions") settled the *existence* question from standard-ish assumptions but produced constructions
whose overhead is measured in astronomical factors — correct, polynomial, and completely unusable. Every
practical attempt since has been about finding a construction whose constant factors are merely terrible
rather than impossible.

### What iO does NOT give you

Worth stating up front, because it is routinely oversold:

- **It is not encryption of inputs.** An obfuscated program still sees its inputs in the clear when it runs.
  Hiding inputs is FHE's job, or a note/nullifier scheme's.
- **It does not hide the function's behaviour.** Anyone can run the obfuscated program on any input and
  observe the output. If the function is learnable from its input/output behaviour, obfuscating it protects
  nothing. iO hides the *implementation*, not the *extension*.
- **It does not prevent the program from being run.** An obfuscated program is a program.

So the useful applications are exactly the ones where the function is *unlearnable* from black-box access:
it embeds a secret that the outputs do not reveal.

---

## 3. Diamond iO — why this one is worth watching

**Diamond iO** (Sora Suegami and Enrico Bottazzi, 2025; implementation effort under the *Machina iO*
banner) is the first construction in a while that is simple enough to read in an afternoon and concrete
enough that people have written code against it. The claimed contribution is a *straightforward* iO from
lattices — no FHE-plus-functional-encryption bootstrapping tower, no multilinear maps.

The shape, at the level of detail that matters for deciding whether to invest:

- It builds on the **BGG+ attribute-based encoding** — the same lattice gadget behind key-policy ABE, where
  encodings of attributes can be homomorphically evaluated through a circuit.
- The circuit is evaluated over encoded attributes; correctness comes from the usual lattice
  noise-growth argument; security comes from an **evasive-LWE-style assumption** plus a pseudorandomness
  assumption on the relevant matrix products.
- The "diamond" is the structure used to keep the object from blowing up across the circuit's depth.

Two properties make it interesting *to NADO specifically*:

1. **It is lattice-based, therefore plausibly post-quantum.** NADO is a post-quantum chain by
   construction — ML-DSA-44 signatures (`signatures.py`), hash-based commitments, STARKs rather than
   pairing-based SNARKs. A pairing-based obfuscation scheme would be architecturally off-brand here;
   a lattice one is not.
2. **There is running code.** A construction with an implementation can be *measured*, and measurement is
   the only thing that settles the "is this usable" question. Reading a paper cannot.

> **Reference hygiene.** Cite the paper by title and authors — *"Diamond iO: A Straightforward Construction
> of Indistinguishability Obfuscation from Lattices"* — and confirm the ePrint identifier and the current
> version before quoting any parameter, bound, or benchmark from it. This document deliberately quotes no
> numbers: the ones in an actively-revised preprint go stale, and a stale benchmark repeated confidently is
> worse than no benchmark.

---

## 4. What NADO would actually do with it

Ordered by (usefulness × plausibility), best first. Note that the first two need *far* less than full iO,
which is the whole point of listing them first.

### 4.1 Compute-and-compare / point-function obfuscation → witness encryption for a fixed predicate

The weakest useful case, and the one with the best odds: obfuscate a program that outputs a secret **iff**
the input satisfies a check. This is *lock obfuscation*, it is achievable from plain LWE (no evasive
assumption), and it gives a usable form of witness encryption.

On-chain that buys: **a sealed value that unseals itself when a public on-chain condition is met** — a
sealed-bid auction where bids open only after the deadline, a dead-man's switch, a time-lock whose key
nobody holds. Today those need either a trusted opener or an interactive MPC committee. This is the target
to attempt first, and it does *not* require Diamond iO.

### 4.2 Private contract logic

The headline use: a contract whose *rules* are hidden while its *state transitions remain publicly
verifiable* by the existing STARK machinery. Note how cleanly the two compose:

- iO hides the program.
- The exec-layer STARK proves the hidden program was executed faithfully on the committed state.

Neither primitive substitutes for the other, and together they are strictly more than either. This is the
architecturally interesting claim in this whole document, and it is the reason to care about iO here rather
than in general.

The blunt caveat: the exec VM (`doc/exec-instructions.md`) is a real instruction set with loops and
memory. Obfuscating a *circuit* is one thing; obfuscating an *interpreter for a Turing-complete VM,
bounded to some step count* multiplies the circuit size by that bound. Section 6's cost problem lands
here with full force.

### 4.3 Programmable, non-interactive threshold behaviour

iO implies non-interactive multiparty key exchange, which would let a validator set derive shared secrets
without a DKG ceremony and without the liveness assumptions a DKG carries. Attractive, but strictly
downstream of the first two working at all.

### Explicit non-goals

- **Hiding transaction amounts or participants.** That is `doc/privacy.md`'s job and it has a working,
  cheap answer. iO is the wrong tool and would be a hilariously expensive one.
- **DRM / anti-cheat / "protecting" client code.** Not a chain problem.
- **Replacing the STARK layer.** Integrity and secrecy are different properties; see §4.2.

---

## 5. Why not the alternatives

Any honest case for obfuscation has to survive the comparison, because the alternatives are all cheaper
today:

| Approach | Hides logic? | Trust assumption | Cost today |
|---|---|---|---|
| **TEEs** (SGX/TDX) | yes | hardware vendor + a long history of breaks | ~free |
| **MPC committee** | yes | honest threshold, and liveness | interactive, needs a committee |
| **FHE** | no (hides *inputs*) | lattice assumptions | heavy but shipping |
| **Witness encryption** (from lock obfuscation) | partly | LWE | plausible |
| **iO** | yes | evasive-LWE-family, unsettled | prohibitive |

The row that matters: **iO is the only one with no trusted party and no interaction.** That is a real,
qualitative difference from every other row — a TEE moves trust to Intel, an MPC committee moves it to a
threshold-honest quorum, and both are exactly the kind of assumption a chain like this exists to avoid. It
is also the only row where the cost column says "prohibitive". Both halves of that sentence are the point.

---

## 6. The part that decides everything: is the assumption sound?

**Evasive LWE is not a settled assumption.** Several formulations proposed since 2022 have been shown to be
false, by explicit counterexamples rather than by weakening — the pattern being that a formulation general
enough to be *useful* for the construction is often general enough to be *attackable*, and the fix is to
narrow the assumption until it is nearly as specific as the scheme that needs it.

This has two consequences and they are the whole risk story:

1. **A break invalidates the construction, not just a parameter choice.** This is not "raise the modulus".
   There is no security margin to tune when the assumption itself is the thing that fails.
2. **"Nobody has broken this particular variant yet" is a much weaker statement here than it is for, say,
   Module-LWE**, which has had two decades of concentrated attention and a NIST standardisation process
   pointed at it. Diamond iO's assumptions have had neither.

Add the practical problem: even granting soundness, obfuscated objects for anything resembling a real
program are enormous, and the object has to be *distributed to every node* and *evaluated* by them. A chain
is close to the worst possible deployment target for a primitive with a large per-program constant — it is
inherently a broadcast medium.

**Therefore the position of this document is: track, reproduce, measure — do not build on.** A design that
assumes iO works is a design that has to be thrown away if it does not.

---

## 7. A concrete research program

Each milestone is falsifiable and each one ends in a number or a "no". That is deliberate: the failure mode
for a topic like this is a year of reading.

**M1 — Reproduce.** Build the reference implementation. Obfuscate the smallest non-trivial circuit it
supports. Record: object size, obfuscation time, evaluation time, peak memory, and the parameter set that
produced them. Deliverable: a table, plus a note on what broke.
*Kill criterion:* the smallest supported circuit does not fit in a node's memory budget.

**M2 — Scale curve.** Measure how object size and evaluation time grow with circuit size and depth over
whatever range is feasible. Extrapolate to the smallest genuinely useful NADO program. Deliverable: the
curve, and the extrapolated cost of one real contract.
*Kill criterion:* the extrapolation exceeds a block interval by more than ~3 orders of magnitude with no
identified path down.

**M3 — Assumption review.** Write down the exact assumption the implementation relies on — not the paper's
general statement, the specific instance. Check it against the current counterexample literature. This is a
literature task with a written verdict, and it is the milestone most likely to end the program.
*Kill criterion:* the specific instance is covered by a known counterexample, or nobody can state it
precisely.

**M4 — The cheap win, done properly.** Independently of M1–M3: implement compute-and-compare obfuscation
from plain LWE (§4.1) and wire it to a real on-chain condition. This is the milestone with actual expected
value — it needs no evasive assumption, and a sealed-bid auction that opens itself is a feature this chain
could ship.

**M5 — Composition sketch.** *Only if* M1–M3 all pass: specify how an obfuscated program's execution would
be proven by the existing exec-layer STARK (§4.2). What does the AIR commit to? What is the public
statement? Where does the obfuscated object live — in state, or in a DA blob referenced by hash?

### What would change the verdict

- A formulation of the underlying assumption that survives sustained attention (say, two years and a
  standardisation-adjacent process), **or** a construction from Module-LWE alone.
- Object sizes for a useful program within a small multiple of what a block can carry.
- An independent implementation agreeing with the reference on both output and cost.

---

## 8. Reading

- Suegami & Bottazzi — *Diamond iO: A Straightforward Construction of Indistinguishability Obfuscation from
  Lattices* (2025), and the Machina iO implementation. **Confirm the ePrint ID and version before citing.**
- Jain, Lin & Sahai — *Indistinguishability Obfuscation from Well-Founded Assumptions* (2020). The
  existence result; read for what "polynomial but unusable" means concretely.
- Wee — the evasive-LWE line, and the counterexample papers that followed it. Read these **before** the
  construction papers, not after: they are what determines whether any of it stands.
- Wichs & Zirdelis; Goyal, Koppula & Waters — compute-and-compare obfuscation from LWE. This is §4.1 and
  it is the part that is actually buildable.
- `doc/privacy.md` and `doc/execution-layer.md` — what NADO already hides and already proves, which is the
  baseline any of this has to beat.

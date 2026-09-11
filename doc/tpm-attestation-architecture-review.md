# Attestation architecture: what a day of real hardware taught us

Written 2026-09-11, after the first end-to-end attempts against a real AMD firmware TPM. Sixteen
commits in eighteen hours. This is what they were, what they have in common, and what the design
should be instead.

## The evidence

Every defect found against real hardware, by class:

| # | Defect | Class |
|---|---|---|
| 1 | kernel emits `ek_identity`, four callers read `identity` | integration seam |
| 2 | `tpm_enrol` missing from the empty-account bypass | liveness |
| 3 | `challenger_set` body kept `registry[a]["bonded"]` after the signature changed | integration seam |
| 4 | `tpm_*` missing from the flexible-landing set — could never be included | liveness |
| 5 | client silently used the operator's production keyfile | integration seam |
| 6 | AIA URL read past the IA5String length | parsing |
| 7 | HTTP client defaulted every host to port 9173 — hung | integration seam |
| 8 | `tpm:` row prefix collided with WebAuthn device bindings | integration seam |
| 9 | challenger loop gated on bonded while the draw moved to producers | integration seam |
| 10 | draw from stake (1%) → producers (0.2%) → duty senders (20%) | liveness |
| 11 | challenge `max_block` past the landing window — every answer refused | liveness |
| 12 | derived enrolment id + no purge = a chip wedged permanently | liveness |
| 13 | the same unclamped `max_block` again, in self-enrolment | liveness |

**Not one of them was cryptographic.** The core — `MakeCredential` determinism, the commit–reveal, the
`certify` check, the chain verification against pinned vendor roots — worked the first time it touched
silicon and never broke once. Seven of thirteen were liveness. The rest were seams between parts.

## What the architecture actually bought

The four-message exchange exists to establish exactly one property:

> the prover must not learn the secret before it commits.

That is a small property, and the design pays for it with a protocol that is **multi-party,
multi-round, strictly ordered, and time-bounded**. Each of those adjectives is a failure mode, and each
one produced defects above:

- **multi-party** → depends on *k* strangers being alive *and* on current code (10, 11)
- **multi-round** → four inclusions, minutes at best, nothing pipelines (4)
- **strictly ordered** → cannot batch or retry a single step (12)
- **time-bounded** → a stall becomes an expiry becomes a permanent wedge (12)

The measured cost: a user watching `1/3 challengers have answered` for 34 minutes, because two drawn
nodes were alive, healthy, producing blocks, and running a binary from before a fix. Nothing was wrong
with the chip, the chain, the prover, or those two operators.

## The alternative I proposed, and why it is worthless

**RETRACTED 2026-09-11, same day. The proposal below is trivially forgeable. It is kept here in full
because the mistake is more instructive than the proposal was, and because someone will think of it
again.**

The idea was to avoid the interactive step by creating the attestation key as a *child* of the
endorsement key and having it certify its own creation:

```
TPM2_CreatePrimary(endorsement, EK template)   -> the vendor-certified key
TPM2_Create(parent = EK, AIK template)         -> outPublic, outPrivate, creationData, ticket
TPM2_Load(EK, outPrivate, outPublic)
TPM2_CertifyCreation(sign = AIK, object = AIK, qualifyingData, creationHash, ticket)
```

`TPMS_CREATION_DATA` carries `parentName`, which any verifier derives from the vendor certificate plus
the fixed TCG template. Every one of those commands works — verified against a real TPM 2.0 in
`tests/test_tpm_certify_creation.py`, nine checks, all passing. The commands are not the problem.

The problem is the verification. A verifier would check: TPM_GENERATED magic, ATTEST_CREATION type,
creationHash matches creationData, `parentName` equals the certified endorsement key's name, signature
verifies under the child's public area, child is `restricted` and `sign`.

**All six pass on a message produced with no TPM at all.** `tests/test_certify_creation_is_forgeable.py`
constructs one: generate an RSA key in software, write a `creationData` naming the victim's endorsement
key — the certificate is public, so the name is public — write a `TPMS_ATTEST` by hand, and sign it with
the software key. Every field the verifier inspects is a field the forger authored.

### Why it fails, stated so it is not re-proposed

Follow the signatures, not the fields:

- the vendor's signature covers the **endorsement key's public key**, and nothing else;
- the creation attestation is signed by the **child**, which is the key whose provenance is in question;
- `parentName` is a claim *inside* a blob signed by the claimant.

There is no signature path from the vendor to the signing key. The WebAuthn `tpm` path works precisely
because there is one: `x5c[0]` is an AIK **certificate**, so a CA's signature reaches the signing key and
the message closes. Ours had no such certificate — that absence is the entire reason this work exists.

### And the hardware refuses it anyway

Measured on the AMD firmware TPM the same day, through the `check-creation` probe:

```
[1/5] endorsement key derives ............ OK  314 byte public area
[2/5] its name is derivable .............. OK  a verifier can recompute it
RESULT: [3/5] TPM2_Create under the endorsement key FAILED (0x0000008b)
```

`0x8b` is format-one, error `0x0b` = `TPM_RC_HANDLE`, with no handle number — the chip rejecting the
endorsement key as a parent handle outright, before any policy or authorisation is evaluated. So the
proposal was dead twice over: forgeable in principle, and unsupported by the only silicon we have.

That second fact is worth keeping on its own. **An AMD fTPM will not act as a storage parent from its
endorsement key.** Anything that assumes otherwise — on this vendor at least — is designing against
hardware that does not exist.

It also tells us nothing about `PolicySecret`. The refusal happened at handle validation, before the
endorsement hierarchy authorisation was ever reached, and steps 1 and 2 are a ReadPublic and a local
hash. `ActivateCredential` against the `adminWithPolicy` endorsement key is exactly as untested after
this probe as before it.

### The constraint, which is not an implementation detail

An endorsement key is a restricted **decryption** key. No signature by it can exist, ever. So the only
operation that demonstrates possession of it is decrypting something the prover could not predict, and
"could not predict" requires a party other than the prover to have chosen it. That is interactive by
construction.

The original design note said this in its second paragraph and listed "derive the challenge from public
data" among the shortcuts that do not work. This proposal was the same shortcut wearing a TPM command as
a disguise: it replaced *predicting a secret* with *asserting a parent*, and an assertion signed by the
asserter is not evidence.

## What actually follows from the day

The four-message exchange is not accidental complexity. It is the cost of the one thing that cannot be
avoided, and the defects listed above are not evidence against it — they are evidence that the
*surrounding machinery* was under-engineered, which is a different claim and a fixable one.

What is worth taking from the experience:

- **Seven of thirteen defects were liveness, and every one had a local fix.** Landing windows, draw
  eligibility, retry on stall, superseding a dead record. None required changing the protocol.
- **A stalled draw now costs three minutes, not an hour**, because a new attestation key is a new
  enrolment id and therefore a fresh draw. That is the real answer to the latency complaint, and it
  needed no security change at all.
- **Any duty that swallows its own exceptions must publish its last outcome.** `tpm_duty` found the next
  defect in seconds after three had each cost a debugging cycle.
- **A stub can only confirm that the caller agrees with itself.** Two defects passed their tests because
  the tests stubbed the thing that changed.

And one about judgement: an architecture proposal that removes the only expensive part of a protocol
should be assumed wrong until someone has tried to forge it. I wrote the document and a passing
hardware test before attempting the forgery, which took twenty lines and worked on the first try.


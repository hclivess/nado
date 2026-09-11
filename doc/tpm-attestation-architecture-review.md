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

## The alternative: prove it with the chip alone

The commit–reveal exists because **an endorsement key cannot sign**, so possession must be shown by
decryption, which is interactive. That is true — but it is not the only way to bind an attestation key
to an endorsement key.

An EK is `restricted | decrypt | adminWithPolicy`: it is a **storage parent**. So create the attestation
key *as a child of the EK*, and have it certify its own creation:

```
TPM2_CreatePrimary(endorsement, EK template)          -> the vendor-certified key
TPM2_Create(parent = EK, AIK template)                -> outPublic, outPrivate, creationData, ticket
TPM2_Load(EK, outPrivate, outPublic)                  -> the AIK
TPM2_CertifyCreation(sign = AIK, object = AIK,
                     qualifyingData, creationHash, ticket)
```

`TPMS_CREATION_DATA` carries `parentName`, and `parentName` is `nameAlg ‖ H(EK pubArea)` — derivable by
any verifier from the public key in the vendor's certificate plus the fixed TCG template. The creation
ticket proves the TPM itself produced that creation data. The AIK is `restricted`, so it signs only
structures the TPM generated.

A verifier then checks, **offline, from one message**:

1. the EK chain reaches a pinned silicon-vendor root;
2. the AIK public area is `restricted`, `sign`, `fixedTPM`, `fixedParent`, `sensitiveDataOrigin`;
3. `creationData.parentName` equals the EK name derived from that certificate;
4. `creationHash` matches the creation data;
5. the `TPM_ST_ATTEST_CREATION` signature verifies under the AIK.

If all five hold, that attestation key was created inside a TPM holding that vendor-certified
endorsement key, and cannot be moved out of it.

## What that removes

| removed | defects it caused |
|---|---|
| the challenger draw | 10 |
| *k*-of-*k* liveness dependency | 10, 11 |
| four-message ordering | 4 |
| the expiry window | 12 |
| supersede and the one-per-chip bound | 12 |
| the challenger duty loop | 9, 11 |

Enrolment becomes **one transaction, verified offline like any certificate**. Registration is unchanged:
a fresh `TPM2_Certify` over that block's own challenge, which is what supplies freshness and already
works on real silicon.

## What it costs, honestly

- **The AIK stops being a derived primary.** A child key's private blob must be stored by the client
  and re-loaded, so the client keeps a small file. Today's AIK is recomputed from a template and needs
  no state. This is a real regression in operational simplicity, and it is worth it.
- **The EK's policy must be satisfied to use it as a parent** — `PolicySecret` against the endorsement
  hierarchy, the same session `ActivateCredential` needs. That path has still never run on real silicon,
  so this does not dodge the one genuinely untested step; it reuses it.
- **`TPM2_CertifyCreation` is unverified here.** Every claim above is from the TCG specification, not
  from a chip. It must be run against the AMD fTPM before any of this is believed. If a firmware TPM
  refuses the EK as a parent, the whole alternative collapses and the commit–reveal stays.
- **It does not help a chip with no endorsement certificate.** That is orthogonal and unchanged.

## What to keep regardless

The commit–reveal is a genuinely good construction and the paper should keep it: it removes a
certificate authority using nothing but the determinism of a TPM command and an agreed ordering. What
today showed is that it is the *wrong tool for a user-facing enrolment*, because it converts a local
hardware fact into a distributed-systems problem. It remains the right tool where no better binding
exists — and the reason a better one exists here is narrow: the EK happens to be usable as a parent.

## The process lesson, which is separate

Two defects (1 and 3) passed their tests because the tests **stubbed the thing that changed**. A stub is
written from the caller's side and can only confirm that the caller agrees with itself. Both were caught
in production, on a user's machine, by a person watching output.

Three more (4, 11, 12) were invisible from the server because the challenger duty catches its own
exceptions so a failure cannot stop block production — which also means the reason never leaves that
machine. The `tpm_duty` field added partway through found the next one in seconds.

**Any duty that swallows its own failures must publish its last outcome.** That is cheap, and it is the
single highest-value change made today.

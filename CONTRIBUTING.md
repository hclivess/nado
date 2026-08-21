# Contributing to NADO

Thanks for your interest. This document covers the legal and process requirements for
contributions; technical orientation lives in `doc/README.md`.

## Licence of contributions

NADO is licensed under the **GNU Affero General Public License v3.0** (`LICENSE`). By
submitting a contribution you agree that:

1. It is licensed to the project and its users under **AGPL-3.0-or-later**, and
2. You have the right to do so — it is your own work, or you have permission from the
   rights holder (e.g. your employer), and it is not copied from incompatibly-licensed code.

No separate CLA is required.

## Developer Certificate of Origin

We use the [DCO 1.1](https://developercertificate.org/). Sign off every commit:

```
git commit -s
```

which appends `Signed-off-by: Your Name <you@example.com>`. The name must be a real name or
a consistently-used handle; the email must be one you control. Unsigned commits may be
rejected.

## Third-party code

- Do not vendor code without recording its origin and licence in `legal/NOTICE.md`.
- Only AGPL-compatible licences are acceptable (MIT, BSD, Apache-2.0, MPL-2.0, LGPL, GPL).
  **Not** acceptable: proprietary, "source-available", non-commercial, SSPL, BUSL, or
  code whose licence is unknown.
- Cryptographic primitives must reference a published specification (e.g. FIPS 204 for
  ML-DSA). Do not submit home-grown primitives without a design document in `doc/`.
- AI-assisted contributions are welcome; you remain responsible for their licensing,
  correctness and for the DCO attestation.

## Consensus-affecting changes

Anything that changes block validation, the state root, the execution layer's determinism,
or the peer protocol is a **hard fork** and will require a coordinated chain reroll. Such
PRs must:

- Explain the change in `doc/` and `RELEASE_NOTES.md`,
- Keep `tests/` green, including the determinism tests,
- Be discussed with maintainers before you invest significant effort.

## Security issues

Do **not** open a PR that silently fixes a vulnerability. Follow `SECURITY.md` so the fix
and disclosure can be coordinated with validators.

## Conduct

All participation is subject to `CODE_OF_CONDUCT.md`.

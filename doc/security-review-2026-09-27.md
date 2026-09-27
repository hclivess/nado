# Closing the 2026-09-24/25 audits (2026-09-27)

Twenty-two read-only audit reports came back on 2026-09-24 and 2026-09-25. On 2026-09-27 every finding in them was
checked against the deployed code (main at c314d790) and the unreleased zk-harden branch, and each was marked FIXED
(with the guarding code), OPEN, MOOT or UNCLEAR. About 145 finding rows resolved into ~56 fixed and ~50 distinct defects
still open.

This record exists because one report — the wallet signing audit of 2026-09-25 — sat unactioned for a day while
its HIGH finding stayed exploitable. A report that is not tracked to closure is the same as no report.

**This document lists what is FIXED.** Open findings are tracked privately until each is fixed. The repository is
public, and a list of unfixed holes is a how-to. Each fix below ships with a test that fails on the code it replaced.

---

## Wallet

**Silent signing followed `ret`, not the caller (HIGH) — c314d790.** `?exec_sign=<blob>&ret=https://chess.nadochain.com/`
is a link anyone can send. The wallet decided trust from `ret`, and value-free autosign is on by default. So such a
link made a default wallet sign any value-free contract call with no tap: `resign` in a staked game pays the pot to the
opponent. With the opt-ins it signed bets up to the cap (compared in NADO units even for an asset) or any blob op.
Reproduced against the previous `interface.js`: signed silently.

The fix:
- Silent signing now requires the caller — `e.origin`, or the referrer's origin — to be the trusted site `ret` names.
  Measured in Chromium that a real cross-origin redirect carries it.
- A `javascript:`/`data:` `ret` is refused instead of navigated to.
- Hidden-frame answers go to the sender only.
- "Auto-sign everything" signs contract calls only.
- The confirm shows `to`, asset, `spender` and arguments.
- Multisig co-signers confirm before signing.
- The quoted fee is capped at 100 × `MIN_TX_FEE`.

`doc/api.md` §6 has the rule dApps must follow. Test: `tests/test_exec_sign_trust.mjs`.

**Bet page stored XSS (HIGH) — be800a17.** A market's outcome label, chosen by its creator, reached two `innerHTML`
sinks unescaped on a page that shares an origin with the wallet. Test: `tests/test_bet_labels_escaped.mjs`.

**A lying relay (HIGH) — 9f77acc5.** Pool heights are self-reported. The wallet took their MAX for the propagation
guard, the failover bar and the ranking, adopted a candidate on its own word when home was down, and downloaded the TPM
helper from whatever relay it was on. Now:
- The tip estimate is capped at median + 30.
- A failover candidate must be corroborated by another relay.
- The helper comes from home only.
- `/relays` clamps peer heights.

`doc/relays.md`. Test: `tests/test_relay_trust.mjs`.

## Node

**A private key was served publicly (CRITICAL) — 6a6d5517.** The TPM enrolment helper writes its signing identity as
`nado-identity.json` beside itself. A run from `static/` on 2026-09-11 left one there, served with HTTP 200 on every
public host for 16 days. The node now refuses, with a 404:
- dotfiles;
- key-material names;
- any file its owner made unreadable to others (how a program writes a secret; no download has that mode).

Treat whatever that identity signed or held as exposed from 2026-09-11. Test: `tests/test_static_never_serves_secrets.py`.

**Memory exhaustion (HIGH/MEDIUM) — 9a15ed85, 58629338, d82b12be.**
- `/tpm_proof_drop` stored every drop before checking it, with no rate limit. It is now throttled, stores only accepted
  proofs, and is capped.
- `/submit_transaction` judged a chunked body (no length) as small, skipping the large-body limit. It is now judged
  large, with at most two large bodies in flight node-wide.
- The proof-verification queue is bounded.
- Peer control messages are read under an 8 MiB cap instead of ~200 MiB.

Tests: `test_tpm_proof_drop_bounded`, `test_submit_body_bounds`, `test_proof_queue_bounded`, `test_control_reads_capped`.

**Update kicks dropped (operational) — d4abb4a4.** A kick that landed on a busy or rate-limited update check was
dropped, and the node stayed a commit behind until its 15-minute timer. Measured: 185.238.249.208, 12 minutes after a
push. Such a kick now queues one deferred re-check. Test: `tests/test_update_kick_never_lost.py`.

**Jobs report (operational) — ce75f17a.** Units whose state cannot be read were reported as "not installed". They are
now listed under `jobs.unreadable`. Test: `tests/test_jobs_report.py`.

## Execution layer (zk-harden branch, dormant until `ZK_HARDEN_HEIGHT`)

**Asset instructions settle by proof.** Every settle proof refused asset io, so an asset-touching span could only
settle by quorum. From the gate the L1 verifier binds asset moves against the pinned records pre-state
(`records_bind.PinnedAssets`) — issuer, supply cap, holdings, and every `ABAL` read. `doc/assets.md` §8.

## Tests that were quietly wrong

Found while making the full suite green on the release candidate (408 of 424 passing at first):
- Four tests read the **live checkout** by absolute path, so from a worktree they checked the deployed file. Three had
  gone stale unnoticed; one hid a real theme bug. The isolation guard now covers `.mjs` tests and refuses any test that
  names the node key's path.
- A manual live test derived an identity from the node's own `private/keys.dat` (rule 8). It now reads a dedicated test
  identity.
- The ERC-20 swap test depended on hand-built files in `/tmp` whose sources were never committed. It now compiles
  committed fixtures and starts its own EVM.
- The TPM tests could not run under the runner, which lacked their oracle library. The runner now uses an interpreter
  that has it; the node itself still does not depend on it.
- Four slow tests each passed in 25–27 minutes but always hit the 900 s timeout.
- The lobby, emission and production pages had been updated on the server and never committed. The test's suggested
  fix would have reverted the live site.

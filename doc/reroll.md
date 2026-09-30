# Reroll runbook and the gate ledger

A **reroll** restarts the chain from a fresh genesis (new `CHAIN_ID`, `GENESIS_TIMESTAMP` and
`CHAIN_GENERATION`), carrying balances forward. This document is the procedure, the failure modes that have actually
happened, and — since 2026-09-09 — the rule that makes the *code* cleanup mechanical instead of archaeological.

## The gate rule

**Every consensus gate is written `<live height> if CHAIN_GENERATION == <gen> else <x>`.** Never a bare height.

A bare height silently survives a reroll: `POOL_HEIGHT = 6000` on a fresh chain means the rule is off for the first
6,000 blocks of a chain that was supposed to start with it. Writing the branch instead means a reroll needs no edit at
all — bump `CHAIN_GENERATION` and every rule lands where a fresh chain wants it:

| `else` value | meaning on the fresh chain | what the cleanup does |
|---|---|---|
| `1` | live from block 1 (or epoch 0) | delete the branch, inline the rule as unconditional |
| `0` | the feature never turns on | delete the gate **and its code path** |

`tests/test_gate_reroll_transfer.py` pins both halves of every live line: that the live value still equals what the
chain uses (a reroll edit must never change live consensus) and that the reroll value is the documented one. A new
gate added without a branch fails that test, and so does a cleaned-up gate that comes back.

**Inlining an `else 1` gate is not deleting the comparison.** A rule "live from block 1" is still OFF at height 0, and
height 0 is reachable: genesis, mempool admission while the tip is genesis, the exec state at cursor -1/0, a tx whose
own `max_block` is 0. Wherever such a caller can reach the check, the cleanup keeps `>= 1` (the gate's own value) so
no verdict moves; only where the height is provably >= 1 does the comparison go.

### The ledger (gen 28, betanet-9)

No generation-keyed gate is live on gen 28; the next one added is keyed `== 28`. ZK hardening (`ZK_HARDEN_HEIGHT`, zk audit 2026-09-26: ARG-bus tags, settle pre_contracts shape, NOP provable, wide pool depth 48, asset instructions settle by proof, the 4-element settle calldata binding — execnode/stark/calls_commit.py "THE BINDING IS WIDE") is unconditional from block 1; the narrow binding answers only at cursor 0.

**Every gen-27 gate is gone** (slice 3 below). The rules they switched on are unconditional; what each one is for:
the device binding keys on the certificate's signed part (`DEVICE_BIND_CANONICAL_HEIGHT`); no free repeatable
transaction — key allowlist + size caps, msgkey first bind only, tpm_ready bonded, one enrolment per chip per block,
settle/xmsg paid outside the duty, one device move per epoch (`SPAM_HARDEN_HEIGHT`, doc/security-review-2026-09-27.md);
the TPM enrolment's challengers are drawn from the endorsement identity and the beacon two epochs after the enrol
(`TPM_DRAW_UNGRINDABLE_HEIGHT`, ops/tpm_enrol "COMMIT, THEN DRAW"); an EK certificate is judged against the roots in
force at its height (`EK_ENROL_ROOTS_AT_HEIGHT`); a DA-carried op whose proof never arrives is refused once finality
passes its block + `EXEC_DA_WAIT_BLOCKS` (`EXEC_DA_DEADLINE_HEIGHT`, audit "exec stall"); certificate validity is judged
at `agreed_time(anchor height)`, never an uncommitted `block_timestamp` (`CERT_CLOCK_HEIGHT`, audit HIGH); an account
carried at its old address because no chain saw its key is claimed by that key (`legacy_claim`; ACCEPTED RISK: a forger
sharing the address's 21 bytes can claim first); every txid-excluded witness is exact-length lowercase hex and a
list-signed tx carries no top-level `public_key` (`TX_HEX_CANONICAL_HEIGHT`, audit MED — signer re-signing,
public_key strip/add and entry reorder/drop stay open: they need a witness-free block hash); the winner's block
signature names `CHAIN_GENERATION` and the genesis hash, so another chain's signature is no slash evidence
(`BLOCK_SIG_CHAIN_BIND_HEIGHT`); carried identities earn the dividend from their carried fidelity
(`DIVIDEND_CARRY_EPOCH`); addresses are format 2 (`ADDRESS_FORMAT`).
**The settle stake floor** (`SETTLE_STAKE_FLOOR_HEIGHT`, audit HIGH "lone-settler drain": a quorum-settled exec root
also needs attesting shares above `SETTLE_FLOOR_NUM/SETTLE_FLOOR_DEN` = 1/16 of ALL bonded shares) is unconditional —
**at every reroll, measure** settling stake against `total_bonded_shares` (`/mining_status` and the settle txs of the
last few hundred blocks): 125 of 952 shares on 2026-09-28, ~127 of 966 at the betanet-9 reroll; the floor freezes
settlement if non-settling bonded stake outgrows the settlers 16:1.
`DEVICE_ATTEST_HEIGHT` is a plain `1`, not generation-keyed.

**Every gen-25 gate is gone** (both cleanup slices below). Inlined as unconditional rules after the betanet-8 reroll
(slice 2), with `>= 1` kept only where height 0 can reach the check: `DEVICE_BIND_HEIGHT`, `DEVICE_BIND_STRICT_HEIGHT`,
`DEVICE_BIND_PERMANENT_HEIGHT`, `DEVICE_REBIND_INSTANT_HEIGHT`, `DEVICE_BIND_PERMANENT_EK_HEIGHT`,
`DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT`, `DEVICE_ATTEST_TREZOR_SERIAL_OPTIONAL_HEIGHT`, `DEVICE_ATTEST_EK_HEIGHT`,
`DEVICE_ATTEST_EK_SHORT_HEIGHT`, `DEVICE_ATTEST_EK_ROOTS_V2_HEIGHT`, `DEVICE_ATTEST_EK_PROVEN_HEIGHT`,
`DEVICE_ATTEST_EK_READY_HEIGHT`, `TX_AT_MOST_ONCE_STRICT_HEIGHT`, `PROOF_BIND_HEIGHT`, `EXEC_RULES_V2_HEIGHT`,
`PROOF_BLOCK_SELECTOR_HEIGHT`, `REVIEW_R2_HEIGHT`, `PROOF_TRACE_LDT_HEIGHT`, `PROOF_FIXED_CID_HEIGHT`,
`PRIVACY_PAUSE_HEIGHT`, `PROOF_QUERY_FULL_HEIGHT`, `ADDRESS_KEY_BIND_HEIGHT`, `SETTLE_ANCHOR_HEIGHT`,
`SLASH_DEDUP_HEIGHT`, `EXEC_CTX_CURRENT_HEIGHT`, `EXEC_ROOT_V2_HEIGHT`, `SHIELD_WIDE_HEIGHT`; and the from-epoch-0
gates `LEASE_V2_EPOCH` (with `protocol.lease_v2_at`), `DIVIDEND_ATTESTED_EPOCH`, `DIVIDEND_WEIGHT_CAP_V2_EPOCH`,
`DIV_CARRY_METER_EPOCH`.

Re-anchored, not gated: `CHAIN_CLOCK_CADENCE_DS` (60 on gen 25 = exactly `h*6`; 64 since, a plain value). At every reroll
**measure** the outgoing chain's cadence from its own block timestamps (`(ts[tip] - ts[1]) / (tip - 1)`, and the
last ~10,000 blocks separately) and set the next value to the recent figure in deciseconds; the accumulated
lag resets with the new `GENESIS_TIMESTAMP`. Gen 25 ran 6.69 s overall and 6.5 s recently against a clock that
assumed 6, which is where the 40 h TIME lag came from.

Never, delete the path (`else 0`): none left. `BOND_DEVICE_CAP_HEIGHT`, `BOND_WEIGHT_CURVE_HEIGHT`, `POOL_HEIGHT` and
`OPEN_LANE_EXCLUDE_BONDED_HEIGHT` (with the derived `OPEN_LANE_EXCLUDE_BONDED_EPOCH`) and their `else 1` retire twins
`BOND_ATTEST_OPTIONAL_HEIGHT`, `POOL_RETIRE_HEIGHT`, `BOND_CURVE_RETIRE_HEIGHT`, `OPEN_LANE_EXCLUDE_RETIRE_HEIGHT` were
deleted with their code after the betanet-8 reroll (below); `tests/test_gate_reroll_transfer.py` pins them as deleted.

### What the cleanup deletes

**Done for the savings-lane gates after the betanet-8 reroll (gen 27).** With the four "never" gates at 0 the savings
lane is plain stake with no device, no pools and no exclusion, so:

- `mining_ops.bonded_producer_registry` collapses to `return bonded_registry`;
- `mining_ops.open_lane_draw_registry` collapses to `return open_registry`;
- `mining_ops.bond_weight` and `bond_knee` lose their last caller;
- `reward_ops._pool_split`, the `pool` / `delegate` / `undelegate` transactions, the `pool_*` account fields, the
  `pool_revert` DB and `/pools` all go;
- the retire gates themselves become vacuous and go with them.

Three things deliberately stayed, because deleting them would have changed gen-27 behaviour: `pool`, `delegate` and
`undelegate` remain in `RESERVED_RECIPIENTS` with their per-block uniqueness key, and `validate_transaction` still
refuses them with the message the gen-25 branch raised at `POOL_HEIGHT = 0` ("staking pools are not enabled yet") —
falling through to the generic path would turn a refused tx into an accepted one. `/mining_status` keeps the fields
wallets read, at their fixed gen-27 values (`bond_attest_required: false`, `bond_plain: true`,
`open_excluded_bonded`); `bond_cap_active`, `pools_retired`, `bond_device_cap`, `bond_knee` and the delegation view
went. `tests/test_savings_lane_is_plain_stake.py` pins all of it.

**Slice 2, done after the betanet-8 reroll (gen 27): the `else 1` and from-epoch-0 gates.** Each constant and its gen-25
branch went; the rule is unconditional. What was kept, and why:

- `>= 1` (the gate's own value) where height 0 reaches the check: `validate_transaction` also runs at mempool
  admission with the tip's height, which is 0 on a genesis tip; a tx's own `max_block` may be 0; the exec node applies
  genesis from cursor -1, so `ExecState.rules_*`, `exec_state_bind.root_v2` (the exec root layout, which reaches
  the exec summaries in L1 `meta`) and the F3 call context keep `>= 1`; a settle cursor or a namespace's top attested
  cursor may be 0. Where the height is provably >= 1 — apply paths (genesis carries no transactions), a remote block
  (rebuilt at tip + 1), the challenger draw (behind the enrolment rule), enrolment records — the guard is gone.
- `stark.Rules` / `rules_at` / `with_rules` plumbing stays; `rules_for_height` returns `RULES_STRICT` for None or
  height >= 1 and `RULES_LEGACY` for height 0, exactly what the six gates computed.
- `epoch is None` stays in the lease helpers (`lease_epochs_for`, `recert_history_epochs`, `fidelity_step`), whose
  signatures still admit a legacy caller with no epoch. `records_bind.dividend_accrual_effects` lost its unmetered
  `epoch is None` branch with `DIV_CARRY_METER_EPOCH` (the SCHEDULED_CLEANUPS.md entry): every production caller passes
  an epoch >= 0.
- `/status` still serves `proof_rules` (every height 1) and `lease_v2_epoch` (0): the wallet reads them.
- `CHAIN_CLOCK_CADENCE_DS` is the plain `64`.

Proven by replaying the live betanet-8 chain from genesis through both trees (same state root as the live blocks at
every height) — see the slice-2 commit messages.

**Slice 3, done after the betanet-9 reroll (gen 28): the gen-27 gates.** Four parallel slices (the transaction rules;
the address format and the legacy claim; the settle floor, exec DA deadline, block-signature binding and dividend carry;
the ZK hardening: the asset-io refusal, the landing-height guards on the pinned asset binding, `records_bind._asset_escrow_derivable`, `stark.RULES_PRE_HARDEN`), each proven by replaying the live betanet-9 chain (blocks 1..5810) through
`CoreClient.produce_block(remote=True)` with the slice's tree and with main: every block accepted, the rebuilt hash, the
L1 state root and the L2 settled commitment identical at every height. Deleted paths: the `block_timestamp` certificate
clock and `cert_verdict`'s single check, the enrol-time TPM draw, the base-set EK root check, the raw device key as the
consensus key, the tpm_ready transfer fall-through, the pre-gate free-tx rules, the chain-less block-signature form at
heights >= 1, the pre-carry dividend branch, the format-1 derivation of KEY addresses (Python and every JS copy).
Kept: `>= 1` wherever height 0 reaches (see the protocol.py GATE LEDGER); the raw-bytes `device_binding_key` form and
the legacy-row eviction while devbind rows carried from betanet-8 exist; `legacy_address()` for `legacy_claim`; the
multisig address body; `/status` `address_format: 2` for the published TPM helper (whose Rust copy still carries a
format switch until its next release); `tools/rekey_v2.py` / `recover_keys.py`, which the carry runs only for a
gen-27 source (a gen-28 carry re-keys nothing and needs no `--known-keys`).
Proof tool: `tools/replay_chain.py` (fetch the chain once, replay main and the candidate from worktrees, compare) —
its docstring is the procedure.

Do this in a **follow-up commit after** the reroll is live and verified, never in the same one — the reroll commit
must be reviewable as "new genesis, same rules".

## Runbook (as executed for gen 22, 23 and 24)

1. Audit exec state read-only over HTTP (`/exec/contracts`, `/exec/bridge`, `/exec/assets`).
2. Dry-run `tools/alphanet6_carryforward.py` against a **read-only LMDB copy**; it folds balances, bonded, dividends,
   pending withdrawals and the bridge, hard-asserts the shielded pool is EMPTY, and refuses unless supply conserves
   exactly (Δ = 0).
3. Rehearse the source edit on a throwaway worktree (symlink `native/` in).
4. Back up the data directory.
5. `systemctl stop nado-watchtower nado-exec nado` (a fixed-point snapshot).
6. **Drain the exec tail**: `python3 tools/exec_drain.py /root/nado/exec_state.json /root`. The exec node applies only
   finalized blocks, so at any stop it is ~45 blocks behind the tip, and those blocks hold real exec ops (dividend
   claims, deposits). The drain replays them with the exec node's own apply path and prints the tip.
7. Run the carry-forward tool `--write --l1-tip <that tip>`; confirm Δ = 0. It also records the identities PRESENT at
   the tip (a live lease); genesis leases exactly those, never every registered identity (see failure 6).
   **Into address format 2 (gen 27 → 28)** every address changes and the tool re-keys the carry (`tools/rekey_v2.py`).
   First recover the keys older generations recorded, from the backups' `index/state` (never the live one; the tool
   refuses it): `python3 tools/recover_keys.py /root/known_keys.json <backup>/index/state ...`, then pass
   `--known-keys /root/known_keys.json` to the carry, which refuses to run without it. Measured at gen 27: 871 accounts
   had never sent on gen 27, and older generations held the key of 535 of them (674 NADO); every such owner's wallet
   derives the new address from the key it already holds. The rest (~142 NADO, 332 accounts on 2026-09-28) stay at their old
   address until their owner's wallet claims them automatically with the key it holds (`legacy_claim`,
   `LEGACY_CLAIM_HEIGHT`; the operator accepted that a forger sharing an old address's 21 bytes could claim first).
8. Edit: `CHAIN_ID`, `GENESIS_TIMESTAMP`, **`CHAIN_GENERATION`** — the last is THE purge trigger; forgetting it means
   nothing purges. `CHAIN_ID` and `GENESIS_TIMESTAMP` must both be NEW values, never an earlier generation's: an FFG
   double-vote proof is bound to its chain only by the tx `chain_id`, so a reused `CHAIN_ID` makes an old
   generation's attestations slash evidence on the new chain (gens 26 and 27 shared both; no block was built on 26).
   `tests/test_slash_evidence_is_this_chain_only.py` refuses a pair it has seen before — add the new pair to its table.
   Delete `private/genesis_alloc.dat`. No gate edits are needed (see above).
9. `tests/test_genesis_alloc_format.py`, `tests/test_gate_reroll_transfer.py` (update its generation), commit.
10. `systemctl start nado` — the node self-purges on the generation mismatch. Check `/get_supply` equals the carry
   total and the node's `open:N` log line equals the tip's live collector count, then push and kick the wave **from a
   fleet node** (`http://<fleet-ip>:9173/update?wave=true`, failure 7) so the fleet purges too. Confirm unification by
   one block hash at a common height across every node.
11. Start exec and watchtower, then `python3 -m execnode.games.redeploy` (confirms via a provisional view, needs no
    finality). It rewires EVERY `const CID` / `const <NAME>_CID` in static/ (the wallet's `RESERVE_CID` included) and
    the reward table, and verifies each resolves to a live contract; the live e2e scripts derive their ids and need
    nothing. Then `_fund_faucet.py <NADO>` with the faucet bank the carry refunded to the operator (betanet-8: 99.4),
    and the manual refunds the carry-forward printed (`scripts/nado_cli.py send <addr> <NADO> --memo …`).
12. Check `/status` → `jobs.problems` is empty (doc/jobs.md). The DEX price history resets itself on the new chain id.
13. Walk every page headless (every `static/*.html`, script errors and failed requests) — the betanet-8 walk found the
    wallet's reserve panel on a dead contract and the lend page broken since it was written.
14. Follow-up commits: the gate cleanup (done for gen 25 in two slices: e7a17f00, 9c6bf717 — replay the live chain
    through old and new code and require the same state root, as those did).

## Failure modes that have actually happened

1. **`CHAIN_GENERATION` not bumped** → nothing purges (fixed c3b5fb84).
2. **Generation marker absent** on a hand-installed layout → the node stamps instead of purging.
3. **Block-0 genesis checks are mute** on rolling/snapshot-booted nodes — they have no block 0 on disk.
4. **Snapshot re-infection**: purged nodes rebooted into the un-purged majority and adopted the old chain through
   quorum snapshots, which carry no genesis-descent proof — 7 of 10 nodes were back on the dead chain within minutes,
   and the old chain's weight froze the new chain's depth floor. The durable defence is the **height-vs-wallclock
   bound**: no chain of this genesis can be taller than about `2 × (now − GENESIS_TIMESTAMP) / BLOCK_TIME + 600`.
   Boot purges on-disk data over the bound, and status admission refuses peers advertising impossible heights or a
   mismatched `genesis_hash`.
5. **A splice edit can produce valid-but-wrong Python** (`f# comment` parses as a bare name): `py_compile` *and*
   import-smoke every edited module before restarting anything.
6. **Every registered identity leased at genesis** (betanet-8, gen 26): the open lane showed 79 collectors against 46
   live, because lapsed identities got a fresh lease and would have been drawn for slots they never fill. Caught before
   block 1 and re-rolled as gen 27. Before starting, check the node's `open:N` log line equals the tip's live count.
7. **The `/update` wave never leaves the push host**: the checkout you push from is already current, answers
   `up_to_date`, and only a node that actually UPDATED forwards the wave — and after a reroll its peer pool is empty
   anyway (every old-chain peer is refused). Kick two fleet nodes directly (`http://<ip>:9173/update?wave=true`).

8. **Non-device rows carried as device bindings** (found by the gen-28 rehearsal): `kv_ops.devbind_rows` returned the
   open-enrolment marker `tpmek:<identity>` — a packed string, indexed character by character — as a binding of address
   `"3"`. The gen-27 carry seeded 7 of them into genesis; the gen-28 re-key refused on them. The table also holds
   `evict:`, `lease:` and `tpm:<enrol id>` rows; devbind_rows now skips all of them by name or shape
   (`tests/test_carry_devices_only.py`).
9. **An address hard-coded from a 42-hex BODY survives a format switch unnoticed** (gen-28 rehearsal):
   `protocol.GENESIS_ADDRESS` (built from `_GENESIS_BODY`) and the faucet contract's `OPERATOR`
   (`make_address(<body>)`, which under format 2 hashes the body into an address nobody holds — every prize payout would
   have reverted on the operator check) were missed by a sweep for full 46-char literals.
   `tests/test_operator_addresses_follow_the_format.py` pins every hard-coded operator address to the live format and
   fails on any unlisted 42/46-hex literal.
10. **"Below the gate" tests at a reroll.** Every gen-27 gate becomes 1, so a test that reproduces the old rule at a real
    gen-27 height finds no "below" left and fails. The fix keeps the property: the test sets the gate it probes to the
    gen-27 value for its below-gate half (`GEN27_GATE`, `NARROW_GATE`) and restores the live one — never delete the check.

## Gen 28 (betanet-9): address format 2

Every address changes (`tools/rekey_v2.py`, `tools/recover_keys.py`). Carried 2026-09-29 at L1 tip 45872 (exec drained
45827..45872): 137,077,938,764,879 raw, Δ = 0; 1,249 accounts, 913 re-keyed (535 with a key recovered from an older
generation's backup), 332 keyless kept at their old address for `legacy_claim`, 4 relay seeds dropped (never produced,
no key on any chain; their coins carry), 135 device bindings, 8 aliases, 47 present identities; 99.2 NADO of contract
pots refunded to the operator (the faucet bank). The operator's addresses: `ebd27698…` → `3cc4c44a…` (settle anchor,
faucet/sovereign fixed cids, faucet operator), `27f2870b…` → `b7a08de8…` (genesis address, the wallet's auto-vote
default; the gen-27 default list follows forward). Chain clock re-anchored to 6.50 s (65 ds).
A node whose keyfile carries `account` (written by `scripts/auth_cli.py` after a rotation) names its OLD address and must
be re-pointed after the reroll; at the rehearsal the only rotated account (`c677679c…` → `f02d7729…`) was no fleet node.
Wallets need nothing: an account address is always derived from the base HD key, and the signer child is re-found by
scanning against the carried auth config.

Verify unification by comparing a block hash at a **common height**, never by comparing tips.

# Working on NADO

This checkout **is the live mainnet node.** `/srv/nado-home/nado` is the directory systemd runs, and
pushing `main` restarts production across the fleet. Read that sentence again before your first edit:
there is no staging copy, and a broken commit is an outage, not a failed build.

Everything below is a rule that was learned by breaking something. Each one names what it cost.

---

## The ten rules that matter most

### 1. End-to-end before touching a live loop

Any edit under `loops/`, `ops/`, `nado.py` or `execnode/` must be proven end to end **before** it is
committed:

```bash
python3 scripts/testnet/run_testnet.py 4 240      # loopback mesh, doc/testnet.md
```

Then, after the commit restarts the live node, watch `/status` for a few minutes: height climbing,
peers linked, no `Error in peer loop`.

*Why:* a `check_save_peers` refactor whose early `return` returned `None` where the caller indexed
`result["success"]`. All 300+ script tests were green. It purge-cycled the bootstrap node 14 times over
12.5 hours.

### 2. Every consensus gate carries a reroll branch

```python
FEATURE_HEIGHT = 45300 if CHAIN_GENERATION == 25 else 1
```

Never a bare height. `else 1` = live from block 1 on a fresh chain; `else 0` = the feature never turns
on and its code path is cleanup fodder. Add a line to the **GATE LEDGER** comment in `protocol.py` and
to `doc/reroll.md`; `tests/test_gate_reroll_transfer.py` fails if you forget, and it also pins that the
live value never changed.

*Why:* `POOL_HEIGHT = 6000` on a fresh chain leaves the rule off for the first 6,000 blocks of a chain
that was supposed to start with it. With the branch, a reroll needs no gate edits at all.

### 3. Gate at the fleet's adoption block, not at the next block

A validation-rule change that arrives on some nodes before others splits the fleet. Measure the live
cadence, pick a height far enough out for the `/update` wave, and confirm the fleet is uniform before it
fires:

```bash
curl -s localhost:9173/status_pool | python3 -c "import json,sys; [print(ip, v['running_commit'][:12]) for ip,v in json.load(sys.stdin).items()]"
```

Gating late costs nothing. Gating early costs a fork.

### 4. Never import node modules against the live database

`import nado` — and anything that reaches `kv_ops` — opens a **write** transaction against production
LMDB. Always:

```python
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-...")   # BEFORE any nado import
```

Every test in `tests/` does this on line 1 for this reason.

### 5. Run the undefined-names test on the final tree

```bash
python3 tests/test_no_undefined_names.py
```

It catches the class of bug that unit tests miss and production finds: a name used but never imported,
in a path that only executes under load. Run it on the tree you are about to commit, not on an earlier
one — then `curl` the node after the restart and count tracebacks.

### 6. Walk the whole user workflow, as the user, before calling anything done

A feature is not finished when its pieces pass. It is finished when a person who knows nothing about
the implementation can complete the journey end to end. Before reporting a user-facing feature as
working, walk it yourself, in order, as they would:

1. **Can they find it?** Not "does the endpoint exist" — is there a path to it from where the user
   already is, without being told a URL or a query string by someone who read the source?
2. **Does every hop actually carry the data?** Follow the value across each boundary — client to
   relay, store to poller, poller to transaction — and *read it back out the far side*. A write that
   returns `ok` proves nothing about what the next component can see.
3. **Simulate the user's run.** Fetch the real artifact from the real public URL, run the real
   binary, read what it prints. Do not test the copy in `target/`, and do not trust that a rebuild was
   copied to where it is served.
4. **Does what it says match what happened?** Every success line must be true of the state that
   actually exists.

*Why:* in one evening, a completed TPM enrolment — a four-message ceremony proven on real silicon —
could not be used by its owner, and each blocker passed its own tests:

- the finished proof was dropped into a store **no wallet read**; the drop returned `ok` and the
  wallet polled a different one, so nothing failed anywhere and there was simply no button;
- the store then rebuilt every statement as a WebAuthn one, so a TPM proof died on `KeyError: 'att'`
  *after* passing validation — inside a bare `except: pass` that made the endpoint report success;
- the helper printed **"DONE: the identity is registered"** immediately after telling the owner the
  registration was not submitted. The owner believed the first line and went looking;
- the download URL handed out all evening was on a port Cloudflare does not forward, so no user could
  ever have fetched it — while 443 had served it correctly the whole time;
- and the binary at the served path was never re-copied after a rebuild, so the fix that was "in this
  build" was absent from the artifact anyone would download.

None of these are consensus bugs and no test suite was going to catch one. They were all the same
failure: a claim about another component that nothing checked, and a workflow nobody walked.

**Never report a workflow as working on the strength of its parts.** If you cannot drive the UI
yourself, say exactly that, name which hops you verified by measurement and which you did not, and do
not let "the code is correct" stand in for "the user can do it".

### 7. The wallet speaks 16 languages, and every one of them is your job

`static/i18n.js` carries **16 language tables** — en, cs, es, pt, fr, de, it, ru, zh, ja, ko, ar, hi,
tr, id, vi — and a user-facing string added in English only is a half-finished string. Every
`i18("key", "English default")` you introduce needs its key in **all sixteen** tables, not just `en`:
the English default is a fallback for a missing translation, not a substitute for one.

```bash
node tests/i18n_coverage.mjs        # every referenced key defined in every language
```

Run it before committing anything that touches the wallet. It reports exactly which keys are missing
and from where, and it is the only thing standing between a new feature and fifteen locales silently
falling back to English.

*Why:* four strings added to the wallet's attestation card in one evening — `remote.tpmOffer`,
`remote.dlWin`, `remote.dlLinux`, `remote.dlHash` — shipped English-only and were caught only because
the user asked about translations afterwards. The feature "worked" in every test. It just spoke the
wrong language to fifteen sixteenths of the people it was built for.

Note `ar` is right-to-left: check that any string you add still reads correctly when the layout flips,
and keep interpolations (`{a}`, `{n}`) intact in every table — a dropped placeholder is a broken
sentence, not a cosmetic issue.

### 8. Never touch the user's keys

A private key is never read, never written, never asked for, never logged, never sent anywhere, and
never made a step the user performs. Not "encrypted first", not "only locally", not "just for testing".

This is a standing rule the operator has had to give more than once, and every time it was because
something in a design implied a key would be handled. The enrolment helper is the shape to copy: it
signs with a throwaway identity it generates beside itself, the chip's certify NAMES the wallet
address, and the finished proof is handed back for the wallet to sign. `vouch_for != signer` is the
normal path, not a workaround — a program that asks someone to paste a private key teaches the habit
that is otherwise the definition of a scam.

An identity file the helper creates for itself is not an exception to this; an existing wallet key is
never read, and the fallback that once reached into `~/nado/private/keys.dat` was deleted after it
silently signed as the production node.

### 9. A feature nobody turns on does not exist

Ship user-visible behaviour **on by default, on every node**, with an opt-out — not off by default
waiting to be discovered. *"default off??? make it default on on every node"*.

Two traps, both of which have shipped here as no-ops that looked correct:

- `get_config()` returns `private/config.json` **verbatim and does not merge new defaults**, so a key
  added to `config.py` reaches only nodes installed afterwards. Default in the CODE —
  `get_config().get("relay_port", 80)` — or your new setting is off everywhere that matters while the
  code reads as if it is on.
- reaching a feature must not require knowing a URL, a query string, or a mode to select first. If the
  only people who can find it are the ones who read the source, it does not exist. *"give me the
  fucking url i have to type it like a retard again"*, *"it should be fucking automatic"*.

### 10. Finish the owed work, and check it before reporting

*"so the multi-week work on the retention window is complete you lazy bastard?"*, *"keep fixing, do not
fall asleep like last night just waving the rounds"*, *"you did lacklustre work without checking after
yourself"*.

- A loop that reports rounds without advancing anything is worse than stopping: it consumes the
  operator's attention and returns nothing.
- Known debt in `SCHEDULED_CLEANUPS.md` is owed, not optional. An item marked consensus-changing that
  misses a reroll has to be raised loudly, at the reroll, not silently carried.
- Check your own work before saying it is done, and say which parts you verified by measurement and
  which you did not. "Committed" is not "deployed"; "compiles" is not "runs"; "the endpoint exists" is
  not "the user can reach it".

---

## How a block gets made, and how a tip goes wrong

There is no proposer. **Every node assembles every block**, so a block is a pure function of (parent,
height, mempool) and two nodes at the same tip build the identical block or they have different
mempools. That single design choice explains every failure mode below: a split is never "who won the
election", it is always "who saw which transaction".

### The pieces, in the order they run

| piece | where | what it decides |
|---|---|---|
| `CoreClient._mode()` | `loops/core_loop.py` | WHEN to mint: `init` / `building` / `produce`. Pure local pacing — `block_time` is **not** consensus, verify only checks `timestamp <= now`. |
| `memserver.reconcile_next_block_set()` | `memserver.py` | Right before assembly, asks peers what THEY would include on THIS tip (`/next_block_txids`), fetches missing bodies, merges through normal admission. The mesh converges on the UNION instead of racing on the difference. |
| `memserver.get_upcoming_block_hash()` | `memserver.py` | The determinism signal: `blake2b(parent, next_height, mature tx subset)`. Two nodes match here **iff** they will build the same next block. Never None — an empty block still hashes, so "no eligible txs" is a comparable answer rather than a null. |
| `ConsensusClient` | `loops/consensus_loop.py` | Fork choice across peers, by cumulative weight. Benches tips that cannot be fetched (12 s doubling to 600 s) and peers that repeatedly fail (to 2 h) — that bench is also how a node can go blind to a real chain. |
| `fork_resolution.resolve()` | `ops/fork_resolution.py` | The verdict: `BEHIND` / `SYNCED` / `REORG` / `DEAD_FORK` / `UNKNOWN`, from a binary-searched common ancestor over direct peer probes. |
| `_maybe_escape_dead_fork()` | `loops/core_loop.py` | Last resort: purge chain data and resync. Destructive, so it is gated on unanimity and weight and probes at the HARD floor only. |

### Two floors, and only one of them is crossable

- **depth floor** (`finality_depth`, 45) — ordinary reorg protection. Crossable.
- **`hard_finality`** — the un-crossable one. Rollback refuses to go below it, ever.

`classify(ancestor, tip, finalized)` is the whole decision and it is pure arithmetic:
`ancestor >= tip` → BEHIND (forward sync, **never** a rollback); `ancestor >= hard_finality` → REORG
(roll back and re-sync); otherwise → DEAD_FORK (only a purge gets out). `ancestor is None` → UNKNOWN,
and **every caller must treat UNKNOWN as "change nothing"**.

### Reading a divergence, in the order that actually discriminates

Do this before touching code — most "forks" are not forks:

1. **Same height, different hash?** If no, it is lag, not a fork.
   ```bash
   # per node: /status -> latest_block_height, latest_block_hash
   ```
2. **Are the laggards moving?** Sample twice, ~75 s apart. Advancing-but-behind is propagation.
   A tip that does not move at all is the real signal, and so is a tip that goes **backwards**.
3. **Where do they actually diverge?** Binary-search `/get_block?number=` between the two nodes.
   A fork one block deep and a fork below the floor need opposite responses.
4. **Is the fork point above `hard_finality`?** Above → rollback is legal and the node should be
   recovering itself. Below → it cannot, by design, and only a purge moves it.
5. **Only then** read `/status`: `recovery`, `recovery_fail`, `last_block_reject`, `dead_fork_probe`,
   `last_fork_diff`. These are *persistent* fields precisely because a failure frame used to live ~3 s
   before the next phase overwrote it.

`last_block_reject` is usually the system **working**: a refused block whose content did not hash to
its claimed hash is a competing block correctly discarded. Check whether the fleet actually holds a
different block at that height before treating it as an incident — measured 2026-09-12, every node held
the same 66084 and the rejection was stale.

### What this has cost before

- **A node alone on a fork mines FASTEST** — unopposed, every slot. "Still moving" is not health, and
  reading it as health let a node mine 600+ blocks on a dead branch invisible to every recovery route.
- **Probing yourself** vetoes your own recovery: a node whose IP is in the seed list answered its own
  fork question with its own hash, counted it as agreement, and could never self-heal.
- **Donor selection keys off the heaviest advertised tip**, which flip-flops between both sides of a
  live split — a same-fork donor re-inflates the fork you just rolled back. The verdict is the
  decision; a donor only matters once you are at the ancestor.
- **The treadmill**: requiring the exact heaviest advertised tip to exit emergency never terminates on
  a chain that keeps producing. 7 h 20 m measured, applying blocks the whole time, with no FFG votes
  and no production while trapped.

---

## Repository shape

| path | what it is |
|---|---|
| `protocol.py` | consensus constants and the **GATE LEDGER**. Changing a value here changes consensus. |
| `ops/` | consensus operations: transactions, accounts, blocks, KV, attestation |
| `loops/core_loop.py` | the node's per-block work: production, sync, duties |
| `nado.py` | the HTTP surface |
| `native/` | Rust kernels (attestation, proving). A `.rs` commit **fail-stops** `nado-exec` until `cargo build --release` runs. |
| `execnode/` | execution layer (contracts, DA, settlement) |
| `scripts/testnet/` | loopback harnesses — `run_testnet.py`, `test_fork_resolution.py` |
| `doc/` | design docs; `doc/reroll.md` and `doc/testnet.md` are procedures, not prose |

## Determinism is the whole game

Consensus code must be a pure function of agreed data, byte-identically, forever, including on replay
years later. Concretely:

- **No wall clocks.** Certificate validity, timeouts and windows read an anchor block's timestamp. A
  certificate expiring mid-block is otherwise valid on one node and expired on the next — a fork with
  no attacker involved.
- **No network reads.** No revocation lists, no vendor fetches, no peer-learned trust. Roots are pinned
  constants; changing one is a gated protocol commit.
- **No dict-order dependence.** msgpack preserves insertion order, so a record two nodes build with the
  same content in a different order is two different byte strings for one state. Store sorted lists of
  pairs, never dicts.
- **No floats.** Anywhere near a txid or a state root.
- **Any new `meta` key enters the L1 state root** unless explicitly excluded. Adding one is a consensus
  change even when it looks like bookkeeping.

## Rollback must be the exact inverse

Every apply path needs a revert path that restores the prior state exactly, and the safe way is to
**journal what was overwritten** rather than to re-derive it. Re-deriving is a second implementation of
the rules, with its own bugs; it produced the `h4260` meta-corruption wedge.

## Conventions

- **Comment every regression site.** When you fix something, leave an invariant comment at *every* place
  a repeat of that fix could regress. This is a standing user rule.
- **Explain why, not what.** The comments in this codebase carry the incident that motivated the line.
  Match that; a comment restating the code is noise.
- **Tests are named after the property, not the function.** `refuses a reveal in the commitment's own
  block`, not `test_reveal_3`.
- **Ship the fix.** Do not pause between diagnosis and fix for approval; report whether it resolved.
- **No unrequested side actions** — no config changes, scripts, or timers without an explicit yes.
  *"you will not fucking write dubious scripts without my permission"*.
- **Fix what was asked, and nothing else.** A request to correct one thing is not licence to redesign
  the surrounding thing. *"I NEVER ASKED FOR THIS, I WANTED YOU TO FIX ..."* — the redesign was not
  wanted, and it broke what worked.
- **The coins are real.** Betanet balances persist across upgrades and carry to mainnet. Never write
  "test coins", never treat a balance as disposable, and never design anything that would discard one.
- **Never hard-code a label that changes.** Network names (`betanet-2`) and version strings drift; a
  page or a binary that states one goes stale the day it changes. Read it from the chain or the
  version file. A build called `alpha.12` during a beta is the same error.
- **An error message names the cause for the platform in front of the user.** A Windows machine told to
  check a Linux path, or a TPM 1.2 owner shown a hex code and sent to their firmware, is being sent to
  fix something that is not broken. Detect the real case and say it.
- **Avoid the word "cyber"** in any form. It trips content safeguards mid-task and costs a round trip
  every time.

## Deploying

```bash
git push origin main          # THIS RESTARTS PRODUCTION
curl -s localhost:9173/update # kick the fleet wave; peers cascade within seconds
```

Then verify: `/status` height climbing, `last_block_reject: null`, and `status_pool` showing every peer
on the new `running_commit`.

A reroll is different and has its own runbook: **`doc/reroll.md`**. `CHAIN_GENERATION` is the purge
trigger; forgetting to bump it means nothing purges.

## Where the durable knowledge lives

Long-form incident notes are in `doc/` (`consensus-mechanics-lessons.md`, `reroll.md`, `testnet.md`,
`device-attestation.md`, `tpm-attestation-without-a-ca.md`). If you learn something that would have
saved you an hour, write it into the relevant doc — not into a commit message where the next person
will not find it.

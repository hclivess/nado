# NADO CLI & headless automation

Everything the browser interface can do except attest a device — send, stake, govern the treasury, collect
the presence dividend — is available from the terminal and, unattended, from the node itself. This document
covers the **`scripts/nado_cli.py`** command-line tool and the node's **headless auto-behavior**.

## Security model (why this is safe)

Every NADO operation is just a **signed transaction**. The CLI:

1. loads your keypair from `private/keys.dat` **in-process**,
2. builds the *same* transaction the web interface builds (it calls the exact `ops.transaction_ops.construct_*`
   helpers), and
3. POSTs the finished, signed tx to the node's **existing public `/submit_transaction`** endpoint.

There is **no new signing endpoint and no new trust surface**: your private key never leaves the local process,
and the node validates a CLI transaction *identically* to a browser one (ML-DSA signature, device attestation, fee rules,
quorum weight, etc.). Anything the CLI could submit, a hostile client could already submit — and the node
rejects it the same way. The CLI is a thin convenience layer over primitives that already exist.

## Usage

```bash
# HOME selects the data dir → HOME/nado/private/keys.dat (the node's own key). Or pass --keys.
python3 scripts/nado_cli.py [--node URL] [--keys PATH] <command> [args]
```

- `--node` — node base URL (default `http://127.0.0.1:9173`, or `$NADO_NODE`).
- `--keys` — path to a `keys.dat` (default `$HOME/nado/private/keys.dat`).

### Commands

| Command | What it does | Example |
|---|---|---|
| `info` | Print address, spendable balance, bonded stake, open/bonded lane status | `nado_cli.py info` |
| `send <to> <amount>` | Transfer NADO (`--memo`, `--fee`) | `nado_cli.py send <address> 12.5` |
| `register` | **Retired at gen 25** — refuses at once (an open-lane identity is a hardware-attested device: use the wallet on a phone, a TPM PC or a security key; nodes earn in the bonded lane) | — |
| `bond <amount>` | Move spendable → **bonded** stake (bonded lane) | `nado_cli.py bond 100` |
| `unbond <amount>` | **Request** the release of bonded stake (**free**). The coins stay bonded — and slashable — until `BOND_UNLOCK_DELAY` passes; nothing moves yet | `nado_cli.py unbond 50` |
| `withdraw` | Claim a **matured** unbond: bonded → spendable (**free**; run it once the release block is within reach) | `nado_cli.py withdraw` |
| `alias <op> <name>` | `register` / `transfer` / `unregister` a human-readable alias (`--to`) | `nado_cli.py alias register alice` |
| `propose` | Open a treasury spend proposal + vote **yes** on it | see below |
| `vote` | Vote `--choice yes\|no` on a proposal | see below |
| `execute` | Trigger payout of an approved proposal | see below |
| `collect` | Sweep your accrued **presence dividend** into a provable collection | `nado_cli.py collect` |
| `bridge-deposit <amount>` | Escrow to the execution-layer bridge | `nado_cli.py bridge-deposit 10` |
| `update` | Ask the node to self-update from `origin/main` (`GET /update?wave=1`); it forwards the wave to its peers | `nado_cli.py update` |
| `msig-address` | Derive an M-of-N multisig address locally (`--threshold`, `--members a,b,c`) | `nado_cli.py msig-address --threshold 2 --members <address>,<address>,<address>` |
| `msig-propose <to> <amount>` | Draft a multisig spend, add your signature, write the proposal file (`--threshold`, `--members`, `--memo`, `--fee`, `--out`, default `msig_proposal.json`) | `nado_cli.py msig-propose <address> 5 --threshold 2 --members …` |
| `msig-sign <file>` | Add your signature to a proposal file | `nado_cli.py msig-sign msig_proposal.json` |
| `msig-submit <file>` | Submit a proposal that holds the threshold of signatures | `nado_cli.py msig-submit msig_proposal.json` |

Treasury commands take the full spend so the proposal id binds to exactly that payout (byte-identical to the
node's `hashing.treasury_proposal_id`), and require **bonded stake** (10 NADO min, `B_MIN`) to have voting weight:

```bash
python3 scripts/nado_cli.py propose --to <address> --amount 500 --memo "grant" --nonce 7 --expiry 60000
python3 scripts/nado_cli.py vote    --to <address> --amount 500 --memo "grant" --nonce 7 --expiry 60000 --choice yes
python3 scripts/nado_cli.py execute --to <address> --amount 500 --memo "grant" --nonce 7 --expiry 60000
```

Notes: `unbond` and `withdraw` are **fee-exempt** (a fully-bonded wallet can always exit). `alias register` pays
`ALIAS_REGISTRATION_FEE` (10,000× `MIN_TX_FEE`, anti-squat); the other ops pay `MIN_TX_FEE`, which is **destroyed**.

## Headless auto-behavior (the node itself)

A running node auto-compounds and maintains itself unattended via `loops/core_loop.py` (all best-effort — a
failure never disrupts consensus). Each runs at most **once per epoch**:

| Behavior | Default | Config key | Env override | Notes |
|---|---|---|---|---|
| **Auto-bond** | **on (99%, `AUTO_BOND_DEFAULT_PERCENT`)** | `auto_bond_percent` (0–100) | `NADO_AUTO_BOND_PERCENT` | Bonds this % of *newly-mined* spendable earnings into the bonded lane; no upper stop (bonded weight is linear in stake); accrues below a dust floor instead of emitting fee-dominated txs. |
| **Auto-collect** | **on** | `auto_collect_dividend` | `NADO_AUTO_COLLECT` | Sweeps the accrued **presence dividend**. Skipped unless the node is an **open-lane member** (bonded-only nodes accrue none, so it never burns a wasted fee). |
| **Auto-register** | **retired** (gen 25) | — | — | PoSW registration is gone: an identity is an attested device. The `auto_register` key and `NADO_AUTO_REGISTER` are ignored; a node bound once to a hardware wallet renews its lease statement-free (`ops/node_attest.py`). |

Config lives in `private/config.json`; env vars take precedence (handy for systemd). The installer wires them:
`sudo scripts/install.sh --service --auto-bond <pct>` installs the node and the exec node (the exec node is the
default; `--no-exec` leaves it out — without it the dividend accrues but is never auto-collected) as systemd
services with `NADO_AUTO_BOND_PERCENT` in the unit.

To keep a node in the free lane, bind it once from the wallet's Mining page (*Attest a node you run*): a node
bound to a Ledger or Trezor renews its lease statement-free from then on. There is no env var for this.

## What is *not* here (yet)

Shielded-pool operations (shield / unshield / shielded transfer) run through the **execution node** and its
in-browser/on-device zk-STARK prover, not L1 `/submit_transaction` — see [privacy.md](privacy.md) and
[wasm-prover.md](wasm-prover.md). HTLC atomic swaps are likewise a distinct flow. These can be scripted the same
way (build the op, submit) but are not yet folded into `nado_cli.py`.

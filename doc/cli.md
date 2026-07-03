# NADO CLI & headless automation

Everything the browser interface can do — send, register for the open lane, stake, govern the treasury, collect
the presence dividend — is available from the terminal and, unattended, from the node itself. This document
covers the **`scripts/nado_cli.py`** command-line tool and the node's **headless auto-behavior**.

## Security model (why this is safe)

Every NADO operation is just a **signed transaction**. The CLI:

1. loads your keypair from `private/keys.dat` **in-process**,
2. builds the *same* transaction the web interface builds (it calls the exact `ops.transaction_ops.construct_*`
   helpers), and
3. POSTs the finished, signed tx to the node's **existing public `/submit_transaction`** endpoint.

There is **no new signing endpoint and no new trust surface**: your private key never leaves the local process,
and the node validates a CLI transaction *identically* to a browser one (ML-DSA signature, PoSW, fee rules,
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
| `send <to> <amount>` | Transfer NADO (`--memo`, `--fee`) | `nado_cli.py send ndo… 12.5` |
| `register` | Join/renew the **OPEN lane** — computes the ~1 s sequential **PoSW** and submits (fee-exempt) | `nado_cli.py register` |
| `bond <amount>` | Move spendable → **bonded** stake (bonded lane) | `nado_cli.py bond 100` |
| `unbond <amount>` | Move bonded → spendable (**free**; unlocks after the delay) | `nado_cli.py unbond 50` |
| `alias <op> <name>` | `register` / `transfer` / `unregister` a human-readable alias (`--to`) | `nado_cli.py alias register alice` |
| `propose` | Open a treasury spend proposal + vote **yes** on it | see below |
| `vote` | Vote `--choice yes\|no` on a proposal | see below |
| `execute` | Trigger payout of an approved proposal | see below |
| `collect` | Sweep your accrued **presence dividend** into a provable collection | `nado_cli.py collect` |
| `bridge-deposit <amount>` | Escrow to the execution-layer bridge | `nado_cli.py bridge-deposit 10` |

Treasury commands take the full spend so the proposal id binds to exactly that payout (byte-identical to the
node's `hashing.treasury_proposal_id`), and require **bonded stake** (100 NADO min) to have voting weight:

```bash
python3 scripts/nado_cli.py propose --to ndo… --amount 500 --memo "grant" --nonce 7 --expiry 60000
python3 scripts/nado_cli.py vote    --to ndo… --amount 500 --memo "grant" --nonce 7 --expiry 60000 --choice yes
python3 scripts/nado_cli.py execute --to ndo… --amount 500 --memo "grant" --nonce 7 --expiry 60000
```

Notes: `register` and `unbond` are **fee-exempt** (a zero-balance newcomer can register; a fully-bonded wallet
can always exit). All other ops pay `MIN_TX_FEE`, which is **burned**.

## Headless auto-behavior (the node itself)

A running node auto-compounds and maintains itself unattended via `loops/core_loop.py` (all best-effort — a
failure never disrupts consensus). Each runs at most **once per epoch**:

| Behavior | Default | Config key | Env override | Notes |
|---|---|---|---|---|
| **Auto-bond** | **on (80%)** | `auto_bond_percent` (0–100) | `NADO_AUTO_BOND_PERCENT` | Bonds this % of *newly-mined* spendable earnings into the bonded lane; stops at the whale cap; accrues below a dust floor instead of emitting fee-dominated txs. |
| **Auto-collect** | **on** | `auto_collect_dividend` | `NADO_AUTO_COLLECT` | Sweeps the accrued **presence dividend**. Skipped unless the node is an **open-lane member** (bonded-only nodes accrue none, so it never burns a wasted fee). |
| **Auto-register** | **off** | `auto_register` | `NADO_AUTO_REGISTER` | Keeps the open-lane **PoSW lease** alive: registers when absent, renews inside the lease tail. **Opt-in** so a headless node doesn't silently join (and Sybil-load) the open lane. The ~1–2 s sequential PoSW is computed inline. |

Config lives in `private/config.dat` (JSON); env vars take precedence (handy for systemd). Example headless
open-lane miner that also compounds and self-collects:

```bash
NADO_AUTO_REGISTER=1 NADO_AUTO_BOND_PERCENT=80 python3 nado.py
# auto-register keeps the lease alive → auto-collect sweeps the dividend → auto-bond compounds the rest
```

`scripts/install.sh --exec` wires the node (and the shielded-pool exec node) as systemd services; add the env
vars to the unit (or config) to turn on auto-register on a server you want mining the free lane 24/7.

## What is *not* here (yet)

Shielded-pool operations (shield / unshield / shielded transfer) run through the **execution node** and its
in-browser/on-device zk-STARK prover, not L1 `/submit_transaction` — see [privacy.md](privacy.md) and
[wasm-prover.md](wasm-prover.md). HTLC atomic swaps are likewise a distinct flow. These can be scripted the same
way (build the op, submit) but are not yet folded into `nado_cli.py`.

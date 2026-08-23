# Local testnet procedure

Repeatable multi-node testnets on one machine, for fork-resolution and sync work. Everything here is
throwaway: each run lives under `/tmp/nado-forknet-*` (or the harness's own temp dir), never touches
real node data, and cleans up after itself.

## The two harnesses

| harness | what it does |
|---|---|
| `scripts/testnet/run_testnet.py [n] [seconds]` | n meshed nodes from one genesis; passes when they converge on a common tip. The smoke test. |
| `scripts/testnet/test_fork_resolution.py [scenario ...]` | adversarial scenarios (below); exit 0 only if every scenario converges. |

Both launch real `nado.py` processes on loopback IPs (`127.0.0.2`, `127.0.0.3`, …) with
`NADO_TESTNET=1`, which:

- binds each node to its own `127.0.0.x` (no dual-stack listener),
- makes `get_public_ip` return the configured IP (no internet),
- relaxes `check_ip` for loopback peers,
- **skips the baked-in mainnet operator seeds** (`ops/peer_ops.seed_peers`), so testnet children
  never dial production boxes. A testnet that wants seeds sets `NADO_SEED_PEERS` itself.

## Scenarios (`test_fork_resolution.py`)

- **behind** — one node SIGSTOPped while the rest produce, then resumed: must catch up by pure
  forward sync (zero rollbacks on the lagger).
- **split** — two groups boot with disjoint peer meshes from one genesis, each mines its own branch
  until both outgrow `max_rollbacks`, then the partition heals via `/announce_peer`: every node must
  end on ONE branch. This models the 2026-08-23 mainnet incident (measured reorg span 84 vs rollback
  cap 40, graft-point mismatch, mid-branch abandonment).
- **swarm** — N fully-meshed nodes (default 50) from one genesis must converge and keep producing.
  Run it explicitly; it is not part of the default set.
- **clean** — kill every stray testnet node from any prior run (matched by `HOME` under
  `/tmp/nado-forknet-*` + `NADO_TESTNET=1` in its environ) and delete their directories.

```bash
# default set (behind + split), ~15-25 min
python3 scripts/testnet/test_fork_resolution.py

# one scenario
python3 scripts/testnet/test_fork_resolution.py split

# the 50-node swarm (heavy: ~50 python processes; nice it and close other work)
NADO_FORKNET_NODES=50 nice -n 15 python3 scripts/testnet/test_fork_resolution.py swarm

# after a crash / Ctrl+C, or just to be sure nothing leaked
python3 scripts/testnet/test_fork_resolution.py clean
```

## Knobs

| env | default | meaning |
|---|---|---|
| `NADO_FORKNET_NODES` | scenario-specific | node count for `swarm` |
| `NADO_TESTNET_BLOCKTIME` | 6 | seconds per block. 2 is faster but starves mempool gossip on a loaded box — same-height forks from divergent tx sets are then the harness's fault, not the node's. |
| `NADO_TESTNET_PORT` | 19173 | listen port. Default deliberately ≠ 9173 so the suite runs on a box that also runs a production node (a `0.0.0.0:9173` listener blocks every `127.0.0.x:9173` bind). |

## Cleanup guarantees

1. Every scenario tears its nodes down in a `finally:` (SIGCONT first — a SIGSTOPped node ignores
   SIGTERM — then terminate/kill) and the suite has an `atexit` reaper for its own crashes.
2. `clean` is the belt-and-braces sweep for anything that still leaked (e.g. `kill -9` of the suite).
3. Temp dirs are `/tmp/nado-forknet-*`; deleting them is always safe.

## Scaling notes (50+ nodes)

- Budget ~1 CPU-thread per 4-6 nodes at 6 s blocks; a 50-node swarm on a shared box wants `nice`.
- File descriptors: each node opens sockets to every peer; raise `ulimit -n` above 4096 for 50 nodes.
- Loopback IPs `127.0.0.2..127.0.0.254` need no setup on Linux (the whole 127/8 answers).
- Prefer one big `swarm` for scale smoke and small `split`/`behind` nets for behavioral assertions —
  a 50-node split takes much longer to outgrow the rollback cap than a 5-node one and proves no more.

## Adding a scenario

Write a `scenario_<name>()` in `test_fork_resolution.py` using the helpers (`launch(n, meshes)` for
custom peer meshes, `announce(i, ip)` to heal partitions, `SIGSTOP`/`SIGCONT` on `procs[i]` for lag,
`wait_converged` for the pass signal), register it in `SCENARIOS`, and always tear down in `finally:`.

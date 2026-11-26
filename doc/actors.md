# NADO actors — the manifest and the standard

An **actor** is a packaged program that does a job on NADO on someone's behalf — a market maker, a watchtower, an
agent that builds in Land — described by one manifest so anyone can find it, see exactly what it may do, run it the
standard way, and check afterwards that it did its job. The idea is Apify's Actors (operator, 2026-11-26: "i kinda
like the idea of Actirs that apify has … do the manifest and standardisation"); the constraints are NADO's.

This document is the standard. `actors/schema.json` is its machine form, `tools/actor.py` validates a manifest and
builds the standard command line, and `tests/test_every_actor_manifest_is_valid_and_pins_its_code.py` holds every
manifest in `actors/` to it. A registry contract and paid runners come later (issue tracked); a manifest is the unit
they will publish and run, so it is designed for them now.

## The rules that are not negotiable

1. **An actor never takes the user's wallet key.** It acts as **its own identity** (`identity.kind: "own-key"` — a key
   it generates, funded with only what it may spend, or granted a scoped allowance) or needs none (`"none"`). The one
   exception is an operator's own job on their own node (`"node-wallet"`, `audience: "operator"`), and a manifest that
   claims `audience: "anyone"` may not use it. (CLAUDE.md §8: a private key is never asked for.)
2. **An actor runs off-chain.** Consensus is a pure function of agreed data; an actor reads networks and clocks. It
   reaches the chain only by submitting ordinary signed transactions, which every node verifies.
3. **What it may do is declared, and checkable.** `effects` names every contract and L1 recipient it may transact
   with and what it may spend; `verify` says how anyone confirms, **from the chain**, that it did its job. A payer
   pays for observed results, not for claimed work.
4. **The code is pinned.** `source.sha256` is the entry file's hash; a manifest describes exactly one version.

## The manifest — `actors/<id>/actor.json`

```jsonc
{
  "manifest": "nado-actor/1",                 // the standard's version
  "id": "otc-watchtower",                     // [a-z][a-z0-9-]{2,47}, unique
  "version": "1.0.0",                         // semver of this actor
  "title": "OTC watchtower",
  "summary": "Expires stale cross-chain orders and relays revealed secrets so swaps finish without both parties online.",
  "category": "dex",                          // dex | bridge | land | chain | utility
  "audience": "anyone",                       // anyone | operator
  "runtime": { "lang": "python3", "entry": "scripts/otc_watchtower.py", "requires": ["bitcoin-cli (optional)"] },
  "source": { "repo": "https://github.com/hclivess/nado", "path": "scripts/otc_watchtower.py", "sha256": "…" },
  "identity": { "kind": "own-key", "how": "keys.dat under $HOME — a key made for the tower, funded for fees only" },
  "commands": {                               // the entry's subcommands (argv[1]); one, if it has none
    "scan": {
      "summary": "one pass (or a loop) over the open book",
      "inputs": {                             // each input maps to the entry's own flag or environment variable
        "submit": { "type": "boolean", "default": false, "cli": "--submit", "description": "actually post" },
        "loop":   { "type": "integer", "default": 0, "cli": "--loop", "description": "seconds between passes; 0 = once" }
      },
      "effects": { "transactions": true, "contracts": ["otc"], "l1": ["blob"], "spends": "fees only" }
    }
  },
  "safety": { "dry_run_by_default": true, "arm": "submit" },   // which input turns a dry run into real transactions
  "lifecycle": { "mode": "both", "loop_input": "loop" },       // once | daemon | both
  "verify": "Expired orders show status 4/5 and settled ones carry the secret in /exec/otc/order — every effect is on-chain."
}
```

### Fields

| field | required | meaning |
|---|---|---|
| `manifest` | yes | `"nado-actor/1"` |
| `id` | yes | lowercase kebab, 3–48 characters; the directory name under `actors/` |
| `version` | yes | semver (`1.0.0`) |
| `title`, `summary` | yes | what a person sees in a store; `summary` ≤ 200 characters |
| `category` | yes | `dex`, `bridge`, `land`, `chain` or `utility` |
| `audience` | yes | `anyone` (anyone may run it as themselves) or `operator` (a node operator's own job) |
| `runtime.lang` | yes | `python3` or `node` |
| `runtime.entry` | yes | the file run, repository-relative |
| `runtime.requires` | no | other programs it needs, as prose |
| `source.repo`, `.path`, `.sha256` | yes | where the code is and its exact hash (`path` = `runtime.entry`) |
| `identity.kind` | yes | `own-key`, `none`, or `node-wallet` (operator only) |
| `identity.how` | yes | where its key lives and how it is funded or granted |
| `inputs` | no | **global** inputs: options the entry takes *before* its command (argparse's top-level options, e.g. the Land agent's `--server`, `--keys`) |
| `commands` | yes | one entry per subcommand the entry takes (its `argv[1]`), or one named `"run"` if it takes none — then nothing is put before the flags |
| `commands.*.summary` | yes | one line |
| `commands.*.inputs` | no | its inputs (below) |
| `commands.*.effects` | yes | `transactions` (bool), and if true: `contracts` and/or `l1` (what it transacts with) and `spends` (prose) |
| `safety.dry_run_by_default` | if any command transacts | whether a run posts nothing unless armed |
| `safety.arm` | if dry-run by default | the input that arms it |
| `lifecycle.mode` | yes | `once`, `daemon` or `both`; `loop_input` names the input that makes it repeat |
| `verify` | yes | how anyone confirms its work from the chain |

### Inputs

```jsonc
"plot": { "type": "integer", "required": true, "cli": "--plot", "description": "the plot it builds on" }
```

`type` is `string`, `integer`, `number` or `boolean`; `default` must have that type; `enum` lists the allowed values;
`required` inputs have no default. Each input reaches the program **one way**: `cli` (a flag the entry itself parses)
or `env` (an environment variable it reads). The validator checks that the entry's source actually contains that flag
or variable name, so a manifest cannot promise an input the code does not take.

### The standard invocation

`tools/actor.py cmd <manifest> <command> [name=value …]` builds the exact command line: the interpreter, the entry,
the command (unless it is `run`), then each given input as its flag (`--name value`; a boolean as the bare flag when
true) — and the `env` inputs as an environment to set. `tools/actor.py run …` executes it. A registry runner will call
the same function, so a person running an actor locally and a runner running it for them do the same thing.

## Validation

`python3 tools/actor.py validate actors/<id>/actor.json` checks, beyond the schema's shape:

- the entry exists, `source.path` is the entry, and its SHA-256 is `source.sha256` (`tools/actor.py pin` refreshes it
  after a deliberate change — and the version should move with it);
- `audience: "anyone"` never uses `node-wallet`; a transacting command has an identity;
- every `cli` flag and `env` name appears in the entry's source, and every command name too (unless `run`);
- defaults match their types and enums; required inputs have none;
- a command that transacts names what with, and a dry-run-by-default actor names an `arm` input that exists.

## The first actors

| id | audience | what it does |
|---|---|---|
| `otc-watchtower` | anyone | expires stale cross-chain orders, relays revealed secrets (dry-run unless `--submit`) |
| `land-agent` | anyone | builds, gathers, crafts and trades in Land as its own identity, for a plot owner who invited it |
| `otc-market-maker` | operator | keeps the cross-chain book filled from the node wallet (`nado-otc-mm.service`) |

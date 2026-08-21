# Security Policy

## Supported versions

NADO is **testnet-stage alpha**. Only the tip of `main` (the current chain id named in
`README.md`) receives fixes. Older chain generations are wiped on every reroll and are
not supported.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security bugs.**

Report privately via one of:

1. **GitHub private vulnerability reporting** — *Security → Report a vulnerability* on the
   repository (preferred; gives you a tracked advisory and CVE assignment if warranted).
2. A direct message to a maintainer on the project Discord (link in `README.md`). Ask for a
   maintainer; do not post details in public channels.

Include: affected component (consensus / execution layer / STARK prover / wallet page /
messaging / shielded pool / a specific game contract), a reproduction or proof-of-concept,
impact, and whether you believe it is being exploited on the live testnet.

### What to expect

| Stage | Target |
|---|---|
| Acknowledgement | 72 hours |
| Triage + severity | 7 days |
| Fix on `main` for consensus-critical bugs | as fast as a coordinated reroll allows |
| Public disclosure | after the fix has shipped and validators have updated, coordinated with you |

Consensus and state-root fixes frequently require a **coordinated chain reroll** (see
`doc/determinism-and-chain-id.md`). Please allow for that when discussing disclosure timing.

## Scope

In scope:

- Consensus (fork choice, finality, RANDAO, slashing), block/tx validation, peer protocol
- Execution layer, zkVM, STARK prover/verifier, settlement and DA
- Shielded pool, messaging, aliases
- Game contracts under `execnode/` (fund-lock, determinism, griefing, economic exploits)
- The browser wallet/explorer/miner page served by every node
- The desktop wallet (`pyside_wallet.py`)

Out of scope:

- Denial of service by raw volume against a single public node
- Issues requiring a compromised validator key or physical access
- Third-party services (Discord, GitHub, hosting providers)
- Findings already listed in `SECURITY_AUDIT.md` / `SECURITY_FIXES_PLAN.md`

## Safe harbour

Good-faith research conducted against the **testnet** and within scope will not be met with
legal action by the project. Do not access, modify or exfiltrate other users' data, do not
attempt to disrupt the network beyond what a proof-of-concept requires, and stop and report
as soon as you have confirmed an issue. Testnet coins have no value; there is no bug bounty
at this time.

## Audits

Internal audits are recorded in `SECURITY_AUDIT.md` and `doc/security-audit-*.md`. No
independent third-party audit has been completed. Treat the software accordingly.

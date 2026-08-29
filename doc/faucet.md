# The Faucet — the airdrop-play PRIZE BANK

Status: **LIVE**. Owner: games/exec layer. One L1 reserved recipient (`faucet`) + one fixed-name
exec contract (cid = the literal string `"faucet"`, `execnode/games/faucet.py`).

## 1. What it is

The faucet is a **prize bank**, not a handout tap. There is **no self-serve claim** — no PoW grind,
no per-address grants, no enrollment registry. The loop:

1. **Funding in** — anyone sends NADO to the literal L1 address `faucet` (a plain transfer from any
   wallet; the exec node mirrors each donation into the contract's balance), the treasury can pay it
   via a governance spend (`treasury_vote`/`treasury_execute` allow the reserved `faucet` recipient),
   and anyone can top it up exec-side with the contract's `fund()`.
2. **Airdrop play** — enrolled games offer free play; the results land on each game's scoreboard.
3. **Prizes out, daily** — the operator's distributor (`_faucet_rewards.py`, run by
   `scripts/nado-faucet-rewards.timer`) tallies every
   enrolled game's leaderboard off-chain — a PROVABLE computation: the boards derive from the game
   contracts' on-chain storage, so anyone can recompute them and audit that the right addresses were
   paid — and calls the contract's `reward(idx, day, rank, addr, amount)` per top finisher
   (rank shares 40/25/15/12/8% of each game's daily budget).

## 2. The contract

Two methods, nothing else:

- `fund()[value]` — anyone tops the bank up; zero-value reverts.
- `reward(idx, day, rank, addr, amount)` — **operator-only**; **idempotent** per `(game, day, rank)`
  via an `H(idx, day, rank)` marker, so a re-run of the distributor can never double-pay; an
  underfunded payout reverts (fails closed).

The operator gets no new powers over user funds: the faucet balance is donations earmarked for
prizes, and every payout is publicly attributable to a scoreboard placement anyone can verify.

## 2b. Scheduling the distributor — the step that is easy to miss

**Donations do not pay themselves out.** `reward()` is operator-only and nothing in the node calls it, so a
faucet with no scheduled distributor accumulates forever and every airdrop-play board goes unpaid. That was
the live state on betanet-3: a funded bank, 14 enrolled games, and no distributor on the box — the code was
written and simply never scheduled, with nothing in the repo to notice was missing.

    sudo scripts/install-timers.sh          # installs + enables the faucet timer (and the bet oracle)
    systemctl list-timers 'nado-*'          # confirm it is armed
    systemctl start nado-faucet-rewards     # run one now; safe, see below

Runs daily at 00:20 UTC — after the boundary the boards are keyed on, because they rank YESTERDAY's
verified play. `Persistent=true`, so a box that was down at 00:20 still pays that day rather than silently
skipping it, and `RandomizedDelaySec` keeps several operators out of the same block.

Re-running is safe by construction: the contract marks `(game, day, rank)` and reverts a repeat, an
underfunded payout reverts, and the per-game daily budget is capped in the script — so a stuck or
double-firing timer cannot double-pay or drain the bank.

## 3. Enrolling a game

Add the game to `_faucet_rewards.py`'s `GAMES` list with its cid and leaderboard `kind`
(`duel` — 2-seat winner tally · `table` — N-seat winner seat 1..4 · `banked` — settled won seats ·
`battleship` — fewest shots to sink the fleet), turn on the scoreboard prize column in the game's
client (`renderScore(..., prize=true)`), and set `faucet:true` on its hub tile. That's the whole
enrollment — the prize note on the scoreboard (`sdk.prizeNote`) tells players the top K win daily.

## defund(amount) — the operator's own money can come back; nobody else's ever can

Added 2026-08-29. The faucet keeps two counters in its own storage: **DONATED** (slot 7) — NADO the
operator put in, whether by an exec-side `fund()` from the operator or an L1 donation the exec node
mirrors — and **DEFUNDED** (slot 8) — what `defund()` has taken back. `defund(amount)` is operator-only
and requires `DONATED − DEFUNDED ≥ amount`; a treasury → faucet payout raises the faucet's balance but
never DONATED, so public money in the faucet cannot leave through this path, for anyone. Both counters
are readable in the contract's view (`donated`, `defunded`), so the take-back is auditable on chain.

When the upgrade that introduces `defund` is applied, DONATED is seeded once with the faucet's balance
at that block: everything in it until then was the operator's funding (the treasury had never paid in —
checked against the ordered stream before shipping). Every node applies the same upgrade at the same
height and reads the same balance, so the seed is deterministic. `tests/test_faucet_defund.py`.


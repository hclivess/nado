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
3. **Prizes out, daily** — the operator's distributor (`_faucet_rewards.py`, cron) tallies every
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

## 3. Enrolling a game

Add the game to `_faucet_rewards.py`'s `GAMES` list with its cid and leaderboard `kind`
(`duel` — 2-seat winner tally · `table` — N-seat winner seat 1..4 · `banked` — settled won seats ·
`battleship` — fewest shots to sink the fleet), turn on the scoreboard prize column in the game's
client (`renderScore(..., prize=true)`), and set `faucet:true` on its hub tile. That's the whole
enrollment — the prize note on the scoreboard (`sdk.prizeNote`) tells players the top K win daily.

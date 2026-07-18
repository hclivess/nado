# Sovereign — a persistent nation-war MMO on NADO

Status: **LIVE** on alphanet-6 (`sovereign.nadochain.com`). Engine + tests (`static/sovereign-engine.js`, `tests/sovereign_engine_test.mjs`,
ALL PASS). Contract + client + practice next.

## 1. What it is

Sovereign is an original clean-room clone of the classic Czech browser-strategy MMO **Webgame.cz**
(scraped from help.webgame.cz). Mechanics are not copyrightable; **every name, label, number layout and
line of code here is original** — no trademarked names, no copied text (same rule as Scrapline/Stormhold).
You rule a nation: gather four resources, raise cities and industry, pick a government, research
technology, field an army, and **raid other players' nations for land and loot** in one shared, always-on
world with a global ranking.

This is a **new pattern** for our game SDK. Everything so far is either a 2-player move-log DUEL
(chess/stormhold/scrapline) or a house-BANKED table (dice/poker/…). Sovereign is a **persistent shared
world**: one contract holds every nation, production runs on the clock, and any player can attack any
other. The reusable core of that pattern (below) is worth an SDK module of its own.

## 2. The mechanics (faithful to the source)

- **Four resources**: people, money, food, energy (32-bit caps, as in the source). People earn $0.0125
  each per turn; 1000 people eat 0.25t food; buildings draw energy; armies eat food (mechs eat energy).
- **Territory + 13 buildings** (village/city/market/farm/lab/factory/barracks/plant/arena/base/builder +
  unbuilt/ruin), each with the source's exact per-turn effect. Build rate = `12 + builders/6` per turn;
  rising unit cost `300 + count·0.3`. Colonize for land; can't hoard >50% empty.
- **10 governments** with multiplicative bonuses/penalties (anarchy/feudal/dictator/zealot/commune/
  technoc/democ/republic/utopia/robocracy — robocracy unlocks at day 25 and runs on energy not food).
  Change by **revolution**, which taxes the nation (painless only from anarchy).
- **Satisfaction** (`joy`): each point above/below 50 shifts money ±0.75%, tech/military ±0.5%; raised by
  arenas + government, lowered by nation size and raids; drives population growth.
- **6 units**: soldier 1/1, tank 6/4, fighter 6/0, bunker 0/6, mech 2/3 (−20% losses, energy-fed), agent
  (spy). Soldiers train passively in barracks; machine units cost components (factories) + money.
- **5 technologies** (weapons/agronomy/grid/commerce/housing), each level a production multiplier bought
  with tech points (rising cost).
- **Combat**: three attack kinds (conquest/plunder/annihilation) resolved as a **pure function** of the
  two nations' strengths + one block-hash roll (±15% luck). Loot moves land + goods off the loser onto
  the winner; annihilation razes buildings into rubble; both sides take casualties (mechs bleed less).
  Provable exactly like a duel move.
- **Prestige** = the world ranking, computed from land + people + buildings + army + tech.

### Coverage (toward 1:1 with the source manual)

MODELED with the source's exact numbers (engine + client, tested): the 4-resource economy, 13 buildings +
territory/colonize, 10 governments + revolution, satisfaction, 6 units, the tech axes, prestige (exact
point values), 14 RANKS + cumulative veteran bonuses, 9 GENERALS (per-level bonuses/caps/XP ladder,
probabilistic award), normal combat + exact composition bonuses + conqueror/liberator, 6 TACTICAL attacks,
4 MISSILES (+ ½-effect-outside-war, interception), ~20 ESPIONAGE operations (infiltrate/sabotage/theft
with danger-scaled success and agent losses), the DOMESTIC MARKET (stock-scaled prices, gov discounts,
Country #0 sell), ADVANCES/Pokroky (5 types, difficulty-scaled cost), EVENTS ×15 + CATASTROPHES, ALLIANCES
(≤10, government-bonus aggregation × floor(members/2)) + war clock, UFO/alien contact, MEDALS.

APPROXIMATED vs the source (documented, not pixel-exact): the tech-tree effect RANGES (modeled as clean
per-level multipliers rather than the source's per-technology min/max bands and double-per-point cases);
the anti-missile interception curve; event magnitudes.

NOT YET modeled (honest gaps — the remaining waves): the WORLD MARKET (player-listed order book — the
domestic market to Country #0 is in; peer-to-peer orders need an on-chain order book), EMBARGO (UN
voting), the deeper DIPLOMACY (coalitions assisting combat/spy, pacts, fake-war penalties, defector,
partners), and the meta layer (info cards, per-age rewards/credits, the full medal roster tiers 4–5).

## 3. The persistent-world contract model (the new SDK pattern)

The hard, novel part is running one shared, always-on world on a zkVM with **no background process** —
and the shipped answer is the opposite of a fat per-nation contract. The pattern (reusable for any future
idle/4X/territory game):

- **One GLOBAL append-only ACTION LOG; the contract is a thin RECORDER, not a referee.** `sovereign.py`
  stores a single ordered log of packed actions (`op + params`, the engine's `encAction`), each bound to
  its index (`ply == mc`, the same anti-rollback trick as a duel move so a stale re-signed action can't
  double-append or land out of order). It does **not** store per-nation economies or run `settle`.
- **All economy + combat rules live in the browser engine** (`static/sovereign-engine.js`); every client
  **folds the whole log into the world state**, settling every nation's lazy production deterministically
  as it replays. Because the referee is the engine, an illegal action (can't afford, hoarding, shielded
  target, unarmed) is simply a **replay no-op** — no on-chain rules check is needed, and every honest
  client derives byte-identical world state from the same log.
- **PvP is just two log entries interpreted by the replay.** A raid records the attacker's action; the
  engine resolves `combat()` against a finalized block-hash roll and applies loot + casualties to both
  nations during the fold. The defender needs no signature (their state is public and self-defending),
  exactly like a duel's illegal-move dispute — validated by re-execution.
- **Rankings + world map** are pure reads over the replayed state: enumerate nations, sort by prestige,
  render the target list — all from the same fold every client runs.
- **Anti-grief rails** (v1, enforced in the engine's replay): a protection window for young nations,
  loot-band caps (the source's 2–16% etc.), a raid cooldown via army readiness, and a minimum-land floor.

Money/coins: Sovereign is a **free strategy world**, not a staked/banked game — no NADO escrow, no house.
Founding and every action is a plain `blob` call (the L1 tx fee is the only cost, which also rate-limits
spam). The optional stake hook (entry buy-in, prize pool for the season's #1) is a later wave, kept out of
v1 so the economy can't be pay-to-win.

## 4. Practice mode (offline, no wallet)

Per house rules every game ships a free practice mode. Sovereign's is a **single-player sandbox against
bot nations**: `practice.js` persistence holds your nation; a deterministic set of AI nations (seeded)
populate the world; you build/raid/climb entirely client-side through the same engine. No chain, no
wallet — and it doubles as the tutorial. The "big automatic multiplayer" is the on-chain shared world;
practice is the same rules with local opponents.

## 5. Files

- `static/sovereign-engine.js` — the deterministic simulation (done): resources, production/settle,
  buildings, governments, satisfaction, army, tech, combat, prestige. Pure, shared by contract + client +
  practice + tests.
- `tests/sovereign_engine_test.mjs` — determinism / boundedness / action-legality / loot-conservation
  (done, ALL PASS).
- `execnode/games/sovereign.py` — the contract: a **single global append-only ACTION LOG** (a thin
  recorder, NOT a per-nation referee — the economy + combat rules live in the browser engine, which
  every client replays; see §3). Registry + prestige view.
- `static/sovereign.js` + `.html` — the client: nation dashboard, build/army/tech/gov panels, the
  world/ranking/target board, raid flow, practice mode.
- `static/sovereign-art.js` — original SVG glyphs for buildings/units.
- i18n `sovereign.*` ×16, nginx `sovereign.nadochain.com`, hub tile.

## 6. Rollout note

The chain rerolled to **alphanet-6 today** (memory: `nado-alphanet6-reroll`), so the whole game fleet
needs redeploy regardless — Sovereign deploys alongside that pass. Being brand-new, it has no legacy
state to carry.

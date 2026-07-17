# Sovereign — a persistent nation-war MMO on NADO

Status: **IN BUILD.** Engine + tests done (`static/sovereign-engine.js`, `tests/sovereign_engine_test.mjs`,
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

Deferred to later waves (documented, not v1): generals, missiles, the full 25-op espionage suite,
alliance diplomacy/treaties, events/UFO, medals/ranks. The v1 core is a complete play loop: build →
grow → army → raid → climb the board.

## 3. The persistent-world contract model (the new SDK pattern)

The hard, novel part is running a time-based economy on a zkVM with **no background process**. The
pattern (reusable for any future idle/4X/territory game):

- **One contract, keyed by owner.** Each nation's state lives in slots keyed by the owner's address
  digest: resources, `tick` (the turn index at its last touch), land, the building/unit/tech vectors,
  government, satisfaction, prestige, alliance.
- **Lazy production — "settle on touch".** There is no cron. Every method first runs `settle(nation,
  turns)` where `turns = (block_cursor − last_cursor) / TURN_BLOCKS`. Production is pure arithmetic ×
  turns (O(1), not a loop over history), so it proves cheaply and every node computes the same result. A
  nation nobody has read still "produced": its resources are whatever `settle()` yields from the elapsed
  turns — the client shows the settled view, the contract writes it on the next action.
- **PvP that mutates two accounts.** `attack(target, kind, comp, …)` settles BOTH nations to the same
  turn, resolves `combat()` against a finalized block-hash roll, and writes back the loot transfer +
  casualties to attacker AND defender. Deterministic and provable; the defender needs no signature (their
  stored state is public and self-defending) — the raid is validated by re-execution, same trust model as
  a duel's illegal-move dispute.
- **Rankings + world map** are pure reads: the client enumerates nations from the registry, settles each
  to `now` locally (the same engine the contract uses), sorts by prestige, and renders the target list.
- **Anti-grief rails** (v1): a protection window for young nations, loot-band caps (the source's 2–16%
  etc.), a raid cooldown via army readiness (`ready −30` per attack, recovers over turns), and a floor on
  minimum land so a nation can't be wiped to zero.

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
- `execnode/games/sovereign.py` — the persistent-world contract (next): per-nation storage, settle,
  found/build/demolish/recruit/research/revolt/colonize/attack, registry + prestige view.
- `static/sovereign.js` + `.html` — the client (next): nation dashboard, build/army/tech/gov panels, the
  world/ranking/target board, raid flow, practice mode.
- `static/sovereign-art.js` — original SVG glyphs for buildings/units.
- i18n `sovereign.*` ×16, nginx `sovereign.nadochain.com`, hub tile.

## 6. Rollout note

The chain rerolled to **alphanet-6 today** (memory: `nado-alphanet6-reroll`), so the whole game fleet
needs redeploy regardless — Sovereign deploys alongside that pass. Being brand-new, it has no legacy
state to carry.

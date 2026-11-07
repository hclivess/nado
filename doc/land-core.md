# Land: digging to the core — design (#112)

"literally to the core" (operator). This is the design that the generator, the mesher, the walker, aiming and the world
server must all agree on before any of it is built. Nothing here is consensus: the deep is off chain like every other
cell of Land.

## Where we are

- Layer `h` sits at radius `R0 + h` (land-world `posOf`). R0 = 83,443 m and the sea is layer 96.
- What exists today is a crust 256 layers thick. Layers 0–3 are unbreakable bedrock; the generator answers
  bedrock for every `h <= 0`.
- From sea level to the centre is about **83.5 km**.
- A column is about 1 m wide at the surface. A column of the same grid at radius `r` is `r / R0` m wide. At half the
  radius it is half a metre, and near the centre a needle. The deep therefore cannot reuse the surface grid all the way
  down. It has to coarsen.

## Geometry: shells that halve the grid

Below layer 0 the planet is cut into **shells**:

- Shell `k` is the band of radius `R0 / 2^(k+1) < r <= R0 / 2^k`.
- Its grid is the face grid with every `2^k × 2^k` columns merged: `W_k = W >> k` cells per face edge.
- Layers stay 1 m thick everywhere.

So every deep cell is between about half a metre and a metre across, at every depth.

| shell | radius (km) | depth below sea (km) | cells per face edge |
|---|---|---|---|
| 0 | 83.4 → 41.7 | 0 → 41.8 | 131,072 |
| 1 | 41.7 → 20.9 | 41.8 → 62.6 | 65,536 |
| 2 | 20.9 → 10.4 | 62.6 → 73.0 | 32,768 |
| … | halves each time | | |
| 16 | 1.3 m → 0.6 m | ≈ 83.5 | 2 |

- **A deep cell's address** is `(k, face, cu, cv, h)`, with `h < 0` and `k = shellOf(h)`, a pure function of the
  depth. The surface column `(u, v)` lies in cell `(u >> k, v >> k)`. The walker, aiming and collision need only this
  one mapping (`deepCellOf(face, u, v, h)`).
- **The first 41.8 km are shell 0, on the surface grid itself.** Everything down to the bottom of the mantle needs no
  shell boundary at all, only negative layers. Shells are needed only for the last half of the radius (phase 4).
- **At a shell boundary** a coarse cell's top face meets four fine cells. The mesher draws the coarse face as the four
  fine quads it touches, so there is no T-junction crack. The smooth-ground field is crisp across a boundary: one layer
  of blocky rock every ~20 km is not visible.

## What lies down there

The generator stays a pure function of the seed. Every deep cell is decided by noise sampled in metres at the cell's
centre (`posOf`), so a cell is the same block on every client and on the server.

| band | depth | what it holds |
|---|---|---|
| bedrock | layers 0–3 | the floor of the crust: breakable only with a **drill** (phase 2) |
| deep crust | 0 – 2 km | stone, denser veins of today's ores, plus **silver** and **gold** below 300 m |
| upper mantle | 2 – 15 km | **basalt** and green **olivine rock**, **diamond** below 5 km (rare, in pipes), **magma pockets** |
| lower mantle | 15 – 41.8 km | hotter rock, larger magma chambers |
| outer core | r < 0.55 R0 (≈ 37.5 km below sea) | **molten iron**: impassable without a **core shield** |
| inner core | r < 0.19 R0 | solid **iron-nickel** |
| the heart | the six innermost cells, one per face | **the planet's heart**: one item each, six per planet, ever |

- **Magma** is a block. It gives light (it joins the torch pool), burns what touches it (the fire rules of #124), is
  never placed by a player and blocks the walker.
- **Molten iron** is the same, and fills the whole outer-core band.
- **The planet's heart** is the only scarce thing in Land that is not a title. Whether a heart becomes an on-chain
  asset (like a title, `seed = heart tag | planet | face`) is the operator's decision. The design keeps it possible:
  six fixed ids, minted to whoever breaks the cell.

## Travel: 83 km is not dug by hand

At ~1.5 s a cell with an iron pick, a straight shaft to the core is ~35 hours of digging. The deep is an expedition, so it
gets its own tools:

- **Drill.** It bores the cell you aim at and the one below, ~1 m/s. It needs steel (iron and coal at the bloomery and
  anvil) and is the only thing that breaks bedrock.
- **Lift.** A built piece set in a 2 × 2 shaft that carries whoever stands on it up or down at 30 m/s. From the crust
  to the heart takes ~46 min, sitting on it. A lift is a piece like a door: the world server moves its cab and tells
  the players near it.
- **Heat.** Heat rises with depth. Below 2 km the world server refuses work (digging, building) to a player without
  **heat gear**: garments after #111 and #128, of mineral wool spun from olivine. A **core shield** (diamond
  and iron-nickel) is needed to cross the molten iron. Heat is enforced on the server, so no client can skip it. There
  is no health or damage; heat only stops your hands.

## Ownership and storage

- A title covers its plot's column down to layer 0, as today, so only a plot's holder or builders open its bedrock.
  An unowned plot's bedrock is the commons.
- **The deep is commons.** Below layer 0 nobody owns anything and anyone may dig. Unlike the wilderness surface, a dug
  deep cell **does not grow back**: a mine stays a mine, and shafts are shared work.
- **Building is allowed in the deep but not protected.** Anyone may take down a deep piece.
- **The server keeps deep edits by region:** `deep/<k>/<face>/<cu >> 8>_<cv >> 8>.json`, keyed `cu:cv:h`, under the
  same rules (`apply`, gravity, fire) as plot edits. Region files keep a deep mine from costing anything per surface
  plot.
- The chunk key gains the shell: `k:face:cu:cv:ch`, where `ch` may be negative.

## What has to change (every place that assumes `h >= 0`)

- **land-world.js:**
  - `terrainBlock` answers `deepBlock` for `h <= 0` instead of bedrock;
  - `shellOf`, `deepCellOf`, and the deep chunk key;
  - `posOf` is unchanged (it already takes any `h`).
- **land-mesher.js:** negative `ch`, shell-`k` cells (size `2^k` columns), and coarse-to-fine faces at shell
  boundaries.
- **land.js:**
  - `updateChunks` clamps `lo` at 0;
  - the walker and `aim` call `deepCellOf` below 0;
  - the far mesh is unchanged (nobody sees the deep from above).
- **land_server.py:**
  - `1 <= h < H` checks become per band;
  - the deep region store, and `deep` in `blocks_at`, `apply` and `settle`;
  - the heat rule;
  - the lift.
- **land_terrain.mjs:** answers deep cells from the same `deepBlock`.

## Phases (each its own issue, each shipped and tested alone)

1. **The deep crust** (shell 0, to 2 km): negative layers in the generator, mesher, walker and server; silver and gold;
   breakable bedrock with a drill; the deep region store.
2. **Expedition tools:** the drill, the lift and heat gear.
3. **The mantle:** basalt, olivine, diamond pipes, magma pockets (light, fire, blocking).
4. **Shells and the core:** shell boundaries in the mesher, walker and server, molten iron with the core shield,
   iron-nickel, the six hearts (and the operator's call on hearts as assets).

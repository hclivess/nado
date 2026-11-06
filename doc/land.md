# Land — one permanent planet, built on titled plots

Land is a Minecraft-like world in the browser (land.nadochain.com): one planet that everyone shares and that is never
reset. The land is divided into plots; each plot's title is an NFT. Whoever holds a plot's title builds on it, block by
block, and can invite builders. Titles are sold by the operator in fixed-price waves on the NFT marketplace and traded
there afterwards, with the issuer's royalty on every resale.

## Decisions (operator, 2026-11-06)

| question | decision |
|---|---|
| first sale | fixed-price waves on the NFT marketplace; **100 plots** in the first wave, **5 NADO** each |
| royalty on resales | **5 %** (registered once per title with the marketplace) |
| issuer and proceeds | **this server's wallet** (`3cc4c44a…`, execnode/games/land.py `ISSUER`); every batch it signs is asked for first |
| world | **procedurally generated planet**, not Earth-sized: a cube-sphere of radius ~83 km (~87,000 km² of surface) |
| renderer | **three.js r187** WebGPU build (static/vendor/three), WebGL2 where WebGPU is missing |
| live world | its own declared service (nado-land.service), **not** inside the node: a game outage never touches the chain |
| contract | **upgradable** (deployed without the lock flag): "make sure that the contract is not locked when deployed so we can keep upgrading it" |
| world fingerprint timer | **none**: an owner anchors their own plot; nothing signs on a timer |
| privacy | anchors are salted commitments (the chain sees a hash, never the build); private interiors and a provable server are later steps |

## The planet

static/land-world.js is the planet as pure functions; the page, the mesher worker, the world server and the tests all
import (or mirror) it.

- **Geometry.** Six cube faces, each a grid of W = 131,072 block columns (FACE_N = 8,192 plots × PLOT = 16 blocks),
  inflated onto a sphere with the equal-angle (tan) warp; a block is ~1 m wide (0.94–1.0 m measured). Radial layers
  0..255 above R0 = W / (π/2) ≈ 83,443 m; the sea is layer 96.
- **Coordinates.** Grid coordinates (face, u, v, h) are the only stored coordinates. Metres are derived to draw, relative
  to the camera (the page places every mesh at anchor − camera, in doubles), so float32 never carries 83 km.
- **Terrain** is a function of WORLD_SEED: seeded gradient noise sampled in metres on the sphere (continents ~30 km,
  ranges ~12 km, ridges ~2.5 km, hills ~400 m, grain ~45 m), so it is continuous across face seams (measured: 0-layer
  steps). Biomes from temperature (latitude and altitude): grass, beach, rock, snow. Trees never grow within 2 columns of
  a plot edge, so no tree straddles two plots.
- **Plots.** plot = (face · FACE_N + row) · FACE_N + col, below PLOT_MAX = 402,653,184 < 2³². A plot is exactly one
  16 × 16 column of chunks.
- **The landing site** is face 0, plot rows 4924–4933, columns 4662–4671: temperate grassland ~5 m above a sea in sight,
  near the face centre — chosen by scanning the equator band. The first wave is those 100 plots. **Fixed once minted.**

## Titles and the land contract

A title is a native asset issued by ISSUER with `seed` = `0x4C414E44 << 32 | plot`, `dec` 0, `supply` 1, `mintable`
false. Its id is `asset_id(ISSUER, seed)`, so nothing needs a registry: execnode/games/land.py recomputes it in-circuit.

| method | who | what |
|---|---|---|
| `anchor(plot, commitment)` | the holder (title shown) | records the build's commitment; version + 1, anchoring owner and height recorded |
| `allow(plot, builder)` | the holder | grants `builder`; the grant stores its GRANTOR |
| `revoke(plot, builder)` | the holder | removes a grant |
| `builder_of(plot, addr)` | view | the grantor's digest (0 = none) |

**Showing the title.** A contract cannot read another account's balance, so the caller sends the title's one unit in
with the call and the contract pays it straight back in the same call. A title escrowed by a marketplace listing cannot
be shown: a plot on sale is frozen until it sells or is unlisted.

**Grants die with ownership.** A grant names whoever made it; the world server honours it only while that grantor still
holds the title. A sale voids the old owner's invitations with no cleanup call; the new owner may also `revoke` them.

**Upgrades.** The contract is upgradable by its deployer and keeps its cid and storage across an upgrade. The field
numbers and K_B are a live storage layout: add fields, never renumber or reuse one.

## A plot's commitment

A plot's data is its edit list over the generated terrain: `[x, z, y, block]` per changed cell (x, z in 0..15 within the
plot, y the layer, block 0 = removed). The commitment is SHA-256 of

    "nado-land-plot-v1" ‖ plot (u32 BE) ‖ salt (32 bytes) ‖ for each edit sorted by (y, z, x): x u8, z u8, y u16 BE, block u8

as one 256-bit integer — the `anchor` argument. The salt is random per plot and kept with its edits, so the chain alone
reveals nothing about a build; anyone handed the edits and the salt can check them against the chain.

## The client

| file | role |
|---|---|
| static/land.html | the page: HUD, hotbar, block palette, touch controls, help |
| static/land.js | renderer, player movement and collision on the sphere, face-seam crossing, chunk streaming, the far land, aiming, edits, titles, anchoring |
| static/land-mesher.js | the chunk mesher (a module Web Worker): a 16³ chunk with a one-block border wrapped across seams, faces culled |
| static/land-world.js | the planet (above) |
| static/i18n_games/land.json | every string in the 17 languages |

Controls: WASD, Space (jump / up), Shift (run / fast), F (fly), C (down), left click break, right click place, 1–9 and
the wheel pick a block, E opens every block. On a touch screen: left half steers, right half looks, buttons for jump,
down, fly, break, place and the palette.

## Tests

- tests/test_a_land_title_is_shown_to_anchor_or_grant_and_a_sale_voids_the_old_owners_grants.py — the contract
- tests/test_the_land_planet_is_one_continuous_world_and_a_plot_is_what_its_title_names.mjs — the planet
- tests/test_a_plot_holder_builds_on_their_plot_and_nowhere_else.mjs — the page, walked on a touch screen
- tests/test_the_vendored_three_js_is_the_published_r187.py — the renderer's bytes

## Still to build

1. nado-land.service: the websocket world server (wallet login, ownership and grant checks, everyone's edits live,
   plots saved on disk), and the wallet's land login signature.
2. Minting the first 100 titles, registering the 5 % royalty, and listing them at 5 NADO — each batch asked for first.
3. land.nadochain.com (nginx site), the lobby entry, deployment of the contract.
4. Private interiors (encrypted plot data for the owner and their builders) and, later, a provable server.

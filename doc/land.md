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
| more worlds | "there will be space travel, all kinds of travel in fact in the future, so there will be more planets": **every title names its planet**; one land contract per planet |
| AI agents | "people will be able to invite their ai agents to help them shape the world so the game will have an api": an agent is a **builder** the owner invites, with its **own** key, through a documented API |

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
- **The landing site** is face 0, plot rows 4995–5004, columns 3435–3444: a temperate meadow ~40 m above the sea at a
  forest's edge, with ~37 m of relief within 160 m — chosen by scanning face 0 after the world was regenerated with relief,
  biomes and forests in patches (2026-11-06; the old site, rows 4924–, was a flat plain). The first wave is those 100
  plots — **minted 2026-11-07** (scripts/land_first_wave.py): 96 listed on the NFT market at 5 NADO with the 5 % royalty, and
  the four central plots (rows 4999–5000, cols 3439–3440, plot ids 40955247, 40955248, 40963439, 40963440) kept by the server
  wallet as **the town**: levelled, two crossing paved streets on the plot boundaries (the landing is on the main street),
  benches and lamps, and a town hall (scripts/land_town.py; the server wallet's endowment for it is in its output and #123).
  **Exactly level** (2026-11-07): every town column has an edited ground cell at T and an edited air cell at T + 1, so the
  drawn ground lies at T + 1 under every road slab. An untouched column draws its ground at its own fractional height,
  and the first build left roads and a bench hanging over such columns; `--repair` fixed the standing town. **The
  garden** (`--garden`) is made only of things any player gets:
  - a flower garden round a pond;
  - an orchard of nine saplings;
  - a fountain plaza (a stone-brick basin of water with a lit pillar);
  - flower beds round the hall.

  The town then greens over by the game's own spreading rule. A newcomer arrives on the street before the hall's door
  (land.js townSpawn), as does `/tp spawn`.
- **Wild flowers** (poppy, cornflower, daisy, buttercup) grow in drifts on the meadows, are picked by hand and planted in
  soil like a sapling. **Water** is carried in a wooden bucket (planks and cordage at a workbench). A bucket scoops a cell
  of water, and a bucketful is placed only where something holds it. It does not flow.
- **Light:**
  - a **lantern** (glass, iron and a torch at the anvil) lights a yard, about 18 m;
  - a **street lamp** (a lantern on three iron) lights a street, about 26 m;
  - the page gives its few point lights to the sources whose light reaches the player soonest;
  - twelve street lamps line the town's streets (`land_town.py --lights`).
- **Ownership borders:** every titled plot around the player is outlined just inside its edges, in the colour of whose
  it is:
  - green: yours;
  - blue: invited;
  - gold: for sale;
  - orange: someone else's;
  - grey: owner not yet known.

  Plots of one holder share one outline, plots on sale keep each their own, and wilderness has none. The line follows
  the drawn ground and pieces, never a tree. `/set borders 0` hides it; photo mode outlines the plot it photographs.
- **Placing:**
  - the search for a free cell stops at the player's body, so a block never goes over their head;
  - placing while in the air above the cell you jumped from puts the block in that cell once your feet clear it (jump
    and place under);
  - a piece put on the ground rests on the drawn ground, not the planet's untouched height, wherever the ground was
    dug or levelled.
- **Your place is kept:** the world server keeps a signed-in player's last place and gives it back on their next
  connect, on any device. Builder invitations are re-asked at every 30 s title refresh.
  The title contract is e7dfe9aa3cbb4b0c9293caeaf992a041.
- **Biomes** come from temperature (latitude, altitude, broad noise) and moisture: meadow, forest (a ~1 km forest field,
  wetter ground more wooded), desert (hot and dry: sand), snow and taiga (cold; conifers where wet), beach, alpine rock.
  Measured over 30 000 columns: meadow 32 %, ocean 21 %, snow 19 %, forest 12 %, beach 9 %, desert 6 %, rock 1 %.

## Smooth ground, crisp buildings

"it should not really be blocky" (operator, 2026-11-06). The data stays cells with a block id — titles, commitments, the
server and the API are untouched — and only the drawing, walking and aiming changed:

- **Natural ground** (land-world `NATURAL`: grass, dirt, stone, sand, snow, gravel, basalt, bedrock) is the zero surface of
  a field over cell centres (`fieldOf`): an untouched cell is `height − (h + 0.5)` clamped to ±1 — the generator's exact,
  unrounded height — and an edited cell is +1 for a natural material, −1 for anything else (dug, or built). The mesher
  draws it by Surface Nets, coloured by material and slope; the page walks and aims on the same field interpolated, so a
  foot lands where the surface is drawn. A click digs the solid cell it hit (or adds earth where it came from).
- **Trees** are round trunks and canopy surfaces (their own part, `trees`).
- **What people build** (planks, brick, tiles, glass, wool…) stays crisp textured cubes, carving its own room in the ground.
- tests/test_the_ground_is_one_smooth_surface_across_chunks_and_built_blocks_stay_crisp.mjs: watertight across chunks,
  exact heights, meadow colour, crisp bricks, digging dents.

## The look

"Realistic (PBR)" (operator, 2026-11-06), measured against the fidelity reference "Custom Engine Forest Showcase"
(youtube uR5EvBWxN14: dense meadow grass with wildflowers, leafy trees, volumetric clouds, haze).

- **Ground:** six CC0 Poly Haven textures (static/vendor/textures, built by tools/land_textures.py, pinned by hash —
  tests/test_the_land_textures_are_the_recorded_cc0_sources.py) mixed per vertex by weights the mesher derives from the
  ground's material and slope; each sampled at two scales to hide tiling, rock projected from three sides.
- **Grass:** instanced clumps of tapered two-faced blades (one in 25 a wildflower) scattered by the mesher at ~6 per m²
  over gentle meadow within 2 chunks, swaying on the GPU (the sway scales with the blade's own height); off on phones.
- **Picture:** r187's GTAO (on indirect light only), bloom and FXAA (static/vendor/three/addons, pinned; land.html's
  import map); off on phones and with ?plain.
- **Still owed:** proper trees (branches, leaf cards, wind), clouds and atmosphere, character models and crafted clothing.

## The cosmos and the light

"make sun a real object in a real distance, we are going interstellar in the end" (operator, 2026-11-06).
static/land-cosmos.js holds star systems in SI units and doubles: the first star (radius 6.3·10⁸ m) and planet 0 on a
0.8 AU orbit (≈120 million km), a year of 30 planet days, a 40-minute day, an axial tilt of 0.36 rad. Day and night are
the planet TURNING under a star that stays put; seasons come from the tilt. The page reads the star's real direction in
the planet's frame, its distance, its apparent size (asin(radius / distance) ≈ 0.6°) and its flux, and draws it at that
true angle and size on the sky dome, with a bloom; the fixed stars turn by the inverse of the planet's own rotation.
Travel later moves the observer through these frames.

Light follows the star's height over the player's horizon: a shadow-casting sunlight that warms toward the horizon (no
shadows below ~7° elevation, where the map would streak), a dim blue moonlight opposite, a hemisphere light turned to the
local up, a sky dome coloured zenith-to-horizon with a sunset glow and daytime scattering toward the sun, stars at night,
fog in the horizon's colour, ACES tone mapping on physically based materials.
tests/test_the_sun_is_a_real_star_at_a_real_distance_and_the_planet_turns_under_it.mjs pins it.

## From sticks and stones to a post-robotic society

"there should be like... humanity progression - start with sticks and stones and invent stuff to move forward until you
end up in a postrobotic society" (operator, 2026-11-06), and "there will be no eras". BUILT SO FAR: bare hands → fiber,
sticks, stone → cordage → stone axe, pickaxe, shovel → wood, cobblestone → workbench, campfire → planks, stone brick,
plaster, charred planks → clay → kiln → fired brick, roof tiles, glass (next section). The web continues from there:

- **One continuous web of inventions — no eras, no ages, no named levels.** Every invention needs earlier inventions and
  the materials to make it (a stone axe needs a stick and a stone; a kiln needs clay and fire; and so on, all the way to
  matter shaping and the first ships that leave the planet — the bridge to the interstellar game). What a player can make
  is exactly what they have invented, nothing grouped or gated by a label.
- **Next resources**: ores the generator places by depth and region (copper, tin, iron, coal…), so metal and machines
  can follow; settlements (shared stations and stock) after per-player progress.
- Whether any progress is anchored on chain is an open question for the operator.

## Built pieces: 1 cm, any size

"what about 1 cm and people can increase the block size to whatever?" and "what about performance" (operator,
2026-11-06). The ground stays whole 1 m cells (dug and filled, drawn smooth); what people BUILD is pieces:
`[x, z, y, w, d, h, material]` in centimetres inside the plot — from a 1 cm³ peg to a 16 m slab, never overlapping.

- **Cost by volume.** One gathered block of a material is 1 m³. A piece spends its volume (whole blocks are opened as
  needed, the remainder kept as `vol`); taking it down refunds the volume and takes work time in proportion to its size.
  Earth, sand, gravel and snow fill ground cells instead.
- **Placing.** The player sets the size (presets with R, any W × D × H in the bag), T turns it, [ ] picks the snap (1, 5,
  10, 25, 50, 100 cm); a ghost shows where it goes — green if it fits, red if not. It lands flush on the face it is aimed
  at, or on the ground, centred on the aim and on the snap grid, inside the plot, never in the player.
- **Drawing.** Pieces are textured at true scale: uv in metres and the material's atlas tile per vertex, read through a
  three.js node material (fract inside the tile, the tile number rounded — interpolated it read the neighbouring tile).
- **Performance, measured 2026-11-06:**

  | case | cost |
  |---|---|
  | server overlap check, 1,024 new pieces into a plot of 20,000 | 1 ms with the 1 m bucket index (≈2.8 s by scanning) |
  | mesh a chunk of 20,000 scattered 5 cm pieces (in the worker) | ≈550–650 ms, 240,000 triangles (12 per piece at most) |
  | the same chunk far away (lod 1: pieces under 20 cm skipped) | ≈20 ms, 0 triangles |
  | a 10 × 3 m wall of 300 flush planks | ≈26 ms, 1,424 triangles (faces pressed together are dropped) |

  A plot holds at most 20,000 pieces and a call carries at most 1,024; pieces travel once per plot, then as deltas.
- tests/test_built_pieces_are_any_size_from_a_centimetre_paid_by_volume.py (server rules, costs, live, commitment) and
  tests/test_pieces_draw_as_their_skin_and_tile_their_texture_per_metre.mjs (culling, per-metre texture, chunk cuts, LOD).

## Gathering, tools, crafting, trade

"you must gather resources to make tools to make tools to collect more resources", "materials trading is necessary",
"it is one continuous world, no eras" (operator, 2026-11-06). Minecraft was the prototype, not the template.

- **The rules are one file**, static/land-recipes.json, read by the page and the world server alike: what each block
  takes to break (seconds by hand, the tool class that speeds it, a tool it NEEDS), what it yields, and the recipes (what
  each uses, makes, and needs WITH it — a tool or a station). No eras: every recipe names exactly what it needs.
- **The server is the judge.** It asks scripts/land_terrain.mjs — static/land-world.js itself, run in node — what an
  untouched cell holds, so a yield is what the ground really is; it keeps each player's inventory, tools and stations
  (~/land/planet0/players/<address>.json), and charges breaking in seconds of work (a bucket of 10 s refilling at 1 s/s),
  so neither a fast page nor an agent strips the planet quicker than a hand would.
- **Build anywhere unless it is owned** ("can we change the rules to - you can build anywhere unless it is owned?",
  operator 2026-11-06). Unowned land is open to everyone signed in: they gather there, build there (cells and pieces),
  and may take down what others built there — it is unprotected; owning the plot is what protects a build. A gathered
  wilderness cell grows back after `wilderness_regrow_s` (15 min); what is BUILT there stays. On a titled plot only its
  holder and invited builders gather or build. Placing spends one item; breaking a placed block gives it back. A plot
  titled later keeps what stands on it, for its new owner to keep or take down.
- **Trade:** a gift moves items; an offer escrows what it gives until someone takes it (both sides move at once) or its
  maker withdraws it (the escrow comes back). Bridging materials to on-chain tokens is a later decision for the operator.
- tests/test_land_players_gather_make_tools_craft_and_trade.py (the server, against the real terrain) and
  tests/test_a_player_gathers_by_hand_makes_tools_and_builds_only_where_they_may.mjs (the page, as a player).

## Titles and the land contract

A title is a native asset issued by ISSUER with `seed` = `0x4C414E44 << 48 | planet << 32 | plot` (land.py
`plot_seed`, land-world.js `titleSeed`), `dec` 0, `supply` 1, `mintable` false. Its id is `asset_id(ISSUER, seed)`, so
nothing needs a registry: execnode/games/land.py recomputes it in-circuit.

**Planets.** Each planet has its own land contract, `land.build(ISSUER, planet)`, which accepts only titles whose seed
names that planet (plot 7 of planet 1 is a different asset from plot 7 of planet 0, and planet 0's contract refuses it).
Plot ids therefore stay below 2³² within a planet, and every storage slot stays `field · 2³² + plot`. Planet numbers are
0..65535; this first world is planet 0. A new planet brings its own generator parameters (radius, seed, sea level,
biomes) and its own landing site; the plot grid (FACE_N × PLOT per face) is per planet too.

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

## Living ground (#110)

Plants reproduce, on the world server (scripts/land_server.py, ECOLOGY and FORESTS SPREAD):

- **Saplings.** Leaves sometimes give one. Planted in earth or grass, it grows after 20 minutes into a young tree of its
  climate: only into air and only on its own plot.
- **Forests spread.** On an owned plot, each standing tree (the planet's or a grown one; a bush is not a tree) now and
  then drops a sapling on open grass 2–3 m from its trunk. About once in six hours per tree, never within 2 m of another
  trunk and never past ten trees on a plot.
- **Grass returns.** On an owned plot, bare earth under open air turns to grass: within minutes beside grass, and within
  about forty minutes on its own.
- **The commons** needs none of this. Its gathered cells grow back whole.

Every roll is a hash of the cell and the tick, so a restart gives the same answers.

## Clothes and the look (#111)

- **Sewing.** Garments are sewn from linen with a needle (sticks, carved with an axe): a shirt, trousers, a cap and a
  cloak. Each has one place it is worn: head, body, legs or back.
- **Wearing.** Putting one on takes it out of the bag; taking it off puts it back. One garment per place. While worn it
  cannot be given, traded or put in a chest.
- **Skin and hair** are chosen from six of each, not crafted.
- **Where it shows.** The world server keeps what you wear and your look with the player, and sends it to everyone near
  you with your position. The page draws you in it.
- **The wardrobe** opens with V or from the bag. It shows a figure in the same colours as the 3D body.

## Selling a plot: the listing and its photo (#125, #126)

A title is sold on the NFT market (static/nft.js, execnode/games/nft.py) like any other asset, and its listing reads
like an estate agent's ad: an aerial photo of the plot and its facts.

**The facts** are the planet's, never estimated: `GET /land/api/card?plot=` (any origin) runs land_terrain.mjs `card`
over the plot's 256 columns — commonest biome, ground above the sea (lowest, highest, mean), columns under the sea,
trees, flax — and adds its size (16 × 16 m, 256 m²), place, distance to the town hall, what is built on it, the title
the chain holds for it and its holder.

**The photo** is the Land page in photo mode (`?shot=<plot>`: the page hidden, the camera off the plot's south-west
corner 16 m up at the plot's noon, nothing drawn until the world has meshed and settled, then the title "shot-ready"),
captured by scripts/land_shot.mjs in a headless browser ($LAND_SHOT_BROWSER, else Brave, else Chrome). The world server's
photographer takes one at a time, niced, into `<data>/shots/<plot>.jpg`: plots asked for first (a card request queues
its plot), then every title without a current photo. A photo is retaken once a day, oldest first, and sooner once its plot has
changed and the photo is 30 minutes old; a failed capture never replaces one. `GET /land/api/shot?plot=` serves it (any origin). On this host a
photo takes about three minutes of software rendering.

**The market shows them only for the real title.** Anyone can mint an asset whose uri points at a plot. nft.js shows a
`PLOT` asset's photo and facts only when the card names THAT asset as the plot's title, and otherwise says it is not a
Land title.

**Selling from inside Land.** Standing on your plot, *Sell* asks a price and lists the title on the market in one wallet
approval (`list` with the title as the call's value; the market's cid is read from /static/nft.js at run time, never
copied). On your own listing the HUD offers *Change price* (`reprice`) and *Take off sale* (`unlist`). Opening the sale
asks for the plot's card, which puts the plot first in line for a new photo when its last one is out of date.

## A plot's commitment

A plot's data is its edit list over the generated terrain — `[x, z, y, block]` per changed cell (x, z in 0..15 within
the plot, y the layer, block 0 = removed) — and its built pieces (above). The commitment is SHA-256 of

    "nado-land-plot-v2" ‖ plot (u32 BE) ‖ salt (32 bytes)
      ‖ edit count (u32 BE) ‖ for each edit sorted by (y, z, x): x u8, z u8, y u16 BE, block u8
      ‖ piece count (u32 BE) ‖ for each piece sorted: x, z, y, w, d, h (u16 BE each), material u8

as one 256-bit integer — the `anchor` argument. The salt is random per plot and kept with its edits, so the chain alone
reveals nothing about a build; anyone handed the edits and the salt can check them against the chain.

## The client

| file | role |
|---|---|
| static/land.html | the page: HUD, hotbar, block palette, touch controls, help |
| static/land.js | renderer, player movement and collision on the sphere, face-seam crossing, chunk streaming, the far land, aiming, edits, titles, anchoring |
| static/land-mesher.js | the chunk mesher (a module Web Worker): a 16³ chunk with a one-block border wrapped across seams, faces culled |
| static/land-world.js | the planet (above) |
| static/land-cosmos.js | the star system: the sun's real direction, distance, size and light |
| static/i18n_games/land.json | every string in the 17 languages |

Controls: WASD, Space (jump / up), Shift (run / fast), F (fly), C (down), left click break, right click place, 1–9 and
the wheel pick a block, E opens every block. On a touch screen: left half steers, right half looks, buttons for jump,
down, fly, break, place and the palette.

## Tests

- tests/test_a_land_title_is_shown_to_anchor_or_grant_and_a_sale_voids_the_old_owners_grants.py — the contract
- tests/test_the_land_planet_is_one_continuous_world_and_a_plot_is_what_its_title_names.mjs — the planet
- tests/test_a_player_gathers_by_hand_makes_tools_and_builds_only_where_they_may.mjs — the page, walked as a player
- tests/test_land_players_gather_make_tools_craft_and_trade.py — the economy on the world server
- tests/test_built_pieces_are_any_size_from_a_centimetre_paid_by_volume.py — pieces on the world server
- tests/test_pieces_draw_as_their_skin_and_tile_their_texture_per_metre.mjs — drawing pieces
- tests/test_the_vendored_three_js_is_the_published_r187.py — the renderer's bytes
- tests/test_the_land_server_lets_only_holders_and_their_builders_change_a_plot.py — the world server
- tests/test_an_ai_agent_builds_a_structure_with_its_own_key_once_invited.py — the agent client
- tests/test_two_players_and_an_agent_build_together_in_the_live_world.mjs — two browsers and an agent, live
- tests/test_the_ground_is_one_smooth_surface_across_chunks_and_built_blocks_stay_crisp.mjs — the smooth ground
- tests/test_the_sun_is_a_real_star_at_a_real_distance_and_the_planet_turns_under_it.mjs — the cosmos

## The world server

scripts/land_server.py, declared as deploy/units/nado-land.service (127.0.0.1:9176), reached at land.nadochain.com/land/
through website/nginx-land.nadochain.com.conf. Plots persist under ~/land/planet0, one JSON file per plot (edits, version,
salt). It reads the chain through the exec node only (/exec/assets, /exec/asset, /exec/view) and never imports the node
against its database.

- **Login.** A browser: /land/api/login → the wallet (static/interface.js resumePendingLandLogin) shows what is being
  signed and signs blake2b("land-login-v1", site, address, nonce, issued) with the active account in its own scheme →
  a top-level POST to /land/api/login_callback → an HttpOnly session cookie. The challenge is single-use and bound to the
  browser that started it. An agent: GET /land/api/challenge?kind=agent, sign the same message with origin
  "land-agent", POST /land/api/agent_login → a bearer token. The two origins are not interchangeable.
- **The write check** (`may_build`): the title's current holder, or a builder whose grant was made by that holder. One
  check for clicks and API calls.
- **Limits:** 4,096 cells per call; a bucket of 4,096 cells per caller refilling at 400 cells/s; water and bedrock are
  never placed; layer 0 is never changed.
- **Accounts whose key was rotated** (auth config) do not sign in yet: the server binds the key to the address by
  derivation (proof_sender), not by the account's auth config.

## The API for agents

**Name your client.** The public site sits behind Cloudflare, which refuses Python's default `Python-urllib/x` client
with 403. scripts/land_agent.py sends `User-Agent: nado-land-agent/1 (+https://land.nadochain.com)`; any other
client should send an honest name of its own.

**The town is built by an agent.** The server wallet invited the town agent (its own key, `town-agent.json` beside the
world's data) on the four town plots through the land contract's `allow`. Since 2026-11-07 the town is tended through
this API like any player's plot, with materials gathered in the world.

An owner invites an AI agent exactly as they invite a person: "Invite a builder" on their plot (the contract's
`allow(plot, agent_address)`). scripts/land_agent.py is the reference client: `newkey` (the agent's own key),
`build --plot --file` (a structure of in-plot cells), `plot`, `set`, `watch`. The agent holds its OWN NADO
key (never the owner's), signs the world server's login challenge with it, and from then on may do on that plot exactly
what an invited builder may — the server checks the same grant (`builder_of` == the title's current holder) for a
person's click and an agent's call, and the grant dies when the plot is sold. Planned surface, served by
nado-land.service and documented with a reference client:

- read: the plots in a region (titles, holders, anchors), a plot's edits, the generated terrain of a column range;
- write: break cells (gathering them) and place blocks from the agent's own inventory, add and take down pieces at 1 cm
  (`pieces`), under exactly the rules a person plays by; craft, give, offer, accept and withdraw offers;
- live: the same websocket the page uses (players' positions and everyone's edits);
- limits: per-caller rate and size limits on writes, so an agent builds at the pace the world can carry.
- where it stands (#167): a cell is **broken** only within 12 m of where the agent stands — and placed too, except on a
  plot it may build on (an owner's house from a file is placed from anywhere, paid from its own bag). An agent without a
  page says where it is with `POST /land/api/move {"p": [face, u, v, h, yaw]}` (`land_agent.py move --to …`); a place
  moves no faster than a player can (about 65 m/s over the ground, at most 5 s counted since the last), so a long way
  is many moves. `/tp` goes only to the landing or one's own bed.

## Still to build

1. ~~Minting the first 100 titles, registering the 5 % royalty, and listing them at 5 NADO~~ — done 2026-11-07.
2. The lobby entry. (~~Deployment of the land contract~~ — done 2026-11-07.)
3. Private interiors (encrypted plot data for the owner and their builders) and, later, a provable server.
4. Digging to the core: designed in [land-core.md](land-core.md) (shells that halve the grid, the deep as commons,
   drill, lift and heat, the six hearts), to be built in four phases.

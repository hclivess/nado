# Land: from stone tools to a flying X fighter

The operator, playing on the live page (2026-11-09): *"tech up and build an X fighter"*, *"you must add actual physics
like engines and gravity to the game and build a real usable xfighter"*, *"you are not adding any materials — you only add
the initial (like iron ore) and then you add techs all the way until you can build an X fighter"*.

So: no material appears from nothing. Everything below is made by recipe from what the planet already holds; a raw
resource is added only where the chain needs one the ground does not have. Each step ships with its test, its 17
translations, and its issue.

## 1. The chain (recipes; station in brackets)

What exists today: stone tools, campfire, workbench, kiln, bloomery, iron (from ore + charcoal), anvil, hammer, nails,
hinges, bronze, coal, copper ore, tin ore, lime, mortar, glass, silver, gold, the drill.

| step | makes | from | at |
|---|---|---|---|
| steel | steel ×1 | iron ×2 + coal ×1 | blast furnace |
| blast furnace (station) | | stone brick ×12 + clay ×6 + iron ×4 | bloomery |
| copper | copper ×1 | copper ore ×2 + charcoal ×1 | bloomery |
| wire | wire ×4 | copper ×1 | anvil + hammer |
| steel plate (a building material, metallic) | steel plate ×1 | steel ×1 | anvil + hammer |
| machine shop (station) | | steel ×6 + iron ×4 + planks ×4 | anvil |
| gear | gear ×2 | steel ×1 | machine shop |
| silicon | silicon ×1 | sand ×4 + coal ×2 | blast furnace |
| circuit | circuit ×1 | silicon ×1 + wire ×2 + tin ore ×1 (solder) | machine shop |
| power cell | power cell ×1 | copper ×1 + tin ore ×1 + lime ×1 | machine shop |
| motor | motor ×1 | wire ×6 + iron ×2 + gear ×1 | machine shop |
| **thruster** (placeable, works) | thruster ×1 | steel plate ×4 + motor ×2 + circuit ×2 + power cell ×4 | machine shop |
| **pilot seat** (placeable, works) | pilot seat ×1 | steel ×2 + glass ×4 + circuit ×3 + chair ×1 | machine shop |

No new raw resource is needed: every input above is already in the ground (coal, copper/tin ore, sand, clay, iron ore —
tin, not deep gold, solders the circuits so a basic part is not a 300 m expedition). If balancing later wants one (e.g. bauxite for a lighter hull), it is added as ore in rock,
like iron.

## 2. A craft flies

* **What a craft is.** Built pieces that touch one another and include at least one pilot seat and one thruster. Its
  mass is the sum of its pieces' volume × their material's density; its thrust is the thrusters' count × THRUST.
* **Taking off.** A player who may build there sits in the seat (Q on it); the server lifts the connected pieces off the
  plot into a vehicle record (pieces relative to an origin, pose, velocity) — they are no longer the plot's pieces.
* **Flying.** Two kinds of craft, told apart by their parts (static/land-flight.js aeroOf, #191):
  * a **rocket** — thruster blocks, which push up — hovers on its thrust: Space climbs, Down sinks, W A S D push along the
    facing, the mouse looks. Too heavy for its thrust, it does not leave the ground.
  * an **aircraft** — engine parts, which push along their own length, and wing parts, which are lifting area — flies by
    the textbook forces, every number cited in /root/land-research/flight (INDEX.md) or labelled a design choice in
    land-recipes.json "flight".aero: lift ½ρv²SC_L from the wings' area and the angle of attack (2πα for a thin aerofoil,
    reduced for the finite wing), induced + zero-lift drag, a stall past 15°, a bank that turns the path (n = 1/cos φ), a
    load limiter at 9 g, controls whose authority grows with airspeed (nothing turns at a standstill), a nose that
    weathervanes toward the velocity. The mouse is the stick (pitch and roll, self-centring), A D the rudder, W S the
    throttle; Space / C work vertical thrusters only. On the ground it rolls on its gear and leaves it when the wings carry
    it — never on a key. Gravity always pulls. The pose carries pitch and roll ([face, u, v, h, yaw, pitch, roll]).
  The pilot's page simulates; the server bounds a pose by the craft's top speed (the X-wing's stated 1,050 km/h) and
  relays it to every player near it, who draw it in its attitude.
* **Landing.** On the ground it stops; leaving the seat parks it. Parked over a plot where the pilot may build, it can be
  set back down as that plot's pieces; anywhere else it stays a parked vehicle (its owner's), drawn where it stands.
* **Hitting things.** The hull is sampled against the ground and built pieces; a hit stops it (no damage in v1).

## 3. Avatars

Kawaii faces (a set of drawn faces on the head's front), a body type (gender), more hair colours; chosen in the
wardrobe (V), kept by the world server like skin and hair, and seen by everyone nearby.

## Order

1. avatars (small, self-contained) · 2. the chain up to steel plate, then to thruster and seat · 3. flight.

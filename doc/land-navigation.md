# Land: finding the way — from a lodestone to satellites (#173)

The operator, playing on the live page (2026-11-10): *"i cant find the way home"*, *"you need to invent maps, compasses,
navigation systems and give them full research+tech+recipe+ingredient walks"*, *"then you need to install that nav
system into the x and give it townhall destination"*, *"the nav system should show the entire earth - and requires
launching orbital real physical gps satellites into orbit"*.

Rules this follows (True Wind's CLAUDE.md, adopted for Land 2026-11-10): every real-world number is cited to a source
mirrored privately (`/root/land-research/navigation/`, listed in its `INDEX.md`, cited below as *article l.N*); a number
the game sets for itself is derived from the game's own constants, formula shown; anything that is neither is labelled
a **design choice**.

## 0. The planet the satellites circle (the game's own numbers, measured from code)

| quantity | value | from |
|---|---|---|
| radius | 83,443 m | `land-world.js` posOf (R0), `land-cosmos.js` planets[0].radius |
| surface gravity g | 9.8 m/s² | `land-recipes.json` flight.g |
| GM = g·R² | 6.823 × 10¹⁰ m³/s² | derived |
| day | 2,400 s (40 min) | `land-cosmos.js` DAY_S |

## 1. The ladder

Each rung is a recipe from what the planet holds, with a page walk, its 17 translations and its tests — as the flight
chain was (`doc/land-tech-to-flight.md`).

### 1.1 Lodestone — the raw resource

* Real: lodestone is magnetite, Fe₃O₄, naturally magnetised (*Lodestone l.32, l.44*); magnetite is one of the main iron
  ores (*Magnetite l.47*), density 5 g/cm³ (*Magnetite l.33*). Earth's field (0.5 gauss) is too weak to magnetise it;
  the leading theory is the field round a lightning strike (*Lodestone l.66*).
* Game: **magnetite** as an ore in rock, as iron ore is; a magnetite block near the surface is sometimes **lodestone**
  (**design choice**: the share, until there is weather to strike it). New raw resource — the chain needs one the ground
  does not have (the flight doc's rule).

### 1.2 Compass

* Real: the first navigation compasses (China, by 1088, Shen Kuo) were iron needles magnetised by striking them with a
  lodestone (*Compass l.28*); a magnetised needle on a low-friction pivot settles north–south (*Compass l.10*); dry
  compasses in Europe and the Islamic world from about 1300 (*Compass l.28*).
* Recipe: needle (iron ×1, at the anvil, with the hammer) → magnetised needle (needle + lodestone, the lodestone kept)
  → compass (magnetised needle + a clay bowl fired in the kiln + glass ×1).
* Game: held or carried, the HUD shows a compass rose and your heading. North is +v on a face (`land-world.js`
  frameOf) — **design choice**: no declination, the magnetic pole is the grid's north.

### 1.3 Paper, ink and the map

* Real: paper is a sheet of plant fibres collected from a suspension on a screen, pressed and dried (*Papermaking l.2*);
  bast fibres such as hemp were the first (*Papermaking l.19*). Iron gall ink: iron(II) sulfate added to tannic acid,
  traditionally from oak galls (*Iron gall ink l.9*).
* Recipe: paper (fiber ×4 + water, on a screen at the workbench); ink (iron ×1 + a tannin source + water — the game has no bark or galls yet: which of its trees gives tannin is to be
  sourced before the recipe is fixed); a map
  (paper ×4 + ink ×1).
* Game: a map draws the land you have **seen** (cartography by survey), with you on it, the town and your bed. It does
  not know where you are when you have not seen the place.

### 1.4 Dead reckoning — the first instrument in a craft

* Real: position from a previous fix plus speed, heading and elapsed time (*Dead reckoning l.7*); an inertial
  navigation system does it without outside signals (*Inertial navigation system*).
* Game: a **nav unit** (circuit ×4 + compass + gear ×2) installed in a craft (a placeable piece, like the thruster)
  keeps the craft's position from the town hall, and shows the bearing and distance to a destination — the town hall
  first. Its drift: **design choice**, until satellites correct it.

### 1.5 Rockets

Sources: `/root/land-research/rockets/` (INDEX.md).

* **What it takes, round this planet.** Vis-viva (*Vis-viva l.10*) from the surface (R = 83,443 m, GM = 6.823 × 10¹⁰)
  to the satellites' orbit (r = 135,520 m, 1.6): the transfer ellipse leaves at **1,006 m/s** and arrives at 619 m/s,
  where the circular speed is 710 m/s — **1,096 m/s** of Δv from the ground, ideally. Thrusting against gravity costs g·t
  more (*Gravity loss l.11*: the loss is a share g/a of the Δv for an acceleration a) — a rocket that leaves at twice its
  weight loses half its burn holding itself up, so the launch computes it from the rocket's own thrust and mass.
* **The engine.** Hydrogen burned in oxygen, as the RS-25: specific impulse **452 s** in vacuum, **366 s** at sea level
  (*RS-25 l.32-33, l.52*), at an oxidiser-to-fuel mass ratio of **6.03 : 1** (*RS-25 l.43*). The rocket equation
  Δv = Isp·g₀·ln(m₀/m_f) (*Tsiolkovsky rocket equation l.10*) then asks a mass ratio of only **1.28** for 1,096 m/s —
  1.33 with a 15 % allowance for gravity loss: a single stage reaches orbit round a planet this small (on Earth it
  takes stages, *Multistage rocket*). The game engine's thrust is a design choice, scaled to the game's craft.
* **The propellant, from water.** Electrolysis splits water into twice as much hydrogen as oxygen, by amount (*Electrolysis
  of water l.25*), and takes at least ΔG = **237.24 kJ** per mole of water (*l.80*; 285.83 kJ with the heat, *l.82*) — so
  making propellant costs the generators real power. Liquid hydrogen boils at **−252.87 °C** and weighs **70.85 kg/m³**
  (*Liquid hydrogen l.50, l.108*); liquid oxygen is the oxidiser. Chain (stations: an electrolyser and a liquefier, both
  machines on a generator's power, as the factory machines run): water → hydrogen + oxygen (gas) → liquid hydrogen +
  liquid oxygen → a propellant tank's load, mixed 6.03 : 1 by mass.
* **The parts.** A rocket engine (a unit part), propellant tanks (their dry mass and what they hold), and a payload —
  built like any craft on a launch pad, its mass the sum of its pieces' (`land-flight.js`).
* **The launch.** Use on the pad: the world server computes it — the rocket's Δv from its own masses and the engine's Isp,
  less its gravity loss from its own thrust-to-weight — against the 1,096 m/s the orbit asks. Enough, and the payload is
  in orbit; not enough, and it falls back: what goes up is spent (the coins and the work are real; nothing is refunded).

### 1.6 Satellites — the positioning constellation

* Real: GPS satellites orbit at 20,180 km altitude (*Global Positioning System l.21*), radius about 26,600 km, two
  orbits per sidereal day (*l.232*); 24 in the design, six planes of four at about 55° inclination (*l.230*); a receiver
  needs **four** in view — three position coordinates and its own clock error (*l.187, l.216*); three if one coordinate
  is already known (*l.218*).
* Game, the same rule on this planet — two orbits per day:
  * period T = 2,400 / 2 = 1,200 s;
  * orbital radius r = (GM·T²/4π²)^⅓ = **135,520 m**, so **52,077 m** above the ground;
  * orbital speed 2πr/T = **710 m/s**.
  * (The same *ratio* to the radius as GPS, 26,600 / 6,371 = 4.175, would put them 265 km up at 443 m/s with an 82-min
    period — a constellation that does not repeat with the day. The half-day rule is the one GPS was designed around,
    so it is the one kept.)
* A satellite is a real object in the world: launched by a rocket, it stays only if it reaches its orbit's speed; its
  position is computed from its orbit (a pure function of time, so every page agrees); it can be seen crossing the sky.
* A receiver gets a **fix** only with four satellites above its horizon — the constellation has to be built before
  positioning works, and works better as it grows.

### 1.7 The nav system in the X

* With a fix, the nav unit shows **the entire planet** — all six faces, drawn from the terrain generator, which is a pure
  function of the seed (`land-world.js` column) — with the craft on it, its heading, and the route and distance to its
  destination: the town hall.
* Without a fix (fewer than four satellites in view), it falls back to dead reckoning and says so.

## 2. Order

1. magnetite + lodestone in rock, compass, HUD heading — the smallest step that helps "i cant find the way home";
2. paper, ink, the surveyed map;
3. the nav unit in a craft, dead reckoning to the town hall;
4. rocket physics and propellant (sources first);
5. satellites in orbit, the four-in-view fix, the whole-planet map in the X.

Each step: sources read before code, numbers above cited, a page walk of the whole journey (find the ore → make the
thing → use it), 17 translations, tests, its issue.

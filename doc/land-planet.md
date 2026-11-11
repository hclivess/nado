# Land: the planet as a physical body

The operator (2026-11-11): *"we need proper planetary physical properties like in Kerbal space"*. Code:
`static/land-planet.js`; sources: `/root/land-research/planet/` (INDEX.md), cited below as *article l.N*.

## Decisions (the operator's, 2026-11-11)

1. **Keep the size and the pull.** Radius 83,443 m, surface gravity 9.8 m/s². Everything else follows from them.
2. **Real air near the ground, vacuum above a set height** — as Kerbal does — after the findings below ruled out both a
   full real atmosphere and none at all.

## What follows from the size and the pull

| quantity | value | how |
|---|---|---|
| mass | 1.022 × 10²¹ kg | M = g R² / G, G = 6.67430 × 10⁻¹¹ (*Gravitational constant l.9*) |
| density | 420,090 kg/m³ — 76 × Earth's 5,513 (*Earth l.51*) | M / (4/3 π R³) |
| gravity with height | g (R / r)² | Newton |
| escape speed | 1,279 m/s | √(2GM / R) |
| lowest orbit (just above the air, 30 km) | 776 m/s, 15.3 min | √(GM / r) |
| synchronous orbit | 131.7 km up | (GM T² / 4π²)^⅓, T = 2,400 s |
| equator spin | 218 m/s | 2π R / T |

A small world with a strong pull is a very dense one; that is shown to the player (`/planet`), not hidden.

## Why the air cannot be fully real here (the findings that decided it)

* **It never thins out.** Pressure falls with *geopotential* height, H = R z / (R + z) on a planet of radius R
  (*Geopotential height*); on this planet H never exceeds 83.4 km however high z goes. The 1976 standard atmosphere
  (*International Standard Atmosphere*, the layer table) taken at H gives, at z → ∞, about **0.48 Pa** — no height would be
  free of drag, no orbit stable. At the satellites' 52 km the air would be 0.013 kg/m³: drag ½ρu²c_dA (*Drag equation l.6*,
  c_d 1.28 for a face square-on, *Drag coefficient*) of ~6 m/s² against 3.7 m/s² of gravity — down within minutes.
* **It would leak away.** Catling & Zahnle (*Scientific American*, May 2009, `catling-zahnle-2009-planetary-air-leak.pdf`):
  at Earth's ~1,000 K exobase hydrogen averages 5 km/s against 10.8 km/s escape — and leaks. Nitrogen here averages
  869 m/s at 1,000 K (mean speed √(8kT/πm), *Maxwell–Boltzmann distribution*) against 1,279 m/s: a ratio of 1.47, below
  hydrogen's 2.16 on Earth.
* **Airless breaks the world.** No liquid water at zero pressure (the seas, wells, the propellant plant), no fire (smelting,
  generators), no fan-and-motor flight (the X), no breathing.

## The air as built

The 1976 standard atmosphere's whole profile — its seven layers, ground to its 86 km top (temperatures, lapse rates,
pressures; barometric formula with R* = 8.31432, M₀ = 0.0289644 kg/mol, g₀' = 9.80665, *Barometric formula l.8-10*) —
fitted between the ground and **ATM_TOP = 30 km**, then vacuum. Sea level is exactly the standard's: 101,325 Pa, 288.15 K,
1.225 kg/m³; it thins with every metre to 0.3 Pa at 30 km. **ATM_TOP is the one number not from physics** (a design
choice, labelled in the code and shown to the player). The positioning satellites (52 km, doc/land-navigation.md 1.6) fly
above it.

## Still to wire in

1. Flight: gravity g (R/r)² with height, and drag from the air's density (the craft's frontal area, c_d) in place of the
   flight model's fixed drag.
2. Rockets: the launch flown as an ascent — thrust from Isp at the outside pressure (a fixed nozzle's thrust falls
   linearly with it: F = ṁvₑ + (pₑ − pₐ)Aₑ, *Rocket engine*), drag, gravity with height — in place of the closed formula.
3. The star: land-cosmos.js gives planet 0 a 30-day year (20 h) at 0.8 AU; by Kepler that asks a star ~10⁶ times the Sun's
   mass. To be made consistent before anything orbits the star.

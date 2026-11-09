# Land: the civilisation ladder, from foraging to the future

The operator, 2026-11-09: *"we will need all the civilisation essentials like berries, hunting, crops, water, wells,
mills, tools, weapons, transport from the stone age to the future"*, *"farmland, farming, soil types, etc"*, *"trading, global marketplace, no inflationary economy (degrading stuff?)"*, *"local markets first, global only with the
invention of the internet"*.

The rules stay those of `land-tech-to-flight.md`: nothing appears from nothing. The planet holds the raw things (a bush,
wild grain, an animal, water, ore); everything else is made by a recipe at a station from what is reached before it.
Each slice ships with its test, its 17 translations and its issue, and is walked in the page before it is called done.

## Decisions taken (change them by saying so)

* **No starvation.** Food is not a meter that kills a player who stops playing for a day. A meal is a reward: eating
  one makes work quicker for a while (breaking time down a fifth for ten minutes). It can become a need later; it should
  not start as a punishment.
* **Hunting is of animals only.** Weapons work on game, never on players.
* **Farming is on land you may build on** (your plot, or the commons, where it regrows like any gathered cell).

## The economy: trade, one market, and nothing that piles up forever

Trading exists (a gift; an offer that escrows what it gives and is taken atomically). What it lacks, and what this adds:

* **Markets are local first.** An offer is made at a trading stand (a placeable station anyone builds — "trading stands", operator 2026-11-09) and lives
  there: it is seen and taken only by a player standing at that stand, or at another stand within reach of it. Goods
  move between markets by being carried — a hand cart, a boat, a car — so distance and transport have a price, and a
  town with a busy stand is a place. The going rate shown is that market's own, from its offers taken.
* **Wider reach comes with technology**, each a step on the ladder: a messenger's post (offers seen, not taken, at
  stands a few plots away), the telegraph (seen across a region over wire, taken by sending goods), and only **the
  internet** — computers, a network, a server station, late in the tech chain — makes one global market where any offer
  is seen and taken from anywhere.
* **No inflation: things wear, spoil and decay**, so the planet's output is matched by what leaves it:
  * tools and weapons have durability: each break or hit wears them; a worn-out tool is gone (a better tool lasts longer,
    a repair at the anvil costs part of its material);
  * food spoils: berries in a day, bread in three, cooked meat in two, salted or dried food far longer (salt, a smokehouse);
  * fuel burns away (exists: a generator burns its fuel);
  * built things in the commons regrow away (exists); a machine left unpowered for long rusts until repaired;
  * the market takes a small fee in kind on every offer taken (a share of what is given, destroyed) — a sink that
    scales with trade itself.
* **Prices in NADO** (offers paid in coin instead of items) touch real coins and the chain's escrow: they come after
  item-for-item trade works world-wide, and only with the operator's go-ahead.

## The ladder

| era | slice | what the player gets |
|---|---|---|
| foraging | **1. food from the land** | berries from wild bushes, wild grain standing in meadows (pulled like flax: grain and seed), water from a lake with the bucket (exists) |
| stone age | **1. farming** | a stone hoe; tilled soil (farmland); seed sown on it grows through visible stages to ripe wheat in its time; a harvest gives grain and seed back; crops beyond wheat (flax sown, not only wild; vegetables) |
| stone age | **1. soil types** | the ground is not one dirt: loam (meadows; crops grow at full speed), sandy soil (dry, near beaches; slow, poor yield), clay soil (wet lowland; slow but rich), peat (wet, cold; rich once drained), stony (hills; cannot be tilled until cleared). The generator already knows climate and wetness; the soil follows them, is drawn differently, and the hoe says what it is. Farmland next to water stays moist and grows faster; compost (leaves, fiber, scraps) and ash improve a poor field |
| _soil detail_ | | (the farming rules, `land-recipes.json` "farming": per soil a growth time factor and a yield; moist +, fertilised +; a field left untended for long goes back to grass) |
| stone age | **1. bread** | a quern (station) grinds grain to flour; flour and water bake to bread at the campfire; berries and bread are eaten for the work bonus |
| stone age | **1. a well** | a well (placeable, stone and planks and a bucket) gives water anywhere, never running dry |
| stone age | **2. hunting** | animals wander the wilderness (deer, boar, rabbit), simulated by the world server and drawn near players; a stone spear, then a bow and arrows; game gives meat, hide and bone; meat is cooked at the campfire |
| stone age | **2. leather and bone** | hide tans into leather (lime, at a tanning rack); bone needles, leather clothes and a pack |
| bronze/iron | **3. weapons ladder** | spear, bow, bronze then iron then steel blades, crossbow — each a better hunting tool |
| iron age | **4. mills** | a windmill and a watermill: machines (the factory system, #148) that grind grain without a hand, a sawmill that cuts planks |
| iron age | **5. transport I** | a hand cart (wheels and a bed of planks) that carries a chest's worth; a boat that floats on water |
| industrial | **5. transport II** | a car: a motor and four wheels on the ground, driven like the craft but held to the surface (the flight physics with ground contact) |
| industrial | **6. power and light** | a power line from the generator, electric lamps, a pump that fills a tank from a well |
| future | **7. beyond the fighter** | rails and a train, a rocket stage that reaches orbit height over the planet |

## Status

* **1a food from the land, 1b farming and soils — built** (#153, #154): berry bushes and wild grain on the planet; the
  stone hoe; Use with it on turf or earth tills farmland (never stony ground) and says the soil; seed is sown on a field
  and ripens in crop_s (1200 s) × its soil's time, × 0.7 when water lies within 3 columns (a ditch filled from a bucket
  irrigates); the harvest gives the soil's grain and seed. A field's earth is drawn in its soil's colour. Not yet:
  compost and ash, a field going back to grass when left, more crops.
* Next: 1c bread and a well (#155), then hunting (#156).

Order: slice 1 first (one piece at a time, each live before the next), then 2, then the rest as listed.

/*
 * A pet carried to generation 29 SHOWS the same animal, coat, tier and stats it had on generation 28: the page reads
 * its traits from the contract's ROLL TABLE (execnode/games/pets.py RT_BASE; the view's r<c> maps) whenever the pet
 * has one, and from its gene only when it has none (doc/stwo/g5-carry.md 2a).
 *
 * On gen 29 the VM hash is BLAKE2s, so roll32(gene + c) recomputed in the browser would draw a different animal and
 * different stats for every carried pet — and v2 exposes only 64 of the gene's 256 bits, so even a new pet's traits
 * could not be re-derived from gl/gh. Pins (the real static/pets-genes.js):
 *   1. with rolls, every trait (species id, tier, base stats, power, coat, shiny) comes from them — given a DIFFERENT
 *      gene, the traits are still exactly the gen-28 pet's;
 *   2. rollsFrom reads the view's r<c> maps (numbers or strings) and is null for a pet with none;
 *   3. without rolls the gene path is unchanged (every gen-28 pet renders as before).
 * Run: node tests/test_a_carried_pet_shows_its_gen28_traits_from_the_roll_table.mjs
 */
const _el = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => "" : _el, apply: () => _el });
for (const k of ["document", "window", "localStorage", "sessionStorage", "location", "history"]) if (!(k in globalThis)) globalThis[k] = _el;
import "./protocol_hook.mjs";
const { loadCrypto } = await import("../static/nadotx.js");
const G = await import("../static/pets-genes.js");
await loadCrypto(".");

let fails = 0;
const check = (name, ok, detail) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  " + JSON.stringify(detail)}`); if (!ok) fails++; };

const gene = 9236603131523051035n, sp = 2;
const animal = G.animalOf(G.speciesIdOf(gene, sp), sp);
const want = { si: G.speciesIdOf(gene, sp), tier: G.speciesOf(gene), base: G.baseStats(gene, sp), power: G.powerOf(gene, sp),
               coat: G.coatOf(gene, animal) };
const rolls = Object.fromEntries(G.ROLL_OFFSETS.map((c) => [c, G.roll32(gene + BigInt(c))]));   // what the carry stores
const other = gene ^ 0xFFFFFFFF00000000n;                                                       // not the pet's gene
check("1. with rolls the species id, tier, base stats and power are the gen-28 pet's, whatever the gene",
      G.speciesIdOf(other, sp, rolls) === want.si && G.speciesOf(other, rolls) === want.tier
      && G.baseStats(other, sp, rolls).join() === want.base.join() && G.powerOf(other, sp, rolls) === want.power,
      [G.speciesIdOf(other, sp, rolls), want.si]);
const coat = G.coatOf(other, animal, rolls);
check("1. ...and so are its coat and shiny", coat.idx === want.coat.idx && coat.shiny === want.coat.shiny, [coat, want.coat]);
check("1. (the gene alone would have drawn another pet — the rolls are what keep it)",
      G.baseStats(other, sp).join() !== want.base.join());

const view = { ow: { 7: "x" } };
for (const c of G.ROLL_OFFSETS) view["r" + c] = { 7: c === 777 ? String(rolls[c]) : rolls[c] };
const got = G.rollsFrom(view, "7");
check("2. rollsFrom reads the view's r<c> maps, numbers or strings", G.ROLL_OFFSETS.every((c) => got[c] === rolls[c]), got);
check("2. ...and is null for a pet with none (every gen-28 pet)", G.rollsFrom({ ow: { 8: "y" } }, "8") === null);
check("3. without rolls the gene path is unchanged", G.baseStats(gene, sp, null).join() === want.base.join()
      && G.speciesIdOf(gene, sp, null) === want.si && G.coatOf(gene, animal, null).idx === want.coat.idx);
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a carried pet shows its gen-28 traits from the roll table");
process.exit(fails ? 1 : 0);

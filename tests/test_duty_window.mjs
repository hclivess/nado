/* A browser-wallet duty lands in a window, exactly the node's window (static/interface.js dutyWindow).
 *
 * MEASURED LIVE (2026-09-22, 24 h on the relay): splits had climbed from 0.6/h to 2/h as the bonded lane
 * grew 56 -> 61. Every duty involved in a same-height split was the LEGACY exact-landing form, all from
 * browser-wallet validators (7 senders), while the node's own duties (29 of 37 in a 300-block sample) were
 * windowed and never split. Of the 23 duties the relay held and a peer lacked, 22 were LOST — never landed —
 * because an exact-landing tx that misses its one block is dead. The wallet built them at latest + 5 and
 * passed no min_block: the node had posted windowed duties since 2026-08-19 and the wallet never followed.
 *
 * WHAT THIS PINS: the wallet's window is the node's window (min_block = latest + TX_INCLUSION_DELAY, max at
 * the epoch end, capped to the reveal window while a reveal is open); the epoch-tail skip matches; every
 * landing keeps attest/commit in the right epoch; both build sites pass the window; and the node side still
 * uses the same formula, so if it changes this fails and the mirror is redone rather than silently rotting.
 *
 * Run: node tests/test_duty_window.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name); if (!cond) fails++; };

const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');
const num = (name) => Number((js.match(new RegExp(`^(?:const|let) ${name} = (\\d+);`, 'm')) || [])[1]);
const EPOCH_LENGTH = num('EPOCH_LENGTH'), TX_INCLUSION_DELAY = num('TX_INCLUSION_DELAY'), FINALITY_DEPTH = num('FINALITY_DEPTH');
check('constants lifted from the wallet', EPOCH_LENGTH > 0 && TX_INCLUSION_DELAY > 0 && FINALITY_DEPTH > 0);

// lift the function itself, not a copy of it
const src = js.match(/function dutyWindow\(latest, X, revealPossible\) \{[\s\S]*?\n\}/);
check('dutyWindow is defined in interface.js', !!src);
const dutyWindow = new Function('EPOCH_LENGTH', 'TX_INCLUSION_DELAY', 'FINALITY_DEPTH',
  src[0] + '; return dutyWindow;')(EPOCH_LENGTH, TX_INCLUSION_DELAY, FINALITY_DEPTH);

const X = 3000, start = X * EPOCH_LENGTH, epochHi = (X + 1) * EPOCH_LENGTH - 1;
const revealHi = (X + 1) * EPOCH_LENGTH - FINALITY_DEPTH - 1;

// ---- the propagation guard, at every height of the epoch ------------------------------------------
let guardOk = true, epochOk = true, ceilOk = true;
for (let latest = start; latest <= epochHi; latest++) {
  for (const rp of [true, false]) {
    const w = dutyWindow(latest, X, rp);
    if (w.minBlock !== latest + TX_INCLUSION_DELAY) guardOk = false;
    if (Math.floor(w.tb / EPOCH_LENGTH) !== X) epochOk = false;     // attest targets X, commit X+2 — bound to max_block
    if (w.tb > epochHi) ceilOk = false;
  }
}
check('min_block is latest + TX_INCLUSION_DELAY at every height (the node\'s guard, not a 5-block cliff)', guardOk);
check('max_block never leaves epoch X, so attest/commit target the epoch validation derives from it', epochOk);
check('max_block never exceeds the epoch end', ceilOk);

// ---- the reveal cap, exactly as the node applies it ---------------------------------------------------
check('while a reveal is possible and its window is open, max_block is capped to the reveal window',
  dutyWindow(start + 3, X, true).tb === revealHi);
check('a dead reveal lifts the cap: the duty runs to the epoch end',
  dutyWindow(start + 3, X, false).tb === epochHi);
check('once the reveal window has shut (revealHi <= latest) the cap lifts too',
  dutyWindow(revealHi, X, true).tb === epochHi);
check('the reveal is included iff max_block is inside its window (the wallet\'s unchanged condition)',
  dutyWindow(start + 3, X, true).tb <= revealHi && !(dutyWindow(revealHi, X, true).tb <= revealHi));

// ---- the epoch tail: skip exactly when the node skips (min_block > max_block) ----------------------
const skips = (latest, rp) => { const w = dutyWindow(latest, X, rp); return w.minBlock > w.tb; };
check('a duty still posts TX_INCLUSION_DELAY blocks before the epoch end (min == max, lands on the last block)',
  !skips(epochHi - TX_INCLUSION_DELAY, false));
check('inside the last TX_INCLUSION_DELAY-1 blocks it waits for the next epoch', skips(epochHi - TX_INCLUSION_DELAY + 1, false) && skips(epochHi, false));
check('a reveal too close to its window edge to propagate is deferred, as the node defers it',
  skips(revealHi - 1, true) && !skips(revealHi, true));

// ---- the build sites carry the window ---------------------------------------------------------------
const builds = [...js.matchAll(/buildTransferTx\(state\.wallet, "duty", 0n, 0, tb, data, nowSeconds\(\), !pubkeyEstablished\(acc\)(, minBlock)?\)/g)];
check('both duty build sites exist', builds.length === 2);
check('both duty build sites pass minBlock', builds.every(b => !!b[1]));
check('the exact-landing cliff (latest + 5) is gone', !/Math\.min\(latest \+ 5,/.test(js));
check('the builder writes min_block into the signed draft when given', /if \(minBlock\) draft\.min_block = minBlock;/.test(js));

// ---- THE COUPLING: the node still computes the same window ---------------------------------------
const py = readFileSync(join(ROOT, 'loops', 'core_loop.py'), 'utf8');
check('node: min_block = latest + TX_INCLUSION_DELAY', py.includes('min_block = latest["block_number"] + TX_INCLUSION_DELAY'));
check('node: epoch_hi = (X + 1) * EPOCH_LENGTH - 1', py.includes('epoch_hi = (X + 1) * EPOCH_LENGTH - 1'));
check('node: reveal_hi = (X + 1) * EPOCH_LENGTH - FINALITY_DEPTH - 1', py.includes('reveal_hi = (X + 1) * EPOCH_LENGTH - FINALITY_DEPTH - 1'));
check('node: caps to the reveal window only while it is open', /if _reveal_due and reveal_hi > latest\["block_number"\]:\s*\n\s*_hi = min\(epoch_hi, reveal_hi\)/.test(py));
const bo = readFileSync(join(ROOT, 'ops', 'block_ops.py'), 'utf8');
check('validation: a duty carrying min_block lands flexibly', /if r == "duty" and "min_block" in transaction:\s*\n\s*return True/.test(bo));

console.log(fails ? `\nFAILED: ${fails}` : '\nall checks passed');
process.exit(fails ? 1 : 0);

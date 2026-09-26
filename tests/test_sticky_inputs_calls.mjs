/* Every page calls stickyInputs(dapp, ids) — the SDK's signature (static/nadodapp.js).
 *
 * lend.js called stickyInputs(ids, key) with the arguments swapped from the day it was written (2026-08-02): the call
 * threw at boot, before any button was wired, so the lend page never did anything and nothing noticed until a headless
 * walk of every page (2026-09-26). Pins: the SDK still takes (dapp, ids), and every call in static/ passes a dapp
 * object first (`dapp` or `this.dapp`) and an array second.
 *
 * Run: node tests/test_sticky_inputs_calls.mjs
 */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const S = join(dirname(fileURLToPath(import.meta.url)), '..', 'static');
let fails = 0;
const check = (name, cond, d = '') => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (cond ? '' : '  ' + d)); if (!cond) fails++; };
check('the SDK signature is stickyInputs(dapp, ids)', /export function stickyInputs\(dapp, ids\)/.test(readFileSync(join(S, 'nadodapp.js'), 'utf8')));
const bad = [];
let n = 0;
for (const f of readdirSync(S).filter((x) => x.endsWith('.js'))) {
  const src = readFileSync(join(S, f), 'utf8');
  for (const m of src.matchAll(/\bstickyInputs\(([^\n]*)/g)) {
    if (/^dapp, ids\)/.test(m[1])) continue;                       // the definition
    n++;
    if (!/^\s*(this\.)?dapp\s*,\s*\[/.test(m[1])) bad.push(`${f}: stickyInputs(${m[1].slice(0, 60)}`);
  }
}
check(`every one of the ${n} calls passes the dapp first and an id array second`, n > 10 && bad.length === 0, bad.join(' | '));
console.log(fails ? `\nFAILED: ${fails}` : '\nall checks passed');
process.exit(fails ? 1 : 0);

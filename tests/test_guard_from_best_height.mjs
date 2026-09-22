/* A wallet's propagation guard starts from the highest tip it knows (static/interface.js guardFrom).
 *
 * h193750, 2026-09-22: a dividend-collect blob built 9 s before that block carried min_block 193748 — its
 * wallet's relay had just restarted and was serving a tip eight blocks behind the network. The guard was
 * already past everywhere else; five nodes rolled back a block. Pins: the guard uses the best of the relay's
 * tip, the pool's highest tip and the last tip the page saw; a later guard is accepted, an earlier one never;
 * every guarded build site goes through guardFrom; and the duty window follows the best tip too.
 *
 * Run: node tests/test_guard_from_best_height.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name); if (!cond) fails++; };
const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');
const D = Number((js.match(/^const TX_INCLUSION_DELAY = (\d+);/m) || [])[1]);
const lift = (n) => (js.match(new RegExp(`\\nfunction ${n}\\([^)]*\\) \\{[\\s\\S]*?\\}\\n`)) || [''])[0];
const src = lift('relayMaxHeight') + lift('guardFrom');
check('both functions lifted', src.includes('relayMaxHeight') && src.includes('guardFrom'));
const mk = (heights, latest) => new Function('relayPool', 'state', 'TX_INCLUSION_DELAY', src + '; return guardFrom;')({ list: heights.map(h => ({ height: h })) }, { latest }, D);

check('relay behind the pool: the guard starts from the pool\'s highest tip', mk([200, 208], 190)(200) === 208 + D);
check('relay at the front: the guard starts from the relay\'s tip', mk([200, 190], 190)(208) === 208 + D);
check('no pool, no page tip: the relay\'s tip alone', mk([], 0)(150) === 150 + D);
check('the page\'s last-seen tip counts when it is the highest', mk([100], 300)(100) === 300 + D);
check('a bad height is treated as zero, never as a guard', mk([], 0)(undefined) === D);

const guarded = (js.match(/guardFrom\(/g) || []).length;
const raw = js.split('\n').filter(l => /\+ TX_INCLUSION_DELAY\b/.test(l) && !/function guardFrom|const minBlock = latest \+ TX_INCLUSION_DELAY|TX_INCLUSION_DELAY \* 2|^\s*\*|^\s*\/\//.test(l));
check(`every guarded build site uses guardFrom (${guarded} calls; ${raw.length} raw sites left)`, guarded >= 14 && raw.length === 0);
if (raw.length) raw.forEach(l => console.log('   raw:', l.trim().slice(0, 100)));
check('the duty window is derived from the best tip, not one relay\'s', /const latest = Math\.max\(state\.latest, relayMaxHeight\(\)\);/.test(js));

console.log(fails ? `\nFAILED: ${fails}` : '\nall checks passed');
process.exit(fails ? 1 : 0);

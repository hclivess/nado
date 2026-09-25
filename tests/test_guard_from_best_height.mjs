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

// A pool restored from localStorage carries URLs, never heights: after the betanet-8 reroll a returning wallet restored
// betanet-7's ~233000 heights, and guardFrom (the pool MAX) set an unreachable min_block on every tx until a refresh.
const restore = (js.match(/\n  list: (\(\(\) => \{ try \{ const l = JSON\.parse\(localStorage\.getItem\(LS_RELAY_POOL\)[^\n]*\}\)\(\)),\n/) || [])[1];
check('the saved relay pool restore is found', !!restore);
if (restore) {
  const saved = JSON.stringify([{ url: 'https://a.example', height: 233042 }, { url: 'https://b.example', height: 233050 }]);
  const list = new Function('localStorage', 'LS_RELAY_POOL', 'return ' + restore)({ getItem: () => saved }, 'k');
  check('a restored pool keeps its urls', list.length === 2 && list[0].url === 'https://a.example');
  check('a restored pool carries no height from an earlier session', list.every(c => c.height === 0));
  check('so the guard starts from live tips only', mk(list.map(c => c.height), 0)(500) === 500 + D);
}

console.log(fails ? `\nFAILED: ${fails}` : '\nall checks passed');
process.exit(fails ? 1 : 0);

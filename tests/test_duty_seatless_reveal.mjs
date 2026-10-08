/* A wallet without a committee seat still reveals the RANDAO secret it committed while seated (static/interface.js
 * seatlessRevealData, the twin of the node's maybe_epoch_duty under protocol.REVEAL_SEATLESS_HEIGHT).
 *
 * Measured 2026-10-08: 28.9 % of commitments were never revealed, because the reveal for X+1 must land from a duty tx
 * in epoch X and that required a seat in X's resampled committee. The node and the wallet both stopped at "no seat".
 *
 * PINS: the decision is lifted from interface.js (never restated) and
 *   - reveals only when the wallet was seated in X-1 (that is when it committed for X+1);
 *   - carries ONLY a reveal section (an unseated attest or commit is refused by the node);
 *   - never once the reveal is known dead, and never outside the reveal window;
 *   - maybeRandao takes this path when it holds no seat, instead of returning.
 * Run: node tests/test_duty_seatless_reveal.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond, d = '') => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (cond ? '' : '   ' + d)); if (!cond) fails++; };
const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');

const lift = (name) => {
  const i = js.indexOf('function ' + name + '(');
  if (i < 0) return null;
  let depth = 0, j = js.indexOf('{', i);
  for (let k = j; k < js.length; k++) {
    if (js[k] === '{') depth++;
    else if (js[k] === '}' && --depth === 0) return js.slice(i, k + 1);
  }
  return null;
};
const EPOCH_LENGTH = 60, FINALITY_DEPTH = 45, TX_INCLUSION_DELAY = 8;
const src = lift('seatlessRevealData'), win = lift('dutyWindow');
check('seatlessRevealData and dutyWindow are defined in interface.js', !!src && !!win);
const seatlessRevealData = new Function(src + '; return seatlessRevealData;')();
const dutyWindow = new Function('EPOCH_LENGTH', 'FINALITY_DEPTH', 'TX_INCLUSION_DELAY', win + '; return dutyWindow;')(EPOCH_LENGTH, FINALITY_DEPTH, TX_INCLUSION_DELAY);
const secretFor = (e) => 'secret-' + e;

const X = 1000, early = X * EPOCH_LENGTH + 2;
const d = seatlessRevealData(X, true, true, dutyWindow(early, X, true), secretFor);
check('seated in X-1, early in X: a reveal for X+1 is built', d && d.reveal && d.reveal.target_epoch === X + 1 && d.reveal.secret === 'secret-' + (X + 1), JSON.stringify(d));
check('the seatless duty carries ONLY the reveal section', d && Object.keys(d).join() === 'reveal', d && Object.keys(d).join());
check('not seated in X-1 (no commitment of ours): nothing', seatlessRevealData(X, false, true, dutyWindow(early, X, true), secretFor) === null);
check('a reveal known dead: nothing', seatlessRevealData(X, true, false, dutyWindow(early, X, false), secretFor) === null);
const late = (X + 1) * EPOCH_LENGTH - FINALITY_DEPTH + 2;           // past the reveal window
check('past the reveal window: nothing', seatlessRevealData(X, true, true, dutyWindow(late, X, true), secretFor) === null);

const body = js.slice(js.indexOf('async function maybeRandao('), js.indexOf('async function maybeRandao(') + 6000);
check('maybeRandao no longer returns on "no seat" before trying the reveal',
  !/if \(!inCommittee\) return;/.test(body) && /if \(!inCommittee\) \{[\s\S]*seatlessRevealData\(/.test(body));
check('the seatless path asks whether it was seated in X-1', /duty_committee\?epoch=" \+ \(X - 1\)/.test(body));

console.log(fails ? `${fails} FAILED` : 'ALL PASSED');
process.exit(fails ? 1 : 0);

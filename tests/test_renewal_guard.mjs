/* The renewal re-broadcast guard + work-sized target margin (static/interface.js).
 * OBSERVED on betanet-3 the day POSW_TARGET_MARGIN went 30 -> 90: 552 stuck registers from 37 senders,
 * ~27 attempts each, every one rejected "sender already recerted this epoch". The first renewal LANDED;
 * the rest were the wallet re-broadcasting because acc.reg_epoch cannot move until the tx is mined, and
 * `register` lands EXACTLY at max_block so the in-flight window is the whole margin. */
import { readFileSync } from 'node:fs';
const js = readFileSync('/srv/nado-home/nado/static/interface.js', 'utf8');
let fails = 0;
const check = (n, c) => { console.log((c ? 'PASS  ' : 'FAIL  ') + n); if (!c) fails++; };

check('an in-flight renewal is tracked (_renewSubmitted)', /let _renewSubmitted = null;/.test(js));
check('...and blocks a re-broadcast until it lands or its target passes',
  /if \(_renewSubmitted\)[\s\S]{0,420}state\.latest <= _renewSubmitted\.targetBlock\) return;/.test(js));
check('...cleared when the chain\'s recert epoch moves past the broadcast epoch',
  /regEpoch > _renewSubmitted\.atEpoch/.test(js));
check('...and set only on an ACCEPTED submit',
  /result\)\s*\{[\s\S]{0,200}_renewSubmitted = \{ targetBlock: tb, atEpoch: regEpoch \}/.test(js));
check('the margin sizer exists', /function poswTargetMarginFor\(requiredT\)/.test(js));
check('both register paths use it', (js.match(/poswTargetMarginFor\(/g) || []).length >= 3);

// the sizer's actual numbers
const m = js.match(/function poswTargetMarginFor\(requiredT\) \{[\s\S]*?\n\}/)[0];
const fn = new Function('POSW_T', 'POSW_TARGET_MARGIN', 'poswRate',
  m.replace('function poswTargetMarginFor(requiredT)', 'return function(requiredT)'));
const sized = fn(1e6, 90, () => 3.2e6);
check(`a base renewal is far cheaper than the worst case (${sized(1e6)} blocks vs 90)`, sized(1e6) < 30);
check('...but never below a propagation floor', sized(1) >= 12);
const slow = fn(1e6, 90, () => 3e5);
check(`an expensive entry on a slow device still gets the full window (${slow(512e6)})`, slow(512e6) === 90);
check('the sizer never exceeds the protocol ceiling (the anchor must already exist)',
  [1e6, 96e6, 512e6, 1e12].every(t => slow(t) <= 90 && sized(t) <= 90));
console.log('\n' + (fails ? `${fails} FAILURE(S)` : 'ALL RENEWAL-GUARD CHECKS PASSED'));
process.exit(fails ? 1 : 0);

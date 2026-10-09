/* The Collecting card's ONE "Earning" figure (static/interface.js collectPerDay), on fixed inputs:
 *   blocks   = 86400 / block_time × k_open / epoch_length × my_open / total_open × avg reward × OPEN_TIP_BPS / 10000
 *   dividend = mean(inflow) × 86400 / (block_time × epoch_length) × my_weight / Σ weights
 *   savings  = 86400 / block_time × (epoch_length − k_open) / epoch_length × my_bonded / total_bonded × bonded cut
 * and the savings tile no longer shows a second per-day figure for the same money.
 * Lifted from the wallet source (never restated). Inputs are the live values of block 135625 and epoch 2100's inflow.
 * Run: node tests/test_collect_per_day.mjs */
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
  let depth = 0;
  for (let k = js.indexOf('{', i); k < js.length; k++) {
    if (js[k] === '{') depth++;
    else if (js[k] === '}' && --depth === 0) return js.slice(i, k + 1);
  }
  return null;
};
const src = lift('collectPerDay');
check('collectPerDay is defined in interface.js', !!src);
const collectPerDay = new Function(src + '; return collectPerDay;')();
const tipM = js.match(/const OPEN_TIP_BPS = (\d+);/);
check('OPEN_TIP_BPS is the protocol value (20 %)', tipM && +tipM[1] === 2000, tipM && tipM[1]);
const fmtM = js.match(/const fmtPerDay = (\(raw\) => \{[^\n]*\});/);
const fmtPerDay = fmtM ? eval(fmtM[1]) : null;
check('fmtPerDay is defined in interface.js', !!fmtPerDay);

const near = (a, b) => Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(b));
const base = { present: true, blockTime: 6, epochLength: 60, kOpen: 18, myOpenWeight: 10, totalOpenWeight: 236,
  avgRewardRaw: 1e10, tipBps: 2000, inflowsRaw: [5812380000], myWeight: 10, sumWeights: 236 };
const r = collectPerDay(base);
// blocks: 14400 blocks/day × 0.3 open × 10/236 × 1 NADO × 0.2 = 36.6101... NADO
const wantBlocks = 14400 * 0.3 * (10 / 236) * 1e10 * 0.2;
// dividend: 240 epochs/day × 0.581238 NADO × 10/236
const wantDiv = 5812380000 * 240 * (10 / 236);
check('blocks per day', near(r.blocks, wantBlocks), `${r.blocks} vs ${wantBlocks}`);
check('dividend per day', near(r.dividend, wantDiv), `${r.dividend} vs ${wantDiv}`);
check('total is the sum', near(r.total, wantBlocks + wantDiv));
check('formatted like renderDelegationLine (two decimals at or above 1 NADO)', fmtPerDay(r.blocks) === (wantBlocks / 1e10).toFixed(2), fmtPerDay(r.blocks));
check('four decimals below 1 NADO', fmtPerDay(4.2e9) === '0.4200', fmtPerDay(4.2e9));

const r2 = collectPerDay({ ...base, inflowsRaw: [4e9, 6e9, 5e9, 5e9] });
check('the dividend averages the inflows', near(r2.dividend, 5e9 * 240 * (10 / 236)));
const r3 = collectPerDay({ ...base, myWeight: 100, sumWeights: 2360 });
check('weights ×10 since block 107000 leave the ratio unchanged', near(r3.dividend, r.dividend));
check('not present and not producing: no estimate (the card shows —)', collectPerDay({ ...base, present: false }) === null);
check('a collector without stake has no savings part', r.savings === null);
const sv = { bondedProducing: true, myBondedShares: 59, totalBondedShares: 1199, bondedCutRaw: 97900000 };
const wantSave = 14400 * (42 / 60) * (59 / 1199) * 97900000;
const r4 = collectPerDay({ ...base, ...sv });
check('savings per day (each lane its own share, never the combined win time)', near(r4.savings, wantSave), `${r4.savings} vs ${wantSave}`);
check('the total adds all three parts', near(r4.total, wantBlocks + wantDiv + wantSave));
const r5 = collectPerDay({ ...base, present: false, ...sv });
check('a saver who is not present: savings only', r5 && r5.blocks === null && r5.dividend === null && near(r5.total, wantSave));
check('no open weight: zero block rewards, never NaN', collectPerDay({ ...base, totalOpenWeight: 0 }).blocks === 0);
check('no inflow data: zero dividend, never NaN', collectPerDay({ ...base, inflowsRaw: [] }).dividend === 0);

const html = readFileSync(join(ROOT, 'static', 'interface.html'), 'utf8');
check('the tile sits beside Expected time to collect', html.indexOf('id="minePerDay"') > html.indexOf('id="mineEta"')
  && /data-i18n-title="tip\.perDay"/.test(html));
check('it renders where #mineEta is rendered', /\$\("mineEta"\)\.textContent = [^\n]*\n\s*refreshCollectPerDay\(ms\)/.test(js));
check('it shows for a present or producing identity only', /if \(!ms \|\| \(!ms\.registered_present && !ms\.bonded_producing\) \|\| !addr\) \{ val\.textContent = "—"/.test(js));
const deleg = lift('renderDelegationLine');
check('the savings tile shows its stake, not a second per-day figure', deleg && !/\/day|perDayOf/.test(deleg) && /ovw\.producingStake/.test(deleg));
check('the tile is labelled Earning', /data-i18n="mine\.earn">Earning</.test(html));
console.log(fails ? `${fails} FAILED` : 'ALL PASSED');
process.exit(fails ? 1 : 0);

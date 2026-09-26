/* A shielded spend is confirmed by its outputs landing in the tree, and restored when they never do
 * (static/interface.js reconcileSpentNotes / _markSpendPending; zk audit 2026-09-26, browser F1).
 *
 * L1 admits a shielded blob without checking the proof and the exec node may refuse it later; the wallet used to mark
 * the note spent (and credit the change) the moment the blob reached the mempool, so a refused proof hid the note for
 * good. Pins: an output in the tree confirms the spend; inside the grace window nothing moves; after it, a spend with no
 * landed output restores the note and drops its phantom change; an unreachable tree changes nothing; and the rules
 * fetch never falls back to "all rules off".
 *
 * Run: node tests/test_shield_spend_reconcile.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');
let fails = 0;
const check = (name, cond) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name); if (!cond) fails++; };
const grab = (re) => (js.match(re) || [''])[0];
const src = grab(/const SPEND_LAND_GRACE_MS = [^\n]*\n/) + grab(/function _markSpendPending\([\s\S]*?\n\}\n/) +
            grab(/async function reconcileSpentNotes\(\)[\s\S]*?\n\}\n/);
check('the reconcile code is found', src.includes('reconcileSpentNotes') && src.includes('_markSpendPending'));

function harness(notes, leaves, now) {
  let saved = null; const logs = [];
  const env = {
    loadNotes: () => JSON.parse(JSON.stringify(notes)), saveNotes: (n) => { saved = n; },
    execJSON: async () => { if (leaves === null) throw new Error('down'); return { leaves }; },
    log: (lvl, m) => logs.push(m), i18: (k, d, v) => d.replace('{n}', v.n),
    Date: { now: () => now },
  };
  const f = new Function(...Object.keys(env), src + '; return { reconcileSpentNotes, _markSpendPending };')(...Object.values(env));
  return { f, get saved() { return saved; }, logs };
}

const GRACE = 20 * 60 * 1000;
const spentNote = (at) => ({ cm: 'in1', value: '100', spent: true, spentAt: at, spentOuts: ['out1', 'out2'] });
const change = { cm: 'out1', value: '40', spent: false };

let h = harness([spentNote(0), change], ['x', 'out1'], GRACE + 5);
await h.f.reconcileSpentNotes();
check('an output in the tree confirms the spend', h.saved && h.saved[0].spent === true && !h.saved[0].spentOuts && h.saved.length === 2);

h = harness([spentNote(1000), change], ['x'], 1000 + GRACE - 1);
await h.f.reconcileSpentNotes();
check('inside the grace window nothing moves', h.saved === null);

h = harness([spentNote(0), change], ['x'], GRACE + 1);
const r = await h.f.reconcileSpentNotes();
check('after the window an unlanded spend is restored', r === 1 && h.saved[0].spent === false && !h.saved[0].spentOuts);
check('... and its phantom change is dropped', h.saved.length === 1);
check('... and the user is told', h.logs.length === 1 && h.logs[0].startsWith('1 '));

h = harness([spentNote(0), change], null, GRACE + 1);
await h.f.reconcileSpentNotes();
check('an unreachable tree changes nothing', h.saved === null);

const n = {}; h.f._markSpendPending(n, { cm_out1: 'a', cm_out2: 'b' });
check('a spend records both output commitments', JSON.stringify(n.spentOuts) === '["a","b"]' && typeof n.spentAt === 'number');

const rules = grab(/async function _proofRulesNow\(\)[\s\S]*?\n\}\n/);
check('the rules fetch never falls back to all-off rules', !/bind: false, blockSelector: false/.test(rules) && /throw new Error/.test(rules));
check('both spend sites record their outputs', (js.match(/^\s+_markSpendPending\(note, pr\);/gm) || []).length === 2);

console.log(fails ? `\nFAILED: ${fails}` : '\nall checks passed');
process.exit(fails ? 1 : 0);

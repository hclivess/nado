/* A bet market's outcome labels are chosen by whoever creates the market, so they reach the page as data, never as
 * markup (audit 2026-09-25, HIGH: a resolved market whose winning label was `<img src=x onerror=…>` ran script on
 * bet.html, which shares its origin with a plaintext wallet key).
 *
 * statusText() returns PLAIN text (one sink uses textContent); every innerHTML sink that carries it must escape it.
 * The functions are lifted from static/bet.js and run, so this tests the shipped code.
 *
 * Run: node tests/test_bet_labels_escaped.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond, detail) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (cond || detail === undefined ? '' : '  ' + JSON.stringify(detail))); if (!cond) fails++; };
const js = readFileSync(join(ROOT, 'static', 'bet.js'), 'utf8');
function lift(start, end) {
  const i = js.indexOf(start); if (i < 0) throw new Error('not found: ' + start);
  const j = js.indexOf(end, i + start.length); if (j < 0) throw new Error('no end after: ' + start);
  return js.slice(i, j);
}
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const window = { t: (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : '{' + n + '}')) };
const SRC = [lift('const statusTag = ', '\nfunction statusText'), lift('function statusText(mk)', '\n}\n') + '\n}',
             lift('function marketCard(mk)', '\n}\n') + '\n}'].join('\n');
const f = new Function('window', 'esc', 'rawToNado', 'activeMarket', 'VOID_GRACE_SEC', 'fmtLeft',
                       SRC + '\nreturn { statusText, marketCard };');
const { statusText, marketCard } = f(window, esc, (x) => String(x), null, 0, (x) => String(x));

const EVIL = '<img src=x onerror="alert(document.cookie)">';
const mk = { id: 1, title: 'Final', resolved: true, winner: 0, labels: [EVIL, 'B'], status: 'resolved', myTotal: 0, outsHTML: '' };
check('statusText is plain text (it carries the label verbatim, for the textContent sink)', statusText(mk).includes(EVIL));
const card = marketCard(mk);
check('a market card never carries the label as markup', !card.includes('<img') && card.includes('&lt;img'), card);

// the my-bets list builds its row inline; its tag must be escaped the same way
check('the my-bets row escapes statusText', /let tag = esc\(statusText\(mk\)\);/.test(js));
// and no innerHTML-bound line in bet.js carries statusText unescaped
const bare = js.split('\n').filter((l) => /statusText\(mk\)/.test(l) && !/esc\(statusText\(mk\)\)/.test(l)
                                      && !/function statusText/.test(l) && !/textContent\s*=\s*statusText/.test(l));
check('every other statusText use is a textContent sink', bare.length === 0, bare);

console.log(fails ? `${fails} FAILURES` : 'ALL PASS — market labels reach the page as text, never as markup');
process.exit(fails ? 1 : 0);

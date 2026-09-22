/* An open wallet reloads itself, once, when its origin moves to a new build (static/interface.js noteBuild).
 *
 * Nothing reloaded a tab when the relay moved to a new commit, so a validator who left the wallet open kept
 * the old duty code for days after the fix shipped (2026-09-22). Pins: the first commit seen is the baseline
 * and never reloads; the same commit again does nothing; a new commit arms one reload and logs once; a
 * commit already seen in this browser session (the page just reloaded onto it, or the served file lags) never
 * re-arms — that is what prevents a reload loop; and the idle test refuses while a modal is open or a field
 * is focused.
 *
 * Run: node tests/test_wallet_reload_on_new_build.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name); if (!cond) fails++; };

const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');
const lift = (name) => { const m = js.match(new RegExp(`\\nfunction ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}`)); check(`${name} is defined`, !!m); return m ? m[0] : ''; };
const src = ['_seenBuilds', '_rememberBuild', 'noteBuild', 'walletIdle', 'reloadWhenIdle'].map(lift).join('\n');

function harness() {
  const store = new Map(); const logs = []; let reloads = 0;
  const env = {
    sessionStorage: { getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, v) },
    log: (lvl, msg) => logs.push(msg), i18: (k, d) => d,
    location: { reload: () => { reloads++; } },
    document: { activeElement: null },
    state: {},
    setTimeout: () => {},
  };
  // _modalEl and _randaoBusy are free identifiers inside the lifted code, so they live inside the
  // harness body with setters — a parameter would be copied at call time and later edits lost.
  const fn = new Function(...Object.keys(env), `let _bootCommit = null, _reloadArmed = false, _modalEl = null, _randaoBusy = false;\n${src}\nreturn { noteBuild, walletIdle, get armed() { return _reloadArmed; }, set modal(v) { _modalEl = v; }, set randaoBusy(v) { _randaoBusy = v; } };`);
  const api = fn(...Object.values(env));
  return { api, env, logs, reloads: () => reloads, store };
}

let h = harness();
check('the first commit seen is the baseline and does not reload', h.api.noteBuild('aaaa1111') === false && h.reloads() === 0);
check('the same commit again does nothing', h.api.noteBuild('aaaa1111') === false && h.reloads() === 0);
check('a new commit arms a reload, and the page (idle) reloads once', h.api.noteBuild('bbbb2222') === true && h.reloads() === 1);
check('it logs the notice exactly once', h.logs.length === 1);
check('a third commit while armed does not reload again', h.api.noteBuild('cccc3333') === false && h.reloads() === 1);

// after the reload: fresh module state, SAME session storage — the page now runs bbbb2222
const store = h.store; h = harness(); h.store.clear(); for (const [k, v] of store) h.store.set(k, v);
check('after reloading onto the new build, seeing it is the baseline again', h.api.noteBuild('bbbb2222') === false && h.reloads() === 0);
check('seeing the OLD commit again (a lagging served file) never re-arms — no reload loop', h.api.noteBuild('aaaa1111') === false && h.reloads() === 0);
check('but a genuinely newer build still does', h.api.noteBuild('dddd4444') === true && h.reloads() === 1);

// idle refuses while the user is mid-something
h = harness();
h.api.modal = { classList: { contains: () => false } };   // a modal is OPEN (not hidden)
check('not idle while a modal is open', h.api.walletIdle() === false);
h.api.modal = null; h.env.document.activeElement = { tagName: 'INPUT' };
check('not idle while a field is focused', h.api.walletIdle() === false);
h.env.document.activeElement = null; h.env.state.autoBondPending = { target: 1n };
check('not idle while an auto-bond is in flight', h.api.walletIdle() === false);
h.env.state.autoBondPending = null; h.api.randaoBusy = true;
check('not idle while a duty is being posted', h.api.walletIdle() === false);
h.api.randaoBusy = false;
check('idle otherwise', h.api.walletIdle() === true);

check('the check runs against the page\'s OWN origin, not whichever relay the wallet polls', /fetch\(location\.origin \+ "\/status"/.test(js));
check('the check is armed once a minute alongside the pollers', /state\._buildTimer = setInterval\(/.test(js));

console.log(fails ? `\nFAILED: ${fails}` : '\nall checks passed');
process.exit(fails ? 1 : 0);

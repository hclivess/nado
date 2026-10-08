/* Importing an existing wallet over the auto-created one (static/interface.js, static/interface.html).
 *
 * REPORTED (2026-10-08): the wallet creates a wallet for every newcomer on first visit, so a person who already owns
 * one arrives holding a second, and the only way to their own key was Settings -> Forget wallet — destroy the
 * auto-created wallet first, coins or not, before the old key was even typed in.
 *
 * THE FIX, and what this pins:
 *   1. the import entry is reachable WITHOUT Forget — a Settings button and a first-run link that open the same
 *      #importBox (moved into Settings) while the current wallet stays stored;
 *   2. a wallet that holds anything (or whose balance cannot be checked) is NOT replaced until its key file has been
 *      downloaded through the existing downloadKeyFile() AND the owner ticks that it is saved;
 *   3. an empty, never-used wallet is replaced after ONE confirm;
 *   4. the imported key becomes the active, stored wallet;
 *   5. every import path (paste, key file, encrypted file) passes the same guard before it overwrites LS_WALLET.
 * Real code is lifted from interface.js and run against stubs; no key goes anywhere (the stubs record every call).
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');
const html = readFileSync(join(ROOT, 'static', 'interface.html'), 'utf8');
let fails = 0;
const check = (n, c) => { console.log((c ? 'PASS  ' : 'FAIL  ') + n); if (!c) fails++; };

function lift(name) {
  const one = js.match(new RegExp('\\n((?:async )?function ' + name + '\\([^\\n]*\\})\\n'));   // a one-line function
  if (one) return one[1];
  const m = js.match(new RegExp('\\n((?:async )?function ' + name + '\\([\\s\\S]*?\\n\\})\\n'));
  if (!m) throw new Error('could not lift ' + name);
  return m[1];
}
const liftedHandler = (() => {
  const m = js.match(/\$\("btnImport"\)\.onclick = (async \(\) => \{[\s\S]*?\n  \});/);
  if (!m) throw new Error('could not lift the btnImport handler');
  return m[1];
})();
const SRC = ['masterSeedOf', 'hdCount', 'walletReplaceRisk', 'confirmReplaceWallet', 'clearToReplaceWith',
  'openImportExisting', 'persistWallet', 'adoptWallet'].map(lift).join('\n');

// A world: one stored wallet, a relay that answers per address, a scripted dialog, and spies on everything.
function world({ accounts = {}, relayThrows = false, htmlError = false, dialog = [], hd = 0, importValue = '' } = {}) {
  const ls = new Map();
  const calls = [];
  const els = {};
  const el = (id) => (els[id] = els[id] || { id, value: '', hidden: true, parentNode: null, textContent: '', classList: { add() {}, remove() {}, contains: () => false },
    appendChild(c) { c.parentNode = this; }, scrollIntoView() {}, focus() {} });
  el('importBox').parentNode = el('onboard');
  el('importMountSettings');
  el('importKey').value = importValue;
  const env = {
    state: { wallet: null, masterSeed: null },
    localStorage: { getItem: (k) => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, String(v)), removeItem: (k) => ls.delete(k) },
    LS_WALLET: 'nado_wallet', LS_AUTO_WALLET: 'nado_auto_wallet', LS_HD_COUNT: 'nado_hd_accounts',
    $: (id) => el(id),
    show: (id, v) => { el(id).hidden = !v; calls.push(['show', id, v]); },
    showTab: (t) => calls.push(['showTab', t]),
    i18: (k, fb, vars) => String(fb).replace(/\{(\w+)\}/g, (_, n) => (vars && n in vars ? vars[n] : '{' + n + '}')),
    accountKeypair: (master, i) => ({ address: 'addr(' + master + ',' + i + ')', privateKey: master + i }),
    keypairFromPriv: (p) => ({ address: 'addr(' + p + ',0)', privateKey: p }),
    looksLikeMnemonic: () => false, _hex: (x) => x, mnemonicToSeed: async (x) => x,
    rpcJSON: async (path) => {
      calls.push(['rpc', path]);
      if (relayThrows) throw new Error('relay down');
      const a = decodeURIComponent(path.split('address=')[1]);
      if (htmlError) return { ok: false, status: 404, data: '<html>not found</html>' };
      // the LIVE relay's shape: a never-touched address is HTTP 404 {"address": "Not found"} — ok is FALSE when empty
      return accounts[a] ? { ok: true, status: 200, data: accounts[a] } : { ok: false, status: 404, data: { address: 'Not found' } };
    },
    uiConfirm: async (spec) => { calls.push(['confirm', spec.title, spec.body]); const d = dialog.shift() || { ok: false }; env._check = !!d.check; return d.ok; },
    modalCheckValue: () => env._check,
    uiAlert: async (b) => calls.push(['alert', b]),
    downloadKeyFile: async () => calls.push(['downloadKeyFile']),
    markBackupSeen: () => calls.push(['markBackupSeen']),
    stopMining: () => calls.push(['stopMining']),
    log: () => {}, showWalletUI: () => calls.push(['showWalletUI']), walletAdopted: () => {}, refreshDashboard: async () => {},
    _check: false,
  };
  if (hd) ls.set('nado_hd_accounts', String(hd));
  const names = Object.keys(env).filter((k) => !k.startsWith('_'));
  const api = new Function(...names, 'env', `${SRC}\nconst btnImport = ${liftedHandler};\n` +
    'return { walletReplaceRisk, confirmReplaceWallet, clearToReplaceWith, openImportExisting, adoptWallet, btnImport };')(
    ...names.map((n) => env[n]), env);
  // the auto-created wallet already on this device
  const cur = { address: 'addr(AUTO,0)', privateKey: 'AUTO' };
  env.state.wallet = cur;
  ls.set('nado_wallet', JSON.stringify(cur));
  ls.set('nado_auto_wallet', '1');
  return { env, api, ls, calls, els, cur };
}
const idx = (calls, kind) => calls.findIndex((c) => c[0] === kind);
const count = (calls, kind) => calls.filter((c) => c[0] === kind).length;

// ---- 1. reachable without Forget --------------------------------------------------------------------------------
{
  const settings = html.slice(html.indexOf('id="settingsCard"'), html.indexOf('id="selftestCard"'));
  check('Settings carries an "Import an existing wallet" button', /id="btnImportExisting"[^>]*data-i18n="import\.existing"/.test(settings));
  check('…with a mount for the import fields beside it', settings.includes('id="importMountSettings"'));
  check('the button is wired to openImportExisting', /\$\("btnImportExisting"\)\.onclick = \(\) => openImportExisting\(\)/.test(js));
  check('the first-run note offers "I already have a wallet" wired to the same opener',
    /id="autoWalletImport"/.test(lift('renderAutoWalletNote')) && /autoWalletImport[\s\S]*?openImportExisting\(\)/.test(lift('renderAutoWalletNote')));
  const w = world();
  w.api.openImportExisting();
  check('opening import shows the import fields inside Settings', !w.els.importBox.hidden && w.els.importBox.parentNode === w.els.importMountSettings
    && w.calls.some((c) => c[0] === 'showTab' && c[1] === 'settings'));
  check('opening import forgets nothing — the current wallet stays stored and active',
    w.ls.get('nado_wallet') === JSON.stringify(w.cur) && w.env.state.wallet === w.cur && count(w.calls, 'stopMining') === 0);
  check('onboarding takes the import fields back if they were moved', /box\.parentNode !== ob\) ob\.appendChild\(box\)/.test(lift('enterOnboarding')));
}

// ---- 2. a funded wallet is not replaced without the backup step -------------------------------------------------
{
  const funded = { 'addr(AUTO,0)': { address: 'addr(AUTO,0)', balance: 5e10, bonded: 0, registered: 1 } };
  const next = { address: 'addr(MINE,0)', privateKey: 'MINE' };

  let w = world({ accounts: funded, dialog: [{ ok: false }] });
  let r = await w.api.clearToReplaceWith(next);
  check('funded: declining the backup step replaces nothing', r === false && count(w.calls, 'downloadKeyFile') === 0 && count(w.calls, 'stopMining') === 0
    && w.ls.get('nado_wallet') === JSON.stringify(w.cur));

  w = world({ accounts: funded, dialog: [{ ok: true }, { ok: true, check: false }] });
  r = await w.api.clearToReplaceWith(next);
  check('funded: confirming without ticking "saved" replaces nothing (and says so)', r === false && count(w.calls, 'downloadKeyFile') === 1 && count(w.calls, 'alert') === 1);

  w = world({ accounts: funded, dialog: [{ ok: true }, { ok: false, check: true }] });
  r = await w.api.clearToReplaceWith(next);
  check('funded: cancelling the final confirm replaces nothing', r === false);

  w = world({ accounts: funded, dialog: [{ ok: true }, { ok: true, check: true }] });
  r = await w.api.clearToReplaceWith(next);
  check('funded: backup downloaded, ticked and confirmed -> may replace', r === true);
  check('funded: the key file is downloaded BEFORE the final confirm, through downloadKeyFile',
    idx(w.calls, 'downloadKeyFile') > -1 && idx(w.calls, 'downloadKeyFile') < w.calls.map((c) => c[0]).lastIndexOf('confirm'));
  check('funded: two dialogs, the final one naming both addresses', count(w.calls, 'confirm') === 2
    && /addr\(AUTO,0\)/.test(w.calls.filter((c) => c[0] === 'confirm')[1][2]) && /addr\(MINE,0\)/.test(w.calls.filter((c) => c[0] === 'confirm')[1][2]));
  check('funded: the old wallet stops collecting before it is replaced', count(w.calls, 'stopMining') === 1);

  // a zero balance with a record is still history
  w = world({ accounts: { 'addr(AUTO,0)': { address: 'addr(AUTO,0)', balance: 0, bonded: 0, registered: 1 } }, dialog: [{ ok: false }] });
  check('an account record with zero balance counts as history (backup required)', (await w.api.walletReplaceRisk()) === 'funded');
  // coins on a DERIVED account of the same seed
  w = world({ hd: 2, accounts: { 'addr(AUTO,2)': { address: 'addr(AUTO,2)', balance: 1 } } });
  check('coins on a derived account (Account 3) count — every account of the seed is checked', (await w.api.walletReplaceRisk()) === 'funded');
  // an answer that is neither a record nor "Not found" (an old relay's HTML 404)
  w = world({ htmlError: true });
  check('an unrecognised relay answer is "could not check", never "empty"', (await w.api.walletReplaceRisk()) === 'unknown');
  w = world({});
  check('the live relay\'s 404 {"address":"Not found"} reads as empty (ok:false is not "exists")', (await w.api.walletReplaceRisk()) === 'empty');
  // relay down
  w = world({ relayThrows: true, dialog: [{ ok: false }] });
  check('a relay that cannot answer is treated as funded, never as empty', (await w.api.walletReplaceRisk()) === 'unknown'
    && (await w.api.clearToReplaceWith(next)) === false && count(w.calls, 'confirm') === 1);
}

// ---- 3. an empty wallet is replaced after one confirm -----------------------------------------------------------
{
  const next = { address: 'addr(MINE,0)', privateKey: 'MINE' };
  let w = world({ dialog: [{ ok: true }] });
  let r = await w.api.clearToReplaceWith(next);
  check('empty: one confirm, no backup step', r === true && count(w.calls, 'confirm') === 1 && count(w.calls, 'downloadKeyFile') === 0);
  w = world({ dialog: [{ ok: false }] });
  r = await w.api.clearToReplaceWith(next);
  check('empty: cancelling that one confirm keeps the wallet', r === false && w.ls.get('nado_wallet') === JSON.stringify(w.cur));
  w = world({});
  r = await w.api.clearToReplaceWith({ address: 'addr(AUTO,0)', privateKey: 'AUTO' });
  check('re-importing the wallet already here is not a replacement (no dialog)', r === true && count(w.calls, 'confirm') === 0);
  w = world({}); w.env.state.wallet = null;
  check('with no wallet loaded (onboarding / after Forget) import is unguarded as before', (await w.api.clearToReplaceWith(next)) === true);
}

// ---- 4. the imported key becomes the active wallet (the real btnImport handler) --------------------------------
{
  const w = world({ importValue: 'MINE', dialog: [{ ok: true }] });            // empty auto wallet: one confirm
  await w.api.btnImport();
  const stored = JSON.parse(w.ls.get('nado_wallet'));
  check('after import the new key is state.wallet', w.env.state.wallet && w.env.state.wallet.address === 'addr(MINE,0)');
  check('…and it is the stored wallet', stored.address === 'addr(MINE,0)');
  check('…the auto-created marker is gone', !w.ls.has('nado_auto_wallet'));
  check('…the pasted secret is cleared from the field and the fields hidden', w.els.importKey.value === '' && w.els.importBox.hidden);

  const w2 = world({ importValue: 'MINE', accounts: { 'addr(AUTO,0)': { address: 'addr(AUTO,0)', balance: 7 } }, dialog: [{ ok: false }] });
  await w2.api.btnImport();
  check('a funded auto wallet survives a declined import through the real handler',
    w2.env.state.wallet === w2.cur && JSON.parse(w2.ls.get('nado_wallet')).address === 'addr(AUTO,0)');
}

// ---- 5. every import path passes the guard before it writes -----------------------------------------------------
{
  const fileImp = lift('importKeyFile');
  check('key-file import guards before adoptWallet', /clearToReplaceWith\(kp\)[\s\S]*?adoptWallet\(kp/.test(fileImp));
  const encImp = lift('importEncryptedBlob');
  check('encrypted-file import guards before it overwrites LS_WALLET (and stays encrypted at rest)',
    /clearToReplaceWith\(w\)[\s\S]*?localStorage\.setItem\(LS_WALLET, JSON\.stringify\(blob\)\)/.test(encImp));
  check('paste import guards before adoptWallet', /clearToReplaceWith\(kp\)[\s\S]*?adoptWallet\(kp/.test(liftedHandler));
  check('the guard sends no key anywhere: its only network read is /get_account by address',
    !/privateKey|masterSeed\b|fetch\(/.test(lift('walletReplaceRisk').replace(/masterSeedOf\(\)/g, '')) && /get_account\?address=/.test(lift('walletReplaceRisk')));
}

console.log(fails ? `\n${fails} FAILED` : '\nall passed');
process.exit(fails ? 1 : 0);

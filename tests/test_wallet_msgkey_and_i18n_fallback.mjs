/* The wallet publishes its messaging key only when it can land, and an early label never shows a raw placeholder
 * (static/interface.js msgPublishPrekey, i18).
 *
 * 2026-09-25: a brand-new wallet submitted its kem_pub before the chain held its account (refused "Empty account") and
 * marked it published anyway, so once funded it stayed unreachable by DM for the session; and i18() returned its
 * English fallback without filling {placeholders} when i18n.js had not loaded, rendering "via {h}". Pins: no account ->
 * no submit; a refused submit is not recorded as published; an accepted one is; the fallback fills placeholders and
 * leaves unknown ones visible.
 *
 * Run: node tests/test_wallet_msgkey_and_i18n_fallback.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const js = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'static', 'interface.js'), 'utf8');
let fails = 0;
const check = (name, cond, d = '') => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (cond ? '' : '  ' + d)); if (!cond) fails++; };
const grab = (re) => (js.match(re) || [''])[0];

const i18src = grab(/function i18\(k, fb, vars\) \{[\s\S]*?\n\}\n/);
const i18 = new Function('window', i18src + '; return i18;')({});
check('the fallback fills placeholders before i18n.js loads', i18('relay.via', 'via {h}', { h: 'get.nadochain.com' }) === 'via get.nadochain.com');
check('... and leaves an unknown placeholder visible rather than blank', i18('x', 'a {q} b', {}) === 'a {q} b');
check('... and uses window.t once loaded', new Function('window', i18src + '; return i18;')({ t: () => 'T' })('k', 'fb') === 'T');

const pub = grab(/async function msgPublishPrekey\(\) \{[\s\S]*?\n\}\n/);
async function run(account, result) {
  let submitted = 0;
  const state = { wallet: { address: 'A' }, _msgPublished: null };
  const env = { msgIdentity: () => ({ kemPub: 'K' }), state, getAccount: async () => account, nextTargetBlock: async () => 5,
    submitTransaction: async () => { submitted++; return { data: { result } }; }, buildMsgkeyTx: () => ({}), nowSeconds: () => 1 };
  await new Function(...Object.keys(env), pub + '; return msgPublishPrekey;')(...Object.values(env))();
  return { submitted, published: state._msgPublished };
}
let r = await run(null, true);
check('no account on chain yet: nothing is submitted', r.submitted === 0 && r.published === null, JSON.stringify(r));
r = await run({ balance: 5 }, false);
check('a refused submit is not recorded as published (the next call retries)', r.submitted === 1 && r.published === null, JSON.stringify(r));
r = await run({ balance: 5 }, true);
check('an accepted submit is recorded', r.published === 'A', JSON.stringify(r));
r = await run({ balance: 5, kem_pub: 'K' }, true);
check('a key already on chain is not resubmitted', r.submitted === 0 && r.published === 'A', JSON.stringify(r));

check('the WASM Merkle (retired canonical-JSON packing) is not enabled by the wallet',
  !/setMerkleWasm\(|initMerkleWasm/.test(js));
console.log(fails ? `\nFAILED: ${fails}` : '\nall checks passed');
process.exit(fails ? 1 : 0);

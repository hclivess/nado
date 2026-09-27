/* One lying relay can neither break every transaction nor get itself adopted unchecked (audit 2026-09-25, HIGH).
 *
 * Pool heights reach the wallet SELF-REPORTED through /relays. The wallet used their MAX in three places: the
 * propagation guard (guardFrom) — so one relay claiming height 10^9 put every tx's min_block past its max_block and
 * nothing could land — the failover acceptance bar and the failover ranking. When home was unreachable a candidate
 * was adopted on its own word, and the TPM enrolment helper and its checksum were downloaded from whatever relay was
 * in use.
 *
 * Pins, on the real functions lifted from static/interface.js: the tip estimate is the max only up to
 * RELAY_LEAD_MAX above the median; guardFrom and failover acceptance use it; with home unreachable a candidate is
 * adopted only if another pool relay holds the same finalized block; and the helper download is always built
 * from the home relay.
 *
 * Run: node tests/test_relay_trust.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond, detail) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (cond || detail === undefined ? '' : '  ' + JSON.stringify(detail))); if (!cond) fails++; };
const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');
function lift(start, end) {
  const i = js.indexOf(start); if (i < 0) throw new Error('not found: ' + start);
  const j = js.indexOf(end, i + start.length); if (j < 0) throw new Error('no end after: ' + start);
  return js.slice(i, j);
}
const SRC = [
  lift('function relayMedianHeight()', '\nfunction relayMaxHeight'),
  lift('function relayMaxHeight()', '\n/* A PROPAGATION GUARD'),
  lift('function guardFrom(h)', '\n'),
  lift('function relayAcceptable(st)', '\nfunction adoptRelay'),
  lift('async function relayAgreesWithHome(url, candTip)', '\n// Live validation of the Send'),
].join('\n');

function harness({ pool, homeUp = true, hashes = {} }) {
  const logs = [];
  const env = {
    relayPool: { list: pool }, state: { latest: 0 }, TX_INCLUSION_DELAY: 2, RELAY_HEIGHT_TOLERANCE: 20,
    CHAIN_ID: 'c', netAdopted: true, homeRelay: () => 'https://home', relayHost: (u) => u,
    log: (lvl, m) => logs.push(m), i18: (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : '')),
    fetchWithTimeout: async (url) => {
      const base = url.split('/').slice(0, 3).join('/');
      if (url.endsWith('/status')) {
        if (base === 'https://home' && !homeUp) throw new Error('down');
        return { json: async () => ({ latest_block_height: 1000 }) };
      }
      if (base === 'https://home' && !homeUp) throw new Error('down');
      return { json: async () => ({ block_hash: hashes[base] || null }) };
    },
  };
  const names = Object.keys(env);
  const f = new Function(...names, SRC + '\nreturn { relayTipEstimate, guardFrom, relayAcceptable, relayAgreesWithHome };');
  return { api: f(...names.map((n) => env[n])), logs };
}

const honest = [{ url: 'https://a', height: 1000 }, { url: 'https://b', height: 1001 }, { url: 'https://c', height: 999 }];
const liar = { url: 'https://liar', height: 1e9 };

{
  const { api } = harness({ pool: [...honest, liar] });
  const est = api.relayTipEstimate();
  check('one relay claiming 10^9 cannot move the tip estimate past median + RELAY_LEAD_MAX', est >= 1000 && est <= 1031, est);
  check('...so the propagation guard stays a real, landable height', api.guardFrom(1000) <= 1031 + 2, api.guardFrom(1000));
  check('...and an honest relay at the real tip is still acceptable for failover',
        api.relayAcceptable({ chain_id: 'c', latest_block_height: 1000 }) === true);
}
{
  const { api } = harness({ pool: [{ url: 'https://a', height: 1000 }, { url: 'https://b', height: 1020 }, { url: 'https://c', height: 1010 }] });
  check('an honest relay a few blocks ahead still counts (estimate = the max when it is credible)', api.relayTipEstimate() === 1020);
}
{
  const { api, logs } = harness({ pool: [...honest, liar], homeUp: false,
                                  hashes: { 'https://liar': 'bad', 'https://a': 'good', 'https://b': 'good' } });
  const ok = await api.relayAgreesWithHome('https://liar', 1000);
  check('with home unreachable, a relay NO other relay corroborates is not adopted', ok === false, logs);
}
{
  const { api } = harness({ pool: [...honest], homeUp: false,
                            hashes: { 'https://a': 'good', 'https://b': 'good', 'https://c': 'good' } });
  check('...and one another relay agrees with IS adopted (failover still works)', (await api.relayAgreesWithHome('https://a', 1000)) === true);
}
{
  const { api } = harness({ pool: [{ url: 'https://a', height: 1000 }], homeUp: false, hashes: { 'https://a': 'good' } });
  check('...and with no other relay to ask it is used as before (liveness)', (await api.relayAgreesWithHome('https://a', 1000)) === true);
}
check('the enrolment helper and its checksum are never built from relayBase()',
      !/relayBase\(\) \+ "\/(download_enrol|static\/nado-tpm-enrol)/.test(js) && /function enrolBase\(\) \{ return homeRelay\(\); \}/.test(js));

// ...and the node does not hand wallets a peer's absurd claim in the first place (nado.py /relays)
const py = readFileSync(join(ROOT, 'nado.py'), 'utf8');
check('/relays clamps a peer\'s reported height to our tip + _RELAYS_LEAD_MAX',
      /_h = min\(_h, own_h \+ _RELAYS_LEAD_MAX\)/.test(py) && /"height": _h, "finalized"/.test(py)
      && Number((py.match(/^_RELAYS_LEAD_MAX = (\d+)/m) || [])[1]) === Number((js.match(/^const RELAY_LEAD_MAX = (\d+);/m) || [])[1]));

console.log(fails ? `${fails} FAILURES` : 'ALL PASS — a lying relay cannot break transactions or get itself adopted unchecked');
process.exit(fails ? 1 : 0);

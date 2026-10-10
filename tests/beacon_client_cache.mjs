// Driven by tests/test_exec_beacon_reaches_the_game_client.py: feeds the REAL /exec/beacon reply (argv[2]) through the
// shipped client code — NadoDapp.prototype.beacons / bc and BankedGame.prototype.prefetchBeacons — and prints one JSON
// line of what they did. Not run on its own (its name is not tests/test_*).
const _el = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => "" : _el, apply: () => _el });
for (const k of ["document", "window", "localStorage", "sessionStorage", "history"]) if (!(k in globalThis)) globalThis[k] = _el;
globalThis.location = { origin: "https://example.test/" };
const reply = JSON.parse(process.argv[2]);
const urls = [];
globalThis.fetch = async (url) => { urls.push(String(url)); return { json: async () => reply }; };

// static/ modules import the relay's /protocol.js (protocol.CLIENT_EXPORTS); tests/protocol_hook.mjs serves it
// rendered from protocol.py, and the static/ modules are loaded AFTER it (dynamic import) so they resolve through it.
import "./protocol_hook.mjs";
const { NadoDapp, chainResultAlg, EPOCH_LENGTH } = await import("../static/nadodapp.js");
const { BankedGame } = await import("../static/bankedgame.js");

const fake = { ns: "default", _bc: {} };
await NadoDapp.prototype.beacons.call(fake, [5, 6, 0, 5, 7]);
const firstUrls = urls.slice();
await NadoDapp.prototype.beacons.call(fake, [5]);              // cached: no second request
const bc5 = NadoDapp.prototype.bc.call(fake, 5);

// prefetchBeacons asks only for live seats of the active table whose beacon epoch has begun
const asked = [];
const bg = { active: 1, dapp: { cursor: 6 * EPOCH_LENGTH + 3, beacons: async (es) => { asked.push(...es); } } };
const sto = { gg: { 10: 1, 11: 1, 12: 2, 13: 1, 14: 1 }, gd: { 13: 1 }, gb: { 10: 5, 11: 7, 12: 5, 13: 6, 14: 6 } };
await BankedGame.prototype.prefetchBeacons.call(bg, sto);

console.log(JSON.stringify({
  urls: firstUrls, afterCache: urls.length, bc5, bc6: fake._bc[6] ?? null, bc7: fake._bc[7] ?? null,
  roll: chainResultAlg(bc5, "0", 10, 100), asked: asked.sort((a, b) => a - b),
}));
process.exit(0);                                                 // the SDK's own timers would keep node alive

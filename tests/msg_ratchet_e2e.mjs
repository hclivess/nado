/* _msg_ratchet_e2e.mjs — LIVE end-to-end of the KEM Double Ratchet through the running node's message pool.
 * Two REAL registered accounts (A = this node's keys.dat, B = private/_msg_e2e_b.json) exchange v2 envelopes via
 * POST /message → GET /tags → GET /message exactly as the wallet does; a third identity C scans the same tags and
 * must see nothing. Keys are read from disk and never printed. Run: node _msg_ratchet_e2e.mjs [step]
 *   step "keys"  → print both ML-KEM pubkeys (for the msgkey on-chain publish)   step "run" → the exchange */
import fs from 'node:fs';
const M = await import('./static/messaging.js');
const NODE = 'http://127.0.0.1:9173';
const kdA = JSON.parse(fs.readFileSync('/root/nado/private/keys.dat')), kdB = JSON.parse(fs.readFileSync('private/_msg_e2e_b.json'));
// addresses are RE-DERIVED from the pubkey (ops.key_ops.load_keys does the same: a key file may carry a stale prefix)
const { blake2b, bytesToHex } = await import('./static/vendor/nado-crypto.js');
const addrOf = (pubHex) => { const body = pubHex.slice(0, 42); return body + bytesToHex(blake2b(new TextEncoder().encode(JSON.stringify(body)), { dkLen: 2 })); };
const A = { addr: addrOf(kdA.public_key), id: M.identity(kdA.private_key) }, B = { addr: addrOf(kdB.public_key), id: M.identity(kdB.private_key) };
const C = { addr: 'c'.repeat(46), id: M.identity('44'.repeat(32)) };
if (process.argv[2] === 'keys') { console.log(JSON.stringify({ [A.addr]: A.id.kemPub, [B.addr]: B.id.kemPub })); process.exit(0); }

const j = async (p, opt) => (await fetch(NODE + p, opt)).json();
const now = () => Math.floor(Date.now() / 1000);
let fails = 0; const ok = (c, m) => { if (!c) fails++; console.log((c ? 'PASS  ' : 'FAIL  ') + m); };
const kemOf = async (addr) => (await j('/msg_key?address=' + addr)).kem_pub;
const cursor0 = (await j('/tags?since=0')).tags.reduce((m, t) => Math.max(m, t.seq), 0);
const post = async (env) => j('/message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(env) });
// poll exactly like msgPoll: scan tags since a cursor, fetch each envelope, try to open against OUR sessions
async function inbox(who, store, since) {
  const tags = (await j('/tags?since=' + since)).tags || [], got = [];
  for (const t of tags) {
    const env = (await j('/message?id=' + t.id)).message; if (!env) continue;
    const r = env.v === 2 ? M.ratchetOpen(who.id, store, env, now()) : null;
    if (r) got.push({ body: r.pt.body, from: r.peer, id: t.id, size: JSON.stringify(env).length });
  }
  return got;
}
const kemA = await kemOf(A.addr), kemB = await kemOf(B.addr);
ok(kemA === A.id.kemPub && kemB === B.id.kemPub, 'both identities resolve their ML-KEM key from the chain (/msg_key)');
const SA = M.sessionsNew(), SB = M.sessionsNew(), SC = M.sessionsNew();

const e1 = M.ratchetSeal(A.id, A.addr, SA, B.addr, kemB, { type: 'msg', from: A.addr, body: 'ratchet hello', ts: now() }, now());
let r = await post(e1); ok(r.result === true, 'node ADMITS a v2 session-init envelope (sig + pow + registered gate): ' + JSON.stringify(r));
let inB = await inbox(B, SB, cursor0);
ok(inB.length === 1 && inB[0].body === 'ratchet hello' && inB[0].from === A.addr, 'B fetches via /tags + /message and opens the session-init');
ok((await inbox(C, SC, cursor0)).length === 0, 'an unrelated identity scanning the same tags sees nothing');

const e2 = M.ratchetSeal(B.id, B.addr, SB, A.addr, kemA, { type: 'msg', from: B.addr, body: 'reply from B', ts: now() }, now());
r = await post(e2); ok(r.result === true, 'node admits B\'s reply (new chain, fresh ratchet key): ' + JSON.stringify(r));
let inA = await inbox(A, SA, cursor0);
ok(inA.length === 1 && inA[0].body === 'reply from B', 'A opens B\'s reply and ratchets forward');

const e3 = M.ratchetSeal(A.id, A.addr, SA, B.addr, kemB, { type: 'msg', from: A.addr, body: 'third (healed chain)', ts: now() }, now());
ok(M.parseHdr(e3.hdr).i === null && M.parseHdr(e3.hdr).k !== M.parseHdr(e1.hdr).k, 'A\'s third message drops the init ct and uses a fresh ratchet key');
r = await post(e3); ok(r.result === true, 'node admits the steady-state envelope');
const cur2 = (await j('/tags?since=0')).tags.reduce((m, t) => Math.max(m, t.seq), 0);
const ack = M.ratchetSeal(B.id, B.addr, SB, A.addr, kemA, { type: 'ack', from: B.addr, ackId: 'x', ts: now() }, now());
r = await post(ack); ok(r.result === true, 'an ack rides the same session');
inB = await inbox(B, SB, cursor0);
ok(inB.some(x => x.body === 'third (healed chain)'), 'B opens the third message (previous ones are burned: ' + inB.length + ' opened of 3)');
ok(inB.length === 1, 'replayed envelopes from the pool are NOT re-decryptable (forward secrecy holds on the wire)');
const bigBody = 'z'.repeat(M.MSG_BODY_MAX);
const e4 = M.ratchetSeal(A.id, A.addr, SA, B.addr, kemB, { type: 'msg', from: A.addr, body: bigBody, ts: now() }, now());
r = await post(e4); ok(r.result === true, 'a MSG_BODY_MAX-char body is under the node\'s 16 KiB cap (' + JSON.stringify(e4).length + ' B json)');
ok((await inbox(B, SB, cur2)).some(x => x.body === bigBody), 'B opens it');
const all = await j('/tags?since=' + cursor0);
const ours = [e1, e2, e3, ack, e4].map(M.messageId);
ok(new Set(all.tags.filter(t => ours.includes(t.id)).map(t => t.tag)).size === 5, 'the node stored 5 distinct, unlinkable tags');
console.log(fails ? `\n${fails} FAILED` : '\nALL PASS'); process.exit(fails ? 1 : 0);

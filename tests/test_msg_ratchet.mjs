/* KEM Double Ratchet (static/messaging.js v2) — behavioural test against the REAL crypto, under Node.
 *
 * Pins the security properties doc/messaging.md §3 promises, not just "it round-trips":
 *   forward secrecy      — a session snapshot taken AFTER a message cannot decrypt that message
 *   post-compromise sec. — a full snapshot of Alice stops decrypting once Alice has replied on a fresh chain
 *   recipient hiding     — a third party gets null; tags are unlinkable across a conversation
 *   robustness           — out-of-order, dropped, duplicated, crossed first messages, lost first message,
 *                          header tampering, persistence round-trip, v1 legacy receive
 * Run: node tests/test_msg_ratchet.mjs
 */
const M = await import('../static/messaging.js');
const alice = M.identity("11".repeat(32)), bob = M.identity("22".repeat(32)), mal = M.identity("33".repeat(32));
const A = "a".repeat(46), B = "b".repeat(46);
let ts = 1_700_000_000, fails = 0;
const ok = (c, m) => { if (!c) { fails++; console.log("FAIL  " + m); } else console.log("PASS  " + m); };
const clone = (x) => JSON.parse(JSON.stringify(x));
const send = (id, addr, store, peer, peerId, body) => M.ratchetSeal(id, addr, store, peer, peerId.kemPub, { type: "msg", from: addr, body, ts }, ts++);
const recv = (id, store, env) => { const r = M.ratchetOpen(id, store, env, ts++); return r ? r.pt.body : null; };

// ---- basic session + bidirectional ratcheting ----
let SA = M.sessionsNew(), SB = M.sessionsNew();
const e1 = send(alice, A, SA, B, bob, "hi bob");
ok(e1.v === 2 && M.parseHdr(e1.hdr).i !== null, "first message is v2 and carries the session-init ciphertext");
ok(recv(bob, SB, e1) === "hi bob", "bob opens the session-init message");
ok(recv(mal, M.sessionsNew(), e1) === null, "a third party cannot open it (nor detect it as theirs)");
const e2 = send(alice, A, SA, B, bob, "second, same chain");
ok(M.parseHdr(e2.hdr).i !== null, "init ciphertext keeps riding along until bob has replied");
ok(recv(bob, SB, e2) === "second, same chain", "second message of the chain");
const r1 = send(bob, B, SB, A, alice, "hi alice");
ok(M.parseHdr(r1.hdr).i === null && M.parseHdr(r1.hdr).k !== M.parseHdr(e1.hdr).k, "bob's reply starts a new chain with a fresh ratchet key");
ok(recv(alice, SA, r1) === "hi alice", "alice ratchets forward on bob's reply");
const e3 = send(alice, A, SA, B, bob, "third");
ok(M.parseHdr(e3.hdr).i === null, "after a reply the init ciphertext is dropped");
ok(M.parseHdr(e3.hdr).k !== M.parseHdr(e2.hdr).k, "alice's next send uses a fresh ratchet key too");
ok(recv(bob, SB, e3) === "third", "bob follows alice's new chain");
ok(e1.tag !== e2.tag && e2.tag !== e3.tag, "detection tags differ per message (node cannot link a conversation)");

// ---- forward secrecy ----
const snapB = clone(SB);                     // stolen AFTER e3 was read
ok(recv(bob, snapB, e3) === null, "forward secrecy: a post-read snapshot cannot re-decrypt e3 (key burned)");
ok(recv(bob, snapB, e1) === null, "forward secrecy: nor the session-init message");

// ---- out-of-order / dropped / duplicate ----
const o1 = send(alice, A, SA, B, bob, "o1"), o2 = send(alice, A, SA, B, bob, "o2"), o3 = send(alice, A, SA, B, bob, "o3");
ok(recv(bob, SB, o3) === "o3", "late chain: o3 arrives first");
ok(recv(bob, SB, o1) === "o1", "o1 arrives late — skipped key cached");
ok(recv(bob, SB, o1) === null, "a replayed o1 is rejected (its key was burned)");
const rb = send(bob, B, SB, A, alice, "reply after gap");
ok(recv(alice, SA, rb) === "reply after gap", "bob replies (new chain) while o2 is still in flight");
ok(recv(bob, SB, o2) === "o2", "o2 from the PREVIOUS chain still opens after the ratchet step");
const gap = []; for (let i = 0; i < M.MAX_SKIP + 2; i++) gap.push(send(alice, A, SA, B, bob, "g" + i));
ok(recv(bob, SB, gap[gap.length - 1]) === null, "a gap beyond MAX_SKIP is refused (DoS bound) without corrupting state");
ok(recv(bob, SB, gap[0]) === "g0" && recv(bob, SB, gap[1]) === "g1", "…and the chain still works in order");

// ---- post-compromise security ----
const leak = clone(SA);                      // attacker has ALL of alice's state now
const pre = send(bob, B, SB, A, alice, "bob to alice before heal");
ok(recv(alice, clone(leak), pre) === "bob to alice before heal", "leaked state follows bob's next chain (expected: alice has not healed yet)");
ok(recv(alice, SA, pre) === "bob to alice before heal", "alice reads it");
const heal = send(alice, A, SA, B, bob, "alice replies (fresh chain)");
ok(recv(bob, SB, heal) === "alice replies (fresh chain)", "bob reads alice's healing message");
const post = send(bob, B, SB, A, alice, "bob to alice after heal");
ok(recv(alice, SA, post) === "bob to alice after heal", "alice reads post-heal");
const leak2 = clone(leak); recv(alice, leak2, pre);
ok(recv(alice, leak2, post) === null, "post-compromise security: the leaked state cannot read messages after alice's fresh chain");

// ---- crossed first messages (both initiate before hearing the other) ----
let XA = M.sessionsNew(), XB = M.sessionsNew();
const xa = send(alice, A, XA, B, bob, "a first"), xb = send(bob, B, XB, A, alice, "b first");
ok(recv(bob, XB, xa) === "a first" && recv(alice, XA, xb) === "b first", "crossed inits both open");
ok(recv(bob, XB, send(alice, A, XA, B, bob, "a again")) === "a again", "and the conversation continues (alice→bob)");
ok(recv(alice, XA, send(bob, B, XB, A, alice, "b again")) === "b again", "(bob→alice)");

// ---- lost first message: init rides along, so the 2nd message still builds the session ----
let LA = M.sessionsNew(), LB = M.sessionsNew();
send(alice, A, LA, B, bob, "lost"); const l2 = send(alice, A, LA, B, bob, "arrives");
ok(recv(bob, LB, l2) === "arrives", "session forms from the 2nd message when the 1st was lost (n=1 skipped)");

// ---- bob lost his storage AFTER replying (init no longer rides along): stranded until alice re-inits ----
ok(recv(alice, LA, send(bob, B, LB, A, alice, "bob replied")) === "bob replied", "bob replies, so alice drops the init ciphertext");
let LB2 = M.sessionsNew();
ok(recv(bob, LB2, send(alice, A, LA, B, bob, "to wiped bob")) === null, "a wiped receiver cannot read a mid-session message (documented limit)");
M.sessionsForget(LA, B);
ok(recv(bob, LB2, send(alice, A, LA, B, bob, "after reset")) === "after reset", "sessionsForget → next send re-initialises and is readable");

// ---- tampering ----
const t = send(alice, A, SA, B, bob, "tamper me"); const tb = clone(t);
tb.hdr = t.hdr.slice(0, 20) + (t.hdr[20] === "A" ? "B" : "A") + t.hdr.slice(21);   // flip a byte inside pn/n/k
ok(recv(bob, clone(SB), tb) === null, "a bit-flipped header fails the AEAD (header is associated data)");
ok(recv(bob, SB, t) === "tamper me", "the untouched original still opens (state was not corrupted by the bad copy)");

// ---- persistence: store survives JSON round-trip (it is what the wallet writes to localStorage) ----
const SB2 = JSON.parse(JSON.stringify(SB));
ok(recv(bob, SB2, send(alice, A, SA, B, bob, "persisted")) === "persisted", "a JSON-serialised session keeps working");

// ---- v1 legacy envelopes are still received; v2 store ignores them ----
const v1 = M.makeEnvelope(alice, A, bob.kemPub, { type: "msg", from: A, body: "legacy", ts }, ts);
ok(M.ratchetOpen(bob, SB, v1, ts) === null && M.tryOpen(bob, v1).body === "legacy", "v1 envelope: ratchetOpen null, tryOpen opens");
ok(M.tryOpen(bob, e1) === null, "tryOpen refuses a v2 envelope cleanly");

// ---- size: stays under the node's 16 KiB envelope cap with a chat-sized body ----
const big = send(alice, A, M.sessionsNew(), B, bob, "x".repeat(M.MSG_BODY_MAX));
ok(JSON.stringify(big).length < 16 * 1024, "session-init envelope with a MSG_BODY_MAX ASCII body is under 16 KiB (" + JSON.stringify(big).length + " B)");
const SZ = M.sessionsNew(); send(alice, A, SZ, B, bob, "warm");
const nsBefore = SZ.peers[B][0].ns; let threw = null;
try { send(alice, A, SZ, B, bob, "\u00e9".repeat(M.MSG_BODY_MAX)); } catch (e) { threw = e.message; }
ok(threw && threw.startsWith("message too long") && SZ.peers[B][0].ns === nsBefore, "an oversized (multibyte) body is refused up-front without burning a chain key");
const SZB = M.sessionsNew(); recv(bob, SZB, send(alice, A, SZ, B, bob, "warm2")); recv(alice, SZ, send(bob, B, SZB, A, alice, "ack"));
const steady = send(alice, A, SZ, B, bob, "y".repeat(M.bodyBudgetBytes(false) - 120));   // init dropped → bigger budget
ok(JSON.stringify(steady).length < 16 * 1024, "a body at the steady-state budget is under 16 KiB (" + JSON.stringify(steady).length + " B)");

console.log(fails ? `\n${fails} FAILED` : "\nALL PASS"); process.exit(fails ? 1 : 0);

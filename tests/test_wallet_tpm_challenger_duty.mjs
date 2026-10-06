/* The wallet's TPM challenger duty keeps the node's safety rules (static/interface.js maybeTpmChallenge, the twin of
 * loops/core_loop.py maybe_tpm_challenge).
 *
 * A bonded wallet drawn as a challenger for a stranger's TPM enrolment seals a secret to that chip, publishes the
 * credential, and reveals (secret, seed) once the client's commitment is on chain. Each rule below has a failure
 * that kills the stranger's enrolment through no fault of their chip:
 *   - the secret is STORED (and read back) before the challenge is broadcast — a published blob whose secret was
 *     lost can never be revealed, by anyone;
 *   - an existing secret for an id is never replaced — the blob on chain may already be sealed under it;
 *   - a reveal goes out only when the relay says "reveal" (it does once the commit is on chain);
 *   - one message per enrolment per pass, never a second while one is in flight for that id;
 *   - a permanent refusal is not resent, a missing secret is reported once, not once per poll;
 *   - stored secrets are pruned only once spent or older than any enrolment can live.
 *
 * The function is LIFTED from interface.js and run against stubs, not restated — a copy here would keep passing
 * after the real one was edited. The credential maths itself is pinned against the Python by
 * tests/test_tpm_cred_js_matches_python.py; here the real tpmcred.js is used so the blob can be checked to be
 * the one the stored secret seals.
 * Run: node tests/test_wallet_tpm_challenger_duty.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { webcrypto } from "node:crypto";
import * as tpmcred from "../static/tpmcred.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const check = (name, cond, detail = "") => { console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : ": " + detail)); if (!cond) fails++; };

const js = readFileSync(join(ROOT, "static", "interface.js"), "utf8");
const start = js.indexOf("const TPM_SECRET_KEEP_BLOCKS");
const end = js.indexOf("/* ---- Payment-request deep links");
check("the duty block is found in interface.js", start > 0 && end > start);
const body = js.slice(start, end);

// ---- a real EK (RSA-2048 SPKI) for the stubs: the duty must seal to it without throwing --------------------------
const kp = await webcrypto.subtle.generateKey({ name: "RSA-OAEP", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["encrypt", "decrypt"]);
const EKPUB = tpmcred.bytesToHex(new Uint8Array(await webcrypto.subtle.exportKey("spki", kp.publicKey)));
const NAME = "000b" + "11".repeat(32);
const ID1 = "a".repeat(32), ID2 = "b".repeat(32);
const ADDR = "ndo" + "c".repeat(46);

function harness(opts = {}) {
  const events = [];
  const lsData = new Map(opts.ls || []);
  const env = {
    events,
    lsData,
    CHAIN_ID: "betanet-9",
    netAdopted: true,
    B_MIN_RAW: 100_000_000_000n,
    state: { wallet: { address: ADDR, publicKey: "pk", privateKey: "sk" }, locked: false, latest: 1000 },
    localStorage: {
      getItem: (k) => { const v = lsData.has(k) ? lsData.get(k) : null; if (opts.onGet) opts.onGet(k, lsData); return v; },
      setItem: (k, v) => { if (opts.lsThrows) throw new Error("QuotaExceededError"); events.push(["store", k, v]); lsData.set(k, v); },
    },
    crypto: webcrypto,
    navigator: opts.navigator || {},                 // no Web Locks unless a test provides them
    getAccount: async () => ({ bonded: opts.bonded ?? 200_000_000_000n, public_key: "pk" }),
    relayBase: () => "http://relay",
    fetch: async (url) => {
      events.push(["fetch", url]);
      const r = opts.duty();
      return { ok: true, json: async () => r };
    },
    refreshNetIdentity: async () => "betanet-9",
    pubkeyEstablished: (a) => !!(a && a.public_key),
    nowSeconds: () => 1,
    buildTransferTx: (wallet, recipient, amount, fee, maxBlock, data, ts, inclPk, minBlock) =>
      ({ txid: "t" + events.length, recipient, amount, fee, max_block: maxBlock, min_block: minBlock, data, sender: wallet.address }),
    submitTransaction: async (tx) => { events.push(["submit", tx]); return { data: (opts.submit || (() => ({ result: true })))(tx) }; },
    isTransient: () => false,
    setConn: () => {},
    log: (kind, msg) => events.push(["log", kind, msg]),
    i18: (k, fb, vars) => String(fb).replace(/\{(\w+)\}/g, (m, n) => (vars && vars[n] != null ? String(vars[n]) : m)),
    tpmMakeCredential: tpmcred.makeCredential,
    tpmHex: tpmcred.hexToBytes,
    tpmToHex: tpmcred.bytesToHex,
  };
  // `with` lets the lifted source resolve its free names against the stubs, exactly as module scope would.
  const make = new Function("env", `with (env) { ${body}\n return { maybeTpmChallenge, DEAD_TPM_RE, tpmSecretsKey, TPM_SECRET_KEEP_BLOCKS }; }`);
  return { env, events, lsData, ...make(env) };
}
const submits = (ev) => ev.filter((e) => e[0] === "submit").map((e) => e[1]);
const storeOf = (h) => JSON.parse(h.lsData.get(h.tpmSecretsKey(ADDR)) || "{}");
const chal = (id, extra = {}) => ({ id, action: "challenge", ekpub: EKPUB, name: NAME, min_block: 1008, max_block: 1300, ...extra });
const reveal = (id, extra = {}) => ({ id, action: "reveal", ekpub: EKPUB, name: NAME, min_block: 1008, max_block: 1300, ...extra });

// ---- 1. challenge: the secret is stored BEFORE the broadcast, and the blob is sealed under THAT secret --------------
{
  let tip = 1000;
  const h = harness({ duty: () => ({ tip, duties: [chal(ID1)] }) });
  await h.maybeTpmChallenge();
  const ev = h.events;
  const iStore = ev.findIndex((e) => e[0] === "store");
  const iSubmit = ev.findIndex((e) => e[0] === "submit");
  check("a challenge is broadcast", iSubmit >= 0);
  check("THE SECRET IS STORED BEFORE THE CHALLENGE IS BROADCAST", iStore >= 0 && iStore < iSubmit, JSON.stringify(ev.map((e) => e[0])));
  const tx = submits(ev)[0];
  const ent = storeOf(h)[ID1];
  check("the stored entry holds a 32-byte secret and seed", ent && /^[0-9a-f]{64}$/.test(ent.secret) && /^[0-9a-f]{64}$/.test(ent.seed));
  check("the message is tpm_challenge {id, blob, enc}, zero amount and fee, the relay's window",
    tx && tx.recipient === "tpm_challenge" && tx.amount === 0n && tx.fee === 0 && tx.max_block === 1300 && tx.min_block === 1008
    && Object.keys(tx.data).sort().join() === "blob,enc,id" && tx.data.id === ID1);
  check("the published blob is the one the STORED secret and seed seal",
    tx && ent && tx.data.blob === tpmcred.bytesToHex(tpmcred.credentialBlob(tpmcred.hexToBytes(NAME), tpmcred.hexToBytes(ent.secret), tpmcred.hexToBytes(ent.seed))));
  check("the wrapped seed is TPM2B(RSA-2048 ciphertext)", tx && tx.data.enc.length === 2 * (2 + 256) && tx.data.enc.startsWith("0100"));
  check("a success line is logged", ev.some((e) => e[0] === "log" && e[1] === "ok" && /Challenging a TPM enrolment/.test(e[2])));
  const oaep = new Uint8Array(await webcrypto.subtle.decrypt({ name: "RSA-OAEP", label: new TextEncoder().encode("IDENTITY\0") }, kp.privateKey, tpmcred.hexToBytes(tx.data.enc).slice(2)));
  check("the EK's private key unwraps the stored seed (label IDENTITY\\0, SHA-256)", tpmcred.bytesToHex(oaep) === ent.seed);

  // ---- 2. in flight: the same duty on the next pass sends nothing --------------------------------------------------
  h.events.length = 0;
  tip = 1001;
  await h.maybeTpmChallenge();
  check("NEVER TWO IN FLIGHT FOR ONE ID: no resend while the challenge's window is open", submits(h.events).length === 0);

  // ---- 3. its window lapsed and the relay still asks: resend, under the SAME secret ------------------------------------
  h.events.length = 0;
  tip = 1301;
  h.env.state.latest = 1301;
  const again = chal(ID1, { min_block: 1309, max_block: 1600 });
  h.env.fetch = async () => ({ ok: true, json: async () => ({ tip, duties: [again] }) });
  await h.maybeTpmChallenge();
  const tx2 = submits(h.events)[0];
  check("a lapsed challenge is re-sent", !!tx2);
  check("AN EXISTING SECRET IS NEVER REPLACED: the re-sent blob is sealed under the first secret",
    tx2 && tx2.data.blob === tx.data.blob && storeOf(h)[ID1].secret === ent.secret);
}

// ---- 4. one message per enrolment per pass; two enrolments both advance --------------------------------------------
{
  const h = harness({ duty: () => ({ tip: 1000, duties: [chal(ID1), chal(ID1), reveal(ID1), chal(ID2)] }) });
  await h.maybeTpmChallenge();
  const s = submits(h.events);
  check("ONE MESSAGE PER ENROLMENT PER PASS", s.filter((t) => t.data.id === ID1).length === 1, s.map((t) => t.recipient + ":" + t.data.id.slice(0, 2)).join());
  check("...and every enrolment gets its step (not one message per pass in total)", s.some((t) => t.data.id === ID2));
  check("one /tpm_duty fetch per pass", h.events.filter((e) => e[0] === "fetch" && /\/tpm_duty\?address=/.test(e[1])).length === 1);
}

// ---- 5. reveal: only on "reveal", with the stored pair -------------------------------------------------------------
{
  const secret = "11".repeat(32), seed = "22".repeat(32);
  const h0 = harness({ duty: () => ({}) });
  const key = h0.tpmSecretsKey(ADDR);
  const ls = [[key, JSON.stringify({ [ID1]: { secret, seed, at: 990, seen: 995, pend: { action: "challenge", txid: "x", max: 999 } } })]];
  const hc = harness({ ls, duty: () => ({ tip: 1000, duties: [chal(ID1)] }) });
  await hc.maybeTpmChallenge();
  check("REVEAL ONLY ON ACTION reveal: a held secret is not revealed while the relay says challenge",
    submits(hc.events).every((t) => t.recipient !== "tpm_reveal"));
  const h = harness({ ls, duty: () => ({ tip: 1000, duties: [reveal(ID1)] }) });
  await h.maybeTpmChallenge();
  const tx = submits(h.events)[0];
  check("on reveal, tpm_reveal {id, secret, seed} carries the stored pair",
    tx && tx.recipient === "tpm_reveal" && tx.data.id === ID1 && tx.data.secret === secret && tx.data.seed === seed
    && Object.keys(tx.data).sort().join() === "id,secret,seed");
  check("the reveal is logged", h.events.some((e) => e[0] === "log" && e[1] === "ok" && /Revealed your TPM challenge/.test(e[2])));
  h.events.length = 0;
  await h.maybeTpmChallenge();
  check("no second reveal while the first is in flight", submits(h.events).length === 0);
}

// ---- 6. reveal without a secret: nothing sent, said once ------------------------------------------------------------
{
  const h = harness({ duty: () => ({ tip: 1000, duties: [reveal(ID1)] }) });
  await h.maybeTpmChallenge();
  await h.maybeTpmChallenge();
  check("a reveal with no stored secret sends nothing", submits(h.events).length === 0);
  check("...and warns ONCE, not once per poll", h.events.filter((e) => e[0] === "log" && /does not hold its challenge secret/.test(e[2])).length === 1);
}

// ---- 7. storage that cannot keep the secret: no challenge at all ----------------------------------------------------
{
  const h = harness({ lsThrows: true, duty: () => ({ tip: 1000, duties: [chal(ID1)] }) });
  await h.maybeTpmChallenge();
  check("NO CHALLENGE WITHOUT A STORED SECRET (storage throws)", submits(h.events).length === 0);
  check("...and the reason is logged", h.events.some((e) => e[0] === "log" && e[1] === "err" && /cannot store the TPM challenge secret/.test(e[2])));
}

// ---- 8. unbonded accounts are never asked ---------------------------------------------------------------------------
{
  const h = harness({ bonded: 0n, duty: () => ({ tip: 1000, duties: [chal(ID1)] }) });
  await h.maybeTpmChallenge();
  check("an unbonded account does not even fetch /tpm_duty", h.events.length === 0);
  const hl = harness({ duty: () => ({ tip: 1000, duties: [chal(ID1)] }) });
  hl.env.state.locked = true;
  await hl.maybeTpmChallenge();
  check("a locked wallet does nothing", hl.events.length === 0);
}

// ---- 9. a permanent refusal is not resent; a transient one is --------------------------------------------------------
{
  let msg = "Could not merge remote transaction: not a drawn challenger for this enrolment";
  const h = harness({ duty: () => ({ tip: 1000, duties: [chal(ID1)] }), submit: () => ({ result: false, message: msg }) });
  await h.maybeTpmChallenge();
  await h.maybeTpmChallenge();
  check("a permanent refusal is sent once and never again", submits(h.events).length === 1);
  check("...and logged once", h.events.filter((e) => e[0] === "log" && /refused/.test(e[2])).length === 1);
  msg = "transaction pool is full";
  const h2 = harness({ duty: () => ({ tip: 1000, duties: [chal(ID2)] }), submit: () => ({ result: false, message: msg }) });
  await h2.maybeTpmChallenge();
  await h2.maybeTpmChallenge();
  check("a transient refusal is retried on the next pass", submits(h2.events).length === 2);
  check("...under the same secret", submits(h2.events)[0].data.blob === submits(h2.events)[1].data.blob);
}

// ---- 9b. two tabs: a secret another tab stored first wins; ours is never written over it ---------------------------
{
  const other = { secret: "33".repeat(32), seed: "44".repeat(32), at: 999, seen: 999 };
  let armed = true;
  const h = harness({
    duty: () => ({ tip: 1000, duties: [chal(ID1)] }),
    // the other tab writes its secret right AFTER this tab's first read of the store (the race a snapshot loses)
    onGet: (k, data) => { if (armed && k.startsWith("nado_tpm_chal_v1:")) { armed = false; data.set(k, JSON.stringify({ [ID1]: other })); } },
  });
  await h.maybeTpmChallenge();
  const st = storeOf(h)[ID1];
  const tx = submits(h.events)[0];
  check("TWO TABS: the secret another tab stored first is kept, never overwritten", st && st.secret === other.secret && st.seed === other.seed);
  check("...and this tab's challenge is sealed under that stored secret",
    tx && tx.data.blob === tpmcred.bytesToHex(tpmcred.credentialBlob(tpmcred.hexToBytes(NAME), tpmcred.hexToBytes(other.secret), tpmcred.hexToBytes(other.seed))));
}
// ---- 9c. Web Locks: a tab that finds the duty lock held skips the pass -------------------------------------------------
{
  const held = { locks: { request: async (name, o, cb) => { check("the lock is per account and non-blocking", name === "nado_tpm_duty:" + ADDR && o && o.ifAvailable === true); return cb(null); } } };
  const h = harness({ navigator: held, duty: () => ({ tip: 1000, duties: [chal(ID1)] }) });
  await h.maybeTpmChallenge();
  check("lock held by another tab: no fetch, no broadcast", h.events.length === 0);
  const free = { locks: { request: async (name, o, cb) => cb({ name }) } };
  const h2 = harness({ navigator: free, duty: () => ({ tip: 1000, duties: [chal(ID1)] }) });
  await h2.maybeTpmChallenge();
  check("lock granted: the pass runs", submits(h2.events).length === 1);
}

// ---- 10. pruning ----------------------------------------------------------------------------------------------------
{
  const h0 = harness({ duty: () => ({}) });
  const keep = h0.TPM_SECRET_KEEP_BLOCKS;
  const s = (o) => ({ secret: "11".repeat(32), seed: "22".repeat(32), ...o });
  const ls = [[h0.tpmSecretsKey(ADDR), JSON.stringify({
    ["1".repeat(32)]: s({ at: 900, seen: 950, revealed: 960, pend: { action: "reveal", txid: "r", max: 990 } }),   // spent
    ["2".repeat(32)]: s({ at: 900, seen: 960, revealed: 960, pend: { action: "reveal", txid: "r", max: 1100 } }),  // reveal still in flight
    ["3".repeat(32)]: s({ at: 900, seen: 950 }),                                                                    // waiting for the commit
    ["4".repeat(32)]: s({ at: 100, seen: 1000 - keep - 1 }),                                                        // older than any enrolment
    [ID1]: s({ at: 900, seen: 950, revealed: 960, pend: { action: "reveal", txid: "r", max: 990 } }),               // spent but STILL returned
  })]];
  const h = harness({ ls, duty: () => ({ tip: 1000, duties: [reveal(ID1, { max_block: 999 })] }) });
  await h.maybeTpmChallenge();
  const st = storeOf(h);
  check("prunes a spent secret the relay no longer returns", !("1".repeat(32) in st));
  check("keeps a revealed secret while its reveal can still land", "2".repeat(32) in st);
  check("keeps an unrevealed secret between challenge and commit (not returned is not enough)", "3".repeat(32) in st);
  check("prunes a secret unseen for longer than any enrolment can live", !("4".repeat(32) in st));
  check("never prunes an id the relay still returns", ID1 in st);
}

// ---- 11. the permanent-refusal classifier still matches what the node raises ------------------------------------------
{
  const h = harness({ duty: () => ({}) });
  const py = readFileSync(join(ROOT, "ops", "tpm_enrol.py"), "utf8") + readFileSync(join(ROOT, "ops", "transaction_ops.py"), "utf8");
  const alts = h.DEAD_TPM_RE.source.split("|");
  for (const a of alts) check(`node still raises: "${a}"`, py.includes(a));
  for (const m of ["a reveal must land in a later block than the commitment — otherwise the client reads the secret",
                   "enrolment is not awaiting reveals", "no such enrolment", "transaction pool is full", "Target block too high"])
    check(`retryable, not dead: "${m.slice(0, 50)}"`, !h.DEAD_TPM_RE.test(m));
}

// ---- 12. wiring: the poll loop runs it next to the epoch duty; every string is in the en table verbatim --------------
{
  const poll = js.slice(js.indexOf("async function pollOnce()"), js.indexOf("function startPollLoop()"));
  const iR = poll.indexOf("await maybeRandao()"), iT = poll.indexOf("await maybeTpmChallenge()");
  check("pollOnce runs maybeTpmChallenge, after the epoch duty", iR > 0 && iT > iR);
  check("interface.js imports the credential module", /from "\.\/tpmcred\.js"/.test(js));
  global.window = {};
  global.document = { readyState: "loading", addEventListener() {}, getElementById() { return null; }, querySelector() { return null; } };
  Object.defineProperty(global, "navigator", { value: { languages: ["en"] }, configurable: true });
  Object.defineProperty(global, "localStorage", { value: { getItem() { return null; }, setItem() {} }, configurable: true });
  eval(readFileSync(join(ROOT, "static", "i18n.js"), "utf8").replace("window.NADO_i18n = {", "window.NADO_i18n = { T: T, "));
  const T = window.NADO_i18n.T;
  for (const m of body.matchAll(/i18\("(log\.tpm\w+)", "((?:[^"\\]|\\.)*)"/g)) {
    check(`${m[1]}: English fallback equals the en table`, T.en[m[1]] === m[2]);
    const ph = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
    for (const l of Object.keys(T)) if (!(T[l][m[1]] && ph(T[l][m[1]]) === ph(m[2]))) check(`${m[1]} in ${l} with its placeholders`, false);
  }
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);

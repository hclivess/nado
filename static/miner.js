/* NADO browser light-miner.
 *
 * Reproduces the node's Python consensus encoding EXACTLY so a phone can compute identical
 * addresses, txids and ML-DSA-44 (post-quantum) signatures without holding the chain or heavy crypto:
 *   - canonical_bytes  == json.dumps(data, sort_keys=True, separators=(",",":"), ensure_ascii=True)
 *   - blake2b_hash(d,n) == blake2b(canonical_bytes(d), digest_size=n).hexdigest()
 *   - make_address / registration PoW / tx bodies match ops/*.py
 * The canonical/crypto functions below are byte-verified against vectors generated from the live
 * repo (see the in-page Self-test). Do NOT change them without re-running the vectors.
 */

/* ----------------------------------------------------------------------------------------------
 * Protocol constants (mirror protocol.py — consensus-critical)
 * -------------------------------------------------------------------------------------------- */
import { poswProveAsync, challengeBytes } from "./posw.js";
const CHAIN_ID = "nado-relaunch-1";
const EPOCH_LENGTH = 60;
const REGISTER_POW_BITS = 16;  // legacy hashcash (retired) — kept only for the self-test vector
// Registration Proof of Sequential Work (must match protocol.py). Non-parallelizable ~1 s chain; the
// registration is a renewable presence LEASE renewed once ~POSW_LEASE_EPOCHS (≈1 day at ~8 min/epoch).
const POSW_T = 1_000_000, POSW_S = 2_000, POSW_K = 20, POSW_ANCHOR_OFFSET = 30, POSW_LEASE_EPOCHS = 180;
const DENOMINATION = 10_000_000_000n; // 1 NADO in raw units (1e10)
const MIN_TX_FEE = 1000;
const BOND_UNLOCK_DELAY = 1440; // protocol.py: blocks a bond stays locked after an unbond request
const BOND_CAP = 100_000_000_000_000n;  // protocol.py: 10,000 NADO — bonding past this buys no weight
const ALIAS_REGISTRATION_FEE = 10_000_000; // protocol.py: 0.001 NADO anti-squat fee for `alias` register
const AUTO_BOND_MIN_RAW = 10_000_000n;  // protocol.py: dust floor for an auto-bond (0.001 NADO)

/* ----------------------------------------------------------------------------------------------
 * Dependency loading: @noble/hashes (blake2b) + @noble/post-quantum (ML-DSA-44) as ESM from a CDN.
 * -------------------------------------------------------------------------------------------- */
let blake2b, bytesToHex, hexToBytes, ml_dsa44;

// Optional, locally-vendored QR generator (static/vendor/qrcode.js). Loaded best-effort: if it is
// missing the Receive tab degrades to showing the address text instead of failing (NO runtime CDN).
let qrEncode = null;
async function loadQR() {
  try { const m = await import('./vendor/qrcode.js'); qrEncode = m.qrMatrix || null; }
  catch (e) { qrEncode = null; }
}

async function loadDeps() {
  // 1) LOCAL self-contained bundle (no internet needed) — all symbols from one vendored module.
  //    This is what makes the wallet WORK on a phone / restricted network where the CDN is blocked.
  try {
    const m = await import('./vendor/nado-crypto.js');
    blake2b = m.blake2b; bytesToHex = m.bytesToHex; hexToBytes = m.hexToBytes; ml_dsa44 = m.ml_dsa44;
    if (blake2b && ml_dsa44) return;
  } catch (e) { /* fall through to CDN */ }
  // 2) CDN fallback (esm.sh, then jsdelivr) only if the local bundle isn't served.
  const cdns = [
    (pkg) => `https://esm.sh/${pkg}`,
    (pkg) => `https://cdn.jsdelivr.net/npm/${pkg}/+esm`,
  ];
  let lastErr;
  for (const build of cdns) {
    try {
      const [hb, hu, pq] = await Promise.all([
        import(build("@noble/hashes@1.4.0/blake2b")),
        import(build("@noble/hashes@1.4.0/utils")),
        import(build("@noble/post-quantum@0.2.0/ml-dsa")),
      ]);
      blake2b = hb.blake2b;
      bytesToHex = hu.bytesToHex;
      hexToBytes = hu.hexToBytes;
      // ML-DSA-44 (FIPS 204). @noble's DEFAULT sign/verify interoperate both ways with the node's
      // dilithium-py ML-DSA-44 *internal* mode (same 32-byte seed -> identical 1312-byte pubkey).
      ml_dsa44 = pq.ml_dsa44;
      return;
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr;
}

/* ----------------------------------------------------------------------------------------------
 * Canonical encoding  (== Python json.dumps sort_keys, compact, ensure_ascii) — BigInt-safe.
 * -------------------------------------------------------------------------------------------- */
function jsonEscapeAscii(s) {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    switch (c) {
      case 0x22: out += '\\"'; continue;
      case 0x5c: out += "\\\\"; continue;
      case 0x08: out += "\\b"; continue;
      case 0x09: out += "\\t"; continue;
      case 0x0a: out += "\\n"; continue;
      case 0x0c: out += "\\f"; continue;
      case 0x0d: out += "\\r"; continue;
    }
    if (c < 0x20 || c > 0x7e) {
      out += "\\u" + c.toString(16).padStart(4, "0");
    } else {
      out += s[i];
    }
  }
  return out + '"';
}

function canonicalize(data) {
  if (data === null || data === undefined) return "null";
  const t = typeof data;
  if (t === "boolean") return data ? "true" : "false";
  if (t === "bigint") return data.toString();
  if (t === "number") {
    if (!Number.isFinite(data) || !Number.isInteger(data))
      throw new Error("canonical encoding forbids floats / non-finite numbers: " + data);
    if (!Number.isSafeInteger(data))
      throw new Error("integer exceeds 2^53; pass it as a BigInt for an exact match");
    return String(data);
  }
  if (t === "string") return jsonEscapeAscii(data);
  if (Array.isArray(data)) {
    let out = "[";
    for (let i = 0; i < data.length; i++) {
      if (i) out += ",";
      out += canonicalize(data[i]);
    }
    return out + "]";
  }
  if (t === "object") {
    const keys = Object.keys(data).sort();
    let out = "{";
    for (let i = 0; i < keys.length; i++) {
      if (i) out += ",";
      out += jsonEscapeAscii(keys[i]) + ":" + canonicalize(data[keys[i]]);
    }
    return out + "}";
  }
  throw new Error("unsupported type in canonical encoding: " + t);
}

const _enc = new TextEncoder();
function canonicalBytes(data) { return _enc.encode(canonicalize(data)); }

function blake2bHash(data, size = 32) {
  return bytesToHex(blake2b(canonicalBytes(data), { dkLen: size }));
}
function blake2bHashLink(a, b, size = 32) { return blake2bHash([a, b], size); }

/* ----------------------------------------------------------------------------------------------
 * Addresses, keys, registration PoW
 * -------------------------------------------------------------------------------------------- */
function makeAddress(pubHex) {
  const body = "ndo" + pubHex.slice(0, 42);
  return body + blake2bHash(body, 2);
}

function newKeypair() {
  // The private key is a 32-byte ML-DSA-44 SEED; the 1312-byte public key derives from it.
  const seed = crypto.getRandomValues(new Uint8Array(32));
  const { publicKey } = ml_dsa44.keygen(seed);
  const seedHex = bytesToHex(seed);
  const pubHex = bytesToHex(publicKey);
  return { privateKey: seedHex, publicKey: pubHex, address: makeAddress(pubHex) };
}

function keypairFromPriv(privHex) {
  privHex = (privHex || "").trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(privHex)) throw new Error("private key (seed) must be 64 hex chars (32 bytes)");
  const { publicKey } = ml_dsa44.keygen(hexToBytes(privHex));
  const pubHex = bytesToHex(publicKey);
  return { privateKey: privHex, publicKey: pubHex, address: makeAddress(pubHex) };
}

// Validate a recipient address byte-identically to ops/address_ops.validate_address: a canonical
// NADO address is "ndo" + 42-hex pubkey body + a 4-hex blake2b checksum over everything-but-the-last-4
// (== 49 chars). A mistyped address fails the checksum and is rejected before any tx is built.
function validateAddress(addr) {
  addr = (addr || "").trim();
  if (!/^ndo[0-9a-f]{46}$/.test(addr)) return false; // ndo + 46 hex = 49 chars
  return blake2bHash(addr.slice(0, -4), 2) === addr.slice(-4);
}

// ALIAS: a short human-readable name that resolves to an owner address on-chain. Client mirror of
// ops/alias_ops.valid_alias_name (3..32 chars, lowercase [a-z0-9_-], starts with a letter, not "ndo…").
function looksLikeAlias(s) { return /^[a-z][a-z0-9_-]{2,31}$/.test(s || "") && !s.startsWith("ndo"); }
// i18n helper for dynamic (JS-set) strings — translates via i18n.js's window.t, English fallback.
function i18(k, fb, vars) { return (typeof window !== "undefined" && window.t) ? window.t(k, fb, vars) : (fb != null ? fb : k); }
async function resolveAlias(name) {
  try {
    const r = await fetch(relayBase() + "/resolve_alias?name=" + encodeURIComponent(name), { cache: "no-store" });
    const d = await r.json();
    return d && d.owner ? d.owner : null;
  } catch { return null; }
}
// Live validation of the Send "to" field: a valid ndo… address, OR a registered alias (resolved
// against the node, so the ✗ clears once the alias exists). Guards against stale async results.
async function validateSendTo() {
  const v = ($("sendTo").value || "").trim();
  if (!v) { setMsg("sendToMsg", "", null); return; }
  if (validateAddress(v)) { setMsg("sendToMsg", i18("sto.valid", "✓ valid address"), "ok"); return; }
  if (looksLikeAlias(v)) {
    setMsg("sendToMsg", i18("sto.resolving", "resolving alias…"), null);
    const owner = await resolveAlias(v);
    if (($("sendTo").value || "").trim() !== v) return;   // input changed while resolving — ignore stale
    setMsg("sendToMsg", owner ? `${i18("sto.aliasPre","✓ alias →")} ${owner.slice(0, 14)}…` : `${i18("sto.aliasNoPre","✗ alias")} “${v}” ${i18("sto.aliasNoSuf","is not registered")}`, owner ? "ok" : "err");
    return;
  }
  setMsg("sendToMsg", i18("sto.invalid", "✗ invalid — a 49-char ndo… address or a registered alias name"), "err");
}

// ADDRESS BOOK: every recipient you send to (alias or address) is remembered in localStorage, offered
// as native autocomplete on the Send field (datalist) + clickable recent chips to reselect.
const LS_ADDRBOOK = "nado_addrbook";
function addrBookLoad() { try { return JSON.parse(localStorage.getItem(LS_ADDRBOOK) || "[]"); } catch { return []; } }
function addrBookAdd(to) {
  to = (to || "").trim();
  if (!to) return;
  let book = addrBookLoad().filter((x) => x !== to);
  book.unshift(to);
  book = book.slice(0, 40);
  try { localStorage.setItem(LS_ADDRBOOK, JSON.stringify(book)); } catch (e) {}
  addrBookRender();
}
function addrBookRender() {
  const book = addrBookLoad();
  const dl = $("sendToBook");
  if (dl) dl.innerHTML = book.map((x) => `<option value="${x.replace(/"/g, "&quot;")}"></option>`).join("");
  const chips = $("addrBook");
  if (chips) {
    chips.innerHTML = book.length
      ? "Recent: " + book.slice(0, 8).map((x) => {
          const label = /^ndo[0-9a-f]{46}$/.test(x) ? x.slice(0, 10) + "…" : x;   // aliases whole, addresses shortened
          return `<a class="ex-link addrpick" data-to="${x.replace(/"/g, "&quot;")}" style="margin-right:8px">${label}</a>`;
        }).join("")
      : "";
  }
}

function powTarget() { return 1n << BigInt(256 - REGISTER_POW_BITS); }
function powHashInt(address, nonce) {
  return BigInt("0x" + blake2bHash(["nado-register", address, nonce]));
}
function powValid(address, nonce) { return powHashInt(address, nonce) < powTarget(); }

/* ----------------------------------------------------------------------------------------------
 * Transactions: build body, add txid (over the body incl. fee), then ML-DSA-44 sign(unhex(txid)).
 * -------------------------------------------------------------------------------------------- */
function randNonce(len = 8) {
  const a = "abcdefghijklmnopqrstuvwxyz";
  let s = "";
  const r = crypto.getRandomValues(new Uint8Array(len));
  for (let i = 0; i < len; i++) s += a[r[i] % 26];
  return s;
}

// PUBKEY-ONCE (#19): mirror the node's ops/transaction_ops.create_txid EXACTLY — the `public_key`
// is EXCLUDED from the txid preimage (it is a recoverable authentication witness bound to the
// sender address, not part of the tx identity). So the txid is identical whether or not the body
// carries the 1312-byte ML-DSA key, letting a later tx (heartbeat / established-sender send) omit it.
function createTxid(body) {
  const preimage = {};
  for (const k of Object.keys(body)) if (k !== "public_key") preimage[k] = body[k];
  return blake2bHash(preimage);
}

function finalizeTransaction(draft, privHex, fee) {
  const body = { ...draft, fee }; // fee is part of the signed body (matches create_transaction)
  const txid = createTxid(body);  // public_key (if present in body) is excluded from this hash
  // Derive the ML-DSA-44 secret key from the 32-byte seed, then sign the message bytes M = unhex(txid).
  const { secretKey } = ml_dsa44.keygen(hexToBytes(privHex));
  const signature = bytesToHex(ml_dsa44.sign(secretKey, hexToBytes(txid)));
  return { ...body, txid, signature };
}

// REGISTER is by definition an address's FIRST on-chain tx, so it MUST carry public_key — this is
// what establishes the sender's pubkey on-chain (the node stores it on first use) and lets every
// later tx omit it. Always include it here.
function buildRegisterTx(wallet, targetBlock, posw, timestamp) {
  const draft = {
    sender: wallet.address,
    recipient: "register",
    amount: 0,
    timestamp,
    data: "",
    nonce: randNonce(),
    public_key: wallet.publicKey,
    target_block: targetBlock,
    chain_id: CHAIN_ID,
    posw,                        // sequential Proof of Work (renewable presence lease); replaces pow_nonce
  };
  return finalizeTransaction(draft, wallet.privateKey, 0);
}

// Fetch the PoSW anchor (hash of block target_block − POSW_ANCHOR_OFFSET — a finalized, stable block that
// the node derives identically), compute the non-parallelizable sequential proof, and build the register tx.
async function computeRegisterTx(targetBlock, onProgress) {
  const anchorNum = Math.max(0, targetBlock - POSW_ANCHOR_OFFSET);
  const r = await fetch(relayBase() + "/get_block_number?number=" + anchorNum, { cache: "no-store" });
  const b = await r.json().catch(() => null);
  const anchorHash = b && b.block_hash;
  if (!anchorHash) throw new Error("registration anchor block unavailable");
  const proof = await poswProveAsync(challengeBytes(state.wallet.address, anchorHash),
    POSW_T, POSW_S, POSW_K, { blake2b, bytesToHex, hexToBytes }, onProgress);
  return buildRegisterTx(state.wallet, targetBlock, proof, nowSeconds());
}


// TRANSFER / bond / unbond. include public_key ONLY when the sender's pubkey isn't yet established
// on-chain (i.e. this could be the address's first tx). Callers pass includePubkey=false once
// /get_account shows the pubkey is established (registered, or a stored public_key) — omitting the
// key then. Including it is always safe (the node accepts a redundant key), so default to true.
function buildTransferTx(wallet, recipient, rawAmount, fee, targetBlock, data, timestamp, includePubkey = true) {
  const draft = {
    sender: wallet.address,
    recipient,
    amount: rawAmount, // BigInt-safe
    timestamp,
    data: data || "",
    nonce: randNonce(),
    target_block: targetBlock,
    chain_id: CHAIN_ID,
  };
  if (includePubkey) draft.public_key = wallet.publicKey;
  return finalizeTransaction(draft, wallet.privateKey, fee);
}

// PUBKEY-ONCE (#19): is the sender's pubkey already recorded on-chain? The node stores it on an
// address's FIRST on-chain tx (register OR any transfer), after which later txs may omit it. If we
// can't tell (no account doc / relay hiccup) return false so we include the key — always safe.
function pubkeyEstablished(acc) {
  return !!(acc && (acc.public_key || acc.registered === 1));
}

/* ----------------------------------------------------------------------------------------------
 * Relay RPC client
 * -------------------------------------------------------------------------------------------- */
const state = {
  wallet: null,
  relay: null,
  mining: false,
  starting: false,     // a start/auto-registration is in flight; button is disabled (idempotency guard)
  powJob: null,
  registering: false,  // a PoW+submit is currently in flight (re-entrancy guard)
  regSubmitted: null,  // { targetBlock, txid } of the registration we last broadcast, or null
  heartbeating: false,   // a heartbeat submit is in flight (re-entrancy guard for overlapping polls)
  latest: null,        // latest block number
  blockTime: 60,
  pollTimer: null,
  wakeLock: null,      // screen WakeLockSentinel held while mining so the phone won't auto-lock/suspend
  nextHbAt: null,
  activeTab: "wallet",
  recommendedFee: null,
  // AUTO-BOND (client-side, opt-in): compound a % of newly-mined earnings straight into bonded stake
  // while mining, at most once per epoch. baseline = last balance we've accounted for.
  autoBondPct: 80,     // AUTO_BOND_DEFAULT_PCT (const declared below); boot overwrites w/ saved pref
  autoBondBaseline: null,
  autoBondPending: null,   // {target, epoch} while an auto-bond is in flight — prevents stacking bonds
  lastAutoBondEpoch: null,
};

function relayBase() { return (state.relay || location.origin).replace(/\/+$/, ""); }
// Execution node (presence dividend + contracts) — same host as the relay, exec port 9273 (overridable).
function execBase() {
  if (state.execUrl) return state.execUrl.replace(/\/+$/, "");
  const b = relayBase();
  return /:\d+$/.test(b) ? b.replace(/:\d+$/, ":9273") : b + ":9273";
}

/* PRESENCE DIVIDEND (doc/presence-dividend.md). accrued lives off-L1 on the execution node; "Collect" submits
 * a fee-cheap collect blob, then the accrued amount is claimed to L1 automatically once the exec root that
 * carries it is settled by the bonded quorum. */
function buildBlobTx(wallet, payload, targetBlock, fee, timestamp) {
  const draft = { sender: wallet.address, recipient: "blob", amount: 0, timestamp, data: payload,
    nonce: randNonce(), public_key: wallet.publicKey, target_block: targetBlock, chain_id: CHAIN_ID };
  return finalizeTransaction(draft, wallet.privateKey, fee);
}
function buildDividendWithdrawTx(wallet, addr, amount, nonce, proof, targetBlock, timestamp) {
  const draft = { sender: wallet.address, recipient: "dividend_withdraw", amount: 0, timestamp,
    data: { addr, amount, nonce, proof }, nonce: randNonce(), public_key: wallet.publicKey,
    target_block: targetBlock, chain_id: CHAIN_ID };
  return finalizeTransaction(draft, wallet.privateKey, 0);   // fee-exempt
}

async function refreshDividend() {
  if (!state.wallet) return;
  // Surface the dividend section whenever you're actively MINING (so it's discoverable — you watch it
  // accrue from 0), or whenever there's an accrued/pending amount even after you stop. Idle non-miners
  // with nothing accrued don't see it (no clutter). Crucially, show it even if the exec node is briefly
  // unreachable (with a status), so a miner is never left wondering where the dividend went.
  const mining = !!state.mining;
  let d = null, reachable = true;
  try {
    const r = await fetch(execBase() + "/exec/dividend?address=" + encodeURIComponent(state.wallet.address), { cache: "no-store" });
    d = await r.json();
  } catch (e) { reachable = false; }
  const accrued = BigInt((d && d.accrued) || 0);
  const pending = (d && d.pending) || [];
  show("divWrap", mining || accrued > 0n || pending.length > 0);
  if ($("divAccrued")) $("divAccrued").textContent = reachable ? (rawToNado(accrued) + " NADO") : i18("div.unavail", "exec node unreachable");
  if ($("btnCollectDiv")) $("btnCollectDiv").disabled = !(accrued > 0n) || state._collecting;
  if (!reachable) return;
  // AUTO-CLAIM any collected-but-unclaimed dividend whose proof matches the settled root.
  if (pending.length && !state._claiming) { state._claiming = true; try { await claimPendingDividends(pending); } finally { state._claiming = false; } }
}

async function claimPendingDividends(pending) {
  let settled;
  try { settled = await (await fetch(relayBase() + "/get_settled", { cache: "no-store" })).json(); } catch { return; }
  const settledRoot = settled && settled.state_root;
  if (!settledRoot) return;
  const latest = await getLatestBlock(); if (!latest) return;
  for (const p of pending) {
    try {
      const pr = await (await fetch(execBase() + "/exec/dividend_proof?nonce=" + encodeURIComponent(p.nonce), { cache: "no-store" })).json();
      if (!pr || pr.state_root !== settledRoot) continue;   // proof must be against the SETTLED root; else wait
      const tx = buildDividendWithdrawTx(state.wallet, state.wallet.address, p.amount, p.nonce, pr.proof, latest.block_number + 8, nowSeconds());
      const res = await submitTransaction(tx);
      if (res.data && res.data.result) log("ok", i18("log.divCollected", "Dividend collected: +{a} NADO to your balance.", {a: rawToNado(BigInt(p.amount))}));
    } catch (e) { /* not claimable yet (unsettled) — retry next refresh */ }
  }
}

async function collectDividend() {
  if (!state.wallet || state._collecting) return;
  state._collecting = true;
  if ($("btnCollectDiv")) $("btnCollectDiv").disabled = true;
  try {
    const latest = await getLatestBlock();
    if (!latest) throw new Error("relay unavailable");
    const tx = buildBlobTx(state.wallet, { op: "collect_dividend" }, latest.block_number + 8, MIN_TX_FEE, nowSeconds());
    const res = await submitTransaction(tx);
    if (res.data && res.data.result)
      log("ok", i18("div.collecting", "Dividend collection submitted — it lands in your balance automatically once the exec root is settled (a few minutes)."));
    else log("err", i18("log.collectRejected", "Collect rejected: {m}", {m: (res.data && (res.data.message || ""))}));
  } catch (e) { log("err", i18("log.collectFailed", "Collect failed: {m}", {m: e.message})); }
  finally { state._collecting = false; }
}

async function rpcJSON(path) {
  const url = relayBase() + path;
  const res = await fetch(url, { method: "GET", cache: "no-store" });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  return { ok: res.ok, status: res.status, data };
}

async function getLatestBlock() { return (await rpcJSON("/get_latest_block")).data; }
async function getAccount(address) {
  const r = await rpcJSON("/get_account?address=" + encodeURIComponent(address));
  return r.ok ? r.data : null;
}
async function getMiningStatus(address) {
  const r = await rpcJSON("/mining_status?address=" + encodeURIComponent(address));
  return r.ok ? r.data : null;
}

/* Submit a transaction. A post-quantum (ML-DSA-44) tx is ~7.8 KB — far past a URL's safe length —
 * so we POST the canonical JSON body (BigInt-safe; the node json.loads() it back to the identical dict). */
async function submitTransaction(tx) {
  const payload = canonicalize(tx);
  // POST the canonical JSON body — the only submit path (a PQ tx is far too large for a GET URL).
  const res = await fetch(relayBase() + "/submit_transaction", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: payload,
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { result: false, message: text }; }
  return { ok: res.ok, status: res.status, data };
}

/* ----------------------------------------------------------------------------------------------
 * UI helpers
 * -------------------------------------------------------------------------------------------- */
const $ = (id) => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);

function log(kind, msg) {
  const el = $("log");
  const line = document.createElement("div");
  line.className = "line";
  const t = new Date().toLocaleTimeString();
  line.innerHTML = `<span class="t">${t}</span> <span class="${kind}">${escapeHtml(msg)}</span>`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
  show("logCard", true);
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function humanizeSeconds(s) {
  if (s == null) return "—";
  s = Math.round(s);
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
  if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
  return Math.floor(s / 86400) + "d " + Math.floor((s % 86400) / 3600) + "h";
}

function rawToNado(raw) {
  raw = BigInt(raw);
  const neg = raw < 0n;
  if (neg) raw = -raw;
  const whole = raw / DENOMINATION;
  const frac = (raw % DENOMINATION).toString().padStart(10, "0").replace(/0+$/, "");
  return (neg ? "-" : "") + whole.toString() + (frac ? "." + frac : "");
}
function nadoToRaw(amountStr) {
  const m = String(amountStr).trim().match(/^(\d+)(?:\.(\d{1,10}))?$/);
  if (!m) throw new Error("invalid amount");
  const whole = BigInt(m[1]);
  const frac = BigInt((m[2] || "").padEnd(10, "0"));
  return whole * DENOMINATION + frac;
}

/* ----------------------------------------------------------------------------------------------
 * Wallet persistence
 * -------------------------------------------------------------------------------------------- */
const LS_WALLET = "nado_miner_wallet";
const LS_RELAY = "nado_miner_relay";
const LS_AUTOBOND = "nado_autobond_pct";   // persisted auto-bond percentage (0..100)
const LS_MINING = "nado_mining";           // "1" while mining, so a browser refresh auto-resumes (no re-click)
const AUTO_BOND_DEFAULT_PCT = 80;          // default when the user has never set one (matches protocol.AUTO_BOND_DEFAULT_PERCENT)
const LS_PENDING_PAY = "nado_pending_pay"; // sessionStorage: a pay-request awaiting wallet setup

function persistWallet(w) { localStorage.setItem(LS_WALLET, JSON.stringify(w)); }
function loadWallet() {
  try { return JSON.parse(localStorage.getItem(LS_WALLET)); } catch { return null; }
}

/* ----------------------------------------------------------------------------------------------
 * Registration PoW — chunked async so the UI stays responsive (and is cancellable).
 * -------------------------------------------------------------------------------------------- */
function solveRegistrationPow(address, { onProgress, signal } = {}) {
  const target = powTarget();
  const start = performance.now();
  let nonce = 0;
  const CHUNK = 1500;
  return new Promise((resolve, reject) => {
    function step() {
      if (signal && signal.cancelled) return reject(new Error("cancelled"));
      const end = nonce + CHUNK;
      for (; nonce < end; nonce++) {
        if (powHashInt(address, nonce) < target) {
          return resolve({ nonce, hashes: nonce + 1, seconds: (performance.now() - start) / 1000 });
        }
      }
      if (onProgress) {
        const secs = (performance.now() - start) / 1000;
        onProgress({ hashes: nonce, seconds: secs, rate: nonce / Math.max(secs, 0.001) });
      }
      setTimeout(step, 0); // yield to the event loop / repaint
    }
    step();
  });
}

/* ----------------------------------------------------------------------------------------------
 * Mining engine
 * -------------------------------------------------------------------------------------------- */

/* ---- Start/Mine button + staged status banner -------------------------------------------------
 * The Start/Mine button has three visual states so a first-time user gets clear feedback that the
 * multi-second one-time auto-registration is underway (and can't be re-clicked into duplicate work):
 *   busy    — DISABLED, spinner + a progress label ("Starting…", "Registering…"). Used the whole time
 *             between the click and mining actually becoming active (PoW → submit → on-chain wait).
 *   mining  — ENABLED red "Stop mining" toggle (clicking stops; it never re-triggers registration).
 *   idle    — ENABLED green "Start mining" (also the post-failure "tap to retry" resting state).
 * The #regBanner reuses the .hint-banner ⓘ styling and narrates the real registration stages. */
function setStartBtnBusy(label) {
  const b = $("btnMine");
  b.disabled = true;
  b.classList.remove("danger"); b.classList.add("primary");
  b.innerHTML = '<span class="spin"></span>' + escapeHtml(label || i18("mine.starting", "Starting…"));
}
function setStartBtnMining() {
  const b = $("btnMine");
  b.disabled = false;
  b.classList.remove("primary"); b.classList.add("danger");
  b.textContent = i18("btn.stopMine", "Stop mining");
}
function setStartBtnIdle(label) {
  const b = $("btnMine");
  b.disabled = false;
  b.classList.remove("danger"); b.classList.add("primary");
  b.textContent = label || i18("btn.startMining", "Start mining");
}
// Update the staged status banner. `html` is built only from our own constant strings plus
// escapeHtml()'d dynamic values, so innerHTML is safe here. kind: "ok" | "warn" | undefined (info).
function setRegBanner(html, kind) {
  const el = $("regBanner");
  if (!el) return;
  el.className = "hint-banner mt" + (kind ? " " + kind : "");
  $("regBannerMsg").innerHTML = html;
  show("regBanner", true);
}
function hideRegBannerSoon(ms = 6000) {
  setTimeout(() => { if (state.mining && !state.starting) show("regBanner", false); }, ms);
}
const REASSURE = ' <b>' + i18("reassure", "One-time setup — no need to click again.") + '</b>';

// Mining is confirmed live (registered on chain + heartbeating): flip the button to the Stop toggle.
function markMiningActive() {
  state.starting = false;
  setStartBtnMining();
  $("mineState").textContent = i18("mine.mining", "Mining");
}

// Registration could not be confirmed (relay rejected it, or the relay was unreachable). Stop the
// background loop so it can't spam re-registration, and leave the button ENABLED so the user can
// simply tap Start to retry — never stuck disabled.
function failStart(reason) {
  state.mining = false;
  state.starting = false;
  state.registering = false;
  if (state.powJob) state.powJob.cancelled = true;
  stopPollLoop();
  show("powWrap", false);
  setStartBtnIdle();
  $("mineState").textContent = i18("mine.idle", "Idle");
  setRegBanner(i18("reg.retry", "Registration didn't confirm — tap Start to retry.") +
    (reason ? ' <span class="faint">(' + escapeHtml(reason) + ')</span>' : ""), "warn");
}

// Decide whether to (re)broadcast a registration, and do it if needed. Called from the poll loop while
// mining and not yet registered. It NEVER blocks waiting for confirmation — the poll loop keeps ticking
// and notices `registered === 1` on its own, at which point heartbeating begins automatically. This is
// what makes mining a SINGLE click: registration, on-chain confirmation and heartbeats are all handled
// in the background without the user ever clicking "Start mining" a second time.
let _renewingLease = false;
async function maybeRenewLease(acc) {
  if (_renewingLease || state.registering || state.regSubmitted || !state.mining) return;
  const epochNow = state.latest != null ? Math.floor((state.latest + 8) / EPOCH_LENGTH) : null;
  const regEpoch = (acc && typeof acc.reg_epoch === "number") ? acc.reg_epoch : -1;
  if (epochNow == null || regEpoch < 0) return;
  if ((epochNow - regEpoch) < Math.floor(POSW_LEASE_EPOCHS * 0.8)) return;   // lease still healthy
  _renewingLease = true;
  try {
    const latest = await getLatestBlock();
    if (!latest || typeof latest.block_number !== "number") return;
    log("info", i18("log.leaseRenewing", "Presence lease expiring — renewing (fresh sequential proof)…"));
    const tx = await computeRegisterTx(latest.block_number + 8, null);       // quiet: no UI takeover
    const res = await submitTransaction(tx);
    if (res.data && res.data.result) log("ok", i18("log.leaseRenewed", "Presence lease renewed ✓"));
    else log("err", i18("log.leaseRejected", "Lease renewal rejected: {m}", {m: (res.data && (res.data.message || ""))}));
  } catch (e) { log("err", i18("log.leaseError", "Lease renewal error: {m}", {m: e.message})); }
  finally { _renewingLease = false; }
}

async function maybeRegister() {
  if (state.registering) return;                 // a PoW/submit is already in flight
  // If we already broadcast a registration that can still land, just keep waiting for it.
  if (state.regSubmitted) {
    if (state.latest != null && state.latest > state.regSubmitted.targetBlock) {
      log("err", i18("log.regExpired", "Registration tx expired before inclusion — re-registering automatically."));
      state.regSubmitted = null;                 // fall through and broadcast a fresh one
    } else {
      const away = state.latest != null ? Math.max(0, state.regSubmitted.targetBlock - state.latest) : null;
      showRegProgress(i18("reg.pending", "Registration in progress — waiting for it to be included in a block…"),
        away != null ? `~${away} block(s) until target ${state.regSubmitted.targetBlock}`
                     : `target block ${state.regSubmitted.targetBlock}`);
      setRegBanner(i18("reg.waiting", "Waiting for on-chain confirmation — this can take a few blocks") +
        (away != null ? " (~" + escapeHtml(String(away)) + " to go, target block " + escapeHtml(String(state.regSubmitted.targetBlock)) + ")" : "") +
        "…" + REASSURE);
      return;                                     // still pending; let the poll loop keep checking
    }
  }
  state.registering = true;
  let accepted = false, failed = null;
  try {
    accepted = await submitRegistration();
  } catch (e) {
    if (e.message !== "cancelled") { log("err", "Auto-register error: " + e.message); failed = e.message; }
  } finally {
    state.registering = false;
  }
  if (!state.mining) return;                      // user stopped/cancelled while we were working
  if (failed) { failStart(failed); return; }      // relay unreachable / error → re-enable for retry
  if (!accepted) failStart("the relay rejected the registration"); // hard rejection → retry, no spam
}

// Keep a prominent "registration in progress" indicator on screen (the powWrap widget with its
// indeterminate bar) for the WHOLE pending period — PoW, submit, and the wait for on-chain inclusion —
// so the user always sees that something is happening, not just a tiny "Registering…" stat. The Cancel
// button only aborts the PoW, so hide it once PoW is done (the user stops the wait via "Stop mining").
function showRegProgress(label, stats) {
  show("powWrap", true);
  $("powLabel").textContent = label;
  if (stats != null) $("powStats").textContent = stats;
  // The main Start/Mine button stays DISABLED during registration, so keep this Cancel button visible
  // the whole time as the escape hatch (it calls stopMining — aborting PoW and the on-chain wait).
  if ($("btnCancelPow")) show("btnCancelPow", true);
  if (state.mining) $("mineState").textContent = i18("mine.registering", "Registering…");
}

// Solve the one-time registration PoW and broadcast the register tx. Records state.regSubmitted on
// acceptance. Does NOT wait for on-chain confirmation (the poll loop owns that). Returns true if the
// tx was accepted into the mempool, false if the relay rejected it.
async function submitRegistration() {
  // need latest block for target_block
  const latest = await getLatestBlock();
  if (!latest || typeof latest.block_number !== "number") throw new Error("relay /get_latest_block unavailable");
  state.latest = latest.block_number;
  const targetBlock = latest.block_number + 8;  // headroom so the tx lands before its target block

  // compute the registration Proof of SEQUENTIAL Work (non-parallelizable ~1 s chain, replaces hashcash)
  setStartBtnBusy(i18("mine.registering", "Registering…"));
  setRegBanner(i18("reg.computing", "Computing the one-time registration proof (a few seconds)…") + REASSURE);
  showRegProgress(i18("reg.computingLabel", "Registering — computing sequential proof-of-work…"), i18("reg.starting", "starting…"));
  let tx;
  const t0 = Date.now();
  try {
    tx = await computeRegisterTx(targetBlock, (done, total) => {
      $("powStats").textContent =
        `${done.toLocaleString()} / ${total.toLocaleString()} sequential hashes · ${((Date.now() - t0) / 1000).toFixed(1)}s`;
    });
  } finally {
    show("powWrap", false);
  }
  log("ok", `Sequential PoW computed in ${((Date.now() - t0) / 1000).toFixed(1)}s (${POSW_T.toLocaleString()} hashes).`);
  setRegBanner(i18("reg.submitting", "Submitting registration to the network…") + REASSURE);
  log("info", `Submitting register tx ${tx.txid.slice(0, 16)}… (target_block ${targetBlock}).`);
  const res = await submitTransaction(tx);
  const m = res.data && (res.data.message || JSON.stringify(res.data));
  if (!(res.data && res.data.result)) {
    // surface the relay's exact reason (e.g. "Empty account") so the user isn't blind.
    log("err", i18("log.regRejected", "Register rejected by relay: {m}", {m}));
    if (/empty account/i.test(m || "")) {
      log("err", "This relay only accepts transactions from accounts that already exist on chain. " +
        "A brand-new address may need the relay operator to seed/allow it (node-side behavior).");
    }
    return false;
  }
  state.regSubmitted = { targetBlock, txid: tx.txid };
  log("ok", i18("log.regAccepted", "Register tx accepted into mempool: {m}", {m}));
  // Registration only takes effect once the tx is INCORPORATED into a block. We DON'T block here —
  // the poll loop watches for it and starts heartbeating automatically. No second click needed. Keep
  // the in-progress widget visible (the poll loop refreshes its "blocks remaining" each tick).
  log("info", i18("log.regWaiting", "Waiting for the registration to be included in a block — mining will start automatically then."));
  showRegProgress(i18("reg.submitted", "Registration submitted — waiting for it to be included in a block…"),
    `target block ${targetBlock}`);
  setRegBanner(i18("reg.waiting", "Waiting for on-chain confirmation — this can take a few blocks") + " (" +
    escapeHtml(String(targetBlock)) + ")…" + REASSURE);
  return true;
}

function nowSeconds() { return Math.floor(Date.now() / 1000); }


async function pollOnce() {
  try {
    const latest = await getLatestBlock();
    if (latest && typeof latest.block_number === "number") {
      state.latest = latest.block_number;
      setConn(true, latest.block_number);
    }
  } catch (e) { setConn(false); }

  // refresh dashboard
  try { await refreshDashboard(); } catch (e) { /* non-fatal */ }

  if (state.mining) {
    // Presence IS the PoSW lease — there is no separate heartbeat. Registration/renewal is fully AUTOMATIC
    // + self-healing: if we're not eligible (no recert, or the lease has lapsed), (re)register in the
    // background and wait. One ~1 s PoSW = a full lease of eligibility, locked phone or not. One click.
    let acc = null;
    try { acc = await getAccount(state.wallet.address); } catch (e) { /* relay hiccup */ }
    const epochNow = state.latest != null ? Math.floor((state.latest + 8) / EPOCH_LENGTH) : null;
    const regEpoch = (acc && typeof acc.reg_epoch === "number") ? acc.reg_epoch : -1;
    // OPEN-lane eligibility = a PoSW recert within POSW_LEASE_EPOCHS (the recert is the single presence signal).
    const leaseValid = epochNow != null && regEpoch >= 0 && (epochNow - regEpoch) < POSW_LEASE_EPOCHS;
    // AUTHORITATIVE presence: the node's open-registry membership (mining_status.registered_present) is ground
    // truth. If the node says we're NOT present — even when the local reg_epoch heuristic thinks the lease is
    // fine — we (re)register. Otherwise a state/index skew or a dropped registration tx leaves us stuck
    // "absent" forever (the local heuristic never triggers a retry). Fall back to the heuristic only when the
    // node's status isn't available yet, so a relay hiccup doesn't cause spurious re-registration.
    const msKnown = state.lastMs && typeof state.lastMs.registered_present === "boolean";
    const present = msKnown ? state.lastMs.registered_present : leaseValid;
    if (!acc || acc.registered !== 1 || !leaseValid || !present) {
      await maybeRegister();          // first registration, an expired lease, OR a node-vs-local presence mismatch
      return;                         // wait for the recert to land
    }
    // eligible: quietly renew the lease (a fresh ~1 s PoSW) once ~80% spent, so the identity never lapses.
    maybeRenewLease(acc).catch(() => {});
    const wasStarting = state.starting || $("btnMine").disabled; // were we still in the setup phase?
    if (state.regSubmitted) { state.regSubmitted = null; show("powWrap", false); log("ok", i18("log.regConfirmed", "Registration confirmed on chain ✓")); }
    markMiningActive();                       // flip the button to the working Stop/Mining toggle
    if (wasStarting) {
      setRegBanner(i18("reg.confirmed", "Registered ✓ — mining now."), "ok");
      hideRegBannerSoon();
    }
    // AUTO-BOND: compound a % of new mining rewards into bonded stake (once/epoch). `acc` is fresh here.
    try { await maybeAutoBond(acc, null); } catch (e) { /* best-effort; never break the loop */ }
  }
}

function startPollLoop() {
  stopPollLoop();
  const periodMs = Math.max(8000, Math.min(state.blockTime, 60) * 1000);
  state.pollTimer = setInterval(pollOnce, periodMs);
  // schedule a rough "next heartbeat" hint
}
function stopPollLoop() { if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; } }

// --- keep mining alive when the phone screen would otherwise lock ---------------------------------
// A backgrounded / locked mobile tab has its timers throttled or fully suspended, which silently
// stalls mining. The Screen Wake Lock keeps the screen ON while mining, so the phone does not
// auto-dim/auto-lock and the loop keeps running. (Honest limit: a hardware power-button lock still
// suspends any web page — no web page can mine with the screen fully off; this covers the common
// case of setting the phone down, and the visibilitychange handler makes mining resume INSTANTLY the
// moment the tab is foregrounded again, even if it was suspended.)
async function acquireWakeLock() {
  try {
    if (!("wakeLock" in navigator) || !state.mining || state.wakeLock) return;
    state.wakeLock = await navigator.wakeLock.request("screen");
    // the browser auto-releases the lock whenever the page is hidden; drop our handle so we re-request
    state.wakeLock.addEventListener("release", () => { state.wakeLock = null; });
    log("info", i18("log.wakeLock", "Screen kept awake so mining continues while the phone is idle."));
  } catch (e) { /* unsupported / denied — mining still runs while the tab is foregrounded */ }
}
async function releaseWakeLock() {
  const wl = state.wakeLock; state.wakeLock = null;
  try { if (wl) await wl.release(); } catch { /* already released */ }
}

// When the tab returns to the foreground (phone unlocked, app switched back), timers may have been
// throttled/suspended while hidden. Re-acquire the wake lock, restart the (possibly stalled) poll
// interval, and poll immediately so mining resumes at once instead of waiting out a dead interval.
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !state.mining) return;
    acquireWakeLock();
    startPollLoop();
    pollOnce().catch(() => {});
  });
}

// MOBILE TOOLTIPS: native title="" tooltips only appear on desktop HOVER. Touch devices have no hover, so
// the ⓘ info buttons did nothing on a phone. This shows the (already-localized) title text in a small
// popover on TAP, and hides it on the next tap/scroll. Desktop hover still works as before.
if (typeof document !== "undefined") {
  let _tipEl = null;
  const _mkTip = () => {
    if (_tipEl) return _tipEl;
    _tipEl = document.createElement("div");
    _tipEl.className = "taptip";
    _tipEl.setAttribute("role", "tooltip");
    _tipEl.style.cssText = "position:fixed;z-index:10000;max-width:min(320px,92vw);padding:10px 12px;" +
      "background:#0e141b;color:#e6edf3;border:1px solid #2a3746;border-radius:10px;font-size:13px;" +
      "line-height:1.45;box-shadow:0 8px 28px rgba(0,0,0,.55);display:none;pointer-events:none";
    document.body.appendChild(_tipEl);
    return _tipEl;
  };
  const _hideTip = () => { if (_tipEl) _tipEl.style.display = "none"; };
  document.addEventListener("click", (e) => {
    // Only intercept genuine info affordances (an ⓘ hint, or anything carrying a localized title).
    const trigger = e.target.closest(".hint, [data-i18n-title], [title]");
    const host = trigger && (trigger.hasAttribute("title") ? trigger : trigger.closest("[title]"));
    const text = host && host.getAttribute("title");
    if (!text) { _hideTip(); return; }
    // don't hijack real controls (links/buttons/inputs) that merely happen to have a title
    const tag = (trigger.tagName || "").toLowerCase();
    if (["a", "button", "input", "select", "textarea", "label"].includes(tag) && !trigger.matches(".hint, [data-i18n-title]")) return;
    if (_tipEl && _tipEl.style.display === "block" && _tipEl.textContent === text) { _hideTip(); return; } // toggle off
    const t = _mkTip();
    t.textContent = text;
    t.style.display = "block";
    const r = t.getBoundingClientRect();
    const rect = trigger.getBoundingClientRect();
    let left = Math.min(Math.max(8, rect.left + rect.width / 2 - r.width / 2), window.innerWidth - r.width - 8);
    let top = rect.bottom + 8;
    if (top + r.height > window.innerHeight - 8) top = Math.max(8, rect.top - r.height - 8);
    t.style.left = left + "px"; t.style.top = top + "px";
    e.preventDefault();
  }, true);
  window.addEventListener("scroll", _hideTip, true);
  window.addEventListener("resize", _hideTip);
}

// Single click does EVERYTHING: enter the active mining state immediately, then let the background poll
// loop register (if needed), wait for on-chain confirmation, and heartbeat each epoch — automatically.
// The user never has to click again after the registration tx lands.
async function startMining() {
  if (!state.wallet) return;
  if (state.starting || state.mining) return;   // idempotency guard: a start is already in flight
  state.mining = true;
  try { localStorage.setItem(LS_MINING, "1"); } catch (e) {}   // remember intent so a refresh auto-resumes
  state.starting = true;                          // button stays DISABLED until mining is live or fails
  state.autoBondBaseline = null; state.autoBondPending = null;   // only earnings AFTER this start auto-bond
  state.lastAutoBondEpoch = null;
  setStartBtnBusy(i18("mine.starting", "Starting…"));                   // disabled spinner button — can't be re-clicked
  setRegBanner(i18("reg.startup", "Starting up — checking your registration with the relay…") + REASSURE);
  $("mineState").textContent = i18("mine.starting", "Starting…");
  log("ok", i18("log.miningStarted", "Mining started — auto-registering / renewing your PoSW lease."));
  startPollLoop();
  acquireWakeLock();   // keep the screen awake so mining doesn't stall when the phone would auto-lock
  // kick off the first cycle immediately (registration / heartbeat / refresh) without blocking the UI
  pollOnce().catch((e) => log("err", i18("log.miningLoopError", "Mining loop error: {m}", {m: e.message})));
}

function stopMining() {
  state.mining = false;
  try { localStorage.removeItem(LS_MINING); } catch (e) {}   // explicit stop -> don't auto-resume on refresh
  state.starting = false;
  if (state.powJob) state.powJob.cancelled = true;   // abort an in-progress registration PoW
  state.registering = false;
  state.autoBondBaseline = null; state.autoBondPending = null;   // re-arm auto-bond baseline for the next start
  stopPollLoop();
  releaseWakeLock();                                   // let the screen sleep again once mining stops
  show("powWrap", false);
  show("regBanner", false);
  setStartBtnIdle();
  $("mineState").textContent = i18("mine.idle", "Idle");
  log("info", i18("log.miningStopped", "Mining stopped."));
}

/* ----------------------------------------------------------------------------------------------
 * Dashboard rendering
 * -------------------------------------------------------------------------------------------- */
/* ------------------------------------------------------------------------------------------------
 * A LITTLE TOUCH — a pile of coins that grows with your wallet, scaled to the richest wallet on the
 * network (from /get_richest). Pure SVG, no assets. Richest → full heap + crown; empty → no coins.
 * ---------------------------------------------------------------------------------------------- */
let _richestCache = { at: 0, value: 0n };
async function getRichest() {
  const now = Date.now();
  if (now - _richestCache.at < 15000 && _richestCache.value > 0n) return _richestCache.value;
  try {
    const r = await fetch(relayBase() + "/get_richest", { cache: "no-store" });
    const d = await r.json();
    _richestCache = { at: now, value: BigInt(d.richest || 0) };
  } catch (e) { /* keep last */ }
  return _richestCache.value;
}
const PILE_MAX_LEVELS = 7;
// MATERIAL TIERS: as your share of the richest wallet climbs, the pile ramps in quantity, then advances
// material — bronze → silver → gold → diamond — resetting to a small pile of the shinier metal each step.
const PILE_TIERS = [
  { id: "bronze",  g: ["#e8a866", "#cd7f32", "#8a5a1e"], base: "#5f3d14", hi: "#f6d6a8", stroke: "#7a4e1a", key: "pile.bronze",  en: "bronze" },
  { id: "silver",  g: ["#f7f9fb", "#cbd3db", "#8a94a0"], base: "#5f6874", hi: "#ffffff", stroke: "#98a2ae", key: "pile.silver",  en: "silver" },
  { id: "gold",    g: ["#ffe066", "#f5c542", "#d69a1e"], base: "#8a6a12", hi: "#fff3c4", stroke: "#a9781a", key: "pile.gold",    en: "gold" },
  { id: "diamond", g: ["#eafcff", "#a7e9f7", "#54c6ea"], base: "#2f7fa0", hi: "#ffffff", stroke: "#7fd3ec", key: "pile.diamond", en: "diamond" },
];
// map a 0..1 wealth ratio to {t: tier index, fill: 0..1 progress WITHIN that tier}. Bronze is the widest
// band (most miners); silver/gold/diamond are progressively rarer (only the near-richest reach them).
function _pileTier(ratio) {
  const bands = [0, 0.40, 0.65, 0.88, 1.0001];
  for (let t = 0; t < 4; t++) if (ratio < bands[t + 1]) return { t, fill: Math.max(0, Math.min(1, (ratio - bands[t]) / (bands[t + 1] - bands[t]))) };
  return { t: 3, fill: 1 };
}
function _coin(cx, cy, m) {   // a stacked coin rendered in material m (its gradient id is "pileMat")
  const rx = 18, ry = 7.5;
  return `<g><ellipse cx="${cx}" cy="${cy + 4}" rx="${rx}" ry="${ry}" fill="${m.base}"/>` +
    `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="url(#pileMat)" stroke="${m.stroke}" stroke-width="1"/>` +
    `<ellipse cx="${cx - rx * 0.28}" cy="${cy - ry * 0.35}" rx="${rx * 0.42}" ry="${ry * 0.4}" fill="${m.hi}" opacity="0.7"/></g>`;
}
function _gem(cx, cy, m) {    // a faceted diamond for the top tier
  const w = 14, h = 15;
  return `<g><path d="M${cx} ${cy + h * 0.62} L${cx - w} ${cy - h * 0.15} L${cx - w * 0.5} ${cy - h * 0.5} L${cx + w * 0.5} ${cy - h * 0.5} L${cx + w} ${cy - h * 0.15} Z" fill="url(#pileMat)" stroke="${m.stroke}" stroke-width="1"/>` +
    `<path d="M${cx - w} ${cy - h * 0.15} L${cx + w} ${cy - h * 0.15} L${cx} ${cy + h * 0.62} Z" fill="${m.stroke}" opacity="0.22"/>` +
    `<path d="M${cx - w * 0.5} ${cy - h * 0.5} L${cx} ${cy - h * 0.15} L${cx + w * 0.5} ${cy - h * 0.5} Z" fill="${m.hi}" opacity="0.65"/></g>`;
}
function renderCoinPile(totalRaw, richestRaw) {
  const svg = $("coinPile"), cap = $("coinPileCap"), wrap = $("coinPileWrap");
  if (!svg || !wrap) return;
  wrap.classList.remove("hidden");
  if (totalRaw <= 0n) {
    // nothing to draw yet — collapse the SVG so an empty/new wallet doesn't reserve the pile's height,
    // leaving just the one-line hint.
    svg.style.display = "none";
    cap.textContent = i18("pile.none", "No coins yet — start mining to grow your pile.");
    return;
  }
  svg.style.display = "";
  const rich = richestRaw > 0n ? richestRaw : 0n;
  const ratio = (totalRaw > 0n && rich > 0n) ? Math.min(1, Number((totalRaw * 1000000n) / rich) / 1000000) : (totalRaw > 0n ? 1 : 0);
  const isTop = totalRaw > 0n && totalRaw >= rich;                 // you're the richest (or tied / network unknown)
  const { t: tierIdx, fill } = _pileTier(ratio);
  const m = PILE_TIERS[tierIdx];
  const L = Math.max(1, Math.round(1 + fill * (PILE_MAX_LEVELS - 1)));   // 1..MAX rows WITHIN this material tier
  const defs = `<defs><linearGradient id="pileMat" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${m.g[0]}"/><stop offset="0.5" stop-color="${m.g[1]}"/><stop offset="1" stop-color="${m.g[2]}"/></linearGradient></defs>`;
  const draw = tierIdx === 3 ? _gem : _coin;                       // diamonds (gems) for the top tier, coins otherwise
  const baseY = 132, dy = 11, sx = 21, cx0 = 120;
  let body = "";
  for (let row = 0; row < L; row++) {                              // row 0 = bottom (widest)
    const n = L - row, y = baseY - row * dy, startX = cx0 - (n - 1) * sx / 2;
    for (let i = 0; i < n; i++) body += draw(startX + i * sx, y, m);
  }
  let crown = "";
  if (isTop) {
    const topY = baseY - (L - 1) * dy - 15;
    crown = `<g transform="translate(120 ${topY})"><path d="M-14 6 L-14 -6 L-7 2 L0 -11 L7 2 L14 -6 L14 6 Z" fill="#ffd24d" stroke="#c99a17" stroke-width="1"/>` +
      `<circle cx="-14" cy="-6" r="2.4" fill="#ffe066"/><circle cx="0" cy="-11" r="2.6" fill="#ffe066"/><circle cx="14" cy="-6" r="2.4" fill="#ffe066"/></g>`;
  }
  svg.innerHTML = defs + body + crown;
  const tierName = i18(m.key, m.en);
  if (isTop) cap.textContent = i18("pile.richest", "👑 Richest wallet on the network!") + " · " + tierName;
  else { const pct = ratio * 100; cap.textContent = `${pct >= 10 ? pct.toFixed(0) : pct.toFixed(1)}% ${i18("pile.ofRichest", "of the richest wallet on the network")} · ${tierName}`; }
}
async function updateCoinPile(totalRaw) {
  try { renderCoinPile(totalRaw, await getRichest()); } catch (e) { /* non-fatal cosmetic */ }
}

async function refreshDashboard() {
  if (!state.wallet) return;
  const addr = state.wallet.address;
  const [acc, ms] = await Promise.all([getAccount(addr), getMiningStatus(addr)]);
  state.lastMs = ms;   // cache the authoritative mining status (pollOnce reads registered_present from it)

  // wallet card + send/stake panels (balances are shared across tabs)
  if (acc) {
    const freeRaw = BigInt(acc.balance ?? 0);          // /get_account: balance == free/spendable
    const bondedRaw = BigInt(acc.bonded ?? 0);         //              bonded  == locked stake
    const bal = rawToNado(freeRaw), bonded = rawToNado(bondedRaw);
    $("walBalance").textContent = bal + " NADO";
    $("walBonded").textContent = bonded + " NADO";
    $("walTotal").textContent = rawToNado(freeRaw + bondedRaw) + " NADO";
    updateCoinPile(freeRaw + bondedRaw);               // a little touch: pile sized vs the richest wallet
    refreshDividend().catch(() => {});                 // presence dividend accrued off-L1 + auto-claim settled
    $("walReg").innerHTML = acc.registered === 1 ? `<span class="badge ok">${i18("badge.yes","yes")}</span>` : `<span class="badge no">${i18("badge.no","no")}</span>`;
    $("walFidelity").textContent = acc.fidelity ?? 0;
    $("sendAvail").textContent = bal + " NADO";
    $("stkAvail").textContent = bal + " NADO";
    $("stkBonded").textContent = bonded + " NADO";
  } else {
    $("walBalance").textContent = "0 NADO";
    $("walBonded").textContent = "0 NADO";
    $("walTotal").textContent = "0 NADO";
    updateCoinPile(0n);
    $("walReg").innerHTML = `<span class="badge idle">${i18("badge.new","new")}</span>`;
    $("walFidelity").textContent = "—";
    $("sendAvail").textContent = "0 NADO";
    $("stkAvail").textContent = "0 NADO";
    $("stkBonded").textContent = "0 NADO";
  }

  if (ms) {
    state.blockTime = ms.block_time || state.blockTime;
    $("walPresent").innerHTML = ms.registered_present ? `<span class="badge ok">${i18("badge.present","present")}</span>` : `<span class="badge no">${i18("badge.absent","absent")}</span>`;
    $("walBadge").className = "badge " + (ms.registered_present ? "ok" : (acc && acc.registered === 1 ? "no" : "idle"));
    $("walBadge").textContent = ms.registered_present ? "present" : (acc && acc.registered === 1 ? "absent" : "unregistered");

    $("mineEpoch").textContent = ms.epoch;
    $("mineEta").textContent = humanizeSeconds(ms.expected_seconds_between_wins);

    // How long a LOCKED phone keeps mining before you must reopen the app: the PoSW lease itself (one
    // recert = a full lease of eligibility, no relay/heartbeats). Reopen before this and it auto-renews.
    const regEpoch = (acc && typeof acc.reg_epoch === "number") ? acc.reg_epoch : -1;
    if (regEpoch >= 0) {
      const epochSecs = EPOCH_LENGTH * (ms.block_time || state.blockTime || 8);
      const leaseEnd = regEpoch + POSW_LEASE_EPOCHS;
      $("mineLocked").textContent = humanizeSeconds(Math.max(0, (leaseEnd - ms.epoch) * epochSecs));
    } else {
      $("mineLocked").textContent = "—";
    }

    renderLanes(ms);
    // visibility of the lanes card is owned by the tab system (it lives on the Wallet tab)
  } else {
    $("walPresent").textContent = "—";
  }
}

function renderLanes(ms) {
  const k = ms.k_open ?? 12, el = ms.epoch_length ?? EPOCH_LENGTH;
  const openPct = Math.round((k / el) * 100);
  const bondedPct = 100 - openPct;
  $("laneOpen").style.flex = `0 0 ${openPct}%`;
  $("laneBonded").style.flex = `0 0 ${bondedPct}%`;
  $("laneOpen").textContent = `${i18("lane.openBar", "OPEN")} ${openPct}%`;
  $("laneBonded").textContent = `${i18("lane.savingsBar", "SAVINGS")} ${bondedPct}%`;

  const myOpen = ms.my_open_weight ?? 0, totOpen = ms.total_open_weight ?? 0;
  const myBond = ms.my_bonded_shares ?? 0, totBond = ms.total_bonded_shares ?? 0;
  const sharePct = totOpen ? ((myOpen / totOpen) * 100).toFixed(1) : "0.0";

  // "Who's in each lane" participant counts + lane totals (same /mining_status fields).
  $("laneOpenCount").textContent = ms.open_registry_size ?? 0;
  $("laneBondedCount").textContent = ms.bonded_registry_size ?? 0;
  $("laneOpenWeight").textContent = totOpen;
  $("laneBondedShares").textContent = totBond;

  $("myShare").innerHTML =
    `${i18("myshare.weight", "Your open-lane weight:")} <b>${myOpen}</b> / ${totOpen} (${sharePct}% ${i18("myshare.ofFree", "of the free lane")}). ` +
    `${i18("myshare.openReg", "Open registry:")} ${ms.open_registry_size ?? 0} ${i18("lane.miners", "miners")} · ${i18("myshare.bondShares", "Savings shares:")} ${myBond}/${totBond} · ` +
    `${i18("myshare.bondReg", "Savings registry:")} ${ms.bonded_registry_size ?? 0}.`;

  // Dynamic "(you)" marker: you're in the FREE lane iff you have open-lane weight (registered + present),
  // and in the SAVINGS lane iff you hold savings shares. Both can be true at once — a stake ADDS the
  // savings lane, it does NOT remove you from the free lane. (Fixes the old static "(you)" on the legend.)
  const _youMark = " " + i18("lane.youMark", "(you)");
  $("laneOpenYou").textContent = myOpen > 0 ? _youMark : "";
  $("laneBondedYou").textContent = myBond > 0 ? _youMark : "";
}

function setConn(ok, tip) {
  const dot = $("connDot"), txt = $("connText");
  if (ok) { dot.className = "dot ok"; txt.textContent = i18("conn.online", "relay online"); if (tip != null) $("tipText").textContent = i18("conn.tip", "tip:") + " " + tip; }
  else { dot.className = "dot bad"; txt.textContent = i18("conn.offline", "relay offline"); }
}

/* ----------------------------------------------------------------------------------------------
 * Onboarding / wallet UI
 * -------------------------------------------------------------------------------------------- */
let pendingWallet = null;

function showWalletUI() {
  show("onboard", false);
  show("savePrompt", false);
  show("tabbar", true);
  $("walAddr").textContent = state.wallet.address;
  $("walPriv").textContent = state.wallet.privateKey;
  $("recvAddr").textContent = state.wallet.address;
  showTab(state.activeTab || "wallet");
  resumePendingPay(); // if a #pay link was opened before this wallet existed, prefill the Send now
}

function adoptWallet(w, { needsSavePrompt }) {
  if (needsSavePrompt) {
    pendingWallet = w;
    $("newPriv").textContent = w.privateKey;
    $("newAddr").textContent = w.address;
    $("ackSave").checked = false;
    $("btnConfirmSave").disabled = true;
    show("onboard", false);
    show("savePrompt", true);
  } else {
    state.wallet = w;
    persistWallet(w);
    showWalletUI();
    log("info", i18("log.walletLoaded", "Wallet loaded: {a}", {a: w.address}));
    refreshDashboard().catch(() => {});
  }
}

/* ----------------------------------------------------------------------------------------------
 * In-page self-test — proves byte-for-byte compatibility with the node's Python.
 * Vectors generated from the live repo (hashing.py / ops/*.py / Curve25519.py).
 * -------------------------------------------------------------------------------------------- */
const VEC = {
  hash_register_list: "8e90f8e4078206d119476611e907e6a829585d2f8393856ca461a26959067a65",
  checksum_string_size2: "3280",
  make_address_pub: "96381e3725f85cfe0ab8de17623957b4565ca9b04d37b903075f2723600c21e3",
  make_address_out: "ndo96381e3725f85cfe0ab8de17623957b4565ca9b04d75f7",
  hash_link_a_b: "d803f13f94cb4546f8f9d50368dfbb44ea46aa3db56fecfa2570a3ebf90f3a13",
  torture_canonical: "{\"a\":\"h\\u00e9llo \\\"x\\\"\\n\\t/end\",\"m\":[3,2,{\"big\":12345678901234567890,\"k\":true}],\"n\":null,\"unicode_key_\\u00fc\":\"\\u2603 snowman\",\"z\":1}",
  torture_hash: "69029840259d7c85d5c3e61f09abc352d0554c9b4320ef7d59bb6942647b840c",
  bigobj_canonical: "{\"amount\":99999999999999999999,\"x\":9007199254740993}",
  bigobj_hash: "8a09e2d0782c39dd1522f8a83c5338d2960d1b9710ec5c18e66d6cc20354de20",
  pow_address: "ndo96381e3725f85cfe0ab8de17623957b4565ca9b04d75f7",
  pow_nonce: 3324492,
  pow_target_str: "1766847064778384329583297500742918515827483896875618958121606201292619776",
  pow_hash_int_str: "17809026246977670515167752421706303018992963831983493225416033548923031",
  fixed_priv: "4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a", // 32-byte ML-DSA-44 seed
  register_tx: { sender: "ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84", recipient: "register", amount: 0, timestamp: 1700000000, data: "", nonce: "fixednonc", public_key: "1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38", target_block: 12345, chain_id: "nado-relaunch-1", pow_nonce: 2108331, fee: 0, txid: "71ba7ea5dff6b128de55651c24dda450ffaef5dfa853b8b75f710eeb28faef3e", signature: "42944e232fdc8c31c7e06bbfd08842e83c0ff738d64c48299b6b94e89cc2da644c1b741bbd39780affc8564473424e30be7ded23be2c4400991e23a9ee5e810e" },
  register_canonical: "{\"amount\":0,\"chain_id\":\"nado-relaunch-1\",\"data\":\"\",\"fee\":0,\"nonce\":\"fixednonc\",\"pow_nonce\":2108331,\"public_key\":\"1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38\",\"recipient\":\"register\",\"sender\":\"ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84\",\"target_block\":12345,\"timestamp\":1700000000}",
  heartbeat_tx: { sender: "ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84", recipient: "heartbeat", amount: 0, timestamp: 1700000000, data: "", nonce: "fixednonc", public_key: "1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38", target_block: 12345, chain_id: "nado-relaunch-1", epoch: 205, fee: 0, txid: "fef23a0cb2a032386271e84b585e786d1a9d6c182687fc8c3a8936a18454222a", signature: "1f525959cad52328829902cb5d703593b4c6df3fb948fecb4b1e0e3ad7276ee89e7e6c7b099ca04eb82f301de97e42c287879887f689528b6bfab2fbf9f1880b" },
  heartbeat_canonical: "{\"amount\":0,\"chain_id\":\"nado-relaunch-1\",\"data\":\"\",\"epoch\":205,\"fee\":0,\"nonce\":\"fixednonc\",\"public_key\":\"1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38\",\"recipient\":\"heartbeat\",\"sender\":\"ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84\",\"target_block\":12345,\"timestamp\":1700000000}",
  transfer_tx: { sender: "ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84", recipient: "ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29", amount: 123456, timestamp: 1700000000, data: "hello world", nonce: "fixednonc", public_key: "1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38", target_block: 12345, chain_id: "nado-relaunch-1", fee: 1000, txid: "857c54c68ccb67f5cba24c6503593a262ea22583d99553ab8143e94058b7a366", signature: "3fdd647501c3727378a01cd7ec1d0a09c318b8fe95ac3084e6f6848a49252263161e852c5e821869a78dec9ee5e4e03016e22eecf2bdc3b9654a201a723f450c" },
  transfer_canonical: "{\"amount\":123456,\"chain_id\":\"nado-relaunch-1\",\"data\":\"hello world\",\"fee\":1000,\"nonce\":\"fixednonc\",\"public_key\":\"1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38\",\"recipient\":\"ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29\",\"sender\":\"ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84\",\"target_block\":12345,\"timestamp\":1700000000}",
};

function bodyOf(tx) {
  const b = {};
  for (const k of Object.keys(tx)) if (k !== "txid" && k !== "signature") b[k] = tx[k];
  return b;
}

function runSelfTest() {
  const cases = [];
  const add = (name, got, want) => cases.push({ name, pass: got === want, got, want });

  add("blake2b_hash(['nado-register','ndoTEST',5])", blake2bHash(["nado-register", "ndoTEST", 5]), VEC.hash_register_list);
  add("blake2b_hash(addr_body, size=2)", blake2bHash("ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80", 2), VEC.checksum_string_size2);
  add("make_address(pubkey)", makeAddress(VEC.make_address_pub), VEC.make_address_out);
  add("blake2b_hash_link('a','b')", blake2bHashLink("a", "b"), VEC.hash_link_a_b);

  // canonical encoding torture (ensure_ascii + sorting + bool + BigInt > 2^53)
  const torture = { z: 1, a: 'héllo "x"\n\t/end', m: [3, 2, { k: true, big: 12345678901234567890n }], n: null, "unicode_key_ü": "☃ snowman" };
  add("canonical(torture obj)", canonicalize(torture), VEC.torture_canonical);
  add("blake2b_hash(torture obj)", blake2bHash(torture), VEC.torture_hash);
  const bigobj = { amount: 99999999999999999999n, x: 9007199254740993n };
  add("canonical(BigInt > 2^53)", canonicalize(bigobj), VEC.bigobj_canonical);
  add("blake2b_hash(BigInt obj)", blake2bHash(bigobj), VEC.bigobj_hash);

  // registration PoW
  add("registration PoW target", powTarget().toString(), VEC.pow_target_str);
  add("registration PoW hash(int)", powHashInt(VEC.pow_address, VEC.pow_nonce).toString(), VEC.pow_hash_int_str);
  add("registration PoW valid", String(powValid(VEC.pow_address, VEC.pow_nonce)), "true");

  // key derivation — ML-DSA-44 keygen is deterministic from the 32-byte seed.
  const kpA = keypairFromPriv(VEC.fixed_priv);
  const kpB = keypairFromPriv(VEC.fixed_priv);
  add("ML-DSA-44 keygen deterministic (same seed → same pubkey)", kpA.publicKey, kpB.publicKey);
  add("ML-DSA-44 public key is 1312 bytes", String(kpA.publicKey.length / 2), "1312");
  add("address derives from ML-DSA-44 pubkey", makeAddress(kpA.publicKey), kpA.address);

  // canonical bodies (full body incl. public_key) — exercises the canonicalize() primitive byte-for-byte
  add("register canonical body", canonicalize(bodyOf(VEC.register_tx)), VEC.register_canonical);
  add("heartbeat canonical body", canonicalize(bodyOf(VEC.heartbeat_tx)), VEC.heartbeat_canonical);
  add("transfer canonical body", canonicalize(bodyOf(VEC.transfer_tx)), VEC.transfer_canonical);

  // txids — PUBKEY-ONCE (#19): createTxid EXCLUDES public_key, so these must equal the node's
  // create_txid over the public_key-stripped body (vectors generated from ops/transaction_ops.py).
  add("register txid (public_key-excluded)", createTxid(bodyOf(VEC.register_tx)), VEC.register_tx.txid);
  add("heartbeat txid (public_key-excluded)", createTxid(bodyOf(VEC.heartbeat_tx)), VEC.heartbeat_tx.txid);
  add("transfer txid (public_key-excluded)", createTxid(bodyOf(VEC.transfer_tx)), VEC.transfer_tx.txid);

  // PUBKEY-ONCE invariant: the txid is IDENTICAL whether or not the body carries public_key (the node
  // recovers an omitted pubkey from chain, so a lean tx and a key-bearing tx share one identity).
  for (const [label, tx] of [["register", VEC.register_tx], ["heartbeat", VEC.heartbeat_tx], ["transfer", VEC.transfer_tx]]) {
    const noPub = bodyOf(tx); delete noPub.public_key;
    add(`${label} txid unchanged when public_key omitted`, createTxid(noPub), tx.txid);
  }

  // ML-DSA-44 signatures are RANDOMIZED — assert a sign→verify round-trip, not byte-equality.
  // Each tx is built from scratch (embedding the real 1312-byte pubkey) and self-verified.
  const w = keypairFromPriv(VEC.fixed_priv);
  const roundTrip = (label, tx) =>
    add(label, String(ml_dsa44.verify(hexToBytes(w.publicKey), hexToBytes(tx.txid), hexToBytes(tx.signature))), "true");
  roundTrip("register sign→verify round-trip", buildRegisterTx(w, 12345, 2108331, 1700000000));
  roundTrip("transfer sign→verify round-trip", buildTransferTx(w, VEC.transfer_tx.recipient, 123456n, 1000, 12345, "hello world", 1700000000));

  // PUBKEY-ONCE leanness: register (first tx) carries public_key; heartbeat omits it; transfer
  // carries it only when the sender's pubkey isn't established yet (includePubkey flag).
  const hasPub = (tx) => "public_key" in tx;
  add("register tx carries public_key (establishes it on-chain)", String(hasPub(buildRegisterTx(w, 12345, 2108331, 1700000000))), "true");
  add("transfer OMITS public_key when sender established", String(hasPub(buildTransferTx(w, VEC.transfer_tx.recipient, 123456n, 1000, 12345, "", 1700000000, false))), "false");
  add("transfer CARRIES public_key when not established", String(hasPub(buildTransferTx(w, VEC.transfer_tx.recipient, 123456n, 1000, 12345, "", 1700000000, true))), "true");
  add("pubkeyEstablished(registered acc)", String(pubkeyEstablished({ registered: 1 })), "true");
  add("pubkeyEstablished(acc with stored pubkey)", String(pubkeyEstablished({ public_key: "ab" })), "true");
  add("pubkeyEstablished(fresh/absent acc)", String(pubkeyEstablished(null) || pubkeyEstablished({ registered: 0 })), "false");

  return renderSelfTest(cases);
}

function renderSelfTest(cases) {
  const box = $("selftest");
  box.innerHTML = "";
  let pass = 0;
  for (const c of cases) {
    if (c.pass) pass++;
    const row = document.createElement("div");
    row.className = "case";
    row.innerHTML = `<span class="name">${escapeHtml(c.name)}</span>` +
      `<span class="res ${c.pass ? "pass" : "fail"}">${c.pass ? "PASS" : "FAIL"}</span>`;
    box.appendChild(row);
    if (!c.pass) {
      console.error("SELFTEST FAIL:", c.name, "\n got:", c.got, "\nwant:", c.want);
      const d = document.createElement("div");
      d.className = "small break faint";
      d.textContent = `got ${c.got} · want ${c.want}`;
      box.appendChild(d);
    }
  }
  const ok = pass === cases.length;
  const s = $("stSummary");
  s.className = "badge " + (ok ? "ok" : "no");
  s.textContent = `${pass}/${cases.length} ${ok ? "PASS" : "FAIL"}`;
  // Only surface the detailed (debug) self-test card when something FAILED; a clean pass stays
  // hidden so the wallet looks like a wallet, not a test harness. The "Run self-test" button
  // reveals it on demand.
  show("selftestCard", !ok);
  console.log(`[NADO self-test] ${pass}/${cases.length} ${ok ? "PASS" : "FAIL"}`);
  return ok;
}

/* ----------------------------------------------------------------------------------------------
 * Full wallet: download key, send, bond/unbond, receive QR, transaction history
 * -------------------------------------------------------------------------------------------- */

/* Download the key as a JSON file via a Blob + a temporary <a download> (explicit user request). */
function downloadKeyFile() {
  // Fall back to pendingWallet: on the "⚠ Save your private key" screen the freshly-generated key is
  // held in pendingWallet and is NOT yet state.wallet (that happens only on "Continue → store"). Without
  // this, a brand-new user who clicks Download on that very screen got a confusing "No wallet loaded."
  const w = state.wallet || pendingWallet;
  if (!w) { alert(i18("wallet.needFirst", "Create or import a wallet first — then you can download its key file.")); return; }
  const keyfile = {
    private_key: w.privateKey,            // the 32-byte ML-DSA-44 SEED (hex) — this IS the secret
    public_key: w.publicKey,
    address: w.address,
    note: "NADO ML-DSA-44 key — keep secret, no recovery",
  };
  const blob = new Blob([JSON.stringify(keyfile, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `nado-key-${w.address.slice(0, 8)}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1500);
  log("info", i18("log.keyDownloaded", "Downloaded key file for {a}…", {a: w.address.slice(0, 12)}));
}

/* Import a wallet from a key FILE (the mirror of downloadKeyFile): reads the JSON produced by
 * downloadKeyFile and adopts the wallet from its private_key. Also tolerates a plain-hex-only file. */
function importKeyFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const text = String(reader.result || "").trim();
      let priv;
      try {
        const obj = JSON.parse(text);
        priv = obj.private_key || obj.privateKey || obj.private || obj.seed;   // our keyfile schema
      } catch (e) {
        priv = text;                                   // fall back: a raw 64-hex seed in a bare file
      }
      if (!priv) throw new Error(i18("import.noKey", "no private key found in the file"));
      adoptWallet(keypairFromPriv(String(priv).trim()), { needsSavePrompt: false });
      log("info", i18("log.keyImported", "Imported key from file."));
    } catch (e) {
      alert(i18("import.fileFailed", "Import from file failed:") + " " + e.message);
    }
  };
  reader.onerror = () => alert(i18("import.readErr", "Could not read the file."));
  reader.readAsText(file);
}

/* The network fee is a tiny fixed protocol minimum (destroyed, not paid out). We hide the raw-unit
 * complexity entirely: the user never types a fee — we apply the relay's recommended fee (floored at
 * MIN_TX_FEE) automatically and just DISPLAY it in NADO. Returns the fee in RAW units. */
async function getRecommendedFee() {
  try {
    const r = await rpcJSON("/get_recommended_fee");
    const f = r.ok && r.data ? Number(r.data.fee) : NaN;
    return Math.max(Number.isFinite(f) ? Math.floor(f) : 0, MIN_TX_FEE);
  } catch (e) { return MIN_TX_FEE; }
}
async function currentFeeRaw() {
  if (state.recommendedFee == null) state.recommendedFee = await getRecommendedFee();
  return state.recommendedFee;
}
// Fill the read-only "Network fee: X NADO" labels on the Send + Stake tabs (no raw units shown).
async function updateFeeInfo() {
  const fee = await currentFeeRaw();
  const txt = rawToNado(fee) + " NADO (automatic)";
  for (const id of ["sendFeeInfo", "bondFeeInfo"]) { const el = $(id); if (el) el.textContent = txt; }
}

function setMsg(id, text, cls) {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.className = "small mt " + (cls ? "msg-" + cls : "faint");
}

async function nextTargetBlock() {
  const latest = await getLatestBlock();
  if (!latest || typeof latest.block_number !== "number") throw new Error("relay /get_latest_block unavailable");
  state.latest = latest.block_number;
  return latest.block_number + 8; // headroom so the tx lands before its target block
}

async function submitAndReport(tx, label, msgId) {
  const res = await submitTransaction(tx);
  const m = res.data && (res.data.message || JSON.stringify(res.data));
  if (res.data && res.data.result) {
    setMsg(msgId, `${label} accepted into mempool — txid ${tx.txid.slice(0, 16)}…`, "ok");
    log("ok", `${label} submitted ${tx.txid.slice(0, 16)}… (${m})`);
    refreshDashboard().catch(() => {});
    return true;
  }
  setMsg(msgId, `${label} rejected: ${m}`, "err");
  log("err", `${label} rejected: ${m}`);
  return false;
}

async function doSend() {
  const recipient = $("sendTo").value.trim();
  let resolvedOwner = null;
  if (!validateAddress(recipient)) {
    if (looksLikeAlias(recipient)) {
      setMsg("sendMsg", `Resolving alias "${recipient}"…`, null);
      resolvedOwner = await resolveAlias(recipient);
      if (!resolvedOwner) { setMsg("sendMsg", `Alias "${recipient}" is not registered.`, "err"); return; }
    } else {
      setMsg("sendMsg", i18("msg.badRecipient", "Invalid recipient — a 49-char ndo… address or a registered alias name."), "err"); return;
    }
  }
  let rawAmount;
  try { rawAmount = nadoToRaw($("sendAmount").value); } catch (e) { setMsg("sendMsg", i18("msg.badAmount", "Invalid amount."), "err"); return; }
  if (rawAmount <= 0n) { setMsg("sendMsg", i18("msg.amountPos", "Amount must be greater than zero."), "err"); return; }
  const fee = await currentFeeRaw();              // automatic network fee (no raw-units input)

  setMsg("sendMsg", i18("msg.checking", "Checking balance…"), null);
  const acc = await getAccount(state.wallet.address);
  const balance = BigInt((acc && acc.balance) || 0);
  if (rawAmount + BigInt(fee) > balance) {
    setMsg("sendMsg", `Insufficient balance: need ${rawToNado(rawAmount + BigInt(fee))} NADO (amount + fee), have ${rawToNado(balance)}.`, "err");
    return;
  }
  const toLine = resolvedOwner ? `${recipient}  (→ ${resolvedOwner})` : recipient;
  const selfWarn = (recipient === state.wallet.address || resolvedOwner === state.wallet.address) ? "\n\nWARNING: this is your OWN address." : "";
  if (!confirm(`Send ${rawToNado(rawAmount)} NADO\nto ${toLine}\nnetwork fee ${rawToNado(fee)} NADO${selfWarn}\n\nProceed?`)) {
    setMsg("sendMsg", i18("msg.cancelled", "Cancelled."), null); return;
  }
  const btn = $("btnSend"); btn.disabled = true;
  try {
    const targetBlock = await nextTargetBlock();
    // PUBKEY-ONCE: omit the 1312-byte public_key once the sender's pubkey is established on-chain.
    const tx = buildTransferTx(state.wallet, recipient, rawAmount, fee, targetBlock, "", nowSeconds(), !pubkeyEstablished(acc));
    if (await submitAndReport(tx, "Transfer", "sendMsg")) { addrBookAdd(recipient); $("sendAmount").value = ""; show("payBanner", false); }
  } catch (e) { setMsg("sendMsg", i18("msg.sendFailed", "Send failed:") + " " + e.message, "err"); }
  finally { btn.disabled = false; }
}

/* ALIAS management: register / transfer / unregister. An alias op is an ordinary signed tx whose
 * recipient is the reserved name "alias" and whose `data` carries {op, name, to?} (amount 0). The node
 * validates ownership + fee and updates the on-chain registry (see ops/alias_ops.py). */
async function doAliasOp(op) {
  const name = ($("aliasName").value || "").trim().toLowerCase();
  if (!looksLikeAlias(name)) {
    setMsg("aliasMsg", i18("alias.nameRule", "Name must be 3–32 chars, lowercase letters/digits/_/-, starting with a letter."), "err"); return;
  }
  let to = null;
  if (op === "transfer") {
    to = ($("aliasTo").value || "").trim();
    if (!validateAddress(to)) { setMsg("aliasMsg", i18("alias.xferTarget", "Transfer target must be a valid ndo… address."), "err"); return; }
  }
  const fee = op === "register" ? ALIAS_REGISTRATION_FEE : await currentFeeRaw();
  const acc = await getAccount(state.wallet.address);
  const balance = BigInt((acc && acc.balance) || 0);
  if (BigInt(fee) > balance) { setMsg("aliasMsg", `Insufficient balance for the ${rawToNado(fee)} NADO fee.`, "err"); return; }
  const data = op === "transfer" ? { op, name, to } : { op, name };
  // register defaults to SELF (the alias resolves to your own address); transfer points it elsewhere.
  const target = op === "transfer" ? "\n→ " + to : (op === "register" ? "\n→ your address (self)" : "");
  if (!confirm(`${op[0].toUpperCase() + op.slice(1)} alias "${name}"${target}\nnetwork fee ${rawToNado(fee)} NADO\n\nProceed?`)) {
    setMsg("aliasMsg", i18("msg.cancelled", "Cancelled."), null); return;
  }
  try {
    const targetBlock = await nextTargetBlock();
    const tx = buildTransferTx(state.wallet, "alias", 0n, fee, targetBlock, data, nowSeconds(), !pubkeyEstablished(acc));
    if (await submitAndReport(tx, "Alias " + op, "aliasMsg")) { $("aliasName").value = ""; $("aliasTo").value = ""; loadMyAliases(); }
  } catch (e) { setMsg("aliasMsg", i18("msg.aliasFailed", "Alias op failed:") + " " + e.message, "err"); }
}
async function loadMyAliases() {
  if (!state.wallet) return;
  try {
    const r = await fetch(relayBase() + "/get_aliases_of?address=" + encodeURIComponent(state.wallet.address), { cache: "no-store" });
    const d = await r.json();
    const names = (d && d.aliases) || [];
    $("myAliases").textContent = names.length ? names.join(", ") : "none yet";
  } catch { $("myAliases").textContent = "—"; }
}

/* bond/unbond move coins between spendable balance and bonded stake. They are ordinary signed txs
 * whose recipient is the reserved protocol name "bond" / "unbond" (see protocol.RESERVED_RECIPIENTS
 * and account_ops.reflect_transaction) — so we reuse buildTransferTx unchanged. */
async function doBond(kind) {
  const isBond = kind === "bond";
  const amtId = isBond ? "bondAmount" : "unbondAmount";
  const btn = $(isBond ? "btnBond" : "btnUnbond");
  let rawAmount;
  try { rawAmount = nadoToRaw($(amtId).value); } catch (e) { setMsg("stakeMsg", i18("msg.badAmount", "Invalid amount."), "err"); return; }
  if (rawAmount <= 0n) { setMsg("stakeMsg", i18("msg.amountPos", "Amount must be greater than zero."), "err"); return; }
  // bond pays the automatic network fee; unbond is FEE-EXEMPT on-chain (fee MUST be 0, else the node
  // rejects it) — so never attach a fee to an unbond.
  const fee = isBond ? await currentFeeRaw() : 0;

  const acc = await getAccount(state.wallet.address);
  const balance = BigInt((acc && acc.balance) || 0);
  const bonded = BigInt((acc && acc.bonded) || 0);
  if (isBond) {
    if (rawAmount + BigInt(fee) > balance) {
      setMsg("stakeMsg", `Insufficient spendable balance: need ${rawToNado(rawAmount + BigInt(fee))} NADO, have ${rawToNado(balance)}.`, "err"); return;
    }
  } else {
    if (rawAmount > bonded) { setMsg("stakeMsg", `Cannot unbond more than bonded (${rawToNado(bonded)} NADO).`, "err"); return; }
  }
  const verb = isBond ? "Bond" : "Unbond";
  const dir = isBond ? "spendable → bonded" : "bonded → spendable";
  const feeLine = isBond ? `\nnetwork fee ${rawToNado(fee)} NADO` : "\nno fee (unbonding is free)";
  const tail = isBond ? "" : `\n\nNote: bonded stake stays locked ${BOND_UNLOCK_DELAY} blocks after unbonding.`;
  if (!confirm(`${verb} ${rawToNado(rawAmount)} NADO (${dir})${feeLine}${tail}\n\nProceed?`)) {
    setMsg("stakeMsg", i18("msg.cancelled", "Cancelled."), null); return;
  }
  btn.disabled = true;
  try {
    const targetBlock = await nextTargetBlock();
    // PUBKEY-ONCE: omit the 1312-byte public_key once the sender's pubkey is established on-chain.
    const tx = buildTransferTx(state.wallet, kind, rawAmount, fee, targetBlock, "", nowSeconds(), !pubkeyEstablished(acc));
    if (await submitAndReport(tx, verb, "stakeMsg")) $(amtId).value = "";
  } catch (e) { setMsg("stakeMsg", verb + " " + i18("msg.failed", "failed:") + " " + e.message, "err"); }
  finally { btn.disabled = false; }
}

/* AUTO-BOND: compound a configured % of newly-mined spendable earnings straight into bonded stake.
 * Mirrors the node's core_loop.maybe_auto_bond EXACTLY: throttled to one bond per epoch, accrues
 * below the AUTO_BOND_MIN_RAW dust floor instead of emitting fee-dominated dust txs, and STOPS once
 * bonded >= BOND_CAP (extra bond buys no selection weight). `acc` is the just-fetched /get_account.
 * Called from the mining poll loop while mining + registered. Best-effort; never throws to the loop. */
function setAutoBondPct(pct) {
  pct = Math.max(0, Math.min(100, Math.floor(Number(pct) || 0)));
  state.autoBondPct = pct;
  // Always persist — INCLUDING 0 — so an explicit "off" is remembered and does NOT fall back to the
  // AUTO_BOND_DEFAULT_PCT (80%) default on the next load (which only applies when nothing was ever set).
  try { localStorage.setItem(LS_AUTOBOND, String(pct)); } catch (e) {}
  const note = $("autoBondNote");
  if (note) note.textContent = pct
    ? `${i18("autobond.onA", "On — saving")} ${pct}% ${i18("autobond.onB", "of new mining rewards each epoch.")}`
    : i18("autobond.off", "Off — mining rewards stay in your spendable balance.");
  // keep BOTH controls (Stake tab + mining card) in sync, without clobbering the one being typed into
  for (const id of ["autoBondPct", "autoBondPctMine"]) {
    const el = $(id);
    if (el && el !== document.activeElement) el.value = String(pct);
  }
  return pct;
}

async function maybeAutoBond(acc, ms) {
  const pct = state.autoBondPct;
  if (!pct || pct <= 0 || !state.mining || !state.wallet) return;
  if (!acc || acc.registered !== 1) return;               // only once we're actually mining on-chain
  const epoch = (ms && typeof ms.epoch === "number") ? ms.epoch
    : (state.latest != null ? Math.floor((state.latest + 8) / EPOCH_LENGTH) : null);
  if (epoch == null || epoch === state.lastAutoBondEpoch) return;  // one auto-bond per epoch

  const balance = BigInt(acc.balance ?? 0);
  const bonded = BigInt(acc.bonded ?? 0);
  // NEVER STACK auto-bonds: if the previous one hasn't landed yet (bonded not risen to its target), skip
  // this epoch. Otherwise the same rewards get bonded again while the first bond still sits in the mempool,
  // and the node rejects the overlap as "overspending balance" — exactly what happens when a phone locks
  // and then resumes several epochs later. Times out after 3 epochs so a dropped bond never wedges it.
  if (state.autoBondPending) {
    if (bonded >= state.autoBondPending.target || (epoch - state.autoBondPending.epoch) > 3) {
      state.autoBondPending = null;
      state.autoBondBaseline = balance;                 // reconcile to on-chain reality after it lands
    } else {
      return;
    }
  }
  if (state.autoBondBaseline == null) { state.autoBondBaseline = balance; return; }  // only future earnings
  if (bonded >= BOND_CAP) { state.autoBondBaseline = balance; return; }              // already at the cap
  const gain = balance - state.autoBondBaseline;
  if (gain <= 0n) { state.autoBondBaseline = balance; return; }                      // balance fell — rebaseline

  let toBond = (gain * BigInt(pct)) / 100n;
  const headroom = BOND_CAP - bonded;
  if (toBond > headroom) toBond = headroom;
  const fee = MIN_TX_FEE;
  if (toBond < AUTO_BOND_MIN_RAW || balance < toBond + BigInt(fee)) return;          // accrue (no rebaseline)

  try {
    const targetBlock = await nextTargetBlock();
    const tx = buildTransferTx(state.wallet, "bond", toBond, fee, targetBlock, "", nowSeconds(), !pubkeyEstablished(acc));
    const res = await submitTransaction(tx);
    if (res.data && res.data.result) {
      state.lastAutoBondEpoch = epoch;
      state.autoBondPending = { target: bonded + toBond, epoch };  // wait for THIS to land before the next
      state.autoBondBaseline = balance - toBond - BigInt(fee);   // optimistic; reconciled once it confirms
      log("ok", i18("log.autoBonded", "Auto-bonded {a} NADO ({p}% of {g} new rewards) → bonded lane.", {a: rawToNado(toBond), p: pct, g: rawToNado(gain)}));
      refreshDashboard().catch(() => {});
    } else {
      const m = res.data && (res.data.message || JSON.stringify(res.data));
      log("err", i18("log.autoBondRejected", "Auto-bond rejected: {m}", {m}));
    }
  } catch (e) { log("err", i18("log.autoBondError", "Auto-bond error: {m}", {m: e.message})); }
}

/* ---- Payment-request deep links: QR / shareable URL that prefills a Send on scan ---- */

let pendingPay = null; // a pay-request parsed from the URL hash before a wallet exists

// Deep link back to THIS hosted wallet: ${origin}${pathname}#pay?to=<addr>&amount=<NADO>.
// AMOUNT IS IN NADO (human-friendly), not raw units, and is OPTIONAL (omitted entirely for a bare
// receive code). Using origin+pathname makes the QR resolve wherever the node serves miner.html.
function payLink(addr, amountNado) {
  const params = new URLSearchParams({ to: addr });
  const a = (amountNado == null ? "" : String(amountNado)).trim();
  if (a) params.set("amount", a);
  return `${location.origin}${location.pathname}#pay?${params.toString()}`;
}

// Clipboard helper (secure-context navigator.clipboard, with an execCommand fallback for plain http).
async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed"; ta.style.top = "0"; ta.style.left = "0"; ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus(); ta.select(); ta.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch (e) { return false; }
}

let _toastTimer = null;
function toast(msg, kind = "info", ms = 5000) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.className = "toast " + kind;
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
}

// The amount (NADO) currently requested on the Receive tab, or "" if blank/malformed/non-positive.
function currentRecvAmount() {
  const raw = (($("recvAmount") && $("recvAmount").value) || "").trim();
  if (!raw) return "";
  try { return nadoToRaw(raw) > 0n ? raw : ""; } catch (e) { return ""; }
}

// Share the payment link via the native share sheet (mobile); else copy it to the clipboard.
async function sharePayLink() {
  if (!state.wallet) return;
  const link = payLink(state.wallet.address, currentRecvAmount());
  if (navigator.share) {
    try { await navigator.share({ title: "NADO payment request", text: "Pay me on NADO", url: link }); return; }
    catch (e) { if (e && e.name === "AbortError") return; /* dismissed sheet isn't an error; else fall through */ }
  }
  const btn = $("btnSharePay");
  const ok = await copyToClipboard(link);
  if (btn) { btn.textContent = ok ? i18("copy.copied", "Copied ✓") : i18("copy.select", "select & copy"); setTimeout(() => (btn.textContent = i18("btn.share", "Share")), ok ? 1200 : 1600); }
}

// Share the MINER itself (the site URL) — the growth loop: whoever opens it can mine + share it again.
async function shareMiner() {
  const url = shareUrl();
  if (navigator.share) {
    try { await navigator.share({ title: "NADO", text: i18("share.msg", "Mine NADO in your browser — no install, no signup. Open and go:"), url }); return; }
    catch (e) { if (e && e.name === "AbortError") return; }
  }
  const btn = $("btnShareMiner");
  const ok = await copyToClipboard(url);
  if (btn) { btn.textContent = ok ? i18("copy.copied", "Copied ✓") : i18("copy.select", "select & copy"); setTimeout(() => (btn.textContent = i18("btn.share", "Share")), ok ? 1200 : 1600); }
}

/* Receive: amount-aware QR + shareable payment link (degrades to the link text if QR is unavailable). */
// Generic QR renderer onto a <canvas>, with a graceful "generator unavailable" note fallback.
function _drawQR(canvas, note, text, targetPx) {
  if (!qrEncode || !canvas) { if (canvas) canvas.classList.add("hidden"); if (note) note.classList.remove("hidden"); return; }
  try {
    let m; try { m = qrEncode(text, "M"); } catch (_) { m = qrEncode(text, "L"); }  // retry at lower ECC if too long
    const n = m.length, quiet = 4, dim = n + quiet * 2;                              // mandatory quiet zone
    const px = Math.max(2, Math.floor((targetPx || 260) / dim)), size = dim * px;
    canvas.width = size; canvas.height = size; canvas.style.width = size + "px"; canvas.style.height = size + "px";
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, size, size); ctx.fillStyle = "#000000";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (m[r][c]) ctx.fillRect((c + quiet) * px, (r + quiet) * px, px, px);
    canvas.classList.remove("hidden"); if (note) note.classList.add("hidden");
  } catch (e) { canvas.classList.add("hidden"); if (note) note.classList.remove("hidden"); }
}

// The bare miner URL (no query/hash) — scanning it opens the miner so a newcomer can start mining in one tap.
function shareUrl() { return location.href.split("#")[0].split("?")[0]; }

function renderReceiveQR() {
  if (!state.wallet) return;
  const addr = state.wallet.address;
  $("recvAddr").textContent = addr;
  const link = payLink(addr, currentRecvAmount());
  $("recvPayLink").textContent = link;
  _drawQR($("recvQR"), $("recvQRNote"), link, 260);            // payment-request QR
  // SHARE QR: the miner's own URL, so anyone who scans opens NADO and can start mining. Growth = the link.
  const su = shareUrl();
  if ($("shareLink")) $("shareLink").textContent = su;
  _drawQR($("shareQR"), $("shareQRNote"), su, 220);
}

/* Parse + consume a #pay?to=...&amount=... deep link. SECURITY: never auto-submits — only prefills. */
function parsePayHash() {
  const h = location.hash || "";
  if (!h.startsWith("#pay?")) return null;
  const params = new URLSearchParams(h.slice(5)); // robustly parse the query part after "#pay?"
  return { to: (params.get("to") || "").trim(), amount: (params.get("amount") || "").trim() };
}

function applyPayRequest(req) {
  if (!state.wallet) return;
  showTab("send");
  const toEl = $("sendTo");
  toEl.value = req.to;
  toEl.dispatchEvent(new Event("input"));   // refresh the live valid/invalid hint
  let amtOk = false;
  if (req.amount) {
    try { if (nadoToRaw(req.amount) > 0n) { $("sendAmount").value = req.amount; amtOk = true; } }
    catch (e) { /* malformed/negative amount -> prefill recipient only */ }
  }
  show("payBanner", true);
  $("payBannerMsg").textContent = amtOk
    ? i18("payBanner.msg", "Payment request loaded — review and confirm.")
    : i18("payBanner.enterAmt", "Payment request loaded — enter an amount, then review and confirm.");
  try { $("sendCard").scrollIntoView({ behavior: "smooth", block: "start" }); } catch (e) {}
  setTimeout(() => { const f = amtOk ? $("btnSend") : $("sendAmount"); if (f) f.focus(); }, 350);
  toast("Payment request loaded — review and confirm.", "info");
  log("info", `Payment request loaded: pay ${req.to.slice(0, 12)}…${amtOk ? " " + req.amount + " NADO" : ""}`);
}

function consumePayRequest() {
  const req = parsePayHash();
  if (!req) return;
  // clear the hash so a refresh won't re-trigger the prefill (and the URL bar isn't left dirty)
  try { history.replaceState(null, "", location.pathname); } catch (e) {}
  if (!validateAddress(req.to)) {
    log("err", "Payment link ignored — invalid recipient address.");
    toast("Payment link ignored — the recipient address is invalid.", "err");
    return;
  }
  if (state.wallet) {
    applyPayRequest(req);
  } else {
    pendingPay = req;                       // stash; resume after the wallet is created/imported
    try { sessionStorage.setItem(LS_PENDING_PAY, JSON.stringify(req)); } catch (e) {}
    toast("Payment request pending — set up a wallet, then it will prefill a Send.", "info", 7000);
    log("info", i18("log.payDetected", "Payment request detected — create or import a wallet to continue."));
  }
}

// After a wallet becomes active (created / imported / loaded), resume any stashed pay-request.
function resumePendingPay() {
  if (!state.wallet) return;
  let req = pendingPay;
  if (!req) { try { const s = sessionStorage.getItem(LS_PENDING_PAY); if (s) req = JSON.parse(s); } catch (e) {} }
  if (!req) return;
  pendingPay = null;
  try { sessionStorage.removeItem(LS_PENDING_PAY); } catch (e) {}
  if (validateAddress(req.to)) applyPayRequest(req);
}

/* Transaction history: classify each tx relative to the wallet and show a signed amount. */
const HIST_ICON = { send: "↑", receive: "↓", bond: "🔒", unbond: "🔓", register: "✦", heartbeat: "♥",
  dividend: "💰", bridge: "🌉", swap: "🔀", blob: "▧", protocol: "•" };
function histClassify(tx, addr) {
  // `amt` (raw) overrides tx.amount for reserved txs whose value is carried in `data`, not the amount field —
  // notably the presence DIVIDEND collection (dividend_withdraw), which otherwise shows as "0 NADO".
  const r = tx.recipient;
  const d = (tx.data && typeof tx.data === "object") ? tx.data : {};
  if (r === "register") return { type: "register", sign: 0, cp: i18("hist.cpReg", "open-lane registration") };
  if (r === "heartbeat") return { type: "heartbeat", sign: 0, cp: i18("hist.cpHb", "open-lane heartbeat") };
  if (r === "bond") return { type: "bond", sign: -1, cp: i18("hist.cpBond", "→ savings") };
  if (r === "unbond") return { type: "unbond", sign: 0, cp: i18("hist.cpUnbond", "savings unbond requested") };
  if (r === "withdraw") return { type: "unbond", sign: 1, cp: i18("hist.cpWithdraw", "← savings (matured)"), amt: BigInt(d.amount || 0) };
  if (r === "dividend_withdraw") return { type: "dividend", sign: 1, cp: i18("hist.cpDividend", "presence dividend"), amt: BigInt(d.amount || 0) };
  if (r === "bridge") return { type: "bridge", sign: -1, cp: i18("hist.cpBridge", "→ bridge escrow") };
  if (r === "bridge_withdraw") return { type: "bridge", sign: 1, cp: i18("hist.cpBridgeExit", "← bridge exit"), amt: BigInt(d.amount || 0) };
  if (r === "htlc_lock") return { type: "swap", sign: -1, cp: i18("hist.cpSwapLock", "→ atomic-swap lock") };
  if (r === "htlc_claim") return { type: "swap", sign: 0, cp: i18("hist.cpSwapClaim", "atomic-swap claim") };
  if (r === "htlc_refund") return { type: "swap", sign: 0, cp: i18("hist.cpSwapRefund", "atomic-swap refund") };
  if (r === "blob") return { type: "blob", sign: 0, cp: (d.op === "collect_dividend") ? i18("hist.cpDivCollect", "dividend collect (requested)") : i18("hist.cpBlob", "data blob") };
  if (["attest", "commit", "reveal", "settle", "slash", "alias"].includes(r)) return { type: "protocol", sign: 0, cp: i18("hist.cp." + r, r) };
  if (tx.sender === addr) return { type: "send", sign: -1, cp: i18("hist.to", "to"), cpAddr: r };
  return { type: "receive", sign: 1, cp: i18("hist.from", "from"), cpAddr: tx.sender };
}

/* Counterparty cell for a history row: link the address into the Explore tab (clickable → account view);
 * plain text for aliases/non-addresses or self-txs (register/heartbeat/bond/unbond). */
function histCp(info) {
  if (info.cpAddr && validateAddress(info.cpAddr))
    return escapeHtml(info.cp) + " " + exLink("a", info.cpAddr, exShort(info.cpAddr, 14));
  if (info.cpAddr) return escapeHtml(info.cp + " " + info.cpAddr);
  return escapeHtml(info.cp);
}
async function loadHistory() {
  if (!state.wallet) return;
  const box = $("history");
  box.innerHTML = `<div class="empty">${i18("hist.loading", "Loading…")}</div>`;
  const addr = state.wallet.address;
  let txs = [];
  try {
    const r = await rpcJSON("/get_transactions_of_account?address=" + encodeURIComponent(addr) + "&min_block=0");
    if (r.ok && r.data && Array.isArray(r.data.transactions)) txs = r.data.transactions;
  } catch (e) { box.innerHTML = `<div class="empty">${i18("hist.loadErr", "Could not load history:")} ` + escapeHtml(e.message) + '</div>'; return; }

  if (!txs.length) { box.innerHTML = `<div class="empty">${i18("hist.empty", "No transactions yet.")}</div>`; return; }
  txs.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)); // newest first

  box.innerHTML = "";
  for (const tx of txs) {
    const info = histClassify(tx, addr);
    const rawAmt = (info.amt != null) ? info.amt : BigInt(tx.amount || 0);
    const signed = info.sign === 0 ? "—"
      : (info.sign < 0 ? "-" : "+") + rawToNado(rawAmt) + " NADO";
    const amtCls = info.sign === 0 ? "zero" : (info.sign < 0 ? "neg" : "pos");
    const when = tx.timestamp ? new Date(tx.timestamp * 1000).toLocaleString() : "—";
    const feeStr = (tx.fee != null) ? ` · ${i18("hist.fee", "fee")} ${tx.fee}` : "";
    const row = document.createElement("div");
    row.className = "htx";
    row.title = "txid " + (tx.txid || "");
    row.innerHTML =
      `<div class="ic">${HIST_ICON[info.type] || "•"}</div>` +
      `<div class="mid"><div class="tp">${i18("hist." + info.type, info.type)}</div>` +
      `<div class="cp">${histCp(info)}</div>` +
      `<div class="meta">${escapeHtml(when)}${escapeHtml(feeStr)}</div></div>` +
      `<div class="amt ${amtCls}">${escapeHtml(signed)}</div>`;
    box.appendChild(row);
  }
}

/* Tabbed navigation: the tab bar owns top-level card visibility once a wallet exists. */
/* ------------------------------------------------------------------------------------------------
 * EXPLORE tab — the block explorer, folded into the wallet. Reads this node's public JSON API and
 * renders blocks / accounts / transactions. Reuses relayBase(), $, resolveAlias, rawToNado.
 * ---------------------------------------------------------------------------------------------- */
const EX_RESERVED = new Set(["bond", "unbond", "withdraw", "register", "heartbeat", "slash", "attest", "commit", "reveal", "alias"]);
async function exGetJSON(path) {
  const r = await fetch(relayBase() + path, { cache: "no-store" });
  const t = await r.text();
  let d; try { d = JSON.parse(t); } catch { d = null; }
  if (!r.ok || d == null) throw new Error((d && d.message) || ("HTTP " + r.status));
  return d;
}
function exNado(raw) { try { return rawToNado(BigInt(raw)) + " NADO"; } catch { return String(raw); } }
function exTime(ts) { if (ts == null) return "—"; return new Date(ts * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC"); }
function exEsc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function exShort(h, n = 12) { return h && h.length > n * 2 ? h.slice(0, n) + "…" + h.slice(-6) : (h ?? "—"); }
// data attrs + event delegation (miner.js is an ES module, so inline onclick can't see exOpen)
function exLink(kind, val, label) { return `<a class="ex-link" data-exk="${kind}" data-exv="${exEsc(val)}">${exEsc(label ?? val)}</a>`; }
function exReservedOrAddr(r) { return EX_RESERVED.has(r) ? `<span class="badge">${exEsc(r)}</span>` : exLink("a", r, exShort(r, 8)); }
// map each explore label to an i18n key (reusing existing keys where they fit), so exStat/exKV localize
const EX_LABELS = {
  "Address":"lbl.address","Amount":"ex.amount","Balance":"ex.balance","Block time":"ex.blockTime","Bonded":"lbl.bonded",
  "Circulating":"ex.circulating","Cumulative fees":"ex.cumFees","Cumulative weight":"ex.cumWeight","Data":"ex.data",
  "Epoch":"ex.epoch","Fee":"ex.fee","Fees burned":"ex.feesBurned","Fidelity":"lbl.fidelity","Finalized":"ex.finalized",
  "From":"ex.from","Hash":"ex.hash","Latest hash":"ex.latestHash","Next block":"ex.nextBlock","OPEN lane":"lanes.open",
  "BONDED lane":"lanes.bonded","Parent":"ex.parent","Produced":"ex.produced","Producer":"ex.producer",
  "Registered":"lbl.registered","Reward":"ex.reward","Target block":"ex.targetBlock","Time":"ex.time",
  "Timestamp":"ex.timestamp","Tip height":"ex.tipHeight","To":"ex.to","Total supply":"ex.totalSupply",
  "Transactions":"ex.transactions","Treasury":"ex.treasury","Txid":"ex.txid",
};
function exT(s) { const k = EX_LABELS[s]; return k ? i18(k, s) : s; }
function exKV(pairs) { return `<div class="ex-kv">${pairs.filter(Boolean).map(([k, v]) => `<div class="k">${exEsc(exT(k))}</div><div class="v">${v}</div>`).join("")}</div>`; }
function exStat(rows) { return rows.map(([k, v]) => `<div class="ex-stat"><span class="k">${exT(k)}</span><span class="n">${v}</span></div>`).join(""); }

async function exLoadOverview() {
  try {
    const [st, sup] = await Promise.all([exGetJSON("/status"), exGetJSON("/get_supply")]);
    $("exNetwork").innerHTML = exStat([
      ["Tip height", exLink("b", st.latest_block_hash, "#" + (sup.block_number ?? "?"))],
      ["Latest hash", `<span class="mono">${exShort(st.latest_block_hash)}</span>`],
      ["Finalized", "#" + st.finalized_height + (st.ffg_finalized != null ? `  ·  FFG #${st.ffg_finalized}` : "")],
      ["Total supply", exNado(sup.total_supply)],
      ["Circulating", exNado(sup.circulating)],
      ["Treasury", exNado(sup.treasury)],
      ["Fees burned", exNado(sup.fees)],
    ]);
  } catch (e) { $("exNetwork").innerHTML = `<div class="warnbox danger">${i18("ex.nodeUnreachable", "Node unreachable:")} ${exEsc(e.message)}</div>`; }
  try {
    const ms = await exGetJSON("/mining_status");
    $("exMining").innerHTML = exStat([
      ["Epoch", ms.epoch + `  (len ${ms.epoch_length})`],
      ["Next block", "#" + ms.next_block],
      ["Block time", ms.block_time + "s"],
      ["OPEN lane", `${ms.open_registry_size} miners · ${ms.k_open}/${ms.epoch_length} slots`],
      ["BONDED lane", `${ms.bonded_registry_size} miners · ${ms.total_bonded_shares} shares`],
    ]);
  } catch { $("exMining").innerHTML = `<div class="faint small">${i18("ex.miningUnavail", "mining status unavailable")}</div>`; }
}
async function exLoadRecent() {
  try {
    const tip = await exGetJSON("/get_latest_block");
    const nums = []; for (let n = tip.block_number, lo = Math.max(0, n - 11); n >= lo; n--) nums.push(n);
    const blocks = await Promise.all(nums.map((n) => exGetJSON("/get_block_number?number=" + n).catch(() => null)));
    $("exRecent").innerHTML = blocks.filter(Boolean).map(exBlockRow).join("") || `<div class="faint small">${i18("ex.noBlocks", "no blocks")}</div>`;
  } catch { $("exRecent").innerHTML = `<div class="faint small">${i18("ex.unavail", "unavailable")}</div>`; }
}
function exBlockRow(b) {
  const txs = (b.block_transactions || []).length;
  return `<div class="ex-row"><div>${exLink("b", b.block_hash, "#" + b.block_number)}
    <span class="faint small">· ${txs} tx${txs === 1 ? "" : "s"}</span><div class="faint small">${exTime(b.block_timestamp)}</div></div>
    <div style="text-align:right"><span class="mono faint small">${exShort(b.block_hash, 8)}</span>
    <div class="small">by ${exLink("a", b.block_creator, exShort(b.block_creator, 8))}</div></div></div>`;
}
function exTxRow(t) {
  return `<div class="ex-row"><div>${t.txid ? exLink("tx", t.txid, exShort(t.txid, 10)) : `<span class="mono">${exEsc(t.recipient)}</span>`}
    <div class="small">${exLink("a", t.sender, exShort(t.sender, 8))} → ${exReservedOrAddr(t.recipient)}</div>
    <div class="faint small">${exTime(t.timestamp)}</div></div>
    <div style="text-align:right" class="mono">${exNado(t.amount)}<div class="faint small">fee ${exNado(t.fee || 0)}</div></div></div>`;
}
function exRenderBlock(b) {
  const txs = b.block_transactions || [];
  return `<h2>${i18("ex.block","Block")} #${b.block_number}</h2>${exKV([
    ["Hash", `<span class="mono">${exEsc(b.block_hash)}</span>`],
    ["Parent", exLink("b", b.parent_hash, exShort(b.parent_hash))],
    ["Producer", exLink("a", b.block_creator)],
    ["Time", exTime(b.block_timestamp)],
    ["Reward", exNado(b.block_reward)],
    ["Cumulative fees", exNado(b.cumulative_fees)],
    ["Cumulative weight", String(b.cumulative_weight)],
    ["Transactions", String(txs.length)],
  ])}${txs.length ? `<div class="ex-rows mt">${txs.map(exTxRow).join("")}</div>` : `<div class="faint small mt">${i18("ex.noTxs", "no transactions")}</div>`}`;
}
function exRenderAccount(a) {
  return `<h2>${i18("ex.account","Account")}</h2>${exKV([
    ["Address", `<span class="mono">${exEsc(a.address)}</span>`],
    ["Balance", exNado(a.balance)],
    ["Bonded", exNado(a.bonded)],
    ["Produced", exNado(a.produced)],
    ["Registered", a.registered ? i18("ex.regYes", "yes (OPEN-lane miner)") : i18("badge.no", "no")],
    ["Fidelity", String(a.fidelity ?? 0) + " / 1000"],
  ])}<div class="row mt"><button class="accent" id="exLoadTxs">${i18("ex.showTxs", "Show transactions")}</button></div><div id="exAcctTxs" class="ex-rows mt"></div>`;
}
function exRenderTx(t) {
  return `<h2>${i18("ex.transaction", "Transaction")}</h2>${exKV([
    ["Txid", `<span class="mono">${exEsc(t.txid || "—")}</span>`],
    ["From", exLink("a", t.sender)],
    ["To", exReservedOrAddr(t.recipient)],
    ["Amount", exNado(t.amount)],
    ["Fee", exNado(t.fee || 0)],
    ["Target block", t.target_block != null ? exLink("b", String(t.target_block), "#" + t.target_block) : "—"],
    ["Timestamp", exTime(t.timestamp)],
    t.data ? ["Data", `<span class="mono">${exEsc(typeof t.data === "string" ? t.data.slice(0, 200) : JSON.stringify(t.data))}</span>`] : null,
  ])}`;
}
function exShowResult(html) { const r = $("exResult"); r.innerHTML = html; r.classList.remove("hidden"); }
async function exOpen(kind, val) {
  try {
    if (kind === "a") {
      exShowResult(exRenderAccount(await exGetJSON("/get_account?address=" + encodeURIComponent(val))));
      const btn = $("exLoadTxs"); if (btn) btn.onclick = async () => {
        const box = $("exAcctTxs"); box.innerHTML = `<div class="faint small">${i18("ex.loading", "loading…")}</div>`;
        try { const d = await exGetJSON("/get_transactions_of_account?address=" + encodeURIComponent(val) + "&min_block=0");
          const txs = d.transactions || []; box.innerHTML = txs.length ? txs.map(exTxRow).join("") : `<div class="faint small">${i18("ex.noTxs", "no transactions")}</div>`;
        } catch (e) { box.innerHTML = `<div class="warnbox danger">${exEsc(e.message)}</div>`; }
      };
    } else if (kind === "b") {
      let b = null;
      if (/^\d+$/.test(val)) b = await exGetJSON("/get_block_number?number=" + val);
      else { try { b = await exGetJSON("/get_block?hash=" + encodeURIComponent(val)); } catch { b = null; }
        if (!b || !b.block_hash) { try { const t = await exGetJSON("/get_transaction?txid=" + encodeURIComponent(val)); if (t) { exShowResult(exRenderTx(t)); return; } } catch {} } }
      if (!b || b === false || !b.block_hash) throw new Error("not found");
      exShowResult(exRenderBlock(b));
    } else if (kind === "tx") {
      const t = await exGetJSON("/get_transaction?txid=" + encodeURIComponent(val));
      if (!t || t === false) throw new Error("not found");
      exShowResult(exRenderTx(t));
    }
  } catch (e) { exShowResult(`<div class="warnbox danger">Not found: ${exEsc(e.message)}</div>`); }
}
async function exSearch() {
  const q = $("exQ").value.trim();
  $("exSearchErr").classList.add("hidden");
  if (!q) return;
  if (/^\d+$/.test(q)) return exOpen("b", q);
  if (/^ndo[0-9a-f]{46}$/i.test(q)) return exOpen("a", q);
  if (/^[0-9a-f]{64}$/i.test(q)) return exOpen("b", q);       // 64-hex: block, falling back to tx
  if (looksLikeAlias(q)) {                                    // an alias -> its owner account
    const owner = await resolveAlias(q);
    if (owner) return exOpen("a", owner);
    $("exSearchErr").textContent = `Alias "${q}" is not registered.`; $("exSearchErr").classList.remove("hidden"); return;
  }
  $("exSearchErr").textContent = i18("ex.searchErr", "Unrecognized — an ndo… address, an alias, a block number, or a 64-hex hash/txid.");
  $("exSearchErr").classList.remove("hidden");
}

/* Rich list (leaderboard): the top wallets by total holdings, from /get_rich_list. Each row links into
 * the Explore tab; the caller's own wallet is highlighted if it's on the list. */
function richRow(e, rank, isMine) {
  const total = rawToNado(BigInt(e.total || 0));
  const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : "#" + rank;
  const you = isMine ? ` <span class="pill">${i18("rich.you", "you")}</span>` : "";
  return `<div class="ex-row${isMine ? " mine" : ""}">
    <div><span class="mono">${medal}</span> ${exLink("a", e.address, exShort(e.address, 12))}${you}</div>
    <div style="text-align:right"><b>${total}</b> NADO</div></div>`;
}

async function loadRichList() {
  const box = $("richList");
  if (!box) return;
  box.innerHTML = `<div class="faint small">${i18("rich.loading", "loading…")}</div>`;
  try {
    const r = await fetch(relayBase() + "/get_rich_list?n=25", { cache: "no-store" });
    const d = await r.json();
    const list = (d && d.rich_list) || [];
    if (!list.length) { box.innerHTML = `<div class="faint small">${i18("rich.empty", "no accounts yet")}</div>`; return; }
    const mine = state.wallet && state.wallet.address;
    box.innerHTML = list.map((e, i) => richRow(e, i + 1, e.address === mine)).join("");
  } catch (e) {
    box.innerHTML = `<div class="faint small">${i18("rich.err", "unavailable")}</div>`;
  }
}

/* ============================ STATS TAB — inline SVG charts (no external lib) ============================ */
const _SVGNS = "http://www.w3.org/2000/svg";
function _svgClear(id) { const s = $(id); if (s) s.innerHTML = ""; return s; }
function _mk(tag, attrs, text) {
  const el = document.createElementNS(_SVGNS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  if (text != null) el.textContent = text;
  return el;
}
function _nadoNum(raw) { try { return Number(BigInt(raw || 0)) / 1e10; } catch { return 0; } }
const _CACC = "#3aa0ff", _CGRID = "#1c2530", _CMUT = "#7c8b9a", _CGOLD = "#f5c542", _CGRN = "#5ad19a";

function barChart(id, values, labels, opts) {
  opts = opts || {}; const svg = _svgClear(id); if (!svg) return;
  const W = 320, H = 120, padL = 32, padB = 16, padT = 8, padR = 6;
  const n = values.length;
  if (!n) { svg.appendChild(_mk("text", { x: W / 2, y: H / 2, fill: _CMUT, "font-size": 11, "text-anchor": "middle" }, i18("stats.nodata", "no data yet"))); return; }
  const max = Math.max(1e-9, ...values), bw = (W - padL - padR) / n;
  for (const frac of [0, 1]) {
    const y = H - padB - frac * (H - padB - padT);
    svg.appendChild(_mk("line", { x1: padL, y1: y, x2: W - padR, y2: y, stroke: _CGRID, "stroke-width": 1 }));
    svg.appendChild(_mk("text", { x: padL - 3, y: y + 3, fill: _CMUT, "font-size": 8, "text-anchor": "end" }, opts.fmt ? opts.fmt(frac * max) : String(Math.round(frac * max))));
  }
  values.forEach((v, i) => {
    const h = (v / max) * (H - padB - padT), x = padL + i * bw + bw * 0.12, y = H - padB - h;
    svg.appendChild(_mk("rect", { x, y, width: bw * 0.76, height: Math.max(0, h), fill: opts.color || _CACC, rx: 2 }));
    if (labels && labels[i] != null && (n <= 10 || i % Math.ceil(n / 10) === 0))
      svg.appendChild(_mk("text", { x: x + bw * 0.38, y: H - 5, fill: _CMUT, "font-size": 7, "text-anchor": "middle" }, labels[i]));
  });
}
function hbarChart(id, rows, opts) {
  opts = opts || {}; const svg = _svgClear(id); if (!svg) return;
  // Three fixed columns so nothing is ragged or overflows: [label] [bar] [value(right-aligned)].
  const W = 320, rowH = 20, padT = 6, labelW = 72, valueW = 58, barX = labelW + 4;
  const barMax = W - barX - valueW;              // the bar can never reach into the value column
  const n = rows.length;
  if (!n) { svg.appendChild(_mk("text", { x: W / 2, y: 20, fill: _CMUT, "font-size": 11, "text-anchor": "middle" }, i18("stats.nodata", "no data yet"))); return; }
  svg.setAttribute("viewBox", `0 0 ${W} ${padT * 2 + n * rowH}`);
  const max = Math.max(1e-9, ...rows.map((r) => r.value));
  rows.forEach((r, i) => {
    const cy = padT + i * rowH + rowH / 2;
    const bw = Math.max(1, (r.value / max) * barMax);
    svg.appendChild(_mk("text", { x: 2, y: cy + 3.5, fill: _CMUT, "font-size": 10 }, r.label));
    svg.appendChild(_mk("rect", { x: barX, y: cy - (rowH - 9) / 2, width: bw, height: rowH - 9, fill: opts.color || _CACC, rx: 2 }));
    svg.appendChild(_mk("text", { x: W - 2, y: cy + 3.5, fill: "#cdd7e0", "font-size": 10, "text-anchor": "end" }, opts.fmt ? opts.fmt(r.value) : String(r.value)));
  });
}
function laneBar(id, open, bonded) {
  const svg = _svgClear(id); if (!svg) return;
  const W = 320, total = Math.max(1, open + bonded);
  const ow = (open / total) * (W - 8), bw = (bonded / total) * (W - 8);
  svg.appendChild(_mk("rect", { x: 4, y: 8, width: Math.max(0, ow), height: 20, fill: _CACC, rx: 3 }));
  svg.appendChild(_mk("rect", { x: 4 + ow, y: 8, width: Math.max(0, bw), height: 20, fill: _CGOLD, rx: 3 }));
  svg.appendChild(_mk("text", { x: 4, y: 45, fill: _CACC, "font-size": 10 }, `${i18("lane.open", "Open")}: ${open}`));
  svg.appendChild(_mk("text", { x: W - 4, y: 45, fill: _CGOLD, "font-size": 10, "text-anchor": "end" }, `${i18("lane.bonded", "Savings")}: ${bonded}`));
}

async function renderStats() {
  if (!state.wallet) return;
  const head = $("statsHeadline"); if (head) head.innerHTML = "";
  let tip = state.latest;
  try { const lb = await getLatestBlock(); if (lb && typeof lb.block_number === "number") tip = lb.block_number; } catch {}
  const N = 16, nums = [];
  for (let i = Math.max(1, (tip || 0) - N + 1); i <= (tip || 0); i++) nums.push(i);
  const blocks = (await Promise.all(nums.map((n) =>
    fetch(relayBase() + "/get_block_number?number=" + n, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
  ))).filter((b) => b && typeof b.block_number === "number");
  blocks.sort((a, b) => a.block_number - b.block_number);
  const times = [], tlabels = [];
  for (let i = 1; i < blocks.length; i++) { times.push(Math.max(0, (blocks[i].block_timestamp || 0) - (blocks[i - 1].block_timestamp || 0))); tlabels.push("#" + blocks[i].block_number); }
  barChart("chartBlockTime", times, tlabels, { color: _CACC, fmt: (v) => Math.round(v) + "s" });
  barChart("chartReward", blocks.map((b) => _nadoNum(b.block_reward)), blocks.map((b) => "#" + b.block_number), { color: _CGOLD, fmt: (v) => v.toFixed(2) });
  try {
    const d = await (await fetch(relayBase() + "/get_rich_list?n=8", { cache: "no-store" })).json();
    const rows = ((d && d.rich_list) || []).slice(0, 8).map((e) => ({ label: exShort(e.address, 8), value: _nadoNum(e.total) }));
    hbarChart("chartWealth", rows, { color: _CGRN, fmt: (v) => (v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(1)) });
  } catch {}
  let ms = state.lastMs;
  try { ms = await getMiningStatus(state.wallet.address); } catch {}
  if (ms) laneBar("chartLanes", ms.open_registry_size || 0, ms.bonded_registry_size || 0);
  const addStat = (label, val) => { if (!head) return; const d = document.createElement("div"); d.className = "stat"; d.innerHTML = `<div class="label"></div><div class="value sm"></div>`; d.children[0].textContent = label; d.children[1].textContent = val; head.appendChild(d); };
  addStat(i18("stats.tip", "Height"), tip != null ? tip : "—");
  if (ms) { addStat(i18("stats.present", "Present miners"), ms.open_registry_size ?? "—"); addStat(i18("stats.bondedMiners", "Savings miners"), ms.bonded_registry_size ?? "—"); }
  try { const pool = await (await fetch(relayBase() + "/get_account?address=dividend", { cache: "no-store" })).json(); addStat(i18("stats.pool", "Dividend pool"), rawToNado(BigInt(pool.balance || 0)) + " NADO"); } catch {}
}

/* ============================ SWAP TAB — HTLC cross-chain atomic swaps ============================ */
function _hex(u8) { return Array.from(u8).map((b) => b.toString(16).padStart(2, "0")).join(""); }
function _unhex(h) { const a = new Uint8Array(h.length / 2); for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }
async function _sha256hex(bytes) { return _hex(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))); }

async function swapLock() {
  if (!state.wallet) return;
  const claimant = $("swapClaimant").value.trim();
  const amtRaw = nadoToRaw($("swapAmount").value || "0");
  const blocks = Math.max(10, parseInt($("swapTimelock").value || "120", 10) || 120);
  let hashlock = $("swapHashlock").value.trim().toLowerCase(), preimageHex = null;
  if (!/^ndo[0-9a-f]{46}$/i.test(claimant)) { log("err", i18("swap.badClaimant", "Enter a valid ndo… claimant address.")); return; }
  if (amtRaw <= 0n) { log("err", i18("swap.badAmount", "Enter an amount to lock.")); return; }
  try {
    if (!hashlock) { const pre = crypto.getRandomValues(new Uint8Array(32)); preimageHex = _hex(pre); hashlock = await _sha256hex(pre); }
    else if (!/^[0-9a-f]{64}$/.test(hashlock)) { log("err", i18("swap.badHash", "Hashlock must be 64 hex chars (SHA-256).")); return; }
    const latest = await getLatestBlock(); const target = latest.block_number + 8; const expiry = target + blocks;
    const tx = buildTransferTx(state.wallet, "htlc_lock", amtRaw, MIN_TX_FEE, target, { claimant, hashlock, expiry }, nowSeconds());
    const res = await submitTransaction(tx);
    if (res.data && res.data.result) {
      log("ok", i18("swap.locked", "Lock submitted ✓ id {id}", { id: tx.txid.slice(0, 12) + "…" }));
      const box = $("swapSecretBox"); box.classList.remove("hidden");
      box.innerHTML = "";
      const line = (k, v) => { const d = document.createElement("div"); d.style.wordBreak = "break-all"; const b = document.createElement("b"); b.textContent = k; d.appendChild(b); d.appendChild(document.createTextNode(" " + v)); return d; };
      box.appendChild(line(i18("swap.idLabel", "HTLC id:"), tx.txid));
      box.appendChild(line(i18("swap.hashLabel", "Hashlock:"), hashlock));
      if (preimageHex) { const warn = document.createElement("div"); warn.style.marginTop = "6px"; warn.className = "danger"; warn.appendChild(line(i18("swap.secretLabel", "⚠ SECRET (preimage) — save it, it's your only way to claim/prove:"), preimageHex)); box.appendChild(warn); }
      setTimeout(() => renderSwaps().catch(() => {}), 1500);
    } else log("err", i18("swap.lockRej", "Lock rejected: {m}", { m: (res.data && res.data.message) || "" }));
  } catch (e) { log("err", i18("swap.lockErr", "Lock error: {m}", { m: e.message })); }
}

async function swapClaim(idFromBtn, preFromBtn) {
  if (!state.wallet) return;
  const hid = (idFromBtn || $("swapClaimId").value.trim());
  const preimage = (preFromBtn || $("swapPreimage").value.trim().toLowerCase());
  if (!hid || !/^[0-9a-f]+$/.test(preimage) || preimage.length % 2) { log("err", i18("swap.badClaim", "Enter the HTLC id and the hex secret.")); return; }
  try {
    const latest = await getLatestBlock(); const target = latest.block_number + 8;
    const tx = buildTransferTx(state.wallet, "htlc_claim", 0n, 0, target, { htlc_id: hid, preimage }, nowSeconds());
    const res = await submitTransaction(tx);
    if (res.data && res.data.result) { log("ok", i18("swap.claimed", "Claim submitted ✓")); setTimeout(() => renderSwaps().catch(() => {}), 1500); }
    else log("err", i18("swap.claimRej", "Claim rejected: {m}", { m: (res.data && res.data.message) || "" }));
  } catch (e) { log("err", i18("swap.claimErr", "Claim error: {m}", { m: e.message })); }
}

async function swapRefund(hid) {
  if (!state.wallet || !hid) return;
  try {
    const latest = await getLatestBlock(); const target = latest.block_number + 8;
    const tx = buildTransferTx(state.wallet, "htlc_refund", 0n, 0, target, { htlc_id: hid }, nowSeconds());
    const res = await submitTransaction(tx);
    if (res.data && res.data.result) { log("ok", i18("swap.refunded", "Refund submitted ✓")); setTimeout(() => renderSwaps().catch(() => {}), 1500); }
    else log("err", i18("swap.refundRej", "Refund rejected: {m}", { m: (res.data && res.data.message) || "" }));
  } catch (e) { log("err", i18("swap.refundErr", "Refund error: {m}", { m: e.message })); }
}

async function renderSwaps() {
  if (!state.wallet) return;
  const box = $("swapList"); if (!box) return;
  const me = state.wallet.address;
  let map = {};
  try { map = (await (await fetch(relayBase() + "/htlcs?address=" + encodeURIComponent(me), { cache: "no-store" })).json()).htlcs || {}; }
  catch { box.innerHTML = `<div class="faint small">${i18("swap.err", "unavailable")}</div>`; return; }
  const ids = Object.keys(map);
  if (!ids.length) { box.innerHTML = `<div class="faint small">${i18("swap.none", "No swaps yet.")}</div>`; return; }
  const tip = state.latest || 0;
  box.innerHTML = "";
  ids.sort().forEach((id) => {
    const h = map[id], iAmClaimant = h.claimant === me, iAmSender = h.sender === me;
    const expired = tip >= (h.expiry || 0);
    const row = document.createElement("div"); row.className = "ex-row";
    const left = document.createElement("div");
    const role = iAmSender ? i18("swap.roleSender", "you → " + exShort(h.claimant, 8)) : i18("swap.roleClaimant", exShort(h.sender, 8) + " → you");
    left.innerHTML = `<div class="mono small">${exShort(id, 14)}</div><div class="faint small">${rawToNado(BigInt(h.amount || 0))} NADO · ${role} · ${i18("swap.status." + h.status, h.status)} · exp #${h.expiry}</div>`;
    row.appendChild(left);
    const right = document.createElement("div");
    if (h.status === "open" && iAmClaimant && !expired) {
      const b = document.createElement("button"); b.className = "accent"; b.textContent = i18("swap.claim", "Claim");
      b.onclick = () => { $("swapClaimId").value = id; $("swapPreimage").focus(); }; right.appendChild(b);
    } else if (h.status === "open" && iAmSender && expired) {
      const b = document.createElement("button"); b.className = "ghost"; b.textContent = i18("swap.refund", "Refund");
      b.onclick = () => swapRefund(id); right.appendChild(b);
    } else if (h.status === "claimed" && h.preimage) {
      const s = document.createElement("div"); s.className = "faint small"; s.style.wordBreak = "break-all"; s.textContent = i18("swap.revealed", "secret: ") + h.preimage; right.appendChild(s);
    }
    row.appendChild(right); box.appendChild(row);
  });
}

function showTab(name) {
  if (!state.wallet) return;
  state.activeTab = name;
  document.querySelectorAll("#tabbar .tab").forEach((b) => b.classList.toggle("active", b.dataset.tabbtn === name));
  document.querySelectorAll("[data-tab]").forEach((el) => el.classList.toggle("hidden", el.dataset.tab !== name));
  if (name !== "send") show("payBanner", false); // the pay-request banner belongs to the Send tab only
  if (name === "receive") renderReceiveQR();
  else if (name === "aliases") loadMyAliases();
  else if (name === "explore") { exLoadOverview(); exLoadRecent(); }
  else if (name === "history") loadHistory().catch(() => {});
  else if (name === "rich") loadRichList().catch(() => {});
  else if (name === "stats") renderStats().catch(() => {});
  else if (name === "swap") renderSwaps().catch(() => {});
  else if (name === "send") { updateFeeInfo().catch(() => {}); validateSendTo().catch(() => {}); addrBookRender(); }
  else if (name === "stake") { updateFeeInfo().catch(() => {}); refreshDashboard().catch(() => {}); }
}

/* Pre-wallet view: no tabs; show onboarding + the Settings card (so the relay can be configured). */
function enterOnboarding() {
  show("tabbar", false);
  document.querySelectorAll("[data-tab]").forEach((el) => show(el.id, false));
  show("settingsCard", true);
  show("savePrompt", false);
  show("onboard", true);
}

/* ----------------------------------------------------------------------------------------------
 * Wire up the UI
 * -------------------------------------------------------------------------------------------- */
function wireEvents() {
  $("btnGenerate").onclick = () => {
    try { adoptWallet(newKeypair(), { needsSavePrompt: true }); }
    catch (e) { log("err", "Key generation failed: " + e.message); }
  };
  $("btnShowImport").onclick = () => show("importBox", !$("importBox").classList.contains("hidden") ? false : true);
  $("btnImport").onclick = () => {
    try { adoptWallet(keypairFromPriv($("importKey").value), { needsSavePrompt: false }); }
    catch (e) { alert(i18("import.pasteFailed", "Import failed:") + " " + e.message); }
  };
  $("ackSave").onchange = (e) => { $("btnConfirmSave").disabled = !e.target.checked; };
  $("btnConfirmSave").onclick = () => {
    state.wallet = pendingWallet; pendingWallet = null;
    persistWallet(state.wallet);
    showWalletUI();
    log("info", i18("log.walletCreated", "New wallet created & stored: {a}", {a: state.wallet.address}));
    refreshDashboard().catch(() => {});
  };

  $("btnMine").onclick = () => {
    if (state.starting) return;            // a start/registration is in flight → ignore extra clicks
    if (state.mining) { stopMining(); return; }  // active mining → Stop (never re-triggers registration)
    startMining();
  };
  $("btnCancelPow").onclick = () => { stopMining(); };  // escape hatch while the main button is disabled
  if ($("btnAliasReg")) $("btnAliasReg").onclick = () => doAliasOp("register");
  if ($("btnAliasUnreg")) $("btnAliasUnreg").onclick = () => doAliasOp("unregister");
  if ($("btnAliasXfer")) $("btnAliasXfer").onclick = () => doAliasOp("transfer");
  if ($("exGo")) $("exGo").onclick = () => exSearch();
  if ($("exQ")) $("exQ").addEventListener("keydown", (e) => { if (e.key === "Enter") exSearch(); });
  document.addEventListener("click", (e) => {           // delegated explorer links (module-safe)
    const a = e.target.closest && e.target.closest("a.ex-link[data-exk]");
    if (a) {
      e.preventDefault();
      if (state.activeTab !== "explore") showTab("explore");   // navigate to the Explore tab so the result is visible
      exOpen(a.dataset.exk, a.dataset.exv);
    }
    const p = e.target.closest && e.target.closest("a.addrpick[data-to]");
    if (p) { e.preventDefault(); showTab("send"); $("sendTo").value = p.dataset.to; validateSendTo(); }
  });
  // re-render dynamic (JS-set) strings — badges, mining status — when the language changes
  window.addEventListener("nado-lang", () => {
    if (state.wallet) refreshDashboard().catch(() => {});
    if (state.mining) setStartBtnMining();                     // re-apply the translated "Stop mining" label
  });

  // --- full-wallet wiring ---
  $("btnDlKey").onclick = downloadKeyFile;
  $("btnDlKeySave").onclick = downloadKeyFile;
  if ($("btnSwapLock")) $("btnSwapLock").onclick = () => swapLock();
  if ($("btnSwapClaim")) $("btnSwapClaim").onclick = () => swapClaim();
  $("btnDlKeySettings").onclick = downloadKeyFile;
  if ($("btnCollectDiv")) $("btnCollectDiv").onclick = () => collectDividend();
  if ($("btnImportFile")) $("btnImportFile").onclick = () => $("importFile").click();
  if ($("importFile")) $("importFile").onchange = (e) => {
    importKeyFile(e.target.files && e.target.files[0]);
    e.target.value = "";                               // allow re-selecting the same file later
  };

  document.querySelectorAll("#tabbar .tab").forEach((b) => { b.onclick = () => showTab(b.dataset.tabbtn); });

  $("btnSend").onclick = () => doSend();
  $("sendTo").oninput = validateSendTo;
  $("btnBond").onclick = () => doBond("bond");
  $("btnUnbond").onclick = () => doBond("unbond");
  if ($("autoBondPct")) {
    const apply = () => { const p = setAutoBondPct($("autoBondPct").value); $("autoBondPct").value = String(p); };
    $("autoBondPct").onchange = apply;
    $("autoBondPct").oninput = () => setAutoBondPct($("autoBondPct").value); // live note, no reformat mid-type
  }
  if ($("autoBondPctMine")) {   // the same control on the mining card (kept in sync via setAutoBondPct)
    $("autoBondPctMine").onchange = () => { const p = setAutoBondPct($("autoBondPctMine").value); $("autoBondPctMine").value = String(p); };
    $("autoBondPctMine").oninput = () => setAutoBondPct($("autoBondPctMine").value);
  }
  $("btnRefreshHist").onclick = () => loadHistory().catch(() => {});

  $("recvAmount").oninput = () => renderReceiveQR();   // live-update the QR + payment link
  $("btnSharePay").onclick = () => sharePayLink();
  if ($("btnShareMiner")) $("btnShareMiner").onclick = () => shareMiner();

  $("btnSaveRelay").onclick = () => {
    const v = $("relayUrl").value.trim();
    state.relay = v || null;
    if (v) localStorage.setItem(LS_RELAY, v); else localStorage.removeItem(LS_RELAY);
    log("info", i18("log.relaySet", "Relay set to {u}", {u: relayBase()}));
    pollOnce().catch(() => {});
  };

  $("btnSelfTest").onclick = () => { try { runSelfTest(); show("selftestCard", true); } catch (e) { log("err", "Self-test error: " + e.message); } };
  $("btnClearLog").onclick = () => { $("log").innerHTML = ""; };
  $("btnForget").onclick = () => {
    if (!confirm("Forget the wallet stored in this browser? Make sure you saved the private key — this cannot be undone.")) return;
    stopMining();
    localStorage.removeItem(LS_WALLET);
    state.wallet = null;
    state.activeTab = "wallet";
    enterOnboarding();
    log("info", i18("log.walletForgotten", "Wallet forgotten."));
  };

  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.onclick = async () => {
      const txt = $(btn.getAttribute("data-copy")).textContent;
      const ok = await copyToClipboard(txt);   // secure-context clipboard, execCommand fallback over http
      if (ok) { btn.textContent = i18("copy.copied", "Copied ✓"); setTimeout(() => (btn.textContent = i18("btn.copy", "Copy")), 1200); }
      else { btn.textContent = i18("copy.select", "select & copy"); setTimeout(() => (btn.textContent = i18("btn.copy", "Copy")), 1600); }
    };
  });
}

/* ----------------------------------------------------------------------------------------------
 * Boot
 * -------------------------------------------------------------------------------------------- */
async function boot() {
  // relay
  state.relay = localStorage.getItem(LS_RELAY) || null;
  $("relayUrl").value = state.relay || "";
  $("relayUrl").placeholder = location.origin;

  // auto-bond preference (persisted %); reflect it into the Stake-tab control + the status note
  try {
    // No saved preference at all -> the 80% default (auto-bond on out of the box). A stored value
    // (including "0" for explicit off) is honoured verbatim.
    const raw = localStorage.getItem(LS_AUTOBOND);
    const saved = raw === null ? AUTO_BOND_DEFAULT_PCT : (parseInt(raw, 10) || 0);
    const p = setAutoBondPct(saved);
    if ($("autoBondPct")) $("autoBondPct").value = String(p);
  } catch (e) {}

  try {
    await loadDeps();
  } catch (e) {
    show("bootError", true);
    $("bootErrorMsg").textContent = "Could not load crypto (local vendor bundle + CDN both failed): " + (e && e.message || e);
    return;
  }

  await loadQR(); // optional, vendored QR generator (Receive tab degrades gracefully if absent)

  wireEvents();

  // run the self-test automatically on boot (also logs to console)
  let ok = false;
  try { ok = runSelfTest(); } catch (e) { log("err", "Self-test crashed: " + e.message); }
  log(ok ? "ok" : "err", `Self-test: ${ok ? "all vectors match Python ✓" : "MISMATCH — see Self-test card"}`);

  // load existing wallet or onboard
  const w = loadWallet();
  let resumedMining = false;
  if (w && w.address) {
    state.wallet = w;
    showWalletUI();
    log("info", i18("log.walletLoadedDevice", "Loaded wallet from this device: {a}", {a: w.address}));
    // AUTO-RESUME across a browser refresh: the in-memory mining flag is lost on reload, but the intent is
    // persisted, so we resume without a re-click. This won't double anything — the node dedups heartbeats
    // one-per-(address,epoch) and won't re-register an already-registered (lease-valid) identity.
    if (localStorage.getItem(LS_MINING) === "1") {
      log("info", i18("log.resuming", "Resuming mining after refresh (no re-click needed)…"));
      startMining();
      resumedMining = true;
    }
  } else {
    enterOnboarding();
  }

  // payment-request deep link (#pay?to=…&amount=…): prefill a Send if a wallet exists, else stash it
  // and resume after onboarding. Never auto-submits — the user still reviews + confirms.
  try { consumePayRequest(); } catch (e) { log("err", "Pay-link error: " + e.message); }

  // initial connectivity + dashboard (startMining already kicks a poll when we auto-resumed)
  if (!resumedMining) pollOnce().catch(() => setConn(false));
}

boot();

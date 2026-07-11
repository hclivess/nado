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
import * as shielded from "./shielded.js";
import * as alghash from "./alghash.js";
import * as sfield from "./stark/field.js";
import { initHashing as initStarkHashing } from "./stark/hashing.js";
import { initBlake2bWasm, initMerkleWasm } from "./vendor/blake2b-wasm.js";
import { initGoldilocksWasm } from "./vendor/goldilocks-wasm.js";
import { setFieldWasm } from "./stark/field.js";
import { setMerkleWasm } from "./stark/merkle.js";
import * as sjoinsplit2 from "./stark/joinsplit2.js";
import * as sstark from "./stark/stark.js";
import { treePath } from "./stark/tree.js";
import { seedToMnemonic, mnemonicToSeed, looksLikeMnemonic } from "./bip39.js";
const CHAIN_ID = "alphanet-4";
const EPOCH_LENGTH = 60;
const FINALITY_DEPTH = 30;     // protocol.py: reveal window for epoch E ends at E*EPOCH_LENGTH - FINALITY_DEPTH - 1
const REGISTER_POW_BITS = 16;  // legacy hashcash (retired) — kept only for the self-test vector
// Registration Proof of Sequential Work (must match protocol.py). Non-parallelizable ~1 s chain; the
// registration is a renewable presence LEASE renewed once ~POSW_LEASE_EPOCHS (≈1 day at ~8 min/epoch).
const POSW_T = 1_000_000, POSW_S = 2_000, POSW_K = 20, POSW_ANCHOR_OFFSET = 30, POSW_LEASE_EPOCHS = 180;
// Headroom (in blocks) between the current tip and the register/recert max_block, so the tx still lands
// BEFORE its target while the sequential PoW is computing. It is capped by POSW_ANCHOR_OFFSET: the anchor is
// block (target − POSW_ANCHOR_OFFSET), which the client must be able to FETCH now, so target ≤ tip + offset.
// The old value (8 blocks ≈ 64 s at 8 s/block) was too tight when the PoW runs in pure JS (WASM unavailable) —
// the chain passed target during proving and the node rejected it "Target block too low". Use the max (≈240 s).
const POSW_TARGET_MARGIN = POSW_ANCHOR_OFFSET;
const DENOMINATION = 10_000_000_000n; // 1 NADO in raw units (1e10)
const MIN_TX_FEE = 1000;
const BOND_UNLOCK_DELAY = 1440; // protocol.py: blocks a bond stays locked after an unbond request
const BOND_CAP = 100_000_000_000_000n;  // protocol.py: 10,000 NADO — bonding past this buys no weight
const ALIAS_REGISTRATION_FEE = 10_000_000; // protocol.py: 0.001 NADO anti-squat fee for `alias` register
const AUTO_BOND_MIN_RAW = 10_000_000n;  // protocol.py: dust floor for an auto-bond (0.001 NADO)

/* ----------------------------------------------------------------------------------------------
 * Dependency loading: @noble/hashes (blake2b) + @noble/post-quantum (ML-DSA-44) as ESM from a CDN.
 * -------------------------------------------------------------------------------------------- */
let blake2b, bytesToHex, hexToBytes, ml_dsa44, ml_kem768;

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
    const m = await import('./vendor/nado-crypto.js?v=mlkem');
    blake2b = m.blake2b; bytesToHex = m.bytesToHex; hexToBytes = m.hexToBytes; ml_dsa44 = m.ml_dsa44;
    ml_kem768 = m.ml_kem768;   // ML-KEM-768 for messaging E2E (may be undefined on a stale cached bundle)
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
      const [hb, hu, pq, pk] = await Promise.all([
        import(build("@noble/hashes@1.4.0/blake2b")),
        import(build("@noble/hashes@1.4.0/utils")),
        import(build("@noble/post-quantum@0.2.0/ml-dsa")),
        import(build("@noble/post-quantum@0.2.0/ml-kem")),
      ]);
      blake2b = hb.blake2b;
      bytesToHex = hu.bytesToHex;
      hexToBytes = hu.hexToBytes;
      ml_kem768 = pk.ml_kem768;   // ML-KEM-768 (FIPS 203) for messaging E2E encryption
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

// ---- HD ACCOUNTS: multiple addresses from ONE master seed / recovery phrase -----------------------
// Your master seed (the 32-byte ML-DSA seed behind your recovery phrase) is account "Main". Extra accounts
// are DERIVED from it deterministically, so the single recovery phrase restores them all. Only the MASTER is
// ever persisted / encrypted / exported; switching accounts is just an in-memory signing view (switching
// never writes localStorage, so a derived key can never overwrite the stored master). Derivation is
// domain-tagged + canonical-JSON, so any wallet — and the node's Python `blake2b_hash` — reproduces the
// same child addresses for recovery.
const LS_HD_COUNT = "nado_hd_accounts";     // how many DERIVED accounts (beyond Main) the user has added
function hdCount() { return Math.max(0, parseInt(localStorage.getItem(LS_HD_COUNT) || "0", 10) || 0); }
function accountChildSeed(masterHex, index) { return blake2bHash(["nado-hd-account", masterHex, index], 32); }
function accountKeypair(masterHex, index) {
  return keypairFromPriv(index === 0 ? masterHex : accountChildSeed(masterHex, index));
}
function masterSeedOf() { return state.masterSeed || (state.wallet && state.wallet.privateKey) || null; }
function accountLabel(i) { return i === 0 ? i18("acct.main", "Main") : i18("acct.n", "Account {n}", { n: i + 1 }); }
// Keep the HD layer consistent with state.wallet. A wallet (re)loaded by unlock/import/boot is ALWAYS the
// master on account 0 — its address won't match our expected active-account address — so re-anchor to it.
function hdSync() {
  if (!state.wallet) return;
  if (state.masterSeed == null || state.wallet.address !== state._hdExpectedAddr) {
    state.masterSeed = state.wallet.privateKey;
    state.activeIdx = 0;
    state._hdExpectedAddr = state.wallet.address;
  }
}
function switchAccount(i) {
  const master = masterSeedOf();
  if (master == null) return;
  i = Math.max(0, Math.min(hdCount(), i | 0));
  const kp = accountKeypair(master, i);
  state.masterSeed = master;              // preserve the master; state.wallet becomes the derived signer
  state.wallet = kp;
  state.activeIdx = i;
  state._hdExpectedAddr = kp.address;      // so hdSync won't mistake this switch for an external reload
  // NEVER persistWallet here — LS_WALLET must stay the master seed so one phrase restores every account.
  showWalletUI();
  refreshDashboard().catch(() => {});
}
function addAccount() {
  const n = hdCount() + 1;
  localStorage.setItem(LS_HD_COUNT, String(n));
  switchAccount(n);
}
function renderAccountBar() {
  const bar = $("accountBar");
  if (!bar || !state.wallet) return;
  const count = hdCount(), active = state.activeIdx || 0;
  bar.textContent = "";
  bar.style.cssText = "display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap";
  const lbl = document.createElement("span");
  lbl.className = "small faint"; lbl.textContent = i18("acct.label", "Account");
  const sel = document.createElement("select");
  sel.setAttribute("aria-label", i18("acct.label", "Account"));
  sel.style.cssText = "width:auto;background:var(--bg);color:var(--txt);border:1px solid var(--border);border-radius:8px;padding:4px 8px;font-size:12px;font-family:var(--sans);color-scheme:dark";
  for (let i = 0; i <= count; i++) {
    const o = document.createElement("option");
    o.value = String(i); o.textContent = accountLabel(i);
    if (i === active) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => switchAccount(parseInt(sel.value, 10));
  const add = document.createElement("button");
  add.className = "copy"; add.type = "button";
  add.textContent = i18("acct.add", "+ Add");
  add.title = i18("acct.addTip", "Derive a new address from your recovery phrase");
  add.onclick = addAccount;
  bar.appendChild(lbl); bar.appendChild(sel); bar.appendChild(add);
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
// case-insensitive on purpose: on-chain alias names are all-lowercase, and callers normalize with
// .toLowerCase() before resolving/sending — typing "Alice" must behave exactly like "alice".
function looksLikeAlias(s) { return /^[a-z][a-z0-9_-]{2,31}$/i.test(s || "") && !/^ndo/i.test(s || ""); }
// i18n helper for dynamic (JS-set) strings — translates via i18n.js's window.t, English fallback.
function i18(k, fb, vars) { return (typeof window !== "undefined" && window.t) ? window.t(k, fb, vars) : (fb != null ? fb : k); }
async function resolveAlias(name) {
  try {
    name = (name || "").trim().toLowerCase();   // registry names are all-lowercase
    const r = await fetch(relayBase() + "/resolve_alias?name=" + encodeURIComponent(name), { cache: "no-store" });
    const d = await r.json();
    return d && d.owner ? d.owner : null;
  } catch { return null; }
}
// Live validation of the Send "to" field: a valid ndo… address, OR a registered alias (resolved
// against the node, so the ✗ clears once the alias exists). Guards against stale async results.
async function validateSendTo() {
  const v = ($("sendTo").value || "").trim().toLowerCase();
  if (!v) { setMsg("sendToMsg", "", null); return; }
  if (validateAddress(v)) { setMsg("sendToMsg", i18("sto.valid", "✓ valid address"), "ok"); return; }
  if (looksLikeAlias(v)) {
    setMsg("sendToMsg", i18("sto.resolving", "resolving alias…"), null);
    const owner = await resolveAlias(v);
    if (($("sendTo").value || "").trim().toLowerCase() !== v) return;   // input changed while resolving — ignore stale
    setMsg("sendToMsg", owner ? `${i18("sto.aliasPre","✓ alias →")} ${owner.slice(0, 14)}…` : `${i18("sto.aliasNoPre","✗ alias")} “${v}” ${i18("sto.aliasNoSuf","is not registered")}`, owner ? "ok" : "err");
    return;
  }
  setMsg("sendToMsg", i18("sto.invalid", "✗ invalid — a 49-char ndo… address or a registered alias name"), "err");
}

// ADDRESS BOOK: every recipient you send to (alias or address) is remembered in localStorage, offered
// as native autocomplete on the Send field (datalist) + clickable recent chips to reselect.
// ADDRESS BOOK: saved contacts [{addr,label}] (label = your nickname). Each contact also shows its on-chain
// @alias. Auto-saved on send + manually via ⭐ Save; rename/remove inline; feeds the Send recipient autocomplete.
const LS_ADDRBOOK = "nado_addrbook";
function addrBookLoad() {
  try {
    return JSON.parse(localStorage.getItem(LS_ADDRBOOK) || "[]")
      .map((x) => typeof x === "string" ? { addr: x, label: "" } : { addr: (x && x.addr) || "", label: (x && x.label) || "" })
      .filter((x) => x.addr);
  } catch { return []; }
}
function addrBookSave(book) { try { localStorage.setItem(LS_ADDRBOOK, JSON.stringify(book.slice(0, 100))); } catch (e) {} }
function addrBookAdd(addr, label) {
  addr = (addr || "").trim().toLowerCase();
  if (!addr) return;
  const book = addrBookLoad(), existing = book.find((x) => x.addr === addr);
  const keepLabel = (label || "").trim() || (existing && existing.label) || "";   // re-send must not wipe a label
  const rest = book.filter((x) => x.addr !== addr);
  rest.unshift({ addr, label: keepLabel });
  addrBookSave(rest); addrBookRender();
}
function addrBookRemove(addr) { addrBookSave(addrBookLoad().filter((x) => x.addr !== addr)); addrBookRender(); }
function addrBookSetLabel(addr, label) {
  const book = addrBookLoad(), e = book.find((x) => x.addr === addr);
  if (e) { e.label = (label || "").trim(); addrBookSave(book); addrBookRender(); }
}
const _abAlias = {};   // addr -> alias name ("" if none), resolved from chain
async function abResolveAliases(addrs) {
  await Promise.all([...new Set(addrs)].filter((a) => a && /^ndo/.test(a) && !(a in _abAlias)).map(async (a) => {
    try { const r = await (await fetch(relayBase() + "/get_aliases_of?address=" + encodeURIComponent(a), { cache: "no-store" })).json(); _abAlias[a] = (r.aliases && r.aliases[0]) || ""; }
    catch { _abAlias[a] = ""; }
  }));
}
const _abShort = (a) => /^ndo[0-9a-f]{46}$/.test(a) ? a.slice(0, 10) + "…" + a.slice(-4) : a;
function _abRow(x) {
  const alias = _abAlias[x.addr] ? "@" + _abAlias[x.addr] : "", short = _abShort(x.addr);
  const name = x.label || alias || short;
  const sub = [alias && alias !== name ? alias : "", short !== name ? short : ""].filter(Boolean).join(" · ");
  const a = x.addr.replace(/"/g, "&quot;");
  return `<div class="ab-row"><a class="addrpick ab-name" data-to="${a}" title="Send to this contact">${escapeHtml(name)}</a>`
    + (sub ? `<span class="ab-sub faint">${escapeHtml(sub)}</span>` : "")
    + `<span class="ab-acts"><a class="ab-edit" data-abaddr="${a}" title="Rename">✎</a><a class="ab-del" data-abaddr="${a}" title="Remove">✕</a></span></div>`;
}
async function saveCurrentContact() {
  let to = ($("sendTo").value || "").trim().toLowerCase(); let alias = "";
  if (!to) { setMsg("sendMsg", "Enter an address or alias to save.", "err"); return; }
  if (!validateAddress(to) && looksLikeAlias(to)) {
    const owner = await resolveAlias(to);
    if (!owner) { setMsg("sendMsg", `Alias "${to}" is not registered.`, "err"); return; }
    alias = to; to = owner;
  }
  if (!validateAddress(to)) { setMsg("sendMsg", "Enter a valid ndo… address or a registered alias to save.", "err"); return; }
  const label = await uiPrompt({ title: i18("ab.nameIt", "Name this contact (optional):"), placeholder: alias || "e.g. Alice" });
  if (label === null) return;
  addrBookAdd(to, (label || "").trim() || alias);
  setMsg("sendMsg", i18("ab.saved", "Saved to your address book."), null);
}
function addrBookRender() {
  const book = addrBookLoad();
  const dl = $("sendToBook");
  if (dl) dl.innerHTML = book.map((x) => `<option value="${x.addr.replace(/"/g, "&quot;")}">${escapeHtml(x.label || "")}</option>`).join("");
  const box = $("addrBook"); if (!box) return;
  if (!book.length) { box.innerHTML = '<span class="faint">No saved contacts yet — send to someone, or ⭐ Save an address.</span>'; return; }
  const paint = () => { box.innerHTML = '<div class="ab-head">📇 Address book</div>' + book.map(_abRow).join(""); };
  paint();
  abResolveAliases(book.map((x) => x.addr)).then(paint);
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
  const { publicKey, secretKey } = ml_dsa44.keygen(hexToBytes(privHex));
  const m = hexToBytes(txid);
  // ML-DSA-44 signing is HEDGED (randomized). A rare bad hedge yields a signature that does NOT verify —
  // the node then rejects the tx with "Invalid signature" (seen intermittently on auto-bond). Verify our own
  // signature locally and re-sign until it checks out, so we never submit a non-verifying signature.
  let signature = null;
  for (let i = 0; i < 8; i++) {
    const sig = ml_dsa44.sign(secretKey, m);
    if (ml_dsa44.verify(publicKey, m, sig)) { signature = bytesToHex(sig); break; }
  }
  if (!signature) throw new Error("could not produce a verifying signature — please retry");
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
    max_block: targetBlock,
    chain_id: CHAIN_ID,
    posw,                        // sequential Proof of Work (renewable presence lease); replaces pow_nonce
  };
  return finalizeTransaction(draft, wallet.privateKey, 0);
}

// ON-CHAIN messaging key (fee-exempt identity tx): binds the sender's ML-KEM-768 pubkey to their account so
// peers can DM them by address/alias with NO off-chain prekey. Mirrors buildRegisterTx — the extra committed
// field is `kem_pub` (register's `posw`). public_key is included (pubkey-once stores it idempotently; it's
// excluded from the txid so its presence is free and always safe).
function buildMsgkeyTx(wallet, kemPubHex, targetBlock, timestamp) {
  const draft = {
    sender: wallet.address,
    recipient: "msgkey",
    amount: 0,
    timestamp,
    data: "",
    nonce: randNonce(),
    public_key: wallet.publicKey,
    max_block: targetBlock,
    chain_id: CHAIN_ID,
    kem_pub: kemPubHex,
  };
  return finalizeTransaction(draft, wallet.privateKey, 0);
}

// The sequential proof hashes POSW_T (1,000,000) times in a chain. Route that through the WASM blake2b —
// byte-identical to the JS/Python blake2b (verified against the node's hash), so the proof still verifies —
// which is far faster than pure JS. Cached; falls back to the JS blake2b if WASM is unavailable.
let _wasmB2b;   // undefined = not yet tried; function = ready; null = unavailable
async function miningHashDeps() {
  if (_wasmB2b === undefined) { try { _wasmB2b = await initBlake2bWasm(); } catch (e) { _wasmB2b = null; } }
  return { blake2b: _wasmB2b ? (b) => _wasmB2b(b) : blake2b, bytesToHex, hexToBytes };
}

// Fetch the PoSW anchor (hash of block max_block − POSW_ANCHOR_OFFSET — a finalized, stable block that
// the node derives identically), compute the non-parallelizable sequential proof, and build the register tx.
async function computeRegisterTx(targetBlock, onProgress, requiredT) {
  const anchorNum = Math.max(0, targetBlock - POSW_ANCHOR_OFFSET);
  const r = await fetch(relayBase() + "/get_block_number?number=" + anchorNum, { cache: "no-store" });
  const b = await r.json().catch(() => null);
  const anchorHash = b && b.block_hash;
  if (!anchorHash) throw new Error("registration anchor block unavailable");
  // Prove at the CONSENSUS required step count (base × difficulty). During a registration flood this is higher,
  // and the node rejects a proof made with fewer steps — so match it or the registration is invalid.
  const T = (requiredT && requiredT >= POSW_T && requiredT % POSW_S === 0) ? requiredT : POSW_T;
  const proof = await poswProveAsync(challengeBytes(state.wallet.address, anchorHash),
    T, POSW_S, POSW_K, await miningHashDeps(), onProgress);
  return buildRegisterTx(state.wallet, targetBlock, proof, nowSeconds());
}

// Current registration difficulty from the relay: {reqT, mult, recent}. Falls back to base (1× normal load).
async function registrationDifficulty() {
  try {
    const r = await fetch(relayBase() + "/posw_difficulty", { cache: "no-store" });
    const d = await r.json();
    const t = Number(d.required_t);
    if (t >= POSW_T && t % POSW_S === 0) return { reqT: t, mult: Number(d.multiplier) || 1, recent: Number(d.recent_registrations) || 0 };
  } catch (e) { /* older node / offline → base difficulty */ }
  return { reqT: POSW_T, mult: 1, recent: 0 };
}
// Rolling estimate of this device's sequential-hash rate (hashes/sec), so the wait ETA is device-calibrated.
function poswRate() { const r = parseFloat(localStorage.getItem("nado_posw_rate") || ""); return (r > 0 && isFinite(r)) ? r : 700000; }
function savePoswRate(hashes, ms) { if (hashes > 0 && ms > 200) { try { localStorage.setItem("nado_posw_rate", String(Math.round(hashes / (ms / 1000)))); } catch (e) {} } }


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
    max_block: targetBlock,
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
  // Relay reached on an explicit port (a direct node, e.g. http://ip:9173) -> the exec node is on :9273 of the
  // same host. Relay reached with NO port (served behind a reverse proxy on 80/443, e.g. https://get.nadochain.com)
  // -> the exec node is proxied at /exec on the SAME origin, so keep the origin as-is.
  return /:\d+$/.test(b) ? b.replace(/:\d+$/, ":9273") : b;
}

/* PRESENCE DIVIDEND (doc/presence-dividend.md). accrued lives off-L1 on the execution node; "Collect" submits
 * a fee-cheap collect blob, then the accrued amount is claimed to L1 automatically once the exec root that
 * carries it is settled by the bonded quorum. */
function buildBlobTx(wallet, payload, targetBlock, fee, timestamp) {
  const draft = { sender: wallet.address, recipient: "blob", amount: 0, timestamp, data: payload,
    nonce: randNonce(), public_key: wallet.publicKey, max_block: targetBlock, chain_id: CHAIN_ID };
  return finalizeTransaction(draft, wallet.privateKey, fee);
}
// ML-DSA-44 signing is HEDGED (randomized): a rare signature verifies locally yet is rejected by the node /
// peers as "Invalid signature" (the JS and native verifiers disagree on a boundary case). Each rebuild
// re-signs with FRESH randomness and a fresh nonce, so simply resubmitting clears it. Retry ONLY on a
// signature-related rejection — any other rejection (insufficient balance, bad amount, expired) won't be
// fixed by re-signing, so return it immediately. `buildTxFn` MUST build+sign a brand-new tx on each call.
async function submitResilient(buildTxFn, tries = 8) {
  let last = null, tx = null;
  for (let i = 0; i < tries; i++) {
    tx = await buildTxFn();
    let res;
    try { res = await submitTransaction(tx); }
    catch (e) { res = { data: { message: String((e && e.message) || e) } }; }   // network/HTTP error -> retry
    if (res && res.data && res.data.result) return { res, tx };
    last = res;
    const msg = (res && res.data && res.data.message) || "";
    // RETRY the transient rejections a thin/degraded node emits: bad signature draw, a momentary node
    // stall / pool churn (a bare 403), rate-limit, relay unreachable. Only a DEFINITIVE reject (insufficient
    // balance, revert, duplicate, expired target) breaks out — retrying those is pointless.
    const transient = msg === "" || /signature|unreachable|timeout|temporar|degraded|pool|busy|try again|429|forbidden|network/i.test(msg);
    if (!transient) break;
    await new Promise((r) => setTimeout(r, 1500 + i * 900));   // back off to ride out a block-production stall
  }
  return { res: last, tx };
}
function buildDividendWithdrawTx(wallet, addr, amount, nonce, proof, targetBlock, timestamp) {
  const draft = { sender: wallet.address, recipient: "dividend_withdraw", amount: 0, timestamp,
    data: { addr, amount, nonce, proof }, nonce: randNonce(), public_key: wallet.publicKey,
    max_block: targetBlock, chain_id: CHAIN_ID };
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
  state._divAccruedNow = accrued.toString();
  const pending = (d && d.pending) || [];
  show("divWrap", mining || accrued > 0n || pending.length > 0);
  if ($("divAccrued")) $("divAccrued").textContent = reachable ? (rawToNado(accrued) + " NADO") : i18("div.unavail", "exec node unreachable");
  const inflight = state._divInFlight && state._divInFlight.accrued === accrued.toString() && (Date.now() - state._divInFlight.ts) < 600000;
  if (state._divInFlight && !inflight) state._divInFlight = null;   // settled (amount changed) or timed out
  if ($("btnCollectDiv")) {
    $("btnCollectDiv").disabled = !(accrued > 0n) || state._collecting || !!inflight;
    $("btnCollectDiv").textContent = inflight ? i18("div.inflight", "Collecting — settling on-chain…") : i18("div.collect", "Collect dividend");
  }
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
  coinShower($("btnCollectDiv"));           // tiered coin shower on click (cosmetic; button is only enabled when a dividend is due)
  state._collecting = true;
  if ($("btnCollectDiv")) $("btnCollectDiv").disabled = true;
  try {
    const latest = await getLatestBlock();
    if (!latest) throw new RelayUnreachable("relay unavailable");
    const tx = buildBlobTx(state.wallet, { op: "collect_dividend" }, latest.block_number + 8, MIN_TX_FEE, nowSeconds());
    const res = await submitTransaction(tx);
    if (res.data && res.data.result) {
      state._divInFlight = { accrued: (state._divAccruedNow || "0"), ts: Date.now() };
      log("ok", i18("div.collecting", "Dividend collection submitted — it lands in your balance automatically once the exec root is settled (a few minutes)."));
    }
    else log("err", i18("log.collectRejected", "Collect rejected: {m}", {m: (res.data && (res.data.message || ""))}));
  } catch (e) { log("err", i18("log.collectFailed", "Collect failed: {m}", {m: e.message})); }
  finally { state._collecting = false; }
}

// A relay that is momentarily unreachable — a fetch reject (offline/DNS/TLS), a request timeout, an
// HTTP 5xx/429, or a non-JSON body (a proxy 502 HTML page). This is EXPECTED and transient: the node
// bounces for a few seconds on a restart/crash-restart, and Cloudflare/nginx answer with an error page
// meanwhile. Callers treat it as "retry quietly", NOT as a hard failure to scare the user with.
class RelayUnreachable extends Error {
  constructor(msg) { super(msg); this.name = "RelayUnreachable"; this.transient = true; }
}
function isTransient(e) { return !!(e && e.transient); }

async function fetchWithTimeout(url, opts, ms) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } catch (e) {
    // AbortError (timeout) and TypeError ("Failed to fetch") are both transient reachability failures.
    throw new RelayUnreachable(e && e.name === "AbortError" ? "relay timed out" : "relay unreachable");
  } finally {
    clearTimeout(timer);
  }
}

// GET a JSON endpoint with a timeout and ONE silent retry on a transient blip, so a ~5 s node restart
// is ridden out instead of surfaced. Returns {ok, status, data}. A response that isn't JSON (proxy
// error page) or a 5xx/429 is treated as unreachable: after the retry it throws RelayUnreachable, so
// read callers can `return null` and write callers (registration) can retry quietly.
async function rpcJSON(path, { timeout = 12000, retry = true } = {}) {
  const url = relayBase() + path;
  let lastTransient;
  for (let attempt = 0; attempt <= (retry ? 1 : 0); attempt++) {
    try {
      const res = await fetchWithTimeout(url, { method: "GET", cache: "no-store" }, timeout);
      const text = await res.text();
      let data, parsed = true;
      try { data = JSON.parse(text); } catch { parsed = false; data = text; }
      // A 5xx/429, or a 200 whose body isn't JSON, is a proxy/relay blip — retry rather than trust it.
      if (res.status >= 500 || res.status === 429 || !parsed) {
        lastTransient = new RelayUnreachable("relay returned HTTP " + res.status);
        continue;
      }
      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      if (!isTransient(e)) throw e;      // a real bug in our code, not a reachability blip
      lastTransient = e;
    }
  }
  throw lastTransient || new RelayUnreachable("relay unreachable");
}

// The latest block, or null when the relay is momentarily unreachable (never throws for a blip, so the
// poll loop just shows "disconnected" and retries next tick instead of logging an error).
async function getLatestBlock() {
  try { return (await rpcJSON("/get_latest_block")).data; }
  catch (e) { if (isTransient(e)) return null; throw e; }
}
async function getAccount(address) {
  try {
    const r = await rpcJSON("/get_account?address=" + encodeURIComponent(address));
    return r.ok ? r.data : null;
  } catch (e) { if (isTransient(e)) return null; throw e; }   // relay blip -> unknown, not an error
}
async function getMiningStatus(address) {
  try {
    const r = await rpcJSON("/mining_status?address=" + encodeURIComponent(address));
    return r.ok ? r.data : null;
  } catch (e) { if (isTransient(e)) return null; throw e; }
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
  // A non-JSON body means the relay/proxy returned an HTML error page (e.g. a Cloudflare 502). NEVER surface
  // that raw HTML — it would render a whole page inside an alert. Show a clean status-coded message instead.
  try { data = JSON.parse(text); }
  catch { data = { result: false, message: res.ok ? (text || "").slice(0, 200)
    : i18("err.relayHttp", "The relay is unreachable right now (HTTP {s}). Please try again in a moment.", { s: res.status || "?" }) }; }
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
// H-5: coerce a relay-supplied field to a plain number before interpolating it into innerHTML. A hostile (or
// MITM'd) relay can return ANY JSON for /mining_status, /status, /htlcs, etc.; `x ?? 0` only replaces
// null/undefined and passes a hostile STRING through unchanged, so an "<img src=x onerror=…>" payload would be
// parsed into the DOM and could exfiltrate the (default-plaintext) wallet seed. `+x` turns any non-numeric
// value into NaN → 0, so no markup can ever reach a numeric sink. Non-numeric relay strings that must be shown
// (hashes, addresses, statuses) go through escapeHtml instead.
function num(x) { return Number.isFinite(+x) ? +x : 0; }
// H-5 companion: BigInt() throws on a non-numeric string, which would break a whole relay-driven list render;
// return 0n instead so one hostile field can't blank the UI (and can't inject — the value is used numerically).
function bnum(x) { try { return BigInt(x || 0); } catch { return 0n; } }

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

// Estimate the bonded ("savings") lane APY from recent on-chain performance, plus the presence dividend.
// Reward model (protocol.py): a bonded block pays the producer 70% (dividend 20%, treasury 10%); an open block
// pays the producer 20% (dividend 70%, treasury 10%). The bonded lane mints (epoch_length - k_open)/epoch_length
// of blocks (~80%). Bonded rewards are shared across all bonded shares (B_MIN = 1,000 NADO each), so the APY on
// staked capital ≈ (annual bonded producer reward ÷ total bonded shares) ÷ B_MIN. The dividend is paid to
// PRESENT open-lane miners (not to stake), so it's shown separately as a capital-free bonus.
const B_MIN_RAW = 100_000_000_000n;        // protocol.py B_MIN: 10 NADO per bonded selection share — MUST track the node
const BASE_SUBSIDY_RAW = 1_000_000_000n;   // protocol.py: 0.1 NADO/block reward floor
async function estimateSavingsApy() {
  const box = $("apyResult");
  if (!box) return;
  box.textContent = i18("apy.calc", "estimating from recent blocks…");
  try {
    const addr = state.wallet && state.wallet.address;
    // rpcJSON returns a {ok,status,data} envelope — unwrap .data (reading fields off the envelope zeroed
    // out total_bonded_shares / block_number / block_reward and produced the "0 blocks / no stake" bug).
    const ms = (await rpcJSON("/mining_status" + (addr ? "?address=" + encodeURIComponent(addr) : ""))).data || {};
    const tip = (await rpcJSON("/get_latest_block")).data || {};
    const n = num(tip.block_number);
    const nums = []; for (let i = 0; i < 30 && n - i > 0; i++) nums.push(n - i);
    const blks = await Promise.all(nums.map((x) => rpcJSON("/get_block_number?number=" + x).then((r) => r.data).catch(() => null)));
    const rewards = blks.filter(Boolean).map((b) => { try { return BigInt(b.block_reward || 0); } catch { return 0n; } }).filter((r) => r > 0n);
    const avgReward = rewards.length ? Number(rewards.reduce((a, b) => a + b, 0n) / BigInt(rewards.length)) : Number(BASE_SUBSIDY_RAW);
    const blockTime = num(ms.block_time) || state.blockTime || 8;
    const epochLen = num(ms.epoch_length) || EPOCH_LENGTH;
    const kOpen = num(ms.k_open) || 12;
    const bondedFrac = (epochLen - kOpen) / epochLen, openFrac = kOpen / epochLen;
    // The relay's savings-lane total can lag a bond you made against a different node, and it counts a
    // newly-bonded identity's RAMPED weight (which starts small). Fall back to your OWN bonded shares — read
    // straight from your account balance, so a staker always gets a figure even if the lane total hasn't caught it.
    let totalShares = num(ms.total_bonded_shares), myShares = num(ms.my_bonded_shares);
    if (addr) {
      try {
        const acc = (await rpcJSON("/get_account?address=" + encodeURIComponent(addr))).data || {};
        myShares = Math.max(myShares, Number(BigInt(acc.bonded || 0) / B_MIN_RAW));   // shares = bonded // B_MIN
      } catch (e) { /* keep ms.my_bonded_shares */ }
    }
    const effTotal = Math.max(totalShares, myShares);   // never let a stale lane total zero out your APY
    const blocksYear = 31557600 / blockTime;
    const bondedBlocksYear = blocksYear * bondedFrac, openBlocksYear = blocksYear * openFrac;

    let head;
    if (effTotal > 0) {
      const perShareYearRaw = (avgReward * bondedBlocksYear * 0.70) / effTotal;   // raw/yr per bonded share
      const apy = (perShareYearRaw / Number(B_MIN_RAW)) * 100;
      const shown = apy >= 1000 ? Math.round(apy).toLocaleString() : apy.toFixed(1);
      head = `<b class="ok">${shown}% ${i18("apy.savings", "APY on bonded stake")}</b>`
        + (apy >= 500 ? ` <span class="faint">${i18("apy.earlyNote", "(very high while little is bonded — it falls as more coins stake)")}</span>` : "");
    } else {
      head = `<span class="faint">${i18("apy.noBond", "No bonded stake yet — APY is undefined until the savings lane has stake.")}</span>`;
    }
    // presence dividend: 20% of every bonded block + 70% of every open block, shared among present open miners
    const annualDivRaw = avgReward * (bondedBlocksYear * 0.20 + openBlocksYear * 0.70);
    const openMiners = Math.max(1, num(ms.open_registry_size));
    const divNado = rawToNado(BigInt(Math.max(0, Math.round(annualDivRaw / openMiners))));
    box.innerHTML = head
      + `<span class="faint"> · ${i18("apy.from", "from the last {n} blocks", { n: rewards.length })}</span>`
      + `<div class="faint mt">${i18("apy.divNote", "+ presence dividend ≈ {a} NADO/yr per present open-lane miner (a capital-free bonus if you also mine the open lane).", { a: divNado })}</div>`;
  } catch (e) {
    box.innerHTML = `<span class="warn">${i18("apy.err", "Couldn't estimate APY:")} ${escapeHtml(e.message)}</span>`;
  }
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
const LS_PENDING_CLAIM = "nado_pending_claim"; // sessionStorage: a banknote claim link awaiting wallet setup

function persistWallet(w) { localStorage.setItem(LS_WALLET, JSON.stringify(w)); }
function loadWallet() {
  try { return JSON.parse(localStorage.getItem(LS_WALLET)); } catch { return null; }
}

/* ----------------------------------------------------------------------------------------------
 * Wallet encryption at rest + auto-lock (WebCrypto: AES-256-GCM, key from PBKDF2-SHA256/210k).
 * The stored seed is either plaintext {privateKey,…} or an encrypted blob {enc:1,salt,iv,ct,address,
 * publicKey}. The decrypted seed lives ONLY in memory (state.wallet) while unlocked; locking clears it and
 * requires the password again. GCM authenticates, so a wrong password fails to decrypt (no silent garbage).
 * -------------------------------------------------------------------------------------------- */
const LS_AUTOLOCK = "nado_autolock_min";
let _autolockTimer = null;

// --- portable pure-JS authenticated cipher (blake2b), format v:2 -----------------------------------
// WebCrypto's crypto.subtle is a SECURE-CONTEXT-ONLY API, so it is undefined over plain http://<ip> (the way
// the light miner is usually served) — which made "Encrypt this wallet" crash with "…reading 'importKey'".
// crypto.getRandomValues IS available over http, and the wallet already vendors blake2b, so encryption uses an
// AES-free construction that works in ANY context: PBKDF2-style stretch with blake2b-keyed as the PRF, a
// blake2b-CTR keystream, and encrypt-then-MAC with a blake2b MAC (wrong password fails the MAC, like GCM auth).
// New wallets always use v:2 (portable across http/https/localhost); legacy AES-GCM blobs (v:1) still decrypt
// wherever crypto.subtle exists.
const _ENC_ITERS = 150000;
function _u8cat(...arrs) { let n = 0; for (const a of arrs) n += a.length; const o = new Uint8Array(n); let k = 0; for (const a of arrs) { o.set(a, k); k += a.length; } return o; }
function _prfKey(passBytes) { return blake2b(passBytes, { dkLen: 32 }); }   // normalise any password length to a 32-byte blake2b key
function _b2bKey(msg, key, dkLen) { return blake2b(msg, { dkLen, key }); }
function _deriveKeyJS(passBytes, salt, iters, dkLen) {
  const pk = _prfKey(passBytes);                          // PRF key (handles >64-byte passwords)
  let u = _b2bKey(_u8cat(salt, new Uint8Array([0, 0, 0, 1])), pk, 64);   // U1 = PRF(pw, salt||INT32(1))
  const out = u.slice();
  for (let i = 1; i < iters; i++) { u = _b2bKey(u, pk, 64); for (let k = 0; k < out.length; k++) out[k] ^= u[k]; }
  return out.slice(0, dkLen);
}
function _ctrXorJS(data, keyEnc, nonce) {
  const out = new Uint8Array(data.length);
  for (let off = 0; off < data.length; off += 64) {
    const blk = off >>> 6, ctr = new Uint8Array([(blk >>> 24) & 255, (blk >>> 16) & 255, (blk >>> 8) & 255, blk & 255]);
    const ks = _b2bKey(_u8cat(nonce, ctr), keyEnc, 64);   // keystream block = keyed-hash(nonce || counter)
    for (let i = 0; i < 64 && off + i < data.length; i++) out[off + i] = data[off + i] ^ ks[i];
  }
  return out;
}
function _ctEqJS(a, b) { if (a.length !== b.length) return false; let d = 0; for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i]; return d === 0; }
function encryptSeedJS(seedHex, password) {
  const pw = new TextEncoder().encode(password);
  const salt = crypto.getRandomValues(new Uint8Array(16)), nonce = crypto.getRandomValues(new Uint8Array(16));
  const dk = _deriveKeyJS(pw, salt, _ENC_ITERS, 64), keyEnc = dk.slice(0, 32), keyMac = dk.slice(32, 64);
  const ct = _ctrXorJS(hexToBytes(seedHex), keyEnc, nonce);
  const tag = _b2bKey(_u8cat(nonce, ct), keyMac, 32);
  return { enc: 1, v: 2, iters: _ENC_ITERS, salt: _hex(salt), iv: _hex(nonce), ct: _hex(ct), tag: _hex(tag) };
}
function decryptSeedJS(blob, password) {
  const pw = new TextEncoder().encode(password);
  const dk = _deriveKeyJS(pw, hexToBytes(blob.salt), blob.iters || _ENC_ITERS, 64);
  const keyEnc = dk.slice(0, 32), keyMac = dk.slice(32, 64);
  const ct = hexToBytes(blob.ct), nonce = hexToBytes(blob.iv);
  if (!_ctEqJS(_b2bKey(_u8cat(nonce, ct), keyMac, 32), hexToBytes(blob.tag))) throw new Error("bad password");
  return _hex(_ctrXorJS(ct, keyEnc, nonce));
}

// --- legacy AES-GCM (format v:1) — decrypt-only, for wallets encrypted in a secure context ---------
async function _deriveAesKey(password, salt) {
  const km = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 210000, hash: "SHA-256" },
    km, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
async function encryptSeed(seedHex, password) {
  if (!blake2b) throw new Error(i18("sec.notReady", "Crypto still loading — try again in a moment."));
  return encryptSeedJS(seedHex, password);                // portable v:2 (works over http)
}
async function decryptSeed(blob, password) {
  if (blob.v === 2 || blob.tag) return decryptSeedJS(blob, password);
  // legacy v:1 AES-GCM needs WebCrypto (secure context only)
  if (!(globalThis.crypto && crypto.subtle)) throw new Error(i18("sec.needSecure", "This wallet was encrypted with WebCrypto — open it over HTTPS or on localhost to unlock, then re-encrypt to make it portable."));
  const key = await _deriveAesKey(password, hexToBytes(blob.salt));
  const pt = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: hexToBytes(blob.iv) }, key, hexToBytes(blob.ct)));
  return _hex(pt);
}
function walletIsEncrypted() { const w = loadWallet(); return !!(w && w.enc); }

async function enableEncryption(password) {
  if (!state.wallet || !password) return;
  // HD SAFETY: always encrypt the MASTER seed (never the active derived child) so the stored/encrypted
  // wallet remains the one recovery phrase that restores every account.
  const seed = masterSeedOf() || state.wallet.privateKey;
  const mk = keypairFromPriv(seed);
  const blob = await encryptSeed(seed, password);
  blob.publicKey = mk.publicKey; blob.address = mk.address;
  localStorage.setItem(LS_WALLET, JSON.stringify(blob));
  armAutolock();
}
async function disableEncryption(password) {
  const w = loadWallet();
  if (!w || !w.enc) return;
  const seed = await decryptSeed(w, password);          // throws on wrong password
  persistWallet(keypairFromPriv(seed));
  clearTimeout(_autolockTimer);
}

let _unlockLeaseTimer = null;
function showUnlock() {
  show("tabbar", false);
  document.querySelectorAll("[data-tab]").forEach((el) => show(el.id, false));
  show("onboard", false); show("savePrompt", false);
  const w = loadWallet();
  if ($("unlockAddr")) $("unlockAddr").textContent = (w && w.address) || "";
  if ($("unlockRelayUrl")) { $("unlockRelayUrl").value = state.relay || ""; $("unlockRelayUrl").placeholder = location.origin; }
  if ($("unlockPass")) $("unlockPass").value = "";
  if ($("unlockErr")) $("unlockErr").textContent = "";
  show("unlockCard", true);
  // A locked wallet is still MINING on-chain until its PoSW lease lapses — show how much presence is left
  // (we know the address even while locked). Refresh it periodically so the countdown stays live.
  show("unlockLease", false);
  refreshUnlockLease();
  clearInterval(_unlockLeaseTimer);
  _unlockLeaseTimer = setInterval(refreshUnlockLease, 30000);
}
// Populate the locked screen's "still mining, ~X left" banner from the stored address (no key needed).
async function refreshUnlockLease() {
  const box = $("unlockLease");
  const w = loadWallet();
  const addr = w && w.address;
  if (!box || !addr || !state.locked) return;
  try {
    const [acc, ms] = await Promise.all([getAccount(addr), getMiningStatus(addr)]);
    const regEpoch = (acc && typeof acc.reg_epoch === "number") ? acc.reg_epoch : -1;
    const present = !!(ms && ms.registered_present);
    if (present && regEpoch >= 0 && ms && typeof ms.epoch === "number") {
      const epochSecs = EPOCH_LENGTH * (ms.block_time || state.blockTime || 8);
      const secsLeft = Math.max(0, (regEpoch + POSW_LEASE_EPOCHS - ms.epoch) * epochSecs);
      box.innerHTML = "⛏ " + escapeHtml(i18("unlock.mining",
        "Still mining while locked — about {t} of presence left. Reopen before it runs out to auto-renew.",
        { t: humanizeSeconds(secsLeft) }));
      show("unlockLease", true);
    } else {
      show("unlockLease", false);
    }
  } catch (e) { /* relay hiccup — just leave the banner as-is */ }
}
function lockWallet() {
  if (!walletIsEncrypted() || state.locked) return;     // only an encrypted wallet can lock
  // PAUSE the auto-renew loop (we can't sign PoSW recerts while locked) but KEEP the intent flag, so
  // unlock resumes it. Your PoSW lease stays valid on-chain meanwhile, so you keep earning until it lapses.
  try { if (state.mining) pauseMining(); } catch (e) {}
  state.wallet = null; state.locked = true;
  clearTimeout(_autolockTimer);
  showUnlock();
}
// Stop the local auto-renew loop WITHOUT clearing the persisted intent (unlike stopMining()). The identity
// stays present on-chain (the PoSW lease), and unlock/refresh auto-resumes renewal from the intent flag.
function pauseMining() {
  state.mining = false; state.starting = false;
  if (state.powJob) state.powJob.cancelled = true;
  state.registering = false;
  stopPollLoop();
  releaseWakeLock();
}
async function unlockWallet(password) {
  const w = loadWallet();
  if (!w || !w.enc) return;
  const seed = await decryptSeed(w, password);          // throws on wrong password
  state.wallet = keypairFromPriv(seed); state.locked = false;
  clearInterval(_unlockLeaseTimer); _unlockLeaseTimer = null;
  show("unlockCard", false);
  showWalletUI(); armAutolock();
  // The poll loop skips refreshDashboard() while locked (state.wallet is null), so pull fresh balances /
  // mining status NOW instead of leaving stale data until the next poll tick (which looks like a freeze).
  refreshDashboard().catch(() => {});
  // Resume the mining the lock paused (LS_MINING intent survives a lock). startMining() re-runs the loop;
  // it won't re-register an already-present, lease-valid identity — it just resumes renewal.
  if (localStorage.getItem(LS_MINING) === "1") startMining();
  else if (!state.pollTimer) startPollLoop();            // else at least keep the dashboard live
}
// Remove the password from a LOCKED wallet in one step (still needs the password — the seed is encrypted).
// Decrypts, re-persists the key in plain text, and enters the app. For a user who wants to drop the lock
// without going Unlock -> Security -> Remove.
async function unlockRemovePassword(password) {
  const w = loadWallet();
  if (!w || !w.enc) return;
  await disableEncryption(password);                    // decrypts (throws on wrong password) + persists PLAINTEXT
  const plain = loadWallet();
  state.wallet = keypairFromPriv(plain.privateKey); state.locked = false;
  clearInterval(_unlockLeaseTimer); _unlockLeaseTimer = null; clearTimeout(_autolockTimer);
  show("unlockCard", false); showWalletUI();
  refreshDashboard().catch(() => {});
  if (localStorage.getItem(LS_MINING) === "1") startMining();
  else if (!state.pollTimer) startPollLoop();
}
function autolockMinutes() { return parseInt(localStorage.getItem(LS_AUTOLOCK) || "0", 10) || 0; }
function armAutolock() {
  clearTimeout(_autolockTimer);
  const m = autolockMinutes();
  if (m > 0 && walletIsEncrypted() && !state.locked) _autolockTimer = setTimeout(lockWallet, m * 60000);
}
function bumpAutolock() { if (!state.locked && state.wallet) armAutolock(); }
function renderSecurity() {
  const enc = walletIsEncrypted();
  if ($("secStatus")) $("secStatus").innerHTML = enc
    ? '<b class="ok">' + i18("sec.on", "Encrypted at rest ✓") + "</b>"
    : '<span class="faint">' + i18("sec.off", "Not encrypted — stored in plain text on this device.") + "</span>";
  show("btnEncrypt", !enc);
  show("btnRemoveEnc", enc);
  show("btnLockNow", enc);
  show("btnDlEnc", enc);
  if ($("autolockSel")) $("autolockSel").value = String(autolockMinutes());
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
// SELF-HEALING: the failure is often STALE — e.g. a re-register is rejected as a duplicate while the
// original tx lands a block later, or the relay hiccuped after actually accepting it. With the poll
// loop stopped, that used to leave a false "didn't confirm" banner until a page refresh. So after
// failing we quietly re-check the chain a few times, and if the registration turns out to have landed
// (registered + lease valid), we resume mining automatically — same outcome as the refresh, minus the user.
let _failRecheckTimer = null;
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
  clearTimeout(_failRecheckTimer);
  let tries = 0;
  const recheck = async () => {
    if (state.mining || state.registering || !state.wallet) return;   // user restarted / logged out meanwhile
    try {
      const [latest, acc] = await Promise.all([getLatestBlock(), getAccount(state.wallet.address)]);
      const tip = latest && typeof latest.block_number === "number" ? latest.block_number : null;
      const epochNow = tip != null ? Math.floor((tip + 8) / EPOCH_LENGTH) : null;
      const regEpoch = (acc && typeof acc.reg_epoch === "number") ? acc.reg_epoch : -1;
      if (acc && acc.registered === 1 && epochNow != null && regEpoch >= 0
          && (epochNow - regEpoch) < POSW_LEASE_EPOCHS) {
        log("ok", i18("log.regHealed", "Registration confirmed on chain after all ✓ — resuming mining automatically."));
        state.mining = true;
        startPollLoop();
        pollOnce();                                       // confirms, flips the button, starts heartbeats
        return;
      }
    } catch (e) { /* relay still unreachable — keep the retry banner */ }
    if (++tries < 5) _failRecheckTimer = setTimeout(recheck, 15000);  // ~4 more blocks of patience
  };
  _failRecheckTimer = setTimeout(recheck, 12000);
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
    log("info", i18("log.leaseRenewing", "Presence lease expiring — renewing (fresh sequential proof)…"));
    // Up to 2 attempts: if the chain outran max_block while the (pure-JS) PoW was computing, recompute
    // against a fresh tip. Each attempt targets tip + POSW_TARGET_MARGIN (max headroom for the proof).
    let lastMsg = "";
    for (let attempt = 0; attempt < 2; attempt++) {
      const latest = await getLatestBlock();
      if (!latest || typeof latest.block_number !== "number") return;
      const tx = await computeRegisterTx(latest.block_number + POSW_TARGET_MARGIN, null,
        (await registrationDifficulty()).reqT);   // quiet: no UI takeover; still prove at the required difficulty
      const res = await submitTransaction(tx);
      if (res.data && res.data.result) { log("ok", i18("log.leaseRenewed", "Presence lease renewed ✓")); return; }
      lastMsg = (res.data && res.data.message) || "";
      if (!/too low/i.test(lastMsg)) break;   // a different rejection won't be fixed by retrying
    }
    log("err", i18("log.leaseRejected", "Lease renewal rejected: {m}", { m: lastMsg }));
  } catch (e) { log("err", i18("log.leaseError", "Lease renewal error: {m}", { m: e.message })); }
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
    // A momentarily-unreachable relay (node restart/crash-restart, a proxy 502) is NOT a registration
    // failure — the poll loop retries every ~second. Show a soft "reconnecting" banner and bail WITHOUT
    // logging an error or tearing down mining, so a 5 s node bounce never scares the user.
    if (isTransient(e)) {                          // finally{} below clears state.registering
      setConn(false);
      setRegBanner(i18("reg.reconnecting", "Relay momentarily unreachable — reconnecting…"), "warn");
      return;
    }
    if (e.message !== "cancelled") { log("err", "Auto-register error: " + e.message); failed = e.message; }
  } finally {
    state.registering = false;
  }
  if (!state.mining) return;                      // user stopped/cancelled while we were working
  if (failed || !accepted) {
    // A rejection/error is often STALE: a re-register gets refused as a duplicate precisely because
    // the earlier tx just landed (or presence is already established). Ask the chain before scaring
    // the user — if we're in fact registered, keep the loop alive and let pollOnce confirm quietly.
    try {
      const acc2 = await getAccount(state.wallet.address);
      if (acc2 && acc2.registered === 1) { show("powWrap", false); return; }
    } catch (e) { /* fall through to the real failure path */ }
    failStart(failed || "the relay rejected the registration"); // genuine failure → retry, no spam
  }
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
  // need latest block for max_block
  const latest = await getLatestBlock();
  if (!latest || typeof latest.block_number !== "number") throw new RelayUnreachable("relay /get_latest_block unavailable");
  state.latest = latest.block_number;
  const targetBlock = latest.block_number + POSW_TARGET_MARGIN;  // headroom so the tx lands before its target block

  // compute the registration Proof of SEQUENTIAL Work (non-parallelizable ~1 s chain, replaces hashcash)
  // Registration difficulty (consensus, scales with load) + a device-calibrated wait estimate, shown up front.
  const diff = await registrationDifficulty();
  const etaSec = Math.max(1, Math.ceil(diff.reqT / poswRate()));
  setStartBtnBusy(i18("mine.registering", "Registering…"));
  const busyNote = diff.mult > 1
    ? " " + i18("reg.difficultyHigh", "Network is busy — ×{m} difficulty from {n} recent registrations.", { m: diff.mult, n: diff.recent })
    : "";
  setRegBanner(i18("reg.computingEta", "Computing your one-time registration proof — about {s}s on this device.", { s: etaSec }) + busyNote + REASSURE);
  showRegProgress(i18("reg.computingLabel", "Registering — computing sequential proof-of-work…"), i18("reg.starting", "starting…"));
  let tx;
  const t0 = Date.now();
  try {
    tx = await computeRegisterTx(targetBlock, (done, total) => {
      const el = (Date.now() - t0) / 1000;
      const rate = (done > 0 && el > 0) ? done / el : poswRate();
      const remain = Math.max(0, Math.ceil((total - done) / rate));
      $("powStats").textContent = i18("reg.progress", "{done} / {total} · {el}s · ~{remain}s left",
        { done: done.toLocaleString(), total: total.toLocaleString(), el: el.toFixed(1), remain });
    }, diff.reqT);
  } finally {
    show("powWrap", false);
  }
  savePoswRate(diff.reqT, Date.now() - t0);
  log("ok", `Sequential PoW computed in ${((Date.now() - t0) / 1000).toFixed(1)}s (${diff.reqT.toLocaleString()} hashes${diff.mult > 1 ? `, ×${diff.mult} difficulty` : ""}).`);
  setRegBanner(i18("reg.submitting", "Submitting registration to the network…") + REASSURE);
  log("info", `Submitting register tx ${tx.txid.slice(0, 16)}… (max_block ${targetBlock}).`);
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
    } else {
      setConn(false);                 // null = relay momentarily unreachable (getLatestBlock ate the blip)
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

  // RANDAO duty — runs whether or not the open-lane miner is on: bonded stake earns NOTHING in an
  // epoch it didn't reveal for (mandatory RANDAO), so any unlocked wallet holding >= B_MIN bonded
  // participates while the tab is open. No-op for everyone else (one cheap /get_account check).
  try { await maybeRandao(); } catch (e) { /* best-effort */ }
}

function startPollLoop() {
  stopPollLoop();
  const periodMs = Math.max(8000, Math.min(state.blockTime, 60) * 1000);
  state.pollTimer = setInterval(pollOnce, periodMs);
  // seamless shielded withdrawals: quietly sweep any settled unshield into the balance in the background
  if (!state.claimTimer) state.claimTimer = setInterval(() => {
    if (state.wallet && !state.locked && loadNotes().length) claimUnshields(true).catch(() => {});
  }, 45000);
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
  clearTimeout(_failRecheckTimer);                           // an explicit stop must not self-heal back to mining
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
let _wealthCache = { at: 0, stats: null };
async function getWealthStats() {
  const now = Date.now();
  if (now - _wealthCache.at < 15000 && _wealthCache.stats) return _wealthCache.stats;
  try {
    const r = await fetch(relayBase() + "/wealth_stats", { cache: "no-store" });
    const d = await r.json();
    _wealthCache = { at: now, stats: {
      count: num(d.count) || 0, richest: BigInt(d.richest || 0),
      logMean: Number(d.log_mean) || 0, logStd: Number(d.log_std) || 0,
    } };
  } catch (e) { /* keep last */ }
  return _wealthCache.stats;
}
// Standard-normal CDF (Abramowitz-Stegun erf 7.1.26). Wealth is log-normal, so a wallet's RANK is Φ of its
// z-score on ln(total) = the fraction of wallets it is richer than — a robust distribution rank, not "% of
// the single richest wallet" (which one whale dominates).
function _erf(x) {
  const s = x < 0 ? -1 : 1; x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t) * Math.exp(-x * x);
  return s * y;
}
function _normalCdf(z) { return 0.5 * (1 + _erf(z / Math.SQRT2)); }
const PILE_MAX_LEVELS = 7;
// MATERIAL TIERS: as your share of the richest wallet climbs, the pile ramps in quantity, then advances
// material — bronze → silver → gold → diamond — resetting to a small pile of the shinier metal each step.
const PILE_TIERS = [
  { id: "bronze",  g: ["#e8a866", "#cd7f32", "#8a5a1e"], base: "#5f3d14", hi: "#f6d6a8", stroke: "#7a4e1a", key: "pile.bronze",  en: "bronze" },
  { id: "silver",  g: ["#f7f9fb", "#cbd3db", "#8a94a0"], base: "#5f6874", hi: "#ffffff", stroke: "#98a2ae", key: "pile.silver",  en: "silver" },
  { id: "gold",    g: ["#ffe066", "#f5c542", "#d69a1e"], base: "#8a6a12", hi: "#fff3c4", stroke: "#a9781a", key: "pile.gold",    en: "gold" },
  { id: "diamond", g: ["#eafcff", "#a7e9f7", "#54c6ea"], base: "#2f7fa0", hi: "#ffffff", stroke: "#7fd3ec", key: "pile.diamond", en: "diamond" },
];
// map a 0..1 PERCENTILE (fraction of wallets you're richer than) to {t: tier index, fill: progress WITHIN
// the tier}. Bronze = the bottom majority; silver/gold/diamond are the 60th / 90th / 99th-percentile bands —
// distribution-based, so a single whale no longer makes everyone else "bronze".
function _pileTier(pctile) {
  const bands = [0, 0.60, 0.90, 0.99, 1.0001];
  for (let t = 0; t < 4; t++) if (pctile < bands[t + 1]) return { t, fill: Math.max(0, Math.min(1, (pctile - bands[t]) / (bands[t + 1] - bands[t]))) };
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
function renderCoinPile(totalRaw, stats) {
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
  const rich = (stats && stats.richest > 0n) ? stats.richest : 0n;
  const isTop = totalRaw > 0n && rich > 0n && totalRaw >= rich;    // you're the richest (or tied / network unknown)
  // log-normal percentile: the fraction of wallets this total is richer than (Φ of its z-score on ln(total)).
  let pctile;
  if (stats && stats.count > 1 && stats.logStd > 1e-9) {
    pctile = Math.max(0, Math.min(1, _normalCdf((Math.log(Number(totalRaw)) - stats.logMean) / stats.logStd)));
  } else {
    pctile = isTop ? 1 : 0.5;                                      // degenerate/unknown population -> neutral
  }
  const { t: tierIdx, fill } = _pileTier(pctile);
  const m = PILE_TIERS[tierIdx];
  state.walletTierIdx = tierIdx;                                        // remember tier -> the collect coin-shower matches it
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
  else { const p = Math.round(pctile * 100); cap.textContent = i18("pile.richerThan", "richer than {p}% of wallets", { p }) + " · " + tierName; }
}
async function updateCoinPile(totalRaw) {
  try { renderCoinPile(totalRaw, await getWealthStats()); } catch (e) { /* non-fatal cosmetic */ }
}

// COIN SHOWER: clicking "Collect dividend" springs a small shower of coins out of the button. The METAL and
// the COUNT scale with your wallet tier (bronze → silver → gold → diamond — the same tiers as the coin pile),
// so a richer wallet gets a shinier, denser burst; the top tier rains faceted gems. Pure DOM + one rAF loop,
// self-cleaning, and it honours prefers-reduced-motion. Cosmetic only — never throws into the collect flow.
const _SHOWER_TIERS = [
  { n: 12, sz: [12, 16], burst: [7, 12],  gem: false },   // bronze
  { n: 16, sz: [13, 18], burst: [8, 13],  gem: false },   // silver
  { n: 22, sz: [14, 20], burst: [9, 15],  gem: false },   // gold
  { n: 28, sz: [13, 18], burst: [10, 16], gem: true  },   // diamond → gems
];
function coinShower(originEl) {
  try {
    if (!originEl) return;
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const tierIdx = Math.max(0, Math.min(3, (state && state.walletTierIdx) || 0));
    const m = PILE_TIERS[tierIdx], cfg = _SHOWER_TIERS[tierIdx];
    const rect = originEl.getBoundingClientRect();
    const rnd = (a, b) => a + Math.random() * (b - a);
    // Native `title` tooltips are painted by the browser ABOVE all page content — above our z-index — so an
    // open explanation tooltip (e.g. #divWrap's PRESENCE-DIVIDEND title) would cover the whole shower. Strip
    // any titled ancestor for the shower's lifetime (this also dismisses an already-visible tooltip), restore after.
    const titled = [];
    for (let n = originEl; n && n !== document.body; n = n.parentElement) {
      if (n.hasAttribute && n.hasAttribute("title")) { titled.push([n, n.getAttribute("title")]); n.removeAttribute("title"); }
    }
    const restoreTitles = () => { for (const [n, t] of titled) if (n && !n.hasAttribute("title")) n.setAttribute("title", t); };
    setTimeout(restoreTitles, 1700);          // safety restore even if the rAF loop is paused (backgrounded tab)
    let layer = document.getElementById("coinShowerLayer");
    if (!layer) {
      layer = document.createElement("div");
      layer.id = "coinShowerLayer";
      layer.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:9999;overflow:hidden";
      document.body.appendChild(layer);
    }
    const coins = [];
    for (let i = 0; i < cfg.n; i++) {
      const sz = rnd(cfg.sz[0], cfg.sz[1]);
      const el = document.createElement("div");
      el.style.position = "absolute";
      el.style.left = "0"; el.style.top = "0";
      el.style.width = sz + "px"; el.style.height = sz + "px";
      el.style.willChange = "transform, opacity";
      if (cfg.gem) {
        el.style.clipPath = "polygon(50% 0,100% 34%,82% 100%,18% 100%,0 34%)";
        el.style.background = "linear-gradient(150deg," + m.hi + "," + m.g[1] + " 55%," + m.g[2] + ")";
        el.style.boxShadow = "0 0 " + (sz * 0.5) + "px " + m.g[0] + "aa";
      } else {
        el.style.borderRadius = "50%";
        el.style.background = "radial-gradient(circle at 34% 30%," + m.hi + "," + m.g[1] + " 55%," + m.g[2] + ")";
        el.style.border = "1px solid " + m.stroke;
        el.style.boxShadow = "0 0 " + (sz * 0.35) + "px " + m.g[0] + "88, inset 0 1px 1px " + m.hi;
      }
      layer.appendChild(el);
      coins.push({
        el,
        x: rnd(rect.left + rect.width * 0.2, rect.left + rect.width * 0.8),
        y: rect.top + rnd(-2, rect.height * 0.5),
        vx: rnd(-4.5, 4.5), vy: -rnd(cfg.burst[0], cfg.burst[1]),
        rot: rnd(0, 360), vrot: rnd(-16, 16),
        life: rnd(950, 1500), born: 0,
      });
    }
    const G = 0.42, DRAG = 0.995;
    let last = null;
    function frame(now) {
      if (last == null) { last = now; for (const c of coins) c.born = now; }
      const dt = Math.min(2.5, (now - last) / 16.6667); last = now;
      let alive = 0;
      for (const c of coins) {
        if (!c.el) continue;
        const age = now - c.born;
        if (age >= c.life) { c.el.remove(); c.el = null; continue; }
        alive++;
        c.vy += G * dt; c.vx *= Math.pow(DRAG, dt);
        c.x += c.vx * dt; c.y += c.vy * dt; c.rot += c.vrot * dt;
        c.el.style.opacity = age > c.life - 420 ? Math.max(0, (c.life - age) / 420) : 1;
        c.el.style.transform = "translate(" + c.x + "px," + c.y + "px) rotate(" + c.rot + "deg)";
      }
      if (alive) requestAnimationFrame(frame);
      else { restoreTitles(); if (layer && !layer.children.length) layer.remove(); }
    }
    requestAnimationFrame(frame);
  } catch (e) { /* cosmetic only */ }
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

  // H-5: coerce every relay-supplied field to a number before it reaches the innerHTML sink below.
  const myOpen = num(ms.my_open_weight), totOpen = num(ms.total_open_weight);
  const myBond = num(ms.my_bonded_shares), totBond = num(ms.total_bonded_shares);
  const openReg = num(ms.open_registry_size), bondReg = num(ms.bonded_registry_size);
  const sharePct = totOpen ? ((myOpen / totOpen) * 100).toFixed(1) : "0.0";

  // "Who's in each lane" participant counts + lane totals (same /mining_status fields).
  $("laneOpenCount").textContent = openReg;
  $("laneBondedCount").textContent = bondReg;
  $("laneOpenWeight").textContent = totOpen;
  $("laneBondedShares").textContent = totBond;

  $("myShare").innerHTML =
    `${i18("myshare.weight", "Your open-lane weight:")} <b>${myOpen}</b> / ${totOpen} (${sharePct}% ${i18("myshare.ofFree", "of the free lane")}). ` +
    `${i18("myshare.openReg", "Open registry:")} ${openReg} ${i18("lane.miners", "miners")} · ${i18("myshare.bondShares", "Savings shares:")} ${myBond}/${totBond} · ` +
    `${i18("myshare.bondReg", "Savings registry:")} ${bondReg}.`;

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

// ---- FORUM SSO: forum.nadochain.com bounces the user here to sign a one-time login challenge with their
// wallet. We show exactly what they're signing, sign with the ACTIVE account (so HD accounts pick their forum
// identity), and POST the signature back to the forum as a top-level navigation POST (no CORS). Only a
// hardcoded-allowlisted forum origin is ever sent a signature — a login sig is domain-tagged ("nado-forum-login")
// so it can NEVER be replayed as a transaction, but we still refuse unknown targets as defense-in-depth.
const FORUM_ORIGIN_ALLOW = ["https://forum.nadochain.com"];
let pendingForumLogin = (() => {
  try {
    const p = new URLSearchParams(location.search);
    const rid = p.get("forum_login");
    if (!rid) return null;
    return { rid, nonce: p.get("nonce") || "", forum: p.get("forum") || "", issued: parseInt(p.get("issued") || "0", 10) };
  } catch (e) { return null; }
})();
async function resumePendingForumLogin() {
  const req = pendingForumLogin;
  if (!req || !state.wallet) return;
  pendingForumLogin = null;                        // consume — don't re-prompt on later showWalletUI calls
  try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) {}   // scrub the params
  if (!FORUM_ORIGIN_ALLOW.includes(req.forum)) {
    uiAlert(i18("forum.badOrigin", "Ignored a sign-in request for an unrecognised site.") + " (" + req.forum + ")");
    return;
  }
  const okc = await uiConfirm({
    title: i18("forum.title", "Sign in to NADO Forum"),
    body: i18("forum.body", "Prove you own this wallet to sign in to {f} as {a}. This cannot move funds.",
      { f: req.forum.replace(/^https?:\/\//, ""), a: state.wallet.address.slice(0, 14) + "…" }),
    confirmText: i18("forum.signin", "Sign in"),
  });
  if (!okc) return;
  try {
    const msg = blake2bHash(["nado-forum-login", req.forum, state.wallet.address, req.nonce, req.issued], 32);
    const { publicKey, secretKey } = ml_dsa44.keygen(hexToBytes(state.wallet.privateKey));
    const mb = hexToBytes(msg);
    let signature = null;
    for (let i = 0; i < 8; i++) {                    // re-sign on the rare non-verifying hedge (see finalizeTransaction)
      const sig = ml_dsa44.sign(secretKey, mb);
      if (ml_dsa44.verify(publicKey, mb, sig)) { signature = bytesToHex(sig); break; }
    }
    if (!signature) throw new Error("could not produce a verifying signature");
    const form = document.createElement("form");
    form.method = "POST"; form.action = req.forum + "/api/sso_callback";
    for (const [n, v] of [["request_id", req.rid], ["address", state.wallet.address],
                          ["public_key", state.wallet.publicKey], ["signature", signature]]) {
      const i = document.createElement("input"); i.type = "hidden"; i.name = n; i.value = v; form.appendChild(i);
    }
    document.body.appendChild(form);
    form.submit();                                 // navigates to the forum, which verifies + sets the session cookie
  } catch (e) {
    uiAlert(i18("forum.failed", "Forum sign-in failed:") + " " + (e && e.message ? e.message : e));
  }
}

// ---- dApp exec-call signing: a NADO dApp (e.g. coinflip.nadochain.com) bounces the user here to sign & submit
// ONE execution-layer contract call with their wallet, then returns. Same redirect pattern as the forum SSO,
// but this signs a REAL (fee-only) blob tx — so we confirm explicitly, only return to an ALLOWLISTED dApp
// origin, and it can never move funds beyond the network fee (a `blob` tx has amount 0).
const EXEC_SIGN_ALLOW = ["https://coinflip.nadochain.com", "https://roulette.nadochain.com", "https://dice.nadochain.com", "https://chess.nadochain.com", "https://poker.nadochain.com", "https://farkle.nadochain.com", "https://pets.nadochain.com", "https://slots.nadochain.com", "https://tictactoe.nadochain.com"];
let pendingExecSign = (() => {
  try {
    const p = new URLSearchParams(location.search);
    const b = p.get("exec_sign");
    return b ? { payload: b, ret: p.get("ret") || "", app: p.get("app") || "a dApp" } : null;
  } catch (e) { return null; }
})();
function _decodeArg(a) { return (a && typeof a === "object" && "$big" in a) ? BigInt(a.$big) : a; }   // 256-bit args ride as {$big:"…"}
async function resumePendingExecSign() {
  const req = pendingExecSign;
  if (!req || !state.wallet) return;
  pendingExecSign = null;
  try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) {}
  let call, retUrl;
  try { call = JSON.parse(decodeURIComponent(escape(atob(req.payload)))); retUrl = new URL(req.ret); }
  catch (e) { uiAlert(i18("dapp.bad", "Ignored a malformed signing request.")); return; }
  // The origin allowlist is the default guard. A user can opt to skip it (Settings → "Trust any site that
  // asks me to sign") — unknown origins then get a LOUDER confirm that names the origin, never a silent pass.
  const skipOriginCheck = localStorage.getItem("nado_skip_origin_check") === "1";
  const trustedOrigin = EXEC_SIGN_ALLOW.includes(retUrl.origin);
  if (!trustedOrigin && !skipOriginCheck) {
    uiAlert(i18("dapp.badOrigin", "Ignored a signing request for an unrecognised site.") + " (" + retUrl.origin + ")");
    return;
  }
  const back = (params) => { location.href = req.ret + (req.ret.includes("?") ? "&" : "?") + params; };
  if (call.connect) {   // lightweight "sign in": just return the wallet address, no transaction, no fee
    const c = await uiConfirm({
      title: i18("dapp.connectTitle", "Sign in"),
      body: i18("dapp.connectBody", "{app} wants your wallet address ({a}) to sign you in. No transaction — nothing moves.",
        { app: req.app, a: state.wallet.address.slice(0, 14) + "…" }),
      confirmText: i18("dapp.connect", "Sign in"),
    });
    back(c ? "ok=1&addr=" + state.wallet.address : "ok=0");
    return;
  }
  if (call.deposit) {   // BRIDGE DEPOSIT: move the user's OWN L1 funds into their OWN exec balance (safe, bounded — no third-party recipient)
    let amt; try { amt = BigInt(call.deposit.amount); } catch (e) { back("ok=0&err=bad+amount"); return; }
    if (amt <= 0n) { back("ok=0"); return; }
    const okc = await uiConfirm({
      title: i18("dapp.depTitle", "Deposit to the exec layer"),
      body: i18("dapp.depBody", "{app}: move {n} NADO from your L1 balance into your execution-layer balance so you can stake it — it stays yours.",
        { app: req.app, n: rawToNado(amt) }),
      rows: [{ k: i18("dapp.amount", "Amount"), v: rawToNado(amt) + " NADO" }],
      confirmText: i18("dapp.deposit", "Deposit"),
    });
    if (!okc) { back("ok=0"); return; }
    try {
      const { res, tx } = await submitResilient(async () => {
        const latest = await getLatestBlock();
        if (!latest) throw new Error("relay unavailable");
        const draft = { sender: state.wallet.address, recipient: "bridge", amount: amt, timestamp: nowSeconds(),
          data: "", nonce: randNonce(), public_key: state.wallet.publicKey, max_block: latest.block_number + 300, chain_id: CHAIN_ID };
        return finalizeTransaction(draft, state.wallet.privateKey, MIN_TX_FEE);
      });
      back(res && res.data && res.data.result ? "ok=1&txid=" + tx.txid + "&addr=" + state.wallet.address
                                       : "ok=0&err=" + encodeURIComponent(((res && res.data && res.data.message) || "rejected").slice(0, 80)));
    } catch (e) { back("ok=0&err=" + encodeURIComponent(String(e.message || e).slice(0, 80))); }
    return;
  }
  // decode {$big} recursively so 256-bit args (commit hashes) rebuild as BigInt anywhere in the payload
  const decodeDeep = (v) => Array.isArray(v) ? v.map(decodeDeep)
    : (v && typeof v === "object") ? ("$big" in v ? BigInt(v.$big) : Object.fromEntries(Object.keys(v).map((k) => [k, decodeDeep(v[k])])))
    : v;
  // the dApp may send a FULL blob payload (call.blob) or the legacy {cid,method,args} call shape
  const blob = decodeDeep(call.blob || { op: "call", contract: call.cid, method: call.method, args: call.args || [] });
  if (call.ns && call.ns !== "default" && blob.ns === undefined) blob.ns = call.ns;
  // AUDIT FIX: show the REAL action (op + key fields), never just the dApp's free-text label, so the confirm can't be spoofed
  const rows = [{ k: i18("dapp.action", "Action"), v: String(blob.op || "call") }];
  if (blob.contract) rows.push({ k: i18("dapp.contract", "Contract"), v: String(blob.contract).slice(0, 22) });
  if (blob.method)   rows.push({ k: i18("dapp.method", "Method"), v: String(blob.method) });
  if (blob.game !== undefined)  rows.push({ k: i18("dapp.game", "Game"), v: String(blob.game) });
  try { if (blob.stake  !== undefined) rows.push({ k: i18("dapp.stake", "Stake"),  v: rawToNado(BigInt(blob.stake)) + " NADO" }); } catch (e) {}
  try { if (blob.amount !== undefined && blob.amount) rows.push({ k: i18("dapp.amount", "Amount"), v: rawToNado(BigInt(blob.amount)) + " NADO" }); } catch (e) {}
  // A `call` can carry VALUE — real NADO escrowed from YOUR exec balance into the contract. Show it prominently
  // (it can't be spoofed by the dApp's label) so signing a staking call is always an informed choice.
  let escrow = 0n; try { escrow = blob.value ? BigInt(blob.value) : 0n; } catch (e) { escrow = 0n; }
  if (escrow > 0n) rows.push({ k: i18("dapp.escrows", "Escrows from your exec balance"), v: rawToNado(escrow) + " NADO" });
  // AUTOSIGN (opt-in): value-free contract calls from APPROVED game origins (chess moves, settles, reveals —
  // nothing escrows, nothing moves beyond the network fee) can sign+submit without the confirm tap, so a game
  // isn't interrupted on every action. Anything that moves NADO (value/deposit/withdraw) ALWAYS confirms.
  const AUTOSIGN_KEY = "nado_autosign_dapp";
  const valueFree = escrow === 0n && (blob.op || "call") === "call" && blob.amount === undefined && !call.confirm;
  // BET CAP: a `call` that escrows NADO (a slot spin, a small bet) can also auto-sign — but ONLY up to a
  // user-set ceiling, so a game can never quietly drain more than you allow. 0 (default) = always confirm
  // bets. The escrow is from the bounded EXEC/playable balance, never L1, and only from trusted origins.
  let betCap = 0n; try { betCap = BigInt(localStorage.getItem("nado_autosign_bet_cap_raw") || "0"); } catch (e) { betCap = 0n; }
  const smallBet = escrow > 0n && escrow <= betCap && (blob.op || "call") === "call" && blob.amount === undefined && !call.confirm;
  const submitBlob = async () => {
    const { res, tx } = await submitResilient(async () => {
      const latest = await getLatestBlock();
      if (!latest) throw new Error("relay unavailable");
      return buildBlobTx(state.wallet, blob, latest.block_number + 300, MIN_TX_FEE, nowSeconds());
    });
    if (res && res.data && res.data.result) back("ok=1&txid=" + tx.txid + "&addr=" + state.wallet.address);
    else back("ok=0&err=" + encodeURIComponent(((res && res.data && res.data.message) || "rejected").slice(0, 80)));
  };
  // AUTOSIGN IS DEFAULT-ON for value-free moves (user ask: zero friction for non-monetary actions). Only
  // an explicit "0" (turned off in Settings) disables it. Anything moving NADO never autosigns.
  // never autosign for an origin that isn't on the trusted allowlist (even if the user enabled skip) —
  // an untrusted site always gets an explicit confirm that names it.
  const autosignOn = localStorage.getItem(AUTOSIGN_KEY) !== "0" && trustedOrigin;
  // AUTO-SIGN EVERYTHING (opt-in): sign ANY contract call from a trusted game \u2014 bets included \u2014 with no
  // tap. Off by default; the user turns it on in Settings or straight from a sign dialog. Untrusted
  // origins are still never auto-signed.
  const autosignAll = localStorage.getItem("nado_autosign_all") === "1" && trustedOrigin;
  if (autosignAll || (valueFree && autosignOn) || smallBet) {
    signSplash(req.app);   // full-screen "signing\u2026" cover so the dashboard never flashes before the bounce
    try { await submitBlob(); } catch (e) { back("ok=0&err=" + encodeURIComponent(String(e.message || e).slice(0, 80))); }
    return;
  }
  const okc = await uiConfirm({
    title: i18("dapp.title", "Sign a contract call"),
    body: escrow > 0n
      ? i18("dapp.bodyValue", "{app} wants to sign & submit this from your wallet ({a}). It ESCROWS {v} NADO from your exec balance into the contract (no L1 funds move beyond the network fee).",
          { app: req.app, a: state.wallet.address.slice(0, 14) + "…", v: rawToNado(escrow) })
      : i18("dapp.body2", "{app} wants to sign & submit this from your wallet ({a}). It moves no L1 funds beyond the network fee.",
          { app: req.app, a: state.wallet.address.slice(0, 14) + "…" }),
    rows,
    // One opt-in on every trusted-game dialog: auto-sign ALL exec-layer calls from now on. These only ever
    // escrow from your playable (exec/VM) balance — never your L1 wallet — so ticking it lets bets/spins and
    // moves alike sign with no tap. Only shown for trusted origins.
    checkbox: trustedOrigin ? { label: i18("dapp.autoExecOptIn", "Auto-sign exec-layer game calls from now on (escrow from your playable balance, never L1)"), checked: false } : null,
    confirmText: i18("dapp.sign", "Sign & submit"),
  });
  if (!okc) { back("ok=0"); return; }
  if (trustedOrigin && modalCheckValue()) { try { localStorage.setItem("nado_autosign_all", "1"); } catch (e) {} }
  try {
    // short expiry; flexible landing mines it in the next produced block. submitResilient re-signs + resubmits
    // on the rare hedged "Invalid signature" rejection so a contract call isn't lost to a bad signature draw.
    await submitBlob();
  } catch (e) { back("ok=0&err=" + encodeURIComponent(String(e.message || e).slice(0, 80))); }
}

function wireAutosignToggle() {
  const el = $("autosignDapp");
  if (!el) return;
  el.checked = localStorage.getItem("nado_autosign_dapp") !== "0";   // default ON for value-free moves
  el.onchange = () => { try { localStorage.setItem("nado_autosign_dapp", el.checked ? "1" : "0"); } catch (e) {} };
  const so = $("skipOriginCheck");
  if (so) {
    so.checked = localStorage.getItem("nado_skip_origin_check") === "1";
    so.onchange = () => { try { localStorage.setItem("nado_skip_origin_check", so.checked ? "1" : "0"); } catch (e) {} };
  }
  const aa = $("autosignAll");
  if (aa) {
    aa.checked = localStorage.getItem("nado_autosign_all") === "1";
    aa.onchange = () => { try { localStorage.setItem("nado_autosign_all", aa.checked ? "1" : "0"); } catch (e) {} };
  }
  const bc = $("autosignBetCap");
  if (bc) {
    try { const raw = localStorage.getItem("nado_autosign_bet_cap_raw"); bc.value = raw && raw !== "0" ? rawToNado(BigInt(raw)) : ""; } catch (e) {}
    bc.onchange = () => { try { const r = nadoToRaw(bc.value); localStorage.setItem("nado_autosign_bet_cap_raw", r ? r.toString() : "0"); } catch (e) {} };
  }
}
// signSplash: a full-screen cover shown the instant we decide to auto-sign, so the wallet dashboard never
// flashes before we submit + bounce back to the game. Removed automatically when the page unloads.
function signSplash(app) {
  try {
    if (document.getElementById("signSplash")) return;
    const d = document.createElement("div");
    d.id = "signSplash";
    d.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:radial-gradient(700px 400px at 50% 40%,rgba(0,173,147,.14),#0b0f14 70%);color:#e6edf3;font:600 15px system-ui";
    d.innerHTML = '<div style="width:44px;height:44px;border:3px solid #243140;border-top-color:#00c9a7;border-radius:50%;animation:ssspin .8s linear infinite"></div>'
      + '<div>🔏 Signing your ' + (app ? String(app).replace(/[<>&]/g, "") + " " : "") + 'move…</div>'
      + '<div style="font-size:12px;color:#93a1b0">back to the game in a moment</div>'
      + '<style>@keyframes ssspin{to{transform:rotate(360deg)}}</style>';
    document.body.appendChild(d);
  } catch (e) {}
}
function showWalletUI() {
  wireAutosignToggle();
  show("onboard", false);
  show("savePrompt", false);
  show("unlockCard", false);
  show("tabbar", true);
  hdSync();                                          // anchor the HD layer to the loaded wallet (Main on a fresh load)
  renderAccountBar();
  $("walAddr").textContent = state.wallet.address;   // the ACTIVE account's address (receive/send from here)
  // The "Reveal / export private key" section is the BACKUP surface — always the MASTER seed + phrase, which
  // recovers EVERY derived account (a per-account child key would only restore that one address).
  const masterSeed = masterSeedOf() || state.wallet.privateKey;
  $("walPriv").textContent = masterSeed;
  if ($("walMnemonic")) {
    $("walMnemonic").textContent = "…";
    seedToMnemonic(hexToBytes(masterSeed))
      .then((m) => { $("walMnemonic").textContent = m; })
      .catch(() => { $("walMnemonic").textContent = i18("save.mnemonicErr", "(recovery phrase unavailable)"); });
  }
  $("recvAddr").textContent = state.wallet.address;
  const _urlTab = location.pathname.replace(/^\/+/, "");   // deep link: /aliases, /messages, …
  showTab(TAB_NAMES.has(_urlTab) ? _urlTab : (state.activeTab || "wallet"));
  if (_urlTab === "explore") {   // /explore?q=<address|alias|block|txid> (forum profiles link here) pre-runs a search
    const _q = (new URLSearchParams(location.search).get("q") || "").trim();
    if (_q && $("exQ")) {
      $("exQ").value = _q;
      exSearch().catch(() => {});
      try { history.replaceState(null, "", "/explore"); } catch (e) {}   // scrub the param once consumed
    }
  }
  msgInitBackground().catch(() => {});   // derive identity + poll so the Messages badge works anywhere
  resumePendingPay();   // if a #pay link was opened before this wallet existed, prefill the Send now
  resumePendingClaim(); // if a #claim link was opened before this wallet existed, receive the banknote now
  resumePendingForumLogin(); // if the forum bounced us here to sign a login challenge, prompt + sign now
  resumePendingExecSign();   // if a dApp (e.g. coinflip) bounced us here to sign a contract call, prompt + sign
}

function adoptWallet(w, { needsSavePrompt }) {
  if (needsSavePrompt) {
    pendingWallet = w;
    $("newPriv").textContent = w.privateKey;
    $("newMnemonic").textContent = "…";
    seedToMnemonic(hexToBytes(w.privateKey))
      .then((m) => { $("newMnemonic").textContent = m; })
      .catch(() => { $("newMnemonic").textContent = i18("save.mnemonicErr", "(recovery phrase unavailable)"); });
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
 * Vectors generated from the live repo (hashing.py / ops/*.py / signatures.py).
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
  // The tx vectors carry NO signature field: ML-DSA signatures are hedged/randomized by design, so only
  // txid/canonical bytes are comparable. REGENERATE these whenever a tx FIELD is renamed — canonical
  // encoding sorts keys, so a rename reorders the whole string (the target_block -> max_block rename
  // silently broke them once: the old strings had max_block in target_block's sort slot).
  register_tx: { sender: "ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84", recipient: "register", amount: 0, timestamp: 1700000000, data: "", nonce: "fixednonc", public_key: "1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38", max_block: 12345, chain_id: "nado-relaunch-1", pow_nonce: 2108331, fee: 0, txid: "ee0f586670ed8ad37faff2b6bd180bf827a3e1fbf8a4075ea9fe522adae1d687" },
  register_canonical: "{\"amount\":0,\"chain_id\":\"nado-relaunch-1\",\"data\":\"\",\"fee\":0,\"max_block\":12345,\"nonce\":\"fixednonc\",\"pow_nonce\":2108331,\"public_key\":\"1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38\",\"recipient\":\"register\",\"sender\":\"ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84\",\"timestamp\":1700000000}",
  heartbeat_tx: { sender: "ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84", recipient: "heartbeat", amount: 0, timestamp: 1700000000, data: "", nonce: "fixednonc", public_key: "1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38", max_block: 12345, chain_id: "nado-relaunch-1", epoch: 205, fee: 0, txid: "2c87b709e41164f5a25bfae1e4be4cc2d9ca01aff46bd652082b1534cfb71f16" },
  heartbeat_canonical: "{\"amount\":0,\"chain_id\":\"nado-relaunch-1\",\"data\":\"\",\"epoch\":205,\"fee\":0,\"max_block\":12345,\"nonce\":\"fixednonc\",\"public_key\":\"1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38\",\"recipient\":\"heartbeat\",\"sender\":\"ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84\",\"timestamp\":1700000000}",
  transfer_tx: { sender: "ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84", recipient: "ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29", amount: 123456, timestamp: 1700000000, data: "hello world", nonce: "fixednonc", public_key: "1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38", max_block: 12345, chain_id: "nado-relaunch-1", fee: 1000, txid: "7b384a64496b39eb6006cc7342c10f22c843a831334b25ca1886613f32f1b8b6" },
  transfer_canonical: "{\"amount\":123456,\"chain_id\":\"nado-relaunch-1\",\"data\":\"hello world\",\"fee\":1000,\"max_block\":12345,\"nonce\":\"fixednonc\",\"public_key\":\"1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38\",\"recipient\":\"ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29\",\"sender\":\"ndo1e9f9f319a9ee0f98b3147a67dca40e7296d5e847bdd84\",\"timestamp\":1700000000}",
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
  // HD SAFETY: export the MASTER key (recovers every derived account), not the active child.
  const w = (masterSeedOf() ? keypairFromPriv(masterSeedOf()) : null) || state.wallet || pendingWallet;
  if (!w) { uiAlert(i18("wallet.needFirst", "Create or import a wallet first — then you can download its key file.")); return; }
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

// Restore an encrypted wallet backup: ask for its password, decrypt, and adopt it — keeping it ENCRYPTED at
// rest on this device (unlike a plaintext key file, which persists the raw seed).
async function importEncryptedBlob(blob) {
  const pw = await uiPrompt({ title: i18("import.encPass", "Encrypted wallet backup — enter its password:"), password: true });
  if (pw == null) return;
  try {
    const seed = await decryptSeed(blob, pw);
    const w = keypairFromPriv(seed);
    localStorage.setItem(LS_WALLET, JSON.stringify(blob));   // keep it encrypted at rest here too
    state.wallet = w; state.locked = false;
    show("importBox", false); show("onboard", false); show("unlockCard", false);
    showWalletUI(); armAutolock();
    log("info", i18("log.keyImported", "Imported key from file."));
    refreshDashboard().catch(() => {});
  } catch (e) {
    uiAlert(i18("import.encWrong", "Wrong password for this encrypted backup."));
  }
}

// Download the ENCRYPTED wallet blob (a safe backup you can store anywhere — it needs your password to open).
// Unlike the plaintext key file, this never exposes the seed. Importable via the same "Import key file".
function downloadEncryptedWallet() {
  const w = loadWallet();
  if (!w || !w.enc) { uiAlert(i18("sec.notEnc", "Encrypt the wallet first — then you can download the encrypted backup.")); return; }
  const blob = new Blob([JSON.stringify(w, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `nado-wallet-encrypted-${(w.address || "").slice(0, 8)}.json`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1500);
  log("ok", i18("sec.dlEncOk", "Encrypted backup downloaded — it needs your password to restore."));
}

/* Import a wallet from a key FILE (the mirror of downloadKeyFile): reads the JSON produced by
 * downloadKeyFile and adopts the wallet from its private_key. Also tolerates a plain-hex-only file. */
function importKeyFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const text = String(reader.result || "").trim();
    let obj = null;
    try { obj = JSON.parse(text); } catch (e) { obj = null; }
    if (obj && obj.enc) { importEncryptedBlob(obj); return; }   // an encrypted backup -> ask for the password
    try {
      const priv = (obj && (obj.private_key || obj.privateKey || obj.private || obj.seed)) || (obj ? null : text);
      if (!priv) throw new Error(i18("import.noKey", "no private key found in the file"));
      adoptWallet(keypairFromPriv(String(priv).trim()), { needsSavePrompt: false });
      log("info", i18("log.keyImported", "Imported key from file."));
    } catch (e) {
      uiAlert(i18("import.fileFailed", "Import from file failed:") + " " + e.message);
    }
  };
  reader.onerror = () => uiAlert(i18("import.readErr", "Could not read the file."));
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
  if (!latest || typeof latest.block_number !== "number") throw new RelayUnreachable("relay /get_latest_block unavailable");
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
  // lowercase: alias names are all-lowercase on-chain (and THIS string becomes the signed tx
  // recipient), while a valid ndo… address is lowercase hex anyway — so "Alice" sends to "alice".
  const recipient = $("sendTo").value.trim().toLowerCase();
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
  const toLine = resolvedOwner ? `${recipient} (→ ${resolvedOwner})` : recipient;
  const isSelf = (recipient === state.wallet.address || resolvedOwner === state.wallet.address);
  const okSend = await uiConfirm({
    title: i18("dlg.sendTitle", "Confirm transfer"),
    rows: [
      { k: i18("dlg.amount", "Amount"), v: rawToNado(rawAmount) + " NADO" },
      { k: i18("dlg.to", "To"), v: toLine },
      { k: i18("dlg.fee", "Network fee"), v: rawToNado(fee) + " NADO" },
    ],
    warn: isSelf ? i18("dlg.selfWarn", "This is your OWN address.") : null,
  });
  if (!okSend) { setMsg("sendMsg", i18("msg.cancelled", "Cancelled."), null); return; }
  const btn = $("btnSend"); btn.disabled = true;
  try {
    const targetBlock = await nextTargetBlock();
    // PUBKEY-ONCE: omit the 1312-byte public_key once the sender's pubkey is established on-chain.
    const tx = buildTransferTx(state.wallet, recipient, rawAmount, fee, targetBlock, "", nowSeconds(), !pubkeyEstablished(acc));
    if (await submitAndReport(tx, "Transfer", "sendMsg")) { addrBookAdd(resolvedOwner || recipient, looksLikeAlias(recipient) ? recipient : ""); $("sendAmount").value = ""; show("payBanner", false); }
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
    to = ($("aliasTo").value || "").trim().toLowerCase();
    if (looksLikeAlias(to)) {                                    // accept another ALIAS as the target — resolve to its owner
      setMsg("aliasMsg", i18("quorum.resolving", "Resolving alias…"), null);
      const owner = await resolveAlias(to);
      if (!owner) { setMsg("aliasMsg", i18("alias.xferAliasMissing", "That target alias isn't registered."), "err"); return; }
      to = owner;
    }
    if (!validateAddress(to)) { setMsg("aliasMsg", i18("alias.xferTarget", "Transfer target must be a valid ndo… address or a registered alias."), "err"); return; }
  }
  const fee = op === "register" ? ALIAS_REGISTRATION_FEE : await currentFeeRaw();
  const acc = await getAccount(state.wallet.address);
  const balance = BigInt((acc && acc.balance) || 0);
  if (BigInt(fee) > balance) { setMsg("aliasMsg", `Insufficient balance for the ${rawToNado(fee)} NADO fee.`, "err"); return; }
  const data = op === "transfer" ? { op, name, to } : { op, name };
  // register defaults to SELF (the alias resolves to your own address); transfer points it elsewhere.
  const aliasTitle = { register: i18("dlg.aliasReg", "Register alias"), transfer: i18("dlg.aliasXfer", "Transfer alias"), unregister: i18("dlg.aliasUnreg", "Unregister alias") }[op];
  const aliasRows = [{ k: i18("dlg.aliasName", "Alias"), v: name }];
  if (op === "transfer") aliasRows.push({ k: i18("dlg.to", "To"), v: to });
  else if (op === "register") aliasRows.push({ k: i18("dlg.to", "To"), v: i18("dlg.selfAddr", "your address (self)") });
  aliasRows.push({ k: i18("dlg.fee", "Network fee"), v: rawToNado(fee) + " NADO" });
  if (!await uiConfirm({ title: aliasTitle, rows: aliasRows })) {
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
  const verb = isBond ? "Bond" : "Unbond";   // internal label for submitAndReport / logs (not user-facing)
  const okBond = await uiConfirm({
    title: isBond ? i18("btn.bond", "Deposit to savings") : i18("btn.unbond", "Withdraw from savings"),
    rows: [
      { k: i18("dlg.amount", "Amount"), v: rawToNado(rawAmount) + " NADO" },
      { k: i18("dlg.direction", "Direction"), v: isBond ? i18("dlg.dirBond", "spendable → savings") : i18("dlg.dirUnbond", "savings → spendable") },
      { k: i18("dlg.fee", "Network fee"), v: isBond ? rawToNado(fee) + " NADO" : i18("dlg.free", "Free (no fee)") },
    ],
    note: isBond ? null : i18("dlg.lockNote", "Savings stay locked {n} blocks after withdrawing.", { n: BOND_UNLOCK_DELAY }),
  });
  if (!okBond) { setMsg("stakeMsg", i18("msg.cancelled", "Cancelled."), null); return; }
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

/* ----------------------------------------------------------------------------------------------
 * RANDAO duty (MANDATORY for bonded stake): commit a secret for epoch E in E-2, reveal it in E-1's
 * finalized window. Consensus filters the bonded-lane producer draw to validators that REVEALED
 * for the epoch (randao_eligible_bonded) — a bonded identity that skips this earns NOTHING that
 * epoch. Mirrors the node's maybe_randao: best-effort, retried while each window lasts, secrets in
 * localStorage so a tab reload between commit (E-2) and reveal (E-1) doesn't forfeit the epoch.
 * The tab must be open sometime during BOTH windows (each >= ~5 min at 10 s blocks); an always-on
 * node remains the reliable way to run serious stake.
 * -------------------------------------------------------------------------------------------- */
const RANDAO_RETRY_BLOCKS = 12;          // re-submit an unconfirmed commit/reveal every ~2 min
function randaoKey() { return "nado_randao_" + state.wallet.address; }
function loadRandao() { try { return JSON.parse(localStorage.getItem(randaoKey()) || "{}"); } catch { return {}; } }
function saveRandao(m) { try { localStorage.setItem(randaoKey(), JSON.stringify(m)); } catch (e) { /* quota */ } }
// The epoch secret is DERIVED from the wallet key (like ETH validators' deterministic randao_reveal):
// every device holding this wallet computes the SAME secret, so multi-device mining can never
// split-brain an epoch. Only the key holder can compute it; the commit binds it two epochs ahead.
function randaoSecretFor(epoch) { return blake2bHash(["nado-randao-secret", masterSeedOf() || state.wallet.privateKey, Number(epoch)]); }

let _randaoBusy = false;
const _randaoDead = new Set();     // epochs with a DETERMINISTIC reveal rejection — same inputs give the same
                                   // answer, so a resubmit can never succeed; never send one twice
async function maybeRandao() {
  if (_randaoBusy || !state.wallet || state.locked || state.latest == null) return;
  _randaoBusy = true;
  try {
    const acc = await getAccount(state.wallet.address);
    if (!acc || BigInt(acc.bonded ?? 0) < B_MIN_RAW) return;   // duty applies to bonded validators only
    const latest = state.latest;
    const epochNow = Math.floor(latest / EPOCH_LENGTH);
    const store = loadRandao();
    let dirty = false;
    for (const k of Object.keys(store)) {                      // prune epochs whose windows have passed
      if (Number(k) <= epochNow) { delete store[k]; dirty = true; }
    }

    // COMMIT for epoch current+2 (we are in its E-2 window). Confirmation is observed as the
    // node rejecting a re-submit with "Already committed" — until then, retry (throttled).
    const eCommit = epochNow + 2;
    let rec = store[eCommit];
    if (!rec || !rec.committed) {
      const tb = Math.min(latest + 5, (epochNow + 1) * EPOCH_LENGTH - 1);
      const due = !rec || rec.lastTry == null || (latest - rec.lastTry) >= RANDAO_RETRY_BLOCKS;
      if (tb > latest && due) {
        if (!rec) { rec = store[eCommit] = { secret: randaoSecretFor(eCommit) }; }
        rec.lastTry = latest; dirty = true;
        const commitment = blake2bHash(["nado-randao-commit", rec.secret]);
        const tx = buildTransferTx(state.wallet, "commit", 0n, 0,
                                   tb, { target_epoch: eCommit, commitment },
                                   nowSeconds(), !pubkeyEstablished(acc));
        const res = await submitTransaction(tx);
        const msg = String(res.data && (res.data.message || ""));
        if (/already committed/i.test(msg)) { rec.committed = true; }
        else if (!(res.data && res.data.result) && msg) { log("err", i18("log.randaoCommitErr", "RANDAO commit rejected: {m}", {m: msg.slice(0, 120)})); }
      }
    }

    // REVEAL for epoch current+1 (its E-1 finalized window) — this is what earns the epoch.
    const eReveal = epochNow + 1;
    const rrec = store[eReveal];
    if (rrec && rrec.secret && !rrec.revealed && !_randaoDead.has(eReveal)) {
      const lo = epochNow * EPOCH_LENGTH;
      const hi = eReveal * EPOCH_LENGTH - FINALITY_DEPTH - 1;
      const tb = latest + 5;
      const due = rrec.lastReveal == null || (latest - rrec.lastReveal) >= RANDAO_RETRY_BLOCKS;
      if (tb >= lo && tb <= hi && due) {
        rrec.lastReveal = latest; dirty = true;
        const tx = buildTransferTx(state.wallet, "reveal", 0n, 0,
                                   tb, { target_epoch: eReveal, secret: rrec.secret },
                                   nowSeconds(), !pubkeyEstablished(acc));
        const res = await submitTransaction(tx);
        const msg = String(res.data && (res.data.message || ""));
        if (/already revealed/i.test(msg)) {
          rrec.revealed = true;
          log("ok", i18("log.randaoRevealed", "RANDAO reveal confirmed for epoch {e} — bonded lane eligible ✓", {e: eReveal}));
        } else if (/no matching commit/i.test(msg)) {
          rrec.revealed = true; _randaoDead.add(eReveal); saveRandao(store);   // persist NOW, not just end-of-cycle
          log("err", i18("log.randaoNoCommit", "RANDAO: commit for epoch {e} never landed — bonded rewards skip this epoch.", {e: eReveal}));
        } else if (/does not open the commitment/i.test(msg)) {
          rrec.revealed = true; _randaoDead.add(eReveal); saveRandao(store);   // deterministic — retrying can't help
          log("err", i18("log.randaoRevealErr", "RANDAO reveal rejected: {m}", {m: msg.slice(0, 120)}));
        } else if (!(res.data && res.data.result) && msg) {
          log("err", i18("log.randaoRevealErr", "RANDAO reveal rejected: {m}", {m: msg.slice(0, 120)}));
        }
      }
    }
    if (dirty) saveRandao(store);
  } catch (e) { /* best-effort; never break the poll loop */ }
  finally { _randaoBusy = false; }
}

/* ---- Payment-request deep links: QR / shareable URL that prefills a Send on scan ---- */

let pendingPay = null;   // a pay-request parsed from the URL hash before a wallet exists
let pendingClaim = null; // a banknote claim-request awaiting wallet setup, same lifecycle

// Deep link back to THIS hosted wallet: ${origin}${pathname}#pay?to=<addr>&amount=<NADO>.
// AMOUNT IS IN NADO (human-friendly), not raw units, and is OPTIONAL (omitted entirely for a bare
// receive code). Using origin+pathname makes the QR resolve wherever the node serves interface.html.
function payLink(addr, amountNado) {
  const params = new URLSearchParams({ to: addr });
  const a = (amountNado == null ? "" : String(amountNado)).trim();
  if (a) params.set("amount", a);
  return `${location.origin}${location.pathname}#pay?${params.toString()}`;
}

// Claim-link twin for shielded banknotes: opening it receives the note automatically — nothing to paste.
// The code only reconstructs into a pool note with the intended recipient's key, so a stranger opening the
// link can't take it; still treat it like cash and deliver it over a private channel.
function claimLink(code) { return `${location.origin}${location.pathname}#claim?${new URLSearchParams({ code }).toString()}`; }

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

/* Custom in-app dialogs — replace the browser's native confirm()/alert()/prompt() with a styled,
 * translatable modal. All three return a Promise (await them). Built once, reused, keyboard-friendly
 * (Enter = confirm, Esc = cancel, click-outside = cancel). spec: {title, body, rows:[{k,v}], warn, note,
 * confirmText, cancelText, danger}; uiPrompt adds {password, placeholder}. */
let _modalEl = null, _modalResolve = null, _modalKind = "confirm";
function _closeModal(result) {
  if (!_modalEl || !_modalResolve) return;
  _modalEl.classList.add("hidden");
  document.removeEventListener("keydown", _modalKey, true);
  const r = _modalResolve; _modalResolve = null;
  r(result);
}
function _modalKey(e) {
  if (e.key === "Escape") { e.preventDefault(); _closeModal(_modalKind === "prompt" ? null : false); }
  else if (e.key === "Enter" && _modalKind !== "prompt") { e.preventDefault(); _closeModal(true); }
}
function _openModal(spec) {
  if (!_modalEl) {
    _modalEl = document.createElement("div");
    _modalEl.className = "modal-backdrop hidden";
    _modalEl.innerHTML =
      '<div class="modal card" role="dialog" aria-modal="true">' +
        '<h3 class="modal-title"></h3><div class="modal-body hidden"></div>' +
        '<div class="modal-rows hidden"></div><div class="modal-warn hidden"></div>' +
        '<input class="modal-user" type="text" autocomplete="username" tabindex="-1" aria-hidden="true" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0" />' +
        '<input class="modal-input hidden" autocomplete="off" /><div class="modal-note hidden"></div>' +
        '<label class="modal-check hidden" style="display:flex;gap:10px;align-items:center;font-size:12.5px;color:var(--dim);margin:10px 0 0;cursor:pointer"><input type="checkbox" class="switch"><span></span></label>' +
        '<div class="modal-actions"><button type="button" class="modal-cancel ghost"></button>' +
        '<button type="button" class="modal-ok primary"></button></div></div>';
    document.body.appendChild(_modalEl);
  }
  const el = _modalEl, q = (s) => el.querySelector(s);
  _modalKind = spec.kind || "confirm";
  q(".modal-title").textContent = spec.title || "";
  const setText = (sel, val) => { const n = q(sel); n.textContent = val || ""; n.classList.toggle("hidden", !val); };
  setText(".modal-body", spec.body);
  setText(".modal-warn", spec.warn);
  setText(".modal-note", spec.note);
  const rowsEl = q(".modal-rows"); rowsEl.innerHTML = "";
  (spec.rows || []).forEach((r) => {
    const row = document.createElement("div"); row.className = "modal-row";
    const k = document.createElement("span"); k.className = "k"; k.textContent = r.k;
    const v = document.createElement("span"); v.className = "v"; v.textContent = r.v;
    row.appendChild(k); row.appendChild(v); rowsEl.appendChild(row);
  });
  rowsEl.classList.toggle("hidden", !(spec.rows && spec.rows.length));
  const chk = q(".modal-check");
  chk.classList.toggle("hidden", !spec.checkbox);
  if (spec.checkbox) { chk.querySelector("span").textContent = spec.checkbox.label; chk.querySelector("input").checked = !!spec.checkbox.checked; }
  _modalCheckEl = spec.checkbox ? chk.querySelector("input") : null;
  const inp = q(".modal-input"), isPrompt = _modalKind === "prompt";
  inp.classList.toggle("hidden", !isPrompt);
  const userInp = q(".modal-user");
  if (isPrompt) {
    inp.type = spec.password ? "password" : "text";
    inp.value = ""; inp.placeholder = spec.placeholder || "";
    // Password fields: give the browser a REAL username (the wallet address) + the right autocomplete role,
    // so if it offers to save the credential it stores address/password — not some stray number from the page
    // (which is why the save prompt showed "username 120"). newPassword=true when SETTING one (encryption).
    if (spec.password) {
      userInp.value = (state.wallet && state.wallet.address) || "NADO wallet";
      inp.setAttribute("autocomplete", spec.newPassword ? "new-password" : "current-password");
      inp.setAttribute("name", "nado-wallet-password");
    } else {
      userInp.value = ""; inp.setAttribute("autocomplete", "off"); inp.removeAttribute("name");
    }
    inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); _closeModal(inp.value); } };
  } else {
    userInp.value = "";
  }
  const okBtn = q(".modal-ok"), cancelBtn = q(".modal-cancel");
  okBtn.textContent = spec.confirmText || i18("dlg.confirm", "Confirm");
  okBtn.className = "modal-ok " + (spec.danger ? "danger" : "primary");
  cancelBtn.textContent = spec.cancelText || i18("dlg.cancel", "Cancel");
  cancelBtn.classList.toggle("hidden", _modalKind === "alert");
  okBtn.onclick = () => _closeModal(isPrompt ? inp.value : true);
  cancelBtn.onclick = () => _closeModal(isPrompt ? null : false);
  el.onclick = (e) => { if (e.target === el) _closeModal(isPrompt ? null : false); };
  el.classList.remove("hidden");
  document.addEventListener("keydown", _modalKey, true);
  setTimeout(() => { (isPrompt ? inp : okBtn).focus(); }, 30);
  return new Promise((res) => { _modalResolve = res; });
}
let _modalCheckEl = null;
function modalCheckValue() { return !!(_modalCheckEl && _modalCheckEl.checked); }
function uiConfirm(spec) { return _openModal(Object.assign({}, spec, { kind: "confirm" })); }
function uiAlert(body, title) { return _openModal({ kind: "alert", title: title || i18("dlg.notice", "Notice"), body: body, confirmText: i18("dlg.ok", "OK") }); }
function uiPrompt(spec) { return _openModal(Object.assign({}, spec, { kind: "prompt" })); }

// The request-amount (NADO) currently in the given input, or "" if blank/malformed/non-positive.
function _reqAmount(id) {
  const raw = (($(id) && $(id).value) || "").trim();
  if (!raw) return "";
  try { return nadoToRaw(raw) > 0n ? raw : ""; } catch (e) { return ""; }
}
function currentRecvAmount() { return _reqAmount("recvAmount"); }     // Receive tab
function currentZrecvAmount() { return _reqAmount("zrecvAmount"); }   // Shield tab's receive block

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

// Share the banknote claim LINK (auto-receives on open) — never just the raw code (that needs pasting).
async function shareZcodeLink() {
  const code = (($("zsendCode") || {}).textContent) || "";
  if (!code) return;
  const link = claimLink(code);
  if (navigator.share) {
    try { await navigator.share({ title: "NADO shielded claim link", text: i18("share.zcodeMsg", "A private NADO banknote for you — open to claim:"), url: link }); return; }
    catch (e) { if (e && e.name === "AbortError") return; }
  }
  const btn = $("btnZcodeShare");
  const ok = await copyToClipboard(link);
  if (btn) { btn.textContent = ok ? i18("copy.copied", "Copied ✓") : i18("copy.select", "select & copy"); setTimeout(() => (btn.textContent = i18("btn.share", "Share")), ok ? 1200 : 1600); }
}

// The shielded twin of sharePayLink — the same #pay deep link, carrying the znado… address instead.
async function shareZpayLink() {
  if (!state.wallet) return;
  const link = payLink(shieldAddr(), currentZrecvAmount());
  if (navigator.share) {
    try { await navigator.share({ title: "NADO private payment request", text: i18("share.zpayMsg", "Pay me privately on NADO — shielded payment link:"), url: link }); return; }
    catch (e) { if (e && e.name === "AbortError") return; }
  }
  const btn = $("btnZaddrShare");
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

// A #pay link's recipient can be transparent (ndo…) or shielded (znado…) — same link format, routed by prefix.
function _isZAddr(a) { try { parseShieldAddr(a); return true; } catch (e) { return false; } }

// A #pay link with a znado… recipient prefills the SHIELDED send (same review-first rule as a normal Send).
function applyZpayRequest(req) {
  showTab("shield");
  $("zsendTo").value = req.to;
  let amtOk = false;
  if (req.amount) {
    try { if (nadoToRaw(req.amount) > 0n) { $("zsendAmount").value = req.amount; amtOk = true; } }
    catch (e) { /* malformed/negative amount -> prefill recipient only */ }
  }
  const msg = amtOk
    ? i18("payBanner.msg", "Payment request loaded — review and confirm.")
    : i18("payBanner.enterAmt", "Payment request loaded — enter an amount, then review and confirm.");
  toast(msg, "info");
  try { $("zsendTo").scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {}
  setTimeout(() => { const f = amtOk ? $("btnZsend") : $("zsendAmount"); if (f) f.focus(); }, 350);
  log("info", `Private payment request loaded: pay ${req.to.slice(0, 12)}…${amtOk ? " " + req.amount + " NADO" : ""}`);
}

function applyPayRequest(req) {
  if (!state.wallet) return;
  if (_isZAddr(req.to)) return applyZpayRequest(req);
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
  if (!validateAddress(req.to) && !_isZAddr(req.to)) {
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
  if (validateAddress(req.to) || _isZAddr(req.to)) applyPayRequest(req);
}

/* #claim?code=… deep links — the shielded-banknote twin of #pay. Unlike #pay (which only ever PREFILLS a
 * send), a claim may safely auto-run: receiving is local, moves no funds out, and the code only becomes a
 * valid pool note under the intended recipient's key. */
function parseClaimHash() {
  const h = location.hash || "";
  if (!h.startsWith("#claim?")) return null;
  return { code: (new URLSearchParams(h.slice(7)).get("code") || "").trim() };
}

function applyClaimRequest(req) {
  if (!state.wallet) return;
  showTab("shield");
  $("zrecvCode").value = req.code;    // visible + editable, so a failed claim can simply be retried
  toast("Claim link opened — receiving the banknote…", "info");
  try { $("zrecvCode").scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {}
  doReceiveShielded().catch((e) => log("err", "Claim failed: " + e.message));
}

function consumeClaimRequest() {
  const req = parseClaimHash();
  if (!req) return;
  try { history.replaceState(null, "", location.pathname); } catch (e) {}
  if (!req.code.startsWith("znote") || req.code.indexOf(".") < 0) {
    log("err", "Claim link ignored — malformed claim code.");
    toast("Claim link ignored — the claim code is malformed.", "err");
    return;
  }
  if (state.wallet) {
    applyClaimRequest(req);
  } else {
    pendingClaim = req;                     // stash; the banknote is received right after wallet setup
    try { sessionStorage.setItem(LS_PENDING_CLAIM, JSON.stringify(req)); } catch (e) {}
    toast("Banknote pending — set up a wallet and it will be received automatically.", "info", 7000);
    log("info", "Claim link detected — create or import a wallet to receive the banknote.");
  }
}

function resumePendingClaim() {
  if (!state.wallet) return;
  let req = pendingClaim;
  if (!req) { try { const s = sessionStorage.getItem(LS_PENDING_CLAIM); if (s) req = JSON.parse(s); } catch (e) {} }
  if (!req) return;
  pendingClaim = null;
  try { sessionStorage.removeItem(LS_PENDING_CLAIM); } catch (e) {}
  if (req.code && req.code.startsWith("znote")) applyClaimRequest(req);
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
function exNado(raw) { try { return rawToNado(BigInt(raw)) + " NADO"; } catch { return exEsc(String(raw)); } }  // H-5: escape on non-numeric
function exTime(ts) { if (ts == null) return "—"; return new Date(ts * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC"); }
function exEsc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function exShort(h, n = 12) { return exEsc(h && h.length > n * 2 ? h.slice(0, n) + "…" + h.slice(-6) : (h ?? "—")); }  // H-5: escape (relay hashes/addrs)
// data attrs + event delegation (interface.js is an ES module, so inline onclick can't see exOpen)
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
    // H-5: exStat inserts each value into innerHTML raw, so every relay-supplied number is coerced with num().
    $("exNetwork").innerHTML = exStat([
      ["Tip height", exLink("b", st.latest_block_hash, "#" + num(sup.block_number))],
      ["Latest hash", `<span class="mono">${exShort(st.latest_block_hash)}</span>`],
      ["Finalized", "#" + num(st.finalized_height) + (st.ffg_finalized != null ? `  ·  FFG #${num(st.ffg_finalized)}` : "")],
      ["Total supply", exNado(sup.total_supply)],
      ["Circulating", exNado(sup.circulating)],
      ["Treasury", exNado(sup.treasury)],
      ["Fees burned", exNado(sup.fees)],
    ]);
  } catch (e) { $("exNetwork").innerHTML = `<div class="warnbox danger">${i18("ex.nodeUnreachable", "Node unreachable:")} ${exEsc(e.message)}</div>`; }
  try {
    const ms = await exGetJSON("/mining_status");
    $("exMining").innerHTML = exStat([
      ["Epoch", num(ms.epoch) + `  (len ${num(ms.epoch_length)})`],
      ["Next block", "#" + num(ms.next_block)],
      ["Block time", num(ms.block_time) + "s"],
      ["OPEN lane", `${num(ms.open_registry_size)} miners · ${num(ms.k_open)}/${num(ms.epoch_length)} slots`],
      ["BONDED lane", `${num(ms.bonded_registry_size)} miners · ${num(ms.total_bonded_shares)} shares`],
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
  return `<h2>${i18("ex.block","Block")} #${num(b.block_number)}</h2>${exKV([
    ["Hash", `<span class="mono">${exEsc(b.block_hash)}</span>`],
    ["Parent", exLink("b", b.parent_hash, exShort(b.parent_hash))],
    ["Producer", exLink("a", b.block_creator)],
    ["Time", exTime(b.block_timestamp)],
    ["Reward", exNado(b.block_reward)],
    ["Cumulative fees", exNado(b.cumulative_fees)],
    ["Cumulative weight", exEsc(String(b.cumulative_weight))],
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
    ["Fidelity", num(a.fidelity) + " / 1000"],
  ])}<div class="row mt"><button class="accent" id="exLoadTxs">${i18("ex.showTxs", "Show transactions")}</button></div><div id="exAcctTxs" class="ex-rows mt"></div>`;
}
function exRenderTx(t) {
  return `<h2>${i18("ex.transaction", "Transaction")}</h2>${exKV([
    ["Txid", `<span class="mono">${exEsc(t.txid || "—")}</span>`],
    ["From", exLink("a", t.sender)],
    ["To", exReservedOrAddr(t.recipient)],
    ["Amount", exNado(t.amount)],
    ["Fee", exNado(t.fee || 0)],
    ["Target block", t.max_block != null ? exLink("b", String(t.max_block), "#" + t.max_block) : "—"],
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
        } catch (e) {   // an account with no transactions answers 404 — that's "none", not an error
          box.innerHTML = /HTTP 404/.test(e.message || "")
            ? `<div class="faint small">${i18("ex.noTxs", "no transactions")}</div>`
            : `<div class="warnbox danger">${exEsc(e.message)}</div>`;
        }
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
  } catch (e) {
    // A pruned/absent record answers 404 (or the legacy 403). Say so plainly instead of "Not found: HTTP 404".
    const msg = /HTTP 40[34]|not found/i.test(e.message || "")
      ? i18("ex.notFoundPruned", "Not found on this node. If this is an old block or transaction, the node may have pruned it from its retained history.")
      : i18("ex.lookupErr", "Lookup failed:") + " " + exEsc(e.message);
    exShowResult(`<div class="warnbox danger">${msg}</div>`);
  }
}
async function exSearch() {
  const q = $("exQ").value.trim().toLowerCase();   // addresses/hashes/aliases are all lowercase
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
const _CACC = "#3aa0ff", _CGRID = "#1c2530", _CMUT = "#7c8b9a", _CGOLD = "#f5c542", _CGRN = "#5ad19a", _CPUR = "#c77dff";

// Donut/pie with a legend — for distribution breakdowns (reward pipelines, supply). slices: [{label,value,color}].
function pieChart(id, slices, opts) {
  opts = opts || {}; const svg = _svgClear(id); if (!svg) return;
  svg.setAttribute("viewBox", "0 0 320 132");
  const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0);
  const cx = 64, cy = 66, r = 52, ir = 30;
  if (total <= 0) { svg.appendChild(_mk("text", { x: 160, y: 66, fill: _CMUT, "font-size": 11, "text-anchor": "middle" }, i18("stats.nodata", "no data yet"))); return; }
  let ang = -Math.PI / 2;
  slices.forEach((sl) => {
    const frac = Math.max(0, sl.value) / total;
    if (frac <= 0) return;
    const a2 = ang + frac * 2 * Math.PI, large = frac > 0.5 ? 1 : 0;
    const P = (rad, a) => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
    const [x1, y1] = P(r, ang), [x2, y2] = P(r, a2), [xi2, yi2] = P(ir, a2), [xi1, yi1] = P(ir, ang);
    svg.appendChild(_mk("path", { d: `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${xi2} ${yi2} A ${ir} ${ir} 0 ${large} 0 ${xi1} ${yi1} Z`, fill: sl.color }));
    ang = a2;
  });
  slices.forEach((sl, i) => {
    const y = 20 + i * 19, pct = (Math.max(0, sl.value) / total) * 100;
    svg.appendChild(_mk("rect", { x: 134, y: y - 8, width: 10, height: 10, fill: sl.color, rx: 2 }));
    svg.appendChild(_mk("text", { x: 150, y: y + 1, fill: "#cdd7e0", "font-size": 9 }, `${sl.label} — ${opts.fmt ? opts.fmt(sl.value) : pct.toFixed(1) + "%"}`));
  });
}

// Social brand-icon share buttons were removed: every share context (pay / site / zpay / zcode) already
// has a single "Share" button that uses the native share sheet (navigator.share) with a clipboard
// fallback — the same clean format as the Coin Flip dApp. No more direct per-network icons.

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
  // Three fixed columns so nothing is ragged or overlaps: [label] [bar] [value(right-aligned)]. The label is
  // hard-clipped to its column so a long address can never paint over the bars.
  const W = 320, rowH = 18, padT = 5, labelW = 66, gap = 4, valueW = 46, barX = labelW + gap;
  const barMax = W - barX - valueW;              // the bar can never reach into the value column
  const n = rows.length;
  if (!n) { svg.appendChild(_mk("text", { x: W / 2, y: 20, fill: _CMUT, "font-size": 11, "text-anchor": "middle" }, i18("stats.nodata", "no data yet"))); return; }
  svg.setAttribute("viewBox", `0 0 ${W} ${padT * 2 + n * rowH}`);
  // one clipPath the label text is rendered inside, so overflow is cut at the column edge
  const cp = _mk("clipPath", { id: id + "_lc" });
  cp.appendChild(_mk("rect", { x: 0, y: 0, width: labelW, height: padT * 2 + n * rowH }));
  svg.appendChild(cp);
  const max = Math.max(1e-9, ...rows.map((r) => r.value));
  rows.forEach((r, i) => {
    const cy = padT + i * rowH + rowH / 2;
    const bw = Math.max(1, (r.value / max) * barMax);
    svg.appendChild(_mk("text", { x: 2, y: cy + 3, fill: _CMUT, "font-size": 8.5, "clip-path": `url(#${id}_lc)` }, r.label));
    svg.appendChild(_mk("rect", { x: barX, y: cy - (rowH - 8) / 2, width: bw, height: rowH - 8, fill: opts.color || _CACC, rx: 2 }));
    svg.appendChild(_mk("text", { x: W - 2, y: cy + 3, fill: "#cdd7e0", "font-size": 8.5, "text-anchor": "end" }, opts.fmt ? opts.fmt(r.value) : String(r.value)));
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
    const rows = ((d && d.rich_list) || []).slice(0, 8).map((e) => ({ label: /^ndo/.test(e.address) ? e.address.slice(0, 8) + "…" : e.address, value: _nadoNum(e.total) }));
    hbarChart("chartWealth", rows, { color: _CGRN, fmt: (v) => (v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(1)) });
  } catch {}
  let ms = state.lastMs;
  try { ms = await getMiningStatus(state.wallet.address); } catch {}
  if (ms) laneBar("chartLanes", ms.open_registry_size || 0, ms.bonded_registry_size || 0);

  // REWARD DISTRIBUTION by pipeline (structural consensus split): open lane is ~20% of blocks (treasury 10 /
  // tip 20 / dividend 70), bonded ~80% (producer 70 / dividend 20 / treasury 10) -> effective network split.
  pieChart("chartRewardSplit", [
    { label: i18("stats.pipeProducer", "Bonded producer"), value: 56, color: _CACC },
    { label: i18("stats.pipeDividend", "Presence dividend"), value: 30, color: _CGRN },
    { label: i18("stats.pipeTreasury", "Treasury"), value: 10, color: _CGOLD },
    { label: i18("stats.pipeTip", "Open-lane tip"), value: 4, color: _CPUR },
  ], { fmt: (v) => v.toFixed(0) + "%" });

  // SUPPLY DISTRIBUTION (live): where the minted coins currently sit.
  try {
    const sup = await (await fetch(relayBase() + "/get_supply", { cache: "no-store" })).json();
    const total = _nadoNum(sup.total_supply || 0), treasury = _nadoNum(sup.treasury || 0);
    let div = 0, shd = 0;
    try { div = _nadoNum((await (await fetch(relayBase() + "/get_account?address=dividend", { cache: "no-store" })).json()).balance || 0); } catch {}
    try { shd = _nadoNum((await (await fetch(relayBase() + "/get_account?address=shield", { cache: "no-store" })).json()).balance || 0); } catch {}
    const circ = Math.max(0, total - treasury - div - shd);
    const fmtN = (v) => (v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(0)) + " NADO";
    pieChart("chartSupply", [
      { label: i18("stats.supCirc", "Circulating"), value: circ, color: _CACC },
      { label: i18("stats.supTreasury", "Treasury"), value: treasury, color: _CGOLD },
      { label: i18("stats.supDividend", "Dividend pool"), value: div, color: _CGRN },
      { label: i18("stats.supShield", "Shielded"), value: shd, color: _CPUR },
    ], { fmt: fmtN });
  } catch {}
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
    // H-5: /htlcs is relay JSON — coerce the amount (bnum guards BigInt from throwing on a hostile value),
    // escape the free-form status fallback, and coerce the expiry before they reach this innerHTML sink.
    left.innerHTML = `<div class="mono small">${exShort(id, 14)}</div><div class="faint small">${rawToNado(bnum(h.amount))} NADO · ${role} · ${i18("swap.status." + h.status, exEsc(h.status))} · exp #${num(h.expiry)}</div>`;
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

// Deep-linkable tab URLs — /aliases, /messages, /send, … (the node serves the interface at each path).
const TAB_NAMES = new Set(["wallet", "send", "receive", "aliases", "stake", "quorum", "multisig", "messages", "history", "rich", "stats", "swap", "shield", "settlement", "rollup", "explore", "settings"]);

// Read-only Settlement (L2) view: L1's justified settled root (/get_settled) vs this exec node's tip
// (/exec/settlement) vs the mining wallet's bonded role. Fail-soft: any source may be down (exec node not
// running, no settlement yet) and the panel still renders what it can, never throwing.
async function renderSettlement() {
  const setT = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  let settled = null, execn = null, acct = null;
  try { settled = await (await fetch(relayBase() + "/get_settled", { cache: "no-store" })).json(); } catch (e) {}
  try { execn = await (await fetch(execBase() + "/exec/settlement", { cache: "no-store" })).json(); } catch (e) {}
  try { acct = await (await fetch(relayBase() + "/get_account?address=" + encodeURIComponent(state.wallet.address), { cache: "no-store" })).json(); } catch (e) {}

  const sRoot = settled && settled.state_root;
  const sCursor = settled ? settled.exec_cursor : null;
  setT("settleL1Root", sRoot ? (sRoot.slice(0, 20) + "…") : "none settled yet");
  setT("settleL1Cursor", (sCursor != null && sCursor >= 0) ? String(sCursor) : "—");

  const eCursor = execn ? execn.cursor : null;
  setT("settleExecCursor", (eCursor != null && eCursor >= 0) ? String(eCursor)
                                                             : (execn ? "syncing…" : "exec node unreachable"));

  let gap = "—";
  if (execn && eCursor != null && sCursor != null && sCursor >= 0) gap = String(Math.max(0, eCursor - sCursor)) + " block(s)";
  setT("settleGap", gap);

  let match = "—";
  if (execn && execn.state_root && sRoot) match = (execn.state_root === sRoot) ? "✅ yes" : "⚠️ divergent — investigate";
  setT("settleMatch", match);

  let bonded = 0n;
  try { bonded = acct && acct.bonded ? BigInt(acct.bonded) : 0n; } catch (e) { bonded = 0n; }
  let role, note = "";
  if (bonded > 0n && execn && execn.settle_enabled) {
    role = "Settling — attesting every " + (execn.settle_every || "?") + " blocks";
  } else if (bonded > 0n) {
    role = "Bonded, not settling";
    note = "Your stake is bonded, but this node isn't posting settlement attestations. Set NADO_EXEC_SETTLE=1 on your exec node to help settle the L2.";
  } else {
    role = "Observer";
    note = "Bond stake (Stake tab) to become a validator that attests the L2 state root to L1.";
  }
  setT("settleRole", role);
  setT("settleNote", note);
}
window.addEventListener("popstate", () => { const p = location.pathname.replace(/^\/+/, ""); if (state.wallet && TAB_NAMES.has(p)) showTab(p); });

function showTab(name) {
  if (!state.wallet) return;
  state.activeTab = name;
  if (TAB_NAMES.has(name) && location.pathname !== "/" + name) history.pushState(null, "", "/" + name);
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
  else if (name === "shield") renderShield().catch(() => {});
  else if (name === "settlement") renderSettlement().catch(() => {});
  else if (name === "rollup") renderRollup().catch(() => {});
  else if (name === "send") { updateFeeInfo().catch(() => {}); validateSendTo().catch(() => {}); addrBookRender(); }
  else if (name === "stake") { updateFeeInfo().catch(() => {}); refreshDashboard().catch(() => {}); }
  else if (name === "quorum") renderQuorum().catch(() => {});
  else if (name === "multisig") renderMsig().catch(() => {});
  else if (name === "messages") msgOpen().catch(() => {});
  else if (name === "settings") renderSecurity();
}

/* ----------------------------------------------------------------------------------------------
 * ROLLUP tab — browse / deploy / call execution-layer contracts. Deploys & calls ride L1 as ordered
 * `blob` txs (apply at finality); reads are live from the exec node. Contract runtimes are pluggable.
 * -------------------------------------------------------------------------------------------- */
let _rollupExamples = null, _rollupWired = false, _rollupContracts = {}, _rollupActive = "", _rollupLoadedAbi = {}, _rollupLoadedCode = "";
function rollupNs() { const v = ($("rollupNs").value || "").trim(); return v || "default"; }

async function renderRollup() {
  rollupWire();
  await rollupLoadExamples();
  await rollupRefresh();
  rollupRenderHistory();
}

function rollupWire() {
  if (_rollupWired) return;
  _rollupWired = true;
  $("rollupRefresh").onclick = () => rollupRefresh();
  $("rollupLoadExample").onclick = () => {
    const k = $("rollupExample").value, ex = k && _rollupExamples && _rollupExamples[k];
    if (ex) { $("rollupCode").value = JSON.stringify(ex.code, null, 1); _rollupLoadedAbi = ex.abi || {}; _rollupLoadedCode = $("rollupCode").value; }
  };
  $("rollupDeploy").onclick = () => rollupDeploy();
  $("rollupCall").onclick = () => rollupCall();
  $("rollupView").onclick = () => rollupView();
  $("rollupCallMethodSel").onchange = () => rollupRenderArgs(_rollupActive, $("rollupCallMethodSel").value);
  $("rollupMine").onchange = () => { if ($("rollupMine").value) rollupSelectContract($("rollupMine").value, "mine"); };
  // "All contracts" is a search-as-you-type datalist — SCALES to any number of contracts: each keystroke
  // queries the node by cid PREFIX (bounded to 50 rows), and picking a full cid selects it.
  let _rst;
  $("rollupAllSearch").oninput = () => {
    const v = $("rollupAllSearch").value.trim();
    if (_rollupContracts[v]) { rollupSelectContract(v, "all"); return; }   // a full cid chosen from the list
    clearTimeout(_rst); _rst = setTimeout(() => rollupSearchAll(v), 250);
  };
  if (!window._rollupTimer) window._rollupTimer = setInterval(() => {
    if (state.activeTab === "rollup" && state.wallet) rollupRefresh();   // pending deploys land without a manual refresh
  }, 15000);
}

async function rollupLoadExamples() {
  if (_rollupExamples) return;
  try {
    const j = await (await fetch(execBase() + "/exec/examples", { cache: "no-store" })).json();
    _rollupExamples = j.examples || {};
    const sel = $("rollupExample");
    for (const name of Object.keys(_rollupExamples)) {
      const o = document.createElement("option"); o.value = name; o.textContent = name; sel.appendChild(o);
    }
  } catch (e) { _rollupExamples = {}; }
}

// pending deploys tracked locally (per ns) so the pickers show them BEFORE they land at finality
function rollupPendLoad() { try { return JSON.parse(localStorage.getItem("nado_rollup_pending") || "{}"); } catch { return {}; } }
function rollupPendSave(p) { try { localStorage.setItem("nado_rollup_pending", JSON.stringify(p)); } catch (e) {} }
function rollupAddPending(ns, cid, methods, abi) {
  const p = rollupPendLoad(); (p[ns] = p[ns] || {})[cid] = { methods, abi: abi || {}, ts: Date.now() }; rollupPendSave(p);
}

// refresh MY contracts (deployer-filtered + bounded) + local pending; the "all" picker is search-driven so it
// never bulk-loads. _rollupContracts ACCUMULATES (mine + whatever you've searched/selected) for method lookup.
async function rollupRefresh() {
  const ns = rollupNs(), me = state.wallet && state.wallet.address;
  let cs = [];
  if (me) {
    try { cs = ((await (await fetch(execBase() + "/exec/contracts?ns=" + encodeURIComponent(ns)
      + "&deployer=" + encodeURIComponent(me) + "&limit=200", { cache: "no-store" })).json()).contracts) || []; }
    catch (e) { /* exec node unreachable -> still show local pending */ }
  }
  cs.forEach((c) => { _rollupContracts[c.cid] = { methods: c.methods || [], deployer: c.deployer, pending: false, abi: c.abi || {} }; });
  const onchain = new Set(cs.map((c) => c.cid));
  const pend = rollupPendLoad(), pendNs = pend[ns] || {};
  let changed = false;
  for (const cid of Object.keys(pendNs)) {
    if (onchain.has(cid)) { delete pendNs[cid]; changed = true; }         // landed on-chain -> drop the pending copy
    else _rollupContracts[cid] = { methods: pendNs[cid].methods || [], deployer: me, pending: true, abi: pendNs[cid].abi || {} };
  }
  if (changed) { pend[ns] = pendNs; rollupPendSave(pend); }
  rollupFillMine();
}

function _rollupOpt(cid, info) {
  const o = document.createElement("option"); o.value = cid;
  o.textContent = cid.slice(0, 12) + "… · " + (info.methods.join(", ") || "—") + (info.pending ? "  (" + i18("rollup.pendingTag", "pending") + ")" : "");
  return o;
}

function rollupFillMine() {
  const me = state.wallet && state.wallet.address;
  const sel = $("rollupMine"), ph = sel.firstElementChild;                // keep the "— select —" placeholder
  sel.innerHTML = ""; sel.appendChild(ph);
  for (const cid of Object.keys(_rollupContracts)) {
    if (_rollupContracts[cid].deployer !== me) continue;
    sel.appendChild(_rollupOpt(cid, _rollupContracts[cid]));
  }
  sel.value = [...sel.options].some((o) => o.value === _rollupActive) ? _rollupActive : "";
}

// search ALL contracts by cid prefix (bounded to 50) -> the datalist; caches results for method lookup
async function rollupSearchAll(q) {
  const dl = $("rollupAllList"); if (!dl) return;
  try {
    const u = execBase() + "/exec/contracts?ns=" + encodeURIComponent(rollupNs())
      + (q ? "&prefix=" + encodeURIComponent(q) : "") + "&limit=50";
    const cs = ((await (await fetch(u, { cache: "no-store" })).json()).contracts) || [];
    dl.innerHTML = "";
    for (const c of cs) {
      _rollupContracts[c.cid] = { methods: c.methods || [], deployer: c.deployer, pending: false, abi: c.abi || {} };
      const o = document.createElement("option"); o.value = c.cid;
      o.label = c.cid.slice(0, 12) + "… · " + (c.methods || []).join(", ");
      dl.appendChild(o);
    }
  } catch (e) { /* exec node unreachable */ }
}

function rollupSelectContract(cid, from) {
  _rollupActive = cid;
  if (from === "mine") $("rollupAllSearch").value = "";                   // one picker active at a time
  else { $("rollupMine").value = ""; $("rollupAllSearch").value = cid; }
  rollupLoadMethods(cid);
  rollupShowDetail(cid);
}

function rollupLoadMethods(cid) {
  const sel = $("rollupCallMethodSel");
  sel.innerHTML = "";
  const ph = document.createElement("option"); ph.value = ""; ph.textContent = i18("rollup.selectMethod", "— method —"); sel.appendChild(ph);
  for (const m of ((_rollupContracts[cid] || {}).methods || [])) {
    const o = document.createElement("option"); o.value = m; o.textContent = m; sel.appendChild(o);
  }
  rollupRenderArgs(cid, "");   // reset arg inputs + doc for the new contract
}

// render labelled arg inputs + the method's doc from the contract ABI; if the method has no ABI, fall back
// to a raw JSON args field so any contract is still callable.
function rollupRenderArgs(cid, method) {
  const doc = $("rollupMethodDoc"), box = $("rollupArgs"), jsonf = $("rollupCallArgs");
  doc.textContent = ""; box.innerHTML = "";
  const info = _rollupContracts[cid] || {};
  const abi = (info.abi || {})[method];
  let argNames = null;
  if (method && abi) {                                  // ABI -> named, documented arg fields
    if (abi.doc) doc.textContent = abi.doc;
    argNames = abi.args || [];
  } else if (method && info.code && info.code[method]) { // no ABI -> infer arg COUNT from the bytecode's ARG(i)
    let maxi = -1;
    for (const ins of info.code[method]) if (ins[0] === "ARG" && typeof ins[1] === "number") maxi = Math.max(maxi, ins[1]);
    argNames = Array.from({ length: maxi + 1 }, (_, i) => "arg" + i);
  }
  if (argNames) {
    jsonf.classList.add("hidden");
    argNames.forEach((name, i) => {
      const wrap = document.createElement("div"); wrap.className = "mt";
      const lab = document.createElement("label"); lab.textContent = name; wrap.appendChild(lab);
      const inp = document.createElement("input"); inp.className = "rollup-arg"; inp.dataset.i = i; inp.placeholder = name;
      wrap.appendChild(inp); box.appendChild(wrap);
    });
    if (!argNames.length) box.innerHTML = '<span class="faint small">' + escapeHtml(i18("rollup.noArgs", "no arguments")) + '</span>';
  } else if (method) {
    jsonf.classList.remove("hidden");   // code not loaded yet -> raw JSON fallback (re-renders once detail arrives)
  } else {
    jsonf.classList.add("hidden");
  }
}

async function rollupShowDetail(cid) {
  const d = $("rollupDetail"), info = _rollupContracts[cid] || { methods: [], pending: false };
  const head = '<div class="label">' + i18("rollup.contractId", "Contract") + '</div><div class="addr small break">' + escapeHtml(cid) + '</div>'
    + '<div class="label mt">' + i18("rollup.methods", "Methods") + '</div><div class="mono small">' + escapeHtml(info.methods.join(", ") || "—") + '</div>';
  if (info.pending) { d.innerHTML = head + '<div class="faint small mt">' + escapeHtml(i18("rollup.pendingDetail", "Pending — appears once applied at finality (a few minutes).")) + '</div>'; return; }
  d.innerHTML = head + '<div class="faint small mt">' + escapeHtml(i18("rollup.loading", "Loading…")) + '</div>';
  try {
    const r = await fetch(execBase() + "/exec/contract?ns=" + encodeURIComponent(rollupNs()) + "&cid=" + encodeURIComponent(cid), { cache: "no-store" });
    const c = r.ok ? await r.json() : {};
    if (c.code) { info.code = c.code; if ($("rollupCallMethodSel").value) rollupRenderArgs(cid, $("rollupCallMethodSel").value); }  // now that we have the bytecode, infer arg fields
    d.innerHTML = head + '<div class="label mt">' + i18("rollup.storage", "Storage") + '</div><pre class="mono small">' + escapeHtml(JSON.stringify(c.storage || {}, null, 1)) + '</pre>';
  } catch (e) { d.innerHTML = head; }
}

function _rollupParams() {
  const msg = $("rollupCallMsg"); msg.textContent = "";
  if (!_rollupActive) { msg.textContent = i18("rollup.needContract", "Select a contract first."); return null; }
  const method = ($("rollupCallMethodSel").value || "").trim();
  if (!method) { msg.textContent = i18("rollup.needMethod", "Select a method."); return null; }
  let args = [];
  const inputs = [...$("rollupArgs").querySelectorAll(".rollup-arg")].sort((a, b) => a.dataset.i - b.dataset.i);
  if (inputs.length) {
    // a number typed -> a number; anything else stays a string (matches the VM's int/str values)
    args = inputs.map((el) => { const raw = el.value.trim(); if (raw === "") return ""; try { const v = JSON.parse(raw); return (typeof v === "number" || typeof v === "string") ? v : raw; } catch { return raw; } });
  } else {
    const raw = ($("rollupCallArgs").value || "").trim();
    if (raw) { try { args = JSON.parse(raw); if (!Array.isArray(args)) throw 0; } catch (e) { msg.textContent = i18("rollup.badArgs", "Args must be a JSON array."); return null; } }
  }
  return { cid: _rollupActive, method, args };
}

async function rollupDeploy() {
  const msg = $("rollupDeployMsg"); msg.textContent = "";
  let code;
  try { code = JSON.parse($("rollupCode").value); } catch (e) { msg.textContent = i18("rollup.badJson", "Code must be valid JSON."); return; }
  const latest = await getLatestBlock();
  if (!latest) { msg.textContent = i18("rollup.relayDown", "Relay unavailable."); return; }
  const ns = rollupNs(), nonce = randNonce();
  const cid = blake2bHash(["deploy", state.wallet.address, code, nonce]).slice(0, 32);   // deterministic, known now
  const payload = { op: "deploy", code, nonce };
  if (ns !== "default") payload.ns = ns;
  // attach the loaded example's ABI (arg names + docs) if the code is still the one we loaded, so the
  // deployed contract is self-describing in the wallet
  const abi = ($("rollupCode").value === _rollupLoadedCode) ? _rollupLoadedAbi : {};
  if (abi && Object.keys(abi).length) payload.abi = abi;
  const tx = buildBlobTx(state.wallet, payload, latest.block_number + 8, MIN_TX_FEE, nowSeconds());
  const res = await submitTransaction(tx);
  if (res.data && res.data.result) {
    rollupAddPending(ns, cid, Object.keys(code), payload.abi);
    msg.innerHTML = i18("rollup.deployedAs", "Deployed as") + ' <span class="addr">' + escapeHtml(cid)
      + '</span> — ' + escapeHtml(i18("rollup.afterFinality", "live after finality (a few minutes)."));
    await rollupRefresh();
    rollupSelectContract(cid, "mine");                                    // auto-select it, ready to call
  } else {
    msg.textContent = i18("rollup.rejected", "Rejected: ") + ((res.data && res.data.message) || "");
  }
}

async function rollupCall() {
  const p = _rollupParams(); if (!p) return;
  const latest = await getLatestBlock();
  if (!latest) { $("rollupCallMsg").textContent = i18("rollup.relayDown", "Relay unavailable."); return; }
  const payload = { op: "call", contract: p.cid, method: p.method, args: p.args };
  const ns = rollupNs(); if (ns !== "default") payload.ns = ns;
  const tx = buildBlobTx(state.wallet, payload, latest.block_number + 8, MIN_TX_FEE, nowSeconds());
  const res = await submitTransaction(tx);
  const ok = !!(res.data && res.data.result);
  const status = ok ? i18("rollup.histSent", "sent (applies at finality)") : i18("rollup.rejected", "Rejected: ") + ((res.data && res.data.message) || "");
  $("rollupCallMsg").textContent = ok ? i18("rollup.callSent", "Call submitted — state updates after finality.") : status;
  rollupHistLog(ns, { cid: p.cid, method: p.method, args: p.args, ok, status, ts: Date.now() });
}

async function rollupView() {
  const p = _rollupParams(); if (!p) return;
  const out = $("rollupViewResult"); out.textContent = i18("rollup.loading", "Loading…");
  const ns = rollupNs();
  try {
    const u = execBase() + "/exec/view?ns=" + encodeURIComponent(ns) + "&cid=" + encodeURIComponent(p.cid)
      + "&method=" + encodeURIComponent(p.method) + "&args=" + encodeURIComponent(JSON.stringify(p.args));
    const j = await (await fetch(u, { cache: "no-store" })).json();
    out.textContent = i18("rollup.result", "Result: ") + JSON.stringify(j.result);
    rollupHistLog(ns, { cid: p.cid, method: p.method, args: p.args, ok: true, status: "→ " + JSON.stringify(j.result), ts: Date.now() });
  } catch (e) { out.textContent = i18("rollup.execDown", "Execution node unreachable."); }
}

// per-namespace local call history (last 30) shown in the tab — immediate feedback for what you called
function rollupHistLog(ns, entry) {
  let all = {}; try { all = JSON.parse(localStorage.getItem("nado_rollup_hist") || "{}"); } catch (e) {}
  const arr = all[ns] || []; arr.unshift(entry); all[ns] = arr.slice(0, 30);
  try { localStorage.setItem("nado_rollup_hist", JSON.stringify(all)); } catch (e) {}
  rollupRenderHistory();
}
function rollupRenderHistory() {
  const el = $("rollupHistory"); if (!el) return;
  let arr = []; try { arr = (JSON.parse(localStorage.getItem("nado_rollup_hist") || "{}"))[rollupNs()] || []; } catch (e) {}
  if (!arr.length) { el.innerHTML = '<span class="faint">' + escapeHtml(i18("rollup.noHistory", "No calls yet.")) + '</span>'; return; }
  el.innerHTML = arr.map((e) => '<div class="rollup-hist"><span class="mono">' + escapeHtml((e.cid || "").slice(0, 10)) + '….' + escapeHtml(e.method)
    + '(' + escapeHtml(JSON.stringify(e.args)) + ')</span> <span class="' + (e.ok ? "faint" : "err") + '">' + escapeHtml(e.status) + '</span> '
    + '<span class="faint">' + escapeHtml(new Date(e.ts).toLocaleTimeString()) + '</span></div>').join("");
}

/* ----------------------------------------------------------------------------------------------
 * MULTISIG tab — opt-in M-of-N shared accounts, mirroring ops/multisig_ops.py byte-for-byte:
 *   address = make_address(blake2b(["nado-msig-v1", threshold, sortedMembers]))   (the address IS the policy)
 * A spend proposal is an ordinary tx whose SIGNED body carries the descriptor and whose `signature`
 * is a LIST of {public_key, signature} member entries over the txid. Because each entry signs the
 * txid (which commits everything), co-signers can sign independently in any order and exchange the
 * proposal JSON over any channel.
 * -------------------------------------------------------------------------------------------- */
const MSIG_MAX_MEMBERS = 16;
const MSIG_TARGET_HEADROOM = 300;   // blocks of co-signing time (mempool accepts < tip+360)

function msigAddress(threshold, members) {
  return makeAddress(blake2bHash(["nado-msig-v1", threshold, members]));
}

/* BigInt-safe JSON parse for PASTED proposals: raw amounts can exceed 2^53 and JSON.parse would
 * silently round them — the co-signer would then re-hash a DIFFERENT body and (correctly) refuse to
 * sign, with a baffling error. Integers parse to Number when safe, BigInt when not; floats reject
 * (a tx body never contains one). */
function jsonParseBig(text) {
  let i = 0;
  const err = (m) => { throw new Error(i18("msig.badJson", "This is not a valid proposal ({m}).", { m })); };
  const ws = () => { while (i < text.length && " \t\n\r".includes(text[i])) i++; };
  function str() {
    const re = /"(?:[^"\\]|\\.)*"/y; re.lastIndex = i;
    const m = re.exec(text); if (!m) err("bad string");
    i = re.lastIndex; return JSON.parse(m[0]);
  }
  function num() {
    const re = /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/y; re.lastIndex = i;
    const m = re.exec(text); if (!m) err("unexpected token");
    if (/[.eE]/.test(m[0])) err("float in tx body");
    i = re.lastIndex;
    const n = Number(m[0]);
    return Number.isSafeInteger(n) ? n : BigInt(m[0]);
  }
  function value() {
    ws();
    const c = text[i];
    if (c === "{") {
      i++; const o = {}; ws();
      if (text[i] === "}") { i++; return o; }
      for (;;) {
        ws(); if (text[i] !== '"') err("expected key");
        const k = str(); ws();
        if (text[i++] !== ":") err("expected :");
        o[k] = value(); ws();
        const d = text[i++];
        if (d === "}") return o;
        if (d !== ",") err("expected , or }");
      }
    }
    if (c === "[") {
      i++; const a = []; ws();
      if (text[i] === "]") { i++; return a; }
      for (;;) {
        a.push(value()); ws();
        const d = text[i++];
        if (d === "]") return a;
        if (d !== ",") err("expected , or ]");
      }
    }
    if (c === '"') return str();
    if (text.startsWith("true", i)) { i += 4; return true; }
    if (text.startsWith("false", i)) { i += 5; return false; }
    if (text.startsWith("null", i)) { i += 4; return null; }
    return num();
  }
  const v = value(); ws();
  if (i !== text.length) err("trailing data");
  return v;
}

function msigReadDescriptor() {
  const members = [...new Set(($("msigMembers").value || "").split(/[\s,;]+/)
    .map((s) => s.trim().toLowerCase()).filter(Boolean))].sort();
  if (members.length < 2 || members.length > MSIG_MAX_MEMBERS)
    throw new Error(i18("msig.badCount", "Enter 2–16 distinct member addresses."));
  for (const m of members)
    if (!validateAddress(m)) throw new Error(i18("msig.badMember", "Not a valid ndo… address: {a}", { a: m }));
  const threshold = parseInt(($("msigThreshold").value || "").trim(), 10);
  if (!(threshold >= 1 && threshold <= members.length))
    throw new Error(i18("msig.badThreshold", "Signatures required must be between 1 and the number of members."));
  return { threshold, members };
}

/* Verify a pasted proposal's SHAPE + txid before doing anything with it — a member must never sign
 * (or display as trustworthy) a body that doesn't hash to the txid it claims. Returns the tx. */
function msigCheckProposal(tx) {
  if (!tx || typeof tx !== "object" || !tx.multisig || !Array.isArray(tx.signature) || !tx.txid)
    throw new Error(i18("msig.notProposal", "This is not a multisig proposal."));
  const d = tx.multisig;
  if (!(Array.isArray(d.members) && d.members.length >= 2 && d.threshold >= 1))
    throw new Error(i18("msig.notProposal", "This is not a multisig proposal."));
  const body = {};
  for (const k of Object.keys(tx)) if (k !== "signature" && k !== "txid") body[k] = tx[k];
  if (createTxid(body) !== tx.txid)
    throw new Error(i18("msig.txidMismatch", "Proposal id does not match its contents — do not sign it."));
  if (tx.sender !== msigAddress(d.threshold, d.members))
    throw new Error(i18("msig.senderMismatch", "Proposal sender does not match its member list — do not sign it."));
  return tx;
}

/* Add THIS wallet's signature entry (if it is a member and hasn't signed). Returns true if added. */
function msigTrySignLocal(tx) {
  const w = state.wallet;
  if (!w || !tx.multisig.members.includes(w.address)) return false;
  if (tx.signature.some((e) => e && makeAddress(String(e.public_key || "")) === w.address)) return false;
  const { publicKey, secretKey } = ml_dsa44.keygen(hexToBytes(w.privateKey));
  const m = hexToBytes(tx.txid);
  let sig = null;   // hedged signing can rarely produce a non-verifying sig — verify + retry (see finalizeTransaction)
  for (let k = 0; k < 8; k++) {
    const s = ml_dsa44.sign(secretKey, m);
    if (ml_dsa44.verify(publicKey, m, s)) { sig = bytesToHex(s); break; }
  }
  if (!sig) throw new Error("could not produce a verifying signature — please retry");
  tx.signature.push({ public_key: bytesToHex(publicKey), signature: sig });
  return true;
}

function msigBlobTx() {
  const raw = ($("msigBlob").value || "").trim();
  if (!raw) return null;
  return msigCheckProposal(jsonParseBig(raw));
}

const LS_MSIG = () => "nado_msig_" + (state.wallet ? state.wallet.address : "_");

async function msigDerive() {
  try {
    const d = msigReadDescriptor();
    const addr = msigAddress(d.threshold, d.members);
    $("msigAddr").textContent = addr;
    show("msigDerived", true);
    setMsg("msigDeriveMsg", i18("msig.derived", "{m}-of-{n} account ready — fund it like any address.", { m: d.threshold, n: d.members.length }), "ok");
    try { localStorage.setItem(LS_MSIG(), JSON.stringify(d)); } catch (e) {}
    const acc = await getAccount(addr);
    $("msigBal").textContent = rawToNado(BigInt((acc && acc.balance) || 0)) + " NADO";
  } catch (e) { show("msigDerived", false); setMsg("msigDeriveMsg", e.message, "err"); }
}

async function msigPropose() {
  const btn = $("btnMsigPropose"); btn.disabled = true;
  try {
    const d = msigReadDescriptor();
    const sender = msigAddress(d.threshold, d.members);
    // lowercase like doSend: this string becomes the signed recipient (aliases are lowercase on-chain)
    const recipient = $("msigTo").value.trim().toLowerCase();
    if (!validateAddress(recipient)) {
      if (looksLikeAlias(recipient)) {
        setMsg("msigProposeMsg", i18("quorum.resolving", "Resolving alias…"), null);
        const owner = await resolveAlias(recipient);
        if (!owner) { setMsg("msigProposeMsg", i18("msig.aliasMissing", "That alias isn't registered."), "err"); return; }
      } else {
        setMsg("msigProposeMsg", i18("msg.badRecipient", "Invalid recipient — a 49-char ndo… address or a registered alias name."), "err"); return;
      }
    }
    let rawAmount;
    try { rawAmount = nadoToRaw($("msigAmount").value); } catch (e) { setMsg("msigProposeMsg", i18("msg.badAmount", "Invalid amount."), "err"); return; }
    if (rawAmount <= 0n) { setMsg("msigProposeMsg", i18("msg.amountPos", "Amount must be greater than zero."), "err"); return; }
    const fee = MIN_TX_FEE * d.members.length;   // consensus floor is MIN_TX_FEE per signature ENTRY — cover all members signing
    const acc = await getAccount(sender);
    const balance = BigInt((acc && acc.balance) || 0);
    if (rawAmount + BigInt(fee) > balance) {
      setMsg("msigProposeMsg", i18("msig.insufficient", "The shared account holds {b} NADO — not enough for this amount + fee.", { b: rawToNado(balance) }), "err"); return;
    }
    const latest = await getLatestBlock();
    const body = {
      sender, recipient, amount: rawAmount, timestamp: nowSeconds(), data: "",
      nonce: randNonce(), max_block: latest.block_number + MSIG_TARGET_HEADROOM,
      chain_id: CHAIN_ID, multisig: { threshold: d.threshold, members: d.members }, fee,
    };
    const tx = { ...body, txid: createTxid(body), signature: [] };
    try { msigTrySignLocal(tx); } catch (e) { setMsg("msigProposeMsg", e.message, "err"); return; }
    $("msigBlob").value = canonicalize(tx);
    msigRefreshStatus();
    setMsg("msigProposeMsg", i18("msig.proposed", "Proposal created below — copy it and pass it to your co-signers."), "ok");
  } catch (e) { setMsg("msigProposeMsg", e.message, "err"); }
  finally { btn.disabled = false; }
}

function msigRefreshStatus() {
  const box = $("msigStatus");
  let tx = null;
  try { tx = msigBlobTx(); }
  catch (e) { box.innerHTML = '<span class="warn">' + e.message + "</span>"; return; }
  if (!tx) { box.textContent = ""; return; }
  const d = tx.multisig;
  const mine = state.wallet && d.members.includes(state.wallet.address);
  const signed = tx.signature.map((e) => makeAddress(String(e.public_key || "")));
  const iSigned = state.wallet && signed.includes(state.wallet.address);
  const ready = signed.length >= d.threshold;
  const rows = [
    i18("msig.stFrom", "From {a}", { a: tx.sender.slice(0, 12) + "…" }),
    i18("msig.stTo", "to {a}", { a: tx.recipient }),
    rawToNado(BigInt(tx.amount)) + " NADO",
    i18("msig.stSigs", "signatures {have}/{need}", { have: signed.length, need: d.threshold }),
    i18("msig.stExpiry", "valid until block {b}", { b: tx.max_block }),
  ];
  let verdict;
  if (ready) verdict = '<span class="ok">' + i18("msig.stReady", "Ready to submit ✓") + "</span>";
  else if (iSigned) verdict = '<span class="faint">' + i18("msig.stWaiting", "You signed — pass it to the next co-signer.") + "</span>";
  else if (mine) verdict = '<span class="warn">' + i18("msig.stYourTurn", "Your signature is needed.") + "</span>";
  else verdict = '<span class="faint">' + i18("msig.stNotMember", "This wallet is not a member of the account.") + "</span>";
  box.innerHTML = rows.join(" · ") + "<br>" + verdict;
}

async function msigSign() {
  try {
    const tx = msigBlobTx();
    if (!tx) { setMsg("msigMsg", i18("msig.pasteFirst", "Paste a proposal first."), "err"); return; }
    const added = msigTrySignLocal(tx);
    $("msigBlob").value = canonicalize(tx);
    msigRefreshStatus();
    if (added) setMsg("msigMsg", i18("msig.signedOk", "Signature added ✓ — copy the proposal and pass it on (or submit if it's ready)."), "ok");
    else setMsg("msigMsg", i18("msig.alreadySigned", "Nothing to add — you already signed, or this wallet is not a member."), null);
  } catch (e) { setMsg("msigMsg", e.message, "err"); }
}

async function msigSubmit() {
  const btn = $("btnMsigSubmit"); btn.disabled = true;
  try {
    const tx = msigBlobTx();
    if (!tx) { setMsg("msigMsg", i18("msig.pasteFirst", "Paste a proposal first."), "err"); return; }
    const d = tx.multisig;
    const ok = await uiConfirm({
      title: i18("msig.dlgTitle", "Submit multisig transfer"),
      rows: [
        { k: i18("dlg.amount", "Amount"), v: rawToNado(BigInt(tx.amount)) + " NADO" },
        { k: i18("dlg.to", "To"), v: tx.recipient },
        { k: i18("dlg.fee", "Network fee"), v: rawToNado(BigInt(tx.fee)) + " NADO" },
        { k: i18("msig.dlgSigs", "Signatures"), v: tx.signature.length + " / " + d.threshold },
      ],
    });
    if (!ok) { setMsg("msigMsg", i18("msg.cancelled", "Cancelled."), null); return; }
    const res = await submitTransaction(tx);
    if (res.ok && res.data && res.data.result) {
      setMsg("msigMsg", i18("msig.submitted", "Submitted ✓ — the transfer settles on-chain in a few blocks."), "ok");
    } else {
      setMsg("msigMsg", (res.data && res.data.message) || i18("quorum.rejected", "Rejected"), "err");
    }
  } catch (e) { setMsg("msigMsg", e.message, "err"); }
  finally { btn.disabled = false; }
}

async function renderMsig() {
  // restore this wallet's last descriptor so the shared account is one tap away
  try {
    const saved = JSON.parse(localStorage.getItem(LS_MSIG()) || "null");
    if (saved && saved.members && !$("msigMembers").value.trim()) {
      $("msigMembers").value = saved.members.join("\n");
      $("msigThreshold").value = String(saved.threshold);
      await msigDerive();
    }
  } catch (e) {}
  msigRefreshStatus();
}

/* ----------------------------------------------------------------------------------------------
 * MESSAGES tab (doc/messaging.md): off-chain, end-to-end-encrypted, post-quantum DMs. The crypto +
 * transport live in ./messaging.js (ML-KEM-768 encrypt + ML-DSA sign, tag-routed through the node's
 * blind message pool). Here we handle identity/prekey publish, send, an inbox poll (tag-scan ->
 * trial-decapsulate), local history, delivery acks, and the "not delivered" status.
 * -------------------------------------------------------------------------------------------- */
let MSG = null;
async function loadMessaging() {
  if (MSG) return MSG;
  try { MSG = await import('./messaging.js'); }
  catch (e) { MSG = null; log("err", "Messaging unavailable: " + (e && e.message || e)); }
  return MSG;
}
function _msgKey(suffix) { return "nado_msg_v1_" + (state.wallet ? state.wallet.address : "_") + "_" + suffix; }
function msgHistLoad() { try { return JSON.parse(localStorage.getItem(_msgKey("hist")) || "{}"); } catch { return {}; } }
function msgHistSave(h) { try { localStorage.setItem(_msgKey("hist"), JSON.stringify(h)); } catch (e) {} }
function msgCursor() { return parseInt(localStorage.getItem(_msgKey("cursor")) || "0", 10) || 0; }
function msgSetCursor(n) { try { localStorage.setItem(_msgKey("cursor"), String(n)); } catch (e) {} }
function _nowSec() { return Math.floor(Date.now() / 1000); }
function _lastTs(conv) { return conv.messages.length ? conv.messages[conv.messages.length - 1].ts : 0; }

function msgIdentity() {
  if (!MSG || !state.wallet || !state.wallet.privateKey) return null;
  if (!state._msgId || state._msgId.addr !== state.wallet.address) {
    state._msgId = { addr: state.wallet.address, id: MSG.identity(state.wallet.privateKey) };  // per-account
  }
  return state._msgId.id;
}
function myPrimaryAlias() { return (state.myAliases && state.myAliases[0]) || null; }

// Resolve a recipient's ML-KEM-768 messaging pubkey (hex). Prefers the ON-CHAIN key (bound to their identity
// by a `msgkey` tx — consensus state, never wiped, no pre-publish needed); falls back to a legacy off-chain
// prekey bundle for accounts that only ever published the old way.
async function msgFetchKemPub(addr) {
  try {
    const r = await fetch(relayBase() + "/msg_key?address=" + encodeURIComponent(addr), { cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    return j.kem_pub || (j.bundle && j.bundle.ik_pub) || null;
  } catch { return null; }
}

// Bind OUR ML-KEM messaging pubkey to our on-chain account (once), so anyone can DM us by address/alias with
// no setup on their side and it survives node restarts. Idempotent: skips if our key is already on-chain.
async function msgPublishPrekey() {
  const id = msgIdentity(); if (!id) return;
  if (state._msgPublished === state.wallet.address) return;
  try {
    const acc = await getAccount(state.wallet.address);
    if (acc && acc.kem_pub === id.kemPub) { state._msgPublished = state.wallet.address; return; }  // already bound
    const targetBlock = await nextTargetBlock();
    await submitTransaction(buildMsgkeyTx(state.wallet, id.kemPub, targetBlock, nowSeconds()));
    state._msgPublished = state.wallet.address;   // one publish per session; confirms on-chain within a block
  } catch (e) {}
}

async function msgOpen() {
  const m = await loadMessaging();
  if (!m) { $("msgThread").innerHTML = '<div class="empty">' + escapeHtml(i18("msg.needBundle", "Messaging needs the ML-KEM crypto bundle — reload the page.")) + '</div>'; return; }
  if (!msgIdentity()) return;
  if (state._msgPublished !== state.wallet.address) msgPublishPrekey().catch(() => {});   // be reachable
  $("msgSendBtn").onclick = () => msgSend().catch(() => {});
  $("msgNewBtn").onclick = () => { state.msgActivePeer = null; $("msgTo").value = ""; $("msgBody").value = ""; renderMessages(); $("msgTo").focus(); };
  $("msgBody").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); msgSend().catch(() => {}); } };
  if (state.msgActivePeer) msgMarkRead(state.msgActivePeer);
  renderMessages();
  msgInitBackground().catch(() => {});   // starts the shared poll (badge) if not already running
  msgPoll().catch(() => {});
}

async function msgSend() {
  const m = await loadMessaging(); if (!m) return;
  const toRaw = ($("msgTo").value || "").trim().toLowerCase();
  const body = ($("msgBody").value || "").trim();
  if (!toRaw || !body) return;
  let addr = toRaw;
  if (!/^ndo[0-9a-f]{40,}$/i.test(toRaw)) {                       // resolve an alias
    const owner = await resolveAlias(toRaw.replace(/^@/, ""));
    if (!owner) { $("msgHint").textContent = i18("msg.noAlias", "No such alias:") + " " + toRaw; return; }
    addr = owner;
  }
  const id = msgIdentity(), ts = _nowSec();
  const hist = msgHistLoad();
  const conv = (hist[addr] = hist[addr] || { alias: (addr !== toRaw ? toRaw : null), messages: [] });
  const kemPub = await msgFetchKemPub(addr);
  if (!kemPub) {
    conv.messages.push({ id: "local-" + ts + "-" + Math.floor(Math.random() * 1e6), dir: "out", body, ts,
      status: "undelivered", reason: i18("msg.noKeyYet", "no messaging key on-chain yet — they need to open NADO once to publish it") });
    msgHistSave(hist); $("msgBody").value = ""; renderMessages(); return;
  }
  let res, mid;
  try {
    const env = m.makeEnvelope(id, state.wallet.address, kemPub,
      { type: "msg", from: state.wallet.address, alias: myPrimaryAlias(), body, ts }, ts);
    mid = m.messageId(env);
    res = await (await fetch(relayBase() + "/message", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(env) })).json();
  } catch (e) { res = { result: false, reason: e && e.message || i18("msg.sendFail", "send failed") }; }
  conv.messages.push({ id: mid || ("local-" + ts), dir: "out", body, ts,
    status: (res && res.result) ? "sent" : "undelivered", reason: (res && res.result) ? null : (res && res.reason || i18("msg.sendFail", "send failed")) });
  msgHistSave(hist); $("msgBody").value = ""; renderMessages();
}

async function msgSendAck(m, id, toAddr, ackId) {
  const kemPub = await msgFetchKemPub(toAddr);
  if (!kemPub) return;
  const ts = _nowSec();
  const env = m.makeEnvelope(id, state.wallet.address, kemPub, { type: "ack", from: state.wallet.address, ackId, ts }, ts);
  try { await fetch(relayBase() + "/message", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(env) }); } catch (e) {}
}

async function msgPoll() {
  const m = await loadMessaging(); if (!m || !state.wallet) return;
  const id = msgIdentity(); if (!id) return;
  let data;
  try { data = await (await fetch(relayBase() + "/tags?since=" + msgCursor(), { cache: "no-store" })).json(); }
  catch { return; }
  const hist = msgHistLoad();
  let maxSeq = msgCursor(), changed = false;
  for (const t of (data.tags || [])) {
    if (t.seq > maxSeq) maxSeq = t.seq;
    let env;
    try { env = (await (await fetch(relayBase() + "/message?id=" + t.id, { cache: "no-store" })).json()).message; } catch { continue; }
    if (!env) continue;
    const pt = m.tryOpen(id, env);
    if (!pt) continue;                                            // not ours (or not decryptable)
    if (pt.type === "ack") {
      for (const c of Object.values(hist)) for (const msg of c.messages)
        if (msg.dir === "out" && msg.id === pt.ackId && msg.status !== "delivered") { msg.status = "delivered"; changed = true; }
    } else {
      const from = pt.from || env.sender;
      const conv = (hist[from] = hist[from] || { alias: pt.alias || null, messages: [] });
      if (pt.alias && !conv.alias) conv.alias = pt.alias;
      if (!conv.messages.some(x => x.id === t.id)) {
        const viewing = state.activeTab === "messages" && state.msgActivePeer === from;
        conv.messages.push({ id: t.id, dir: "in", body: pt.body, ts: pt.ts || env.ts, status: "received", read: viewing });
        changed = true;
        msgSendAck(m, id, from, t.id).catch(() => {});           // confirm delivery to the sender
      }
    }
  }
  const now = _nowSec();
  for (const c of Object.values(hist)) for (const msg of c.messages)
    if (msg.dir === "out" && msg.status === "sent" && now - msg.ts > 7 * 86400) {
      msg.status = "undelivered"; msg.reason = "not delivered — hasn't come online in 7 days"; changed = true;
    }
  if (maxSeq > msgCursor()) msgSetCursor(maxSeq);
  if (changed) { msgHistSave(hist); if (state.activeTab === "messages") renderMessages(); }
  updateMsgBadge();
}

// ---- unread badge on the Messages tab ---------------------------------------------------------
function msgUnreadCount() {
  const hist = msgHistLoad(); let n = 0;
  for (const c of Object.values(hist)) for (const msg of c.messages) if (msg.dir === "in" && !msg.read) n++;
  return n;
}
function updateMsgBadge() {
  const el = $("msgBadge"); if (!el) return;
  const n = msgUnreadCount();
  if (n > 0) { el.textContent = n > 99 ? "99+" : String(n); el.classList.remove("hidden"); }
  else el.classList.add("hidden");
}
function msgMarkRead(peer) {
  const hist = msgHistLoad(); const c = hist[peer]; if (!c) return;
  let changed = false;
  for (const msg of c.messages) if (msg.dir === "in" && !msg.read) { msg.read = true; changed = true; }
  if (changed) { msgHistSave(hist); updateMsgBadge(); }
}

// Background messaging: derive identity, publish the prekey, and poll so the unread badge updates even
// while another tab is open. Starts once per session after the wallet is ready.
async function msgInitBackground() {
  if (state._msgBgStarted) return;
  const m = await loadMessaging(); if (!m || !state.wallet) return;
  state._msgBgStarted = true;
  if (state._msgPublished !== state.wallet.address) msgPublishPrekey().catch(() => {});
  msgPoll().catch(() => {});
  if (!state._msgPollTimer) state._msgPollTimer = setInterval(() => { msgPoll().catch(() => {}); }, 20000);
}

function _msgStatusLabel(msg) {
  if (msg.dir === "in") return "";
  if (msg.status === "delivered") return i18("msg.st.delivered", "✓ delivered");
  if (msg.status === "sent") return i18("msg.st.sent", "· sent");
  if (msg.status === "undelivered") return "✕ " + (msg.reason || i18("msg.st.undelivered", "not delivered"));
  return "";
}

function renderMessages() {
  const listEl = $("msgConvList"), threadEl = $("msgThread");
  if (!listEl || !threadEl) return;
  const hist = msgHistLoad();
  const peers = Object.keys(hist).sort((a, b) => _lastTs(hist[b]) - _lastTs(hist[a]));
  // conversation list
  if (!peers.length) {
    listEl.innerHTML = '<div class="small faint" style="padding:4px 0">' + escapeHtml(i18("msg.noConv", "No conversations yet — enter an alias or address above and say hi.")) + '</div>';
  } else {
    listEl.innerHTML = peers.map((p) => {
      const c = hist[p], last = c.messages[c.messages.length - 1];
      const name = c.alias ? "@" + escapeHtml(c.alias) : escapeHtml(p.slice(0, 18)) + "…";
      const active = state.msgActivePeer === p ? " msgconv-active" : "";
      const prev = last ? escapeHtml((last.dir === "out" ? i18("msg.youPrefix", "You: ") : "") + last.body).slice(0, 46) : "";
      return `<button class="msgconv${active}" data-peer="${escapeHtml(p)}"><b>${name}</b><span class="small faint">${prev}</span></button>`;
    }).join("");
    listEl.querySelectorAll(".msgconv").forEach((b) => b.onclick = () => {
      state.msgActivePeer = b.dataset.peer;
      const c = hist[b.dataset.peer];
      $("msgTo").value = c && c.alias ? c.alias : b.dataset.peer;
      msgMarkRead(b.dataset.peer);
      renderMessages();
    });
  }
  // active thread
  const peer = state.msgActivePeer;
  if (!peer || !hist[peer]) {
    threadEl.innerHTML = '<div class="msgempty">' +
      escapeHtml(i18("msg.pick", "Select a conversation, or enter an alias/address above and send a message.")) + '</div>';
    return;
  }
  threadEl.innerHTML = hist[peer].messages.map((msg) => {
    const cls = msg.dir === "out" ? "msgbubble out" : "msgbubble in";
    const status = _msgStatusLabel(msg);
    return `<div class="${cls}"><div class="msgtext">${escapeHtml(msg.body)}</div>` +
      `<div class="msgmeta small faint">${_msgTime(msg.ts)}${status ? " · " + escapeHtml(status) : ""}</div></div>`;
  }).join("");
  threadEl.scrollTop = threadEl.scrollHeight;
}
function _msgTime(ts) { try { return new Date(ts * 1000).toLocaleString(); } catch { return ""; } }

/* ----------------------------------------------------------------------------------------------
 * Treasury Quorum tab (doc/treasury.md §3.3/§3.6): the treasury is spent ONLY when bonded stakers approve.
 * Propose a spend + vote (a fee-bearing treasury_vote whose approval weight is snapshotted), and execute a
 * proposal once it passes the 2/3 activated-stake quorum. pid is computed client-side (byte-identical to the
 * node's hashing.treasury_proposal_id — verified), so a vote binds to EXACTLY the displayed spend.
 * -------------------------------------------------------------------------------------------- */
const TREASURY_PROPOSAL_TTL = 43200;   // default proposal lifetime in blocks (must be <= node TREASURY_PROPOSAL_MAX_TTL)
function treasuryProposalId(recipient, amount, memo, nonce, expiry) {
  return blake2bHash(["treasury_spend", recipient, amount, memo || "", nonce, expiry]);
}
async function submitTreasurySpend(kind, recipient, amountRaw, memo, nonce, expiry, choice) {
  const latest = await getLatestBlock();
  if (!latest || typeof latest.block_number !== "number") throw new RelayUnreachable("relay unavailable");
  const exp = (expiry != null) ? expiry : latest.block_number + TREASURY_PROPOSAL_TTL;   // propose -> fresh window
  const spend = { recipient, amount: amountRaw, memo: memo || "", nonce, expiry: exp };
  const data = { pid: treasuryProposalId(recipient, amountRaw, memo, nonce, exp), spend };
  if (kind === "treasury_vote") data.choice = choice || "yes";   // yes=approve, no=oppose/withdraw (re-vote overwrites)
  const draft = { sender: state.wallet.address, recipient: kind, amount: 0, timestamp: nowSeconds(),
    data,
    nonce: randNonce(), public_key: state.wallet.publicKey,
    max_block: latest.block_number + 8, chain_id: CHAIN_ID };
  return submitTransaction(finalizeTransaction(draft, state.wallet.privateKey, MIN_TX_FEE));
}
async function proposeSpend() {
  const msg = $("qPropMsg");
  try {
    let to = ($("qPropRecipient").value || "").trim().toLowerCase();
    if (looksLikeAlias(to)) {                                     // accept a human-readable alias, resolve to its owner
      msg.textContent = i18("quorum.resolving", "Resolving alias…");
      const owner = await resolveAlias(to);
      if (!owner) throw new Error(i18("quorum.aliasErr", "Alias not found."));
      to = owner;
    }
    if (!(to.startsWith("ndo") && to.length === 49)) throw new Error(i18("quorum.badAddr", "Enter a valid ndo… address or a registered alias."));
    const amtRaw = nadoToRaw($("qPropAmount").value || "");
    if (!(amtRaw > 0n)) throw new Error(i18("quorum.badAmount", "Enter a positive amount."));
    const memo = ($("qPropMemo").value || "").slice(0, 256);
    msg.textContent = i18("quorum.submitting", "Submitting…");
    const res = await submitTreasurySpend("treasury_vote", to, Number(amtRaw), memo, randNonce(10));
    msg.textContent = res.ok ? i18("quorum.proposed", "Proposed + voted yes ✓") : ((res.data && res.data.message) || i18("quorum.rejected", "Rejected"));
    if (res.ok) { $("qPropRecipient").value = $("qPropAmount").value = $("qPropMemo").value = ""; setTimeout(() => renderQuorum().catch(() => {}), 1500); }
  } catch (e) { msg.textContent = e.message; }
}
async function _qAct(kind, p, choice, btn) {
  const label = btn ? btn.textContent : null;
  if (btn) { btn.disabled = true; btn.textContent = i18("quorum.sending", "Submitting…"); }
  try {
    const res = await submitTreasurySpend(kind, p.recipient, p.amount, p.memo, p.nonce, p.expiry, choice);
    if (res.ok) {
      toast(kind === "treasury_execute"
        ? i18("quorum.execOk", "Payout triggered ✓ — it settles on-chain in a few blocks.")
        : i18("quorum.voteOk", "Vote submitted ✓ — it counts in a few blocks."), "info", 6000);
      if (btn) btn.textContent = i18("quorum.pending", "Pending…");   // stays disabled until the re-render replaces it
      // a treasury tx confirms a few blocks later, so refresh several times instead of once
      [4000, 10000, 20000, 35000].forEach((t) => setTimeout(() => renderQuorum().catch(() => {}), t));
    } else {
      if (btn) { btn.disabled = false; btn.textContent = label; }
      uiAlert((res.data && res.data.message) || i18("quorum.rejected", "Rejected"));
    }
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = label; }
    uiAlert(e.message);
  }
}
async function renderQuorum() {
  const box = $("qProposals");
  if (!box) return;
  if ($("qPropBtn")) $("qPropBtn").onclick = proposeSpend;
  if ($("qPropMine")) $("qPropMine").onclick = () => { if (state.wallet) $("qPropRecipient").value = state.wallet.address; };
  let d;
  try { d = await (await fetch(relayBase() + "/treasury_status", { cache: "no-store" })).json(); }
  catch (e) { box.textContent = i18("quorum.loadErr", "Could not load treasury status."); return; }
  if ($("qTreasury")) $("qTreasury").textContent = rawToNado(BigInt(d.treasury || 0)) + " NADO";
  if ($("qMaxSpend")) $("qMaxSpend").textContent = rawToNado(BigInt(d.max_spend || 0)) + " NADO";
  if ($("qBurn")) $("qBurn").textContent = "#" + (d.next_burn_block || 0);
  // voter eligibility: only bonded (savings-lane) stake may propose or vote
  let bonded = 0n;
  try { const acc = await getAccount(state.wallet.address); bonded = BigInt((acc && acc.bonded) || 0); } catch (e) {}
  const canPropose = bonded >= B_MIN_RAW;
  const total = num(d.total_activated_shares) || 0;
  if ($("qPropBtn")) $("qPropBtn").disabled = !canPropose;
  if ($("qStatus")) {
    if (!canPropose) $("qStatus").innerHTML = '<span class="warn">' + i18("quorum.needBond2", "Proposing and voting need a bonded stake of at least {min} NADO — you have {have} NADO bonded. Bond more in the Savings tab (balance alone doesn't count).", { min: rawToNado(B_MIN_RAW), have: rawToNado(bonded) }) + "</span>";
    else if (total === 0) $("qStatus").innerHTML = '<span class="faint">' + i18("quorum.aging", "Bonded ✓ — your stake counts toward votes once it passes the activation window.") + "</span>";
    else $("qStatus").innerHTML = '<span class="ok">' + i18("quorum.canVote", "You can propose and vote (bonded ✓).") + "</span>";
  }
  const props = d.proposals || [];
  if (!props.length) { box.innerHTML = `<p class="small faint">${i18("quorum.none", "No proposals yet.")}</p>`; return; }
  box.innerHTML = props.map((p, i) => {
    const appr = num(p.approving_shares) || 0;
    const pct = total > 0 ? Math.min(100, Math.round(appr * 100 / total)) : 0;
    const stKey = p.status === "executed" ? "quorum.executed" : (p.status === "passed" ? "quorum.passed" : "quorum.open");
    const stEn = p.status === "executed" ? "paid ✓" : (p.status === "passed" ? "passed — ready" : "open");
    const canVote = canPropose && p.status === "open";
    const canExec = canPropose && p.status === "passed" && p.within_cap;
    return `<div class="stat mt" style="text-align:left">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
        <b>${rawToNado(BigInt(p.amount || 0))} NADO</b>
        <span class="badge ${p.status === "open" ? "idle" : "ok"}">${i18(stKey, stEn)}</span></div>
      <div class="small faint">→ ${escapeHtml((p.recipient || "").slice(0, 18))}…${p.memo ? " · " + escapeHtml(p.memo) : ""}</div>
      <div class="progress mt"><span style="display:block;height:100%;width:${pct}%;background:var(--accent)"></span></div>
      <div class="small faint">${i18("quorum.tally", "{pct}% of stake · needs 2/3 · {v} voter(s)", { pct, v: p.voters || 0 })}${p.within_cap ? "" : " · " + i18("quorum.overCap", "over cap")}</div>
      ${canVote ? `<button class="accent mt small qvote" data-i="${i}" style="width:100%">${i18("quorum.voteYes", "Vote yes")}</button>` : ""}
      ${canVote ? `<button class="ghost mt small qoppose" data-i="${i}" style="width:100%">${i18("quorum.oppose", "Oppose / withdraw vote")}</button>` : ""}
      ${canExec ? `<button class="primary mt small qexec" data-i="${i}" style="width:100%">${i18("quorum.execute", "Execute payout")}</button>` : ""}</div>`;
  }).join("");
  box.querySelectorAll(".qvote").forEach(b => b.onclick = () => _qAct("treasury_vote", props[+b.dataset.i], "yes", b));
  box.querySelectorAll(".qoppose").forEach(b => b.onclick = () => _qAct("treasury_vote", props[+b.dataset.i], "no", b));
  box.querySelectorAll(".qexec").forEach(b => b.onclick = () => _qAct("treasury_execute", props[+b.dataset.i], undefined, b));
}

/* ----------------------------------------------------------------------------------------------
 * Shielded pool (doc/privacy.md) — deposit/withdraw against the exec-layer zk-STARK pool. Notes are
 * private, so the wallet keeps its OWN notes locally (localStorage per address); the pool never reveals
 * which note is whose. Transparent phase today: the witness is the proof; the STARK slots in later.
 * -------------------------------------------------------------------------------------------- */
let _shInit = false;
function ensureShielded() { if (!_shInit) { alghash.initAlghash(blake2bHash); _shInit = true; } }
function shieldStoreKey() { return "nado.shieldf." + (state.wallet ? state.wallet.address : "none"); }
function loadNotes() { try { return JSON.parse(localStorage.getItem(shieldStoreKey()) || "[]"); } catch (e) { return []; } }
function saveNotes(notes) { try { localStorage.setItem(shieldStoreKey(), JSON.stringify(notes)); } catch (e) {} }
function _randField() {   // a random Goldilocks field element (note randomness rho)
  const b = crypto.getRandomValues(new Uint8Array(8)); let x = 0n;
  for (const by of b) x = (x << 8n) | BigInt(by);
  return (x % alghash.P).toString();
}
// STABLE per-wallet shielded spend key, derived from the seed -> recoverable from the recovery phrase, and
// reusable as a receive address (the on-chain commitments hide it, like a reusable Zcash address).
function shieldNsk() { ensureShielded(); return BigInt("0x" + blake2bHash(["nado.shield.nsk", state.wallet.privateKey])) % alghash.P; }
function shieldOwner() { return alghash.ownerOf(shieldNsk()); }
function shieldAddr() { return "znado" + shieldOwner().toString(36); }
function _b36(s) { let x = 0n; for (const c of s.toLowerCase()) { const d = "0123456789abcdefghijklmnopqrstuvwxyz".indexOf(c); if (d < 0) throw new Error("bad shielded address"); x = x * 36n + BigInt(d); } return x; }
function parseShieldAddr(a) {
  a = String(a || "").trim();
  if (!a.startsWith("znado")) throw new Error("not a znado… shielded address");
  return _b36(a.slice(5));   // -> the recipient's owner id (a field element)
}

// Shielded receive: amount-aware payment-link QR + link text (mirrors renderReceiveQR; the raw znado…
// address stays visible below for wallets that want the bare address).
function renderZaddrQR() {
  if (!state.wallet) return;
  ensureShielded();
  const za = shieldAddr();
  if ($("zaddr")) $("zaddr").textContent = za;
  const link = payLink(za, currentZrecvAmount());
  if ($("zpayLink")) $("zpayLink").textContent = link;
  _drawQR($("zaddrQR"), $("zaddrQRNote"), link, 260);
}

async function renderShield() {
  if (!state.wallet) return;
  ensureShielded();
  renderZaddrQR();   // your reusable shielded receive address as a payment-link QR
  const notes = loadNotes();
  const bal = notes.filter((n) => !n.spent).reduce((s, n) => s + BigInt(n.value), 0n);
  $("shieldBal").textContent = rawToNado(bal) + " NADO";
  try {
    const p = await (await fetch(execBase() + "/exec/field_shielded", { cache: "no-store" })).json();
    $("shieldPool").textContent = i18("shield.poolInfo", "{n} banknotes · root {r}", { n: p.notes, r: (p.root || "").slice(0, 10) + "…" });
  } catch (e) { $("shieldPool").textContent = "—"; }
  claimUnshields(true).catch(() => {});    // seamless: sweep any settled withdrawals into the balance automatically
  const box = $("shieldNotes"); box.innerHTML = "";
  const mine = notes.filter((n) => !n.spent);
  if (!mine.length) { box.innerHTML = '<div class="faint small">' + i18("shield.none", "No shielded banknotes yet.") + "</div>"; return; }
  for (const n of mine) {
    const row = document.createElement("div"); row.className = "ex-row";
    const l = document.createElement("div"); l.innerHTML = "<b>" + rawToNado(BigInt(n.value)) + " NADO</b>";
    const r = document.createElement("div"); r.className = "faint small mono"; r.textContent = "cm " + String(n.cm).slice(0, 12) + "…";
    row.appendChild(l); row.appendChild(r); box.appendChild(row);
  }
}

async function doShield() {
  if (!state.wallet) return;
  ensureShielded();
  const rawAmount = nadoToRaw($("shieldAmount").value || "0");
  if (rawAmount <= 0n) { log("err", i18("shield.badAmount", "Enter an amount to shield.")); return; }
  const rho = _randField();
  const owner = shieldOwner();                               // this wallet's stable shielded owner
  const cm = alghash.commit(rawAmount, owner, BigInt(rho));  // field-native note commitment
  try {
    const latest = await getLatestBlock(); const target = latest.block_number + 8;
    // C-2: send (owner, rho) so the exec node BINDS the note value to the escrowed amount by recomputing
    // commit(amount, owner, rho) itself. `cm` is kept for local reference only; the node does not trust it.
    const data = { field: true, owner: owner.toString(), rho: rho.toString(), cm: cm.toString() };
    const tx = buildTransferTx(state.wallet, "shield", rawAmount, MIN_TX_FEE, target, data, nowSeconds());
    const res = await submitTransaction(tx);
    if (res.data && res.data.result) {
      const notes = loadNotes();
      notes.push({ value: rawAmount.toString(), rho, cm: cm.toString(), spent: false, ts: Date.now() });
      saveNotes(notes);
      log("ok", i18("shield.done", "Shielded {a} NADO ✓ (the banknote appears once the exec node applies it)", { a: rawToNado(rawAmount) }));
      $("shieldAmount").value = "";
      setTimeout(() => renderShield().catch(() => {}), 1500);
    } else log("err", i18("shield.rej", "Shield rejected: {m}", { m: (res.data && res.data.message) || "" }));
  } catch (e) { log("err", i18("shield.err", "Shielded-pool error: {m}", { m: e.message })); }
}

async function doUnshield() {
  if (!state.wallet) return;
  ensureShielded();
  const rawAmount = nadoToRaw($("unshieldAmount").value || "0");
  const to = $("unshieldTo").value.trim() || state.wallet.address;
  if (rawAmount <= 0n) { log("err", i18("shield.badAmount", "Enter an amount to unshield.")); return; }
  if (!/^ndo[0-9a-f]{46}$/i.test(to)) { log("err", i18("shield.badAddr", "Enter a valid ndo… address.")); return; }
  const notes = loadNotes();
  const note = notes.find((n) => !n.spent && BigInt(n.value) >= rawAmount);
  if (!note) { log("err", i18("shield.noNote", "No single banknote covers that amount yet (splitting across banknotes isn't supported here).")); return; }
  const _ub = $("btnUnshield");
  if (_ub) { _ub.disabled = true; _ub.textContent = i18("shield.provingBtn", "🔐 Proving…"); }
  try {
    const change = BigInt(note.value) - rawAmount;
    const r1 = _randField(), r2 = _randField();
    const owner = shieldOwner();                             // change comes back to this wallet
    $("shieldStatus").innerHTML = '<span class="spin">◐</span> ' + i18("shield.proving", "Generating your zero-knowledge proof… (~15s, one-time per withdrawal)");
    // withdrawal = a 2-output join-split with a public exit: out1 = change (back to me), out2 = empty note,
    // public_value = -amount (the coins leaving the pool). Uses the SAME on-device prover as a shielded send.
    const wit = {
      cm: note.cm, nsk: shieldNsk().toString(), value_in: note.value, rho_in: note.rho,
      v1: change.toString(), o1: owner.toString(), r1,
      v2: "0", o2: owner.toString(), r2,
      public_value: (-rawAmount).toString(), fee: "0", withdraw_addr: to,
    };
    const pr = await proveTransfer2(wit);
    if (pr.error || !pr.ok) {
      log("err", i18("shield.proveErr", "Proof failed: {m}", { m: pr.error || pr.applied || "" }));
      $("shieldStatus").textContent = ""; return;
    }
    // The proof (on-device or delegated) was applied; the withdrawal settles on L1 via the bonded-quorum root.
    // Nothing else to submit — just track the change note + auto-claim.
    note.spent = true;
    if (change > 0n) notes.push({ value: change.toString(), rho: r1, cm: pr.cm_out1, spent: false, ts: Date.now() });
    saveNotes(notes);
    log("ok", i18("shield.unshieldSent", "Unshield proved ✓ — {a} NADO will arrive once the exec root settles.", { a: rawToNado(rawAmount) }));
    $("shieldStatus").textContent = i18("shield.pending", "Pending: {a} NADO → {t} (settling…).", { a: rawToNado(rawAmount), t: to.slice(0, 12) + "…" });
    $("unshieldAmount").value = "";
    setTimeout(() => { renderShield().catch(() => {}); claimUnshields().catch(() => {}); }, 2000);
  } catch (e) { log("err", i18("shield.err", "Shielded-pool error: {m}", { m: e.message })); $("shieldStatus").textContent = ""; }
  finally { if (_ub) { _ub.disabled = false; _ub.textContent = i18("shield.unshield", "Unshield"); } }
}

// (The 1-output on-device path was dead code and had the same silent-fallback key-leak as proveTransfer2 did;
// removed. All shielded sends/withdrawals go through proveTransfer2, which fails closed when on-device is on.)
function _b36enc(x) { x = BigInt(x); if (x === 0n) return "0"; const D = "0123456789abcdefghijklmnopqrstuvwxyz"; let s = ""; while (x > 0n) { s = D[Number(x % 36n)] + s; x /= 36n; } return s; }

// ON-DEVICE 2-output prover: build the Merkle path from the pool + prove entirely in the browser, so the node
// never sees the witness. Returns the same shape as the delegated /exec/prove_transfer2. (~20-30s at depth 12.)
let _starkInit = false;
async function ensureFastStarkHash() {
  // route the prover's Merkle/transcript hashing through the WASM BLAKE2b (~50x faster; identical output).
  if (_starkInit) return;
  try {
    const h = await initBlake2bWasm();
    initStarkHashing((data, size = 32) => (size === 32 ? bytesToHex(h(canonicalBytes(data))) : blake2bHash(data, size)));
    setMerkleWasm(await initMerkleWasm());   // whole-tree Merkle in wasm
  } catch (e) {
    initStarkHashing(blake2bHash);   // wasm unavailable -> pure-JS fallback
  }
  try { setFieldWasm(await initGoldilocksWasm()); } catch (e) { /* NTT stays pure-JS BigInt */ }
  _starkInit = true;
}
// DA-only submission (alphanet — no legacy single-operator path): publish the ~1-4MB proof to the DA layer
// (too big for a 16KB blob), then submit an L1 blob carrying ONLY the proof's commitment. Every exec node
// resolves the proof by that commitment from DA and applies it in L1 ORDER — so the shielded pool is
// reconstructible by the whole bonded quorum. Throws (no fallback) if DA publish or the relay is unavailable.
async function _daSubmitFieldTransfer(bundle, execBase) {
  const pr = await fetch(execBase + "/da/publish", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(bundle) });
  if (!pr.ok) throw new Error("DA publish failed (HTTP " + pr.status + ")");
  const commitment = (await pr.json()).commitment;
  if (!commitment) throw new Error("DA publish returned no commitment");
  if (!state.wallet) throw new Error("no wallet loaded");
  const latest = await getLatestBlock();
  if (!latest) throw new Error("relay unavailable");
  const tx = buildBlobTx(state.wallet, { op: "field_transfer", proof_da: commitment },
    latest.block_number + 8, MIN_TX_FEE, nowSeconds());
  const res = await submitTransaction(tx);
  return { ok: !!(res.data && res.data.result), da: true, commitment, txid: tx.txid,
           message: res.data && res.data.message };
}

async function _onDeviceProve2(wit, execBase) {
  await ensureFastStarkHash();
  ensureShielded();
  const leaves = (await (await fetch(execBase + "/exec/field_leaves", { cache: "no-store" })).json()).leaves || [];
  const cm = BigInt(wit.cm);
  const idx = leaves.findIndex((l) => BigInt(l) === cm);
  if (idx < 0) throw new Error("note not in the pool yet");
  const { sibs, dirs } = treePath(leaves, idx);
  const J = sjoinsplit2;
  const bt = J.buildTrace(BigInt(wit.nsk), BigInt(wit.value_in), BigInt(wit.rho_in), sibs, dirs,
    BigInt(wit.v1), BigInt(wit.o1), BigInt(wit.r1), BigInt(wit.v2), BigInt(wit.o2), BigInt(wit.r2));
  const total = J.bounds(bt.D)[2];
  const consPub = sfield.sub(BigInt(wit.fee), BigInt(wit.public_value));
  const bnd = [[0, J.S0, alghash.DOM_OWNER], [0, J.S1, alghash.ivVal()], [0, J.AB, alghash.DOM_OWNER], [0, J.CONS, consPub],
    [total, J.ROOTREG, bt.root], [total, J.NFREG, bt.nf], [total, J.CMOUT1, bt.cm1], [total, J.S0, bt.cm2]];
  // sstark.NUM_QUERIES is the protocol FRI query count (execnode/stark/fri.py NUM_QUERIES). The node's
  // verifier REQUIRES exactly this many + the grinding PoW (C-1), so an on-device proof must produce them or
  // it is rejected. The last arg binds the unshield withdraw_addr into the proof (H-4) so the exit can't be
  // redirected; null for a transfer.
  const proof = sstark.prove(bt.tr, J.transitions(), bnd, J.periodic(bt.T, bt.D), J.MAX_DEGREE, sstark.NUM_QUERIES, wit.withdraw_addr || null);
  proof.D = bt.D;
  const ser = (x) => typeof x === "bigint" ? x.toString() : Array.isArray(x) ? x.map(ser) : (x && typeof x === "object" ? Object.fromEntries(Object.entries(x).map(([k, v]) => [k, ser(v)])) : x);
  const bundle = { stark: { joinsplit2: { proof: ser(proof), root: bt.root.toString(), nf: bt.nf.toString(),
    cm_out1: bt.cm1.toString(), cm_out2: bt.cm2.toString(), public_value: wit.public_value, fee: wit.fee } } };
  if (wit.withdraw_addr) bundle.withdraw_addr = wit.withdraw_addr;
  // DA-backed path (falls back to legacy POST-apply on nodes without /da/publish)
  const res = await _daSubmitFieldTransfer(bundle, execBase);
  return { ok: res.ok, applied: res.applied, da: res.da, commitment: res.commitment,
           cm_out1: bt.cm1.toString(), cm_out2: bt.cm2.toString() };
}
if (typeof window !== "undefined") window.nadoProve2 = _onDeviceProve2;

async function proveTransfer2(wit) {   // 2-output proof (send + change) — ALWAYS generated on THIS device
  // The shielded spend key (nsk) and the amounts live in `wit`. The delegated "let the node prove it" option
  // has been removed entirely: it necessarily handed the spend key to the exec node, and even a fail-closed
  // fallback (H-6) is a footgun. Proving is now on-device only — the node never receives the witness, it only
  // verifies + applies the finished proof. If WebAssembly is unavailable the proof simply can't be made here.
  if (!window.nadoProve2) throw new Error(i18("shield.ondeviceUnavail", "Private proving needs WebAssembly — open this in a modern browser to send or withdraw shielded."));
  return await window.nadoProve2(wit, execBase());
}

// SHIELDED TRANSFER — a private note→note payment INSIDE the pool (public_value=0, no on-chain amount). Sends
// any amount and keeps the change (1-in/2-out); the recipient reconstructs their note from a claim code.
async function doSendShielded() {
  if (!state.wallet) return; ensureShielded();
  let recipientOwner;
  try { recipientOwner = parseShieldAddr($("zsendTo").value); }
  catch (e) { log("err", i18("shield.badZaddr", "Enter a valid znado… shielded address.")); return; }
  const rawAmount = nadoToRaw($("zsendAmount").value || "0");
  if (rawAmount <= 0n) { log("err", i18("shield.badAmount", "Enter an amount to send.")); return; }
  const notes = loadNotes();
  const note = notes.find((n) => !n.spent && BigInt(n.value) >= rawAmount);
  if (!note) { log("err", i18("shield.noNote", "No single shielded banknote covers {a} NADO — shield more first.", { a: rawToNado(rawAmount) })); return; }
  const _sb = $("btnZsend"); if (_sb) { _sb.disabled = true; _sb.textContent = i18("shield.provingBtn", "🔐 Proving…"); }
  try {
    const change = BigInt(note.value) - rawAmount;
    const r1 = _randField(), r2 = _randField();          // recipient-note rho, change-note rho
    $("shieldStatus").innerHTML = '<span class="spin">◐</span> ' + i18("shield.proving", "Generating your zero-knowledge proof…");
    const wit = {
      cm: note.cm, nsk: shieldNsk().toString(), value_in: note.value, rho_in: note.rho,
      v1: rawAmount.toString(), o1: recipientOwner.toString(), r1,
      v2: change.toString(), o2: shieldOwner().toString(), r2,
      public_value: "0", fee: "0",
    };
    const pr = await proveTransfer2(wit);
    if (pr.error || !pr.ok) { log("err", i18("shield.proveErr", "Proof failed: {m}", { m: pr.error || pr.applied || "" })); $("shieldStatus").textContent = ""; return; }
    note.spent = true;
    if (change > 0n) notes.push({ value: change.toString(), rho: r2, cm: pr.cm_out2, spent: false, ts: Date.now() });
    saveNotes(notes);
    // the recipient reconstructs their note from (amount, r1) + THEIR key -> a claim code to deliver to them
    const code = "znote" + _b36enc(rawAmount) + "." + _b36enc(r1);
    $("zsendCode").textContent = code;
    if ($("zsendLink")) $("zsendLink").textContent = claimLink(code);
    show("zsendCodeBox", true);
    _drawQR($("zsendCodeQR"), null, claimLink(code), 260);  // scanning opens the wallet and banks the banknote
    $("shieldStatus").textContent = "";
    log("ok", i18("shield.sent", "Sent {a} NADO privately ✓ — give the recipient the claim link below.", { a: rawToNado(rawAmount) }));
    setTimeout(() => renderShield().catch(() => {}), 1500);
  } catch (e) { log("err", i18("shield.err", "Shielded-pool error: {m}", { m: e.message })); $("shieldStatus").textContent = ""; }
  finally { if (_sb) { _sb.disabled = false; _sb.textContent = i18("shield.zsend", "Send shielded"); } }
}

async function doReceiveShielded() {
  if (!state.wallet) return; ensureShielded();
  const code = String($("zrecvCode").value || "").trim();
  if (!code.startsWith("znote") || code.indexOf(".") < 0) { log("err", i18("shield.badCode", "Paste a znote… claim code.")); return; }
  try {
    const [vB, rB] = code.slice(5).split(".");
    const value = _b36(vB), rho = _b36(rB);
    const cm = alghash.commit(value, shieldOwner(), rho);      // reconstruct the note with YOUR key
    const info = await (await fetch(execBase() + "/exec/field_shielded?cm=" + cm.toString(), { cache: "no-store" })).json();
    if (info.pos === null || info.pos === undefined) { log("err", i18("shield.noteNotFound", "That banknote isn't in the pool yet — ask the sender to confirm it settled, then retry.")); return; }
    const notes = loadNotes();
    if (notes.some((n) => n.cm === cm.toString())) { log("info", i18("shield.already", "You already have that banknote.")); return; }
    notes.push({ value: value.toString(), rho: rho.toString(), cm: cm.toString(), spent: false, ts: Date.now() });
    saveNotes(notes);
    $("zrecvCode").value = "";
    log("ok", i18("shield.received", "Received {a} NADO privately ✓", { a: rawToNado(BigInt(value)) }));
    renderShield().catch(() => {});
  } catch (e) { log("err", i18("shield.badCode", "Invalid claim code: {m}", { m: e.message })); }
}

async function claimUnshields(silent) {
  if (!state.wallet) return;
  try {
    const r = await (await fetch(execBase() + "/exec/unshields?addr=" + encodeURIComponent(state.wallet.address), { cache: "no-store" })).json();
    const pending = r.unshields || [];
    if (!pending.length) { if (!silent) $("shieldStatus").textContent = i18("shield.noClaims", "No pending withdrawals for this address."); return; }
    let claimed = 0;
    for (const u of pending) {
      const pr = await (await fetch(execBase() + "/exec/unshield_proof?nonce=" + encodeURIComponent(u.nonce), { cache: "no-store" })).json();
      if (pr.error || !pr.proof) continue;
      const latest = await getLatestBlock(); const target = latest.block_number + 8;
      const data = { addr: pr.addr, amount: pr.amount, nonce: pr.nonce, proof: pr.proof };
      const tx = buildTransferTx(state.wallet, "unshield", 0n, 0n, target, data, nowSeconds());
      const res = await submitTransaction(tx);
      if (res.data && res.data.result) claimed++;
    }
    if (claimed) $("shieldStatus").textContent = i18("shield.claimed", "Received {n} withdrawal(s) ✓ — coins are in your balance.", { n: claimed });
    else if (!silent) $("shieldStatus").textContent = i18("shield.notSettled", "Still settling on L1 — it'll arrive automatically in a few minutes.");
    setTimeout(() => { refreshBalance().catch(() => {}); renderShield().catch(() => {}); }, 1800);
  } catch (e) { log("err", i18("shield.err", "Shielded-pool error: {m}", { m: e.message })); }
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
  $("btnImport").onclick = async () => {
    try {
      const raw = $("importKey").value.trim();
      // accept EITHER a 64-hex seed OR a 24-word recovery phrase
      const priv = looksLikeMnemonic(raw) ? _hex(await mnemonicToSeed(raw)) : raw;
      adoptWallet(keypairFromPriv(priv), { needsSavePrompt: false });
    } catch (e) { uiAlert(i18("import.pasteFailed", "Import failed:") + " " + e.message); }
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
    const ed = e.target.closest && e.target.closest("a.ab-edit[data-abaddr]");
    if (ed) { e.preventDefault(); const cur = (addrBookLoad().find((x) => x.addr === ed.dataset.abaddr) || {}).label || "";
      uiPrompt({ title: i18("ab.rename", "Rename contact:"), value: cur, placeholder: "nickname" }).then((v) => { if (v !== null) addrBookSetLabel(ed.dataset.abaddr, v); }); }
    const dl2 = e.target.closest && e.target.closest("a.ab-del[data-abaddr]");
    if (dl2) { e.preventDefault(); addrBookRemove(dl2.dataset.abaddr); }
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
  if ($("btnShield")) $("btnShield").onclick = () => doShield();
  if ($("btnUnshield")) $("btnUnshield").onclick = () => doUnshield();
  if ($("btnClaimUnshield")) $("btnClaimUnshield").onclick = () => claimUnshields();
  if ($("btnZsend")) $("btnZsend").onclick = () => doSendShielded();
  if ($("btnZrecv")) $("btnZrecv").onclick = () => doReceiveShielded();
  if ($("btnZaddrShare")) $("btnZaddrShare").onclick = () => shareZpayLink();
  if ($("zrecvAmount")) $("zrecvAmount").oninput = () => renderZaddrQR();   // live-update the shielded QR + payment link
  if ($("btnZcodeShare")) $("btnZcodeShare").onclick = () => shareZcodeLink();
  $("btnDlKeySettings").onclick = downloadKeyFile;
  if ($("btnCollectDiv")) $("btnCollectDiv").onclick = () => collectDividend();
  if ($("btnMsigDerive")) $("btnMsigDerive").onclick = () => msigDerive();
  if ($("btnMsigPropose")) $("btnMsigPropose").onclick = () => msigPropose();
  if ($("btnMsigSign")) $("btnMsigSign").onclick = () => msigSign();
  if ($("btnMsigSubmit")) $("btnMsigSubmit").onclick = () => msigSubmit();
  if ($("btnMsigCopyBlob")) $("btnMsigCopyBlob").onclick = async () => {
    try { await navigator.clipboard.writeText($("msigBlob").value); setMsg("msigMsg", i18("msig.copied", "Proposal copied — send it to a co-signer."), "ok"); }
    catch (e) { $("msigBlob").select(); document.execCommand && document.execCommand("copy"); }
  };
  if ($("msigBlob")) $("msigBlob").addEventListener("input", () => msigRefreshStatus());
  if ($("btnImportFile")) $("btnImportFile").onclick = () => $("importFile").click();
  if ($("importFile")) $("importFile").onchange = (e) => {
    importKeyFile(e.target.files && e.target.files[0]);
    e.target.value = "";                               // allow re-selecting the same file later
  };

  document.querySelectorAll("#tabbar .tab").forEach((b) => { b.onclick = () => { showTab(b.dataset.tabbtn); b.blur(); }; });

  $("btnSend").onclick = () => doSend();
  if ($("btnSaveContact")) $("btnSaveContact").onclick = () => saveCurrentContact();
  $("sendTo").oninput = validateSendTo;
  $("btnBond").onclick = () => doBond("bond");
  $("btnUnbond").onclick = () => doBond("unbond");
  if ($("btnApy")) $("btnApy").onclick = () => estimateSavingsApy();
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

  // --- wallet encryption + auto-lock wiring ---
  const _btn = (id, fn) => { if ($(id)) $(id).onclick = fn; };
  _btn("btnEncrypt", async () => {
    if (!state.wallet) return;
    const pw = await uiPrompt({ title: i18("sec.setPass", "Set a wallet password (min 8 characters):"), password: true, newPassword: true });
    if (pw == null) return;
    if (pw.length < 8) { uiAlert(i18("sec.tooShort", "Password must be at least 8 characters.")); return; }
    if (await uiPrompt({ title: i18("sec.confirmPass", "Confirm the password:"), password: true, newPassword: true }) !== pw) { uiAlert(i18("sec.mismatch", "Passwords don't match.")); return; }
    try { await enableEncryption(pw); log("ok", i18("sec.encrypted", "Wallet encrypted ✓")); renderSecurity(); }
    catch (e) { log("err", i18("sec.encErr", "Encryption failed: {m}", { m: e.message })); }
  });
  _btn("btnRemoveEnc", async () => {
    const pw = await uiPrompt({ title: i18("sec.enterPass", "Enter your wallet password:"), password: true });
    if (pw == null) return;
    try { await disableEncryption(pw); log("ok", i18("sec.removed", "Password removed — key stored in plain text.")); renderSecurity(); }
    catch (e) { uiAlert(i18("sec.wrongPass", "Wrong password.")); }
  });
  _btn("btnLockNow", () => lockWallet());
  _btn("btnDlEnc", () => downloadEncryptedWallet());
  if ($("autolockSel")) $("autolockSel").onchange = (e) => {
    try { localStorage.setItem(LS_AUTOLOCK, String(parseInt(e.target.value, 10) || 0)); } catch (x) {}
    armAutolock();
  };
  _btn("btnUnlock", async () => {
    const pw = $("unlockPass").value;
    try { await unlockWallet(pw); } catch (e) { $("unlockErr").textContent = i18("unlock.wrong", "Wrong password — try again."); }
  });
  if ($("unlockPass")) $("unlockPass").onkeydown = (e) => { if (e.key === "Enter") $("btnUnlock").click(); };
  _btn("btnUnlockSaveRelay", () => {
    const v = (($("unlockRelayUrl") || {}).value || "").trim();
    state.relay = v || null;
    if (v) localStorage.setItem(LS_RELAY, v); else localStorage.removeItem(LS_RELAY);
    if ($("relayUrl")) $("relayUrl").value = v;              // keep the Settings-tab field in sync
    log("info", i18("log.relaySet", "Relay set to {u}", { u: relayBase() }));
    refreshUnlockLease();                                    // retry the "still mining" banner with the new relay
  });
  _btn("btnUnlockRemove", async () => {
    const pw = $("unlockPass").value;
    if (!(await uiConfirm(i18("unlock.removeConfirm", "Remove the password and store the key UNENCRYPTED on this device?")))) return;
    try { await unlockRemovePassword(pw); log("ok", i18("sec.removed", "Password removed — key stored in plain text.")); }
    catch (e) { $("unlockErr").textContent = i18("unlock.wrong", "Wrong password — try again."); }
  });
  _btn("btnUnlockRestore", () => { state.locked = false; show("unlockCard", false); enterOnboarding(); if ($("btnShowImport")) show("importBox", true); });

  // reset the auto-lock countdown on any interaction
  ["click", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, bumpAutolock, { passive: true }));
  $("btnClearLog").onclick = () => { $("log").innerHTML = ""; };
  $("btnForget").onclick = async () => {
    const okForget = await uiConfirm({
      title: i18("dlg.forgetTitle", "Forget this wallet?"),
      body: i18("dlg.forgetBody", "Make sure you've saved the private key first — this can't be undone."),
      confirmText: i18("dlg.forget", "Forget wallet"), danger: true,
    });
    if (!okForget) return;
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
  // EARLY LOCK GATE: if the stored wallet is encrypted, show the unlock screen on the FIRST paint — before the
  // async dependency load below (~1s). Otherwise the default-visible Settings card + the reward flash for a
  // second and then get replaced by the unlock prompt. (boot() re-affirms this after deps load; idempotent.)
  { const w0 = loadWallet(); if (w0 && w0.enc) { state.locked = true; showUnlock(); } }

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
  if (w && w.enc) {
    state.locked = true;
    showUnlock();                     // encrypted at rest — require the password before anything
  } else if (w && w.address) {
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
  try { consumeClaimRequest(); } catch (e) { log("err", "Claim-link error: " + e.message); }

  // initial connectivity + dashboard (startMining already kicks a poll when we auto-resumed)
  if (!resumedMining) pollOnce().catch(() => setConn(false));
  initNetTag().catch(() => {});
}

/* Network tag (header, upper right): which chain THIS wallet build signs for (CHAIN_ID). One
 * startup /status fetch cross-checks the relay's chain_id — a mismatched relay would reject every
 * tx with "Wrong or missing chain id", so surface the mismatch loudly instead of failing quietly. */
async function initNetTag() {
  const el = $("netTag");
  if (!el) return;
  el.textContent = CHAIN_ID;
  el.title = i18("net.tagTip", "The network this wallet signs for.");
  try {
    const st = (await rpcJSON("/status")).data;
    if (st && st.chain_id && st.chain_id !== CHAIN_ID) {
      el.textContent = CHAIN_ID + " ≠ " + st.chain_id;
      el.classList.add("mismatch");
      el.title = i18("net.mismatch", "The relay node runs a different chain — transactions will be rejected. Change the relay in Settings.");
    }
  } catch (e) {}
}

boot();

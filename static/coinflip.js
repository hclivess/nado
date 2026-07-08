// coinflip.js — NADO Coin Flip dApp. Fair 2-player commit-reveal against the on-chain COIN_FLIP contract.
// LOGIN + SIGNING are delegated to the NADO wallet (get.nadochain.com) via the SSO-style redirect: you sign
// in once (the wallet returns your address, no tx), then each move (commit/reveal) bounces to the wallet to
// sign & submit, and back. The key never touches this origin; coinflip only holds the game secret.
import { loadCrypto, blake2bHash } from "./nadotx.js";

const CID = "d5f4e0b00fa21a77dff33f70437a032a";   // canonical COIN_FLIP (nonce "coinflip-v1")
const NS = "default";
const WALLET = "https://get.nadochain.com";
const base = () => location.origin.replace(/\/+$/, "");
const $ = (id) => document.getElementById(id);

const LS_ME = "nado_coinflip_me", LS_G = "nado_coinflip_games", LS_P = "nado_coinflip_pending";
const gamesLoad = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const gamesSave = (g) => { try { localStorage.setItem(LS_G, JSON.stringify(g)); } catch {} };
let me = localStorage.getItem(LS_ME) || null;
let active = null, lastStatus = null;

const randInt = () => globalThis.crypto.getRandomValues(new Uint32Array(1))[0] % 1000000000;
const commitHashOf = (secret) => BigInt("0x" + blake2bHash(secret));   // == VM HASH(secret), cross-checked

// ---- delegated wallet signing (redirect) ---------------------------------------------------------
function walletRedirect(callObj, pend) {
  const payload = btoa(unescape(encodeURIComponent(JSON.stringify(callObj))));
  localStorage.setItem(LS_P, JSON.stringify(pend || {}));
  location.href = WALLET + "/?exec_sign=" + encodeURIComponent(payload) + "&ret=" + encodeURIComponent(base() + "/") + "&app=" + encodeURIComponent("Coin Flip");
}
function signIn() { walletRedirect({ connect: true, label: "sign in" }, { phase: "connect" }); }
function signCall(method, args, label, gameId, phase) {
  const enc = args.map((a) => typeof a === "bigint" ? { $big: a.toString() } : a);
  walletRedirect({ cid: CID, method, args: enc, ns: NS, label }, { gameId, phase, method });
}

// on load: did the wallet bounce us back?
function handleReturn() {
  const p = new URLSearchParams(location.search);
  if (!p.has("ok")) return;
  const ok = p.get("ok") === "1", addr = p.get("addr"), err = p.get("err") ? decodeURIComponent(p.get("err")) : "";
  let pend = null; try { pend = JSON.parse(localStorage.getItem(LS_P) || "null"); } catch {}
  localStorage.removeItem(LS_P);
  try { history.replaceState(null, "", location.pathname); } catch {}
  if (ok && addr) { me = addr; localStorage.setItem(LS_ME, addr); }
  if (!pend) return;
  if (pend.phase === "connect") { $("status").textContent = ok ? "Signed in." : "Sign-in cancelled."; return; }
  active = pend.gameId;
  const g = gamesLoad();
  if (ok && g[pend.gameId]) {
    // move SUBMITTED (in the mempool) — mark pending until the exec node reflects it on-chain
    if (pend.phase === "commit") g[pend.gameId].commit = "pending";
    if (pend.phase === "reveal") g[pend.gameId].reveal = "pending";
    gamesSave(g);
    $("status").textContent = (pend.phase === "commit" ? "Commit" : "Reveal") + " submitted — confirming on-chain…";
  } else {
    $("status").textContent = (pend.phase === "commit" ? "Commit" : "Reveal") + " rejected" + (err ? ": " + err : ".");
  }
}

// ---- contract reads ------------------------------------------------------------------------------
async function viewFlip(gameId) {
  try {
    const u = base() + "/exec/view?ns=" + NS + "&cid=" + CID + "&method=flip&args=" + encodeURIComponent(JSON.stringify([gameId]));
    return (await (await fetch(u, { cache: "no-store" })).json()).result;
  } catch { return null; }
}
async function gameStatus(gameId) {
  try {
    const c = await (await fetch(base() + "/exec/contract?ns=" + NS + "&cid=" + CID, { cache: "no-store" })).json();
    const s = c.storage || {}, key = String(gameId) + "|" + (me || "");
    return { ncom: (s.ncom || {})[String(gameId)] || 0, nrev: (s.nrev || {})[String(gameId)] || 0,
             iCommitted: !!(s.commit || {})[key], iRevealed: !!(s.done || {})[key] };
  } catch { return null; }
}

// ---- game flow -----------------------------------------------------------------------------------
function startGame(gameId, role) {
  if (!me) { $("status").textContent = "Sign in first."; return; }
  const g = gamesLoad(), secret = g[gameId] ? g[gameId].secret : randInt();
  g[gameId] = { secret, role, ts: Date.now(), commit: (g[gameId] || {}).commit, reveal: (g[gameId] || {}).reveal }; gamesSave(g);
  active = gameId; render();
  $("status").textContent = "Opening your wallet to commit…";
  signCall("commit", [gameId, commitHashOf(secret)], "commit to game #" + gameId, gameId, "commit");
}
function reveal() {
  const g = gamesLoad()[active];
  if (!g) { $("status").textContent = "No secret for this game on this device — reveal from where you committed."; return; }
  $("status").textContent = "Opening your wallet to reveal…";
  signCall("reveal", [active, g.secret], "reveal game #" + active, active, "reveal");
}
async function refreshActive() {
  if (active == null) return;
  const st = await gameStatus(active); lastStatus = st;
  // once the exec node reflects my move, flip the local "pending" -> "confirmed"
  if (st) {
    const g = gamesLoad(); let ch = false;
    if (g[active]) {
      if (st.iCommitted && g[active].commit !== "confirmed") { g[active].commit = "confirmed"; ch = true; }
      if (st.iRevealed && g[active].reveal !== "confirmed") { g[active].reveal = "confirmed"; ch = true; }
    }
    if (ch) gamesSave(g);
  }
  renderActive(st, st && st.nrev >= 2 ? await viewFlip(active) : null);
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = () => signIn();
  $("btnNew").onclick = () => startGame(randInt(), "new");
  $("btnJoin").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) startGame(id, "join"); };
  $("btnReveal").onclick = () => reveal();
}
function badge(state) {
  if (state === "confirmed") return '<span class="b ok">confirmed ✓</span>';
  if (state === "pending") return '<span class="b pend">pending…</span>';
  return '<span class="b dimb">—</span>';
}
function render() {
  const signedIn = !!me;
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? (me.slice(0, 16) + "…") : "not signed in";
  $("play").classList.toggle("hidden", !signedIn);
  const g = gamesLoad(), ids = Object.keys(g).sort((a, b) => g[b].ts - g[a].ts).slice(0, 8);
  $("recent").innerHTML = ids.length
    ? ids.map((id) => '<button class="chip ghost" data-g="' + id + '">#' + id + " · " + (g[id].reveal === "confirmed" ? "revealed" : g[id].role) + "</button>").join(" ")
    : '<span class="dim">No games yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { active = parseInt(b.dataset.g, 10); render(); refreshActive(); });
  renderActive(lastStatus, null);
}
function renderActive(st, result) {
  const box = $("activeGame");
  if (active == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const g = gamesLoad()[active] || {};
  $("gameId").textContent = "#" + active;
  $("shareLink").value = base() + "/?game=" + active;
  $("gStatus").textContent = st ? (st.ncom + "/2 committed · " + st.nrev + "/2 revealed") : "…";
  $("myCommit").innerHTML = "Your commit: " + badge(g.commit);
  $("myReveal").innerHTML = "Your reveal: " + badge(g.reveal);
  $("btnReveal").disabled = !g.secret || g.reveal === "pending" || g.reveal === "confirmed";
  const coin = $("coin");
  if (result === 0 || result === 1) {
    coin.className = "coin " + (result === 0 ? "heads" : "tails"); coin.textContent = result === 0 ? "H" : "T";
    $("result").textContent = "Result: " + (result === 0 ? "HEADS (0)" : "TAILS (1)");
  } else { coin.className = "coin spin"; coin.textContent = "?"; $("result").textContent = st && st.nrev >= 2 ? "Computing…" : "Waiting for both reveals…"; }
}

async function boot() {
  try { await loadCrypto(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload the page."; return; }
  wireUI();
  // is the Coin Flip contract live on the exec node yet?
  try {
    const r = await fetch(base() + "/exec/contract?ns=" + NS + "&cid=" + CID, { cache: "no-store" });
    if (!r.ok) $("status").textContent = "The Coin Flip contract is deploying — the game goes live in a few minutes, then reload.";
  } catch { /* exec node unreachable — handled per-call */ }
  handleReturn();
  const q = new URLSearchParams(location.search).get("game");
  if (q) $("joinId").value = q;
  render();
  if (active != null) refreshActive();
  setInterval(refreshActive, 6000);
}
boot();

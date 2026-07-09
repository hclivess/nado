// roulette.js — NADO Roulette: a provably-fair, PEER-BANKED European (single-zero) roulette on the execution
// layer. It reuses Coin Flip's exact commit-reveal skeleton, so a game is two seats: a BANK (posts a bankroll,
// commits a secret) and a BETTOR (stakes a bet on a set of table numbers, commits a secret). One shared spin
// r = HASH(bankSecret + bettorSecret) % 37 is fair because neither secret is revealed before both are
// committed. A winning bet returns stake × 36/count (the universal roulette rule → exact 2.70% single-zero
// edge); a loss sweeps the stake into the bank. Everything is an ON-CHAIN CONTRACT (runtime stackvm, cid
// below) called via the GENERIC exec `call` op — stakes/bankrolls are escrowed as VALUE and paid by PAY; there
// is NO roulette-specific API. Login + every signature is delegated to the NADO wallet (get.nadochain.com).
import { loadCrypto, blake2bHash } from "./nadotx.js";

const NS = "default";
const WALLET = "https://get.nadochain.com";
const RAW = 10n ** 10n;                 // 1 NADO = 1e10 raw units
const PN = 37;                          // pockets 0..36
const MAXSLOTS = 18, SENTINEL = 99;     // biggest bet covers 18 numbers; pad unused slots with the sentinel
const base = () => location.origin.replace(/\/+$/, "");
const $ = (id) => document.getElementById(id);

// European wheel colours — the one set with no formula; everything else derives from it.
const RED = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
const colorOf = (n) => n === 0 ? "green" : (RED.has(n) ? "red" : "black");

// ---- QR (vendored, best-effort — same generator as the wallet / coinflip) ------------------------
let qrEncode = null;
async function loadQR() { try { const m = await import("./vendor/qrcode.js"); qrEncode = m.qrMatrix || null; } catch { qrEncode = null; } }
function drawQR(canvas, note, text, targetPx) {
  if (!qrEncode || !canvas) { if (canvas) canvas.classList.add("hidden"); if (note) note.classList.remove("hidden"); return; }
  try {
    let m; try { m = qrEncode(text, "M"); } catch { m = qrEncode(text, "L"); }
    const n = m.length, quiet = 4, dim = n + quiet * 2, px = Math.max(2, Math.floor((targetPx || 200) / dim)), size = dim * px;
    canvas.width = size; canvas.height = size; canvas.style.width = size + "px"; canvas.style.height = size + "px";
    const ctx = canvas.getContext("2d"); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size); ctx.fillStyle = "#000";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (m[r][c]) ctx.fillRect((c + quiet) * px, (r + quiet) * px, px, px);
    canvas.classList.remove("hidden"); if (note) note.classList.add("hidden");
  } catch { canvas.classList.add("hidden"); if (note) note.classList.remove("hidden"); }
}
async function shareGame() {
  if (active == null) return;
  const url = base() + "/?game=" + active;
  const stake = (lastGame && lastGame.exists) ? "for " + rawToNado(lastGame.bankroll) + " NADO " : "";
  if (navigator.share) {
    try { await navigator.share({ title: "NADO Roulette", text: "Bet against my bank " + stake + "on NADO — table #" + active + ":", url }); return; }
    catch (e) { if (e && e.name === "AbortError") return; }
  }
  const btn = $("btnShare"); let ok = false;
  try { await navigator.clipboard.writeText(url); ok = true; } catch {}
  if (btn) { btn.textContent = ok ? "Copied ✓" : "copy failed"; setTimeout(() => (btn.textContent = "Share"), 1400); }
}

const LS_ME = "nado_roulette_me", LS_G = "nado_roulette_games", LS_P = "nado_roulette_pending";
const gamesLoad = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const gamesSave = (g) => { try { localStorage.setItem(LS_G, JSON.stringify(g)); } catch {} };
let me = localStorage.getItem(LS_ME) || null;
let active = null, lastGame = null, myBalance = 0n, myL1Balance = 0n;
let selected = new Set();     // the numbers the bettor is covering right now (the table selection)
const FEE = 1000n;
let deepLinkGame = null;
const stageCache = {};        // gid -> {settled, ncom, bankroll} : drives list colours + join affordability

// ---- amounts / secrets ---------------------------------------------------------------------------
const randId = () => globalThis.crypto.getRandomValues(new Uint32Array(1))[0] % 1000000000;
const randSecret = () => { let h = "0x"; for (const b of globalThis.crypto.getRandomValues(new Uint8Array(32))) h += b.toString(16).padStart(2, "0"); return BigInt(h); };
const commitHashOf = (secret) => BigInt("0x" + blake2bHash(secret));   // 256-bit; == VM HASH(secret)
function nadoToRaw(s) {
  s = String(s || "").trim(); if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const [w, f = ""] = s.split("."); const raw = BigInt(w) * RAW + BigInt((f + "0000000000").slice(0, 10));
  return raw > 0n ? raw : null;
}
const rawToNado = (raw) => { raw = BigInt(raw); const w = raw / RAW, f = (raw % RAW).toString().padStart(10, "0").replace(/0+$/, ""); return f ? `${w}.${f}` : `${w}`; };
const encBig = (v) => typeof v === "bigint" ? { $big: v.toString() }
  : Array.isArray(v) ? v.map(encBig)
  : (v && typeof v === "object") ? Object.fromEntries(Object.keys(v).map((k) => [k, encBig(v[k])])) : v;

// ---- delegated wallet signing (redirect) ---------------------------------------------------------
function go(obj, pend) {
  const payload = btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
  localStorage.setItem(LS_P, JSON.stringify(pend || {}));
  location.href = WALLET + "/?exec_sign=" + encodeURIComponent(payload) + "&ret=" + encodeURIComponent(base() + "/") + "&app=" + encodeURIComponent("Roulette");
}
const signIn = () => go({ connect: true, label: "sign in" }, { phase: "connect" });
const deposit = (raw) => go({ deposit: { amount: raw.toString() }, label: "deposit " + rawToNado(raw) + " NADO" }, { phase: "deposit" });
const signBlob = (blob, label, pend) => go({ blob: encBig(blob), label }, pend);

// on return from the wallet
function handleReturn() {
  const p = new URLSearchParams(location.search);
  if (!p.has("ok")) return;
  const ok = p.get("ok") === "1", addr = p.get("addr"), err = p.get("err") ? decodeURIComponent(p.get("err")) : "";
  let pend = null; try { pend = JSON.parse(localStorage.getItem(LS_P) || "null"); } catch {}
  localStorage.removeItem(LS_P);
  try { history.replaceState(null, "", location.pathname); } catch {}
  if (ok && addr) { me = addr; localStorage.setItem(LS_ME, addr); }
  if (!pend) return;
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming on-chain…", bet: "Bet submitted — confirming…",
                  reveal: "Reveal submitted — confirming…", settle: "Paying out…", claim: "Claiming…", withdraw: "Withdrawal submitted." }[pend.phase] || "Submitted.";
  if (pend.gameId != null) active = pend.gameId;
  if (ok && pend.phase === "bet") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].bet = "pending"; gamesSave(g); } }
  if (ok && pend.phase === "reveal") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].reveal = "pending"; gamesSave(g); } }
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
}

// ---- reads ---------------------------------------------------------------------------------------
async function fetchBalance() {
  if (!me) { myBalance = 0n; myL1Balance = 0n; return; }
  try {
    const b = await (await fetch(base() + "/exec/bridge?ns=" + NS + "&provisional=1", { cache: "no-store" })).json();
    myBalance = BigInt((b.balances || {})[me] || 0);
  } catch { myBalance = 0n; }
  try {
    const a = await (await fetch(base() + "/get_account?address=" + encodeURIComponent(me), { cache: "no-store" })).json();
    myL1Balance = BigInt(a.balance || 0);
  } catch { myL1Balance = 0n; }
}
const CID = "186ebadb975794e2ed7eeb1c7b5115a5";   // the Roulette CONTRACT (runtime stackvm) — staked via VALUE/PAY, no native API

// generic contract call, signed by the wallet; valueRaw (raw NADO) is ESCROWED from the caller's bridge balance
function callC(method, args, valueRaw, label, pend) {
  const payload = { op: "call", contract: CID, method, args };
  if (valueRaw != null) payload.value = valueRaw;
  signBlob(payload, label, pend);
}
// spin result — MUST match the contract: HASH(s1+s2) % 37, HASH = blake2b(decimal string) as a 256-bit int
function spinResult(s1, s2) { return Number(BigInt("0x" + blake2bHash((BigInt(s1) + BigInt(s2)).toString())) % BigInt(PN)); }

// ---- reads: game / lobby / scoreboard are all DERIVED from the contract's storage maps ----------
let lastStorage = {};
async function fetchStorage() {
  try { return (await (await fetch(base() + "/exec/contract?ns=" + NS + "&cid=" + CID + "&provisional=1", { cache: "no-store" })).json()).storage || {}; }
  catch { return null; }
}
const _m = (sto, name) => sto[name] || {};
const allGids = (sto) => Object.keys(_m(sto, "nn"));
// the covered numbers of a game: cov is keyed by gid*37+n, so scan 0..36
function coveredOf(sto, gid) {
  const cov = _m(sto, "cov"), out = []; const b = Number(gid) * PN;
  for (let n = 0; n < PN; n++) if (cov[String(b + n)]) out.push(n);
  return out;
}
function gameFrom(sto, gid) {
  gid = String(gid); const nn = _m(sto, "nn")[gid] || 0;
  if (!nn) return { exists: false };
  const bank = _m(sto, "p1")[gid], bettor = _m(sto, "p2")[gid];
  const r1 = _m(sto, "r1")[gid] ? 1 : 0, r2 = _m(sto, "r2")[gid] ? 1 : 0;
  const settled = !!_m(sto, "sd")[gid];
  const g = { exists: true, bank, bettor, bankroll: _m(sto, "bk")[gid] || 0, stake: _m(sto, "st")[gid] || 0,
              count: _m(sto, "cn")[gid] || 0, settled, ncom: nn, r1, r2, deadline: _m(sto, "dl")[gid] || 0,
              covered: bettor ? coveredOf(sto, gid) : [] };
  const roStored = _m(sto, "ro")[gid] || 0;
  if (settled && roStored) { g.result = roStored - 1; g.win = _m(sto, "wn")[gid] ? 1 : 0; }
  else if (r1 && r2) { const s1 = _m(sto, "s1")[gid], s2 = _m(sto, "s2")[gid];
    if (s1 != null && s2 != null) { g.result = spinResult(s1, s2); g.win = g.covered.includes(g.result) ? 1 : 0; } }
  return g;
}
function lobbyFrom(sto) {
  return allGids(sto).map((gid) => {
    const nn = _m(sto, "nn")[gid], settled = !!_m(sto, "sd")[gid];
    return { game: gid, bankroll: _m(sto, "bk")[gid] || 0, stake: _m(sto, "st")[gid] || 0, settled, ncom: nn,
             stage: settled ? "done" : (nn >= 2 ? "live" : "open"), deadline: _m(sto, "dl")[gid] || 0 };
  }).sort((a, b) => b.deadline - a.deadline);
}
// scoreboard: net NADO across finished games, for BOTH banks and bettors (a table is zero-sum bank vs bettor)
function boardFrom(sto) {
  const stats = {};
  const bump = (a, net) => { const x = stats[a] || (stats[a] = { addr: a, wins: 0, losses: 0, games: 0, net: 0 }); x.games++; x.net += net; net >= 0 ? x.wins++ : x.losses++; };
  for (const gid of allGids(sto)) {
    if (!_m(sto, "sd")[gid]) continue;
    const bank = _m(sto, "p1")[gid], bettor = _m(sto, "p2")[gid];
    if (!bank || !bettor) continue;                       // cancelled (no bettor) — not a played game
    const stake = _m(sto, "st")[gid] || 0, cn = _m(sto, "cn")[gid] || 1, win = _m(sto, "wn")[gid] ? 1 : 0;
    const bettorNet = win ? stake * (Math.floor(36 / cn) - 1) : -stake;   // bettor gains net win, or loses stake
    bump(bettor, bettorNet); bump(bank, -bettorNet);
  }
  return Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
}
async function fetchGame(gid) { const sto = await fetchStorage(); return sto ? gameFrom(sto, gid) : null; }

const _aliasCache = {};
async function resolveAliases(addrs) {
  await Promise.all([...new Set(addrs)].filter((a) => a && !(a in _aliasCache)).map(async (a) => {
    try { const r = await (await fetch(base() + "/get_aliases_of?address=" + encodeURIComponent(a), { cache: "no-store" })).json(); _aliasCache[a] = (r.aliases && r.aliases[0]) || null; }
    catch { _aliasCache[a] = null; }
  }));
}
const disp = (addr) => !addr ? "—" : (_aliasCache[addr] ? "@" + _aliasCache[addr] : addr.slice(0, 10) + "…" + addr.slice(-4));

// ---- bet maths (universal roulette rule) ---------------------------------------------------------
const betCount = () => selected.size;
const betMult = () => { const c = betCount(); return c >= 1 && c <= MAXSLOTS ? Math.floor(36 / c) : 0; };   // total return factor
const betSlots = () => { const a = [...selected].sort((x, y) => x - y); while (a.length < MAXSLOTS) a.push(SENTINEL); return a; };

// ---- actions -------------------------------------------------------------------------------------
function doDeposit() {
  const raw = nadoToRaw($("bankAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to deposit."; return; }
  if (raw + FEE > myL1Balance) {
    $("status").textContent = "Not enough in your L1 wallet: you have " + rawToNado(myL1Balance) +
      " NADO (deposit needs " + rawToNado(raw) + " + a tiny fee). Mine or receive more first.";
    return;
  }
  deposit(raw);
}
function doWithdraw() {
  const raw = nadoToRaw($("bankAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to withdraw."; return; }
  if (myBalance < raw) { $("status").textContent = "You only have " + rawToNado(myBalance) + " NADO in the exec layer."; return; }
  signBlob({ op: "bridge_withdraw", amount: raw }, "withdraw " + rawToNado(raw) + " NADO to L1", { phase: "withdraw" });
}
// BANK a table: escrow a bankroll, commit a secret
async function openTable(gid, bankrollRaw) {
  const g = gamesLoad();
  const secretStr = (g[gid] && g[gid].secret) ? g[gid].secret : randSecret().toString();
  g[gid] = { secret: secretStr, role: "bank", ts: Date.now(), bet: (g[gid] || {}).bet, reveal: (g[gid] || {}).reveal, bankroll: bankrollRaw.toString() }; gamesSave(g);
  active = gid; render();
  callC("open", [gid, commitHashOf(BigInt(secretStr))], bankrollRaw,
        "bank table #" + gid + " · " + rawToNado(bankrollRaw) + " NADO bankroll", { gameId: gid, phase: "bet" });
}
async function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) { $("status").textContent = "Enter a bankroll (NADO) to bank a table."; return; }
  if (myBalance < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(myBalance) + " NADO."; return; }
  openTable(randId(), raw);
}
// BET at a table: escrow the stake, commit a secret, declare the covered-number set
async function joinTable(gid, stakeRaw, slots) {
  const g = gamesLoad();
  const secretStr = (g[gid] && g[gid].secret) ? g[gid].secret : randSecret().toString();
  g[gid] = { secret: secretStr, role: "bettor", ts: Date.now(), bet: (g[gid] || {}).bet, reveal: (g[gid] || {}).reveal,
             stake: stakeRaw.toString(), numbers: slots.filter((n) => n < PN) }; gamesSave(g);
  active = gid; render();
  callC("join", [gid, commitHashOf(BigInt(secretStr)), ...slots], stakeRaw,
        "bet " + rawToNado(stakeRaw) + " NADO on " + slots.filter((n) => n < PN).length + " number(s) · table #" + gid, { gameId: gid, phase: "bet" });
}
async function doJoin() {
  const gid = parseInt($("joinId").value, 10);
  if (!gid) { $("status").textContent = "Enter a table ID (or pick one from the lobby)."; return; }
  deepLinkGame = null; $("btnJoin").classList.remove("pulse");
  if (!betCount()) { $("status").textContent = "Pick at least one number on the table to bet on."; return; }
  const g = await fetchGame(gid);
  if (!g || !g.exists) { $("status").textContent = "No such table yet — ask the bank for the ID after they open it."; return; }
  if (g.settled || g.ncom >= 2) { $("status").textContent = "That table is full or already settled."; return; }
  await fetchBalance();
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  if (myBalance < stake) { $("status").textContent = "You need " + rawToNado(stake) + " NADO in your exec balance (you have " + rawToNado(myBalance) + "). Deposit first."; render(); return; }
  const need = stake * BigInt(betMult() - 1);
  if (BigInt(g.bankroll) < need) { $("status").textContent = "This table's bankroll (" + rawToNado(g.bankroll) + " NADO) can't cover a " + betMult() + "× win. Lower your stake, widen your bet, or pick a bigger table."; render(); return; }
  joinTable(gid, stake, betSlots());
}
function reveal() {
  const g = gamesLoad()[active];
  if (!g) { $("status").textContent = "No secret for this table on this device."; return; }
  const mine = (lastGame && lastGame.bank === me) ? 1 : (lastGame && lastGame.bettor === me) ? 2 : (g.role === "bank" ? 1 : 2);
  callC("reveal" + mine, [active, BigInt(g.secret)], null, "reveal your secret · table #" + active, { gameId: active, phase: "reveal" });
}
const settle = () => callC("settle", [active], null, "spin & pay out · table #" + active, { gameId: active, phase: "settle" });
const claim = () => callC("claim", [active], null, "claim (opponent stalled) · table #" + active, { gameId: active, phase: "claim" });
const cancelGame = () => callC("cancel", [active], null, "cancel table #" + active, { gameId: active, phase: "cancel" });

// deterministic rematch id (same LCG as coinflip) — both players' "Play again" land in ONE new table, roles kept
function rematchGidFor(oldGid) { return Number((BigInt(oldGid) * 6364136223846793005n + 1442695040888963407n) % 1000000000n); }
async function rematch() {
  if (!lastGame || !lastGame.exists) return;
  const rgid = rematchGidFor(active);
  if (lastGame.bank === me) {
    const bankroll = BigInt(lastGame.bankroll);
    if (myBalance < bankroll) { $("status").textContent = "Deposit more to bank again — need " + rawToNado(bankroll) + " NADO."; return; }
    openTable(rgid, bankroll);
  } else if (lastGame.bettor === me) {
    const stake = BigInt(lastGame.stake), slots = lastGame.covered.slice();
    while (slots.length < MAXSLOTS) slots.push(SENTINEL);
    const rg = await fetchGame(rgid);
    if (!rg || !rg.exists) { $("status").textContent = "Waiting for the bank to start the rematch (table #" + rgid + ")…"; active = rgid; render(); return; }
    if (myBalance < stake) { $("status").textContent = "Deposit more to play again — need " + rawToNado(stake) + " NADO."; return; }
    joinTable(rgid, stake, slots);
  }
}

async function refreshActive() {
  await fetchBalance();
  const sto = await fetchStorage();
  if (sto) {
    lastStorage = sto;
    if (active != null) lastGame = gameFrom(sto, active);
    for (const gid of allGids(sto)) stageCache[gid] = { settled: !!_m(sto, "sd")[gid], ncom: _m(sto, "nn")[gid] || 0, bankroll: _m(sto, "bk")[gid] || 0 };
    renderLobby(lobbyFrom(sto));
    renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([me].concat(lastGame ? [lastGame.bank, lastGame.bettor] : []));
  render();
}
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No finished games yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10);
  await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => {
        const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO";
        const you = r.addr === me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") +
          '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>";
      }).join("") + "</tbody></table>";
}
function renderLobby(games) {
  const el = $("lobbyList"); if (!el) return;
  const rank = { open: 0, live: 1, done: 2 }, tag = { open: "⏳", live: "▶", done: "✓" }, verb = { open: " · bet here", live: " · watch", done: "" };
  const shown = (games || []).slice().sort((a, b) => rank[a.stage] - rank[b.stage]).slice(0, 24);
  if (!shown.length) { el.innerHTML = '<span class="dim">No tables yet — bank one below.</span>'; return; }
  el.innerHTML = shown.map((g) => '<button class="chip ' + g.stage + '" data-lg="' + g.game + '">' + tag[g.stage] + " #" + g.game + " · bank " + rawToNado(g.bankroll) + " NADO" + verb[g.stage] + "</button>").join(" ");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => {
    active = parseInt(b.dataset.lg, 10); $("joinId").value = b.dataset.lg; refreshActive();
    try { $("betTable").scrollIntoView({ behavior: "smooth", block: "center" }); } catch {}
  });
}

// ---- the roulette TABLE (bettor's bet builder) ---------------------------------------------------
// quick outside bets -> the exact number set each covers
const GROUPS = {
  "1-18": range(1, 18), "19-36": range(19, 36), EVEN: evens(), ODD: odds(),
  RED: [...RED].sort((a, b) => a - b), BLACK: range(1, 36).filter((n) => !RED.has(n)),
  "1st 12": range(1, 12), "2nd 12": range(13, 24), "3rd 12": range(25, 36),
  C1: col(1), C2: col(2), C3: col(3),
};
function range(a, b) { const o = []; for (let i = a; i <= b; i++) o.push(i); return o; }
function evens() { return range(1, 36).filter((n) => n % 2 === 0); }
function odds() { return range(1, 36).filter((n) => n % 2 === 1); }
function col(c) { return range(1, 36).filter((n) => (n % 3) === (c % 3)); }   // C3 -> n%3==0
function buildTable() {
  const grid = $("tableGrid"); if (!grid || grid.dataset.built) return;
  grid.dataset.built = "1";
  // 0 cell (spans all three rows)
  let html = '<button class="cell green zero" data-n="0">0</button>';
  // numbers 1..36 laid out in the standard 3×12 grid (top row 3,6,9…; bottom row 1,4,7…)
  for (let rrow = 0; rrow < 3; rrow++) for (let ccol = 0; ccol < 12; ccol++) {
    const n = ccol * 3 + (3 - rrow);   // rrow0->+3 (top), rrow1->+2, rrow2->+1 (bottom)
    html += '<button class="cell ' + colorOf(n) + '" data-n="' + n + '" style="grid-row:' + (rrow + 1) + ';grid-column:' + (ccol + 2) + '">' + n + "</button>";
  }
  // column 2:1 buttons at the right
  for (let rrow = 0; rrow < 3; rrow++)
    html += '<button class="cell col2to1" data-grp="C' + (3 - rrow) + '" style="grid-row:' + (rrow + 1) + ';grid-column:14">2:1</button>';
  grid.innerHTML = html;
  grid.querySelectorAll("[data-n]").forEach((b) => b.onclick = () => toggleNum(parseInt(b.dataset.n, 10)));
  grid.querySelectorAll("[data-grp]").forEach((b) => b.onclick = () => selectGroup(b.dataset.grp));
  // outside-bet buttons (dozens + even-money) already in the HTML
  document.querySelectorAll("[data-grp2]").forEach((b) => b.onclick = () => selectGroup(b.dataset.grp2));
  const clr = $("btnClearBet"); if (clr) clr.onclick = () => { selected = new Set(); paintTable(); render(); };
}
function toggleNum(n) { if (selected.has(n)) selected.delete(n); else if (selected.size < MAXSLOTS) selected.add(n); paintTable(); render(); }
function selectGroup(key) { const nums = GROUPS[key] || []; selected = new Set(nums.slice(0, MAXSLOTS)); paintTable(); render(); }
function paintTable() {
  document.querySelectorAll("#tableGrid .cell[data-n]").forEach((b) => b.classList.toggle("sel", selected.has(parseInt(b.dataset.n, 10))));
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = signIn;
  $("btnDeposit").onclick = doDeposit;
  $("btnWithdraw").onclick = doWithdraw;
  $("btnNewTable").onclick = newTable;
  $("btnJoin").onclick = doJoin;
  $("joinId").oninput = () => render();
  $("stakeAmt").oninput = () => render();
  $("btnReveal").onclick = reveal;
  $("btnSettle").onclick = settle;
  $("btnClaim").onclick = claim;
  $("btnCancel").onclick = cancelGame;
  $("btnShare").onclick = shareGame;
  $("btnRematch").onclick = rematch;
  buildTable();
}
const badge = (s) => s === "confirmed" ? '<span class="b ok">confirmed ✓</span>' : s === "pending" ? '<span class="b pend">pending…</span>' : '<span class="b dimb">—</span>';
function render() {
  const signedIn = !!me;
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(me) : "not signed in";
  $("bal").textContent = rawToNado(myBalance) + " NADO";
  $("l1bal").textContent = rawToNado(myL1Balance) + " NADO";
  $("play").classList.toggle("hidden", !signedIn);
  $("bankcard").classList.toggle("hidden", !signedIn);
  $("bankroll").classList.toggle("hidden", !signedIn);
  // bet summary: count · multiplier · payout on a stake
  const c = betCount(), M = betMult();
  const stakeRaw = nadoToRaw($("stakeAmt").value);
  $("betInfo").innerHTML = c
    ? "Covering <b>" + c + "</b> number" + (c > 1 ? "s" : "") + " · pays <b>" + M + "×</b>" +
      (stakeRaw ? " · win returns <b>" + rawToNado(stakeRaw * BigInt(M)) + " NADO</b> (net +" + rawToNado(stakeRaw * BigInt(M - 1)) + ")" : "")
    : '<span class="dim">Tap numbers or a bet region on the table to build your bet.</span>';
  // Join affordability / joinability (mirrors coinflip): needs a table id, a bet, enough balance, and a bank
  // that can cover the win. Disable + explain instead of failing after the click.
  const jid = ($("joinId").value || "").trim();
  const lgv = lastGame || {};
  let iAmIn = false, stageJoinable = true, bankroll = null;
  if (jid && String(active) === jid && lgv.exists) {
    iAmIn = lgv.bank === me || lgv.bettor === me;
    stageJoinable = !lgv.settled && lgv.ncom < 2; bankroll = BigInt(lgv.bankroll);
  } else if (jid && stageCache[jid]) {
    iAmIn = !!(gamesLoad()[jid] || {}).bet;
    stageJoinable = !stageCache[jid].settled && stageCache[jid].ncom < 2; bankroll = BigInt(stageCache[jid].bankroll || 0);
  }
  const need = (stakeRaw && M) ? stakeRaw * BigInt(M - 1) : null;
  const canAffordStake = !(signedIn && stakeRaw && myBalance < stakeRaw);
  const bankCovers = !(bankroll != null && need != null && bankroll < need);
  const joinable = !!jid && !!c && !!stakeRaw && !iAmIn && stageJoinable && canAffordStake && bankCovers;
  $("btnJoin").disabled = !joinable;
  $("btnJoin").classList.toggle("pulse", joinable && signedIn);
  $("btnSignIn").classList.toggle("pulse", !!jid && !!c && stageJoinable && !signedIn);
  // inline hint explaining the current blocker (only once a table + a bet exist)
  let hint = "";
  if (jid && c && signedIn && !iAmIn && stageJoinable) {
    if (stakeRaw && myBalance < stakeRaw) hint = "Not enough NADO — your bet stakes " + rawToNado(stakeRaw) + " but your exec balance is " + rawToNado(myBalance) + ". Deposit at least " + rawToNado(stakeRaw - myBalance) + " more below.";
    else if (!bankCovers) hint = "This table's bankroll (" + rawToNado(bankroll) + " NADO) can't cover a " + M + "× win on " + rawToNado(stakeRaw) + ". Lower your stake, widen your bet, or pick a bigger table.";
  }
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  // your tables (only those that exist on-chain)
  const g = gamesLoad();
  const ids = Object.keys(g).filter((id) => stageCache[id]).sort((a, b) => g[b].ts - g[a].ts).slice(0, 8);
  $("recent").innerHTML = ids.length
    ? ids.map((id) => {
        const stg = stageCache[id]; let cls = "", tag = "";
        if (stg.settled) { cls = " done"; tag = "✓ "; } else if (stg.ncom >= 2) { cls = " live"; tag = "▶ "; } else { cls = " open"; tag = "⏳ "; }
        const role = g[id].role === "bank" ? "🏦" : "🎯";
        return '<button class="chip' + cls + '" data-g="' + id + '">' + tag + role + " #" + id + "</button>";
      }).join(" ")
    : '<span class="dim">No tables yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { active = parseInt(b.dataset.g, 10); refreshActive(); });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (active == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const lg = lastGame || {}, local = gamesLoad()[active] || {};
  const iAmBank = lg.bank === me, iAmBettor = lg.bettor === me, iAmIn = iAmBank || iAmBettor;
  const mySlot = iAmBank ? 1 : iAmBettor ? 2 : 0;
  const myRevealed = mySlot === 1 ? lg.r1 : mySlot === 2 ? lg.r2 : 0;
  $("gameId").textContent = "#" + active;
  $("shareLink").value = base() + "/?game=" + active;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?game=" + active, 200);
  $("gBankroll").textContent = lg.exists ? rawToNado(lg.bankroll) + " NADO" : (local.bankroll ? rawToNado(local.bankroll) + " NADO" : "—");
  $("gStake").textContent = lg.exists && lg.stake ? rawToNado(lg.stake) + " NADO" : (local.stake ? rawToNado(local.stake) + " NADO" : "—");
  const covered = (lg.covered && lg.covered.length) ? lg.covered : (local.numbers || []);
  $("gBet").innerHTML = covered.length
    ? covered.map((n) => '<span class="pip ' + colorOf(n) + '">' + n + "</span>").join(" ") + ' <span class="dim">· ' + (lg.count || covered.length) + " no. · " + (lg.count ? Math.floor(36 / lg.count) : "?") + "× </span>"
    : '<span class="dim">no bet yet</span>';
  $("gStatus").textContent = lg.exists ? (lg.ncom + "/2 seated · " + ((lg.r1 ? 1 : 0) + (lg.r2 ? 1 : 0)) + "/2 revealed" + (lg.settled ? " · settled" : (lg.ncom >= 2 ? " · ⚡ live" : " · waiting for a bettor"))) : "opening…";
  // seats
  const seat = (addr, role, revealed) => addr ? '<span class="chip">' + (addr === me ? "you " : "") + role + " " + disp(addr) + (revealed ? " ✓" : "") + "</span>" : "";
  let seats = seat(lg.bank, "🏦 bank", lg.r1);
  if (lg.bettor) seats += " " + seat(lg.bettor, "🎯 bettor", lg.r2);
  else if (!iAmBank && local.role === "bettor" && local.bet === "pending") seats += ' <span class="chip" style="opacity:.75">you · confirming…</span>';
  $("seats").innerHTML = seats || '<span class="dim">no players yet</span>';
  // my move badges (only when I'm in the game)
  const betC = iAmIn ? "confirmed" : (local.bet === "pending" ? "pending" : null);
  const revC = myRevealed ? "confirmed" : local.reveal;
  const showMine = iAmIn || (local.bet === "pending" && !lg.settled);
  $("myBet").classList.toggle("hidden", !showMine);
  $("myReveal").classList.toggle("hidden", !showMine);
  if (!iAmIn && local.bet === "pending" && lg.exists && lg.ncom >= 2)
    $("myBet").innerHTML = 'Your bet: <span class="b" style="background:rgba(248,81,73,.16);color:var(--danger)">didn\'t land — table filled first (your stake is safe)</span>';
  else
    $("myBet").innerHTML = (local.role === "bank" ? "Your bank: " : "Your bet: ") + badge(betC);
  $("myReveal").innerHTML = "Your reveal: " + badge(revC);
  // buttons
  const bothIn = lg.ncom === 2, bothRev = lg.r1 && lg.r2;
  const pastDeadline = lg.exists && !lg.settled && lastCursor != null && lastCursor > lg.deadline;
  $("btnReveal").classList.toggle("hidden", !(iAmIn && !myRevealed && bothIn && !lg.settled));
  $("btnSettle").classList.toggle("hidden", !(bothRev && !lg.settled));
  if (bothRev && !lg.settled) {
    const iWon = (iAmBettor && lg.win) || (iAmBank && lg.win === 0 && lg.result != null);
    $("btnSettle").textContent = iAmIn ? (iWon ? "💰 Collect your winnings" : "Spin & pay out") : "Spin & pay out";
  }
  $("btnClaim").classList.toggle("hidden", !pastDeadline);
  $("btnCancel").classList.toggle("hidden", !(iAmBank && lg.exists && !lg.settled && lg.ncom === 1));
  $("btnRematch").classList.toggle("hidden", !(lg.settled && iAmIn));
  // the wheel result
  const wheel = $("wheel");
  if (lg.result != null && (bothRev || lg.settled)) {
    wheel.className = "wheel " + colorOf(lg.result); wheel.textContent = lg.result;
    const w = iAmIn ? ((iAmBettor && lg.win) ? "you WON " + rawToNado(BigInt(lg.stake) * BigInt(Math.floor(36 / lg.count))) + " NADO 🎉"
                      : (iAmBank && !lg.win) ? "your bank WON +" + rawToNado(lg.stake) + " NADO 🎉"
                      : "you lost")
                    : (lg.win ? "bettor won" : "bank won");
    $("result").textContent = colorOf(lg.result).toUpperCase() + " " + lg.result + " — " + w + (lg.settled ? "" : " · paying out…");
  } else {
    wheel.className = "wheel spin"; wheel.textContent = "?";
    $("result").textContent = bothIn ? "Both seated — reveal to spin the wheel!"
      : (local.bet === "pending" && !iAmIn) ? "Your bet is confirming on-chain (~1 min)…"
      : lg.ncom === 1 ? "Waiting for a bettor to sit down…" : "Waiting for the bank…";
  }
}

let lastCursor = null;
async function pollCursor() {   // the applied L1 height, for the claim (past-deadline) affordance
  try { const s = await (await fetch(base() + "/exec/root?ns=" + NS + "&provisional=1", { cache: "no-store" })).json(); lastCursor = s.cursor != null ? Number(s.cursor) : lastCursor; } catch {}
}

async function boot() {
  try { await loadCrypto(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI();
  if ($("play") && $("activeGame")) $("play").parentNode.insertBefore($("activeGame"), $("play"));
  loadQR();
  handleReturn();
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (active == null) active = parseInt(q, 10); deepLinkGame = q; }
  if (me) await fetchBalance();
  paintTable();
  render();
  pollCursor(); refreshActive();
  setInterval(() => { pollCursor(); refreshActive(); }, 3000);
}
boot();

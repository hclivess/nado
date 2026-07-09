// roulette.js — NADO Roulette: a provably-fair, peer-banked, MULTIPLAYER European (single-zero) roulette on
// the execution layer. A table is one shared wheel: a BANK opens it with a bankroll and a committed secret,
// then during a betting WINDOW any number of BETTORS take a seat by staking a bet on a set of table numbers
// (one signature per bet — no per-player secret). When the window closes the bank reveals its secret and ONE
// shared spin  result = HASH(bankSecret + tableId) % 37  decides every seat at once. A win pays the true
// 36/count; losers' stakes go to the bank. Each seat settles INDEPENDENTLY, so a no-show never stalls the
// table; if the bank itself stalls, every seat force-claims its MAX win after the deadline. It is an ordinary
// upgradable stackvm CONTRACT (cid below) driven through the generic exec `call` op — no roulette-specific API.
import { loadCrypto, blake2bHash } from "./nadotx.js";

const NS = "default";
const WALLET = "https://get.nadochain.com";
const RAW = 10n ** 10n;
const PN = 37, MAXSLOTS = 18, SENTINEL = 99;
const BLOCK_SECS = 6;
const base = () => location.origin.replace(/\/+$/, "");
const $ = (id) => document.getElementById(id);
const RED = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
const colorOf = (n) => n === 0 ? "green" : (RED.has(n) ? "red" : "black");

// ---- QR (vendored) -------------------------------------------------------------------------------
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
async function shareTable() {
  if (activeTable == null) return;
  const url = base() + "/?table=" + activeTable;
  if (navigator.share) {
    try { await navigator.share({ title: "NADO Roulette", text: "Bet at my roulette table #" + activeTable + " on NADO:", url }); return; }
    catch (e) { if (e && e.name === "AbortError") return; }
  }
  const btn = $("btnShare"); let ok = false;
  try { await navigator.clipboard.writeText(url); ok = true; } catch {}
  if (btn) { btn.textContent = ok ? "Copied ✓" : "copy failed"; setTimeout(() => (btn.textContent = "Share"), 1400); }
}

const LS_ME = "nado_roul_me", LS_T = "nado_roul_tables", LS_S = "nado_roul_seats", LS_P = "nado_roul_pending";
const load = (k) => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
let me = localStorage.getItem(LS_ME) || null;
let activeTable = null, lastTable = null, lastSeats = [], myBalance = 0n, myL1Balance = 0n, lastCursor = null;
let selected = new Set();
const FEE = 1000n;

// ---- amounts / secrets ---------------------------------------------------------------------------
const randId = () => globalThis.crypto.getRandomValues(new Uint32Array(1))[0] % 1000000000 + 1;   // 1..1e9
const randSecret = () => { let h = "0x"; for (const b of globalThis.crypto.getRandomValues(new Uint8Array(32))) h += b.toString(16).padStart(2, "0"); return BigInt(h); };
const commitHashOf = (secret) => BigInt("0x" + blake2bHash(secret));
function nadoToRaw(s) {
  s = String(s || "").trim(); if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const [w, f = ""] = s.split("."); const raw = BigInt(w) * RAW + BigInt((f + "0000000000").slice(0, 10));
  return raw > 0n ? raw : null;
}
const rawToNado = (raw) => { raw = BigInt(raw); const w = raw / RAW, f = (raw % RAW).toString().padStart(10, "0").replace(/0+$/, ""); return f ? `${w}.${f}` : `${w}`; };
const encBig = (v) => typeof v === "bigint" ? { $big: v.toString() }
  : Array.isArray(v) ? v.map(encBig)
  : (v && typeof v === "object") ? Object.fromEntries(Object.keys(v).map((k) => [k, encBig(v[k])])) : v;

// ---- delegated wallet signing --------------------------------------------------------------------
function go(obj, pend) {
  const payload = btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
  save(LS_P, pend || {});
  location.href = WALLET + "/?exec_sign=" + encodeURIComponent(payload) + "&ret=" + encodeURIComponent(base() + "/") + "&app=" + encodeURIComponent("Roulette");
}
const signIn = () => go({ connect: true, label: "sign in" }, { phase: "connect" });
const deposit = (raw) => go({ deposit: { amount: raw.toString() }, label: "deposit " + rawToNado(raw) + " NADO" }, { phase: "deposit" });
const signBlob = (blob, label, pend) => go({ blob: encBig(blob), label }, pend);
const CID = "186ebadb975794e2ed7eeb1c7b5115a5";
function callC(method, args, valueRaw, label, pend) {
  const payload = { op: "call", contract: CID, method, args };
  if (valueRaw != null) payload.value = valueRaw;
  signBlob(payload, label, pend);
}
// shared spin — MUST match the contract: HASH(secret + tableId) % 37
function spinResult(secret, t) { return Number(BigInt("0x" + blake2bHash((BigInt(secret) + BigInt(t)).toString())) % BigInt(PN)); }

function handleReturn() {
  const p = new URLSearchParams(location.search);
  if (!p.has("ok")) return;
  const ok = p.get("ok") === "1", addr = p.get("addr"), err = p.get("err") ? decodeURIComponent(p.get("err")) : "";
  let pend = null; try { pend = JSON.parse(localStorage.getItem(LS_P) || "null"); } catch {}
  localStorage.removeItem(LS_P);
  try { history.replaceState(null, "", location.pathname); } catch {}
  if (ok && addr) { me = addr; localStorage.setItem(LS_ME, addr); }
  if (!pend) return;
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming on-chain…", open: "Table opening — confirming…",
    bet: "Bet placed — confirming…", reveal: "Spinning the wheel — confirming…", settle: "Collecting…",
    claim: "Claiming…", close: "Closing table…", withdraw: "Withdrawal submitted." }[pend.phase] || "Submitted.";
  if (pend.table != null) activeTable = pend.table;
  if (ok && pend.phase === "bet" && pend.seat != null) { const s = load(LS_S); if (s[pend.seat]) { s[pend.seat].bet = "pending"; save(LS_S, s); } }
  if (ok && pend.phase === "reveal" && pend.table != null) { const t = load(LS_T); if (t[pend.table]) { t[pend.table].reveal = "pending"; save(LS_T, t); } }
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
}

// ---- reads ---------------------------------------------------------------------------------------
async function fetchBalance() {
  if (!me) { myBalance = 0n; myL1Balance = 0n; return; }
  try { const b = await (await fetch(base() + "/exec/bridge?ns=" + NS + "&provisional=1", { cache: "no-store" })).json(); myBalance = BigInt((b.balances || {})[me] || 0); } catch { myBalance = 0n; }
  try { const a = await (await fetch(base() + "/get_account?address=" + encodeURIComponent(me), { cache: "no-store" })).json(); myL1Balance = BigInt(a.balance || 0); } catch { myL1Balance = 0n; }
}
async function pollCursor() {
  try { const s = await (await fetch(base() + "/exec/root?ns=" + NS + "&provisional=1", { cache: "no-store" })).json(); lastCursor = s.cursor != null ? Number(s.cursor) : lastCursor; } catch {}
}
async function fetchStorage() {
  try { return (await (await fetch(base() + "/exec/contract?ns=" + NS + "&cid=" + CID + "&provisional=1", { cache: "no-store" })).json()).storage || {}; }
  catch { return null; }
}
const _m = (sto, name) => sto[name] || {};
const allTables = (sto) => Object.keys(_m(sto, "ta"));
const allSeats = (sto) => Object.keys(_m(sto, "gg"));
function coveredOf(sto, g) { const cov = _m(sto, "cov"), out = [], b = Number(g) * PN; for (let n = 0; n < PN; n++) if (cov[String(b + n)]) out.push(n); return out; }

// a table's phase from the current cursor
function tablePhase(tb) {
  if (tb.closed) return "done";
  if (tb.revealed) return "revealed";
  const cur = lastCursor;
  if (cur == null) return "betting";
  if (cur <= tb.joinDeadline) return "betting";
  if (cur <= tb.revealDeadline) return "spinning";
  return "forfeit";
}
function tableFrom(sto, t) {
  t = String(t); const bank = _m(sto, "ta")[t];
  if (!bank) return { exists: false };
  const tb = { exists: true, id: Number(t), bank, bankroll: _m(sto, "tk")[t] || 0, pool: _m(sto, "tp")[t] || 0,
    committed: _m(sto, "tc")[t] || 0, revealed: !!_m(sto, "tr")[t], secret: _m(sto, "ts")[t] || null,
    joinDeadline: _m(sto, "tj")[t] || 0, revealDeadline: _m(sto, "tv")[t] || 0,
    seatCount: _m(sto, "tn")[t] || 0, settledCount: _m(sto, "tx")[t] || 0, closed: !!_m(sto, "tz")[t] };
  tb.result = (tb.revealed && tb.secret != null) ? spinResult(tb.secret, tb.id) : null;
  tb.phase = tablePhase(tb);
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const covered = coveredOf(sto, g), cn = _m(sto, "gc")[g] || covered.length || 1;
    out.push({ g: Number(g), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0, count: cn, covered,
      settled: !!_m(sto, "gd")[g], mult: Math.floor(36 / cn) });
  }
  return out.sort((a, b) => a.g - b.g);
}
async function fetchTable(t) { const sto = await fetchStorage(); return sto ? tableFrom(sto, t) : null; }

const _aliasCache = {};
async function resolveAliases(addrs) {
  await Promise.all([...new Set(addrs)].filter((a) => a && !(a in _aliasCache)).map(async (a) => {
    try { const r = await (await fetch(base() + "/get_aliases_of?address=" + encodeURIComponent(a), { cache: "no-store" })).json(); _aliasCache[a] = (r.aliases && r.aliases[0]) || null; }
    catch { _aliasCache[a] = null; }
  }));
}
const disp = (addr) => !addr ? "—" : (_aliasCache[addr] ? "@" + _aliasCache[addr] : addr.slice(0, 8) + "…" + addr.slice(-4));

// ---- bet maths -----------------------------------------------------------------------------------
const betCount = () => selected.size;
const betMult = () => { const c = betCount(); return c >= 1 && c <= MAXSLOTS ? Math.floor(36 / c) : 0; };
const betSlots = () => { const a = [...selected].sort((x, y) => x - y); while (a.length < MAXSLOTS) a.push(SENTINEL); return a; };
const blocksToTime = (b) => { b = Math.max(0, b) * BLOCK_SECS; const m = Math.floor(b / 60), s = b % 60; return m + ":" + String(s).padStart(2, "0"); };

// ---- actions -------------------------------------------------------------------------------------
function doDeposit() {
  const raw = nadoToRaw($("bankAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to deposit."; return; }
  if (raw + FEE > myL1Balance) { $("status").textContent = "Not enough in your L1 wallet: you have " + rawToNado(myL1Balance) + " NADO. Mine or receive more first."; return; }
  deposit(raw);
}
function doWithdraw() {
  const raw = nadoToRaw($("bankAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to withdraw."; return; }
  if (myBalance < raw) { $("status").textContent = "You only have " + rawToNado(myBalance) + " NADO in the exec layer."; return; }
  signBlob({ op: "bridge_withdraw", amount: raw }, "withdraw " + rawToNado(raw) + " NADO to L1", { phase: "withdraw" });
}
function openTable(t, bankrollRaw) {
  const T = load(LS_T);
  const secretStr = (T[t] && T[t].secret) ? T[t].secret : randSecret().toString();
  T[t] = { secret: secretStr, bankroll: bankrollRaw.toString(), ts: Date.now(), reveal: (T[t] || {}).reveal }; save(LS_T, T);
  activeTable = t; render();
  callC("open", [t, commitHashOf(BigInt(secretStr))], bankrollRaw, "bank roulette table #" + t + " · " + rawToNado(bankrollRaw) + " NADO", { table: t, phase: "open" });
}
function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) { $("status").textContent = "Enter a bankroll (NADO) to bank a table."; return; }
  if (myBalance < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(myBalance) + " NADO."; return; }
  openTable(randId(), raw);
}
async function doBet() {
  const t = parseInt($("joinId").value, 10);
  if (!t) { $("status").textContent = "Enter a table ID (or pick one from the lobby)."; return; }
  if (!betCount()) { $("status").textContent = "Pick at least one number on the table to bet on."; return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = "No such table yet — ask the bank for the ID after they open it."; return; }
  if (tb.phase !== "betting") { $("status").textContent = "Betting is closed on that table (" + tb.phase + ")."; return; }
  await fetchBalance();
  if (myBalance < stake) { $("status").textContent = "You need " + rawToNado(stake) + " NADO in your exec balance (you have " + rawToNado(myBalance) + "). Deposit first."; render(); return; }
  const need = stake * BigInt(betMult() - 1);
  if (BigInt(tb.bankroll) - BigInt(tb.committed) < need) { $("status").textContent = "This table can't cover a " + betMult() + "× win right now (bankroll left: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake or widen your bet."; render(); return; }
  const g = randId(), slots = betSlots();
  const S = load(LS_S);
  S[g] = { table: t, stake: stake.toString(), numbers: slots.filter((n) => n < PN), ts: Date.now(), bet: undefined }; save(LS_S, S);
  activeTable = t; render();
  callC("bet", [g, t, ...slots], stake, "bet " + rawToNado(stake) + " NADO on " + selected.size + " number(s) · table #" + t, { table: t, seat: g, phase: "bet" });
}
function revealTable() {
  const T = load(LS_T)[activeTable];
  if (!T || !T.secret) { $("status").textContent = "No bank secret for this table on this device."; return; }
  callC("reveal", [activeTable, BigInt(T.secret)], null, "spin the wheel · table #" + activeTable, { table: activeTable, phase: "reveal" });
}
const settleSeat = (g) => callC("settle", [g], null, "collect seat #" + g, { table: activeTable, phase: "settle" });
const claimSeat = (g) => callC("claim", [g], null, "claim seat #" + g + " (bank stalled)", { table: activeTable, phase: "claim" });
const closeTable = () => callC("close", [activeTable], null, "close table #" + activeTable, { table: activeTable, phase: "close" });

async function refreshActive() {
  await fetchBalance();
  const sto = await fetchStorage();
  if (sto) {
    if (activeTable != null) { lastTable = tableFrom(sto, activeTable); lastSeats = seatsOfTable(sto, activeTable); }
    renderLobby(sto);
    renderScoreboard(boardFrom(sto));
    lastStorage = sto;
  }
  await resolveAliases([me].concat(lastTable ? [lastTable.bank] : []).concat(lastSeats.map((s) => s.addr)));
  render();
}
let lastStorage = {};
// scoreboard: net NADO across finished (settled) seats + the bank's net per table
function boardFrom(sto) {
  const stats = {};
  const bump = (a, net) => { const x = stats[a] || (stats[a] = { addr: a, wins: 0, losses: 0, games: 0, net: 0 }); x.games++; x.net += net; net >= 0 ? x.wins++ : x.losses++; };
  for (const g of allSeats(sto)) {
    if (!_m(sto, "gd")[g]) continue;                    // only settled seats
    const t = String(_m(sto, "gg")[g]); const tb = tableFrom(sto, t);
    if (!tb.exists || tb.result == null) continue;
    const covered = coveredOf(sto, g), cn = _m(sto, "gc")[g] || 1, stake = _m(sto, "gs")[g] || 0;
    const win = covered.includes(tb.result);
    const seatNet = win ? stake * (Math.floor(36 / cn) - 1) : -stake;
    bump(_m(sto, "ga")[g], seatNet); bump(tb.bank, -seatNet);
  }
  return Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
}
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No finished bets yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10);
  await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => { const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO"; const you = r.addr === me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") + '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>"; }).join("") + "</tbody></table>";
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = allTables(sto).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  const rank = { betting: 0, spinning: 1, revealed: 2, forfeit: 1, done: 3 };
  const tag = { betting: "🟢", spinning: "🎡", revealed: "✓", forfeit: "⚠" };
  tables.sort((a, b) => (rank[a.phase] - rank[b.phase]) || (b.joinDeadline - a.joinDeadline));
  const shown = tables.slice(0, 24);
  if (!shown.length) { el.innerHTML = '<span class="dim">No tables yet — bank one below.</span>'; return; }
  el.innerHTML = shown.map((t) => {
    const left = t.phase === "betting" && lastCursor != null ? " · " + blocksToTime(t.joinDeadline - lastCursor) + " left" : "";
    const verb = t.phase === "betting" ? " · bet" : t.phase === "spinning" ? " · spinning" : t.phase === "forfeit" ? " · claim" : "";
    return '<button class="chip ' + t.phase + '" data-t="' + t.id + '">' + (tag[t.phase] || "") + " #" + t.id + " · bank " + rawToNado(t.bankroll) + " · " + t.seatCount + " seat" + (t.seatCount === 1 ? "" : "s") + left + verb + "</button>";
  }).join(" ");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeTable = parseInt(b.dataset.t, 10); $("joinId").value = b.dataset.t; refreshActive(); try { $("betTable").scrollIntoView({ behavior: "smooth", block: "center" }); } catch {} });
}

// ---- the roulette TABLE (bet builder) ------------------------------------------------------------
const GROUPS = { "1-18": range(1, 18), "19-36": range(19, 36), EVEN: range(1,36).filter(n=>n%2===0), ODD: range(1,36).filter(n=>n%2===1),
  RED: [...RED].sort((a,b)=>a-b), BLACK: range(1,36).filter(n=>!RED.has(n)),
  "1st 12": range(1,12), "2nd 12": range(13,24), "3rd 12": range(25,36), C1: col(1), C2: col(2), C3: col(3) };
function range(a, b) { const o = []; for (let i = a; i <= b; i++) o.push(i); return o; }
function col(c) { return range(1, 36).filter((n) => (n % 3) === (c % 3)); }
function buildTable() {
  const grid = $("tableGrid"); if (!grid || grid.dataset.built) return; grid.dataset.built = "1";
  let html = '<button class="cell green zero" data-n="0">0</button>';
  for (let rrow = 0; rrow < 3; rrow++) for (let ccol = 0; ccol < 12; ccol++) {
    const n = ccol * 3 + (3 - rrow);
    html += '<button class="cell ' + colorOf(n) + '" data-n="' + n + '" style="grid-row:' + (rrow + 1) + ';grid-column:' + (ccol + 2) + '">' + n + "</button>";
  }
  for (let rrow = 0; rrow < 3; rrow++) html += '<button class="cell col2to1" data-grp="C' + (3 - rrow) + '" style="grid-row:' + (rrow + 1) + ';grid-column:14">2:1</button>';
  grid.innerHTML = html;
  grid.querySelectorAll("[data-n]").forEach((b) => b.onclick = () => toggleNum(parseInt(b.dataset.n, 10)));
  grid.querySelectorAll("[data-grp]").forEach((b) => b.onclick = () => selectGroup(b.dataset.grp));
  document.querySelectorAll("[data-grp2]").forEach((b) => b.onclick = () => selectGroup(b.dataset.grp2));
  const clr = $("btnClearBet"); if (clr) clr.onclick = () => { selected = new Set(); paintTable(); render(); };
}
function toggleNum(n) { if (selected.has(n)) selected.delete(n); else if (selected.size < MAXSLOTS) selected.add(n); paintTable(); render(); }
function selectGroup(key) { selected = new Set((GROUPS[key] || []).slice(0, MAXSLOTS)); paintTable(); render(); }
function paintTable() { document.querySelectorAll("#tableGrid .cell[data-n]").forEach((b) => b.classList.toggle("sel", selected.has(parseInt(b.dataset.n, 10)))); }

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = signIn;
  $("btnDeposit").onclick = doDeposit;
  $("btnWithdraw").onclick = doWithdraw;
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("joinId").oninput = () => render();
  $("stakeAmt").oninput = () => render();
  $("btnReveal").onclick = revealTable;
  $("btnClose").onclick = closeTable;
  $("btnShare").onclick = shareTable;
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
  const c = betCount(), M = betMult(), stakeRaw = nadoToRaw($("stakeAmt").value);
  $("betInfo").innerHTML = c
    ? "Covering <b>" + c + "</b> number" + (c > 1 ? "s" : "") + " · pays <b>" + M + "×</b>" + (stakeRaw ? " · win returns <b>" + rawToNado(stakeRaw * BigInt(M)) + " NADO</b> (net +" + rawToNado(stakeRaw * BigInt(M - 1)) + ")" : "")
    : '<span class="dim">Tap numbers or a bet region on the table to build your bet.</span>';
  // Bet button affordability (mirrors the coinflip lessons)
  const jid = ($("joinId").value || "").trim();
  const tb = (jid && String(activeTable) === jid && lastTable && lastTable.exists) ? lastTable : null;
  const canBetPhase = !tb || tb.phase === "betting";
  const canAfford = !(signedIn && stakeRaw && myBalance < stakeRaw);
  const need = (stakeRaw && M) ? stakeRaw * BigInt(M - 1) : null;
  const bankCovers = !(tb && need != null && (BigInt(tb.bankroll) - BigInt(tb.committed)) < need);
  const betable = !!jid && !!c && !!stakeRaw && canBetPhase && canAfford && bankCovers;
  $("btnBet").disabled = !betable;
  $("btnBet").classList.toggle("pulse", betable && signedIn);
  $("btnSignIn").classList.toggle("pulse", !!jid && !!c && !signedIn);
  let hint = "";
  if (jid && c && signedIn && canBetPhase) {
    if (stakeRaw && myBalance < stakeRaw) hint = "Not enough NADO — your bet stakes " + rawToNado(stakeRaw) + " but your exec balance is " + rawToNado(myBalance) + ". Deposit at least " + rawToNado(stakeRaw - myBalance) + " more below.";
    else if (tb && !bankCovers) hint = "This table can't cover a " + M + "× win right now (bankroll left: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake or widen your bet.";
  } else if (jid && tb && tb.phase !== "betting") hint = "Betting is closed on table #" + jid + " (" + tb.phase + ").";
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  // my recent tables + seats
  const T = load(LS_T), S = load(LS_S);
  const mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, role: "bet", seat: +g, ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts);
  const seen = new Set();
  $("recent").innerHTML = mine.filter((x) => { const k = x.id + x.role; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8)
    .map((x) => '<button class="chip" data-t="' + x.id + '">' + (x.role === "bank" ? "🏦" : "🎯") + " #" + x.id + "</button>").join(" ") || '<span class="dim">No tables yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeTable = parseInt(b.dataset.t, 10); refreshActive(); });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (activeTable == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {}, S = load(LS_S);
  const iAmBank = tb.bank === me;
  const mySeats = lastSeats.filter((s) => s.addr === me);
  $("gameId").textContent = "#" + activeTable;
  $("shareLink").value = base() + "/?table=" + activeTable;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?table=" + activeTable, 180);
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.bankroll) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  const left = tb.exists && !tb.committed ? tb.bankroll : (tb.exists ? BigInt(tb.bankroll) - BigInt(tb.committed) : 0);
  $("gCover").textContent = tb.exists ? rawToNado(left) + " NADO free" : "—";
  // phase line + countdown
  let phaseTxt = "opening…";
  if (tb.exists) {
    if (tb.phase === "betting") phaseTxt = "🟢 betting open — " + (lastCursor != null ? blocksToTime(tb.joinDeadline - lastCursor) + " left" : "…") + " · " + tb.seatCount + " seat" + (tb.seatCount === 1 ? "" : "s");
    else if (tb.phase === "spinning") phaseTxt = "🎡 betting closed — waiting for the bank to spin";
    else if (tb.phase === "forfeit") phaseTxt = "⚠ bank didn't spin — claim your max win";
    else if (tb.phase === "revealed") phaseTxt = "✓ spun — " + tb.settledCount + "/" + tb.seatCount + " seats collected";
    else if (tb.phase === "done") phaseTxt = "table closed";
  }
  $("gStatus").textContent = phaseTxt;
  // the wheel
  const wheel = $("wheel");
  if (tb.result != null) { wheel.className = "wheel " + colorOf(tb.result); wheel.textContent = tb.result;
    $("result").textContent = colorOf(tb.result).toUpperCase() + " " + tb.result; }
  else if (tb.phase === "spinning" || tb.phase === "forfeit") { wheel.className = "wheel spin"; wheel.textContent = "?"; $("result").textContent = tb.phase === "forfeit" ? "Bank stalled — claim below" : "Betting closed — spinning soon"; }
  else { wheel.className = "wheel"; wheel.textContent = "?"; $("result").textContent = tb.phase === "betting" ? "Place your bets!" : "…"; }
  // seats list
  const seatRow = (s) => {
    const youTag = s.addr === me ? '<b style="color:var(--accent2)">you</b> ' : "";
    const pips = s.covered.slice(0, 6).map((n) => '<span class="pip ' + colorOf(n) + '">' + n + "</span>").join("") + (s.covered.length > 6 ? " +" + (s.covered.length - 6) : "");
    let out = "";
    if (tb.result != null) { const win = s.covered.includes(tb.result);
      out = s.settled ? (win ? '<span class="b ok">won ' + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + "</span>" : '<span class="b dimb">no win</span>')
                      : (win ? '<span class="b pend">wins ' + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + " — collect</span>" : '<span class="b dimb">lost</span>'); }
    return '<div class="seat">' + youTag + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> on " + pips + " <span class='dim'>(" + s.mult + "×)</span> " + out + "</div>";
  };
  $("seats").innerHTML = lastSeats.length ? lastSeats.map(seatRow).join("") : '<span class="dim">No seats yet — be the first to bet.</span>';
  // my seats' pending bets not yet on-chain
  const myPending = Object.keys(S).filter((g) => S[g].table === activeTable && S[g].bet === "pending" && !mySeats.some((s) => s.g === +g));
  $("myStuff").innerHTML = myPending.length ? myPending.map((g) => '<div class="seat"><b style="color:var(--accent2)">you</b> · ' + rawToNado(S[g].stake) + ' NADO on ' + (S[g].numbers || []).length + " no. " + badge("pending") + "</div>").join("") : "";
  // action buttons
  const bankPending = T.reveal === "pending";
  $("btnReveal").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.revealed && (tb.phase === "spinning") && !bankPending));
  $("btnReveal").textContent = "🎡 Spin the wheel (" + tb.seatCount + " bet" + (tb.seatCount === 1 ? "" : "s") + ")";
  // per-seat collect/claim buttons for MY seats
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled) continue;
    if (tb.phase === "revealed") { const win = s.covered.includes(tb.result);
      const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
      b.textContent = win ? "💰 Collect " + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + " (seat #" + s.g + ")" : "Close out seat #" + s.g;
      b.onclick = () => settleSeat(s.g); if (win || iAmBank) wrap.appendChild(b);
    } else if (tb.phase === "forfeit") {
      const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
      b.textContent = "⚠ Claim max win — seat #" + s.g; b.onclick = () => claimSeat(s.g); wrap.appendChild(b);
    }
  }
  // bank close (reclaim pool) once every seat is resolved
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.settledCount >= tb.seatCount && (tb.revealed || tb.phase === "forfeit" || tb.seatCount === 0)));
  $("btnClose").textContent = tb.seatCount === 0 ? "Cancel — reclaim bankroll" : "Close table — reclaim " + rawToNado(tb.pool);
}

async function boot() {
  try { await loadCrypto(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI();
  if ($("play") && $("activeGame")) $("play").parentNode.insertBefore($("activeGame"), $("play"));
  loadQR();
  handleReturn();
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  if (me) await fetchBalance();
  paintTable(); render();
  pollCursor(); refreshActive();
  setInterval(() => { pollCursor(); refreshActive(); }, 3000);
}
boot();

// bet.js — NADO Bet: parimutuel sports betting on the execution layer, built on the shared game SDK
// (nadodapp.js). No house, no bookmaker: every stake on a match goes into ONE escrow pool; when the
// result is posted the winning outcome's backers split the whole pool pro-rata to their stake
//     payout = your_stake * total_pool / winning_pool
// The real-world result is the one thing the chain can't derive, so an authorized ORACLE key posts it
// via resolve() reading a free public source; the oracle set is configurable (admin can add keys and
// require M-of-N). Bettors are protected: the oracle can void() a postponed match and, past a per-market
// deadline, ANYONE can void -> every stake refunds 1:1; an unbacked winner auto-voids. Payouts are
// pull-based (each bettor calls claim). Outcomes are integers 0..nout-1 everywhere.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, blocksToTime,
         wireWallet, stickyInputs, renderWallet, statusLabel, disp, resolveAliases,
         loadQR, share, shareInvite } from "./nadodapp.js";

const CID = "fe303d9880c8222dcf3b9953eb86a0fa";   // execnode/contracts/bet.json, deployed by the node key (nonce "bet-v1")
const dapp = new NadoDapp({ cid: CID, app: "Bet" });
const BLOCK_SECS = 6, BPM = 60 / BLOCK_SECS;   // 10 blocks / minute
let lastSto = null, activeMarket = null, selOutcome = null;

// ---- reads (bet-specific storage schema) ---------------------------------------------------------
const cfg = (sto, k) => _m(sto, "cfg")[k];
const isOracle = (sto) => !!dapp.me && Number(_m(sto, "orc")[dapp.me] || 0) === 1;
const isAdmin  = (sto) => !!dapp.me && dapp.me === cfg(sto, "admin");
const sourcesOf = (sto) => { const s = _m(sto, "src"), n = Number(cfg(sto, "srcN") || 0), out = []; for (let i = 0; i < n; i++) if (s[i]) out.push(s[i]); return out; };

function parseMarket(sto, id) {
  const G = (m) => _m(sto, m)[id];
  if (!G("mk")) return null;
  const nout = Number(G("no") || 0);
  const lines = String(G("ds") || "").split("\n");
  const title = lines[0] || ("Match #" + id);
  const labels = []; for (let i = 0; i < nout; i++) labels.push(lines[i + 1] || ("Outcome " + i));
  const total = Number(_m(sto, "tot")[id] || 0);
  const pools = []; for (let i = 0; i < nout; i++) pools.push(Number(_m(sto, "pl")[id + "|" + i] || 0));
  const resolved = !!G("dn"), voided = !!G("vd");
  const winner = resolved ? Number(G("rs")) - 1 : null;
  const lock = Number(G("lk") || 0), deadline = Number(G("dl") || 0), cur = dapp.cursor;
  const locked = cur != null && cur >= lock;
  const status = voided ? "void" : resolved ? "resolved" : locked ? "locked" : "open";
  const me = dapp.me;
  const myStakes = []; for (let i = 0; i < nout; i++) myStakes.push(me ? Number(_m(sto, "stk")[id + "|" + i + "|" + me] || 0) : 0);
  const myTotal = me ? Number(_m(sto, "us")[id + "|" + me] || 0) : 0;
  const claimed = me ? !!_m(sto, "cl")[id + "|" + me] : false;
  return { id: Number(id), nout, title, labels, total, pools, resolved, voided, winner, lock, deadline, cur,
           locked, status, myStakes, myTotal, claimed, source: String(G("so") || ""), ev: String(G("ev") || "") };
}
const allMarkets = (sto) => Object.keys(_m(sto, "mk")).map((id) => parseMarket(sto, id)).filter(Boolean);
// live decimal odds for outcome i: whole pool ÷ that outcome's pool (what a winning unit returns)
const oddsOf = (mk, i) => mk.pools[i] > 0 && mk.total > 0 ? mk.total / mk.pools[i] : null;
const fmtOdds = (o) => o == null ? "—" : o.toFixed(2) + "×";
// claimable amount for the signed-in bettor (0 if nothing / already claimed / not yet settled)
function claimable(mk) {
  if (!mk || mk.claimed || mk.myTotal <= 0) return 0;
  if (mk.voided) return mk.myTotal;
  if (mk.resolved && mk.winner != null && mk.pools[mk.winner] > 0)
    return Math.floor(mk.myStakes[mk.winner] * mk.total / mk.pools[mk.winner]);
  return 0;
}
const STATUS_TAG = { open: '<span class="b ok">🟢 open</span>', locked: '<span class="b pend">🔒 locked</span>',
  resolved: '<span class="b ok">✅ resolved</span>', void: '<span class="b void">↩ void</span>' };
function statusText(mk) {
  if (mk.voided) return "voided — every stake refunded 1:1";
  if (mk.resolved) return "resolved — " + mk.labels[mk.winner] + " won";
  if (mk.locked) return "locked — awaiting the result" + (mk.cur >= mk.deadline ? " (past deadline — anyone can void)" : "");
  const left = mk.cur != null ? blocksToTime(mk.lock - mk.cur) : "…";
  return "open — betting closes in " + left;
}

// ---- actions -------------------------------------------------------------------------------------
async function placeBet() {
  if (activeMarket == null || selOutcome == null) { $("status").textContent = "Pick a match and an outcome first."; return; }
  const mk = lastSto && parseMarket(lastSto, activeMarket);
  if (!mk || mk.status !== "open") { $("status").textContent = "This match isn't open for bets."; render(); return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  await dapp.refresh();
  if (!canPay(dapp, stake, "This bet")) { render(); return; }
  const lab = mk.labels[selOutcome];
  dapp.call("bet", [activeMarket, selOutcome], stake, "bet " + rawToNado(stake) + " on " + lab + " · match #" + activeMarket,
            { market: activeMarket, phase: "bet" });
}
const claimMarket = (m) => dapp.call("claim", [m], null, "collect from match #" + m, { market: m, phase: "claim" });
const voidMarket  = (m) => dapp.call("void", [m], null, "void match #" + m + " (refund everyone)", { market: m, phase: "void" });
const resolveMarket = (m, out, lab) => dapp.call("resolve", [m, out], null, "post result: " + lab + " won · match #" + m, { market: m, phase: "resolve" });

function createMarket() {
  const title = ($("cmTitle").value || "").trim();
  const labels = ($("cmLabels").value || "").split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
  const source = $("cmSource").value || "";
  const ev = ($("cmEvent").value || "").trim();
  const closeMin = parseFloat($("cmCloseMin").value) || 0, voidHrs = parseFloat($("cmVoidHrs").value) || 0;
  if (!title) return set("Give the match a title.");
  if (labels.length < 2) return set("List at least two outcomes (comma- or line-separated).");
  if (!source) return set("Add and pick a source first.");
  if (closeMin <= 0) return set("Betting must close in a positive number of minutes.");
  if (dapp.cursor == null) return set("Chain height unknown — try again in a moment.");
  const lock = Math.round(dapp.cursor + closeMin * BPM);
  const deadline = Math.round(lock + Math.max(voidHrs, 0.5) * 60 * BPM);
  const id = randId();
  const desc = [title].concat(labels).join("\n");
  dapp.call("create_market", [id, labels.length, lock, deadline, desc, source, ev], null,
            "list “" + title + "” for betting", { market: id, phase: "create" });
}
const addSource = () => { const n = ($("srcName").value || "").trim(); if (!n) return set("Enter a source name."); dapp.call("add_source", [n], null, "add source " + n, { phase: "src" }); };
const addOracle = () => { const a = ($("orcAddr").value || "").trim(); if (!a) return set("Enter an oracle address."); dapp.call("set_oracle", [a, 1], null, "add oracle " + disp(a), { phase: "orc" }); };
const setThreshold = () => { const m = parseInt($("thrVal").value, 10); if (!m || m < 1) return set("Enter a threshold ≥ 1."); dapp.call("set_threshold", [m], null, "require " + m + "-of-N oracles", { phase: "thr" }); };
const set = (m) => { $("status").textContent = m; };

// ---- refresh + render ----------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) lastSto = sto;
  if (lastSto) await resolveAliases([dapp.me, cfg(lastSto, "admin")].filter(Boolean));
  render();
}
function selectMarket(id) {
  activeMarket = Number(id); selOutcome = null;
  set("Match #" + id + " — pick an outcome and place your bet.");
  render();
  try { $("activeMarket").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

function marketCard(mk) {
  const oddsRow = mk.outsHTML;
  const meta = [];
  if (mk.myTotal > 0) meta.push('<span class="b ok" style="margin-left:0">your bet ' + rawToNado(mk.myTotal) + "</span>");
  meta.push(statusText(mk));
  return '<div class="mkt' + (mk.id === activeMarket ? " sel" : "") + '" data-m="' + mk.id + '">' +
    '<div class="top"><span class="ttl">' + esc(mk.title) + "</span>" + STATUS_TAG[mk.status] + "</div>" +
    '<div class="meta">' + meta.join(" · ") + "</div>" + oddsRow + "</div>";
}
function outcomesHTML(mk, opts) {
  opts = opts || {};
  return '<div class="outs">' + mk.labels.map((lab, i) => {
    const o = oddsOf(mk, i), pct = mk.total > 0 ? Math.round(mk.pools[i] * 100 / mk.total) : 0;
    const cls = ["out"];
    if (opts.select && i === selOutcome) cls.push("sel");
    if (mk.resolved && i === mk.winner) cls.push("win");
    return '<div class="' + cls.join(" ") + '" data-o="' + i + '"' + (opts.click ? ' data-click="1"' : "") + '>' +
      '<div class="lab">' + esc(lab) + "</div>" +
      '<div class="odds">' + fmtOdds(o) + "</div>" +
      '<div class="pool">' + rawToNado(mk.pools[i]) + " · " + pct + "%</div>" +
      '<div class="oddsbar"><i style="width:' + pct + '%"></i></div></div>';
  }).join("") + "</div>";
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function render() {
  const sto = lastSto;
  const signedIn = renderWallet(dapp);
  gate({ bankroll: signedIn });
  if (!sto) { $("marketsList").innerHTML = '<span class="dim">Connecting to the chain…</span>'; return; }
  dapp.reflectUrl("market", activeMarket);

  // markets list — open first (by soonest close), then locked, then settled
  const mkts = allMarkets(sto);
  for (const mk of mkts) mk.outsHTML = outcomesHTML(mk);
  const rank = { open: 0, locked: 1, resolved: 2, void: 3 };
  mkts.sort((a, b) => (rank[a.status] - rank[b.status]) || (a.lock - b.lock) || (b.id - a.id));
  $("marketsList").innerHTML = mkts.length ? mkts.map(marketCard).join("")
    : '<span class="dim">No matches listed yet' + (isOracle(sto) ? " — list one in the Oracle console below." : ", check back soon.") + "</span>";
  $("marketsList").querySelectorAll(".mkt").forEach((el) => el.onclick = () => selectMarket(el.dataset.m));

  // my bets
  const mine = mkts.filter((m) => m.myTotal > 0);
  gate({ mybets: signedIn && mine.length > 0 });
  if (mine.length) $("myBetsList").innerHTML = mine.map((mk) => {
    const c = claimable(mk);
    let tag = statusText(mk);
    if (c > 0) tag = '<span class="b ok">💰 ' + rawToNado(c) + " to collect</span>";
    else if (mk.claimed) tag = '<span class="b dimb">collected ✓</span>';
    return '<div class="pos" data-m="' + mk.id + '" style="cursor:pointer"><span>' + esc(mk.title) +
      ' <span class="dim">· ' + rawToNado(mk.myTotal) + " staked</span></span><span>" + tag + "</span></div>";
  }).join("");
  $("myBetsList").querySelectorAll(".pos").forEach((el) => el.onclick = () => selectMarket(el.dataset.m));

  // sources + oracle panel
  const srcs = sourcesOf(sto);
  $("sourcesList").innerHTML = srcs.length ? srcs.map((s) => '<span class="b dimb" style="margin:0 4px 4px 0;display:inline-block">' + esc(s) + "</span>").join("")
    : '<span class="dim">none configured yet</span>';
  const oracle = isOracle(sto), admin = isAdmin(sto);
  gate({ oraclePanel: oracle });
  if (oracle) {
    $("cmSource").innerHTML = srcs.length ? srcs.map((s) => '<option>' + esc(s) + "</option>").join("")
      : '<option value="">— add a source first —</option>';
    $("cfgLine").textContent = (cfg(sto, "oc") || 1) + " key(s) · " + (cfg(sto, "thr") || 1) + "-of-N";
    gate({ adminOnly: admin, thrRow: admin });
  }
  renderActive(sto);
}

function renderActive(sto) {
  const shown = activeMarket != null && parseMarket(sto, activeMarket);
  gate({ activeMarket: !!shown });
  if (!shown) return;
  const mk = shown;
  $("mId").textContent = "#" + mk.id;
  $("mTitle").textContent = mk.title;
  $("mStatus").textContent = statusText(mk);
  $("mPool").textContent = rawToNado(mk.total) + " NADO";
  $("mSource").textContent = mk.source ? (mk.source + (mk.ev ? " · event " + mk.ev : "")) : "—";
  shareInvite("market", mk.id, "Bet on " + mk.title + " on NADO:", 180);

  // outcome picker (only clickable while open)
  $("mOutcomes").outerHTML = outcomesHTML(mk, { select: mk.status === "open", click: mk.status === "open" }).replace('class="outs"', 'class="outs" id="mOutcomes"');
  $("mOutcomes").querySelectorAll(".out[data-click]").forEach((el) => el.onclick = () => { selOutcome = Number(el.dataset.o); render(); });

  // bet builder
  const canBet = mk.status === "open";
  gate({ betBuilder: canBet });
  if (canBet) {
    const stake = nadoToRaw($("stakeAmt").value);
    let prev = "";
    if (selOutcome != null && stake) {
      const np = mk.pools[selOutcome] + Number(stake), nt = mk.total + Number(stake);
      const win = Math.floor(Number(stake) * nt / np);
      prev = "If " + esc(mk.labels[selOutcome]) + " wins and no one else bets, ≈ " + rawToNado(win) + " NADO (" + (win / Number(stake)).toFixed(2) + "×). Live odds move as others bet.";
    } else if (selOutcome == null) prev = "Pick an outcome above.";
    $("payoutPreview").innerHTML = prev;
    const ok = selOutcome != null && stake && dapp.me && dapp.exec >= stake;
    $("btnBet").disabled = !ok;
    $("btnBet").classList.toggle("pulse", !!ok);
    $("btnBet").textContent = selOutcome != null ? "Place bet on " + mk.labels[selOutcome] : "Place bet";
    const hint = $("betHint");
    let h = "";
    if (!dapp.me) h = "Sign in to bet.";
    else if (selOutcome != null && stake && dapp.exec < stake) h = "Not enough playable NADO — deposit at least " + rawToNado(stake - dapp.exec) + " more above.";
    hint.textContent = h; hint.classList.toggle("hidden", !h);
  }

  // my positions in this match
  const posEl = $("myPositions");
  const held = mk.myStakes.map((s, i) => ({ s, i })).filter((x) => x.s > 0);
  if (held.length) {
    posEl.innerHTML = '<div class="divlabel">Your bets on this match</div>' + held.map((x) => {
      let tail = "";
      if (mk.resolved) tail = x.i === mk.winner ? '<span class="b ok">won</span>' : '<span class="b dimb">lost</span>';
      else if (mk.voided) tail = '<span class="b void">refund</span>';
      return '<div class="pos"><span>' + esc(mk.labels[x.i]) + " · " + rawToNado(x.s) + " NADO</span><span>" + tail + "</span></div>";
    }).join("");
  } else posEl.innerHTML = "";

  // claim
  const c = claimable(mk), cr = $("claimRow"); cr.innerHTML = "";
  if (c > 0) {
    const b = document.createElement("button"); b.className = "primary pulse"; b.style.width = "100%";
    b.textContent = (mk.voided ? "↩ Reclaim " : "💰 Collect ") + rawToNado(c) + " NADO";
    b.onclick = () => claimMarket(mk.id); cr.appendChild(b);
  } else if (mk.claimed && mk.myTotal > 0) {
    cr.innerHTML = '<div class="small dim">You already collected from this match.</div>';
  }

  // oracle controls
  const oracle = isOracle(sto);
  gate({ oracleControls: oracle && (mk.status === "locked" || mk.status === "open") });
  if (oracle && (mk.status === "locked" || mk.status === "open")) {
    const canResolve = mk.status === "locked";
    $("resolveOutcomes").innerHTML = mk.labels.map((lab, i) =>
      '<button class="out" data-o="' + i + '"' + (canResolve ? "" : " disabled") + '><div class="lab">' + esc(lab) + " won</div></button>").join("");
    $("resolveOutcomes").querySelectorAll("button[data-o]").forEach((el) => el.onclick = () => resolveMarket(mk.id, Number(el.dataset.o), mk.labels[el.dataset.o]));
    $("btnVoid").onclick = () => voidMarket(mk.id);
  }
}

// ---- boot ----------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ["stakeAmt", "bankAmt", "cmTitle", "cmLabels", "cmEvent", "cmCloseMin", "cmVoidHrs"]);
  $("btnBet").onclick = placeBet;
  $("stakeAmt").addEventListener("input", () => { if (lastSto) renderActive(lastSto); });
  $("btnCreate").onclick = createMarket;
  $("btnAddSource").onclick = addSource;
  $("btnAddOracle").onclick = addOracle;
  $("btnSetThreshold").onclick = setThreshold;
  $("btnShare").onclick = () => share(base() + "/?market=" + activeMarket, "Bet on this match on NADO:", $("btnShare"));
}
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.market != null) activeMarket = pend.market;
  $("status").textContent = statusLabel(pend, ok, err);
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR();
  const q = new URLSearchParams(location.search).get("market");
  if (q && activeMarket == null) activeMarket = parseInt(q, 10);
  render(); refreshAll();
  setInterval(refreshAll, 4000);
}
boot();

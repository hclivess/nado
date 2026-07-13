// bet.js — NADO Bet: parimutuel sports betting on the execution layer, built on the shared game SDK
// (nadodapp.js). No house, no bookmaker: every stake on a match goes into ONE escrow pool; when the
// result is posted the winning outcome's backers split the whole pool pro-rata to their stake
//     payout = your_stake * total_pool / winning_pool
// The real-world result is the one thing the chain can't derive, so an authorized ORACLE key posts it
// via resolve() reading a free public source; the oracle set is configurable (admin can add keys and
// require M-of-N). Bettors are protected: the oracle can void() a postponed match and, past a per-market
// deadline, ANYONE can void -> every stake refunds 1:1; an unbacked winner auto-voids. Payouts are
// pull-based (each bettor calls claim). Outcomes are integers 0..nout-1 everywhere.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay,
         wireWallet, stickyInputs, renderWallet, statusLabel, disp, resolveAliases,
         alertBar, notify,
         loadQR, share, shareInvite } from "./nadodapp.js";

const CID = "fe303d9880c8222dcf3b9953eb86a0fa";   // execnode/contracts/bet.json, deployed by the node key (nonce "bet-v1")
const dapp = new NadoDapp({ cid: CID, app: "Bet" });
// Markets close/void by WALL-CLOCK time (the contract's TIME opcode = L1 block timestamp), never block height —
// block rate drifts, so a height deadline fires at an unpredictable real moment (that bug voided live matches a
// day early). lk/dl are epoch seconds. VOID_GRACE_SEC is UI wiggle room: the chain clock is only precise to tens
// of seconds (±30s producer drift + ~1 block of staleness), so we only hint "past deadline — anyone can void"
// once we're comfortably past it, never right on the boundary.
const VOID_GRACE_SEC = 300;
const fmtLeft = (s) => { s = Math.max(0, Math.round(s)); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), ss = s % 60;
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : m ? `${m}m ${ss}s` : `${ss}s`; };
let lastSto = null, activeMarket = null, selOutcome = null;
// Matches list scales to thousands: filter (settled markets accumulate forever, so hide them by default) +
// text search + a DOM cap so we never inject thousands of cards at once. shownN grows via "show more".
const PAGE_SIZE = 60;
let searchQ = "", mktFilter = "live", shownN = PAGE_SIZE;
const isSettled = (m) => m.status === "resolved" || m.status === "void";
function visibleMarkets(mkts) {
  const q = searchQ.trim().toLowerCase();
  return mkts.filter((m) => {
    if (mktFilter === "live" && isSettled(m)) return false;
    if (mktFilter === "settled" && !isSettled(m)) return false;
    return !q || m.title.toLowerCase().includes(q) || String(m.id).includes(q);
  });
}
// optimistic-status labels (SDK owns the lifecycle via showReturn/settleInflight/doneLabels)
const CONFIRMING = { bet: window.t("bet.cfBet", "Bet placed — confirming on-chain…"), claim: window.t("bet.cfClaim", "Collecting your winnings — confirming…"),
  create: window.t("bet.cfCreate", "Listing your market — confirming…"), resolve: window.t("bet.cfResolve", "Posting the result — confirming…"),
  void: window.t("bet.cfVoid", "Voiding — refunding bettors…"), src: window.t("bet.cfSrc", "Adding source — confirming…") };
const DONE = { bet: window.t("bet.dnBet", "✓ Bet confirmed"), claim: window.t("bet.dnClaim", "✓ Winnings collected"), create: window.t("bet.dnCreate", "✓ Market listed"),
  resolve: window.t("bet.dnResolve", "✓ Result posted"), void: window.t("bet.dnVoid", "✓ Market voided"), src: window.t("bet.dnSrc", "✓ Source added") };
// game-specific "did the in-flight action land on-chain?" check for dapp.settleInflight
function actionLanded(f) {
  const sto = lastSto, me = dapp.me, m = f.market;
  if (!sto || !me) return false;
  if (f.phase === "bet") return Number(_m(sto, "us")[m + "|" + me] || 0) > (f.prevUs || 0);
  if (f.phase === "claim") return !!_m(sto, "cl")[m + "|" + me];
  if (f.phase === "create") return !!_m(sto, "mk")[m];
  if (f.phase === "resolve") return !!_m(sto, "dn")[m] || !!_m(sto, "vd")[m] || Number(_m(sto, "vt")[m + "|" + me] || 0) > 0;
  if (f.phase === "void") return !!_m(sto, "vd")[m];
  if (f.phase === "src") return true;
  return false;
}

// ---- reads (bet-specific storage schema) ---------------------------------------------------------
const cfg = (sto, k) => _m(sto, "cfg")[k];
const isOracle = (sto) => !!dapp.me && Number(_m(sto, "orc")[dapp.me] || 0) === 1;
const isAdmin  = (sto) => !!dapp.me && dapp.me === cfg(sto, "admin");
// may the signed-in user resolve market m? — a named resolver of THIS market, or the admin for a
// legacy (resolver-less) market. Mirrors the contract's resolve/void gate.
const canResolveMkt = (sto, m) => !!dapp.me && (Number(_m(sto, "mres")[m + "|" + dapp.me] || 0) === 1
  || (Number(_m(sto, "mrc")[m] || 0) === 0 && dapp.me === cfg(sto, "admin")));
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
  // lk/dl are epoch seconds; cur is the chain's wall-clock now (the same TIME the contract gates on).
  const lock = Number(G("lk") || 0), deadline = Number(G("dl") || 0), cur = dapp.chainNow();
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
const statusTag = (s) => ({ open: '<span class="b ok">' + window.t("bet.tagOpen", "🟢 open") + '</span>', locked: '<span class="b pend">' + window.t("bet.tagLocked", "🔒 locked") + '</span>',
  resolved: '<span class="b ok">' + window.t("bet.tagResolved", "✅ resolved") + '</span>', void: '<span class="b void">' + window.t("bet.tagVoid", "↩ void") + '</span>' }[s]);
function statusText(mk) {
  if (mk.voided) return window.t("bet.stVoided", "voided — every stake refunded 1:1");
  if (mk.resolved) return window.t("bet.stResolved", "resolved — {label} won", { label: mk.labels[mk.winner] });
  if (mk.locked) return window.t("bet.stLocked", "locked — awaiting the result") + (mk.cur >= mk.deadline + VOID_GRACE_SEC ? window.t("bet.stPastDeadline", " (past deadline — anyone can void)") : "");
  const left = mk.cur != null ? fmtLeft(mk.lock - mk.cur) : "…";
  return window.t("bet.stOpen", "open — betting closes in {left}", { left });
}

// ---- actions -------------------------------------------------------------------------------------
async function placeBet() {
  if (activeMarket == null || selOutcome == null) return alertBar(window.t("bet.pickFirst", "Pick a match and an outcome first."));
  const mk = lastSto && parseMarket(lastSto, activeMarket);
  if (!mk || mk.status !== "open") { alertBar(window.t("bet.notOpen", "This match isn't open for bets.")); render(); return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) return alertBar(window.t("bet.enterStake", "Enter a stake (NADO)."));
  await dapp.refresh();
  if (!canPay(dapp, stake, window.t("bet.thisBet", "This bet"))) { render(); return; }
  const lab = mk.labels[selOutcome];
  // prevUs lets refreshAll detect when THIS bet lands on-chain (my stake in the market grows) and clear
  // the optimistic "confirming…" line — otherwise it sticks forever.
  dapp.call("bet", [activeMarket, selOutcome], stake, window.t("bet.callBet", "bet {amt} on {lab} · match #{id}", { amt: rawToNado(stake), lab, id: activeMarket }),
            { market: activeMarket, phase: "bet", prevUs: mk.myTotal });
}
const claimMarket = (m) => dapp.call("claim", [m], null, window.t("bet.callClaim", "collect from match #{id}", { id: m }), { market: m, phase: "claim" });
const voidMarket  = (m) => dapp.call("void", [m], null, window.t("bet.callVoid", "void match #{id} (refund everyone)", { id: m }), { market: m, phase: "void" });
const resolveMarket = (m, out, lab) => dapp.call("resolve", [m, out], null, window.t("bet.callResolve", "post result: {lab} won · match #{id}", { lab, id: m }), { market: m, phase: "resolve" });

function createMarket() {
  const title = ($("cmTitle").value || "").trim();
  const labels = ($("cmLabels").value || "").split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
  const source = $("cmSource").value || "";
  const ev = ($("cmEvent").value || "").trim();
  const closeMin = parseFloat($("cmCloseMin").value) || 0, voidHrs = parseFloat($("cmVoidHrs").value) || 0;
  // resolver set: up to 3 addresses (comma/space/line separated); blank -> you resolve it yourself
  const resolvers = ($("cmResolvers").value || "").split(/[\n,\s]+/).map((s) => s.trim()).filter(Boolean).slice(0, 3);
  const thr = parseInt($("cmThreshold").value, 10) || 0;
  if (!title) return alertBar(window.t("bet.needTitle", "Give the market a title."));
  if (labels.length < 2) return alertBar(window.t("bet.needOutcomes", "List at least two outcomes (comma- or line-separated)."));
  if (closeMin <= 0) return alertBar(window.t("bet.needClose", "Betting must close in a positive number of minutes."));
  if (thr && resolvers.length && thr > resolvers.length) return alertBar(window.t("bet.thrTooHigh", "Threshold can't exceed the number of resolvers."));
  const now = dapp.chainNow();
  const lock = Math.round(now + closeMin * 60);               // betting closes closeMin minutes from now (epoch secs)
  const deadline = Math.round(lock + Math.max(voidHrs, 0.5) * 3600);   // anyone may void this long after close
  const id = randId();
  const desc = [title].concat(labels).join("\n");
  const r = resolvers.concat(["", "", ""]);
  dapp.call("create_market", [id, labels.length, lock, deadline, desc, source, ev, thr, r[0], r[1], r[2]], null,
            window.t("bet.callCreate", "list “{title}”", { title }), { market: id, phase: "create" });
}
const addSource = () => { const n = ($("srcName").value || "").trim(); if (!n) return alertBar(window.t("bet.needSource", "Enter a source name.")); dapp.call("add_source", [n], null, window.t("bet.callAddSource", "add source {n}", { n }), { phase: "src" }); };

// ---- refresh + render ----------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) lastSto = sto;
  if (lastSto) await resolveAliases([dapp.me, cfg(lastSto, "admin")].filter(Boolean));
  render();
  dapp.settleInflight(actionLanded);   // SDK retires the optimistic "confirming…" line once the action lands
  // AUTO-COLLECT (shared SDK tick, opt-out): claim any settled market that owes me, one per refresh
  if (lastSto) {
    const owed = allMarkets(lastSto).filter((m) => claimable(m) > 0);
    dapp.autoCollect(owed, (m) => claimMarket(m.id), { key: (x) => x.id });
  }
}
function selectMarket(id) {
  activeMarket = Number(id); selOutcome = null;
  notify(window.t("bet.selectPrompt", "Match #{id} — pick an outcome and place your bet.", { id }));
  render();
  try { $("activeMarket").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

function marketCard(mk) {
  const oddsRow = mk.outsHTML;
  const meta = [];
  if (mk.myTotal > 0) meta.push('<span class="b ok" style="margin-left:0">' + window.t("bet.yourBet", "your bet {amt}", { amt: rawToNado(mk.myTotal) }) + "</span>");
  meta.push(statusText(mk));
  return '<div class="mkt' + (mk.id === activeMarket ? " sel" : "") + '" data-m="' + mk.id + '">' +
    '<div class="top"><span class="ttl">' + esc(mk.title) + "</span>" + statusTag(mk.status) + "</div>" +
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

// Live match details from the source named on the market (transparency: the same free public feed the
// oracle resolves from). TheSportsDB allows browser CORS. Cached per (source,event) for the session; a
// completed fetch re-renders the open market. Best-effort — a missing/failed lookup just shows nothing.
const _evCache = {};
async function loadEventDetails(mk) {
  const el = $("mDetails");
  if (!el) return;
  if (mk.source !== "thesportsdb" || !mk.ev) { el.innerHTML = ""; return; }
  const key = mk.source + ":" + mk.ev;
  if (!(key in _evCache)) {
    _evCache[key] = null;   // in-flight: don't refetch on the next 4s tick
    try {
      const r = await fetch("https://www.thesportsdb.com/api/v1/json/3/lookupevent.php?id=" + encodeURIComponent(mk.ev));
      const d = await r.json();
      _evCache[key] = (d && d.events && d.events[0]) || false;
    } catch (e) { _evCache[key] = false; }
    if (activeMarket === mk.id && lastSto) renderActive(lastSto);   // re-render once details arrive
    return;
  }
  const e = _evCache[key];
  if (e == null) return;                     // still loading
  if (e === false) { el.innerHTML = '<span class="dim">match details unavailable from ' + esc(mk.source) + "</span>"; return; }
  const bits = [];
  if (e.strEvent) bits.push("<b>" + esc(e.strEvent) + "</b>");
  if (e.strTimestamp) { const dt = new Date(e.strTimestamp + (/[zZ]|[+-]\d\d:?\d\d$/.test(e.strTimestamp) ? "" : "Z")); if (!isNaN(dt)) bits.push("🗓 " + dt.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })); }
  if (e.strLeague) bits.push("🏆 " + esc(e.strLeague) + (e.strSport ? " (" + esc(e.strSport) + ")" : ""));
  const hs = e.intHomeScore, as = e.intAwayScore, st = (e.strStatus || "").trim();
  if (hs != null && hs !== "" && as != null && as !== "") bits.push('<b class="under">' + esc(hs) + "–" + esc(as) + "</b>" + (st && !/finished|ft/i.test(st) ? " " + esc(st) : ""));
  else if (st && !/not started|ns/i.test(st)) bits.push(esc(st));
  el.innerHTML = bits.join(" · ");
}

function render() {
  const sto = lastSto;
  const signedIn = renderWallet(dapp);
  gate({ bankroll: signedIn });
  if (!sto) { $("marketsList").innerHTML = '<span class="dim">' + window.t("bet.connecting", "Connecting to the chain…") + '</span>'; return; }
  dapp.reflectUrl("market", activeMarket);

  // markets list — open first (by soonest close), then locked, then settled. Filtered + capped so a board of
  // thousands never builds thousands of DOM nodes: we sort, apply the search/filter, then render only a slice.
  const mkts = allMarkets(sto);
  const rank = { open: 0, locked: 1, resolved: 2, void: 3 };
  mkts.sort((a, b) => (rank[a.status] - rank[b.status]) || (a.lock - b.lock) || (b.id - a.id));
  const visible = visibleMarkets(mkts);
  const slice = visible.slice(0, shownN);
  for (const mk of slice) mk.outsHTML = outcomesHTML(mk);   // odds HTML only for the cards we actually render
  const ml = $("marketsList");
  if (!visible.length) {
    ml.innerHTML = '<span class="dim">' + (mkts.length
      ? window.t("bet.noMatchZero", "No matches match your search/filter.")
      : window.t("bet.noMatches", "No matches listed yet") + (signedIn ? window.t("bet.noMatchesCreate", " — create one below.") : window.t("bet.noMatchesSoon", ", check back soon."))) + "</span>";
  } else {
    let html = slice.map(marketCard).join("");
    if (visible.length > slice.length)
      html += '<button id="mktMore" class="ghost" style="width:100%;margin-top:8px">'
        + window.t("bet.showMore", "Show more ({n} more)", { n: visible.length - slice.length }) + "</button>";
    ml.innerHTML = html;
  }
  $("mktCount").textContent = mkts.length
    ? window.t("bet.countShown", "Showing {shown} of {total} matches", { shown: slice.length, total: visible.length })
      + (visible.length !== mkts.length ? window.t("bet.countFiltered", " (filtered from {all})", { all: mkts.length }) : "")
    : "";

  // my bets
  const mine = mkts.filter((m) => m.myTotal > 0);
  gate({ mybets: signedIn && mine.length > 0 });
  if (mine.length) $("myBetsList").innerHTML = mine.map((mk) => {
    const c = claimable(mk);
    let tag = statusText(mk);
    if (c > 0) tag = '<span class="b ok">' + window.t("bet.toCollect", "💰 {amt} to collect", { amt: rawToNado(c) }) + "</span>";
    else if (mk.claimed) tag = '<span class="b dimb">' + window.t("bet.collectedTag", "collected ✓") + "</span>";
    return '<div class="pos" data-m="' + mk.id + '" style="cursor:pointer"><span>' + esc(mk.title) +
      ' <span class="dim">· ' + rawToNado(mk.myTotal) + " staked</span></span><span>" + tag + "</span></div>";
  }).join("");
  $("myBetsList").querySelectorAll(".pos").forEach((el) => el.onclick = () => selectMarket(el.dataset.m));

  // sources + oracle panel
  const srcs = sourcesOf(sto);
  $("sourcesList").innerHTML = srcs.length ? srcs.map((s) => '<span class="b dimb" style="margin:0 4px 4px 0;display:inline-block">' + esc(s) + "</span>").join("")
    : '<span class="dim">' + window.t("bet.noSources", "none configured yet") + "</span>";
  const admin = isAdmin(sto);
  gate({ oraclePanel: signedIn });   // creating a market is PERMISSIONLESS — anyone signed in can list one
  if (signedIn) {
    // source is optional: pick a registered public source (auto-resolvable) or leave it self-resolved
    $("cmSource").innerHTML = '<option value="">' + esc(window.t("bet.sourceNone", "— none / I'll resolve it —")) + '</option>'
      + srcs.map((s) => '<option>' + esc(s) + "</option>").join("");
    gate({ adminCfg: admin });   // add-source is protocol config, admin only
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
  $("mSource").textContent = mk.source ? (mk.source + (mk.ev ? window.t("bet.eventTag", " · event {ev}", { ev: mk.ev }) : "")) : "—";
  loadEventDetails(mk);   // pull kickoff / league / status / score from the source (best-effort)
  shareInvite("market", mk.id, window.t("bet.shareMatch", "Bet on {title} on NADO:", { title: mk.title }), 180);

  // outcome picker (only clickable while open)
  $("mOutcomes").outerHTML = outcomesHTML(mk, { select: mk.status === "open", click: mk.status === "open" }).replace('class="outs"', 'class="outs" id="mOutcomes"');
  $("mOutcomes").querySelectorAll(".out[data-click]").forEach((el) => el.onclick = () => { selOutcome = Number(el.dataset.o); render(); });

  // bet builder
  const canBet = mk.status === "open";
  gate({ betBuilder: canBet });
  if (canBet) {
    dapp.syncStakeSlider(dapp.exec);   // keep the % slider in step with your live playable balance
    const stake = nadoToRaw($("stakeAmt").value);
    let prev = "";
    if (selOutcome != null && stake) {
      const np = mk.pools[selOutcome] + Number(stake), nt = mk.total + Number(stake);
      const win = Math.floor(Number(stake) * nt / np);
      prev = window.t("bet.payoutPreview", "If {lab} wins and no one else bets, ≈ {win} NADO ({x}×). Live odds move as others bet.", { lab: esc(mk.labels[selOutcome]), win: rawToNado(win), x: (win / Number(stake)).toFixed(2) });
    } else if (selOutcome == null) prev = window.t("bet.pickAbove", "Pick an outcome above.");
    $("payoutPreview").innerHTML = prev;
    const confirming = dapp.busy("bet", "market", mk.id);
    const ok = selOutcome != null && stake && dapp.me && dapp.exec >= stake && !confirming;
    $("btnBet").disabled = !ok;
    $("btnBet").classList.toggle("pulse", !!ok);
    $("btnBet").textContent = confirming ? window.t("bet.btnConfirming", "⏳ Bet placed — confirming…")
      : (selOutcome != null ? window.t("bet.btnBetOn", "Place bet on {lab}", { lab: mk.labels[selOutcome] }) : window.t("bet.btnBet", "Place bet"));
    const hint = $("betHint");
    let h = "";
    if (!dapp.me) h = window.t("bet.signInToBet", "Sign in to bet.");
    else if (selOutcome != null && stake && dapp.exec < stake) h = window.t("bet.notEnough", "Not enough playable NADO — deposit at least {amt} more above.", { amt: rawToNado(stake - dapp.exec) });
    hint.textContent = h; hint.classList.toggle("hidden", !h);
  }

  // my positions in this match
  const posEl = $("myPositions");
  const held = mk.myStakes.map((s, i) => ({ s, i })).filter((x) => x.s > 0);
  if (held.length) {
    posEl.innerHTML = '<div class="divlabel">' + window.t("bet.yourBetsHere", "Your bets on this match") + '</div>' + held.map((x) => {
      let tail = "";
      if (mk.resolved) tail = x.i === mk.winner ? '<span class="b ok">' + window.t("bet.won", "won") + '</span>' : '<span class="b dimb">' + window.t("bet.lost", "lost") + '</span>';
      else if (mk.voided) tail = '<span class="b void">' + window.t("bet.refund", "refund") + '</span>';
      return '<div class="pos"><span>' + esc(mk.labels[x.i]) + " · " + rawToNado(x.s) + " NADO</span><span>" + tail + "</span></div>";
    }).join("");
  } else posEl.innerHTML = "";

  // claim
  const c = claimable(mk), cr = $("claimRow"); cr.innerHTML = "";
  if (c > 0) {
    const b = document.createElement("button"); b.className = "primary pulse"; b.style.width = "100%";
    b.textContent = mk.voided ? window.t("bet.reclaim", "↩ Reclaim {amt} NADO", { amt: rawToNado(c) }) : window.t("bet.collect", "💰 Collect {amt} NADO", { amt: rawToNado(c) });
    b.onclick = () => claimMarket(mk.id); cr.appendChild(b);
  } else if (mk.claimed && mk.myTotal > 0) {
    cr.innerHTML = '<div class="small dim">' + window.t("bet.alreadyCollected", "You already collected from this match.") + '</div>';
  }

  // resolve/void controls — shown to anyone who may resolve THIS market (its named resolvers, or the
  // admin for a legacy market)
  const canRes = canResolveMkt(sto, mk.id);
  gate({ oracleControls: canRes && (mk.status === "locked" || mk.status === "open") });
  if (canRes && (mk.status === "locked" || mk.status === "open")) {
    const canResolve = mk.status === "locked";
    $("resolveOutcomes").innerHTML = mk.labels.map((lab, i) =>
      '<button class="out" data-o="' + i + '"' + (canResolve ? "" : " disabled") + '><div class="lab">' + window.t("bet.outcomeWon", "{lab} won", { lab: esc(lab) }) + "</div></button>").join("");
    $("resolveOutcomes").querySelectorAll("button[data-o]").forEach((el) => el.onclick = () => resolveMarket(mk.id, Number(el.dataset.o), mk.labels[el.dataset.o]));
    $("btnVoid").onclick = () => voidMarket(mk.id);
  }
}

// ---- boot ----------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  dapp.wireAutoCollect();   // shared "Auto-collect my winnings" opt-out toggle (#autoCollect)
  stickyInputs(dapp, ["stakeAmt", "bankAmt", "cmTitle", "cmLabels", "cmEvent", "cmCloseMin", "cmVoidHrs"]);
  $("btnBet").onclick = placeBet;
  // shared SDK stake slider: the stake input + a 0–100% slider + Max, bound to your playable balance
  dapp.wireStakeSlider(() => dapp.exec, () => { if (lastSto) renderActive(lastSto); });
  $("btnCreate").onclick = createMarket;
  if ($("btnAddSource")) $("btnAddSource").onclick = addSource;
  $("btnShare").onclick = () => share(base() + "/?market=" + activeMarket, window.t("bet.shareThis", "Bet on this match on NADO:"), $("btnShare"));
  // ONE delegated handler for the whole (capped) list — a card click selects, "Show more" grows the slice.
  // Delegation means we don't (re)bind a listener per card, so cost stays flat as the board grows.
  $("marketsList").addEventListener("click", (e) => {
    if (e.target.closest("#mktMore")) { shownN += PAGE_SIZE; render(); return; }
    const card = e.target.closest(".mkt");
    if (card) selectMarket(card.dataset.m);
  });
  // search + filter reset the slice and re-render off the last-known storage (no chain round-trip)
  const relist = () => { shownN = PAGE_SIZE; if (lastSto) render(); };
  $("mktSearch").addEventListener("input", (e) => { searchQ = e.target.value; relist(); });
  $("mktFilter").addEventListener("change", (e) => { mktFilter = e.target.value; relist(); });
}
dapp.doneLabels(DONE);
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.market != null) activeMarket = pend.market;
  dapp.showReturn(pend, ok, err, CONFIRMING);   // SDK sets #status + tracks the optimistic phase
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("bet.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR();
  const q = new URLSearchParams(location.search).get("market");
  if (q && activeMarket == null) activeMarket = parseInt(q, 10);
  render(); refreshAll();
  setInterval(refreshAll, 4000);
}
boot();

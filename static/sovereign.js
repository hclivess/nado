// sovereign.js — NADO Sovereign client: the persistent nation-war world. Built on the shared SDK
// (nadodapp.js) for the wallet/call/storage/block-hash primitives, and on the tested rules engine
// (sovereign-engine.js) for the whole economy + combat. This module reads the global action log, REPLAYS
// it through the engine to derive the live world (my nation + every rival), and turns dashboard taps into
// ply-bound act() calls. Practice mode runs the identical engine over a local sandbox of bot nations.
import { NadoDapp, $, _m, base, notify, alertBar, disp, share, wireWallet, renderWallet, stickyInputs,
         orderCards, resolveAliases, renderTopScores, uiPrompt, uiConfirm } from "./nadodapp.js";
import * as E from "./sovereign-engine.js";
import { ART } from "./sovereign-art.js";
import { Practice, prand } from "./practice.js";

const CID = "sovereign";                              // fixed-name deploy (like the faucet); set at deploy
const dapp = new NadoDapp({ cid: CID, app: "Sovereign" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("sov." + k, d, v) : d;
const MAPS = ["la", "lc", "le", "lt"];
const fmt = (x) => { x = Math.floor(x); return x >= 1e9 ? (x / 1e9).toFixed(1) + "G" : x >= 1e6 ? (x / 1e6).toFixed(1) + "M" : x >= 1e3 ? (x / 1e3).toFixed(1) + "k" : "" + x; };
const fmtInt = (x) => String(Math.floor(x)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");   // full number, thousands-grouped — NEVER abbreviated (turn counter)
const sign = (x) => (x >= 0 ? "+" : "") + (Math.abs(x) >= 100 ? Math.round(x) : x.toFixed(1));

let world = {}, me = null, mc = 0, tab = "build", target = null, atkKind = "plunder";
let myLastCur = 0, nowCur = 0;                            // my last on-chain touch + the live cursor (for the turn clock)
const BLOCK_SECS = 6;
let comp = { soldier: 1, tank: 1, fighter: 1, bunker: 0, mech: 1 };
let practice = null;                                  // {seed, log, bots} when in the offline sandbox
const prac = new Practice("sovereign");

// ---- seed for a raid roll: the block hash at the entry's future seed height (fast provisional is safe —
// a reorg just replays the raid visibly, like every other public on-chain randomness) ------------------
function seedOf(rh) { const h = dapp.bh(rh); return h ? BigInt("0x" + h) : null; }

// ---- read the global log + replay it into the world --------------------------------------------------
function logFromSto(sto) {
  const la = _m(sto, "la"), lc = _m(sto, "lc"), le = _m(sto, "le"), lt = _m(sto, "lt");
  mc = Object.keys(la).length ? Math.max(...Object.keys(la).map(Number)) + 1 : 0;
  const log = [];
  for (let i = 0; i < mc; i++) {
    if (!la[String(i)]) { log.gap = true; break; }    // provisional read raced the append — retry next poll
    const rh = lc[String(i)] || 0;                    // lc = submission cursor + GAP(2); settle uses the submission cursor
    log.push({ actor: la[String(i)], cursor: rh - 2, rh, enc: le[String(i)] || 0, target: lt[String(i)] || 0 });
  }
  return log;
}
async function refresh() {
  if (practice) return renderPractice();
  await dapp.refresh();          // keep dapp.cursor advancing (lazy production settles forward) + balances live
  const sto = await dapp.storage({ append: MAPS });
  if (!sto) return;
  const log = logFromSto(sto);
  // fetch the seed blocks every past raid needs (fast/provisional — public randomness)
  const need = [];
  for (const e of log) if (e.target) { const rh = e.rh; if (rh && dapp.cursor != null && dapp.cursor >= rh && dapp.bh(rh) === undefined) need.push(rh); }
  if (need.length) await dapp.blockHashes(need.slice(0, 60), { fast: true });
  const now = dapp.cursor != null ? dapp.cursor : (log.length ? log[log.length - 1].rh : 0);
  nowCur = now;
  myLastCur = dapp.me ? log.reduce((m, e) => e.actor === dapp.me && e.cursor > m ? e.cursor : m, 0) : 0;
  const rr = E.replayWorld(log, now, seedOf);
  world = rr.world;
  me = dapp.me ? world[dapp.me] : null;
  showFeed(rr.feed);          // toast any new raid outcome involving me (I raided, or I was raided)
  render();
}

// ---- action feedback (beginner-friendly): a clear toast for every raid/strike/spy outcome ---------------
let feedSeen = -1;            // -1 = not yet initialised; on first load we seed the marker and skip history
const troops = (m) => Object.values(m || {}).reduce((s, v) => s + (v || 0), 0);
function lootStr(loot) {
  const p = [];
  if (loot.money) p.push("+" + fmt(Math.abs(loot.money)) + "💰");
  if (loot.food) p.push("+" + fmt(Math.abs(loot.food)) + "🌾");
  if (loot.energy) p.push("+" + fmt(Math.abs(loot.energy)) + "⚡");
  if (loot.tech) p.push("+" + fmt(Math.abs(loot.tech)) + "🔬");
  return p.length ? " " + p.join(" ") : "";
}
function showFeed(feed) {
  const meId = practice ? "you" : dapp.me;
  if (!feed || !meId) { feedSeen = feed ? feed.length : 0; return; }
  if (feedSeen < 0) { feedSeen = feed.length; return; }      // first render: don't replay historical toasts
  const fresh = feed.slice(feedSeen); feedSeen = feed.length;
  for (let i = fresh.length - 1; i >= 0; i--) {              // newest outcome involving me wins the toast
    const f = fresh[i];
    if (f.actor === meId) return toastMine(f);
    if (f.target === meId) return toastVictim(f);
  }
}
function toastMine(f) {
  const who = practice ? f.target : disp(f.target), r = f.rep;
  if (f.op === E.OP.attack) return r.win
    ? alertBar("⚔ " + T("raidWon", "Raid on {who}: VICTORY!", { who }) + " +" + fmt(r.lootLand) + " km²" + lootStr(r.loot) + " · −" + fmt(troops(r.atkLoss)) + " 🪖 · +" + fmt(r.xp) + " XP", null, null, { tone: "ok" })
    : alertBar("⚔ " + T("raidLost", "Raid on {who}: defeat — lost {t} troops.", { who, t: fmt(troops(r.atkLoss)) }), null, null, { tone: "warn" });
  if (f.op === E.OP.tactical) return alertBar("🎯 " + (r.win ? T("tacHit", "Strike on {who} landed — {h} destroyed.", { who, h: fmt(r.hit) }) : T("tacMiss", "Strike on {who} missed.", { who })), null, null, { tone: r.win ? "ok" : "warn" });
  if (f.op === E.OP.launch) return alertBar("🚀 " + T("misHit", "Missiles struck {who}.", { who }), null, null, { tone: "ok" });
  if (f.op === E.OP.spy) return alertBar("🕵 " + (r.win ? T("spyWon", "Spy op on {who} succeeded.", { who }) : T("spyLost", "Spy op on {who} failed — lost {l} agents.", { who, l: fmt(r.lost) })), null, null, { tone: r.win ? "ok" : "warn" });
}
function toastVictim(f) {
  const who = practice ? f.actor : disp(f.actor), r = f.rep;
  if (f.op === E.OP.attack) return r.win
    ? alertBar("🛡 " + T("raidedLost", "{who} raided you: −{land} km², −{t} troops.", { who, land: fmt(r.lootLand), t: fmt(troops(r.defLoss)) }), null, null, { tone: "warn" })
    : alertBar("🛡 " + T("raidedHeld", "You repelled {who}'s raid!", { who }), null, null, { tone: "ok" });
  if (f.op === E.OP.tactical) return alertBar("🎯 " + T("tacVictim", "{who} hit you with a tactical strike.", { who }), null, null, { tone: "warn" });
  if (f.op === E.OP.launch) return alertBar("🚀 " + T("misVictim", "{who} struck you with missiles.", { who }), null, null, { tone: "warn" });
  if (f.op === E.OP.spy) return alertBar("🕵 " + T("spyVictim", "{who} ran a spy op against you.", { who }), null, null, { tone: "warn" });
}

// ---- submit an action (ply-bound to the current log length) ------------------------------------------
function act(enc, tgt, label) {
  if (practice) return pracAct(enc, tgt);
  if (!dapp.me) return dapp.signIn();
  dapp.call("act", [enc, tgt || 0, mc], null, label, { phase: "act" });
}
const found = () => act(E.encAction(E.OP.found), 0, T("cfFound", "found your nation"));

// ---- practice (offline): a local log over bot nations, same engine -----------------------------------
function pracSeedOf(rh) { const r = prand(practice.seed + ":seed:" + rh); return BigInt(Math.floor(r() * 1e15)) * 1000003n + 7n; }
function pracReplay() {
  const rr = E.replayWorld(practice.log, practice.now, pracSeedOf); world = rr.world; me = world.you || null;
  showFeed(rr.feed);
}
function pracAct(enc, tgt) {
  practice.log.push({ actor: "you", cursor: practice.now, rh: practice.now, enc, target: tgt || 0 });
  practice.now += E.TURN_BLOCKS;                       // each of your actions advances the world a turn
  practice.bots.forEach((b, i) => { if (Math.random() < 0.5) practice.log.push({ actor: b, cursor: practice.now, rh: practice.now, enc: botMove(world[b], i), target: 0 }); });
  practice.now += E.TURN_BLOCKS * 3;
  prac.saveRun(practice); pracReplay(); renderPractice();
}
function botMove(n, i) {
  if (!n) return E.encAction(E.OP.found);
  // a simple builder bot: keep raising villages/barracks/labs, colonize when it can
  if (n.bld.unbuilt / Math.max(1, n.land) <= 0.5 && Math.random() < 0.3) return E.encAction(E.OP.colonize);
  const pick = ["village", "barracks", "farm", "lab", "market", "plant"][Math.floor(Math.random() * 6)];
  return E.encAction(E.OP.build, E.BUILDABLE.indexOf(pick), Math.max(1, Math.floor(E.buildsPerTurn(n) / 2)));
}
function startPractice() {
  const seed = "sov-" + Math.random().toString(36).slice(2, 9);
  const bots = ["Ferralis", "Kaltberg", "Osmara", "Venturia", "Drakov"];
  const log = [{ actor: "you", cursor: 0, rh: 0, enc: E.encAction(E.OP.found), target: 0 }];
  bots.forEach((b) => log.push({ actor: b, cursor: 0, rh: 0, enc: E.encAction(E.OP.found), target: 0 }));
  // bot head start — a STATELESS deterministic build pattern (no per-turn replay; keeps it O(n))
  const pattern = ["village", "village", "farm", "barracks", "market", "plant", "lab", "base", "factory", "builder"];
  for (let t = 3; t < 180; t += 3) bots.forEach((b, i) => {
    const cur = t * E.TURN_BLOCKS;
    if ((t / 3 + i) % 5 === 0) { log.push({ actor: b, cursor: cur, rh: cur, enc: E.encAction(E.OP.colonize), target: 0 }); return; }
    const what = pattern[(Math.floor(t / 3) + i) % pattern.length];
    log.push({ actor: b, cursor: cur, rh: cur, enc: E.encAction(E.OP.build, E.BUILDABLE.indexOf(what), 10), target: 0 });
  });
  practice = { seed, bots, log, now: 180 * E.TURN_BLOCKS };
  prac.saveRun(practice); pracReplay(); render();
}
function pracSeedOfFor(seed) { return (rh) => { const r = prand(seed + ":seed:" + rh); return BigInt(Math.floor(r() * 1e15)) * 1000003n + 7n; }; }
function exitPractice() { practice = null; prac.clearRun(); refresh(); }

// ---- rendering ---------------------------------------------------------------------------------------
const gicon = (k) => '<span class="gi">' + (ART[k] || "") + "</span>";
function ratesLine(n) {
  const p = E.production(n), pay = E.upkeep(n);
  const r = (lab, v, unit) => '<span class="rate"><b>' + lab + '</b> ' + sign(v) + (unit || "") + "/t</span>";
  return r("💰", p.money - pay) + r("🌾", p.food) + r("⚡", p.energy) + r("🔬", p.tech) + r("👥", p.grow, "");
}
function nationHead(n) {
  return '<div class="stats">'
    + '<span class="stat">🗺 <b>' + fmt(n.land) + "</b> km²</span>"
    + '<span class="stat">👥 <b>' + fmt(n.people) + "</b></span>"
    + '<span class="stat">💰 <b>' + fmt(n.money) + "</b></span>"
    + '<span class="stat">🌾 <b>' + fmt(n.food) + "</b></span>"
    + '<span class="stat">⚡ <b>' + fmt(n.energy) + "</b></span>"
    + '<span class="stat">😊 <b>' + Math.round(n.joy) + "%</b></span>"
    + '<span class="stat">🏛 <b>' + T("gov_" + n.gov, E.GOV[n.gov].k) + "</b></span>"
    + '<span class="stat prestige">⭐ <b>' + fmt(E.prestige(n)) + "</b></span></div>"
    + '<div class="stats mt">'
    + '<span class="stat">🎖 <b>' + T("rank_" + E.RANKS[E.rankOf(n)].k, E.RANKS[E.rankOf(n)].k) + "</b> · " + fmt(n.exp) + " XP</span>"
    + '<span class="stat">🛡 ' + T("ready", "readiness") + " <b>" + Math.round(n.ready) + "%</b></span>"
    + '<span class="stat">⏳ ' + T("turnN", "turn") + " <b>" + fmtInt(n.tick) + "</b>" + turnClock() + "</span>"
    + (n.generals && n.generals.length ? '<span class="stat">⭐ ' + n.generals.map((gn) => T("gen_" + gn.type, E.GENERALS[gn.type].k) + " " + genLvl(gn)).join(", ") + "</span>" : "")
    + (n.ally ? '<span class="stat">🤝 ' + T("alliance", "alliance") + " #" + n.ally + "</span>" : "")
    + (n.ufoExplore > 0 ? '<span class="stat">👽 ' + Math.round(n.ufoExplore) + "%</span>" : "")
    + "</div>"
    + '<div class="rates">' + ratesLine(n) + "</div>"
    + (n.lastEvent ? '<div class="evline">📣 ' + T("ev_" + n.lastEvent, n.lastEvent) + "</div>" : "");
}
function genLvl(gn) { return "L" + (E.genLevel ? E.genLevel(gn.xp) : 0); }
// how long until the next economy turn ticks (production settles every TURN_BLOCKS blocks from your last touch)
function turnClock() {
  if (practice || !myLastCur || !nowCur || nowCur < myLastCur) return "";
  const into = (nowCur - myLastCur) % E.TURN_BLOCKS;
  const left = (E.TURN_BLOCKS - into) % E.TURN_BLOCKS || E.TURN_BLOCKS;
  const secs = left * BLOCK_SECS;
  const t = secs >= 60 ? Math.floor(secs / 60) + "m" + (secs % 60 ? (secs % 60) + "s" : "") : secs + "s";
  return ' <span class="dim">· ' + T("nextTurnIn", "next in ~{t}", { t }) + "</span>";
}

const TABS = ["build", "army", "arsenal", "market", "tech", "gov", "diplo", "world"];
function render() {
  const dash = $("dash"); if (!dash) return;
  renderWallet(dapp);          // reflect sign-in state into #who / #l1bal / btnSignIn (was imported but never called)
  if (practice) { $("pracBanner").classList.remove("hidden"); } else if ($("pracBanner")) $("pracBanner").classList.add("hidden");
  if (!me) {
    dash.innerHTML = '<div class="empty">' + (dapp.me || practice
      ? T("foundPrompt", "You don't rule a nation yet. Found one — it starts at 40 km² and grows every turn.")
      : T("signPrompt", "Sign in, then found your nation to enter the world.")) + "</div>";
    $("foundRow").classList.remove("hidden");
    $("tabs").innerHTML = ""; $("panel").innerHTML = ""; renderWorld();
    return;
  }
  $("foundRow").classList.add("hidden");
  dash.innerHTML = nationHead(me);
  $("tabs").innerHTML = TABS.map((t) => '<button class="tab' + (t === tab ? " on" : "") + '" data-tab="' + t + '">' + T("tab_" + t, t) + "</button>").join("");
  $("tabs").querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { raidOwner = null; tab = b.dataset.tab; render(); });
  renderPanel();
}
function renderPanel() {
  const el = $("panel"); if (!el || !me) return;
  if (tab === "build") return renderBuild(el);
  if (tab === "army") return renderArmy(el);
  if (tab === "arsenal") return renderArsenal(el);
  if (tab === "market") return renderMarket(el);
  if (tab === "tech") return renderTech(el);
  if (tab === "gov") return renderGov(el);
  if (tab === "diplo") return renderDiplo(el);
  if (tab === "world") return renderWorld(el);
}
function tile(inner, cls, data) { return '<div class="tile ' + (cls || "") + '" ' + (data || "") + ">" + inner + "</div>"; }

// SDK-modal numeric prompt (replaces the browser's blocking prompt()); returns 0 on cancel/empty.
async function askNum(title, def, note) {
  const v = await uiPrompt({ title, note, value: def, placeholder: String(def) });
  if (v == null) return 0;
  return Math.max(0, parseInt(String(v).replace(/[^0-9]/g, "") || "0", 10) || 0);
}
function renderBuild(el) {
  const per = E.buildsPerTurn(me), left = E.buildsLeft(me), n = me;
  const unit = E.buildCost(n, 1);          // money for the NEXT building (same for every type; rises as you grow)
  let h = '<p class="hint">' + T("buildHint2", "Up to {per} buildings PER TURN (shared across all types). Cost rises as you grow. Colonize for more land — but not while over half sits empty.", { per }) + "</p>";
  h += '<div class="colonizeRow"><button class="primary colonizeBtn" id="btnColonize">🧭 ' + T("colonize", "Colonize — claim more land") + ' · 🟩 ' + fmt(n.bld.unbuilt) + "</button></div>";
  h += '<div class="chips">'
    + (practice ? "" : '<span class="landchip">🏗 ' + T("buildsLeft", "builds left this turn") + " <b>" + left + "/" + per + "</b></span>")
    + "</div>";
  h += '<div class="grid">' + E.BUILDABLE.map((k) => tile(
      gicon(k) + '<div class="tn">' + T("b_" + k, E.B[k].k) + '</div><div class="tc">' + n.bld[k] + "</div>"
      + '<div class="tx dim">' + T("bx_" + k, E.B[k].txt) + '</div><div class="tcost">💰 ' + fmt(unit) + " " + T("each", "each") + "</div>",
      "b-" + k + (n.money >= unit && n.bld.unbuilt > 0 && left > 0 ? " ready" : ""), 'data-build="' + k + '"')).join("") + "</div>";
  el.innerHTML = h;
  $("btnColonize").onclick = () => act(E.encAction(E.OP.colonize), 0, T("cfColonize", "colonize"));
  el.querySelectorAll("[data-build]").forEach((d) => d.onclick = () => promptCount(d.dataset.build, per));
}
async function promptCount(type, per) {
  const max = Math.min(E.buildsLeft(me), me.bld.unbuilt);
  if (E.buildsLeft(me) < 1) return notify(T("noBuildsLeft", "No builds left this turn — wait for the next turn."));
  if (max < 1) return notify(T("noOpenLand", "No open land — colonize first."));
  const each = E.buildCost(me, 1);
  const q = Math.min(max, await askNum(T("howMany", "Build how many {t}? (max {m})", { t: T("b_" + type, E.B[type].k), m: max }), max,
    T("costEach", "💰 {c} each · you have {have}", { c: fmt(each), have: fmt(me.money) })));
  if (!q) return;
  if (me.money < E.buildCost(me, q)) return notify(T("tooPoor", "Not enough money for that."));
  act(E.encAction(E.OP.build, E.BUILDABLE.indexOf(type), q), 0, "build " + q + " " + type);
}
function renderArmy(el) {
  const n = me;
  let h = '<p class="hint">' + T("armyHint", "Soldiers train in barracks every turn on their own. Machine units cost factory components + money. Agents run spy ops (coming soon).") + "</p>";
  const recruitCost = (k) => k === "agent" ? E.U[k].pay * 30 : E.U[k].pay * 20;   // mirrors engine recruit()
  h += '<div class="grid">' + E.UKEYS.map((k) => { const u = E.U[k]; const machine = k !== "soldier" && k !== "agent";
    const costLine = k === "soldier" ? T("fromBarracks", "auto from barracks")
      : "💰 " + fmt(recruitCost(k)) + (machine ? " +1 🔧" : "") + " " + T("each", "each");
    return tile(gicon(k) + '<div class="tn">' + T("u_" + k, u.k) + '</div><div class="tc">' + fmt(n.units[k]) + "</div>"
      + '<div class="tx dim">⚔' + u.a + " 🛡" + u.d + " · 💰" + u.pay + "/t</div>"
      + '<div class="tcost">' + costLine + "</div>",
      "u-" + k, 'data-unit="' + k + '"'); }).join("") + "</div>";
  h += '<p class="hint mt">' + T("compHave", "Components in stock: {c}", { c: Math.floor(n.comps) }) + "</p>";
  el.innerHTML = h;
  el.querySelectorAll("[data-unit]").forEach((d) => d.onclick = async () => {
    const k = d.dataset.unit;
    if (k === "soldier") return notify(T("soldierAuto", "Soldiers come from barracks automatically — build more barracks."));
    const each = recruitCost(k);
    const q = await askNum(T("recruitHow", "Recruit how many {u}?", { u: T("u_" + k, E.U[k].k) }), 10,
      T("costEach", "💰 {c} each · you have {have}", { c: fmt(each), have: fmt(me.money) }));
    if (!q) return;
    act(E.encAction(E.OP.recruit, E.UKEYS.indexOf(k), q), 0, "recruit " + q + " " + k);
  });
}
function renderTech(el) {
  const n = me;
  let h = '<p class="hint">' + T("techHint", "Laboratories generate research points. Spend them to raise a technology a level — each level is a permanent production multiplier.", {}) + '</p><div class="techpts">🔬 ' + T("points", "points") + " <b>" + Math.floor(n.techPts) + "</b></div>";
  h += '<div class="grid">' + E.TKEYS.map((k) => { const tk = E.TECH[k], lv = n.tech[k], cost = E.TECH_COST(lv);
    return tile(gicon("lab") + '<div class="tn">' + T("t_" + k, tk.k) + '</div><div class="tc">' + T("lvl", "lvl") + " " + lv + "/" + tk.cap + "</div>"
      + '<div class="tx dim">' + T("tx_" + k, tk.txt) + '</div><div class="tcost">' + (lv >= tk.cap ? T("maxed", "maxed") : cost + " 🔬") + "</div>",
      "t-" + k + (n.techPts >= cost && lv < tk.cap ? " ready" : ""), 'data-tech="' + k + '"'); }).join("") + "</div>";
  el.innerHTML = h;
  el.querySelectorAll("[data-tech]").forEach((d) => d.onclick = () => {
    const k = d.dataset.tech;
    if (me.tech[k] >= E.TECH[k].cap) return;
    if (me.techPts < E.TECH_COST(me.tech[k])) return notify(T("needPts", "Not enough research points yet."));
    act(E.encAction(E.OP.research, E.TKEYS.indexOf(k)), 0, "research " + k);
  });
}
function renderGov(el) {
  const n = me;
  let h = '<p class="hint">' + T("govHint", "Your government tilts every part of the economy and war. Changing it is a REVOLUTION — it costs a slice of everything (painless only from Anarchy).") + "</p>";
  h += '<div class="grid">' + E.GKEYS.map((k) => { const gv = E.GOV[k], locked = (gv.day || 0) > n.day, cur = k === n.gov;
    return tile('<div class="tn">' + T("gov_" + k, gv.k) + (cur ? " ✓" : "") + '</div><div class="tx dim">' + T("govx_" + k, gv.txt) + "</div>"
      + (locked ? '<div class="tcost">' + T("unlockDay", "day {d}", { d: gv.day }) + "</div>" : ""),
      "g-" + k + (cur ? " on" : "") + (locked ? " locked" : ""), locked || cur ? "" : 'data-gov="' + k + '"'); }).join("") + "</div>";
  el.innerHTML = h;
  el.querySelectorAll("[data-gov]").forEach((d) => d.onclick = async () => {
    const k = d.dataset.gov;
    if (!await uiConfirm({ title: T("confirmRevolt", "Revolt to {g}? This destroys part of your nation.", { g: T("gov_" + k, E.GOV[k].k) }),
      warn: T("revoltWarn", "A revolution taxes people, money, buildings and army."), danger: true, confirmText: T("revoltGo", "Revolt") })) return;
    act(E.encAction(E.OP.revolt, E.GKEYS.indexOf(k)), 0, "revolt to " + k);
  });
}
function renderWorld(el) {
  el = el || $("panel"); if (!el) return;
  const rows = Object.values(world).filter((n) => n && (!me || n.owner !== me.owner))
    .map((n) => ({ n, p: E.prestige(n) })).sort((a, b) => b.p - a.p).slice(0, 40);
  const mine = me ? E.prestige(me) : 0;
  let h = '<p class="hint">' + T("worldHint", "Every nation in the world, by prestige. Raid one for land and loot — young or tiny nations are shielded.") + "</p>";
  if (me) h += '<div class="myrank">' + T("yourPrestige", "Your prestige") + ": <b>⭐ " + fmt(mine) + "</b></div>";
  h += '<table class="wtab"><thead><tr><th>#</th><th>' + T("nation", "Nation") + "</th><th>🗺</th><th>⭐</th><th></th></tr></thead><tbody>";
  h += rows.map((r, i) => {
    const shielded = r.n.tick < E.PROTECT_TURNS && r.p < 200;
    const nm = practice ? r.n.owner : disp(r.n.owner);
    return "<tr><td>" + (i + 1) + '</td><td class="nm">' + nm + "</td><td>" + fmt(r.n.land) + "</td><td>" + fmt(r.p) + "</td>"
      + "<td>" + (me && !shielded ? '<button class="raid" data-raid="' + r.n.owner + '">⚔ ' + T("raid", "Raid") + "</button>" : (shielded ? '<span class="dim small">🛡</span>' : "")) + "</td></tr>";
  }).join("") + "</tbody></table>";
  if (!rows.length) h += '<p class="dim">' + T("worldEmpty", "No rivals yet — be the first, and grow before others arrive.") + "</p>";
  el.innerHTML = h;
  el.querySelectorAll("[data-raid]").forEach((b) => b.onclick = () => openRaid(b.dataset.raid));
}
function renderArsenal(el) {
  const n = me;
  let h = '<p class="hint">' + T("arsenalHint", "Military bases generate research points; spend them on missiles. Advances are permanent nation-wide upgrades bought with technology points.") + '</p><div class="techpts">🚀 ' + T("rocketPts", "research") + " <b>" + Math.floor(n.rocketPts) + "</b></div>";
  h += '<h3 class="sub2">' + T("missiles", "Missiles") + "</h3><div class=\"grid\">" + E.MKEYS.map((k) => { const M = E.MISSILES[k];
    return tile(gicon("base") + '<div class="tn">' + T("m_" + k, M.k) + '</div><div class="tc">' + fmt(n.rockets[k] || 0) + "</div>"
      + '<div class="tx dim">' + T("mx_" + k, M.txt) + '</div><div class="tcost">' + M.cost + " 🚀</div>",
      "m-" + k + (n.rocketPts >= M.cost ? " ready" : ""), 'data-mis="' + k + '"'); }).join("") + "</div>";
  h += '<h3 class="sub2 mt">' + T("advances", "Advances") + '</h3><div class="techpts">🔬 <b>' + Math.floor(n.techPts) + "</b></div><div class=\"grid\">"
    + E.ADV_KEYS.filter((k) => E.ADVANCES[k].type !== "M").map((k) => { const A = E.ADVANCES[k], owned = E.hasAdv(n, k), cost = E.advCost(n, k);
      return tile('<div class="tn">' + T("adv_" + k, A.k) + (owned ? " ✓" : "") + '</div><div class="tx dim">' + T("advx_" + k, A.txt) + '</div><div class="tcost">' + (owned ? T("owned", "owned") : cost + " 🔬") + "</div>",
        "a-" + k + (owned ? " on" : n.techPts >= cost ? " ready" : ""), owned ? "" : 'data-adv="' + k + '"'); }).join("")
    + E.ADV_KEYS.filter((k) => E.ADVANCES[k].type === "M" && E.hasAdv(n, k)).map((k) => tile('<div class="tn">👽 ' + T("adv_" + k, E.ADVANCES[k].k) + ' ✓</div><div class="tx dim">' + T("advx_" + k, E.ADVANCES[k].txt) + "</div>", "a-" + k + " on")).join("") + "</div>";
  el.innerHTML = h;
  el.querySelectorAll("[data-mis]").forEach((d) => d.onclick = async () => { const k = d.dataset.mis;
    if (n.rocketPts < E.MISSILES[k].cost) return notify(T("needRocketPts", "Not enough research points."));
    const q = await askNum(T("buildHowMany", "Build how many {m}?", { m: T("m_" + k, E.MISSILES[k].k) }), 1,
      T("costEachRkt", "🚀 {c} each · you have {have}", { c: E.MISSILES[k].cost, have: Math.floor(n.rocketPts) }));
    if (q) act(E.encAction(E.OP.missile, E.MKEYS.indexOf(k), q), 0, "build " + q + " " + k); });
  el.querySelectorAll("[data-adv]").forEach((d) => d.onclick = () => { const k = d.dataset.adv;
    if (me.techPts < E.advCost(me, k)) return notify(T("needPts", "Not enough research points yet."));
    act(E.encAction(E.OP.advance, E.ADV_KEYS.indexOf(k)), 0, "research advance " + k); });
}
function renderMarket(el) {
  const n = me, items = E.MARKET_ITEMS;
  let h = '<p class="hint">' + T("marketHint", "The domestic market: buy or sell food, energy and units for money. Prices rise as your stock of an item falls; you sell to Country #0 at a discount.") + "</p>";
  h += '<table class="wtab"><thead><tr><th>' + T("good", "Good") + "</th><th>" + T("stock", "Stock") + "</th><th>" + T("buyPrice", "Buy") + "</th><th></th><th></th></tr></thead><tbody>";
  h += items.map((it) => { const have = (it === "food" || it === "energy") ? n[it] : n.units[it];
    return "<tr><td>" + T(it === "food" || it === "energy" ? it : "u_" + it, it) + "</td><td>" + fmt(have) + "</td><td>💰" + fmt(E.unitPrice(n, it)) + "</td>"
      + '<td><button class="mk" data-buy="' + it + '">' + T("buy", "Buy") + '</button></td><td><button class="mk ghost" data-sell="' + it + '">' + T("sell", "Sell") + "</button></td></tr>"; }).join("") + "</tbody></table>";
  el.innerHTML = h;
  const amt = (verb, it) => askNum(verb + " " + T(it === "food" || it === "energy" ? it : "u_" + it, it) + " — " + T("howMuch", "how much?"), 100,
    T("unitPriceNote", "💰 {p} per unit · you have {have}", { p: fmt(E.unitPrice(n, it)), have: fmt(n.money) }));
  el.querySelectorAll("[data-buy]").forEach((b) => b.onclick = async () => { const it = b.dataset.buy, q = await amt(T("buy", "Buy"), it); if (!q) return;
    const ti = E.MARKET_ITEMS.indexOf(it); act(E.encBig(E.OP.market, 0 * 64 + ti, q), 0, "buy " + q + " " + it); });
  el.querySelectorAll("[data-sell]").forEach((b) => b.onclick = async () => { const it = b.dataset.sell, q = await amt(T("sell", "Sell"), it); if (!q) return;
    const ti = E.MARKET_ITEMS.indexOf(it); act(E.encBig(E.OP.market, 1 * 64 + ti, q), 0, "sell " + q + " " + it); });
}
function renderDiplo(el) {
  const n = me;
  let h = '<p class="hint">' + T("diploHint", "Join an alliance to share your members' government bonuses (scaled by size, up to 10). Declaring war on a rival doubles the experience both sides earn against each other.") + "</p>";
  h += n.ally ? '<div class="myrank">' + T("inAlliance", "You are in alliance") + " <b>#" + n.ally + "</b>" + (n._ally ? " · " + n._ally.members + " " + T("members", "members") : "") + "</div>"
    : '<div class="myrank">' + T("noAlliance", "You are unaligned.") + "</div>";
  h += '<div class="row2"><input id="allyId" placeholder="' + T("allianceId", "alliance # (1–4095)") + '" inputmode="numeric"><button class="primary" id="btnJoinAlly">' + T("joinAlliance", "Join / create") + "</button>"
    + (n.ally ? '<button class="ghost" id="btnLeaveAlly">' + T("leaveAlliance", "Leave (−⅓ XP)") + "</button>" : "") + "</div>";
  // alliance roster
  const mates = Object.values(world).filter((x) => x && x.ally && x.ally === n.ally);
  if (n.ally && mates.length) h += '<div class="mt small dim">' + T("roster", "Roster") + ": " + mates.map((x) => (practice ? x.owner : disp(x.owner))).join(", ") + "</div>";
  el.innerHTML = h;
  $("btnJoinAlly").onclick = () => { const id = Math.max(1, Math.min(4095, parseInt($("allyId").value || "0", 10)));
    if (!id) return notify(T("badAllyId", "Enter an alliance number 1–4095.")); act(E.encAction(E.OP.alliance, 0, id), 0, "join alliance " + id); };
  if ($("btnLeaveAlly")) $("btnLeaveAlly").onclick = async () => { if (await uiConfirm({ title: T("confirmLeave", "Leave the alliance? You lose a third of your army experience."), danger: true, confirmText: T("leaveGo", "Leave") })) act(E.encAction(E.OP.alliance, 1), 0, "leave alliance"); };
}

let warMode = "attack", tacType = "partisan", spyOpK = "infra_gov", misType = "conv", raidOwner = null;
const WAR_MODES = ["attack", "tactical", "missile", "spy"];
function openRaid(owner) {
  target = world[owner]; if (!target || !me) return; const tgt = target;
  raidOwner = owner;                       // marks the war council open so the auto-refresh won't wipe it
  const who = practice ? tgt.owner : disp(tgt.owner);
  let h = '<div class="raidbox"><h3>⚔ ' + T("warOn", "War council — {who}", { who }) + "</h3>";
  h += '<div class="kinds">' + WAR_MODES.map((m) => '<button class="kind' + (m === warMode ? " on" : "") + '" data-mode="' + m + '">' + T("wm_" + m, m) + "</button>").join("") + "</div>";
  if (warMode === "attack") {
    const kinds = Object.keys(E.ATTACK_KINDS);
    h += '<div class="pw">' + T("yourPower", "Your attack power") + ": <b>" + fmt(E.power(me, "atk", comp)) + '</b> · ' + T("theirDef", "their defense") + ": <b>" + fmt(E.power(tgt, "def", null)) + "</b></div>";
    h += '<div class="kinds">' + kinds.map((k) => '<button class="kind sub' + (k === atkKind ? " on" : "") + '" data-kind="' + k + '">' + T("k_" + k, E.ATTACK_KINDS[k].k) + "</button>").join("") + "</div>";
    h += '<p class="dim small">' + T("kx_" + atkKind, E.ATTACK_KINDS[atkKind].txt) + "</p>";
    h += '<div class="comp">' + E.FIGHT_UNITS.map((k) => '<label>' + T("u_" + k, E.U[k].k) + ' <input type="range" min="0" max="8" value="' + Math.round((comp[k] || 0) * 8) + '" data-comp="' + k + '"></label>').join("") + "</div>";
  } else if (warMode === "tactical") {
    h += '<div class="kinds">' + E.TKEYS_TAC.map((k) => '<button class="kind sub' + (k === tacType ? " on" : "") + '" data-tac="' + k + '">' + T("tac_" + k, E.TACTICAL[k].k) + "</button>").join("") + "</div>";
    h += '<p class="dim small">' + T("tacx_" + tacType, E.TACTICAL[tacType].txt) + "</p>";
  } else if (warMode === "missile") {
    h += '<div class="kinds">' + E.MKEYS.map((k) => '<button class="kind sub' + (k === misType ? " on" : "") + '" data-mis2="' + k + '">' + T("m_" + k, E.MISSILES[k].k) + " (" + fmt(me.rockets[k] || 0) + ")</button>").join("") + "</div>";
    h += '<p class="dim small">' + T("mx_" + misType, E.MISSILES[misType].txt) + "</p>";
  } else if (warMode === "spy") {
    h += '<div class="pw">' + T("yourSpy", "Your spy strength") + ": <b>" + fmt(E.spyPower(me)) + '</b> · ' + T("agents", "agents") + ": <b>" + fmt(me.units.agent) + "</b></div>";
    h += '<select id="spySel">' + E.ESP_KEYS.map((k) => '<option value="' + k + '"' + (k === spyOpK ? " selected" : "") + ">" + T("esp_" + k, E.ESPIONAGE[k].k) + "</option>").join("") + "</select>";
    h += '<p class="dim small">' + T("espx_" + spyOpK, E.ESPIONAGE[spyOpK].txt) + "</p>";
  }
  h += '<div class="row2"><button class="primary" id="btnLaunch">🔥 ' + T("launch", "Launch") + '</button><button class="ghost" id="btnCancelRaid">' + T("cancel", "Cancel") + "</button></div></div>";
  $("panel").innerHTML = h;
  const P = $("panel");
  P.querySelectorAll("[data-mode]").forEach((b) => b.onclick = () => { warMode = b.dataset.mode; openRaid(owner); });
  P.querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => { atkKind = b.dataset.kind; openRaid(owner); });
  P.querySelectorAll("[data-tac]").forEach((b) => b.onclick = () => { tacType = b.dataset.tac; openRaid(owner); });
  P.querySelectorAll("[data-mis2]").forEach((b) => b.onclick = () => { misType = b.dataset.mis2; openRaid(owner); });
  P.querySelectorAll("[data-comp]").forEach((s) => s.oninput = () => { comp[s.dataset.comp] = s.value / 8; openRaid(owner); });
  if (P.querySelector("#spySel")) P.querySelector("#spySel").onchange = (e) => { spyOpK = e.target.value; openRaid(owner); };
  $("btnCancelRaid").onclick = () => { raidOwner = null; tab = "world"; render(); };
  $("btnLaunch").onclick = async () => {
    if (warMode === "attack") { if (me.ready < 40) return notify(T("notReady", "Your army is regrouping — wait for readiness."));
      const pk = E.packComp(comp); act(E.encAction(E.OP.attack, Object.keys(E.ATTACK_KINDS).indexOf(atkKind), pk.b, pk.c), tgt.owner, "attack " + atkKind); }
    else if (warMode === "tactical") { if (me.ready < 20) return notify(T("notReady2", "Not enough readiness for a strike."));
      act(E.encAction(E.OP.tactical, E.TKEYS_TAC.indexOf(tacType)), tgt.owner, "tactical " + tacType); }
    else if (warMode === "missile") { if ((me.rockets[misType] || 0) < 1) return notify(T("noMissiles", "You have no {m} to fire.", { m: T("m_" + misType, E.MISSILES[misType].k) }));
      const q = Math.min(me.rockets[misType] || 0, await askNum(T("fireHow", "Fire how many {m}?", { m: T("m_" + misType, E.MISSILES[misType].k) }), 1,
        T("haveN", "you have {n}", { n: fmt(me.rockets[misType] || 0) })));
      if (q) act(E.encAction(E.OP.launch, E.MKEYS.indexOf(misType), q), tgt.owner, "launch " + misType); }
    else if (warMode === "spy") { if (me.units.agent < 1) return notify(T("noAgents", "You have no agents — buy some on the market."));
      const send = Math.min(me.units.agent, await askNum(T("sendAgents", "Send how many agents?"), Math.min(me.units.agent, 100),
        T("haveN", "you have {n}", { n: fmt(me.units.agent) })));
      if (send) act(E.encBig(E.OP.spy, E.ESP_KEYS.indexOf(spyOpK), send), tgt.owner, "spy " + spyOpK); }
    raidOwner = null; tab = "world";
  };
}
function renderPractice() { render(); }

// ---- boot --------------------------------------------------------------------------------------------
function wire() {
  wireWallet(dapp);
  if ($("btnFound")) $("btnFound").onclick = found;
  if ($("btnPractice")) $("btnPractice").onclick = startPractice;
  if ($("btnExitPrac")) $("btnExitPrac").onclick = exitPractice;
}
async function boot() {
  dapp.onReturn((pend, ok, err) => dapp.showReturn(pend, ok, err, {
    connect: T("cfConnect", "Signed in."), act: T("cfAct", "Order sent — confirming on-chain…") }));
  dapp.doneLabels({ act: T("doneAct", "✓ Recorded on-chain.") });
  try { await dapp.init(); } catch { alertBar(T("cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wire(); orderCards(["pracBanner", "nationCard", "walletcard"]);
  const saved = prac.run();
  if (saved && saved.log) { practice = saved; pracReplay(); }
  render();
  await refresh();
  setInterval(() => { if (!document.hidden && !raidOwner) refresh(); }, 8000);  // don't wipe an open war council
}
boot();
if (typeof window !== "undefined") window.__sov = { dapp, get world() { return world; }, get me() { return me; } };

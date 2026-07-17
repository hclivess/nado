// sovereign.js — NADO Sovereign client: the persistent nation-war world. Built on the shared SDK
// (nadodapp.js) for the wallet/call/storage/block-hash primitives, and on the tested rules engine
// (sovereign-engine.js) for the whole economy + combat. This module reads the global action log, REPLAYS
// it through the engine to derive the live world (my nation + every rival), and turns dashboard taps into
// ply-bound act() calls. Practice mode runs the identical engine over a local sandbox of bot nations.
import { NadoDapp, $, _m, base, notify, alertBar, disp, share, wireWallet, renderWallet, stickyInputs,
         orderCards, resolveAliases, renderTopScores } from "./nadodapp.js";
import * as E from "./sovereign-engine.js";
import { ART } from "./sovereign-art.js";
import { Practice, prand } from "./practice.js";

const CID = "sovereign";                              // fixed-name deploy (like the faucet); set at deploy
const dapp = new NadoDapp({ cid: CID, app: "Sovereign" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("sov." + k, d, v) : d;
const MAPS = ["la", "lc", "le", "lt"];
const fmt = (x) => { x = Math.floor(x); return x >= 1e9 ? (x / 1e9).toFixed(1) + "G" : x >= 1e6 ? (x / 1e6).toFixed(1) + "M" : x >= 1e3 ? (x / 1e3).toFixed(1) + "k" : "" + x; };
const sign = (x) => (x >= 0 ? "+" : "") + (Math.abs(x) >= 100 ? Math.round(x) : x.toFixed(1));

let world = {}, me = null, mc = 0, tab = "build", target = null, atkKind = "plunder";
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
  const sto = await dapp.storage({ append: MAPS });
  if (!sto) return;
  const log = logFromSto(sto);
  // fetch the seed blocks every past raid needs (fast/provisional — public randomness)
  const need = [];
  for (const e of log) if (e.target) { const rh = e.rh; if (rh && dapp.cursor != null && dapp.cursor >= rh && dapp.bh(rh) === undefined) need.push(rh); }
  if (need.length) await dapp.blockHashes(need.slice(0, 60), { fast: true });
  const now = dapp.cursor != null ? dapp.cursor : (log.length ? log[log.length - 1].rh : 0);
  world = E.replayWorld(log, now, seedOf).world;
  me = dapp.me ? world[dapp.me] : null;
  render();
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
  world = E.replayWorld(practice.log, practice.now, pracSeedOf).world; me = world.you || null;
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
  bots.forEach((b, i) => log.push({ actor: b, cursor: 0, rh: 0, enc: E.encAction(E.OP.found), target: 0 }));
  // give the bots a head start so there's a world to climb
  for (let t = 1; t < 200; t++) bots.forEach((b, i) => { if (t % 3 === 0) log.push({ actor: b, cursor: t * E.TURN_BLOCKS, rh: t * E.TURN_BLOCKS, enc: botMove(E.replayWorld(log, t * E.TURN_BLOCKS, pracSeedOfFor(seed)).world[b], i), target: 0 }); });
  practice = { seed, bots, log, now: 200 * E.TURN_BLOCKS };
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
    + '<div class="rates">' + ratesLine(n) + "</div>";
}

const TABS = ["build", "army", "tech", "gov", "world"];
function render() {
  const dash = $("dash"); if (!dash) return;
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
  $("tabs").querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { tab = b.dataset.tab; render(); });
  renderPanel();
}
function renderPanel() {
  const el = $("panel"); if (!el || !me) return;
  if (tab === "build") return renderBuild(el);
  if (tab === "army") return renderArmy(el);
  if (tab === "tech") return renderTech(el);
  if (tab === "gov") return renderGov(el);
  if (tab === "world") return renderWorld(el);
}
function tile(inner, cls, data) { return '<div class="tile ' + (cls || "") + '" ' + (data || "") + ">" + inner + "</div>"; }

function renderBuild(el) {
  const per = E.buildsPerTurn(me), n = me;
  let h = '<p class="hint">' + T("buildHint", "Build up to {n} per turn on open land. Cost rises as you grow. Colonize for more land — but not while over half your land sits empty.", { n: per }) + "</p>";
  h += '<div class="row2"><button class="ghost" id="btnColonize">🧭 ' + T("colonize", "Colonize (+land)") + "</button>"
    + '<span class="landchip">🟩 ' + T("openLand", "open land") + " <b>" + n.bld.unbuilt + "</b></span></div>";
  h += '<div class="grid">' + E.BUILDABLE.map((k) => tile(
      gicon(k) + '<div class="tn">' + T("b_" + k, E.B[k].k) + '</div><div class="tc">' + n.bld[k] + "</div>"
      + '<div class="tx dim">' + T("bx_" + k, E.B[k].txt) + "</div>",
      "b-" + k, 'data-build="' + k + '"')).join("") + "</div>";
  el.innerHTML = h;
  $("btnColonize").onclick = () => act(E.encAction(E.OP.colonize), 0, T("cfColonize", "colonize"));
  el.querySelectorAll("[data-build]").forEach((d) => d.onclick = () => promptCount(d.dataset.build, per));
}
function promptCount(type, per) {
  const max = Math.min(per, me.bld.unbuilt);
  const q = Math.max(1, Math.min(max, parseInt(prompt(T("howMany", "Build how many {t}? (max {m})", { t: T("b_" + type, E.B[type].k), m: max }), String(max)) || "0", 10)));
  if (!q) return;
  if (me.money < E.buildCost(me, q)) return notify(T("tooPoor", "Not enough money for that."));
  act(E.encAction(E.OP.build, E.BUILDABLE.indexOf(type), q), 0, "build " + q + " " + type);
}
function renderArmy(el) {
  const n = me;
  let h = '<p class="hint">' + T("armyHint", "Soldiers train in barracks every turn on their own. Machine units cost factory components + money. Agents run spy ops (coming soon).") + "</p>";
  h += '<div class="grid">' + E.UKEYS.map((k) => { const u = E.U[k];
    return tile(gicon(k) + '<div class="tn">' + T("u_" + k, u.k) + '</div><div class="tc">' + fmt(n.units[k]) + "</div>"
      + '<div class="tx dim">⚔' + u.a + " 🛡" + u.d + " · 💰" + u.pay + "</div>",
      "u-" + k, 'data-unit="' + k + '"'); }).join("") + "</div>";
  h += '<p class="hint mt">' + T("compHave", "Components in stock: {c}", { c: Math.floor(n.comps) }) + "</p>";
  el.innerHTML = h;
  el.querySelectorAll("[data-unit]").forEach((d) => d.onclick = () => {
    const k = d.dataset.unit;
    if (k === "soldier") return notify(T("soldierAuto", "Soldiers come from barracks automatically — build more barracks."));
    const q = Math.max(1, parseInt(prompt(T("recruitHow", "Recruit how many {u}?", { u: T("u_" + k, E.U[k].k) }), "10") || "0", 10));
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
  el.querySelectorAll("[data-gov]").forEach((d) => d.onclick = () => {
    const k = d.dataset.gov;
    if (!confirm(T("confirmRevolt", "Revolt to {g}? This destroys part of your nation.", { g: T("gov_" + k, E.GOV[k].k) }))) return;
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
function openRaid(owner) {
  target = world[owner]; if (!target || !me) return;
  const kinds = Object.keys(E.ATTACK_KINDS);
  let h = '<div class="raidbox"><h3>⚔ ' + T("raidOn", "Raid on {who}", { who: practice ? target.owner : disp(target.owner) }) + "</h3>";
  h += '<div class="pw">' + T("yourPower", "Your attack power") + ": <b>" + fmt(E.power(me, "atk", comp)) + '</b> · ' + T("theirDef", "their defense") + ": <b>" + fmt(E.power(target, "def", null)) + "</b></div>";
  h += '<div class="kinds">' + kinds.map((k) => '<button class="kind' + (k === atkKind ? " on" : "") + '" data-kind="' + k + '">' + T("k_" + k, E.ATTACK_KINDS[k].k) + "</button>").join("") + "</div>";
  h += '<p class="dim small">' + T("kx_" + atkKind, E.ATTACK_KINDS[atkKind].txt) + "</p>";
  h += '<div class="comp">' + E.FIGHT_UNITS.map((k) => '<label>' + T("u_" + k, E.U[k].k) + ' <input type="range" min="0" max="8" value="' + Math.round((comp[k] || 0) * 8) + '" data-comp="' + k + '"></label>').join("") + "</div>";
  h += '<div class="row2"><button class="primary" id="btnLaunch">🔥 ' + T("launch", "Launch raid") + '</button><button class="ghost" id="btnCancelRaid">' + T("cancel", "Cancel") + "</button></div></div>";
  $("panel").innerHTML = h;
  $("panel").querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => { atkKind = b.dataset.kind; openRaid(owner); });
  $("panel").querySelectorAll("[data-comp]").forEach((s) => s.oninput = () => { comp[s.dataset.comp] = s.value / 8; openRaid(owner); });
  $("btnCancelRaid").onclick = () => { tab = "world"; render(); };
  $("btnLaunch").onclick = () => {
    if (me.ready < 40) return notify(T("notReady", "Your army is still regrouping — wait for readiness to recover."));
    const pk = E.packComp(comp), k = kinds.indexOf(atkKind);
    act(E.encAction(E.OP.attack, k, pk.b, pk.c), target.owner, "raid " + atkKind);
    tab = "world";
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
  setInterval(() => { if (!document.hidden) refresh(); }, 8000);
}
boot();
if (typeof window !== "undefined") window.__sov = { dapp, get world() { return world; }, get me() { return me; } };

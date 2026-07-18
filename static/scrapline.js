// scrapline.js — NADO Scrapline: an ORIGINAL cooldown auto-battler duel for stakes (a genre homage,
// inspired by "From Rust To Ash" by LokiStriker — nothing ported: all code/items/names here are original).
// Built on the shared SDK (nadodapp.js), the shared move-log duel scaffold (duelgame.js) and the
// headless-tested rules engine (scrapline-engine.js). Both players DRAFT CONCURRENTLY from their own
// blockhash-seeded offer streams (each offer derives from the seed height your previous move pinned —
// unpredictable when you signed, replayable by every browser); once both have drafted 9 rounds the fight
// resolves as a pure deterministic simulation and the wager settles concede / agree / refund-timeout.
// This module owns ONLY the Scrapline half: offers, gear slots, and the combat report.
import { NadoDapp, $, notify, disp, _m, renderTopScores, share, base } from "./nadodapp.js";
import { DuelGame } from "./duelgame.js";
import * as E from "./scrapline-engine.js";
import { ART } from "./scrapline-art.js";
import { prand, Practice } from "./practice.js";   // practice-vs-computer + solo persistence
import { dayAnchor, verifyEntries, entriesFrom } from "./provable.js";   // provable daily claims (see doc/provable-practice.md)

const CID = "634dc7c3eda3fea16fddfaca47a0c8aa";
const dapp = new NadoDapp({ cid: CID, app: "Scrapline" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("scrap." + k, d, v) : d;

const IN = (it) => T("it_" + it.k, it.n);            // item name (translatable)
const IX = (it) => T("itx_" + it.k, it.txt);           // item description (translatable)
const TG = (i) => T("tag_" + E.TAGS[i].toLowerCase(), E.TAGS[i]);  // tag label BLADE/BOLT/… (translatable)
let sel = null;                                            // selected offer choice (0..2)
const TAGC = ["tg-blade", "tg-bolt", "tg-spark", "tg-ember", "tg-plate", "tg-mend", "tg-core"];

const duel = new DuelGame(dapp, {
  prefix: "scrap", icon: "⚙", marks: ["⚙", "🔩"], prize: true,
  appendMaps: ["eday", "eaddr", "escore", "en", "ea0", "ea1", "ea2", "ea3", "ea4", "ea5", "ea6", "ea7"],
  onStorage(sto) { renderSoloBoard(sto); },
  rebuild(gm) {
    if (!gm.kh) return null;
    return E.replay(gm.id, this.qOf(gm.kh), (gm.recs || []).map((r) => ({ enc: r.enc, side: r.side, q: this.qOf(r.rh) })));
  },
  // drafting is concurrent: it's "my move" whenever I still have rounds left
  canAct: (eng, me) => eng.ps[me].round < E.ROUNDS,
  // practice-vs-computer (duelgame.js SDK feature): direct local apply + a greedy merge-first drafter
  applyLocal(eng, side, enc, q) { eng._q = q; E.applyMove(eng, side, enc); eng.mi++; },
  botMove(eng, k) {
    const offer = E.offerFor(eng, 1);
    if (!offer) return null;
    const rnd = prand(this.practice.seed + ":bot:" + k);
    if (rnd() < 0.08) return E.encMove(2, 0);                        // occasional scrap for max HP
    const choice = Math.floor(rnd() * 3), z = eng.ps[1];
    let slot = z.gear.findIndex((g) => g && g.id === offer[choice] && g.rank < E.MAXRANK);
    if (slot < 0) slot = z.gear.findIndex((g) => !g);
    if (slot < 0) slot = Math.floor(rnd() * E.SLOTS);
    return E.encMove(1, choice + 4 * slot);
  },
  turnOf: (eng) => (eng.ps[0].round < E.ROUNDS && eng.ps[1].round < E.ROUNDS) ? null
    : eng.ps[0].round < E.ROUNDS ? 0 : eng.ps[1].round < E.ROUNDS ? 1 : null,
  resultOf: (eng) => eng.result,
  overHint(eng) {
    const c = eng.combat;
    return c ? T("finalHp", "Final hull {a}/{ma} vs {b}/{mb}.", { a: c.hp[0], ma: c.maxhp[0], b: c.hp[1], mb: c.maxhp[1] }) : "";
  },
  onReset() { sel = null; },
  onAdvance() { sel = null; },
  onSubmit() { sel = null; },
  shareText: (gm, id) => T("shareText", "Fight me at Scrapline for {stake}on NADO — game #{id}:", { stake: gm && gm.exists ? (Number(gm.stake) / 1e10) + " NADO " : "", id }),
  inviteTitle: T("inviteTitle", "You're challenged to a Scrapline fight"),
  inviteBody: (gm) => T("inviteBody", "Fight {who} for <b>{amt} NADO</b> — winner takes the pot.", { who: disp(gm.p1), amt: Number(gm.stake) / 1e10 }),
  renderGame,
});

// ---- tiles ---------------------------------------------------------------------------------------------
const stars = (rank) => (rank <= 4 ? "★".repeat(rank) : "★" + rank);   // ranks reach 9 — keep the badge compact
function statLine(it, rank) {
  const v = E.itemVal(it, rank);
  // CORES spell out EXACTLY what they add at this rank (the old "⚙ 12" told the player nothing)
  if (it.kind === "c") {
    if (it.chp) return "➕ " + v + " " + T("fxMaxHp", "max HP");
    if (it.ccd) return "⏩ −" + Math.min(40, v) + "% " + T("fxCd", "cooldowns");
    if (it.call) return "⚔ +" + v + " " + T("fxAllWeapons", "ALL weapons");
    if (it.cburn) return "🔥 +" + v + " " + T("fxBurnEmber", "burn on EMBER");
    if (it.ctag === 4) return "🛡 +" + v + " " + TG(it.ctag);
    return "⚔ +" + v + " " + TG(it.ctag);
  }
  const bits = [];
  if (it.kind === "d" && v > 0) bits.push("⚔ " + v);
  if (it.kind === "s") bits.push("🛡 " + v);
  if (it.kind === "h") bits.push("➕ " + v);
  if (it.burn) bits.push("🔥 " + (it.burn + (it.burna || 0) * (rank - 1)));
  if (it.sh) bits.push("🛡 " + (it.sh + (it.sha || 0) * (rank - 1)));
  if (it.ref) bits.push("↩ " + (it.ref + (it.refa || 0) * (rank - 1)));
  if (it.spc === 7) bits.push("💥 +" + it.ram + "% 🛡");
  return bits.join(" ") + (it.cd ? " · " + (it.cd / 10) + "s" : "");
}
// one short, translated, NUMERIC effect line per special — replaces the untranslated prose for known effects
function fxLine(it, rank) {
  const P = {
    1: () => T("fx1", "fires ×2 per trigger"),
    2: () => T("fx2", "pierces shields"),
    3: () => T("fx3", "+50% vs burning"),
    4: () => T("fx4", "reflects {n} per hit while shielded", { n: it.ref + (it.refa || 0) * (rank - 1) }),
    5: () => T("fx5", "+{n} shield to self", { n: (it.sh || 0) + (it.sha || 0) * (rank - 1) }),
    6: () => T("fx6", "detonates burn: ×4 damage"),
    7: () => T("fx7", "ram: +{n}% of your shield as damage", { n: it.ram }),
    8: () => T("fx8", "overheal becomes shield"),
  };
  if (it.spc && P[it.spc]) return P[it.spc]();
  if (it.tag === 2 && it.kind === "d") return T("fxSpark", "double damage vs shielded");
  if (it.burn) return T("fxBurn", "burn: {n} damage per second, fading", { n: it.burn + (it.burna || 0) * (rank - 1) });
  return IX(it);
}
function itemTile(id, rank, extra, data) {
  const it = E.ITEMS[id];
  return '<div class="ctile ' + TAGC[it.tag] + (extra || "") + '" ' + (data || "") + ' title="' + IX(it) + '">'
    + '<span class="cost">T' + it.tier + "</span>"
    + (rank > 1 ? '<span class="cnt">' + stars(rank) + "</span>" : "")
    + '<div class="cart">' + (ART[it.k] || "") + "</div>"
    + '<div class="cname">' + IN(it) + "</div>"
    + '<div class="ctxt">' + statLine(it, rank) + "</div>"
    + '<div class="ctxt dim">' + TG(it.tag) + " · " + fxLine(it, rank) + "</div>"
    + "</div>";
}

// ---- interaction ---------------------------------------------------------------------------------------
function onOfferTap(i) {
  if (!duel.canAct()) return;
  sel = sel === i ? null : i;
  duel.render();
}
function onSlotTap(slot) {
  const eng = duel.eng; if (!duel.canAct() || sel == null) return notify(T("pickFirst", "Tap an offered item first, then a gear slot."));
  const me = duel.myIdx(duel.last);
  const offer = E.offerFor(eng, me); if (!offer) return;
  const id = offer[sel], cur = eng.ps[me].gear[slot];
  const label = cur && cur.id === id && cur.rank < E.MAXRANK ? "merge " + E.ITEMS[id].n : "equip " + E.ITEMS[id].n;
  duel.submit(1, sel + 4 * slot, label);
}
function skipOffer() {
  if (!duel.canAct()) return;
  const n = Math.min(50, 8 + 4 * (duel.eng.ps[duel.myIdx(duel.last)].round + 1));
  duel.arm("skip", T("tapAgainSkip", "Tap again to scrap this offer (+{n} max HP)", { n }), () => duel.submit(2, 0, "scrap offer"));
}

// ---- render --------------------------------------------------------------------------------------------
function hpBar(hp, maxhp, cls) {
  const pct = Math.max(0, Math.min(100, Math.round(hp * 100 / maxhp)));
  return '<div class="hpbar"><div class="hpfill ' + (cls || "") + '" style="width:' + pct + '%"></div>'
    + '<span class="hplbl">' + Math.max(0, hp) + " / " + maxhp + "</span></div>";
}
function gearRow(eng, p, mine) {
  const z = eng.ps[p];
  return z.gear.map((gitem, slot) => {
    if (!gitem) return '<div class="ctile slot-empty' + (mine && sel != null ? " buyable" : "") + '" data-slot="' + slot + '"><div class="cname dim">' + T("emptySlot", "empty") + "</div></div>";
    const it = E.ITEMS[gitem.id];
    let extra = "";
    if (mine && sel != null) {
      const me = duel.myIdx(duel.last), offer = E.offerFor(eng, me);
      if (offer) extra = offer[sel] === gitem.id && gitem.rank < E.MAXRANK ? " sel" : " buyable";
    }
    return itemTile(gitem.id, gitem.rank, extra, 'data-slot="' + slot + '"');
  }).join("");
}
function fmtCombat(gm, c) {
  const me = duel.myIdx(gm);
  const who = (p) => (p === me ? T("you", "You") : disp(p === 0 ? gm.p1 : gm.p2));
  const rows = [];
  for (const e of c.ev.slice(-40)) {
    const it = e.x != null ? E.ITEMS[e.x].n : "";
    const M = { hit: T("cHit", "{w}: {i} hits for {n}"), burn: T("cBurn", "{w} burns for {n}"),
      shield: T("cShield", "{w}: {i} shields {n}"), heal: T("cHeal", "{w}: {i} repairs {n}"),
      ignite: T("cIgnite", "{w}: {i} ignites +{n}") };
    rows.push('<div class="' + (e.p === me ? "me" : "") + '"><span class="dim">' + (e.t / 10).toFixed(1) + "s</span> "
      + (M[e.e] || e.e).replace("{w}", who(e.p)).replace("{i}", it).replace("{n}", e.n) + "</div>");
  }
  return rows.join("");
}
function renderGame(gm, eng) {
  const me = duel.myIdx(gm);
  const hud = $("hud");
  if (!eng || eng.setup || gm.nn !== 2) {
    hud.innerHTML = ""; $("offer").innerHTML = ""; $("myGear").innerHTML = ""; $("oppGear").innerHTML = "";
    $("combatPane").innerHTML = ""; $("offerBtns").innerHTML = ""; $("oppZone").classList.add("hidden");
    return;
  }
  $("oppZone").classList.remove("hidden");
  const mp = me != null ? me : 0, op = 1 - mp;
  const zm = eng.ps[mp], zo = eng.ps[op];
  hud.innerHTML =
    '<span class="turnbadge">' + (eng.over ? T("phaseCombat", "COMBAT RESOLVED") : T("phaseDraft", "DRAFT {a}/{r} vs {b}/{r}", { a: zm.round, b: zo.round, r: E.ROUNDS })) + "</span>"
    + '<span class="stat vp">' + T("hpYou", "Your max HP") + " <b>" + zm.maxhp + "</b></span>"
    + '<span class="stat vp">' + T("hpThem", "Theirs") + " <b>" + zo.maxhp + "</b></span>";
  // opponent zone
  $("oppHead").textContent = disp(op === 0 ? gm.p1 : gm.p2);
  $("oppCounts").textContent = T("drafted", "drafted {n}/{r}", { n: zo.round, r: E.ROUNDS });
  $("oppGear").innerHTML = gearRow(eng, op, false);
  // my offer
  const offer = me != null && !eng.over ? E.offerFor(eng, me) : null;
  const ob = $("offerBtns"); ob.innerHTML = "";
  if (me != null && !eng.over && zm.round < E.ROUNDS) {
    if (offer == null) {
      $("offer").innerHTML = '<span class="dim">' + (duel.pendingMove ? T("offerConfirming", "move confirming…") : T("offerPending", "🌀 forging your next offer — waiting for the randomness block…")) + "</span>";
    } else {
      $("offer").innerHTML = offer.map((id, i) => itemTile(id, 1, sel === i ? " sel" : " buyable", 'data-off="' + i + '"')).join("");
      $("offer").querySelectorAll("[data-off]").forEach((d) => d.onclick = () => onOfferTap(parseInt(d.dataset.off, 10)));
      const b = document.createElement("button"); b.className = "ghost";
      b.textContent = duel.armed && duel.armed.key === "skip" ? duel.armed.label
        : T("skipOffer", "♻ Scrap this offer (+{n} max HP)", { n: Math.min(50, 8 + 4 * (duel.eng.ps[duel.myIdx(duel.last)].round + 1)) });
      if (duel.armed && duel.armed.key === "skip") b.classList.add("pulse");
      b.onclick = skipOffer; ob.appendChild(b);
      $("offerHint").textContent = sel == null ? T("offerHintPick", "Tap an item, then a gear slot. Same item on the slot = MERGE (rank up); a different one replaces it (old is scrapped for max HP).") : T("offerHintSlot", "Now tap a gear slot to place it.");
    }
  } else if (me != null && !eng.over) {
    $("offer").innerHTML = '<span class="dim">' + T("draftDone", "Your build is locked — waiting for the opponent to finish drafting.") + "</span>";
    $("offerHint").textContent = "";
  } else { $("offer").innerHTML = ""; $("offerHint").textContent = ""; }
  // my gear
  $("myHead").textContent = me != null ? T("yourGear", "Your gear") : disp(gm.p1);
  $("myGear").innerHTML = gearRow(eng, mp, me != null && duel.canAct());
  $("myGear").querySelectorAll("[data-slot]").forEach((d) => d.onclick = () => onSlotTap(parseInt(d.dataset.slot, 10)));
  // combat report
  const cp = $("combatPane");
  if (eng.over && eng.combat) {
    const c = eng.combat;
    cp.innerHTML = '<div class="zh">' + T("combatHead", "Combat report") + "</div>"
      + '<div class="small">' + (me != null ? T("you", "You") : disp(gm.p1)) + "</div>" + hpBar(c.hp[mp], c.maxhp[mp], "me")
      + '<div class="small mt">' + disp(op === 0 ? gm.p1 : gm.p2) + "</div>" + hpBar(c.hp[op], c.maxhp[op])
      + '<div id="combatLog" class="mt">' + fmtCombat(gm, c) + "</div>";
  } else cp.innerHTML = "";
}

// ---- SOLO GAUNTLET (free, fully client-side — no wallet, no stake; deterministic per seed) --------------
const soloPrac = new Practice("scrapline_solo");     // SDK persistence: run state + local bests
let soloSel = null;
// The daily seed (engine seedOfDay = provable.js provableSeed) is CONSENSUS for on-chain claims. It
// binds (a) the FIRST FINALIZED L1 BLOCK of the UTC day — nobody can pre-grind tomorrow's run — and
// (b) YOUR ADDRESS — a copied move list verifies only for its owner. Signed-out players get an "anon"
// run they can play but never post; the daily button hints to sign in first.
const today = () => Math.floor(Date.now() / 86400000);
let _anch = { day: 0, hash: null };
async function anchorOf(day) {
  if (_anch.day !== day) _anch = { day, hash: await dayAnchor(base(), day).catch(() => null) };
  return _anch.hash;
}
const isDailySeed = (seed) => typeof seed === "string" && seed.startsWith("daily2-scrapline-" + today() + "-");
async function dailySeed() {
  const day = today(), anch = await anchorOf(day);
  return anch ? E.seedOfDay(day, anch, dapp.me || "anon") : null;
}
const soloLoad = () => soloPrac.run();
const soloSave = (r) => soloPrac.saveRun(r);
let soloRun = soloLoad();
if (soloRun && (soloRun.picks === undefined || !Array.isArray(soloRun.choices))) soloRun = null;   // pre-rebalance run shape

function soloStart(seed) {
  soloRun = E.soloNew(seed); soloSel = null; soloSave(soloRun); renderSolo();
}
function soloBank() {   // record a finished run's score on the local best-board
  if (!soloRun || !soloRun.over) return;
  soloPrac.bump(soloRun.seed.startsWith("daily-") ? soloRun.seed : "random", soloRun.score);
}
function soloGearRow(gear, clickable) {
  return gear.map((gitem, slot) => {
    if (!gitem) return '<div class="ctile slot-empty' + (clickable && soloSel != null ? " buyable" : "") + '" data-sslot="' + slot + '"><div class="cname dim">' + T("emptySlot", "empty") + "</div></div>";
    let extra = "";
    if (clickable && soloSel != null) {
      const offer = E.soloOfferFor(soloRun);
      if (offer) extra = offer[soloSel] === gitem.id && gitem.rank < E.MAXRANK ? " sel" : " buyable";
    }
    return itemTile(gitem.id, gitem.rank, extra, 'data-sslot="' + slot + '"');
  }).join("");
}
function renderSolo() {
  const top = $("soloTop"), hud = $("soloHud"), zones = $("soloZones");
  if (!top) return;
  const bd = soloPrac.best("daily-" + today()), br = soloPrac.best("random");
  top.innerHTML = "";
  const mkBtn = (txt, fn, primary) => { const x = document.createElement("button"); x.className = primary ? "primary" : "ghost"; x.textContent = txt; x.onclick = fn; top.appendChild(x); };
  const isDaily = soloRun && isDailySeed(soloRun.seed);
  mkBtn(T("dailyRun", "📅 Daily gauntlet") + (bd ? " · " + T("bestN", "best {n}", { n: bd }) : ""), async () => {
    if (!dapp.me) notify(T("dailyAnonHint", "Playing signed out — sign in BEFORE starting if you want this run to count on the board."));
    const seed = await dailySeed();
    if (!seed) return notify(T("dailyNotReady", "Today's gauntlet is still being seeded by the chain — try again in a minute."));
    soloStart(seed);
  }, !soloRun || (soloRun.over && isDaily));
  mkBtn(T("randomRun", "🎲 Random gauntlet") + (br ? " · " + T("bestN", "best {n}", { n: br }) : ""), () => soloStart("rnd-" + Math.random().toString(36).slice(2, 10)));
  if (!soloRun) { hud.innerHTML = ""; zones.classList.add("hidden"); return; }
  zones.classList.remove("hidden");
  const run = soloRun;
  hud.innerHTML =
    '<span class="turnbadge">' + (run.over ? T("runOver", "RUN OVER — score {n}", { n: run.score }) : T("stageN", "STAGE {n}", { n: run.stage })) + "</span>"
    + '<span class="stat">' + T("lives", "Lives") + " <b>" + "❤".repeat(Math.max(0, run.lives)) + (run.lives <= 0 ? "0" : "") + "</b></span>"
    + '<span class="stat vp">' + T("hpYou", "Your max HP") + " <b>" + run.maxhp + "</b></span>"
    + '<span class="stat vp">' + T("scoreN", "Score") + " <b>" + run.score + "</b></span>"
    + (isDaily ? '<span class="stat">' + T("dailyTag2", "daily gauntlet") + "</span>" : "");
  // offer
  const offer = E.soloOfferFor(run), ob = $("soloBtns");
  ob.innerHTML = "";
  if (run.over) {
    $("soloOffer").innerHTML = '<span class="dim">' + T("runOverMsg", "The wrecks got you at stage {n}. Start another run — or take this build style into a PvP fight for stakes above.", { n: run.stage }) + "</span>";
    $("soloHint").textContent = "";
    const shareBtn = document.createElement("button"); shareBtn.className = "primary";
    shareBtn.textContent = T("shareRun", "📣 Share my score");
    // the SDK share(): native share sheet on mobile, clipboard fallback + button feedback elsewhere
    shareBtn.onclick = () => share(base(),
      T("shareRunText", "I cleared {n} stages in the Scrapline {kind} gauntlet — beat that: https://scrapline.nadochain.com", { n: run.score, kind: isDaily ? T("daily", "daily") : T("random", "random") }),
      shareBtn);
    ob.appendChild(shareBtn);
    // post a finished DAILY run on the global board: the claim is the packed choice list — every
    // browser re-verifies it by replaying, so a fake score simply never renders.
    const day = today();
    if (isDaily && run.score > 0 && (run.choices || []).length <= E.MAX_ATT) {
      // postable ONLY if the run was seeded with MY signed-in address (the claim verifies against the
      // poster's address on every browser — an anon or copied run can never land on the board)
      const mine = dapp.me && _anch.day === day && _anch.hash && run.seed === E.seedOfDay(day, _anch.hash, dapp.me);
      const post = document.createElement("button"); post.className = "ghost";
      post.textContent = mine ? T("postScore", "🏆 Post my score on the daily board")
        : T("postScoreAnon", "🏆 Board runs must start signed in — sign in and start a fresh daily");
      post.disabled = !mine;
      post.onclick = () => {
        if (!mine) return;
        const words = E.packChoices(run.choices);
        dapp.call("post", [day, run.score, run.choices.length].concat(words), null,
          "post daily gauntlet score " + run.score, { phase: "post" });
        notify(T("postSent", "Score submitted — it appears on the board once verified on-chain."));
      };
      ob.appendChild(post);
    }
  } else if (offer) {
    $("soloOffer").innerHTML = offer.map((id, i) => itemTile(id, 1, soloSel === i ? " sel" : " buyable", 'data-soff="' + i + '"')).join("");
    $("soloOffer").querySelectorAll("[data-soff]").forEach((d) => d.onclick = () => { const i = parseInt(d.dataset.soff, 10); soloSel = soloSel === i ? null : i; renderSolo(); });
    const skip = document.createElement("button"); skip.className = "ghost";
    skip.textContent = T("skipOffer", "♻ Scrap this offer (+{n} max HP)", { n: Math.min(50, 8 + 4 * soloRun.stage) });
    skip.onclick = () => { E.soloPick(soloRun, -1, 0); soloSel = null; soloSave(soloRun); renderSolo(); };
    ob.appendChild(skip);
    $("soloHint").textContent = soloSel == null ? T("offerHintPick", "Tap an item, then a gear slot. Same item on the slot = MERGE (rank up); a different one replaces it (old is scrapped for max HP).") : T("offerHintSlot", "Now tap a gear slot to place it.");
  } else {
    $("soloOffer").innerHTML = '<span class="dim">' + T("readyToFight", "Gear locked in — fight when ready.") + "</span>";
    $("soloHint").textContent = "";
  }
  // gear + enemy
  $("soloGear").innerHTML = soloGearRow(run.gear, !run.over);
  $("soloGear").querySelectorAll("[data-sslot]").forEach((d) => d.onclick = () => {
    if (run.over || soloSel == null) return;
    E.soloPick(soloRun, soloSel, parseInt(d.dataset.sslot, 10));
    soloSel = null; soloSave(soloRun); renderSolo();
  });
  const enemy = run.over ? (run.lastCombat && run.lastCombat.enemy) : E.enemyBuild(run.seed, run.stage);
  $("soloEnemyHead").textContent = T("soloEnemyN", "Wreck #{n}", { n: run.over ? (run.lastCombat ? run.lastCombat.stage : run.stage) : run.stage });
  $("soloEnemyHp").textContent = enemy ? enemy.maxhp + " HP" : "";
  $("soloEnemy").innerHTML = enemy ? enemy.gear.filter(Boolean).map((gi) => itemTile(gi.id, gi.rank)).join("") : "";
  // fight
  const fb = $("btnSoloFight");
  fb.classList.toggle("hidden", run.over);
  fb.disabled = run.picks > 0;
  fb.textContent = run.picks > 0
    ? T("fightNeedsPicks", "⚔ Fight — {n} salvage offer(s) to resolve first", { n: run.picks })
    : T("fightBtn", "⚔ Fight");
  fb.onclick = () => {
    if (run.over || run.picks > 0) return;
    const c = E.soloFight(soloRun);
    soloBank(); soloSave(soloRun); renderSolo();
    const cp = $("soloCombat");
    if (c) {
      cp.classList.remove("hidden");
      const won = c.result === 1 || c.result === 3;
      cp.innerHTML = '<div class="zh">' + (won ? T("soloWin", "✔ Wreck #{n} destroyed!", { n: c.stage }) : T("soloLoss", "✘ Wreck #{n} took you down — {l}", { n: c.stage, l: soloRun.over ? T("runEnded", "run over") : T("lifeLost", "you lost a life") })) + "</div>"
        + '<div class="small">' + T("you", "You") + "</div>" + hpBar(c.hp[0], c.maxhp[0], "me")
        + '<div class="small mt">' + T("soloEnemyN", "Wreck #{n}", { n: c.stage }) + "</div>" + hpBar(c.hp[1], c.maxhp[1])
        + '<div id="combatLog" class="mt">' + c.ev.slice(-30).map((e) => {
          const it = e.x != null ? E.ITEMS[e.x].n : "";
          const M = { hit: T("cHit", "{w}: {i} hits for {n}"), burn: T("cBurn", "{w} burns for {n}"),
            shield: T("cShield", "{w}: {i} shields {n}"), heal: T("cHeal", "{w}: {i} repairs {n}"),
            ignite: T("cIgnite", "{w}: {i} ignites +{n}") };
          const w = e.p === 0 ? T("you", "You") : T("wreck", "Wreck");
          return '<div class="' + (e.p === 0 ? "me" : "") + '"><span class="dim">' + (e.t / 10).toFixed(1) + "s</span> " + (M[e.e] || e.e).replace("{w}", w).replace("{i}", it).replace("{n}", e.n) + "</div>";
        }).join("") + "</div>";
    }
  };
}
renderSolo();

// ---- daily highscore board (verified client-side) ------------------------------------------------------
let _boardBusy = false;
async function renderSoloBoard(sto) {
  const el = $("soloScoreList"); if (!el || _boardBusy) return;
  _boardBusy = true;
  try {
    const day = today(), anch = await anchorOf(day);
    if (!anch) { el.innerHTML = '<span class="dim">' + T("boardSeeding", "Today's board is being seeded by the chain…") + "</span>"; return; }
    // provable.js pipeline: read today's entries, REPLAY each claim with the poster's own
    // address-bound seed (verdicts cached per entry) — a forged or copied claim never renders.
    const entries = entriesFrom(sto, _m, day, [0, 1, 2, 3, 4, 5, 6, 7].map((i) => "ea" + i));
    const rows = await verifyEntries(entries, (en) => E.verifyClaim(day, en.n, en.words, anch, en.addr));
    renderTopScores(el, rows, dapp.me,
      T("noSoloScores", "No verified scores today — finish a daily run and post yours."),
      T("stagesHead", "Stages"), true);
  } finally { _boardBusy = false; }
}

duel.boot(["activeGame", "solo", "lobby", "play", "walletcard", "bankroll", "scoreboard"]);

// test hook: the UI E2E harness (tests/*_ui_e2e.mjs) drives the real DOM against crafted engine states
if (typeof window !== "undefined") window.__duel = duel;

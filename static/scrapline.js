// scrapline.js — NADO Scrapline: an ORIGINAL cooldown auto-battler duel for stakes (a genre homage,
// inspired by "From Rust To Ash" by LokiStriker — nothing ported: all code/items/names here are original).
// Built on the shared SDK (nadodapp.js), the shared move-log duel scaffold (duelgame.js) and the
// headless-tested rules engine (scrapline-engine.js). Both players DRAFT CONCURRENTLY from their own
// blockhash-seeded offer streams (each offer derives from the seed height your previous move pinned —
// unpredictable when you signed, replayable by every browser); once both have drafted 9 rounds the fight
// resolves as a pure deterministic simulation and the wager settles concede / agree / refund-timeout.
// This module owns ONLY the Scrapline half: offers, gear slots, and the combat report.
import { NadoDapp, $, notify, disp } from "./nadodapp.js";
import { DuelGame } from "./duelgame.js";
import * as E from "./scrapline-engine.js";

const CID = "72a195822ef32caa9680eee51eb95dc9";
const dapp = new NadoDapp({ cid: CID, app: "Scrapline" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("scrap." + k, d, v) : d;

let sel = null;                                            // selected offer choice (0..2)
const TAGC = ["tg-blade", "tg-bolt", "tg-spark", "tg-ember", "tg-plate", "tg-mend", "tg-core"];

const duel = new DuelGame(dapp, {
  prefix: "scrap", icon: "⚙", marks: ["⚙", "🔩"],
  rebuild(gm) {
    if (!gm.kh) return null;
    return E.replay(gm.id, this.qOf(gm.kh), (gm.recs || []).map((r) => ({ enc: r.enc, side: r.side, q: this.qOf(r.rh) })));
  },
  // drafting is concurrent: it's "my move" whenever I still have rounds left
  canAct: (eng, me) => eng.ps[me].round < E.ROUNDS,
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
const stars = (rank) => "★".repeat(rank);
function statLine(it, rank) {
  const v = E.itemVal(it, rank);
  if (it.kind === "c") return "⚙ " + v;
  const bits = [];
  if (it.kind === "d" && v > 0) bits.push("⚔ " + v);
  if (it.kind === "s") bits.push("🛡 " + v);
  if (it.kind === "h") bits.push("➕ " + v);
  if (it.burn) bits.push("🔥 " + (it.burn + (it.burna || 0) * (rank - 1)));
  if (it.sh) bits.push("🛡 " + (it.sh + (it.sha || 0) * (rank - 1)));
  return bits.join(" ") + (it.cd ? " · " + (it.cd / 10) + "s" : "");
}
function itemTile(id, rank, extra, data) {
  const it = E.ITEMS[id];
  return '<div class="ctile ' + TAGC[it.tag] + (extra || "") + '" ' + (data || "") + ' title="' + it.txt + '">'
    + '<span class="cost">T' + it.tier + "</span>"
    + (rank > 1 ? '<span class="cnt">' + stars(rank) + "</span>" : "")
    + '<div class="cname">' + it.n + "</div>"
    + '<div class="ctxt">' + statLine(it, rank) + "</div>"
    + '<div class="ctxt dim">' + E.TAGS[it.tag] + " · " + it.txt + "</div>"
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
  duel.arm("skip", T("tapAgainSkip", "Tap again to scrap this offer (+12 max HP)"), () => duel.submit(2, 0, "scrap offer"));
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
      b.textContent = duel.armed && duel.armed.key === "skip" ? duel.armed.label : T("skipOffer", "♻ Scrap this offer (+12 max HP)");
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

duel.boot(["activeGame", "lobby", "play", "walletcard", "bankroll"]);

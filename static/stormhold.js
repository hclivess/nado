// stormhold.js — NADO Stormhold: a 2-player deck-building strategy duel for stakes, built on the shared
// SDK (nadodapp.js), the shared move-log duel scaffold (duelgame.js) and the headless-tested rules engine
// (stormhold-engine.js). The contract is the chess model — escrow + ordered on-chain move log + mutual-
// agreement settle — extended with per-move SEED HEIGHTS: every move pins a future L1 block hash, and the
// engine derives every shuffle from it, so both browsers replay byte-identical games and no shuffle can be
// rigged. All information is public on-chain (open-hand play); the skill is the deck-building itself.
// This module owns ONLY the Stormhold-specific half: engine replay, the supply/hand/decision UI, and the
// move encodings; everything else (escrow actions, lobby, invites, settle chrome) lives in duelgame.js.
import { NadoDapp, $, notify, disp, randSecret, algHashn, ALG_P } from "./nadodapp.js";
import { DuelGame } from "./duelgame.js";
import { faucetAttach } from "./faucet.js";   // free-play claims for broke newcomers (doc/faucet.md)
import * as E from "./stormhold-engine.js";
import { ART } from "./stormhold-art.js";
import { prng, randomMove } from "./stormhold-bot.js";   // powers the free practice-vs-computer mode
import { prand } from "./practice.js";

const CID = "9f66d438dcbc87adc748f0cbe13a701b";
const dapp = new NadoDapp({ cid: CID, app: "Stormhold" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("storm." + k, d, v) : d;
const SKIP = 4095;

let dsel = new Set();              // multi-select (mask frames / treasure picking)
let senD = [0, 0], senSwap = 0;    // Skywatch chooser
let peekOpp = false;

const isA = (id) => !!(E.CARDS[id].t & E.A), isT = (id) => !!(E.CARDS[id].t & E.T), isV = (id) => !!(E.CARDS[id].t & E.V);
const NAME = (id) => E.CARDS[id].n;
const maskOf = (set) => [...set].reduce((m, i) => m + 2 ** i, 0);
const MASK_FRAMES = { cel: 1, chp: 1, mil: 1, poa: 1 };
const PICK_FRAMES = { bur: 1, burH: 1, remT: 1, minT: 1, thr: 1, artT: 1 };
const GAIN_FRAMES = { remG: 1, minG: 1, wsh: 1, artG: 1 };

// ---- hidden hands (commit-reveal) ------------------------------------------------------------------
// The per-game SECRET lives only in this browser (localStorage). Its alghash commit rides open()/join();
// at game end reveal() posts the secret and every client runs the exact verification replay.
let hiddenWant = false;                                   // the "hidden hands" toggle for NEW games
const SKEY = (g) => "nado_stormhold_secret_" + g;
function mySecret(g) {
  let s = null;
  try { s = localStorage.getItem(SKEY(g)); } catch {}
  if (!s) { s = (randSecret() % ALG_P()).toString(); try { localStorage.setItem(SKEY(g), s); } catch {} }
  return BigInt(s);
}
const isHiddenGame = (gm) => !!(gm && !gm.practice && gm.c1 && gm.c2);
const hid = () => isHiddenGame(duel.last);                // is the ACTIVE game a hidden one?
const encClaim = (idx, id) => idx + id * 32;              // 5-bit index + card id (engine's claim format)

const duel = new DuelGame(dapp, {
  prefix: "storm", icon: "🏰", marks: ["🏰", "⚔"],
  appendMaps: ["cfg", "c1", "c2", "r1h", "r1l", "r2h", "r2l"],
  rebuild(gm) {
    if (!gm.kh) return null;
    const mask = gm.practice ? kMask : gm.cfg;   // practice honors your current picker choice too
    const recsQ = (gm.recs || []).map((r) => ({ enc: r.enc, side: r.side, q: this.qOf(r.rh) }));
    if (isHiddenGame(gm)) {
      // both secrets revealed → the authoritative EXACT replay: hands go public, claims verified,
      // st.cheater/st.result decide the settle. Until then: my pov (my zones real, theirs face-down).
      if (gm.r1 && gm.r2) return E.verifyHidden(gm.id, this.qOf(gm.kh), recsQ, mask, [gm.r1, gm.r2]);
      const me = this.myIdx(gm);
      if (me == null) return null;                        // spectators can't derive either hidden hand
      const sec = mySecret(gm.id);
      const wrap = (q) => (q == null ? null : { pub: q, [me]: E.mixQ(q, sec), [1 - me]: null });
      return E.replay(gm.id, wrap(this.qOf(gm.kh)), recsQ.map((r) => ({ ...r, q: wrap(r.q) })), mask, { pov: me });
    }
    return E.replay(gm.id, this.qOf(gm.kh), recsQ, mask);
  },
  // extra open() args: the kingdom-mask cfg word + the hidden-hands commit (0 = open-hand). A rematch
  // (gm != null) keeps the original game's kingdom AND hiddenness, with a FRESH secret for the new id.
  openExtra: (gm, id) => [gm ? (gm.cfg || 0) : kMask,
    (gm ? !!gm.c1 : hiddenWant) ? algHashn([mySecret(id)]) : 0],
  joinExtra: (gm, id) => (gm.c1 ? [algHashn([mySecret(id)])] : []),
  joinGate: (gm) => gm.cfg && !E.maskToKingdom(gm.cfg) ? T("kingdomBad", "⚠ invalid kingdom config — don't join this game") : null,
  canAct: (eng, me) => E.legalActor(eng) === me,
  // practice-vs-computer (duelgame.js SDK feature): direct local apply + the shared fuzz/oracle bot
  applyLocal(eng, side, enc, q) { eng._q = q; E.applyMove(eng, side, enc); eng.mi++; },
  botMove(eng, k) {
    const mv = randomMove(eng, prng((Math.floor(prand(this.practice.seed)() * 1e9) + k * 977) >>> 0));
    return mv && mv.side === 2 ? mv.enc : null;
  },
  turnOf: (eng) => E.legalActor(eng),
  resultOf: (eng) => eng.result,
  overHint: (eng) => T("finalScore", "Final score {a} : {b} VP.", { a: E.scoreOf(eng, 0), b: E.scoreOf(eng, 1) }),
  onReset() { dsel = new Set(); senD = [0, 0]; senSwap = 0; },
  onAdvance() { dsel = new Set(); senD = [0, 0]; senSwap = 0; },
  onSubmit() { dsel = new Set(); },
  shareText: (gm, id) => T("shareText", "Duel me at Stormhold for {stake}on NADO — game #{id}:", { stake: gm && gm.exists ? (Number(gm.stake) / 1e10) + " NADO " : "", id }),
  inviteTitle: T("inviteTitle", "You're invited to a Stormhold duel"),
  inviteBody: (gm) => T("inviteBody", "Duel {who} for <b>{amt} NADO</b> — winner takes the pot.", { who: disp(gm.p1), amt: Number(gm.stake) / 1e10 }),
  wire() { $("oppHandWrap").onclick = () => { peekOpp = !peekOpp; this.render(); }; wireKingdomPicker();
    if ($("hiddenToggle")) $("hiddenToggle").onchange = (e) => { hiddenWant = !!e.target.checked; }; },
  renderGame,
});

const eng_ = () => duel.eng;
const topFrame = () => { const e = eng_(); return e && e.frames && e.frames.length ? e.frames[e.frames.length - 1] : null; };
const decide = (payload, label) => duel.submit(5, payload, label);

// ---- interaction: hand / supply taps -----------------------------------------------------------------
function onHandTap(idx) {
  const eng = eng_(); if (!duel.canAct()) return;
  const f = topFrame(), hand = eng.ps[duel.myIdx(duel.last)].hand, id = hand[idx];
  if (f && MASK_FRAMES[f.t]) { dsel.has(idx) ? dsel.delete(idx) : dsel.add(idx); duel.render(); return; }
  if (f && PICK_FRAMES[f.t]) {
    if ((f.t === "bur" || f.t === "burH") && !isV(id)) return notify(T("pickVictory", "Pick a Victory card."));
    if (f.t === "minT" && !isT(id)) return notify(T("pickTreasure", "Pick a Treasure."));
    if (f.t === "thr" && !isA(id)) return notify(T("pickAction", "Pick an Action card."));
    if (f.t === "burH") { decide(1 + 2 * encClaim(idx, id), "topdeck " + NAME(id)); return; }
    const claimed = hid() && (f.t === "thr" || f.t === "remT" || f.t === "minT");
    decide(claimed ? encClaim(idx, id) : idx, "choose " + NAME(id)); return;
  }
  if (f) return;
  if (eng.phase === 0 && isA(id)) {
    if (eng.actions < 1) return notify(T("noActions", "No actions left — play treasures or buy."));
    duel.submit(1, hid() ? encClaim(idx, id) : idx, "play " + NAME(id)); return;
  }
  if (isT(id)) { dsel.has(idx) ? dsel.delete(idx) : dsel.add(idx); duel.render(); return; }
  if (isA(id)) return notify(T("actionsOver", "The action phase is over this turn."));
  notify(T("victoryHint", "Victory cards score at the end — they can't be played."));
}
function onSupplyTap(id) {
  const eng = eng_(); if (!duel.canAct()) return;
  const f = topFrame();
  if (f && GAIN_FRAMES[f.t]) {
    const max = f.t === "wsh" ? 4 : f.t === "artG" ? 5 : f.max, tOnly = f.t === "minG";
    if (!E.gainable(eng, max, tOnly).includes(id)) return notify(T("cantGain", "That pile isn't eligible."));
    decide(id, "gain " + NAME(id)); return;
  }
  if (f) return;
  if (eng.buys < 1) return notify(T("noBuys", "No buys left this turn."));
  if (!(eng.supply[id] > 0)) return notify(T("pileEmpty", "That pile is empty."));
  if (eng.coins < E.CARDS[id].c) return notify(T("cantAfford", "Not enough coins — play your treasures first."));
  duel.arm("buy" + id, T("tapAgainBuy", "Tap {card} again to buy it for {cost} 🪙", { card: NAME(id), cost: E.CARDS[id].c }),
    () => duel.submit(3, id, "buy " + NAME(id)));
}
function playTreasures() {
  const eng = eng_(); if (!duel.canAct() || topFrame()) return;
  const hand = eng.ps[duel.myIdx(duel.last)].hand;
  let idxs = [...dsel];
  if (idxs.some((i) => !isT(hand[i]))) { dsel = new Set(); return duel.render(); }
  if (!idxs.length) idxs = hand.map((c, i) => (isT(c) ? i : -1)).filter((i) => i >= 0);
  if (!idxs.length) return;
  let payload = maskOf(new Set(idxs));
  if (hid()) {
    const cnt = { 0: 0, 1: 0, 2: 0 };
    idxs.forEach((i) => cnt[hand[i]]++);
    payload += 16777216 * (cnt[0] + 32 * cnt[1] + 1024 * cnt[2]);
  }
  duel.submit(2, payload, "play treasures");
}
function endTurn() {
  if (!duel.canAct() || topFrame()) return;
  duel.arm("end", T("tapAgainEnd", "Tap again to end your turn"), () => duel.submit(4, 0, "end turn"));
}

// ---- rendering -----------------------------------------------------------------------------------------
const tileCls = (id) => {
  const c = E.CARDS[id];
  return "ctile " + (c.t & E.T ? "ty-t" : c.t & E.V ? "ty-v" : c.t & E.CU ? "ty-c" : "ty-a")
    + (c.t & E.ATK ? " atk" : "") + (c.t & E.RE ? " re" : "");
};
const art = (id) => '<div class="cart">' + (ART[E.CARDS[id].k] || "") + "</div>";
const tile = (id) =>
  '<div class="' + tileCls(id) + '" title="' + (E.CARDS[id].txt || "") + '">'
  + '<span class="cost">' + E.CARDS[id].c + "</span>" + art(id)
  + '<div class="cname">' + NAME(id) + "</div></div>";

// ---- kingdom picker (game creator chooses the 10 piles; random stays the default) -----------------------
let kMask = 0;                          // the cfg word sent with open(); 0 = random kingdom
let kSel = new Set();                   // picker working selection (card ids 7..32)
const KINGDOM_IDS = Array.from({ length: 26 }, (_, i) => 7 + i);
// curated presets (original combos in the spirit of the genre's recommended first sets)
const K_PRESETS = () => [
  [T("kpStarter", "🏁 First duel"), [7, 28, 11, 17, 29, 9, 20, 21, 13, 14]],
  [T("kpBig", "🏗 Sprawl"), [32, 23, 15, 8, 25, 16, 30, 22, 31, 14]],
  [T("kpControl", "🔭 Deck control"), [32, 15, 24, 25, 10, 26, 18, 30, 12, 13]],
];
function kingdomStateLine() {
  const el = $("kingdomState"); if (!el) return;
  el.innerHTML = kMask === 0 ? T("kingdomRandom", "🎲 random (seeded at join)")
    : E.maskToKingdom(kMask).map((id) => NAME(id)).join(" · ");
}
function renderKingdomPicker() {
  const grid = $("kingdomGrid"); if (!grid) return;
  grid.innerHTML = KINGDOM_IDS.map((id) => {
    const s = kSel.has(id) ? " sel" : "";
    return '<div class="' + tileCls(id) + s + '" data-k="' + id + '" title="' + (E.CARDS[id].txt || "") + '">'
      + '<span class="cost">' + E.CARDS[id].c + "</span>" + art(id)
      + '<div class="cname">' + NAME(id) + "</div></div>";
  }).join("");
  grid.querySelectorAll("[data-k]").forEach((d) => d.onclick = () => {
    const id = parseInt(d.dataset.k, 10);
    if (kSel.has(id)) kSel.delete(id);
    else if (kSel.size < 10) kSel.add(id);
    else return notify(T("kingdomFull", "10 piles max — deselect one first."));
    renderKingdomPicker();
  });
  const use = $("btnKingdomUse");
  use.textContent = T("kingdomUse", "✓ Use these piles ({n}/10)", { n: kSel.size });
  use.disabled = kSel.size !== 10;
}
function wireKingdomPicker() {
  if (!$("btnKingdom")) return;
  $("btnKingdom").onclick = () => {
    $("kingdomPicker").classList.toggle("hidden");
    const pr = $("kingdomPresets");
    pr.innerHTML = "";
    for (const [label, ids] of K_PRESETS()) {
      const b = document.createElement("button"); b.className = "ghost"; b.textContent = label;
      b.onclick = () => { kSel = new Set(ids); renderKingdomPicker(); };
      pr.appendChild(b);
    }
    renderKingdomPicker();
  };
  $("btnKingdomUse").onclick = () => {
    if (kSel.size !== 10) return;
    kMask = E.kingdomToMask([...kSel]);
    $("kingdomPicker").classList.add("hidden");
    kingdomStateLine();
  };
  $("btnKingdomRandom").onclick = () => { kMask = 0; kSel = new Set(); $("kingdomPicker").classList.add("hidden"); kingdomStateLine(); };
  kingdomStateLine();
}

function renderSupply(gm, eng) {
  const el = $("supply"); if (!el || !eng || eng.setup) { if (el) el.innerHTML = ""; return; }
  const f = topFrame(), me = duel.myIdx(gm), act = duel.canAct();
  let eligible = null;
  if (act && f && GAIN_FRAMES[f.t] && f.p === me) {
    eligible = new Set(E.gainable(eng, f.t === "wsh" ? 4 : f.t === "artG" ? 5 : f.max, f.t === "minG"));
  }
  const order = [E.COPPER, E.SILVER, E.GOLD, E.HOMESTEAD, E.VALLEY, E.CITADEL, E.BLIGHT].concat(eng.kingdom);
  el.innerHTML = order.map((id) => {
    const n = eng.supply[id] || 0, c = E.CARDS[id];
    const buyable = act && !f && eng.buys > 0 && n > 0 && eng.coins >= c.c;
    const gainOk = eligible && eligible.has(id);
    const cls = (n === 0 ? " dis" : "") + (gainOk ? " sel" : buyable ? " buyable" : "")
      + (duel.armed && duel.armed.key === "buy" + id ? " armed" : "");
    return '<div class="' + tileCls(id) + cls + '" data-sid="' + id + '" title="' + (c.txt || "") + '">'
      + '<span class="cost">' + c.c + '</span><span class="cnt">' + n + "</span>" + art(id)
      + '<div class="cname">' + c.n + "</div>"
      + (c.txt ? '<div class="ctxt">' + c.txt + "</div>" : (c.coin ? '<div class="ctxt">🪙 ' + c.coin + "</div>" : c.vp != null ? '<div class="ctxt">🏆 ' + c.vp + "</div>" : ""))
      + "</div>";
  }).join("");
  el.querySelectorAll("[data-sid]").forEach((d) => d.onclick = () => onSupplyTap(parseInt(d.dataset.sid, 10)));
}

function decisionPrompt(gm, eng, f) {
  const me = duel.myIdx(gm), mine = f.p === me;
  const who = mine ? "" : T("oppDeciding", "Waiting for {who} to decide — ", { who: disp(f.p === 0 ? gm.p1 : gm.p2) });
  // LAZY table: each entry is a thunk — eager evaluation crashed on frame-specific fields
  // (e.g. NAME(f.atk) exists only for moat frames) and killed the whole decision bar.
  const P = {
    cel: () => T("dCel", "Winnow: select any cards to discard, then draw that many."),
    chp: () => T("dChp", "Purifier: select up to 4 cards to trash."),
    har: () => T("dHar", "Undertow: you may put a card from your discard pile on top of your deck."),
    vas: () => T("dVas", "Whirlwind revealed {card} — play it?", { card: f.card != null ? NAME(f.card) : "" }),
    mil: () => T("dMil", "Raiders attack! Select {n} card(s) to discard (down to 3).", { n: Math.max(0, (eng.ps[f.p].hand.length - 3)) }),
    bur: () => T("dBur", "Collector attack! Tap a Victory card to put on top of your deck."),
    ban: () => T("dBan", "Storm Riders attack! Tap the revealed treasure to trash."),
    mon: () => T("dMon", "Smelter: trash a Copper for +3 🪙?"),
    poa: () => T("dPoa", "Drifter: select {n} card(s) to discard.", { n: f.n }),
    remT: () => T("dRemT", "Reforge: tap a card to trash (you'll gain up to its cost +2)."),
    remG: () => T("dRemG", "Reforge: tap a supply pile costing up to {max} to gain.", { max: f.max }),
    thr: () => T("dThr", "Echo: tap an Action card to play it twice."),
    minT: () => T("dMinT", "Refinery: tap a Treasure to trash (gain one costing up to +3, to your hand)."),
    minG: () => T("dMinG", "Refinery: tap a Treasure pile costing up to {max} — it goes to your hand.", { max: f.max }),
    sen: () => T("dSen", "Skywatch: choose what happens to your top card(s)."),
    lib: () => T("dLib", "Almanac revealed {card} — keep it in hand or set it aside?", { card: f.card != null ? NAME(f.card) : "" }),
    artG: () => T("dArtG", "Atelier: tap a pile costing up to 5 — the card goes to your hand."),
    artT: () => T("dArtT", "Atelier: tap a hand card to put on top of your deck."),
    wsh: () => T("dWsh", "Foundry: tap a supply pile costing up to 4 to gain."),
    moat: () => T("dMoat", "{card} attacks you — reveal your Windbreak to be unaffected?", { card: NAME(f.atk) }),
    vasH: () => (mine && f.card != null && f.card !== E.UNKNOWN)
      ? T("dVas", "Whirlwind revealed {card} — play it?", { card: NAME(f.card) })
      : T("dVasH", "Whirlwind: deciding on the revealed top card…"),
    burH: () => T("dBurH", "Collector attack! Tap a Victory card to put on your deck — or reveal a hand without one."),
    banH: () => T("dBan", "Storm Riders attack! Tap the revealed treasure to trash."),
  };
  return who + (P[f.t] ? P[f.t]() : f.t);
}
// hidden games: once the log says GAME OVER, both secrets must be revealed on-chain before anyone can
// score it — this bar drives that: reveal mine → wait for theirs → verified verdict (result or CHEATER).
function renderReveal(gm, eng) {
  const el = $("revealBar"); if (!el) return;
  el.innerHTML = "";
  if (!eng || !gm || !isHiddenGame(gm) || !eng.over || gm.settled) return;
  const me = duel.myIdx(gm);
  const myR = me === 0 ? gm.r1 : gm.r2, theirR = me === 0 ? gm.r2 : gm.r1;
  if (gm.r1 && gm.r2) {
    if (eng.cheater) {
      const iCheated = eng.cheater - 1 === me;
      el.innerHTML = '<div class="dp" style="color:var(--danger)">' + (iCheated
        ? T("youCheatFlag", "⚠ Your claims failed verification — the game is void; your opponent will claim the refund.")
        : T("oppCheatFlag", "🚨 {who} CHEATED — a claim failed verification. Don't agree to anything: claim the refund when the move clock runs out.", { who: disp(eng.cheater === 1 ? gm.p1 : gm.p2) }))
        + "</div>";
    }
    return;                                              // verified honest game: the normal settle chrome applies
  }
  if (me == null) { el.innerHTML = '<div class="dp">' + T("revealWait", "Waiting for the players to reveal their hands…") + "</div>"; return; }
  const b = document.createElement("button");
  if (!myR) {
    b.className = "primary"; b.textContent = T("revealBtn", "🔓 Reveal your hand — settle the game");
    b.onclick = () => dapp.call("reveal", [gm.id, mySecret(gm.id)], null,
      T("revealDesc", "reveal your Stormhold hand · game #{g}", { g: gm.id }), { game: gm.id, phase: "reveal" });
    el.innerHTML = '<div class="dp">' + T("revealMine", "Game over — reveal your hand so the result can be verified.") + "</div>";
    el.appendChild(b);
  } else if (!theirR) {
    el.innerHTML = '<div class="dp">' + T("revealTheirs", "✓ Your hand is revealed — waiting for your opponent (the refund clock protects you if they stall).") + "</div>";
  }
}

function renderDecision(gm, eng) {
  const el = $("decision"); if (!el) return;
  const f = topFrame(), me = duel.myIdx(gm);
  if (!eng || !f || eng.over || eng.corrupt) { el.innerHTML = ""; return; }
  const mine = f.p === me && duel.canAct();
  let btns = "";
  const B = (id, label, primary, disabled) => '<button id="' + id + '" class="' + (primary ? "primary" : "ghost") + '"' + (disabled ? " disabled" : "") + ">" + label + "</button>";
  if (mine) {
    if (MASK_FRAMES[f.t]) {
      const need = f.t === "mil" ? Math.max(0, eng.ps[f.p].hand.length - 3) : f.t === "poa" ? f.n : null;
      const ok = need == null ? (f.t === "chp" ? dsel.size <= 4 : true) : dsel.size === need;
      btns = B("dConfirm", T("dConfirmN", "Confirm ({n} selected)", { n: dsel.size }), ok, !ok);
    } else if (f.t === "vas") btns = B("dYes", T("playIt", "▶ Play it"), 1) + B("dNo", T("discardIt", "Discard it"));
    else if (f.t === "vasH") btns = (f.card !== E.UNKNOWN && isA(f.card) ? B("dYes", T("playIt", "▶ Play it"), 1) : "") + B("dNo", T("discardIt", "Discard it"));
    else if (f.t === "burH") { if (!eng.ps[f.p].hand.some(isV)) btns = B("dNoVic", T("revealNoVictory", "Reveal — no Victory cards"), 1); }
    else if (f.t === "banH") {
      btns = f.cards.map((c, i) => {
        const ok = isT(c) && c !== E.COPPER;
        return '<button class="' + (ok ? "primary" : "ghost") + '" data-banh="' + i + '" ' + (ok ? "" : "disabled") + ">🔥 " + NAME(c) + "</button>";
      }).join("");
      if (!f.cards.some((c) => isT(c) && c !== E.COPPER)) btns += B("dBanNone", T("nothingToTrash", "Nothing to trash — continue"), 1);
    }
    else if (f.t === "lib") btns = B("dNo", T("keepIt", "Keep in hand"), 1) + B("dYes", T("setAside", "Set aside"));
    else if (f.t === "mon") btns = B("dYes", T("trashCopper", "🔥 Trash a Copper (+3 🪙)"), 1) + B("dNo", T("skip", "Skip"));
    else if (f.t === "moat") btns = B("dYes", T("revealBlock", "🛡 Reveal — block the attack"), 1) + B("dNo", T("takeHit", "Take the hit"));
    else if (f.t === "har") {
      btns = eng.ps[f.p].disc.map((c, i) => '<button class="ghost" data-har="' + (i + 1) + '">' + NAME(c) + "</button>").join("")
        + B("dNo", T("skip", "Skip"));
    } else if (f.t === "ban") {
      btns = f.cards.map((c, i) => {
        const ok = isT(c) && c !== E.COPPER;
        return '<button class="' + (ok ? "primary" : "ghost") + '" data-ban="' + i + '" ' + (ok ? "" : "disabled") + ">🔥 " + NAME(c) + "</button>";
      }).join("");
    } else if (f.t === "sen") {
      const LBL = [T("senKeep", "⬆ keep"), T("senDiscard", "🗑 discard"), T("senTrash", "🔥 trash")];
      btns = f.cards.map((c, i) => '<button class="ghost" data-sen="' + i + '">' + NAME(c) + " · " + LBL[senD[i]] + "</button>").join("");
      if (f.cards.length === 2 && senD[0] === 0 && senD[1] === 0)
        btns += '<button class="ghost" id="dSwap">' + (senSwap ? T("senOrd2", "order: 2nd on top") : T("senOrd1", "order: 1st on top")) + "</button>";
      btns += B("dConfirm", T("confirm", "Confirm"), 1);
    } else if (f.t === "thr" || f.t === "minT") btns = B("dNo", T("skip", "Skip"));
    else if (GAIN_FRAMES[f.t]) {
      const max = f.t === "wsh" ? 4 : f.t === "artG" ? 5 : f.max;
      if (!E.gainable(eng, max, f.t === "minG").length) btns = B("dSkipGain", T("nothingToGain", "Nothing to gain — continue"), 1);
    }
  }
  el.innerHTML = '<div class="dp">' + decisionPrompt(gm, eng, f) + "</div>" + (btns ? '<div id="decisionBtns">' + btns + "</div>" : "");
  if (!mine) return;
  const on = (id, fn) => { const b = el.querySelector("#" + id); if (b) b.onclick = fn; };
  on("dConfirm", () => {
    if (f.t === "sen") decide(senD[0] + 3 * (senD[1] || 0) + 9 * (senD[0] === 0 && senD[1] === 0 && f.cards.length === 2 ? senSwap : 0), "skywatch");
    else decide(maskOf(dsel), "confirm");
  });
  on("dYes", () => decide(f.t === "vasH" ? 1 + 2 * f.card : 1, "yes"));
  on("dNoVic", () => decide(0, "reveal none"));
  on("dBanNone", () => { const b = 3 * (f.cards[0] + 64 * (f.cards[1] ?? 0)); decide(2 + b, "continue"); });
  on("dNo", () => decide(f.t === "har" ? 0 : f.t === "thr" || f.t === "minT" ? SKIP : 0, "skip"));
  on("dSkipGain", () => decide(SKIP, "skip gain"));
  on("dSwap", () => { senSwap = 1 - senSwap; duel.render(); });
  el.querySelectorAll("[data-har]").forEach((b) => b.onclick = () => decide(parseInt(b.dataset.har, 10), "topdeck"));
  el.querySelectorAll("[data-ban]").forEach((b) => b.onclick = () => decide(parseInt(b.dataset.ban, 10), "trash"));
  el.querySelectorAll("[data-banh]").forEach((b) => b.onclick = () => {
    const base = 3 * (f.cards[0] + 64 * (f.cards[1] ?? 0));
    decide(parseInt(b.dataset.banh, 10) + base, "trash");
  });
  el.querySelectorAll("[data-sen]").forEach((b) => b.onclick = () => { const i = parseInt(b.dataset.sen, 10); senD[i] = (senD[i] + 1) % 3; duel.render(); });
}

function fmtEv(gm, e) {
  const me = duel.myIdx(gm);
  const who = e.p === me ? T("you", "You") : disp(e.p === 0 ? gm.p1 : gm.p2);
  const c = e.c != null ? NAME(e.c) : "";
  const M = {
    play: T("lPlay", "{w} plays {c}"), play2: T("lPlay2", "{w} plays {c} (again)"), playT: T("lPlayT", "{w} plays {c}"),
    buy: T("lBuy", "{w} buys {c}"), gain: T("lGain", "{w} gains {c}"), gaindeck: T("lGainDeck", "{w} gains {c} onto their deck"),
    curse: T("lBlight", "{w} gains a Blight"), trash: T("lTrash", "{w} trashes {c}"),
    discard: T("lDiscardN", "{w} discards {n} card(s)"), discard1: T("lDiscard1", "{w} discards {c}"),
    draw: T("lDraw", "{w} draws {n} card(s)"), shuffle: T("lShuffle", "{w} shuffles their deck"),
    topdeck: T("lTopdeck", "{w} puts {c} on their deck"), reveal: T("lReveal", "{w} reveals a hand with no Victory cards"),
    reveal2: T("lReveal2", "{w} reveals their top {n} card(s)"), revealc: T("lRevealC", "{w} reveals {c}"),
    immune: T("lImmune", "{w} reveals Windbreak — attack blocked"), merchant: T("lHawker", "{w} gets +{n} 🪙 from Hawker"),
    endturn: T("lEndTurn", "{w} ends turn {n}"), gameover: T("lGameOver", "— game over —"),
    supplyout: T("lSupplyOut", "the {c} pile is empty"),
  };
  return (M[e.ev] || e.ev).replace("{w}", who).replace("{c}", c).replace("{n}", String(e.n != null ? e.n : ""));
}

// the DuelGame renderGame hook — everything between the status line and the settle buttons
function renderGame(gm, eng) {
  const me = duel.myIdx(gm);
  const hud = $("hud");
  if (eng && !eng.setup && gm.nn === 2) {
    const turnWho = eng.turn === me ? T("yourTurn", "YOUR TURN") : T("theirTurn", "{who}'s turn", { who: disp(eng.turn === 0 ? gm.p1 : gm.p2) });
    hud.innerHTML =
      '<span class="turnbadge">' + turnWho + " · " + (eng.phase === 0 ? T("phaseAction", "action phase") : T("phaseBuy", "buy phase")) + "</span>"
      + '<span class="stat">' + T("actions", "Actions") + " <b>" + eng.actions + "</b></span>"
      + '<span class="stat">' + T("buys", "Buys") + " <b>" + eng.buys + "</b></span>"
      + '<span class="stat">🪙 <b>' + eng.coins + "</b></span>"
      + (me != null ? '<span class="stat vp">' + T("vpYou", "Your VP") + " <b>" + E.scoreOf(eng, me) + "</b></span>"
          + '<span class="stat vp">' + T("vpThem", "Their VP") + " <b>" + (isHiddenGame(gm) && !(gm.r1 && gm.r2) ? "?" : E.scoreOf(eng, 1 - me)) + "</b></span>"
        : '<span class="stat vp">VP <b>' + E.scoreOf(eng, 0) + " : " + E.scoreOf(eng, 1) + "</b></span>")
      + (isHiddenGame(gm) ? '<span class="stat">🂠 ' + T("hiddenBadge", "hidden hands") + "</span>" : "");
  } else hud.innerHTML = "";
  renderReveal(gm, eng);
  renderDecision(gm, eng);
  renderSupply(gm, eng);
  const oz = $("oppZone");
  if (eng && !eng.setup && gm.nn === 2) {
    oz.classList.remove("hidden");
    const op = me != null ? 1 - me : 1, zo = eng.ps[op];
    $("oppHead").textContent = disp(op === 0 ? gm.p1 : gm.p2);
    $("oppCounts").textContent = T("counts", "deck {d} · discard {x} · hand {h}", { d: zo.deck.length, x: zo.disc.length, h: zo.hand.length });
    $("oppHand").innerHTML = peekOpp ? zo.hand.map((c) => tile(c)).join("") : zo.hand.map(() => '<span class="mc"></span>').join("");
    $("oppHand").className = peekOpp ? "handrow" : "mini";
    // While it's their turn: the live play area. Otherwise: what they played/bought LAST turn — a bot
    // (practice) resolves its whole turn between two renders, and on-chain you usually poll after the
    // turn passed, so without this the opponent's cards were never visible at all.
    if (eng.turn === op) $("oppPlay").innerHTML = zo.play.map((c) => tile(c)).join("");
    else {
      const L = eng.log, cards = [];
      let end = -1;
      for (let i = L.length - 1; i >= 0; i--) if (L[i].ev === "endturn" && L[i].p === op) { end = i; break; }
      for (let i = end - 1; i >= 0; i--) {
        const e = L[i];
        if (e.ev === "endturn") break;
        if (e.p === op && e.c != null && (e.ev === "play" || e.ev === "play2" || e.ev === "playT" || e.ev === "buy")) cards.unshift(e.c);
      }
      $("oppPlay").innerHTML = cards.length
        ? '<span class="small dim" style="align-self:center;margin-right:4px">' + T("lastTurn", "last turn:") + "</span>" + cards.map((c) => tile(c)).join("")
        : "";
    }
    const mp = me != null ? me : 0, zm = eng.ps[mp];
    $("myHead").textContent = me != null ? T("yourHand", "Your hand") : disp(gm.p1);
    $("myCounts").textContent = T("counts", "deck {d} · discard {x} · hand {h}", { d: zm.deck.length, x: zm.disc.length, h: zm.hand.length });
    $("myPlay").innerHTML = eng.turn === mp && zm.play.length ? zm.play.map((c) => tile(c)).join("") : "";
    const f = topFrame(), selectable = duel.canAct();
    $("hand").innerHTML = zm.hand.map((c, i) => {
      let cls = "";
      if (dsel.has(i)) cls = " sel";
      else if (selectable && !f && eng.phase === 0 && eng.actions > 0 && isA(c)) cls = " buyable";
      return '<div class="' + tileCls(c) + cls + '" data-h="' + i + '" title="' + (E.CARDS[c].txt || "") + '">'
        + '<span class="cost">' + E.CARDS[c].c + "</span>" + art(c)
        + '<div class="cname">' + NAME(c) + "</div>"
        + (E.CARDS[c].txt ? '<div class="ctxt">' + E.CARDS[c].txt + "</div>" : (E.CARDS[c].coin ? '<div class="ctxt">🪙 ' + E.CARDS[c].coin + "</div>" : '<div class="ctxt">🏆 ' + (E.CARDS[c].vp || 0) + "</div>"))
        + "</div>";
    }).join("");
    $("hand").querySelectorAll("[data-h]").forEach((d) => d.onclick = () => onHandTap(parseInt(d.dataset.h, 10)));
    const hb = $("handBtns"); hb.innerHTML = "";
    if (selectable && !f) {
      const anyT = zm.hand.some(isT);
      const btn = (txt, fn, primary, aid) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.textContent = txt; b.onclick = fn; if (aid && duel.armed && duel.armed.key === aid) { b.classList.add("pulse"); b.textContent = duel.armed.label; } hb.appendChild(b); };
      if (anyT) btn(dsel.size ? T("playSelT", "🪙 Play selected treasures ({n})", { n: dsel.size }) : T("playAllT", "🪙 Play all treasures"), playTreasures, eng.phase === 1 || !zm.hand.some(isA));
      btn(T("endTurn", "⏭ End turn"), endTurn, false, "end");
    }
    $("trashLine").textContent = eng.trash.length ? T("trashN", "trash: {n}", { n: eng.trash.length }) : "";
    $("logPane").innerHTML = eng.log.slice(-14).map((e) => '<div class="' + (e.p === me ? "me" : "") + '">' + fmtEv(gm, e) + "</div>").join("");
    const lp = $("logPane"); lp.scrollTop = lp.scrollHeight;
  } else {
    oz.classList.add("hidden");
    $("hand").innerHTML = ""; $("myPlay").innerHTML = ""; $("handBtns").innerHTML = ""; $("logPane").innerHTML = ""; $("supply").innerHTML = "";
    $("myCounts").textContent = ""; $("trashLine").textContent = "";
    // pre-join preview: the creator picked these 10 piles — the joiner sees exactly what they'd play
    if (gm && gm.exists && gm.nn === 1 && gm.cfg) {
      const pick = E.maskToKingdom(gm.cfg);
      $("supply").innerHTML = pick
        ? '<div class="small dim" style="flex-basis:100%">' + T("kingdomPreview", "⚒ The creator picked this kingdom:") + "</div>" + pick.map((id) => tile(id)).join("")
        : '<span class="small dim">' + T("kingdomBad", "⚠ invalid kingdom config — don't join this game") + "</span>";
    }
  }
}

duel.boot(["activeGame", "lobby", "play", "walletcard", "bankroll", "scoreboard"]);

// test hook: the UI E2E harness (tests/*_ui_e2e.mjs) drives the real DOM against crafted engine states
if (typeof window !== "undefined") window.__duel = duel;

faucetAttach(dapp, "stormhold", $("faucetBar"));

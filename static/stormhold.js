// stormhold.js — NADO Stormhold: a 2-player deck-building strategy duel for stakes on the execution layer,
// built on the shared SDK (nadodapp.js) and the headless-tested rules engine (stormhold-engine.js). The
// contract is the chess model — escrow + ordered on-chain move log + mutual-agreement settle — extended
// with per-move SEED HEIGHTS: every move pins a future L1 block hash, and the engine derives every shuffle
// from it, so both browsers replay byte-identical games and no shuffle can be rigged (the mover signed
// before the seed block existed). All information is public on-chain (open-hand play); what makes it a
// game of skill is the deck-building itself.
import { NadoDapp, rawToNado, nadoToRaw, randId, rematchId, _m, $, base, canPay, alertBar, orderCards,
         resolveAliases, disp, share, wireWallet, inviteGate, stickyInputs, renderWallet, notify,
         blocksToTime } from "./nadodapp.js";
import * as E from "./stormhold-engine.js";

const CID = "9f66d438dcbc87adc748f0cbe13a701b";
const dapp = new NadoDapp({ cid: CID, app: "Stormhold" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("storm." + k, d, v) : d;
const LS_G = "nado_stormhold_games";
const load = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const save = (v) => { try { localStorage.setItem(LS_G, JSON.stringify(v)); } catch {} };
const MAPS = ["wr", "mv", "mh", "mc", "p2", "nn", "a1", "a2", "kh", "dl"];
const SKIP = 4095;

let activeGame = null, lastGame = null, lastSto = null, eng = null, haveState = false;
let pendingMove = null;            // {ply} — input locked until the chain reflects it
let dsel = new Set();              // multi-select (mask frames / treasure picking)
let senD = [0, 0], senSwap = 0;    // Skywatch chooser
let armed = null;                  // {key,label} double-tap confirm for buys / end turn
let peekOpp = false, lastMi = -1, lastDrawOffer = null, nudgeJoin = false;
let knownGames = new Set();

const isA = (id) => !!(E.CARDS[id].t & E.A), isT = (id) => !!(E.CARDS[id].t & E.T), isV = (id) => !!(E.CARDS[id].t & E.V);
const NAME = (id) => E.CARDS[id].n;
const maskOf = (set) => [...set].reduce((m, i) => m + 2 ** i, 0);

function pruneAndTrack(sto) {
  knownGames = new Set(Object.keys(_m(sto, "nn")));
  const G = load(); let c = false;
  for (const g of Object.keys(G)) if (!knownGames.has(g) && Date.now() - (G[g].ts || 0) > 600000) { delete G[g]; c = true; }
  if (c) save(G);
}

// ---- reads -----------------------------------------------------------------------------------------
function gameHead(sto, g) {
  g = String(g); const nn = _m(sto, "nn")[g] || 0;
  if (!nn) return { exists: false, id: Number(g) };
  return { exists: true, id: Number(g), p1: _m(sto, "p1")[g], p2: _m(sto, "p2")[g] || null,
    stake: _m(sto, "st")[g] || 0, pot: _m(sto, "pt")[g] || 0, nn, settled: !!_m(sto, "sd")[g],
    dl: _m(sto, "dl")[g] || 0, mc: _m(sto, "mc")[g] || 0, kh: _m(sto, "kh")[g] || 0,
    a1: _m(sto, "a1")[g] || 0, a2: _m(sto, "a2")[g] || 0, wr: _m(sto, "wr")[g] || 0 };
}
function gameFrom(sto, g) {
  const h = gameHead(sto, g);
  if (!h.exists) return h;
  const mv = _m(sto, "mv"), mh = _m(sto, "mh");
  h.recs = [];
  for (let i = 0; i < h.mc; i++) {
    const enc = mv[String(h.id * 10000 + i)], rec = mh[String(h.id * 10000 + i)];
    if (!enc || !rec) { h.gap = true; break; }            // provisional read raced the log — retry next poll
    h.recs.push({ enc, side: rec % 4, rh: Math.floor(rec / 4) });
  }
  return h;
}
const qOf = (h) => { const a = dapp.bh(h), b = dapp.bh(h + 1); return a && b ? BigInt("0x" + a) + BigInt("0x" + b) : null; };
async function ensureSeeds(gm) {
  const want = [];
  const add = (h) => { if (h && dapp.cursor != null && dapp.cursor >= h + 1) { want.push(h, h + 1); } };
  add(gm.kh);
  for (const r of gm.recs || []) add(r.rh);
  const missing = [...new Set(want)].filter((h) => dapp.bh(h) === undefined);
  // shuffle seeds are PUBLIC randomness -> provisional (fast) is safe: a reorg just replays visibly
  if (missing.length) await dapp.blockHashes(missing.slice(0, 120), { fast: true });
}
function rebuild(gm) {
  if (!gm.exists || gm.nn < 2 || !gm.kh) return null;
  return E.replay(gm.id, qOf(gm.kh), (gm.recs || []).map((r) => ({ enc: r.enc, side: r.side, q: qOf(r.rh) })));
}
const myIdx = (gm) => gm && gm.p1 === dapp.me ? 0 : gm && gm.p2 === dapp.me ? 1 : null;
function canAct() {
  const gm = lastGame;
  if (!gm || !gm.exists || gm.nn !== 2 || gm.settled || pendingMove) return false;
  if (!eng || eng.setup || eng.blocked || eng.corrupt || eng.over || eng.mi !== gm.mc) return false;
  const me = myIdx(gm);
  return me != null && E.legalActor(eng) === me;
}

// ---- actions ---------------------------------------------------------------------------------------
function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) return alertBar(T("enterStake", "Enter a stake (NADO)."));
  if (!canPay(dapp, raw, T("whatOpen", "Opening this game"))) return;
  const g = randId(), G = load(); G[g] = { role: "p1", stake: raw.toString(), ts: Date.now() }; save(G);
  activeGame = g; resetLocal(); render();
  dapp.call("open", [g], raw, "open stormhold game #" + g + " · " + rawToNado(raw) + " NADO stake", { game: g, phase: "open" });
}
async function joinGame() {
  const g = parseInt($("joinId").value, 10);
  if (!g) return alertBar(T("enterGameId", "Enter a game ID (or pick one from the lobby)."));
  const sto = await dapp.storage({ append: MAPS });
  const gm = sto ? gameHead(sto, g) : null;
  if (!gm || !gm.exists) { alertBar(dapp.whereIs(T("gameWord", "game"), g)); if (gm) dapp.clearInvite(); return; }
  if (gm.nn >= 2 || gm.settled) { alertBar(T("fullOrFinished", "That game is full or finished.")); dapp.clearInvite(); return; }
  await dapp.refresh();
  const stake = BigInt(gm.stake);
  if (!canPay(dapp, stake, T("whatJoin", "Joining this game"))) { render(); return; }
  dapp.clearInvite();
  const G = load(); G[g] = { role: "p2", stake: stake.toString(), ts: Date.now() }; save(G);
  activeGame = g; resetLocal(); render();
  dapp.call("join", [g], stake, "join stormhold game #" + g + " · " + rawToNado(stake) + " NADO stake", { game: g, phase: "join" });
}
async function rematch() {
  const g = lastGame; if (!g || !g.exists) return;
  const stake = BigInt(g.stake);
  if (!canPay(dapp, stake, T("whatRematch", "A rematch"))) return;
  const rid = rematchId(activeGame);
  const sto = await dapp.storage({ append: MAPS });
  const rg = sto ? gameHead(sto, rid) : null;
  activeGame = rid; resetLocal(); haveState = false; $("joinId").value = String(rid);
  const G = load();
  if (rg && rg.exists && rg.nn === 1 && !rg.settled) {
    G[rid] = { role: "p2", stake: stake.toString(), ts: Date.now() }; save(G);
    dapp.call("join", [rid], stake, "join rematch stormhold #" + rid, { game: rid, phase: "join" });
  } else {
    G[rid] = { role: "p1", stake: stake.toString(), ts: Date.now() }; save(G);
    dapp.call("open", [rid], stake, "rematch stormhold #" + rid + " · " + rawToNado(stake) + " NADO stake", { game: rid, phase: "open" });
  }
  render();
}
function submit(op, payload, label) {
  const gm = lastGame; if (!canAct()) return;
  const enc = E.encMove(op, payload || 0), ply = gm.mc;
  pendingMove = { ply }; dsel = new Set(); armed = null;
  dapp.call("move", [activeGame, enc, ply], null, label + " · game #" + activeGame, { game: activeGame, phase: "move", ply });
  render();
}
const decide = (payload, label) => submit(5, payload, label);
const resignGame = () => dapp.call("resign", [activeGame], null, "resign game #" + activeGame, { game: activeGame, phase: "resign" });
const agree = (r) => dapp.call("agree", [activeGame, r], null, (r === 3 ? "agree a draw" : "confirm the result") + " · game #" + activeGame, { game: activeGame, phase: "agree" });
const abortGame = () => dapp.call("abort", [activeGame], null, "claim refund (stalled) · game #" + activeGame, { game: activeGame, phase: "abort" });
const cancelGame = () => dapp.call("cancel", [activeGame], null, "cancel game #" + activeGame, { game: activeGame, phase: "cancel" });
function resetLocal() { pendingMove = null; dsel = new Set(); senD = [0, 0]; senSwap = 0; armed = null; lastMi = -1; eng = null; }

// arm(key,label,fn): first tap arms (shows label), second tap within 6s fires — misclick guard for buys/end.
function arm(key, label, fn) {
  if (armed && armed.key === key && Date.now() - armed.ts < 6000) { armed = null; fn(); return; }
  armed = { key, label, ts: Date.now() };
  render();
}

// ---- refresh ---------------------------------------------------------------------------------------
async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage({ append: MAPS });
  if (sto) {
    lastSto = sto;
    pruneAndTrack(sto);
    if (activeGame != null) {
      const ng = gameFrom(sto, activeGame);
      const prog = (ng.settled ? 1e9 : 0) + (ng.nn || 0) * 100000 + (ng.mc || 0);
      if (dapp.accept("storm:" + activeGame, prog) && !ng.gap) {
        lastGame = ng;
        if (pendingMove != null && ng.mc > pendingMove.ply) pendingMove = null;
        if (ng.exists && ng.nn === 2) {
          await ensureSeeds(ng);
          eng = rebuild(ng);
          if (eng && eng.mi !== lastMi) { dsel = new Set(); senD = [0, 0]; senSwap = 0; armed = null; lastMi = eng.mi; }
        } else eng = null;
        haveState = true;
      }
    }
    dapp.settleInflight((f) => {
      const g = gameHead(sto, f.game);
      return f.phase === "open" ? g.exists
        : f.phase === "join" ? g.nn === 2
        : f.phase === "move" ? g.mc > (f.ply || 0)
        : f.phase === "cancel" ? (g.settled || !g.exists)
        : (g.settled || !g.exists);
    });
    renderLobby(sto);
  }
  await resolveAliases([dapp.me].concat(lastGame ? [lastGame.p1, lastGame.p2] : []).filter(Boolean));
  render();
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const games = Object.keys(_m(sto, "nn")).map((g) => gameHead(sto, g)).filter((g) => g.exists && !g.settled);
  games.sort((a, b) => (a.nn - b.nn) || (b.id - a.id));
  const shown = games.slice(0, 24);
  el.innerHTML = shown.length ? shown.map((g) => {
    const verb = g.nn < 2 ? T("joinSuffix", " · join") : T("watchSuffix", " · watch");
    return '<button class="chip ' + (g.nn < 2 ? "open" : "live") + '" data-g="' + g.id + '">' + (g.nn < 2 ? "🏰" : "▶") + " #" + g.id + " · " + rawToNado(g.stake) + " NADO" + verb + "</button>";
  }).join(" ") : '<span class="dim">' + T("noGamesLobby", "No games yet — open one above.") + "</span>";
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeGame = parseInt(b.dataset.g, 10); resetLocal(); haveState = false; $("joinId").value = b.dataset.g;
    notify(T("gameSelected", "Game #{id} selected.", { id: activeGame })); refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
}

// ---- interaction: hand / supply taps -----------------------------------------------------------------
const MASK_FRAMES = { cel: 1, chp: 1, mil: 1, poa: 1 };
const PICK_FRAMES = { bur: 1, remT: 1, minT: 1, thr: 1, artT: 1 };
const GAIN_FRAMES = { remG: 1, minG: 1, wsh: 1, artG: 1 };
const topFrame = () => (eng && eng.frames && eng.frames.length ? eng.frames[eng.frames.length - 1] : null);

function onHandTap(idx) {
  if (!canAct()) return;
  const f = topFrame(), hand = eng.ps[myIdx(lastGame)].hand, id = hand[idx];
  if (f && MASK_FRAMES[f.t]) { dsel.has(idx) ? dsel.delete(idx) : dsel.add(idx); render(); return; }
  if (f && PICK_FRAMES[f.t]) {
    if (f.t === "bur" && !isV(id)) return notify(T("pickVictory", "Pick a Victory card."));
    if (f.t === "minT" && !isT(id)) return notify(T("pickTreasure", "Pick a Treasure."));
    if (f.t === "thr" && !isA(id)) return notify(T("pickAction", "Pick an Action card."));
    decide(idx, "choose " + NAME(id)); return;
  }
  if (f) return;
  // normal turn
  if (eng.phase === 0 && isA(id)) {
    if (eng.actions < 1) return notify(T("noActions", "No actions left — play treasures or buy."));
    submit(1, idx, "play " + NAME(id)); return;
  }
  if (isT(id)) { dsel.has(idx) ? dsel.delete(idx) : dsel.add(idx); render(); return; }
  if (isA(id)) return notify(T("actionsOver", "The action phase is over this turn."));
  notify(T("victoryHint", "Victory cards score at the end — they can't be played."));
}
function onSupplyTap(id) {
  if (!canAct()) return;
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
  arm("buy" + id, T("tapAgainBuy", "Tap {card} again to buy it for {cost} 🪙", { card: NAME(id), cost: E.CARDS[id].c }),
    () => submit(3, id, "buy " + NAME(id)));
}
function playTreasures() {
  if (!canAct() || topFrame()) return;
  const hand = eng.ps[myIdx(lastGame)].hand;
  let idxs = [...dsel];
  if (idxs.some((i) => !isT(hand[i]))) { dsel = new Set(); return render(); }
  if (!idxs.length) idxs = hand.map((c, i) => (isT(c) ? i : -1)).filter((i) => i >= 0);
  if (!idxs.length) return;
  submit(2, maskOf(new Set(idxs)), "play treasures");
}
function endTurn() {
  if (!canAct() || topFrame()) return;
  arm("end", T("tapAgainEnd", "Tap again to end your turn"), () => submit(4, 0, "end turn"));
}

// ---- render ------------------------------------------------------------------------------------------
const tileCls = (id) => {
  const c = E.CARDS[id];
  return "ctile " + (c.t & E.T ? "ty-t" : c.t & E.V ? "ty-v" : c.t & E.CU ? "ty-c" : "ty-a")
    + (c.t & E.ATK ? " atk" : "") + (c.t & E.RE ? " re" : "");
};
const tile = (id, extra, badges) =>
  '<div class="' + tileCls(id) + (extra || "") + '" ' + (badges || "") + ' title="' + (E.CARDS[id].txt || "") + '">'
  + '<span class="cost">' + E.CARDS[id].c + "</span>"
  + '<div class="cname">' + NAME(id) + "</div></div>";

function renderSupply() {
  const el = $("supply"); if (!el || !eng || eng.setup) { if (el) el.innerHTML = ""; return; }
  const f = topFrame(), me = myIdx(lastGame), act = canAct();
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
      + (armed && armed.key === "buy" + id ? " armed" : "");
    return '<div class="' + tileCls(id) + cls + '" data-sid="' + id + '" title="' + (c.txt || "") + '">'
      + '<span class="cost">' + c.c + '</span><span class="cnt">' + n + "</span>"
      + '<div class="cname">' + c.n + "</div>"
      + (c.txt ? '<div class="ctxt">' + c.txt + "</div>" : (c.coin ? '<div class="ctxt">🪙 ' + c.coin + "</div>" : c.vp != null ? '<div class="ctxt">🏆 ' + c.vp + "</div>" : ""))
      + "</div>";
  }).join("");
  el.querySelectorAll("[data-sid]").forEach((d) => d.onclick = () => onSupplyTap(parseInt(d.dataset.sid, 10)));
}

function decisionPrompt(f) {
  const me = myIdx(lastGame);
  const mine = f.p === me;
  const who = mine ? "" : T("oppDeciding", "Waiting for {who} to decide — ", { who: disp(f.p === 0 ? lastGame.p1 : lastGame.p2) });
  const P = {
    cel: T("dCel", "Winnow: select any cards to discard, then draw that many."),
    chp: T("dChp", "Purifier: select up to 4 cards to trash."),
    har: T("dHar", "Undertow: you may put a card from your discard pile on top of your deck."),
    vas: T("dVas", "Whirlwind revealed {card} — play it?", { card: f.card != null ? NAME(f.card) : "" }),
    mil: T("dMil", "Raiders attack! Select {n} card(s) to discard (down to 3).", { n: Math.max(0, (eng.ps[f.p].hand.length - 3)) }),
    bur: T("dBur", "Collector attack! Tap a Victory card to put on top of your deck."),
    ban: T("dBan", "Storm Riders attack! Tap the revealed treasure to trash."),
    mon: T("dMon", "Smelter: trash a Copper for +3 🪙?"),
    poa: T("dPoa", "Drifter: select {n} card(s) to discard.", { n: f.n }),
    remT: T("dRemT", "Reforge: tap a card to trash (you'll gain up to its cost +2)."),
    remG: T("dRemG", "Reforge: tap a supply pile costing up to {max} to gain.", { max: f.max }),
    thr: T("dThr", "Echo: tap an Action card to play it twice."),
    minT: T("dMinT", "Refinery: tap a Treasure to trash (gain one costing up to +3, to your hand)."),
    minG: T("dMinG", "Refinery: tap a Treasure pile costing up to {max} — it goes to your hand.", { max: f.max }),
    sen: T("dSen", "Skywatch: choose what happens to your top card(s)."),
    lib: T("dLib", "Almanac revealed {card} — keep it in hand or set it aside?", { card: f.card != null ? NAME(f.card) : "" }),
    artG: T("dArtG", "Atelier: tap a pile costing up to 5 — the card goes to your hand."),
    artT: T("dArtT", "Atelier: tap a hand card to put on top of your deck."),
    wsh: T("dWsh", "Foundry: tap a supply pile costing up to 4 to gain."),
    moat: T("dMoat", "{card} attacks you — reveal your Windbreak to be unaffected?", { card: NAME(f.atk) }),
  };
  return who + (P[f.t] || f.t);
}
function renderDecision() {
  const el = $("decision"); if (!el) return;
  const f = topFrame(), me = myIdx(lastGame);
  if (!eng || !f || eng.over || eng.corrupt) { el.innerHTML = ""; return; }
  const mine = f.p === me && canAct();
  let btns = "";
  const B = (id, label, primary, disabled) => '<button id="' + id + '" class="' + (primary ? "primary" : "ghost") + '"' + (disabled ? " disabled" : "") + ">" + label + "</button>";
  if (mine) {
    if (MASK_FRAMES[f.t]) {
      const need = f.t === "mil" ? Math.max(0, eng.ps[f.p].hand.length - 3) : f.t === "poa" ? f.n : null;
      const ok = need == null ? (f.t === "chp" ? dsel.size <= 4 : true) : dsel.size === need;
      btns = B("dConfirm", T("dConfirmN", "Confirm ({n} selected)", { n: dsel.size }), ok, !ok);
    } else if (f.t === "vas") btns = B("dYes", T("playIt", "▶ Play it"), 1) + B("dNo", T("discardIt", "Discard it"));
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
  el.innerHTML = '<div class="dp">' + decisionPrompt(f) + "</div>" + (btns ? '<div id="decisionBtns">' + btns + "</div>" : "");
  if (!mine) return;
  const on = (id, fn) => { const b = el.querySelector("#" + id); if (b) b.onclick = fn; };
  on("dConfirm", () => {
    if (f.t === "sen") decide(senD[0] + 3 * (senD[1] || 0) + 9 * (senD[0] === 0 && senD[1] === 0 && f.cards.length === 2 ? senSwap : 0), "skywatch");
    else decide(maskOf(dsel), "confirm");
  });
  on("dYes", () => decide(1, "yes"));
  on("dNo", () => decide(f.t === "har" ? 0 : f.t === "thr" || f.t === "minT" ? SKIP : 0, "skip"));
  on("dSkipGain", () => decide(SKIP, "skip gain"));
  on("dSwap", () => { senSwap = 1 - senSwap; render(); });
  el.querySelectorAll("[data-har]").forEach((b) => b.onclick = () => decide(parseInt(b.dataset.har, 10), "topdeck"));
  el.querySelectorAll("[data-ban]").forEach((b) => b.onclick = () => decide(parseInt(b.dataset.ban, 10), "trash"));
  el.querySelectorAll("[data-sen]").forEach((b) => b.onclick = () => { const i = parseInt(b.dataset.sen, 10); senD[i] = (senD[i] + 1) % 3; render(); });
}

function fmtEv(e) {
  const gm = lastGame, me = myIdx(gm);
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

function render() {
  dapp.reflectUrl("game", activeGame);
  dapp.syncPctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, dapp.exec);
  const signedIn = renderWallet(dapp);
  $("play").classList.toggle("hidden", !signedIn);
  $("bankroll").classList.toggle("hidden", !signedIn);
  const G = load(), ids = Object.keys(G).sort((a, b) => G[b].ts - G[a].ts).slice(0, 8);
  $("recent").innerHTML = ids.length ? ids.map((g) => { const live = knownGames.has(String(g)); let tag = "";
    if (live && lastSto) { const gm = gameHead(lastSto, g); if (gm.exists) tag = gm.settled ? T("tagFinished", " · finished ✓") : gm.nn < 2 ? T("tagWaiting", " · waiting for opponent") : T("tagLive", " · live"); }
    return '<button class="chip' + (live ? "" : " pending") + '" data-g="' + g + '">🏰 #' + g + (live ? tag : T("confirmingTag", " · confirming ⏳")) + "</button>"; }).join(" ")
    : '<span class="dim">' + T("noGames", "No games yet.") + "</span>";
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeGame = parseInt(b.dataset.g, 10); resetLocal(); haveState = false; refreshActive(); });
  renderActive();
}

function renderActive() {
  const box = $("activeGame");
  if (activeGame == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const gm = lastGame || {}, local = load()[activeGame] || {}, me = myIdx(gm);
  $("gameId").textContent = "#" + activeGame;
  $("shareLink").value = base() + "/?game=" + activeGame;
  $("gPot").textContent = gm.exists ? rawToNado(gm.pot) + " NADO" : (local.stake ? rawToNado(BigInt(local.stake) * 2n) + " NADO" : "—");
  const n1 = gm.p1 ? disp(gm.p1) + (gm.p1 === dapp.me ? T("youSuffix", " (you)") : "") : "—";
  const n2 = gm.p2 ? disp(gm.p2) + (gm.p2 === dapp.me ? T("youSuffix", " (you)") : "") : T("waitingDots", "waiting…");
  $("players").innerHTML = '<span class="chip">🏰 ' + n1 + '</span> <span class="chip">⚔ ' + n2 + "</span>";
  if (nudgeJoin && gm.exists && gm.nn === 1 && me == null) {
    nudgeJoin = false;
    alertBar(T("notJoined", "Signed in — but you have NOT joined yet. Tap “Join this game” to take the seat and stake {amt} NADO.", { amt: rawToNado(gm.stake) }));
  }

  // ---- status line -------------------------------------------------------------------------------
  let st = dapp.whereIs(T("gameWord", "game"), activeGame, local.ts);
  const live = gm.exists && gm.nn === 2 && !gm.settled;
  const over = eng && eng.over, rc = over ? eng.result : 0;
  if (gm.exists && gm.settled) {
    const seat = gm.wr === 1 ? T("host", "the host") : T("challenger", "the challenger");
    st = gm.wr === 3 ? T("drawRefunded", "✓ Draw — stakes refunded")
      : gm.wr ? (((gm.wr === 1 && me === 0) || (gm.wr === 2 && me === 1)) ? T("winYou", "✓ You won the pot! 🏆")
        : me != null ? T("winLost", "✓ You lost — {seat} takes the pot", { seat }) : T("winNeutral", "✓ {seat} wins", { seat }))
      : T("settled", "✓ settled");
  }
  else if (gm.exists && eng && eng.corrupt) st = T("illegal", "⚠ an illegal move reached the chain — this game refunds after the timeout.");
  else if (gm.exists && gm.nn < 2) st = me != null ? T("waitingShare", "waiting for an opponent — share the link below") : T("openSeat", "open seat — join to play for {amt} NADO", { amt: rawToNado(gm.stake) });
  else if (eng && (eng.setup || eng.blocked)) st = T("shuffling", "🌀 shuffling — waiting for the randomness block…");
  else if (eng && eng.mi < gm.mc) st = T("catchingUp", "replaying the on-chain log…");
  else if (over) st = rc === 3 ? T("overDraw", "Game over — it's a draw") :
    ((rc === 1 && me === 0) || (rc === 2 && me === 1)) ? T("overWin", "Game over — YOU WIN 🏆") :
    me != null ? T("overLose", "Game over — you lost") : T("overNeutral", "Game over");
  else if (live && eng) {
    const actor = E.legalActor(eng);
    const mine = actor === me;
    st = mine ? (pendingMove ? T("moveConfirming", "your move is confirming…") : T("yourMove", "▶ YOUR MOVE"))
      : T("waitingFor", "waiting for {who}…", { who: disp(actor === 0 ? gm.p1 : gm.p2) });
  }
  $("gStatus").innerHTML = st;

  // ---- HUD + zones ---------------------------------------------------------------------------------
  const hud = $("hud");
  if (eng && !eng.setup && gm.nn === 2) {
    const turnWho = eng.turn === me ? T("yourTurn", "YOUR TURN") : T("theirTurn", "{who}'s turn", { who: disp(eng.turn === 0 ? gm.p1 : gm.p2) });
    hud.innerHTML =
      '<span class="turnbadge">' + turnWho + " · " + (eng.phase === 0 ? T("phaseAction", "action phase") : T("phaseBuy", "buy phase")) + "</span>"
      + '<span class="stat">' + T("actions", "Actions") + " <b>" + eng.actions + "</b></span>"
      + '<span class="stat">' + T("buys", "Buys") + " <b>" + eng.buys + "</b></span>"
      + '<span class="stat">🪙 <b>' + eng.coins + "</b></span>"
      + (me != null ? '<span class="stat vp">' + T("vpYou", "Your VP") + " <b>" + E.scoreOf(eng, me) + "</b></span>"
          + '<span class="stat vp">' + T("vpThem", "Their VP") + " <b>" + E.scoreOf(eng, 1 - me) + "</b></span>"
        : '<span class="stat vp">VP <b>' + E.scoreOf(eng, 0) + " : " + E.scoreOf(eng, 1) + "</b></span>");
  } else hud.innerHTML = "";
  renderDecision();
  renderSupply();

  // opponent zone (or the "other" player for spectators)
  const oz = $("oppZone");
  if (eng && !eng.setup && gm.nn === 2) {
    oz.classList.remove("hidden");
    const op = me != null ? 1 - me : 1, zo = eng.ps[op];
    $("oppHead").textContent = disp(op === 0 ? gm.p1 : gm.p2);
    $("oppCounts").textContent = T("counts", "deck {d} · discard {x} · hand {h}", { d: zo.deck.length, x: zo.disc.length, h: zo.hand.length });
    $("oppHand").innerHTML = peekOpp
      ? zo.hand.map((c) => tile(c)).join("")
      : zo.hand.map(() => '<span class="mc"></span>').join("");
    $("oppHand").className = peekOpp ? "handrow" : "mini";
    $("oppPlay").innerHTML = eng.turn === op ? zo.play.map((c) => tile(c)).join("") : "";
    // my zone
    const mp = me != null ? me : 0, zm = eng.ps[mp];
    $("myHead").textContent = me != null ? T("yourHand", "Your hand") : disp(gm.p1);
    $("myCounts").textContent = T("counts", "deck {d} · discard {x} · hand {h}", { d: zm.deck.length, x: zm.disc.length, h: zm.hand.length });
    $("myPlay").innerHTML = eng.turn === mp && zm.play.length ? zm.play.map((c) => tile(c)).join("") : "";
    const f = topFrame(), selectable = canAct();
    $("hand").innerHTML = zm.hand.map((c, i) => {
      let cls = "";
      if (dsel.has(i)) cls = " sel";
      else if (selectable && !f && eng.phase === 0 && eng.actions > 0 && isA(c)) cls = " buyable";
      return '<div class="' + tileCls(c) + cls + '" data-h="' + i + '" title="' + (E.CARDS[c].txt || "") + '">'
        + '<span class="cost">' + E.CARDS[c].c + '</span><div class="cname">' + NAME(c) + "</div>"
        + (E.CARDS[c].txt ? '<div class="ctxt">' + E.CARDS[c].txt + "</div>" : (E.CARDS[c].coin ? '<div class="ctxt">🪙 ' + E.CARDS[c].coin + "</div>" : '<div class="ctxt">🏆 ' + (E.CARDS[c].vp || 0) + "</div>"))
        + "</div>";
    }).join("");
    $("hand").querySelectorAll("[data-h]").forEach((d) => d.onclick = () => onHandTap(parseInt(d.dataset.h, 10)));
    // hand buttons
    const hb = $("handBtns"); hb.innerHTML = "";
    if (selectable && !f) {
      const anyT = zm.hand.some(isT);
      const btn = (txt, fn, primary, aid) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.textContent = txt; b.onclick = fn; if (aid && armed && armed.key === aid) { b.classList.add("pulse"); b.textContent = armed.label; } hb.appendChild(b); };
      if (anyT) btn(dsel.size ? T("playSelT", "🪙 Play selected treasures ({n})", { n: dsel.size }) : T("playAllT", "🪙 Play all treasures"), playTreasures, eng.phase === 1 || !zm.hand.some(isA));
      btn(T("endTurn", "⏭ End turn"), endTurn, false, "end");
    }
    $("trashLine").textContent = eng.trash.length ? T("trashN", "trash: {n}", { n: eng.trash.length }) : "";
    $("logPane").innerHTML = eng.log.slice(-14).map((e) => '<div class="' + (e.p === me ? "me" : "") + '">' + fmtEv(e) + "</div>").join("");
    const lp = $("logPane"); lp.scrollTop = lp.scrollHeight;
  } else {
    oz.classList.add("hidden");
    $("hand").innerHTML = ""; $("myPlay").innerHTML = ""; $("handBtns").innerHTML = ""; $("logPane").innerHTML = ""; $("supply").innerHTML = "";
    $("myCounts").textContent = ""; $("trashLine").textContent = "";
  }

  // ---- settle / lifecycle buttons (the chess flow) --------------------------------------------------
  const iAmIn = me != null;
  const iAmWinner = over && ((rc === 1 && me === 0) || (rc === 2 && me === 1));
  const iAmLoser = over && ((rc === 2 && me === 0) || (rc === 1 && me === 1));
  $("btnResign").classList.toggle("hidden", !(live && iAmIn));
  $("btnResign").textContent = over ? (iAmLoser ? T("concede", "Concede — pay out the winner") : T("resign", "Resign")) : T("resign", "Resign");
  $("btnRematch").classList.toggle("hidden", !(gm.exists && gm.settled && iAmIn));
  const drawShown = live && iAmIn && !over;
  const myA = me === 0 ? gm.a1 : me === 1 ? gm.a2 : 0;
  const oppA = me === 0 ? gm.a2 : me === 1 ? gm.a1 : 0;
  $("btnDraw").classList.toggle("hidden", !drawShown);
  if (drawShown) {
    if (oppA === 3) { $("btnDraw").textContent = T("acceptDraw", "🤝 Accept draw — refund both stakes"); $("btnDraw").classList.add("pulse"); }
    else if (myA === 3) { $("btnDraw").textContent = T("drawOfferedWait", "½ Draw offered — waiting for opponent…"); $("btnDraw").classList.remove("pulse"); }
    else { $("btnDraw").textContent = T("offerDraw", "½ Offer draw"); $("btnDraw").classList.remove("pulse"); }
    if (oppA === 3 && myA !== 3) { if (lastDrawOffer !== activeGame) { lastDrawOffer = activeGame; alertBar(T("oppOffersDraw", "Your opponent offers a DRAW — accept to split the stakes back, or keep playing to decline.")); } }
    else if (lastDrawOffer === activeGame) lastDrawOffer = null;
  }
  $("btnSettle").classList.toggle("hidden", !(live && iAmIn && over && rc === 3));
  $("btnSettle").textContent = T("agreeDrawRefund", "Agree draw (refund both)");
  const pastDeadline = live && dapp.cursor != null && dapp.cursor > gm.dl;
  $("btnAbort").classList.toggle("hidden", !(iAmIn && pastDeadline));
  $("btnCancel").classList.toggle("hidden", !(gm.exists && gm.nn === 1 && me === 0 && !gm.settled));
  $("btnJoinGame").classList.toggle("hidden", !(gm.exists && gm.nn === 1 && !iAmIn && !gm.settled));
  if (gm.exists && gm.nn === 1 && !iAmIn) $("btnJoinGame").textContent = dapp.me ? T("joinStake", "⚔ Join this game — stake {amt} NADO", { amt: rawToNado(gm.stake) }) : T("signJoinStake", "⚔ Sign in to join — stake {amt} NADO", { amt: rawToNado(gm.stake) });
  const s0 = eng && !eng.setup ? E.scoreOf(eng, 0) : null;
  $("settleHint").textContent = over && !gm.settled
    ? T("finalScore", "Final score {a} : {b} VP. ", { a: s0, b: E.scoreOf(eng, 1) })
      + (rc === 3 ? T("itsDraw", "It's a draw — both players agree to refund.")
        : iAmWinner ? T("youWonWaiting", "You won! Waiting for your opponent to concede (or claim a refund after the timeout).")
        : iAmLoser ? T("beaten", "You're beaten — concede to pay out the winner.") : "")
    : (live && !over && pastDeadline ? T("deadlinePassed", "The move clock ran out — either player can claim the refund.")
      : live && !over && dapp.cursor != null && iAmIn && eng && E.legalActor(eng) !== me
        ? T("moveClock", "move clock: refundable in {t} if they stall", { t: blocksToTime(gm.dl - dapp.cursor) }) : "");
}

// ---- boot --------------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => dapp.exec, render);
  stickyInputs(dapp, ["stakeAmt", "bankAmt"]);
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("btnRematch").onclick = rematch;
  $("btnResign").onclick = resignGame;
  $("btnDraw").onclick = () => agree(3);
  $("btnSettle").onclick = () => agree(3);
  $("btnAbort").onclick = abortGame;
  $("btnCancel").onclick = cancelGame;
  $("btnJoinGame").onclick = () => { if (!dapp.me) return dapp.signIn(); $("joinId").value = String(activeGame); joinGame(); };
  $("oppHandWrap").onclick = () => { peekOpp = !peekOpp; render(); };
  $("btnShare").onclick = () => share(base() + "/?game=" + activeGame, T("shareText", "Duel me at Stormhold for {stake}on NADO — game #{id}:", { stake: lastGame && lastGame.exists ? rawToNado(lastGame.stake) + " NADO " : "", id: activeGame }), $("btnShare"));
}
const replayInvite = (id) => { activeGame = parseInt(id, 10); const j = $("joinId"); if (j) j.value = String(activeGame); joinGame(); };
const CONFIRMING = { connect: T("cfConnect", "Signed in."), deposit: T("cfDeposit", "Deposit submitted — confirming…"), open: T("cfOpen", "Game opening — confirming…"),
  join: T("cfJoin", "Joining — confirming…"), move: T("cfMove", "Move submitted — confirming…"), resign: T("cfResign", "Resigning — confirming…"),
  agree: T("cfAgree", "Submitting…"), abort: T("cfAbort", "Claiming refund…"), cancel: T("cfCancel", "Cancelling…"), withdraw: T("cfWithdraw", "Withdrawal submitted.") };
const DONE = { open: T("doneOpen", "✓ Game is on-chain — share the invite below."), join: T("doneJoin", "✓ You're in — the duel is live."),
  move: T("doneMove", "✓ Move landed."), resign: T("doneResign", "✓ Resigned — result recorded."), agree: T("doneAgree", "✓ Recorded."),
  abort: T("doneAbort", "✓ Refunded."), cancel: T("doneCancel", "✓ Cancelled — stake refunded.") };
dapp.doneLabels(DONE);
dapp.onReturn((pend, ok, err) => {
  nudgeJoin = !!(ok && pend && pend.phase === "connect");
  if (pend && pend.game != null) activeGame = pend.game;
  if (ok && pend && (pend.phase === "connect" || pend.phase === "deposit")) dapp.consumeInvite(replayInvite);
  if (!ok) pendingMove = null;
  dapp.showReturn(pend, ok, err, CONFIRMING);
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(T("cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); orderCards(["activeGame", "lobby", "play", "walletcard", "bankroll"]);
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (activeGame == null) { activeGame = parseInt(q, 10); haveState = false; } }
  if (q && !dapp.me) { const sto = await dapp.storage({ append: MAPS }); const gm = sto ? gameHead(sto, parseInt(q, 10)) : null;
    inviteGate(dapp, { id: parseInt(q, 10), title: T("inviteTitle", "You're invited to a Stormhold duel"),
      body: gm && gm.exists ? T("inviteBody", "Duel {who} for <b>{amt} NADO</b> — winner takes the pot.", { who: disp(gm.p1), amt: rawToNado(gm.stake) }) : T("inviteBodySignin", "Sign in to join this game."),
      joinLabel: T("inviteJoin", "Sign in & join") }); }
  else if (dapp.me) dapp.consumeInvite(replayInvite);
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();

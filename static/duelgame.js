// duelgame.js — the shared 2-PLAYER MOVE-LOG DUEL client scaffold (the chess contract model), extracted
// from stormhold.js for scrapline and every future engine-refereed game. Pairs with the stormhold-family
// contract schema: escrow (p1 opener / p2 joiner / st / pt / nn / sd / wr / mc / dl / a1 / a2), a
// FREE-ACTOR move log mv[g*10000+i] with per-move seed records mh[g*10000+i] = (height)*4 + side, and the
// join-time kingdom/setup seed height kh. The RULES live in a per-game deterministic engine that replays
// the log with block-hash randomness; the wager settles by resign / mutual agree(1|2|3) / refund-timeout.
//
// This module owns the non-game-specific half: the log reader (gameHead/gameFrom), the seed-height
// fetcher (ensureSeeds/qOf), open/join/move/resign/agree/abort/cancel/rematch actions with ply binding,
// the lobby + "your games" chips, invite gating, the anti-rollback accept() cycle, the confirm lifecycle,
// and the shared chrome (players line, pot, status verdict, the concede/draw/refund settle buttons). The
// game supplies its engine replay + full board rendering via cfg hooks:
//
//   const duel = new DuelGame(dapp, {
//     prefix: "storm", icon: "🏰", marks: ["🏰", "⚔"], appendMaps: ["kh"],
//     rebuild(gm) { return E.replay(gm.id, this.qOf(gm.kh), gm.recs.map(...)); },
//     renderGame(gm, eng) { …draw supply/hands/log; call duel.submit(op, payload, label) on taps… },
//     turnOf(eng) { return 0|1|null; },              // null = concurrent (both may act)
//     canAct(eng, me, gm) { return bool; },          // is it `me`'s decision right now?
//     resultOf(eng) { return eng.over ? eng.result : 0; },
//     overHint(eng, me) { return "Final score …"; },
//     shareText(gm) {…}, inviteTitle: "…", inviteBody(gm) {…},
//   });
//   duel.boot(["activeGame", "lobby", "play", "walletcard", "bankroll"]);
import { rawToNado, nadoToRaw, randId, rematchId, _m, $, base, canPay, alertBar, orderCards,
         resolveAliases, disp, share, wireWallet, inviteGate, stickyInputs, renderWallet, notify,
         blocksToTime, renderScore, scoreBump, scoreSort } from "./nadodapp.js";

const T0 = (p, k, d, v) => (typeof window !== "undefined" && window.t) ? window.t(p + "." + k, d, v) : d;

export class DuelGame {
  constructor(dapp, cfg) {
    this.dapp = dapp; this.cfg = cfg;
    this.T = (k, d, v) => T0(cfg.prefix, k, d, v);
    const slug = dapp.app.replace(/\W+/g, "").toLowerCase();
    this.LS_G = "nado_" + slug + "_games";
    this.MAPS = ["wr", "mv", "mh", "mc", "p2", "nn", "a1", "a2", "kh", "dl"].concat(cfg.appendMaps || []);
    this.active = null; this.last = null; this.lastSto = null; this.eng = null; this.haveState = false;
    this.pendingMove = null; this.armed = null;
    this.lastMi = -1; this.lastDrawOffer = null; this.nudgeJoin = false;
    this.knownGames = new Set();
  }
  lsLoad() { try { return JSON.parse(localStorage.getItem(this.LS_G) || "{}"); } catch { return {}; } }
  lsSave(v) { try { localStorage.setItem(this.LS_G, JSON.stringify(v)); } catch {} }

  // ---- reads (the duel/chess storage schema) --------------------------------------------------------
  gameHead(sto, g) {
    g = String(g); const nn = _m(sto, "nn")[g] || 0;
    if (!nn) return { exists: false, id: Number(g) };
    return { exists: true, id: Number(g), p1: _m(sto, "p1")[g], p2: _m(sto, "p2")[g] || null,
      stake: _m(sto, "st")[g] || 0, pot: _m(sto, "pt")[g] || 0, nn, settled: !!_m(sto, "sd")[g],
      dl: _m(sto, "dl")[g] || 0, mc: _m(sto, "mc")[g] || 0, kh: _m(sto, "kh")[g] || 0,
      a1: _m(sto, "a1")[g] || 0, a2: _m(sto, "a2")[g] || 0, wr: _m(sto, "wr")[g] || 0 };
  }
  gameFrom(sto, g) {
    const h = this.gameHead(sto, g);
    if (!h.exists) return h;
    const mv = _m(sto, "mv"), mh = _m(sto, "mh");
    h.recs = [];
    for (let i = 0; i < h.mc; i++) {
      const enc = mv[String(h.id * 10000 + i)], rec = mh[String(h.id * 10000 + i)];
      if (!enc || !rec) { h.gap = true; break; }        // provisional read raced the log — retry next poll
      h.recs.push({ enc, side: rec % 4, rh: Math.floor(rec / 4) });
    }
    return h;
  }
  qOf(h) { const a = this.dapp.bh(h), b = this.dapp.bh(h + 1); return a && b ? BigInt("0x" + a) + BigInt("0x" + b) : null; }
  async ensureSeeds(gm) {
    const want = [], dapp = this.dapp;
    const add = (h) => { if (h && dapp.cursor != null && dapp.cursor >= h + 1) want.push(h, h + 1); };
    add(gm.kh);
    for (const r of gm.recs || []) add(r.rh);
    const missing = [...new Set(want)].filter((h) => dapp.bh(h) === undefined);
    // seed heights are PUBLIC randomness -> provisional (fast) is safe: a reorg just replays visibly
    if (missing.length) await dapp.blockHashes(missing.slice(0, 120), { fast: true });
  }
  myIdx(gm) { return gm && gm.p1 === this.dapp.me ? 0 : gm && gm.p2 === this.dapp.me ? 1 : null; }
  canAct() {
    const gm = this.last, eng = this.eng;
    if (!gm || !gm.exists || gm.nn !== 2 || gm.settled || this.pendingMove) return false;
    if (!eng || eng.setup || eng.blocked || eng.corrupt || eng.over || eng.mi !== gm.mc) return false;
    const me = this.myIdx(gm);
    return me != null && this.cfg.canAct(eng, me, gm);
  }

  // ---- actions ---------------------------------------------------------------------------------------
  newGame() {
    const T = this.T, dapp = this.dapp;
    const raw = nadoToRaw($("stakeAmt").value);
    if (!raw) return alertBar(T("enterStake", "Enter a stake (NADO)."));
    if (!canPay(dapp, raw, T("whatOpen", "Opening this game"))) return;
    const g = randId(), G = this.lsLoad(); G[g] = { role: "p1", stake: raw.toString(), ts: Date.now() }; this.lsSave(G);
    this.active = g; this.resetLocal(); this.render();
    dapp.call("open", [g], raw, "open " + dapp.app.toLowerCase() + " game #" + g + " · " + rawToNado(raw) + " NADO stake", { game: g, phase: "open" });
  }
  async joinGame() {
    const T = this.T, dapp = this.dapp;
    const g = parseInt($("joinId").value, 10);
    if (!g) return alertBar(T("enterGameId", "Enter a game ID (or pick one from the lobby)."));
    const sto = await dapp.storage({ append: this.MAPS });
    const gm = sto ? this.gameHead(sto, g) : null;
    if (!gm || !gm.exists) { alertBar(dapp.whereIs(T("gameWord", "game"), g)); if (gm) dapp.clearInvite(); return; }
    if (gm.nn >= 2 || gm.settled) { alertBar(T("fullOrFinished", "That game is full or finished.")); dapp.clearInvite(); return; }
    await dapp.refresh();
    const stake = BigInt(gm.stake);
    if (!canPay(dapp, stake, T("whatJoin", "Joining this game"))) { this.render(); return; }
    dapp.clearInvite();
    const G = this.lsLoad(); G[g] = { role: "p2", stake: stake.toString(), ts: Date.now() }; this.lsSave(G);
    this.active = g; this.resetLocal(); this.render();
    dapp.call("join", [g], stake, "join " + dapp.app.toLowerCase() + " game #" + g + " · " + rawToNado(stake) + " NADO stake", { game: g, phase: "join" });
  }
  async rematch() {
    const T = this.T, dapp = this.dapp;
    const g = this.last; if (!g || !g.exists) return;
    const stake = BigInt(g.stake);
    if (!canPay(dapp, stake, T("whatRematch", "A rematch"))) return;
    const rid = rematchId(this.active);
    const sto = await dapp.storage({ append: this.MAPS });
    const rg = sto ? this.gameHead(sto, rid) : null;
    this.active = rid; this.resetLocal(); this.haveState = false; $("joinId").value = String(rid);
    const G = this.lsLoad();
    if (rg && rg.exists && rg.nn === 1 && !rg.settled) {
      G[rid] = { role: "p2", stake: stake.toString(), ts: Date.now() }; this.lsSave(G);
      dapp.call("join", [rid], stake, "join rematch #" + rid, { game: rid, phase: "join" });
    } else {
      G[rid] = { role: "p1", stake: stake.toString(), ts: Date.now() }; this.lsSave(G);
      dapp.call("open", [rid], stake, "rematch #" + rid + " · stake " + rawToNado(stake) + " NADO", { game: rid, phase: "open" });
    }
    this.render();
  }
  // submit(op, payload, label): enc = op + payload·16 with PLY BINDING — a stale wallet retry can never
  // land turns later against a changed game.
  submit(op, payload, label) {
    const gm = this.last; if (!this.canAct()) return;
    const enc = op + (payload || 0) * 16, ply = gm.mc;
    this.pendingMove = { ply }; this.armed = null;
    if (this.cfg.onSubmit) this.cfg.onSubmit();
    this.dapp.call("move", [this.active, enc, ply], null, label + " · game #" + this.active, { game: this.active, phase: "move", ply });
    this.render();
  }
  resign() { this.dapp.call("resign", [this.active], null, "resign game #" + this.active, { game: this.active, phase: "resign" }); }
  agree(r) { this.dapp.call("agree", [this.active, r], null, (r === 3 ? "agree a draw" : "confirm the result") + " · game #" + this.active, { game: this.active, phase: "agree" }); }
  abort() { this.dapp.call("abort", [this.active], null, "claim refund (stalled) · game #" + this.active, { game: this.active, phase: "abort" }); }
  cancel() { this.dapp.call("cancel", [this.active], null, "cancel game #" + this.active, { game: this.active, phase: "cancel" }); }
  resetLocal() { this.pendingMove = null; this.armed = null; this.lastMi = -1; this.eng = null; if (this.cfg.onReset) this.cfg.onReset(); }
  // arm(key,label,fn): first tap arms (button shows label), second tap within 6s fires — misclick guard.
  arm(key, label, fn) {
    if (this.armed && this.armed.key === key && Date.now() - this.armed.ts < 6000) { this.armed = null; fn(); return; }
    this.armed = { key, label, ts: Date.now() };
    this.render();
  }

  // ---- refresh cycle ---------------------------------------------------------------------------------
  async refreshActive() {
    const dapp = this.dapp;
    await dapp.refresh();
    const sto = await dapp.storage({ append: this.MAPS });
    if (sto) {
      this.lastSto = sto;
      this.knownGames = new Set(Object.keys(_m(sto, "nn")));
      const G = this.lsLoad(); let c = false;
      for (const g of Object.keys(G)) if (!this.knownGames.has(g) && Date.now() - (G[g].ts || 0) > 600000) { delete G[g]; c = true; }
      if (c) this.lsSave(G);
      if (this.active != null) {
        const ng = this.gameFrom(sto, this.active);
        const prog = (ng.settled ? 1e9 : 0) + (ng.nn || 0) * 100000 + (ng.mc || 0);
        if (dapp.accept(dapp.app + ":" + this.active, prog) && !ng.gap) {
          this.last = ng;
          if (this.pendingMove != null && ng.mc > this.pendingMove.ply) this.pendingMove = null;
          if (ng.exists && ng.nn === 2) {
            await this.ensureSeeds(ng);
            this.eng = this.cfg.rebuild.call(this, ng);
            if (this.eng && this.eng.mi !== this.lastMi) { this.armed = null; this.lastMi = this.eng.mi; if (this.cfg.onAdvance) this.cfg.onAdvance(this.eng); }
          } else this.eng = null;
          this.haveState = true;
        }
      }
      dapp.settleInflight((f) => {
        const g = this.gameHead(sto, f.game);
        return f.phase === "open" ? g.exists
          : f.phase === "join" ? g.nn === 2
          : f.phase === "move" ? g.mc > (f.ply || 0)
          : (g.settled || !g.exists);
      });
      this.renderLobby(sto);
      renderScore($("scoreList"), this.boardFrom(sto), dapp.me,
        this.T("noFinished", "No settled duels yet — win the first one."));
      if (this.cfg.onStorage) this.cfg.onStorage.call(this, sto);
    }
    await resolveAliases([dapp.me].concat(this.last ? [this.last.p1, this.last.p2] : []).filter(Boolean));
    this.render();
  }
  // the shared duel leaderboard: every settled decisive game moves one stake from loser to winner.
  boardFrom(sto) {
    const stats = {};
    for (const g of Object.keys(_m(sto, "nn"))) {
      if (!_m(sto, "sd")[g]) continue;
      const wr = _m(sto, "wr")[g] || 0, st = _m(sto, "st")[g] || 0;
      const p1 = _m(sto, "p1")[g], p2 = _m(sto, "p2")[g];
      if (!p2 || !wr || wr === 3) continue;              // cancelled / draw / void games don't rank
      scoreBump(stats, wr === 1 ? p1 : p2, st);
      scoreBump(stats, wr === 1 ? p2 : p1, -st);
    }
    return scoreSort(stats);
  }
  renderLobby(sto) {
    const el = $("lobbyList"), T = this.T; if (!el) return;
    const games = Object.keys(_m(sto, "nn")).map((g) => this.gameHead(sto, g)).filter((g) => g.exists && !g.settled);
    games.sort((a, b) => (a.nn - b.nn) || (b.id - a.id));
    const shown = games.slice(0, 24);
    el.innerHTML = shown.length ? shown.map((g) => {
      const verb = g.nn < 2 ? T("joinSuffix", " · join") : T("watchSuffix", " · watch");
      return '<button class="chip ' + (g.nn < 2 ? "open" : "live") + '" data-g="' + g.id + '">' + (g.nn < 2 ? this.cfg.icon : "▶") + " #" + g.id + " · " + rawToNado(g.stake) + " NADO" + verb + "</button>";
    }).join(" ") : '<span class="dim">' + T("noGamesLobby", "No games yet — open one above.") + "</span>";
    el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { this.active = parseInt(b.dataset.g, 10); this.resetLocal(); this.haveState = false; $("joinId").value = b.dataset.g;
      notify(T("gameSelected", "Game #{id} selected.", { id: this.active })); this.refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
  }

  // ---- shared chrome render --------------------------------------------------------------------------
  render() {
    const dapp = this.dapp, T = this.T;
    dapp.reflectUrl("game", this.active);
    dapp.syncPctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, dapp.exec);
    const signedIn = renderWallet(dapp);
    $("play").classList.toggle("hidden", !signedIn);
    $("bankroll").classList.toggle("hidden", !signedIn);
    const G = this.lsLoad(), ids = Object.keys(G).sort((a, b) => G[b].ts - G[a].ts).slice(0, 8);
    $("recent").innerHTML = ids.length ? ids.map((g) => { const live = this.knownGames.has(String(g)); let tag = "";
      if (live && this.lastSto) { const gm = this.gameHead(this.lastSto, g); if (gm.exists) tag = gm.settled ? T("tagFinished", " · finished ✓") : gm.nn < 2 ? T("tagWaiting", " · waiting for opponent") : T("tagLive", " · live"); }
      return '<button class="chip' + (live ? "" : " pending") + '" data-g="' + g + '">' + this.cfg.icon + " #" + g + (live ? tag : T("confirmingTag", " · confirming ⏳")) + "</button>"; }).join(" ")
      : '<span class="dim">' + T("noGames", "No games yet.") + "</span>";
    $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { this.active = parseInt(b.dataset.g, 10); this.resetLocal(); this.haveState = false; this.refreshActive(); });
    this.renderActive();
  }
  renderActive() {
    const dapp = this.dapp, T = this.T, cfg = this.cfg;
    const box = $("activeGame");
    if (this.active == null) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const gm = this.last || {}, local = this.lsLoad()[this.active] || {}, me = this.myIdx(gm), eng = this.eng;
    $("gameId").textContent = "#" + this.active;
    $("shareLink").value = base() + "/?game=" + this.active;
    $("gPot").textContent = gm.exists ? rawToNado(gm.pot) + " NADO" : (local.stake ? rawToNado(BigInt(local.stake) * 2n) + " NADO" : "—");
    const n1 = gm.p1 ? disp(gm.p1) + (gm.p1 === dapp.me ? T("youSuffix", " (you)") : "") : "—";
    const n2 = gm.p2 ? disp(gm.p2) + (gm.p2 === dapp.me ? T("youSuffix", " (you)") : "") : T("waitingDots", "waiting…");
    $("players").innerHTML = '<span class="chip">' + cfg.marks[0] + " " + n1 + '</span> <span class="chip">' + cfg.marks[1] + " " + n2 + "</span>";
    if (this.nudgeJoin && gm.exists && gm.nn === 1 && me == null) {
      this.nudgeJoin = false;
      alertBar(T("notJoined", "Signed in — but you have NOT joined yet. Tap “Join this game” to take the seat and stake {amt} NADO.", { amt: rawToNado(gm.stake) }));
    }
    // status line
    let st = dapp.whereIs(T("gameWord", "game"), this.active, local.ts);
    const live = gm.exists && gm.nn === 2 && !gm.settled;
    const over = eng && eng.over, rc = over ? cfg.resultOf(eng) : 0;
    if (gm.exists && gm.settled) {
      const seat = gm.wr === 1 ? T("host", "the host") : T("challenger", "the challenger");
      st = gm.wr === 3 ? T("drawRefunded", "✓ Draw — stakes refunded")
        : gm.wr ? (((gm.wr === 1 && me === 0) || (gm.wr === 2 && me === 1)) ? T("winYou", "✓ You won the pot! 🏆")
          : me != null ? T("winLost", "✓ You lost — {seat} takes the pot", { seat }) : T("winNeutral", "✓ {seat} wins", { seat }))
        : T("settled", "✓ settled");
    }
    else if (gm.exists && eng && eng.corrupt) st = T("illegal", "⚠ an illegal move reached the chain — this game refunds after the timeout.");
    else if (gm.exists && gm.nn < 2) st = me != null ? T("waitingShare", "waiting for an opponent — share the link below") : T("openSeat", "open seat — join to play for {amt} NADO", { amt: rawToNado(gm.stake) });
    else if (eng && (eng.setup || eng.blocked)) st = T("shuffling", "🌀 waiting for the randomness block…");
    else if (eng && eng.mi < gm.mc) st = T("catchingUp", "replaying the on-chain log…");
    else if (over) st = rc === 3 ? T("overDraw", "Game over — it's a draw") :
      ((rc === 1 && me === 0) || (rc === 2 && me === 1)) ? T("overWin", "Game over — YOU WIN 🏆") :
      me != null ? T("overLose", "Game over — you lost") : T("overNeutral", "Game over");
    else if (live && eng) {
      const turn = cfg.turnOf(eng);
      const mine = this.canAct();
      st = mine ? (this.pendingMove ? T("moveConfirming", "your move is confirming…") : T("yourMove", "▶ YOUR MOVE"))
        : this.pendingMove ? T("moveConfirming", "your move is confirming…")
        : turn == null ? T("waitingBoth", "waiting…")
        : T("waitingFor", "waiting for {who}…", { who: disp(turn === 0 ? gm.p1 : gm.p2) });
    }
    $("gStatus").innerHTML = st;
    // the game's own zones
    cfg.renderGame.call(this, gm, eng);
    // settle / lifecycle buttons (the chess flow)
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
      if (oppA === 3 && myA !== 3) { if (this.lastDrawOffer !== this.active) { this.lastDrawOffer = this.active; alertBar(T("oppOffersDraw", "Your opponent offers a DRAW — accept to split the stakes back, or keep playing to decline.")); } }
      else if (this.lastDrawOffer === this.active) this.lastDrawOffer = null;
    }
    $("btnSettle").classList.toggle("hidden", !(live && iAmIn && over && rc === 3));
    $("btnSettle").textContent = T("agreeDrawRefund", "Agree draw (refund both)");
    const pastDeadline = live && dapp.cursor != null && dapp.cursor > gm.dl;
    $("btnAbort").classList.toggle("hidden", !(iAmIn && pastDeadline));
    $("btnCancel").classList.toggle("hidden", !(gm.exists && gm.nn === 1 && me === 0 && !gm.settled));
    $("btnJoinGame").classList.toggle("hidden", !(gm.exists && gm.nn === 1 && !iAmIn && !gm.settled));
    if (gm.exists && gm.nn === 1 && !iAmIn) $("btnJoinGame").textContent = dapp.me ? T("joinStake", "⚔ Join this game — stake {amt} NADO", { amt: rawToNado(gm.stake) }) : T("signJoinStake", "⚔ Sign in to join — stake {amt} NADO", { amt: rawToNado(gm.stake) });
    $("settleHint").textContent = over && !gm.settled
      ? (cfg.overHint ? cfg.overHint(eng, me) + " " : "")
        + (rc === 3 ? T("itsDraw", "It's a draw — both players agree to refund.")
          : iAmWinner ? T("youWonWaiting", "You won! Waiting for your opponent to concede (or claim a refund after the timeout).")
          : iAmLoser ? T("beaten", "You're beaten — concede to pay out the winner.") : "")
      : (live && !over && pastDeadline ? T("deadlinePassed", "The move clock ran out — either player can claim the refund.")
        : live && !over && dapp.cursor != null && iAmIn && eng && !this.canAct() && !this.pendingMove
          ? T("moveClock", "move clock: refundable in {t} if they stall", { t: blocksToTime(gm.dl - dapp.cursor) }) : "");
  }

  // ---- boot ------------------------------------------------------------------------------------------
  wire() {
    const dapp = this.dapp;
    wireWallet(dapp);
    dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => dapp.exec, () => this.render());
    stickyInputs(dapp, ["stakeAmt", "bankAmt"]);
    $("btnNew").onclick = () => this.newGame();
    $("btnJoin").onclick = () => this.joinGame();
    $("btnRematch").onclick = () => this.rematch();
    $("btnResign").onclick = () => this.resign();
    $("btnDraw").onclick = () => this.agree(3);
    $("btnSettle").onclick = () => this.agree(3);
    $("btnAbort").onclick = () => this.abort();
    $("btnCancel").onclick = () => this.cancel();
    $("btnJoinGame").onclick = () => { if (!dapp.me) return dapp.signIn(); $("joinId").value = String(this.active); this.joinGame(); };
    $("btnShare").onclick = () => share(base() + "/?game=" + this.active, this.cfg.shareText(this.last, this.active), $("btnShare"));
    if (this.cfg.wire) this.cfg.wire.call(this);
  }
  async boot(orderIds) {
    const dapp = this.dapp, T = this.T;
    const replayInvite = (id) => { this.active = parseInt(id, 10); const j = $("joinId"); if (j) j.value = String(this.active); this.joinGame(); };
    dapp.doneLabels({ open: T("doneOpen", "✓ Game is on-chain — share the invite below."), join: T("doneJoin", "✓ You're in — the duel is live."),
      move: T("doneMove", "✓ Move landed."), resign: T("doneResign", "✓ Resigned — result recorded."), agree: T("doneAgree", "✓ Recorded."),
      abort: T("doneAbort", "✓ Refunded."), cancel: T("doneCancel", "✓ Cancelled — stake refunded.") });
    dapp.onReturn((pend, ok, err) => {
      this.nudgeJoin = !!(ok && pend && pend.phase === "connect");
      if (pend && pend.game != null) this.active = pend.game;
      if (ok && pend && (pend.phase === "connect" || pend.phase === "deposit")) dapp.consumeInvite(replayInvite);
      if (!ok) this.pendingMove = null;
      dapp.showReturn(pend, ok, err, { connect: T("cfConnect", "Signed in."), deposit: T("cfDeposit", "Deposit submitted — confirming…"),
        open: T("cfOpen", "Game opening — confirming…"), join: T("cfJoin", "Joining — confirming…"), move: T("cfMove", "Move submitted — confirming…"),
        resign: T("cfResign", "Resigning — confirming…"), agree: T("cfAgree", "Submitting…"), abort: T("cfAbort", "Claiming refund…"),
        cancel: T("cfCancel", "Cancelling…"), withdraw: T("cfWithdraw", "Withdrawal submitted.") });
    });
    try { await dapp.init(); } catch (e) { alertBar(T("cryptoFail", "Crypto bundle failed to load — reload.")); return; }
    this.wire(); orderCards(orderIds || ["activeGame", "lobby", "play", "walletcard", "bankroll"]);
    const q = new URLSearchParams(location.search).get("game");
    if (q) { $("joinId").value = q; if (this.active == null) { this.active = parseInt(q, 10); this.haveState = false; } }
    if (q && !dapp.me) { const sto = await dapp.storage({ append: this.MAPS }); const gm = sto ? this.gameHead(sto, parseInt(q, 10)) : null;
      inviteGate(dapp, { id: parseInt(q, 10), title: this.cfg.inviteTitle,
        body: gm && gm.exists ? this.cfg.inviteBody(gm) : T("inviteBodySignin", "Sign in to join this game."),
        joinLabel: T("inviteJoin", "Sign in & join") }); }
    else if (dapp.me) dapp.consumeInvite(replayInvite);
    this.render(); this.refreshActive();
    setInterval(() => this.refreshActive(), 3000);
  }
}

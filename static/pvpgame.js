// pvpgame.js — the shared 2-PLAYER STAKED BOARD GAME client scaffold, extracted from tictactoe.js for
// connect-four/reversi and every future board game. Pairs with tests/vmasm.pvp_methods: contracts store
// the SAME maps (p1 opener, p2 joiner, st stake, pt pot, nn players, sd settled, mc ply, dl deadline,
// wr result 1/2/3) plus their own board, and referee moves entirely on-chain. This module owns the
// non-game-specific client half: the game reader, open/join/move/resign/abort/cancel/rematch actions,
// the lobby of open challenges, "your games" chips, the watch/confirm lifecycle, the anti-rollback
// accept() gating, share-link invites, the scoreboard, and the shared chrome render (players line,
// verdict, move clock, action buttons). The game supplies ONLY its board decode + board render + move
// encoding via cfg hooks. Shared strings live under the `pvp.*` i18n bundle (i18n_games/pvp.json).
//
//   const pvp = new PvpGame(dapp, {
//     marks: ["✕", "◯"], markClass: ["x", "o"],
//     appendMaps: ["bd"],
//     decode(gm, sto, g) { gm.board = …; gm.winLine = …; },
//     renderBoard(gm) { …draw + wire clicks; call pvp.move([cell], label) on a tap… },
//     lobbyChip(gm) { return "…"; },
//     shareText(gm) { return "…"; }, inviteTitle: "…", inviteBody(gm) { return "…"; },
//   });
//   pvp.boot(["activeGame", "lobby", …]);
import { _m, $, gate, canPay, orderCards, alertBar, notify, okBar, blocksToTime, inviteGate, lsLoad, lsSave, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, recentChips, randId, rematchId, rawToNado, nadoToRaw, loadQR, resolveAliases, disp, shareInvite } from "./nadodapp.js";

const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("pvp." + k, d, v) : d;

export class PvpGame {
  constructor(dapp, cfg) {
    this.dapp = dapp; this.cfg = cfg;
    const slug = dapp.app.replace(/\W+/g, "").toLowerCase();
    this.LS_G = "nado_" + slug + "_games";
    this.active = null; this.last = null; this.lastSto = null; this.watch = null;
    this.pendingMove = null;   // the game's optimistic marker (set by game code; cleared when mc advances)
    this.lobbyN = 24;
  }

  // ---- reads (the vmasm.pvp_methods schema) ----
  read(sto, g) {
    g = String(g); const p1 = _m(sto, "p1")[g];
    if (!p1) return { exists: false, id: Number(g) };
    const gm = { exists: true, id: Number(g), p1, p2: _m(sto, "p2")[g] || null, stake: _m(sto, "st")[g] || 0,
      pot: _m(sto, "pt")[g] || 0, nn: _m(sto, "nn")[g] || 0, sd: !!_m(sto, "sd")[g], mc: _m(sto, "mc")[g] || 0,
      dl: _m(sto, "dl")[g] || 0, wr: _m(sto, "wr")[g] || 0 };
    gm.turn = gm.nn === 2 && !gm.sd ? (gm.mc % 2 === 0 ? 1 : 2) : 0;
    gm.turnAddr = gm.turn ? (gm.turn === 1 ? gm.p1 : gm.p2) : null;
    if (this.cfg.decode) this.cfg.decode(gm, sto, Number(g));
    return gm;
  }
  storage() { return this.dapp.storage({ append: ["sd", "wr", "p2", "mc", "nn"].concat(this.cfg.appendMaps || []) }); }
  async fetch(g) { const sto = await this.storage(); return sto ? this.read(sto, g) : null; }
  rec(g, role) { const G = lsLoad(this.LS_G); if (role) { G[g] = { role, ts: Date.now() }; lsSave(this.LS_G, G); } return G[g]; }

  // ---- actions ----
  open() {
    const raw = nadoToRaw($("stakeAmt").value);
    if (!raw) return alertBar(T("enterStake", "Enter your stake in NADO — your opponent matches it, winner takes both."));
    if (!canPay(this.dapp, raw, T("whatOpen", "Opening this game"))) return;
    const g = randId();
    this.rec(g, "p1");
    this.active = g;
    this.dapp.call("open", [g], raw, "open " + this.dapp.app.toLowerCase() + " #" + g + " · stake " + rawToNado(raw) + " NADO", { game: g, phase: "open" });
  }
  join() {
    const gm = this.last;
    if (!gm || !gm.exists) { if (gm) this.dapp.clearInvite(); return; }
    if (gm.nn !== 1) { this.dapp.clearInvite(); return; }
    const stake = BigInt(gm.stake);
    if (!canPay(this.dapp, stake, T("whatJoin", "Joining this game"))) return;   // keep the invite: it re-fires when the deposit lands
    this.dapp.clearInvite();
    this.rec(this.active, "p2");
    this.dapp.call("join", [this.active], stake, "join " + this.dapp.app.toLowerCase() + " #" + this.active + " · " + rawToNado(stake) + " NADO stake", { game: this.active, phase: "join" });
  }
  // move(args, label): args come AFTER the game id and BEFORE the ply — ply binding is handled here
  // (the chess retry-race lesson: a stale wallet retry can never land turns later).
  move(args, label, pend) {
    const gm = this.last; if (!gm || gm.sd || gm.turnAddr !== this.dapp.me) return;
    this.dapp.call("move", [this.active].concat(args).concat([gm.mc]), null, label,
      Object.assign({ game: this.active, phase: "move", ply: gm.mc }, pend || {}));
  }
  resign() { this.dapp.call("resign", [this.active], null, "resign #" + this.active, { game: this.active, phase: "resign" }); }
  abort() { this.dapp.call("abort", [this.active], null, "refund a stalled game #" + this.active, { game: this.active, phase: "abort" }); }
  cancel() { this.dapp.call("cancel", [this.active], null, "cancel game #" + this.active, { game: this.active, phase: "cancel" }); }
  async rematch(stakeRaw) {
    const stake = BigInt(stakeRaw);
    if (!canPay(this.dapp, stake, T("whatRematch", "A rematch"))) return;
    // DETERMINISTIC rematch: both players derive the SAME next-game id, so they reconvene in ONE game.
    const rid = rematchId(this.active), rg = await this.fetch(rid);
    this.active = rid; this.pendingMove = null;
    if (rg && rg.exists && rg.nn === 1 && !rg.sd) {
      this.rec(rid, "p2");
      this.dapp.call("join", [rid], stake, "join rematch #" + rid, { game: rid, phase: "join" });
    } else {
      this.rec(rid, "p1");
      this.dapp.call("open", [rid], stake, "rematch #" + rid + " · stake " + rawToNado(stake) + " NADO", { game: rid, phase: "open" });
    }
  }

  // ---- refresh cycle ----
  async refresh() {
    await this.dapp.refresh();
    this.dapp.settleInflight();
    const sto = await this.storage();
    if (sto) {
      this.lastSto = sto;
      lsPrune(this.LS_G, Object.keys(_m(sto, "p1")));
      if (this.active != null) {
        const ng = this.read(sto, this.active);
        // good-faith anti-rollback: ignore a provisional poll that regresses this game
        const prog = (ng.sd ? 1e9 : 0) + (ng.nn || 0) * 100000 + (ng.mc || 0);
        if (this.dapp.accept(this.dapp.app + ":" + this.active, prog)) {
          this.last = ng;
          if (this.pendingMove != null && ng.exists && ng.mc > (this.pendingMove.ply || 0)) this.pendingMove = null;
        }
      }
      if (this.watch) {
        const g = String(this.watch.game);
        const done =
          this.watch.phase === "open" ? !!_m(sto, "p1")[g] :
          this.watch.phase === "join" ? (_m(sto, "nn")[g] || 0) === 2 :
          this.watch.phase === "move" ? (_m(sto, "mc")[g] || 0) > this.watch.ply || !!_m(sto, "sd")[g] :
          !!_m(sto, "sd")[g];
        if (done) {
          okBar({ open: T("stOpen", "✓ Game is on-chain — send your opponent the invite below."),
            join: T("stJoin", "✓ You're in — the opener moves first."), move: T("stMove", "✓ Move landed."),
            resign: T("stResign", "✓ Resigned."), abort: T("stAbort", "✓ Refunded."), cancel: T("stCancel", "✓ Cancelled — stake refunded.") }[this.watch.phase]);
          this.watch = null;
        } else if (this.watch.ts && Date.now() - this.watch.ts > 75000) {
          notify(T("stSettling", "Still settling on-chain — your move and funds are safe; the board updates by itself."));
          this.watch = null;
        }
      }
      this.renderLobby(sto);
      renderScore($("scoreList"), this.boardFrom(sto), this.dapp.me, T("noFinished", "No finished games yet — open the first challenge."));
      const gm = this.last || {};
      await resolveAliases([this.dapp.me, gm.p1, gm.p2].filter(Boolean));
    }
    this.render();
  }
  boardFrom(sto) {
    const stats = {};
    for (const g of Object.keys(_m(sto, "p1"))) {
      if (!_m(sto, "sd")[g]) continue;
      const wr = _m(sto, "wr")[g] || 0, st = _m(sto, "st")[g] || 0;
      const p1 = _m(sto, "p1")[g], p2 = _m(sto, "p2")[g];
      if (!p2 || !wr || wr === 3) continue;                    // cancelled / draw / void games don't rank
      scoreBump(stats, wr === 1 ? p1 : p2, st);
      scoreBump(stats, wr === 1 ? p2 : p1, -st);
    }
    return scoreSort(stats);
  }
  renderLobby(sto) {
    const el = $("lobbyList"); if (!el) return;
    const open = Object.keys(_m(sto, "p1")).map((g) => this.read(sto, g))
      .filter((g) => g.exists && g.nn === 1 && !g.sd).sort((a, b) => b.id - a.id);
    el.innerHTML = open.length ? open.slice(0, this.lobbyN).map((g) =>
      '<button class="chip betting" data-g="' + g.id + '">' + this.cfg.lobbyChip(g) + "</button>").join(" ")
      : '<span class="dim">' + T("noOpen", "No open challenges — start one below.") + "</span>";
    const bm = $("btnMoreLobby");
    if (bm) {
      bm.classList.toggle("hidden", open.length <= this.lobbyN);
      if (open.length > this.lobbyN) bm.textContent = T("showMoreN", "Show more ({n} more)", { n: open.length - this.lobbyN });
    }
    if (!el._deleg) { el._deleg = true; el.addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) this.select(parseInt(b.dataset.g, 10)); }); }
  }
  select(id) { this.active = id; this.pendingMove = null; this.refresh(); }

  // ---- the shared chrome render (board itself is the game's) ----
  render() {
    const dapp = this.dapp, cfg = this.cfg;
    dapp.reflectUrl("game", this.active);
    dapp.syncPctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, dapp.exec);
    const signedIn = renderWallet(dapp);
    gate({ opencard: signedIn, bankroll: signedIn, activeGame: this.active != null });
    const G = lsLoad(this.LS_G);
    const mine = Object.keys(G).map((g) => ({ id: +g, ts: G[g].ts, icon: cfg.icon || "🎯", live: !!(this.lastSto && _m(this.lastSto, "p1")[g]) }))
      .sort((a, b) => b.ts - a.ts).slice(0, 8);
    for (const x of mine) {
      if (!x.live || !this.lastSto) continue;
      const gm = this.read(this.lastSto, x.id);
      x.tag = gm.sd ? T("tagFinished", "finished ✓") : gm.nn === 1 ? T("tagWaiting", "waiting") : gm.turnAddr === dapp.me ? T("tagYourMove", "YOUR MOVE") : T("tagTheirMove", "their move");
    }
    recentChips($("recent"), mine, (id) => this.select(id), "");
    if (this.active == null) return;
    const gm = this.last || {};
    $("gameId").textContent = "#" + this.active;
    shareInvite("game", this.active, cfg.shareText(gm), 180);
    if (!gm.exists) {
      $("verdict").textContent = dapp.whereIs(T("gameWord", "game"), this.active, (G[this.active] || {}).ts);
      $("board").innerHTML = ""; $("gPot").textContent = "—"; $("gPlayers").textContent = "—"; $("gameActions").innerHTML = "";
      return;
    }
    const me1 = gm.p1 === dapp.me, me2 = gm.p2 === dapp.me, playing = me1 || me2;
    $("gPot").textContent = rawToNado(gm.pot || (gm.sd ? 0 : gm.stake)) + " NADO";
    const youTag = T("you", " (you)");
    const [m1, m2] = cfg.marks;
    $("gPlayers").innerHTML = '<span style="color:var(--accent2)">' + m1 + " " + disp(gm.p1) + (me1 ? youTag : "") + "</span> vs " +
      (gm.p2 ? '<span style="color:var(--gold)">' + m2 + " " + disp(gm.p2) + (me2 ? youTag : "") + "</span>" : '<span class="dim">' + T("waitingDots", "waiting…") + "</span>");
    // verdict line
    let v = "";
    if (gm.sd) v = gm.wr === 3 ? (cfg.drawText ? cfg.drawText(gm) : T("draw", "🤝 Draw — both stakes refunded."))
        : T("winsPot", "{mark} wins the pot!", { mark: gm.wr === 1 ? m1 : m2 }) +
        ((gm.wr === 1 && me1) || (gm.wr === 2 && me2) ? T("thatsYou", " 🏆 That's you!") : "");
    else if (gm.nn === 1) v = me1 ? T("waitOpponent", "Waiting for an opponent — share the invite below.") : T("openJoin", "Open challenge — join below!");
    else if (gm.turnAddr === dapp.me) v = '<span class="yourturn">' + (cfg.yourMoveText ? cfg.yourMoveText(gm) : T("yourMove", "▶ YOUR MOVE")) + "</span>";
    else v = T("waitingFor", "Waiting for {who} to move…", { who: disp(gm.turnAddr) });
    $("verdict").innerHTML = v;
    cfg.renderBoard(gm);
    // actions
    const wrap = $("gameActions"); wrap.innerHTML = "";
    const btn = (txt, fn, primary, pulse) => { const b = document.createElement("button"); b.className = (primary ? "primary" : "ghost") + (pulse ? " pulse" : ""); b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; wrap.appendChild(b); return b; };
    if (gm.sd && dapp.me) btn(T("playAgain", "↻ Play again — new game at {stake} NADO", { stake: rawToNado(gm.stake) }), () => this.rematch(gm.stake), true);
    if (!gm.sd && dapp.me) {
      if (gm.nn === 1 && !playing) btn(cfg.marks[1] + " " + T("joinStake", "Join — stake {stake} NADO", { stake: rawToNado(gm.stake) }), () => this.join(), true, true);
      if (gm.nn === 1 && me1) btn(T("cancelRefund", "Cancel — refund my stake"), () => this.cancel(), false);
      if (gm.nn === 2 && playing) btn(T("resignConcede", "🏳 Resign — concede the pot"), () => this.resign(), false);
      if (gm.nn === 2 && dapp.cursor != null && dapp.cursor > gm.dl)
        btn(T("opponentTimedOut", "⏰ Opponent timed out — refund both stakes"), () => this.abort(), true);
      else if (gm.nn === 2 && dapp.cursor != null && gm.turnAddr !== dapp.me && playing)
        wrap.insertAdjacentHTML("beforeend", '<div class="small dim" style="flex:1 1 100%">' + T("moveClock", "move clock: refundable in {t} if they stall", { t: blocksToTime(gm.dl - dapp.cursor) }) + "</div>");
    }
    if (cfg.extraActions) cfg.extraActions(gm, btn);
  }

  // ---- boot ----
  wire() {
    wireWallet(this.dapp);
    this.dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => this.dapp.exec, () => this.render());
    stickyInputs(this.dapp, ["stakeAmt", "bankAmt"]);
    if ($("btnNewGame")) $("btnNewGame").onclick = () => this.open();
    if ($("btnMoreLobby")) $("btnMoreLobby").onclick = () => { this.lobbyN += 48; if (this.lastSto) this.renderLobby(this.lastSto); };
  }
  async boot(orderIds) {
    const dapp = this.dapp, cfg = this.cfg;
    dapp.onReturn((pend, ok, err) => {
      if (pend && pend.game != null) this.active = pend.game;
      if (ok && pend && (pend.phase === "connect" || pend.phase === "deposit")) dapp.consumeInvite((id) => this._replayInvite(id));
      if (!ok) this.pendingMove = null;
      if (ok && pend && ["open", "join", "move", "resign", "abort", "cancel"].includes(pend.phase)) this.watch = Object.assign({}, pend, { ts: Date.now() });
      dapp.showReturn(pend, ok, err, {
        open: T("pendOpen", "Opening the game — confirming…"), join: T("pendJoin", "Joining — confirming…"),
        move: T("pendMove", "Move sent — landing in the next block…"), resign: T("pendResign", "Resigning…"),
        abort: T("pendAbort", "Refunding…"), cancel: T("pendCancel", "Cancelling…") });
    });
    try { await dapp.init(); } catch (e) { alertBar(T("cryptoFail", "Crypto bundle failed to load — reload.")); return; }
    this.wire(); loadQR();
    orderCards(orderIds || ["activeGame", "lobby", "opencard", "walletcard", "bankroll", "scoreboard"]);
    const q = new URLSearchParams(location.search).get("game");
    if (q) {
      this.active = parseInt(q, 10);
      if (!dapp.me) {
        const sto = await this.storage(); const gm = sto ? this.read(sto, this.active) : null;
        inviteGate(dapp, { id: this.active, title: cfg.inviteTitle,
          body: gm && gm.exists ? cfg.inviteBody(gm) : T("inviteBodyGeneric", "Sign in to join this game."),
          joinLabel: T("inviteJoin", "Sign in & join") });
      }
    }
    if (dapp.me) dapp.consumeInvite((id) => this._replayInvite(id));
    this.render(); this.refresh();
    setInterval(() => this.refresh(), 3000);
  }
  async _replayInvite(id) {   // load the invited game FIRST so join()'s state check isn't stale
    this.active = parseInt(id, 10);
    const sto = await this.storage(); if (sto) this.last = this.read(sto, this.active);
    this.join();
  }
}

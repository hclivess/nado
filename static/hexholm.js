// hexholm.js — NADO Hexholm: the classic island-settlement strategy game (mechanics only — every name,
// text and artwork is original), 2-4 players for stakes on the execution layer. Built on the shared SDK:
// nadodapp.js + the move-log duel scaffold (duelgame.js) SUBCLASSED from 2 seats to a 2-4 seat TABLE —
// the contract is the stormhold/chess model widened (escrow + N-seat lobby + free-actor move log + seed
// heights + unanimous-alive agree settle), the referee is the deterministic engine (hexholm-engine.js),
// and hidden scrolls use the battleship/hold'em commit-reveal model (the secret never leaves this
// browser until the game is decided).
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, canPay, alertBar, notify, disp, share,
         renderWallet, renderScore, renderTopScores, scoreBump, scoreSort, resolveAliases, blocksToTime,
         randSecret, algHashn, ALG_P } from "./nadodapp.js";
import { DuelGame } from "./duelgame.js";
import * as E from "./hexholm-engine.js";
import { pickMove, prng, soloReplay, soloScore, botMustAct, seedOfDay, packRun, verifyClaim,
         MAX_MY, SOLO_TURNS } from "./hexholm-bot.js";
import { dayAnchor, verifyEntries } from "./provable.js";
import { randomSeed } from "./practice.js";

const CID = "13b92dc630e513f11a68df9f405d7b2d";
const dapp = new NadoDapp({ cid: CID, app: "Hexholm" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("hex." + k, d, v) : d;
const TS = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("sdk." + k, d, v) : d;   // shared SDK strings (practice chrome)

const SEAT_MARK = ["🟥", "🟦", "🟨", "⬜"];
const SEAT_COL = ["#e0705f", "#5fa8e0", "#e3c34a", "#e6edf3"];
const TILE_COL = { 0: "#2b7a45", 1: "#b0563a", 2: "#8fbf76", 3: "#d9a94a", 4: "#7d8a99", "-1": "#c9b98a" };
const RESN = (r) => T("res_" + E.RES[r], E.RES[r]);
const DEVN = (t) => T("dev_" + t, E.DEV_NAMES[t]);
const SX = 0.8660254, SY = 0.5;                            // render-only lattice → pixel scale

// ---- per-table secret (commit-reveal): lives only in this browser until reveal --------------------
const SKEY = (g) => "nado_hexholm_secret_" + g;
function mySecret(g) {
  let s = null;
  try { s = localStorage.getItem(SKEY(g)); } catch {}
  if (!s) { s = (randSecret() % ALG_P()).toString(); try { localStorage.setItem(SKEY(g), s); } catch {} }
  return BigInt(s);
}
const commitFor = (g) => algHashn([mySecret(g)]);

// =====================================================================================================
// TableDuel — duelgame.js generalized to a 2-4 seat table (same storage idioms, seats as arrays).
// =====================================================================================================
class TableDuel extends DuelGame {
  gameHead(sto, g) {
    g = String(g); const nn = _m(sto, "nn")[g] || 0;
    if (!nn) return { exists: false, id: Number(g) };
    const seats = [], commits = [], agrees = [], resigned = [], reveals = [];
    for (let i = 1; i <= 4; i++) {
      seats.push(_m(sto, "p" + i)[g] || null);
      commits.push(_m(sto, "c" + i)[g] || 0);
      agrees.push(_m(sto, "a" + i)[g] || 0);
      resigned.push(!!_m(sto, "rs" + i)[g]);
      const hi = _m(sto, "r" + i + "h")[g] || 0, lo = _m(sto, "r" + i + "l")[g] || 0;
      reveals.push((hi || lo) ? BigInt(hi) * 4294967296n + BigInt(lo) : 0n);
    }
    return { exists: true, id: Number(g), nn, cap: _m(sto, "cap")[g] || 2,
      seats, commits, agrees, resigned, reveals, rc: _m(sto, "rc")[g] || 0,
      p1: seats[0], p2: seats[1],                          // base-class compat (recent chips etc.)
      stake: _m(sto, "st")[g] || 0, pot: _m(sto, "pt")[g] || 0, settled: !!_m(sto, "sd")[g],
      dl: _m(sto, "dl")[g] || 0, mc: _m(sto, "mc")[g] || 0, kh: _m(sto, "kh")[g] || 0,
      wr: _m(sto, "wr")[g] || 0, a1: 0, a2: 0, c1: 0, c2: 0 };
  }
  gameFrom(sto, g) {
    const h = this.gameHead(sto, g);
    if (!h.exists) return h;
    const mv = _m(sto, "mv"), mh = _m(sto, "mh");
    h.recs = [];
    for (let i = 0; i < h.mc; i++) {
      const enc = mv[String(h.id * 10000 + i)], rec = mh[String(h.id * 10000 + i)];
      if (!enc || !rec) { h.gap = true; break; }
      h.recs.push({ enc, side: rec % 8, rh: Math.floor(rec / 8) });
    }
    return h;
  }
  myIdx(gm) {
    if (gm && gm.practice) return 0;
    if (!gm || !gm.seats) return null;
    const i = gm.seats.indexOf(this.dapp.me);
    return i >= 0 ? i : null;
  }
  canAct() {
    if (this.practice) {
      const eng = this.eng;
      return !!(eng && eng.layout && !eng.corrupt && !eng.over && !eng.blocked && !this.soloDone()
                && !botMustAct(eng) && E.actorsNow(eng).includes(1));
    }
    const gm = this.last, eng = this.eng;
    if (!gm || !gm.exists || gm.nn !== gm.cap || gm.settled || this.pendingMove) return false;
    if (!eng || eng.blocked || eng.corrupt || eng.over || eng.mi !== gm.mc) return false;
    const me = this.myIdx(gm);
    return me != null && !gm.resigned[me] && E.actorsNow(eng).includes(me + 1);
  }
  submit(enc, label) {                                     // raw engine enc + ply binding
    if (this.practice) {
      if (!this.canAct()) return;
      this.practice.recs.push({ enc, side: 1 });
      this._soloBotLoop();
      this.prac.saveRun(this.practice);
      this.armed = null; this.mode = null;
      this.render();
      return;
    }
    const gm = this.last;
    if (!gm || this.pendingMove || !this.canAct()) return;
    const ply = gm.mc;
    this.pendingMove = { ply }; this.armed = null; this.mode = null;
    this.dapp.call("move", [this.active, enc, ply], null, label + " · table #" + this.active, { game: this.active, phase: "move", ply });
    this.render();
  }
  async joinGame() {
    const dapp = this.dapp;
    const g = parseInt($("joinId").value, 10);
    if (!g) return alertBar(T("enterGameId", "Enter a table ID (or pick one from the lobby)."));
    const sto = await dapp.storage({ append: this.MAPS });
    const gm = sto ? this.gameHead(sto, g) : null;
    if (!gm || !gm.exists) { alertBar(dapp.whereIs(T("gameWord", "table"), g)); if (gm) dapp.clearInvite(); return; }
    if (gm.nn >= gm.cap || gm.settled) { alertBar(T("fullOrFinished", "That table is full or finished.")); dapp.clearInvite(); return; }
    if (this.myIdx(gm) != null) { alertBar(T("alreadySeated", "You are already seated at this table.")); return; }
    await dapp.refresh();
    const stake = BigInt(gm.stake);
    if (!canPay(dapp, stake, T("whatJoin", "Joining this table"))) { this.render(); return; }
    dapp.clearInvite();
    const G = this.lsLoad(); G[g] = { role: "px", stake: stake.toString(), ts: Date.now() }; this.lsSave(G);
    this.active = g; this.resetLocal(); this.render();
    dapp.call("join", [g, commitFor(g)], stake,
      "join hexholm table #" + g + " · " + rawToNado(stake) + " NADO stake", { game: g, phase: "join" });
  }
  async rematch() {                                        // base drops joinExtra — table version keeps the commit
    const dapp = this.dapp;
    const g = this.last; if (!g || !g.exists) return;
    const stake = BigInt(g.stake);
    if (!canPay(dapp, stake, T("whatRematch", "A rematch"))) return;
    const rid = (this.active % 1000000) + 1000000 * (1 + Math.floor(this.active / 1000000));
    const sto = await dapp.storage({ append: this.MAPS });
    const rg = sto ? this.gameHead(sto, rid) : null;
    this.active = rid; this.resetLocal(); $("joinId").value = String(rid);
    const G = this.lsLoad(); G[rid] = { role: "px", stake: stake.toString(), ts: Date.now() }; this.lsSave(G);
    if (rg && rg.exists && rg.nn < rg.cap && !rg.settled && this.myIdx(rg) == null)
      dapp.call("join", [rid, commitFor(rid)], stake, "join rematch #" + rid, { game: rid, phase: "join" });
    else if (!rg || !rg.exists)
      dapp.call("open", [rid, g.cap, commitFor(rid)], stake, "rematch #" + rid + " · stake " + rawToNado(stake) + " NADO", { game: rid, phase: "open" });
    this.render();
  }
  leave() { this.dapp.call("leave", [this.active], null, "leave table #" + this.active, { game: this.active, phase: "leave" }); }
  agreeSeat(w) { this.dapp.call("agree", [this.active, w], null, "confirm the result · table #" + this.active, { game: this.active, phase: "agree" }); }
  reveal() { this.dapp.call("reveal", [this.active, mySecret(this.active)], null, "reveal scrolls · table #" + this.active, { game: this.active, phase: "agree" }); }

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
      if (this.active != null && !this.practice) {
        const ng = this.gameFrom(sto, this.active);
        const prog = (ng.settled ? 1e9 : 0) + (ng.nn || 0) * 100000 + (ng.mc || 0)
          + (ng.reveals || []).filter((r) => r).length * 10000000;
        if (dapp.accept(dapp.app + ":" + this.active, prog) && !ng.gap) {
          this.last = ng;
          if (this.pendingMove != null && ng.mc > this.pendingMove.ply) this.pendingMove = null;
          if (ng.exists && ng.nn === ng.cap) {
            await this.ensureSeeds(ng);
            this.eng = this.rebuild(ng);
            if (this.eng && this.eng.mi !== this.lastMi) { this.armed = null; this.mode = null; this.lastMi = this.eng.mi; }
          } else this.eng = null;
        }
      }
      dapp.settleInflight((f) => {
        const g = this.gameHead(sto, f.game);
        return f.phase === "open" ? g.exists
          : f.phase === "join" ? (g.exists && g.seats && g.seats.includes(dapp.me))
          : f.phase === "leave" ? (!g.exists || !g.seats || !g.seats.includes(dapp.me))
          : f.phase === "move" ? g.mc > (f.ply || 0)
          : (g.settled || !g.exists);
      });
      this.renderLobby(sto);
      renderScore($("scoreList"), this.boardFrom(sto), dapp.me,
        T("noFinished", "No settled tables yet — win the first one."), true);
      this.renderDailyBoard(sto).catch(() => {});
    }
    await resolveAliases([dapp.me].concat(this.last && this.last.seats ? this.last.seats : []).filter(Boolean));
    this.render();
  }
  rebuild(gm) {
    if (gm && gm.practice) return soloReplay(this.practice.seed, gm.recs);
    const qkh = this.qOf(gm.kh);
    const recs = (gm.recs || []).map((r) => ({ enc: r.enc, side: r.side, q: this.qOf(r.rh) }));
    const me = this.myIdx(gm), secrets = {};
    for (let s = 1; s <= gm.cap; s++) {
      if (gm.reveals[s - 1]) secrets[s] = gm.reveals[s - 1];
      else if (me === s - 1) secrets[s] = mySecret(gm.id);
      else secrets[s] = null;
    }
    return E.replay(qkh, recs, { cap: gm.cap, secrets, commits: gm.commits });
  }
  boardFrom(sto) {                                         // scoreboard: winner takes every loser's stake
    const stats = {};
    for (const g of Object.keys(_m(sto, "nn"))) {
      if (!_m(sto, "sd")[g]) continue;
      const wr = _m(sto, "wr")[g] || 0, st = _m(sto, "st")[g] || 0;
      if (!wr || wr === 5) continue;
      const seats = [1, 2, 3, 4].map((i) => _m(sto, "p" + i)[g]).filter(Boolean);
      const winner = _m(sto, "p" + wr)[g];
      if (!winner || seats.length < 2) continue;
      for (const s of seats) scoreBump(stats, s, s === winner ? st * (seats.length - 1) : -st);
    }
    return scoreSort(stats);
  }
  renderLobby(sto) {
    const el = $("lobbyList"); if (!el) return;
    const games = Object.keys(_m(sto, "nn")).map((g) => this.gameHead(sto, g)).filter((g) => g.exists && !g.settled);
    games.sort((a, b) => ((a.nn === a.cap) - (b.nn === b.cap)) || (b.id - a.id));
    const shown = games.slice(0, 24);
    el.innerHTML = shown.length ? shown.map((g) => {
      const open = g.nn < g.cap;
      const verb = open ? T("joinSuffix", " · join") : T("watchSuffix", " · watch");
      return '<button class="chip ' + (open ? "open" : "live") + '" data-g="' + g.id + '">' + (open ? "⬡" : "▶")
        + " #" + g.id + " · " + g.nn + "/" + g.cap + " · " + rawToNado(g.stake) + " NADO" + verb + "</button>";
    }).join(" ") : '<span class="dim">' + T("noGamesLobby", "No tables yet — open one above.") + "</span>";
    el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { this.active = parseInt(b.dataset.g, 10); this.resetLocal(); $("joinId").value = b.dataset.g;
      notify(T("gameSelected", "Table #{id} selected.", { id: this.active })); this.refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
  }

  // ---- SOLO practice + the provable DAILY GAUNTLET (hexholm-bot.js soloState model) ----------------
  pracGm() {
    const recs = (this.practice.recs || []).map((r, i) => ({ enc: r.enc, side: r.side, rh: 1000 + i }));
    return { exists: true, practice: true, id: 0, nn: 2, cap: 2,
      seats: [TS("prYou", "You"), "\u{1F916} " + TS("prCpu", "Computer"), null, null],
      seatNames: true, commits: [1, 1, 0, 0], agrees: [0, 0, 0, 0],
      resigned: [false, false, false, false], reveals: [0n, 0n, 0n, 0n], rc: 0,
      p1: "you", p2: "cpu", stake: 0, pot: 0, settled: false, mc: recs.length,
      dl: Number.MAX_SAFE_INTEGER, kh: 999, wr: 0, recs };
  }
  myEnds() { return (this.practice.recs || []).filter((r) => r.side === 1 && r.enc % 64 === E.OP.END).length; }
  soloDone() {
    return !!this.practice && (this.myEnds() >= SOLO_TURNS || (this.eng && this.eng.over));
  }
  _soloBotLoop() {
    for (let guard = 0; guard < 300; guard++) {
      this.eng = this.rebuild(this.pracGm());
      if (!this.eng || this.eng.corrupt || this.eng.over || this.myEnds() >= SOLO_TURNS) return;
      if (!botMustAct(this.eng)) return;
      const mv = pickMove(this.eng, 2, prng(this.practice.seed + ":bot:" + this.practice.recs.length));
      if (mv == null) return;
      this.practice.recs.push({ enc: mv, side: 2 });
    }
  }
  startPractice(seed) {
    this.active = null; this.resetLocal();
    this.practice = { seed: seed || randomSeed("hexholm"), recs: [], daily: null };
    this._soloBotLoop();
    this.prac.saveRun(this.practice);
    this.render();
    try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
  }
  async startDaily() {
    const day = Math.floor(Date.now() / 86400000);
    if (!this.dapp.me) notify(T("dailyAnonHint", "Playing signed out — sign in BEFORE starting if you want this run to count on the board."));
    if (this._anch.day !== day) this._anch = { day, hash: await dayAnchor(base(), day).catch(() => null) };
    if (!this._anch.hash) return notify(T("dailyNotReady", "Today's island is still being seeded by the chain — try again in a minute."));
    this.active = null; this.resetLocal();
    this.practice = { seed: seedOfDay(day, this._anch.hash, this.dapp.me || "anon"), recs: [], daily: day };
    this._soloBotLoop();
    this.prac.saveRun(this.practice);
    this.render();
    try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
  }
  exitPractice() { this.practice = null; this.prac.clearRun(); this.eng = null; this.active = null; this.render(); }
  postDaily() {
    const p = this.practice, eng = this.eng;
    if (!p || !p.daily || !eng || !this.soloDone() || eng.corrupt) return;
    const my = p.recs.filter((r) => r.side === 1).map((r) => r.enc);
    if (!(my.length > 0 && my.length <= MAX_MY)) return notify(T("postTooLong", "This run is too long to post — dailies cap at {n} of your moves.", { n: MAX_MY }));
    const score = soloScore(eng, my.length);
    this.dapp.call("post", [p.daily, score, my.length].concat(packRun(my)), null,
      "post daily island score " + score, { phase: "agree" });
    notify(T("postSent", "Score submitted — it appears on the board once verified."));
  }
  async renderDailyBoard(sto) {
    const el = $("dailyList"); if (!el || this._boardBusy) return;
    this._boardBusy = true;
    try {
      const day = Math.floor(Date.now() / 86400000);
      if (this._anch.day !== day) this._anch = { day, hash: await dayAnchor(base(), day).catch(() => null) };
      const anch = this._anch.hash; if (!anch) return;
      const eday = _m(sto, "eday"), eaddr = _m(sto, "eaddr"), escore = _m(sto, "escore"), en = _m(sto, "en"), ew = _m(sto, "ew");
      const entries = [];
      for (const e of Object.keys(eday)) {
        if (eday[e] !== day) continue;
        const words = [];
        for (let i = 0; i < 150; i++) words.push(ew[String(Number(e) * 10000 + i)] || 0);
        entries.push({ e, day, addr: eaddr[e], score: escore[e] || 0, n: en[e] || 0, words });
      }
      const rows = await verifyEntries(entries, (en2) => verifyClaim(day, en2.n, en2.words, anch, en2.addr));
      renderTopScores(el, rows, this.dapp.me,
        T("noSoloScores", "No verified scores today — finish a daily island and post yours."),
        T("scoreHeadCol", "Score"), true);
    } finally { this._boardBusy = false; }
  }

  // ---- the whole active-table chrome (N-seat rewrite of the base renderActive) ---------------------
  renderActive() {
    const dapp = this.dapp, box = $("activeGame");
    if (this.practice) return this.renderPracticeTable();
    const pn = $("btnPracNew"), px = $("btnPracExit"), pp = $("btnPracPost");
    if (pn) { pn.classList.add("hidden"); px.classList.add("hidden"); if (pp) pp.classList.add("hidden"); }
    if (this.active == null) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const gm = this.last || {}, local = this.lsLoad()[this.active] || {}, me = this.myIdx(gm), eng = this.eng;
    $("gameId").textContent = "#" + this.active;
    $("shareLink").value = base() + "/?game=" + this.active;
    $("gPot").textContent = gm.exists ? rawToNado(gm.pot) + " NADO" : "—";
    // players line
    $("players").innerHTML = gm.exists ? gm.seats.slice(0, gm.cap).map((a, i) => {
      const nm = a ? disp(a) + (a === dapp.me ? T("youSuffix", " (you)") : "") : T("openSeatWord", "open seat");
      const dead = gm.resigned[i] ? " style='opacity:.45;text-decoration:line-through'" : "";
      return "<span class='chip'" + dead + ">" + SEAT_MARK[i] + " " + nm + "</span>";
    }).join(" ") : "—";
    // status line
    let st = dapp.whereIs(T("gameWord", "table"), this.active, local.ts);
    const live = gm.exists && gm.nn === gm.cap && !gm.settled;
    const winnerSeat = eng && eng.over ? eng.winner : 0;
    if (gm.exists && gm.settled) {
      st = gm.wr === 5 ? T("refunded", "✓ dissolved — stakes refunded")
        : gm.wr ? (me != null && gm.wr === me + 1 ? T("winYou", "✓ You won the pot! 🏆")
          : T("winSeat", "✓ {who} takes the pot", { who: disp(gm.seats[gm.wr - 1] || "?") }))
        : T("settled", "✓ settled");
    }
    else if (gm.exists && eng && eng.corrupt) st = T("illegal", "⚠ an illegal move reached the chain (seat {s}) — honest clients stop here; refund after the timeout.", { s: eng.corrupt });
    else if (gm.exists && gm.nn < gm.cap) st = T("waitingSeats", "waiting for players — {n}/{cap} seated. Share the invite below.", { n: gm.nn, cap: gm.cap });
    else if (eng && eng.blocked) st = T("shuffling", "🌀 waiting for the randomness block…");
    else if (eng && eng.mi < gm.mc) st = T("catchingUp", "replaying the on-chain log…");
    else if (eng && eng.over) st = winnerSeat === me + 1 ? T("overWin", "Game over — YOU WIN 🏆")
      : T("overSeat", "Game over — {who} wins", { who: disp(gm.seats[winnerSeat - 1] || "?") });
    else if (live && eng) {
      const mine = this.canAct() && E.actorsNow(eng)[0] === me + 1;
      st = this.pendingMove ? T("moveConfirming", "your move is confirming…")
        : mine ? "<span class='yourturn'>" + T("yourMove", "▶ YOUR MOVE") + "</span>"
        : this.canAct() ? T("canRespond", "you may trade / respond")
        : T("waitingFor", "waiting for {who}…", { who: disp(gm.seats[(E.actorsNow(eng)[0] || 1) - 1] || "…") });
    }
    $("gStatus").innerHTML = st;
    $("dicebar").textContent = eng && eng.dice && eng.phase !== "preroll"
      ? "🎲 " + eng.dice + (eng.dice === 7 ? " — " + T("marauderMoves", "the Marauder moves!") : "") : "";
    renderBoard(this, gm, eng, me);
    renderSeats(this, gm, eng, me);
    renderCtrls(this, gm, eng, me);
    renderOffers(this, gm, eng, me);
    renderScrolls(this, gm, eng, me);
    renderDiscard(this, gm, eng, me);
    renderLog(eng, gm);
    renderSettle(this, gm, eng, me);
  }

  renderPracticeTable() {
    const box = $("activeGame");
    box.classList.remove("hidden");
    const gm = this.pracGm(), eng = this.eng;
    this.last = gm;
    $("gameId").textContent = this.practice.daily ? "\u{1F4C5}" : "\u{1F3AF}";
    $("shareLink").value = base();
    $("gPot").textContent = this.practice.daily
      ? T("dailyBanner", "DAILY ISLAND — {n} turns, free, postable to the board", { n: SOLO_TURNS })
      : TS("prBanner", "PRACTICE — free play, nothing on-chain");
    $("players").innerHTML = gm.seats.slice(0, 2).map((nm, i) =>
      "<span class='chip'>" + SEAT_MARK[i] + " " + nm + "</span>").join(" ");
    const done = this.soloDone(), vp = eng && eng.layout ? E.totalVp(eng, 1) : 0;
    $("gStatus").innerHTML = !eng ? "…"
      : eng.corrupt ? T("prCorrupt", "practice run desynced — start a new one")
      : done ? T("dailyDone", "Run complete — {vp} points in {n} moves", { vp, n: (this.practice.recs || []).filter((r) => r.side === 1).length })
      : this.canAct() ? "<span class='yourturn'>" + T("yourMove", "\u25B6 YOUR MOVE") + "</span>" + " · " + T("dailyTurnN", "turn {t}/{n}", { t: Math.min(SOLO_TURNS, this.myEnds() + 1), n: SOLO_TURNS })
      : TS("prCpuThinking", "computer to move…");
    $("dicebar").textContent = eng && eng.dice && eng.phase !== "preroll" ? "\u{1F3B2} " + eng.dice : "";
    renderBoard(this, gm, eng, 0);
    renderSeats(this, gm, eng, 0);
    renderCtrls(this, gm, eng, 0);
    renderOffers(this, gm, eng, 0);
    renderScrolls(this, gm, eng, 0);
    renderDiscard(this, gm, eng, 0);
    renderLog(eng, gm);
    for (const id of ["btnResign", "btnDraw", "btnSettle", "btnAbort", "btnCancel", "btnLeave", "btnJoinGame", "btnRematch"])
      $(id).classList.add("hidden");
    $("revealBar").innerHTML = "";
    $("settleHint").textContent = "";
    const row = $("btnResign").parentElement;
    let pn = $("btnPracNew"), px = $("btnPracExit"), pp = $("btnPracPost");
    if (!pn) {
      pn = document.createElement("button"); pn.id = "btnPracNew"; pn.className = "ghost";
      px = document.createElement("button"); px.id = "btnPracExit"; px.className = "ghost";
      pp = document.createElement("button"); pp.id = "btnPracPost"; pp.className = "primary pulse";
      row.appendChild(pp); row.appendChild(pn); row.appendChild(px);
      pn.onclick = () => this.startPractice();
      px.onclick = () => this.exitPractice();
      pp.onclick = () => this.postDaily();
    }
    pn.classList.remove("hidden"); px.classList.remove("hidden");
    pn.textContent = "\u21BB " + T("prNewGame", "New practice island");
    px.textContent = TS("prExit", "Back to real play");
    const canPost = done && this.practice.daily && eng && !eng.corrupt && this.dapp.me
      && this.practice.seed === seedOfDay(this.practice.daily, this._anch.hash, this.dapp.me);
    pp.classList.toggle("hidden", !canPost);
    if (canPost) pp.textContent = "\u{1F3C6} " + T("postScore", "Post my score on the daily board");
  }
}

// ---- board rendering --------------------------------------------------------------------------------
const px = (v) => (E.GEO.verts[v].x * SX).toFixed(3) + "," + (E.GEO.verts[v].y * SY).toFixed(3);
function hexPoints(h) { return E.GEO.hexes[h].corners.map((v) => px(v)).join(" "); }
function renderBoard(duel, gm, eng, me) {
  const svg = $("board");
  svg.setAttribute("viewBox", "-5.6 -5.3 11.2 10.6");
  if (!eng || !eng.layout) { svg.innerHTML = ""; $("boardHint").textContent = ""; return; }
  const st = eng, lay = st.layout, mode = duel.mode, out = [];
  for (let h = 0; h < E.NHEX; h++) {
    const cx = E.GEO.hexes[h].X * SX, cy = E.GEO.hexes[h].Y * SY;
    out.push(`<polygon class="hx" points="${hexPoints(h)}" fill="${TILE_COL[lay.tiles[h]]}"/>`);
    if (lay.tokens[h]) {
      const hot = lay.tokens[h] === 6 || lay.tokens[h] === 8;
      out.push(`<circle class="tokc${hot ? " hot" : ""}" cx="${cx}" cy="${cy}" r=".34"/>`);
      out.push(`<text class="tok${hot ? " hot" : ""}" x="${cx}" y="${cy + 0.15}">${lay.tokens[h]}</text>`);
    }
    if (st.robber === h) out.push(`<text class="marauder" x="${cx}" y="${cy - 0.28}">🏴</text>`);
  }
  E.GEO.PORT_AT.forEach((e, i) => {                        // harbors float just off their coastal edge
    const ed = E.GEO.edges[e], a = E.GEO.verts[ed.a], b = E.GEO.verts[ed.b];
    const mx = (a.x + b.x) / 2 * SX, my = (a.y + b.y) / 2 * SY;
    const ox = mx * 1.18, oy = my * 1.18;
    const t = lay.ports[i];
    out.push(`<text class="port" x="${ox}" y="${oy}">${t < 0 ? "3:1" : "2:1" + E.RES_ICON[t]}</text>`);
  });
  for (let s = 1; s <= st.cap; s++) {                       // roads under buildings
    for (const e of st.players[s].roads) {
      const ed = E.GEO.edges[e];
      out.push(`<line class="road" x1="${E.GEO.verts[ed.a].x * SX}" y1="${E.GEO.verts[ed.a].y * SY}" x2="${E.GEO.verts[ed.b].x * SX}" y2="${E.GEO.verts[ed.b].y * SY}" stroke="${SEAT_COL[s - 1]}"/>`);
    }
  }
  for (let s = 1; s <= st.cap; s++) {
    for (const v of st.players[s].steads) {
      const x = E.GEO.verts[v].x * SX, y = E.GEO.verts[v].y * SY;
      out.push(`<path class="stead" d="M${x - 0.22} ${y + 0.18} v-.22 l.22 -.18 l.22 .18 v.22 z" fill="${SEAT_COL[s - 1]}"/>`);
    }
    for (const v of st.players[s].keeps) {
      const x = E.GEO.verts[v].x * SX, y = E.GEO.verts[v].y * SY;
      out.push(`<path class="stead" d="M${x - 0.28} ${y + 0.22} v-.3 h.16 v-.12 h.1 v.12 h.08 v-.12 h.1 v.12 h.12 v.3 z" fill="${SEAT_COL[s - 1]}"/>`);
    }
  }
  // interactive targets by mode
  const meSeat = me != null ? me + 1 : 0;
  const legalV = new Set(), legalE = new Set(), legalH = new Set();
  if (duel.canAct() && meSeat && mode) {
    if (mode.kind === "setup" && !mode.picks.length)
      for (let v = 0; v < E.NVERT; v++) { if (E.vertexFree(st, v)) legalV.add(v); }
    else if (mode.kind === "setup" && mode.picks.length === 1)
      for (const e of E.GEO.verts[mode.picks[0]].edges) { if (E.edgeFree(st, e)) legalE.add(e); }
    else if (mode.kind === "road" || (mode.kind === "path"))
      for (let e = 0; e < E.NEDGE; e++) { if (E.edgeFree(st, e) && !mode.picks.includes(e) && E.edgeTouchesOwn(st, meSeat, e)) legalE.add(e); }
    else if (mode.kind === "stead")
      for (let v = 0; v < E.NVERT; v++) { if (E.steadSpotOk(st, meSeat, v)) legalV.add(v); }
    else if (mode.kind === "keep")
      for (const v of st.players[meSeat].steads) legalV.add(v);
    else if (mode.kind === "robber" || mode.kind === "warden")
      for (let h = 0; h < E.NHEX; h++) { if (h !== st.robber) legalH.add(h); }
  }
  for (const h of legalH) out.push(`<polygon class="tgt legal" data-h="${h}" points="${hexPoints(h)}"/>`);
  for (const e of legalE) { const ed = E.GEO.edges[e];
    out.push(`<line class="tgt legal" data-e="${e}" x1="${E.GEO.verts[ed.a].x * SX}" y1="${E.GEO.verts[ed.a].y * SY}" x2="${E.GEO.verts[ed.b].x * SX}" y2="${E.GEO.verts[ed.b].y * SY}" stroke="rgba(0,201,167,.55)" stroke-width=".2" stroke-linecap="round"/>`); }
  for (const v of legalV) out.push(`<circle class="tgt legal" data-v="${v}" cx="${E.GEO.verts[v].x * SX}" cy="${E.GEO.verts[v].y * SY}" r=".26"/>`);
  svg.innerHTML = out.join("");
  $("boardHint").textContent = !mode ? "" :
    mode.kind === "setup" ? (mode.picks.length ? T("hintSetupRoad", "…now tap an adjacent road spot") : T("hintSetupStead", "tap a corner for your homestead")) :
    mode.kind === "road" ? T("hintRoad", "tap an edge to build the road") :
    mode.kind === "path" ? T("hintPath", "tap {n} road spots", { n: 2 - mode.picks.length }) :
    mode.kind === "stead" ? T("hintStead", "tap a corner to build the homestead") :
    mode.kind === "keep" ? T("hintKeep", "tap one of your homesteads") :
    (mode.kind === "robber" || mode.kind === "warden") ? T("hintRobber", "tap a hex for the Marauder") : "";
  svg.querySelectorAll(".tgt.legal").forEach((el) => el.addEventListener("click", () => boardTap(duel, el)));
}
function boardTap(duel, el) {
  const eng = duel.eng, me = duel.myIdx(duel.last), meSeat = me + 1, mode = duel.mode;
  if (!mode) return;
  if (el.dataset.v != null) {
    const v = Number(el.dataset.v);
    if (mode.kind === "setup") { mode.picks.push(v); duel.render(); return; }
    if (mode.kind === "stead") return duel.submit(E.enc(E.OP.STEAD, v), "build a homestead");
    if (mode.kind === "keep") return duel.submit(E.enc(E.OP.KEEP, v), "raise a keep");
  }
  if (el.dataset.e != null) {
    const e = Number(el.dataset.e);
    if (mode.kind === "setup" && mode.picks.length === 1)
      return duel.submit(E.enc(E.OP.SETUP, mode.picks[0], e), "place homestead + road");
    if (mode.kind === "road") return duel.submit(E.enc(E.OP.ROAD, e), "build a road");
    if (mode.kind === "path") {
      mode.picks.push(e);
      if (mode.picks.length === 2) return duel.submit(E.enc(E.OP.PATH, mode.picks[0], mode.picks[1]), "play a Pathwright");
      duel.render(); return;
    }
  }
  if (el.dataset.h != null) {
    const h = Number(el.dataset.h);
    const vics = [...new Set([...Array(4)].flatMap((_, i) => i + 1))].filter((s) => s !== meSeat &&
      E.GEO.hexes[h].corners.some((v) => duel.eng.players[s] && (eng.players[s].steads.has(v) || eng.players[s].keeps.has(v))) &&
      eng.players[s].res.reduce((a, b) => a + b, 0) > 0);
    const op = mode.kind === "warden" ? E.OP.WARDEN : E.OP.ROBBER;
    const label = mode.kind === "warden" ? "play a Warden" : "move the Marauder";
    if (vics.length === 0) return duel.submit(E.enc(op, h, 0), label);
    if (vics.length === 1) return duel.submit(E.enc(op, h, vics[0]), label);
    duel.mode = { kind: "victim", op, hex: h, vics, label };
    duel.render();
  }
}

// ---- seat panels ------------------------------------------------------------------------------------
function renderSeats(duel, gm, eng, me) {
  const el = $("seatPanels");
  if (!gm.exists || !eng || !eng.layout) { el.innerHTML = ""; $("bankLine").textContent = ""; return; }
  $("bankLine").textContent = T("bankLine", "bank") + ": " + eng.bank.map((n, r) => E.RES_ICON[r] + n).join(" ");
  el.innerHTML = Array.from({ length: gm.cap }, (_, i) => {
    const s = i + 1, p = eng.players[s];
    const nm = gm.seatNames ? gm.seats[i] : disp(gm.seats[i] || "?") + "";
    const vp = E.totalVp(eng, s), pub = E.publicVp(eng, s);
    const held = p.devDrawn - eng.playsLog.filter((x) => x.s === s).length;
    const turn = eng.turnSeat === s && !eng.over && eng.phase !== "setup";
    return `<div class="seatp${turn ? " turn" : ""}${i === me ? " me" : ""}${gm.resigned[i] ? " resigned" : ""}">
      <div class="nm"><span>${SEAT_MARK[i]} ${nm}</span>
        <span class="vp">${vp != null ? vp : pub + "+?"} ${T("vp", "pts")}</span></div>
      <div class="resrow">${eng.secrets[s] != null || i === me ? p.res.map((n, r) => E.RES_ICON[r] + n).join(" ") : p.res.map((n, r) => E.RES_ICON[r] + n).join(" ")}</div>
      <div class="badges">🛣${p.roadLen}${eng.roadHolder === s ? "🏅" : ""} · ⚔${p.plays[E.WARDEN]}${eng.watchHolder === s ? "🏅" : ""} · 📜${held}</div>
    </div>`;
  }).join("");
}

// ---- contextual controls ---------------------------------------------------------------------------
const costTxt = (c) => c.map((n, r) => n ? E.RES_ICON[r] + n : "").filter(Boolean).join("");
function renderCtrls(duel, gm, eng, me) {
  const el = $("ctrls"), meSeat = me != null ? me + 1 : 0;
  $("myRes").textContent = eng && meSeat && eng.players[meSeat]
    ? eng.players[meSeat].res.map((n, r) => E.RES_ICON[r] + n).join("  ") : "";
  if (!duel.canAct() || !eng) { el.innerHTML = ""; if (!duel.mode) $("tradeBox").classList.add("hidden"); return; }
  const st = eng, moves = E.legalMoves(st, meSeat), ops = new Set(moves.map((m) => E.dec(m).op));
  const B = [];
  const btn = (id, label, cls) => B.push(`<button id="${id}" class="${cls || "ghost"}">${label}</button>`);
  if (duel.mode && duel.mode.kind === "victim") {
    el.innerHTML = duel.mode.vics.map((s) =>
      `<button class="primary" data-vic="${s}">${T("stealFrom", "Steal from")} ${SEAT_MARK[s - 1]} ${disp(gm.seats[s - 1])}</button>`).join("");
    el.querySelectorAll("[data-vic]").forEach((b) => b.onclick = () =>
      duel.submit(E.enc(duel.mode.op, duel.mode.hex, Number(b.dataset.vic)), duel.mode.label));
    return;
  }
  if (st.phase === "setup" && ops.has(E.OP.SETUP)) {
    duel.mode = duel.mode && duel.mode.kind === "setup" ? duel.mode : { kind: "setup", picks: [] };
    el.innerHTML = `<span class="small dim">${T("setupTurn", "Your founding turn — place a homestead and its road on the island above.")}</span>`;
    return;
  }
  if (st.phase === "robber" && ops.has(E.OP.ROBBER)) {
    duel.mode = duel.mode && (duel.mode.kind === "robber" || duel.mode.kind === "victim") ? duel.mode : { kind: "robber", picks: [] };
    el.innerHTML = `<span class="small dim">${T("robberTurn", "A 7! Move the Marauder — tap a hex above.")}</span>`;
    return;
  }
  if (ops.has(E.OP.ROLL)) btn("bRoll", "🎲 " + T("roll", "Roll the dice"), "primary pulse");
  if (ops.has(E.OP.WIN)) btn("bWin", "🏆 " + T("callWin", "Call the win — 10+ points!"), "primary pulse");
  if (st.phase === "main" && meSeat === st.turnSeat) {
    const p = st.players[meSeat];
    const aff = (c) => c.every((n, r) => p.res[r] >= n);
    B.push(`<button id="bRoad" class="ghost${duel.mode && duel.mode.kind === "road" ? " armed" : ""}" ${ops.has(E.OP.ROAD) ? "" : "disabled"}>🛣 ${T("road", "Road")}<span class="cost">${costTxt(E.COST.road)}</span></button>`);
    B.push(`<button id="bStead" class="ghost${duel.mode && duel.mode.kind === "stead" ? " armed" : ""}" ${ops.has(E.OP.STEAD) ? "" : "disabled"}>🏠 ${T("stead", "Homestead")}<span class="cost">${costTxt(E.COST.stead)}</span></button>`);
    B.push(`<button id="bKeep" class="ghost${duel.mode && duel.mode.kind === "keep" ? " armed" : ""}" ${ops.has(E.OP.KEEP) ? "" : "disabled"}>🏰 ${T("keep", "Keep")}<span class="cost">${costTxt(E.COST.keep)}</span></button>`);
    B.push(`<button id="bBuy" class="ghost" ${ops.has(E.OP.BUY) ? "" : "disabled"}>📜 ${T("scroll", "Scroll")}<span class="cost">${costTxt(E.COST.scroll)}</span></button>`);
    // bank trade: pick give (best rate shown) + get
    const rates = E.RES.map((_, r) => E.bankRate(st, meSeat, r));
    const canBank = E.RES.some((_, r) => p.res[r] >= rates[r]);
    B.push(`<button id="bBank" class="ghost" ${canBank ? "" : "disabled"}>⚖ ${T("bankTrade", "Bank trade")}</button>`);
    btn("bOffer", "📣 " + T("tableTrade", "Table trade"));
    btn("bEnd", "⏭ " + T("endTurn", "End turn"));
  } else if (st.phase === "main") {
    btn("bOffer", "📣 " + T("offerMover", "Offer a trade to the mover"));
  }
  el.innerHTML = B.join("");
  const arm = (kind) => { duel.mode = duel.mode && duel.mode.kind === kind ? null : { kind, picks: [] }; duel.render(); };
  if ($("bRoll")) $("bRoll").onclick = () => duel.submit(E.enc(E.OP.ROLL), "roll the dice");
  if ($("bWin")) $("bWin").onclick = () => duel.submit(E.enc(E.OP.WIN), "call the win");
  if ($("bRoad")) $("bRoad").onclick = () => arm("road");
  if ($("bStead")) $("bStead").onclick = () => arm("stead");
  if ($("bKeep")) $("bKeep").onclick = () => arm("keep");
  if ($("bBuy")) $("bBuy").onclick = () => duel.submit(E.enc(E.OP.BUY), "buy a scroll");
  if ($("bEnd")) $("bEnd").onclick = () => duel.submit(E.enc(E.OP.END), "end the turn");
  if ($("bBank")) $("bBank").onclick = () => bankTradePrompt(duel, eng, meSeat);
  if ($("bOffer")) $("bOffer").onclick = () => { duel.tr = { give: [0, 0, 0, 0, 0], get: [0, 0, 0, 0, 0] }; $("tradeBox").classList.remove("hidden"); renderTradeGrid(duel); };
}
function bankTradePrompt(duel, st, meSeat) {
  const p = st.players[meSeat];
  const opts = [];
  for (let g = 0; g < 5; g++) { const rate = E.bankRate(st, meSeat, g);
    if (p.res[g] >= rate) for (let t = 0; t < 5; t++) if (t !== g && st.bank[t] > 0)
      opts.push({ g, t, rate }); }
  if (!opts.length) return;
  const el = $("ctrls");
  el.innerHTML = opts.map((o, i) =>
    `<button class="ghost" data-i="${i}">${E.RES_ICON[o.g]}×${o.rate} → ${E.RES_ICON[o.t]}</button>`).join("")
    + `<button class="ghost" id="bBankBack">↩</button>`;
  el.querySelectorAll("[data-i]").forEach((b) => b.onclick = () => { const o = opts[Number(b.dataset.i)];
    duel.submit(E.enc(E.OP.BANK, o.g * 8 + o.rate, o.t), "bank trade"); });
  $("bBankBack").onclick = () => duel.render();
}
function renderTradeGrid(duel) {
  const gr = $("tradeGrid"), tr = duel.tr;
  const row = (key, label) => `<div class="small dim">${label}</div>` + E.RES.map((_, r) =>
    `<div class="rc"><button data-k="${key}" data-r="${r}" data-d="-1">−</button><span class="n">${E.RES_ICON[r]}${tr[key][r]}</span><button data-k="${key}" data-r="${r}" data-d="1">＋</button></div>`).join("");
  gr.innerHTML = row("give", T("give", "give")) + row("get", T("get", "get"));
  gr.querySelectorAll("button").forEach((b) => b.onclick = () => {
    const k = b.dataset.k, r = Number(b.dataset.r), d = Number(b.dataset.d);
    duel.tr[k][r] = Math.max(0, Math.min(7, duel.tr[k][r] + d));
    renderTradeGrid(duel);
  });
  $("btnOfferSend").onclick = () => {
    const { give, get } = duel.tr;
    if (!give.some(Boolean) || !get.some(Boolean)) return alertBar(T("offerEmpty", "Set both sides of the trade."));
    $("tradeBox").classList.add("hidden");
    duel.submit(E.enc(E.OP.OFFER, E.pack3(give), E.pack3(get)), "post a trade offer");
  };
  $("btnOfferClose").onclick = () => { $("tradeBox").classList.add("hidden"); duel.render(); };
}
function renderOffers(duel, gm, eng, me) {
  const el = $("offers"), meSeat = me != null ? me + 1 : 0;
  if (!eng || !eng.offers.length) { el.innerHTML = ""; return; }
  const moves = duel.canAct() ? E.legalMoves(eng, meSeat) : [];
  el.innerHTML = eng.offers.map((o) => {
    const txt = o.give.map((n, r) => n ? n + E.RES_ICON[r] : "").filter(Boolean).join("+")
      + " ⇄ " + o.get.map((n, r) => n ? n + E.RES_ICON[r] : "").filter(Boolean).join("+");
    const acceptable = moves.includes(E.enc(E.OP.ACCEPT, o.at));
    const mine = o.by === meSeat;
    return `<div class="offer"><span>${SEAT_MARK[o.by - 1]} ${txt}</span><span>
      ${acceptable ? `<button class="primary" data-acc="${o.at}">${T("accept", "Accept")}</button>` : ""}
      ${mine ? `<button class="ghost" data-rsc="${o.at}">${T("rescind", "Rescind")}</button>` : ""}</span></div>`;
  }).join("");
  el.querySelectorAll("[data-acc]").forEach((b) => b.onclick = () => duel.submit(E.enc(E.OP.ACCEPT, Number(b.dataset.acc)), "accept the trade"));
  el.querySelectorAll("[data-rsc]").forEach((b) => b.onclick = () => duel.submit(E.enc(E.OP.RESCIND, Number(b.dataset.rsc)), "rescind the offer"));
}
function renderScrolls(duel, gm, eng, me) {
  const el = $("scrolls"), meSeat = me != null ? me + 1 : 0;
  if (!eng || !meSeat || !eng.players[meSeat]) { el.innerHTML = ""; return; }
  const p = eng.players[meSeat];
  const played = {}; eng.playsLog.filter((x) => x.s === meSeat).forEach((x) => played[x.t] = (played[x.t] || 0) + 1);
  const held = {}; p.devKnown.forEach((t) => held[t] = (held[t] || 0) + 1);
  Object.keys(played).forEach((t) => held[t] = (held[t] || 0) - played[t]);
  const items = [];
  for (const t of [E.WARDEN, E.CHARTER, E.PATHWRIGHT, E.BOUNTY, E.LEVY]) {
    const n = held[t] || 0; if (n <= 0) continue;
    const playable = duel.canAct() && meSeat === eng.turnSeat && !eng.playedScroll && t !== E.CHARTER
      && (eng.phase === "main" || (eng.phase === "preroll" && t === E.WARDEN))
      && p.devKnown.slice(0, p.buysBeforeTurn).filter((x) => x === t).length > (played[t] || 0);
    let act = "";
    if (playable && t === E.WARDEN) act = `<button data-play="w">${T("play", "Play")}</button>`;
    if (playable && t === E.PATHWRIGHT) act = `<button data-play="p">${T("play", "Play")}</button>`;
    if (playable && t === E.BOUNTY) act = `<button data-play="b">${T("play", "Play")}</button>`;
    if (playable && t === E.LEVY) act = `<button data-play="l">${T("play", "Play")}</button>`;
    items.push(`<span class="sc"><b>${DEVN(t)}</b><span class="small dim">×${n}${t === E.CHARTER ? " · +1 " + T("vp", "pts") : ""}</span>${act}</span>`);
  }
  el.innerHTML = items.join("");
  el.querySelectorAll("[data-play]").forEach((b) => b.onclick = () => {
    const k = b.dataset.play;
    if (k === "w") { duel.mode = { kind: "warden", picks: [] }; duel.render(); }
    if (k === "p") { duel.mode = { kind: "path", picks: [] }; duel.render(); }
    if (k === "b") pickTwoRes(duel);
    if (k === "l") pickOneRes(duel);
  });
}
function pickTwoRes(duel) {
  const el = $("ctrls"); const picks = [];
  const draw = () => { el.innerHTML = `<span class="small dim">${T("bountyPick", "Bounty — pick {n} from the bank", { n: 2 - picks.length })}</span>`
    + E.RES.map((_, r) => `<button class="ghost" data-r="${r}">${E.RES_ICON[r]}</button>`).join("");
    el.querySelectorAll("[data-r]").forEach((b) => b.onclick = () => { picks.push(Number(b.dataset.r));
      if (picks.length === 2) duel.submit(E.enc(E.OP.BOUNTY, picks[0], picks[1]), "play a Bounty"); else draw(); }); };
  draw();
}
function pickOneRes(duel) {
  const el = $("ctrls");
  el.innerHTML = `<span class="small dim">${T("levyPick", "Levy — name the resource every rival must hand over")}</span>`
    + E.RES.map((_, r) => `<button class="ghost" data-r="${r}">${E.RES_ICON[r]}</button>`).join("");
  el.querySelectorAll("[data-r]").forEach((b) => b.onclick = () => duel.submit(E.enc(E.OP.LEVY, Number(b.dataset.r)), "play a Levy"));
}
function renderDiscard(duel, gm, eng, me) {
  const el = $("discardBar"), meSeat = me != null ? me + 1 : 0;
  if (!eng || eng.phase !== "discard" || !meSeat || !eng.players[meSeat] || !eng.players[meSeat].owe) { el.innerHTML = ""; duel.disc = null; return; }
  const p = eng.players[meSeat], owe = p.owe;
  if (!duel.disc) duel.disc = [0, 0, 0, 0, 0];
  const n = duel.disc.reduce((a, b) => a + b, 0);
  el.innerHTML = `<div class="small"><b>${T("discardOwed", "A 7 was rolled — discard {n} cards", { n: owe })}</b> (${n}/${owe})</div>`
    + `<div class="tradegrid">` + `<div></div>` + E.RES.map((_, r) =>
      `<div class="rc"><button data-r="${r}" data-d="-1">−</button><span class="n">${E.RES_ICON[r]}${duel.disc[r]}</span><button data-r="${r}" data-d="1">＋</button></div>`).join("") + `</div>`
    + `<div class="row mt"><button class="primary" id="bDisc" ${n === owe ? "" : "disabled"}>${T("discardGo", "Discard")}</button></div>`;
  el.querySelectorAll("[data-r]").forEach((b) => b.onclick = () => {
    const r = Number(b.dataset.r), d = Number(b.dataset.d);
    duel.disc[r] = Math.max(0, Math.min(eng.players[meSeat].res[r], duel.disc[r] + d));
    duel.render();
  });
  if ($("bDisc")) $("bDisc").onclick = () => { const pack = E.pack5(duel.disc); duel.disc = null;
    duel.submit(E.enc(E.OP.DISCARD, 0, pack), "discard"); };
}
function renderLog(eng, gm) {
  const el = $("logPane");
  if (!eng) { el.innerHTML = ""; return; }
  el.innerHTML = eng.log.slice(-40).map((l) => `<div>${SEAT_MARK[l.s - 1] || ""} ${l.msg}</div>`).join("");
  el.scrollTop = el.scrollHeight;
}
function renderSettle(duel, gm, eng, me) {
  const live = gm.exists && gm.nn === gm.cap && !gm.settled;
  const over = eng && eng.over, winner = over ? eng.winner : 0;
  const iAmIn = me != null, meSeat = me != null ? me + 1 : 0;
  $("btnDraw").classList.add("hidden");
  $("btnResign").classList.toggle("hidden", !(live && iAmIn && !gm.resigned[me] && !over));
  $("btnRematch").classList.toggle("hidden", !(gm.exists && gm.settled && iAmIn));
  $("btnLeave").classList.toggle("hidden", !(gm.exists && !gm.settled && gm.nn < gm.cap && iAmIn && me === gm.nn - 1 && me > 0));
  $("btnCancel").classList.toggle("hidden", !(gm.exists && !gm.settled && gm.nn < gm.cap && me === 0));
  const pastDeadline = live && duel.dapp.cursor != null && duel.dapp.cursor > gm.dl;
  $("btnAbort").classList.toggle("hidden", !(live && iAmIn && pastDeadline));
  $("btnJoinGame").classList.toggle("hidden", !(gm.exists && gm.nn < gm.cap && !iAmIn && !gm.settled));
  if (gm.exists && gm.nn < gm.cap && !iAmIn)
    $("btnJoinGame").textContent = duel.dapp.me
      ? T("joinStake", "⬡ Take a seat — stake {amt} NADO", { amt: rawToNado(gm.stake) })
      : T("signJoinStake", "⬡ Sign in to take a seat — stake {amt} NADO", { amt: rawToNado(gm.stake) });
  // reveal + confirm flow
  const rb = $("revealBar");
  let hint = "";
  if (live && over && winner) {
    const needReveal = iAmIn && gm.commits[me] && !gm.reveals[me];
    rb.innerHTML = needReveal
      ? `<button class="primary pulse" id="bReveal">🔓 ${T("revealBtn", "Reveal your scrolls — lets everyone verify the game")}</button>` : "";
    if ($("bReveal")) $("bReveal").onclick = () => duel.reveal();
    const committed = gm.commits.slice(0, gm.cap).map((c, i) => c && !gm.resigned[i]);
    const revealedAll = committed.every((c, i) => !c || gm.reveals[i]);
    const verified = revealedAll && (() => { const vs = duel.rebuild(gm); return !vs.corrupt; })();
    const alive = gm.resigned.slice(0, gm.cap).filter((r) => !r).length;
    const votes = gm.agrees.slice(0, gm.cap).filter((a, i) => !gm.resigned[i] && a === winner).length;
    const myVote = iAmIn && !gm.resigned[me] && gm.agrees[me] === winner;
    $("btnSettle").classList.toggle("hidden", !(iAmIn && !gm.resigned[me] && !myVote));
    $("btnSettle").textContent = "✔ " + T("confirmResult", "Confirm the result — {who} takes the pot", { who: disp(gm.seats[winner - 1] || "?") });
    if (revealedAll && !verified) {
      $("btnSettle").classList.add("hidden");
      hint = T("verifyFail", "⚠ VERIFICATION FAILED — a revealed secret contradicts a play. Do not confirm; the timeout refund protects the honest.");
    } else hint = T("confirmHint", "{v}/{n} confirmations — the pot pays out when every unresigned player confirms.", { v: votes, n: alive })
      + (revealedAll ? " " + T("verifiedOk", "✓ all scroll claims verified.") : "");
  } else { rb.innerHTML = ""; $("btnSettle").classList.add("hidden"); }
  if (!hint && live && !over && pastDeadline) hint = T("deadlinePassed", "The move clock ran out — any player can dissolve the table for an equal refund.");
  else if (!hint && live && !over && duel.dapp.cursor != null && iAmIn && eng && !duel.canAct() && !duel.pendingMove)
    hint = T("moveClock", "move clock: refundable in {t} if the table stalls", { t: blocksToTime(gm.dl - duel.dapp.cursor) });
  $("settleHint").textContent = hint;
}

// =====================================================================================================
const duel = new TableDuel(dapp, {
  prefix: "hex", icon: "⬡", marks: ["🟥", "🟦"],
  appendMaps: ["cap", "p3", "p4", "c1", "c2", "c3", "c4", "a1", "a2", "a3", "a4", "rc",
               "rs1", "rs2", "rs3", "rs4", "r1h", "r1l", "r2h", "r2l", "r3h", "r3l", "r4h", "r4l"],
  openExtra: (gm, id) => [gm ? gm.cap : parseInt($("capSel").value, 10) || 2, commitFor(id)],
  shareText: (gm, id) => T("shareText", "Join my Hexholm table #{id} on NADO — settle the island, winner takes the pot!", { id }),
  inviteTitle: T("inviteTitle", "You are invited to a Hexholm table"),
  inviteBody: (gm) => T("inviteBody", "Stake {amt} NADO, take a seat, race to 10 points.", { amt: rawToNado(gm.stake) }),
  botMove: true,                                            // flag: enables the practice machinery + button
  rebuild(gm) { return this.rebuild(gm); },                 // delegates to the CLASS method (not recursive)
  renderGame() {}, canAct() { return false; }, turnOf() { return null; }, resultOf() { return 0; },
  wire() {
    $("btnSettle").onclick = () => { const eng = this.eng; if (eng && eng.over && eng.winner) this.agreeSeat(eng.winner); };
    $("btnLeave").onclick = () => this.leave();
    if ($("btnDaily")) $("btnDaily").onclick = () => this.startDaily();
  },
});
duel.MAPS = ["nn", "st", "pt", "sd", "wr", "mc", "dl", "kh", "p1", "p2", "mv", "mh",
             "eday", "eaddr", "escore", "en", "ew"].concat(duel.cfg.appendMaps);
duel.mode = null; duel.tr = null; duel.disc = null; duel._anch = { day: 0, hash: null }; duel._boardBusy = false;
duel.boot(["activeGame", "lobby", "play", "walletcard", "bankroll", "dailyBoard", "scoreboard"]);

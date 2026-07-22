// board-daily-ui.js — the FREE DAILY CHALLENGE mode for a 2-player board game, as ONE module.
//
// The three board games (tic-tac-toe, connect four, reversi) differ only in their pure rules and in how a
// cell looks. Everything else about a daily — seeding the day's anchor, resuming an in-progress run,
// replaying it, scoring it, posting the claim, and rendering the replay-VERIFIED leaderboard — is
// identical, so it lives here rather than three times. A game supplies its rules module (which exports
// view() so one renderer paints every board) and a few element ids.
//
// The run is solo vs a DETERMINISTIC bot seeded by the day's on-chain anchor AND your own address, so the
// board is personal and non-transferable: a claim copied from someone else replays against a different
// bot and fails to reproduce its score. Only your moves go on-chain; the rules never do.
import { $, _m, dailyFrame, modeBar, renderTopScores, confirmingLabel, notify, base } from "./nadodapp.js?v=4984604e";
import { todayIdx, anchorOf, seedDaily, pendingDaily, provableSeed, packMoves,
         entriesFrom, verifyEntries } from "./provable.js?v=a13bb487";
import { play, score, verifyClaim } from "./board-daily.js?v=ff35df1e";

const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("sdk." + k, d, v) : d;

export class BoardDaily {
  /**
   * @param dapp   the NadoDapp session
   * @param rules  the game's pure rules module (must export SLUG, MOVE_BITS, MAX_MOVES, view, …)
   * @param cfg    { name, mount, listEl, MAPS, marks?, cellClass? }
   *   mount   — element id the play area is rendered into
   *   listEl  — element id for the verified leaderboard
   *   marks   — [emptyGlyph, yourGlyph, botGlyph] painted into each cell
   */
  constructor(dapp, rules, cfg) {
    this.dapp = dapp; this.rules = rules; this.cfg = cfg || {};
    this.words = Math.ceil(rules.MAX_MOVES / Math.floor(50 / rules.MOVE_BITS));
    this.LS = "nado_" + rules.SLUG + "_daily";
    this.day = todayIdx();
    this.anchor = null; this.seed = null;
    this.moves = this._load();
    this.seeding = false;
    this._posted = null;      // today's best already on-chain for me (null = none)
    this._boardBusy = false;
  }

  // ---- today's run, persisted so a reload (or a wallet round-trip) never loses progress ----
  _load() {
    try { const j = JSON.parse(localStorage.getItem(this.LS) || "{}");
          return j.day === this.day && Array.isArray(j.moves) ? j.moves : []; } catch (e) { return []; }
  }
  _save() { try { localStorage.setItem(this.LS, JSON.stringify({ day: this.day, moves: this.moves })); } catch (e) {} }
  reset() { this.moves = []; this._save(); }

  /** replay the run so far — the single source of truth for the board, the score and doneness */
  run() {
    if (!this.seed) return null;
    return play(this.rules, this.seed, this.moves);
  }
  scoreNow() { const r = this.run(); return r ? score(this.rules, r) : -1; }

  // ---- seeding today's board (shared driver: survives the wallet redirect) ----
  async ensure(sto) {
    if (this.anchor) return this.anchor;
    const a = sto ? anchorOf(sto, _m, this.day) : null;
    if (a) { this.anchor = a; this.seed = provableSeed(this.rules.SLUG, this.day, a, this.dapp.me || "anon"); }
    return this.anchor;
  }
  /** drive the anchor to resolution (button path). Resumes by itself after a wallet round-trip. */
  async seedNow(getStorage, onRender) {
    if (this.seeding) return null;
    this.seeding = true; onRender && onRender();
    let a = null;
    try {
      a = await seedDaily(this.dapp, { slug: this.rules.SLUG, day: this.day, base: base(), _m,
                                       getStorage, onProgress: () => onRender && onRender() });
    } finally { this.seeding = false; }
    if (a) { this.anchor = a; this.seed = provableSeed(this.rules.SLUG, this.day, a, this.dapp.me || "anon"); }
    onRender && onRender();
    return a;
  }
  resumePending() { return pendingDaily(this.rules.SLUG, this.day); }

  // ---- play ----
  tap(mv) {
    const r0 = this.run();
    if (!r0 || r0.complete) return false;
    const next = this.moves.concat([mv]);
    const r = play(this.rules, this.seed, next);
    if (r.illegal) return false;                 // not a legal move here — ignore the tap
    this.moves = next; this._save();
    return true;
  }

  /** post today's finished run. The contract stores the CLAIM; the score is proven by replay, not trusted. */
  post() {
    const r = this.run();
    if (!r || !r.complete) return;
    const sc = score(this.rules, r);
    if (sc < 0) return;
    if (this.dapp.busy("post")) return notify(confirmingLabel());
    const words = packMoves(this.moves, this.rules.MOVE_BITS);
    while (words.length < this.words) words.push(0);
    this.dapp.call("post", [this.day, sc, this.moves.length, ...words.slice(0, this.words)], null,
                   T("postCall", "post my {name} score ({s})", { name: this.cfg.name || "daily", s: sc }),
                   { phase: "post" });
  }

  // ---- render: the SDK frame + ONE grid painter for every board game ----
  render(onRender) {
    const el = $(this.cfg.mount); if (!el) return;
    const rules = this.rules, r = this.run();
    const marks = this.cfg.marks || ["", "●", "○"];
    let body = "";
    if (r) {
      const legal = r.complete ? [] : rules.legal(r.state, 1);
      const v = rules.view(r.state, legal);
      const sc = score(rules, r);
      const line = r.complete
        ? (r.winner === 1 ? T("dailyWon", "🏆 You beat today's bot!")
           : r.winner === 0 ? T("dailyDrew", "🤝 Drawn with today's bot.")
           : T("dailyLost", "💀 Today's bot took it."))
        : T("dailyYourMove", "▶ Your move — you are {m}", { m: marks[1] });
      body = '<div class="small dim" style="margin-bottom:8px">' + line
        + (sc >= 0 ? " · " + T("dailyPts", "{s} pts", { s: sc }) : "") + "</div>"
        + '<div class="dgrid" style="display:grid;grid-template-columns:repeat(' + v.cols + ',1fr);gap:4px;max-width:min(92vw,'
        + (v.cols * 56) + 'px);margin:0 auto">'
        + v.cells.map((c) => '<div class="' + (this.cfg.cellClass || "cell") + (c.v === 1 ? " x" : c.v === 2 ? " o" : "")
            + (c.mv === null ? " dead" : "") + '"' + (c.mv !== null ? ' data-dmv="' + c.mv + '"' : "")
            + ' style="aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;font-size:clamp(14px,5vw,26px)">'
            + marks[c.v] + "</div>").join("")
        + "</div>";
    }
    dailyFrame(this.dapp, {
      el,
      name: this.cfg.name,
      ready: !!(this.anchor && this.seed),
      seeding: this.seeding ? T("dailySeedingNow", "Seeding today's board on-chain — it starts by itself in a moment.") : undefined,
      done: !!(r && r.complete),
      score: r ? score(this.rules, r) : 0,
      posted: this._posted,
      scoreLabel: r && r.complete ? T("dailyFinal", "Final: {s} points in {n} moves", { s: score(this.rules, r), n: this.moves.length }) : undefined,
      postLabel: r && r.complete ? T("dailyPostPts", "🏆 Post my {s} points to the board", { s: score(this.rules, r) }) : undefined,
      body,
      wire: (root) => root.querySelectorAll("[data-dmv]").forEach((x) => x.onclick = () => {
        if (this.tap(parseInt(x.dataset.dmv, 10))) onRender && onRender();
      }),
      onPost: () => this.post(),
      onReplay: () => { this.reset(); onRender && onRender(); },
    });
  }

  /** the verified leaderboard: every posted claim is REPLAYED here before it may rank */
  async renderBoard(sto) {
    const el = $(this.cfg.listEl); if (!el || this._boardBusy) return;
    this._boardBusy = true;
    try {
      const anchor = sto ? anchorOf(sto, _m, this.day) : null;
      if (!anchor) {
        el.innerHTML = '<span class="dim">' + T("dailyBoardUnseeded",
          "Today's board isn't seeded yet — start the daily challenge above to seed it and play the first run.") + "</span>";
        return;
      }
      const entries = entriesFrom(sto, _m, this.day, [...Array(this.words)].map((_x, k) => "ew" + k));
      const rows = await verifyEntries(entries, (en) => verifyClaim(this.rules, this.day, en.n, en.words, anchor, en.addr));
      const mine = rows.filter((x) => x.addr === this.dapp.me);
      this._posted = mine.length ? mine[0].score : null;
      renderTopScores(el, rows, this.dapp.me,
        T("dailyNoScores", "No verified scores today — finish today's run and post yours."),
        T("dailyScoreCol", "Score"), true);
    } finally { this._boardBusy = false; }
  }
}

/**
 * gameModes(el, active, onChange, opts) — the standard three-mode picker for a staked board game, so the
 * same choice reads identically in every game. Modes a game doesn't have are simply omitted.
 */
export function gameModes(el, active, onChange, opts = {}) {
  const modes = [];
  if (opts.play !== false) modes.push({ key: "play", icon: "⚔", label: T("modePlay", "Play for stakes"),
    hint: T("modePlayHint", "Head-to-head against another player for real NADO.") });
  if (opts.practice !== false) modes.push({ key: "practice", icon: "🤖", label: T("modePractice", "Practice"),
    badge: T("free", "free"), hint: T("modePracticeHint", "Play the computer in your browser — nothing on-chain.") });
  if (opts.daily !== false) modes.push({ key: "daily", icon: "🏆", label: T("modeDaily", "Daily Challenge"),
    badge: T("free", "free"), hint: T("modeDailyHint", "Today's free provable board — the faucet pays the daily leaders.") });
  modeBar(el, modes, active, onChange);
}

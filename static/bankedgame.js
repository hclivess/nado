// bankedgame.js — the shared PEER-BANKED TABLE client scaffold (extracted from the dice/slots pair for
// mines/blackjack and every future house game). One player "banks" a table (open/fund/close, maps
// ta/tk/tp/tc/tn/tx/tz — the same schema every banked contract uses via tests/vmasm.bank_table_methods);
// everyone else takes seats against its bankroll. This module owns the NON-game-specific client half:
// the table reader, open/fund/close actions with localStorage tracking, the public lobby, the
// "your tables/seats" chips, and the unresolved-seat block-hash prefetch. The game keeps its own seat
// schema, actions and render.
//
//   const bg = new BankedGame(dapp, { icon: "💣" });
//   bg.open(bankRaw, label);  bg.fund(raw, label);  bg.close(label);
//   bg.track(sto);  const tb = bg.read(sto, bg.active);
//   bg.lobby($("lobbyList"), sto, (tb) => "…chip text…", select, sortFn);
//   bg.recent($("recent"), select, tagFn);
import { _m, $, lsLoad, lsSave, lsPrune, randId, recentChips, notify, confirmingLabel, scoreBump, scoreSort } from "./nadodapp.js";

export class BankedGame {
  constructor(dapp, { icon = "🎯", bankIcon = "🏦" } = {}) {
    this.dapp = dapp; this.icon = icon; this.bankIcon = bankIcon;
    const slug = dapp.app.replace(/\W+/g, "").toLowerCase();
    this.LS_T = "nado_" + slug + "_tables";
    this.LS_S = "nado_" + slug + "_seats";
    this.active = null;          // selected table id
    this.lobbyN = 24;            // lobby cap; "Show more" grows it
    this.knownTables = new Set(); this.knownSeats = new Set();
  }

  // ---- the ONE shared banked-table reader (every banked game uses this — dice/roulette included) ----
  // A table EXISTS iff it has a banker (ta). tk=bankroll tp=pot tc=committed tz=closed. Seat counts come from
  // the contract's tn/tx counters WHEN it keeps them (mines); contracts that omit them (blackjack, dice,
  // roulette) get tn/tx DERIVED from the seat maps (gg=table, gd=settled) in one pass — which also yields the
  // soonest next settle (min gh+1 over unsettled seats) for a "next roll in …" hint. The object carries both the
  // raw slot names (tk/tp/tc/tn/tx) and friendly aliases (bankroll/pool/committed/seatCount/settledCount) so a
  // single reader serves every game's render without per-game duplication.
  ids(sto) { return Object.keys(_m(sto, "ta")); }
  read(sto, t) {
    t = String(t); const bank = _m(sto, "ta")[t];
    if (!bank) return { exists: false };
    const tk = _m(sto, "tk")[t] || 0, tp = _m(sto, "tp")[t] || 0, tc = _m(sto, "tc")[t] || 0, closed = !!_m(sto, "tz")[t];
    let tn = _m(sto, "tn")[t] || 0, tx = _m(sto, "tx")[t] || 0, soonest = null;
    if (!tn) {                                   // contract keeps no seat counter -> derive from the seat maps
      const gg = _m(sto, "gg"), gd = _m(sto, "gd"), gh = _m(sto, "gh");
      for (const g in gg) {
        if (String(gg[g]) !== t) continue;
        tn++;
        if (gd[g]) { tx++; continue; }
        const s = (gh[g] || 0) + 1;             // this seat settles one block after its gh
        if (soonest == null || s < soonest) soonest = s;
      }
    }
    const tb = { exists: true, id: Number(t), bank, tk, tp, tc, tn, tx, closed,
      bankroll: tk, pool: tp, committed: tc, seatCount: tn, settledCount: tx,
      phase: closed ? "done" : "betting", free: BigInt(tk) - BigInt(tc) };
    const cur = this.dapp.cursor;
    if (cur != null && soonest != null) { tb.nextSettle = soonest; tb.roundEndsIn = Math.max(0, soonest - cur); }
    return tb;
  }

  // ---- localStorage table/seat records (survive the signing redirect; pruned once gone on-chain) ----
  track(sto) {
    this._sto = sto;   // freshest storage — fund() reads the current bankroll from here to record its tk0
    this.knownTables = lsPrune(this.LS_T, Object.keys(_m(sto, "ta")));
    this.knownSeats = lsPrune(this.LS_S, Object.keys(_m(sto, "gg")));
  }
  rememberSeat(g, extra) { const S = lsLoad(this.LS_S); S[g] = Object.assign({ table: this.active, ts: Date.now() }, extra); lsSave(this.LS_S, S); }
  seatRec(g) { return lsLoad(this.LS_S)[String(g)] || null; }
  patchSeat(g, patch) { const S = lsLoad(this.LS_S); if (S[g]) { Object.assign(S[g], patch); lsSave(this.LS_S, S); } }
  tableRec(t) { return lsLoad(this.LS_T)[String(t)] || null; }

  // ---- bank actions (identical bytecode in every banked game) ----
  // CLICK-GATED: dapp.busy(phase, "table", id) is true from the tap until the effect is seen on-chain
  // (each game's settleInflight predicate — most now use bg.landed() below). A re-tap in the sign→mine
  // window is swallowed with a toast rather than firing a duplicate open/fund/close.
  open(bankRaw, label) {
    if (this.dapp.busy("open")) { notify(confirmingLabel()); return this.active; }   // one open confirming at a time (each mints a fresh id)
    const t = randId();
    const T = lsLoad(this.LS_T); T[t] = { bankroll: bankRaw.toString(), ts: Date.now() }; lsSave(this.LS_T, T);
    this.active = t;
    this.dapp.call("open", [t], bankRaw, label, { table: t, phase: "open" });
    return t;
  }
  fund(raw, label) { if (this.dapp.busy("fund", "table", this.active)) return notify(confirmingLabel()); const tk0 = this._sto ? (_m(this._sto, "tk")[String(this.active)] || 0) : null; this.dapp.call("fund", [this.active], raw, label, { table: this.active, phase: "fund", tk0 }); }
  close(label, opts) { if (this.dapp.busy("close", "table", this.active)) return notify(confirmingLabel()); this.dapp.call("close", [this.active], null, label, { table: this.active, phase: "close" }, opts); }
  // reopen(t, bankRaw, label): re-bank a CLOSED table id you already own (same id keeps the history/link).
  reopen(t, bankRaw, label) {
    if (this.dapp.busy("open")) { notify(confirmingLabel()); return t; }
    const T = lsLoad(this.LS_T); T[t] = { bankroll: bankRaw.toString(), ts: Date.now() }; lsSave(this.LS_T, T);
    this.active = t;
    this.dapp.call("open", [t], bankRaw, label, { table: t, phase: "open" });
    return t;
  }
  // landed(f, sto): the shared "did this action's effect appear on-chain?" test for the bank-level phases,
  // so a game's settleInflight predicate can defer to it (release the click guard the instant it lands,
  // not on the 2-min TTL). Games compose it: dapp.settleInflight((f) => bg.landed(f, sto) || myOwn(f)).
  //   open  → the table's banker record (ta) exists   fund → bankroll (tk) rose past the pre-submit value
  //   close → the table is flagged closed (tz)        seat-creating bet/spin/deal → the seat (gg) exists
  // A seat-creating phase must pass its new seat id as pend.seat (every banked game already does).
  landed(f, sto) {
    if (!f || !sto) return false;
    const t = String(f.table);
    if (f.phase === "open") return !!_m(sto, "ta")[t];
    if (f.phase === "close") return !!_m(sto, "tz")[t];
    if (f.phase === "fund") return f.tk0 != null && BigInt(_m(sto, "tk")[t] || 0) > BigInt(f.tk0);
    if (f.seat != null) return !!_m(sto, "gg")[String(f.seat)];   // bet/spin/deal created the seat
    return false;
  }

  // seats(sto, t, readSeat): the shared per-seat iteration every banked game re-implemented — walk this
  // table's seats (gg), hand each to readSeat(g, base) where base carries the common fields + phase
  // (settled / ready-to-resolve / pending), and return them newest-first by bound block height. readSeat
  // returns the game's enriched seat object (or null/undefined to drop it).
  seats(sto, t, readSeat) {
    const gg = _m(sto, "gg"), cur = this.dapp.cursor, out = [];
    for (const g of Object.keys(gg)) {
      if (String(gg[g]) !== String(t)) continue;
      const gh = _m(sto, "gh")[g] || 0, settled = !!_m(sto, "gd")[g];
      const base = { g: Number(g), table: Number(t), gh, settled,
        addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0,
        ready: !settled && !!gh && cur != null && cur >= gh + 1,
        phase: settled ? "settled" : (!!gh && cur != null && cur >= gh + 1) ? "ready" : "pending" };
      const s = readSeat ? readSeat(g, base, sto) : base;
      if (s) out.push(s);
    }
    out.sort((a, b) => ((b.gh || 0) - (a.gh || 0)) || (b.g - a.g));   // newest FIRST by bound block height
    return out;
  }

  // ---- discovery: the public lobby + "your tables/seats" chips ----
  lobby(el, sto, chipText, onSelect, sort) {
    if (!el) return;
    const ts = Object.keys(_m(sto, "ta")).map((t) => this.read(sto, t)).filter((m) => m.exists && !m.closed);
    ts.sort(sort || ((a, b) => Number(b.free - a.free)));
    el.innerHTML = ts.length ? ts.slice(0, this.lobbyN).map((m) =>
      '<button class="chip betting" data-t="' + m.id + '">' + chipText(m) + "</button>").join(" ")
      : '<span class="dim">' + (window.t ? window.t("sdk.noTablesYet", "No tables yet — bank the first one below.") : "No tables yet — bank the first one below.") + "</span>";
    const bm = $("btnMoreLobby");
    if (bm) {
      bm.classList.toggle("hidden", ts.length <= this.lobbyN);
      if (ts.length > this.lobbyN) bm.onclick = () => { this.lobbyN += 48; this.lobby(el, sto, chipText, onSelect, sort); };
    }
    if (!el._deleg) { el._deleg = true; el.addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) onSelect(parseInt(b.dataset.t, 10)); }); }
  }
  // recent(el, onSelect, tagFn): newest-first chips over MY banked tables + seated tables; tagFn(rec) may
  // decorate a live entry ("💰 win to collect" / "your move" …).
  recent(el, onSelect, tagFn) {
    const T = lsLoad(this.LS_T), S = lsLoad(this.LS_S), mine = [];
    for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts || 0 });
    for (const g of Object.keys(S)) mine.push({ id: S[g].table, seat: g, role: "seat", ts: S[g].ts || 0 });
    mine.sort((a, b) => b.ts - a.ts);
    const seen = new Set();
    const shown = mine.filter((x) => {
      x.live = x.role === "bank" ? this.knownTables.has(String(x.id)) : this.knownSeats.has(String(x.seat));
      x.icon = x.role === "bank" ? this.bankIcon : this.icon;
      const k = String(x.id); if (seen.has(k)) return false; seen.add(k); return true;
    }).slice(0, 8);
    if (tagFn) for (const x of shown) { if (x.live) x.tag = tagFn(x) || x.tag; }
    recentChips(el, shown, onSelect, "");
    return shown;
  }

  // ---- unresolved-seat hash prefetch: gather (gh, gh+1) for this table's live seats whose result
  // blocks exist, so the game can show outcomes ~one block after they land (fast provisional is safe
  // for PUBLIC on-chain-validated randomness). heightsOf(g) -> pending height (or 0/null to skip).
  async prefetchHashes(sto, heightsOf) {
    const cur = this.dapp.cursor, need = [];
    for (const g of Object.keys(_m(sto, "gg"))) {
      if (String(_m(sto, "gg")[g]) !== String(this.active) || _m(sto, "gd")[g]) continue;
      const gh = heightsOf ? heightsOf(g) : (_m(sto, "gh")[g] || 0);
      if (gh && cur != null && cur >= gh + 1) need.push(gh, gh + 1);
    }
    if (need.length) await this.dapp.blockHashes(need.slice(0, 30), { fast: true });
  }
  /**
   * The per-player profit scoreboard every banked game shows. All four of them (dice, roulette, mines,
   * blackjack) walked the settled-games map with byte-identical code and differed in exactly ONE line:
   * how that game's payout rule turns a stake into a net. So the walk lives here and the rule is the
   * argument.
   *
   * `netOf(gameId, stake)` returns the PLAYER's net for one settled game (negative when they lost).
   *
   * The subtlety worth keeping in one place: a table's bank is credited the mirror of every player's net,
   * EXCEPT when the player is the bank. Self-play would otherwise cancel your own win against yourself to
   * a bogus zero, and the board would quietly under-report everyone who tests their own table.
   */
  scoreboard(sto, netOf) {
    const stats = {};
    for (const g of Object.keys(_m(sto, "gd"))) {
      if (!_m(sto, "gd")[g]) continue;
      const bank = _m(sto, "ta")[String(_m(sto, "gg")[g])];
      if (!bank) continue;
      const who = _m(sto, "ga")[g];
      const net = netOf(g, Number(_m(sto, "gs")[g] || 0));
      scoreBump(stats, who, net);
      if (bank !== who) scoreBump(stats, bank, -net);
    }
    return scoreSort(stats);
  }

}

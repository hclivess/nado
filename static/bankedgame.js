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
import { _m, $, lsLoad, lsSave, lsPrune, randId, recentChips } from "./nadodapp.js";

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
    this.knownTables = lsPrune(this.LS_T, Object.keys(_m(sto, "ta")));
    this.knownSeats = lsPrune(this.LS_S, Object.keys(_m(sto, "gg")));
  }
  rememberSeat(g, extra) { const S = lsLoad(this.LS_S); S[g] = Object.assign({ table: this.active, ts: Date.now() }, extra); lsSave(this.LS_S, S); }
  seatRec(g) { return lsLoad(this.LS_S)[String(g)] || null; }
  patchSeat(g, patch) { const S = lsLoad(this.LS_S); if (S[g]) { Object.assign(S[g], patch); lsSave(this.LS_S, S); } }
  tableRec(t) { return lsLoad(this.LS_T)[String(t)] || null; }

  // ---- bank actions (identical bytecode in every banked game) ----
  open(bankRaw, label) {
    const t = randId();
    const T = lsLoad(this.LS_T); T[t] = { bankroll: bankRaw.toString(), ts: Date.now() }; lsSave(this.LS_T, T);
    this.active = t;
    this.dapp.call("open", [t], bankRaw, label, { table: t, phase: "open" });
    return t;
  }
  fund(raw, label) { this.dapp.call("fund", [this.active], raw, label, { table: this.active, phase: "fund" }); }
  close(label, opts) { this.dapp.call("close", [this.active], null, label, { table: this.active, phase: "close" }, opts); }

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
}

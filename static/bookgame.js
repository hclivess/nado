// bookgame.js — the shared FIXED-ODDS BOOK client scaffold (extracted from hamster + bet).
//
// A second market alongside a pooled/parimutuel one: instead of waiting for other punters to match you,
// one player posts a BANKROLL and publishes a PRICE per outcome, and anyone can take that price
// immediately. The bank keeps every losing stake and pays winners at the price it posted; the contract
// holds the money and refuses any bet the bank could not cover, so "the house" is a role any player can
// take rather than the operator.
//
// This module owns the part where being wrong costs someone money — the state model, the SOLVENCY
// ceiling, the five actions and the did-it-land predicates — because that logic was duplicated between
// hamster.js and bet.js and had to be re-derived (and re-reviewed) in each. Each game keeps its own
// rendering: hamster weaves prices into its lane table, bet uses a card, and forcing one layout on both
// would be worse than the duplication it removes. bet.js's four-state panel is offered as `panel()` for
// any future game that wants it.
//
// Every contract behind it exposes the same five methods and the same storage shape:
//   book(id)[value]        post or top up the bankroll (first caller becomes the bank)
//   quote(id, i, odds)     publish a price for outcome i, in PERCENT (250 = 2.50x)
//   back(id, i)[value]     take that price
//   bclaim(id)             punter collects after settlement
//   bsweep(id)             bank takes back roll + stakes - what it owes
//   maps  bk/br/bs/bd  (bank digest, bankroll, stakes taken, swept)  + boards  od/bp  (price, committed)
//
//   const book = new Book(dapp, { idKey: "market", stride: 8, unit: 10000n });
//   const b = book.read(sto, id, nOutcomes);
//   book.maxBack(b, i);  book.post(id, raw);  book.quote(id, i, 250);  book.back(id, i, raw, label);
import { _m, $, rawToNado, gate, canPay, alertBar, notify, confirmingLabel, disp, esc } from "./nadodapp.js?v=77a0d4df";

const _t = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("book." + k, d, v) : d;

export class Book {
  /**
   * idKey  — the pend field this game keys actions by ("race", "market", …), so busy()/settle line up
   *          with the rest of the game's gating.
   * stride — board stride: the contract stores od/bp at `id * stride + outcome`.
   * unit   — storage unit in RAW NADO (contracts hold money in units to stay DIVMODW-sound). 1n if the
   *          contract already stores raw.
   */
  constructor(dapp, { idKey = "id", stride = 8, unit = 1n } = {}) {
    this.dapp = dapp;
    this.idKey = idKey;
    this.stride = stride;
    this.unit = BigInt(unit);
  }

  _pend(id, phase, extra) { return Object.assign({ [this.idKey]: id, phase }, extra || {}); }

  /** The book on one game/market/race, with money as BigInt RAW throughout (see the class note). */
  read(sto, id, outcomes) {
    const U = this.unit;
    const big = (m, k) => BigInt(_m(sto, m)[k] || 0) * U;
    const odds = [], pay = [];
    for (let i = 0; i < outcomes; i++) {
      odds.push(Number(_m(sto, "od")[Number(id) * this.stride + i] || 0));
      pay.push(BigInt(_m(sto, "bp")[Number(id) * this.stride + i] || 0) * U);
    }
    const bank = String(_m(sto, "bk")[id] || "");
    return {
      id, outcomes, odds, pay,
      bank: bank && bank !== "0" ? bank : null,
      bankroll: big("br", id),
      taken: big("bs", id),
      swept: !!_m(sto, "bd")[id],
      mine: !!(bank && this.dapp.me && bank === this.dapp.me),
      priced: odds.some((o) => o > 100),
    };
  }

  /**
   * The largest stake this outcome can still take, from the contract's OWN per-bet solvency rule:
   *     committed[i] + stake * price  <=  bankroll + all_stakes + stake
   * Floored to a whole `unit`, and floored rather than rounded: a ceiling the chain would refuse is worse
   * than a slightly conservative one, because the player only finds out by losing a transaction.
   */
  maxBack(b, i) {
    const od = b.odds[i] || 0;
    if (od <= 100) return 0n;                       // unpriced, or a price that pays less than the stake
    const head = b.bankroll + b.taken - b.pay[i];
    if (head <= 0n) return 0n;
    // head / (od/100 - 1)  ==  head * 100 / (od - 100)
    const max = (head * 100n) / BigInt(od - 100);
    return (max / this.unit) * this.unit;
  }

  /** What the bank walks away with if outcome i wins: everything it holds minus what it owes there. */
  pnl(b, i) { return b.bankroll + b.taken - b.pay[i]; }

  /** Would this bet be refused? Returns a human reason, or null when it is takeable. */
  refuseReason(b, i, stake) {
    if (!b.bank) return _t("noBank", "Nobody is banking this yet.");
    if ((b.odds[i] || 0) <= 100) return _t("unpriced", "The bank hasn't published a price for this.");
    if (stake <= 0n) return _t("noStake", "Enter a stake.");
    if (stake % this.unit !== 0n)
      return _t("unitStake", "Stakes are in whole units of {u} NADO.", { u: rawToNado(this.unit) });
    const max = this.maxBack(b, i);
    if (stake > max)
      return _t("bankFull", "The bank can only cover {amt} at that price right now.", { amt: rawToNado(max) });
    return null;
  }

  // ---- actions -------------------------------------------------------------------------------------
  // Each one gates on busy() FIRST (click-time, so a double tap cannot sign twice) and carries a pend the
  // game's settleInflight can retire — the same lifecycle every other action in these games uses.
  post(id, raw, label) {
    if (this.dapp.busy("book", this.idKey, id)) return notify(confirmingLabel());
    if (!canPay(this.dapp, raw, _t("thisBankroll", "This bankroll"))) return;
    this.dapp.call("book", [Number(id)], raw,
      label || _t("callBook", "put up {amt} NADO as the bank", { amt: rawToNado(raw) }),
      this._pend(id, "book"));
  }

  quote(id, i, pct, label) {
    if (this.dapp.busy("quote", this.idKey, id)) return notify(confirmingLabel());
    if (!(pct > 100)) return alertBar(_t("badPrice",
      "A price must beat 1.00x — that is what the punter is paid per 1 NADO staked."));
    this.dapp.call("quote", [Number(id), i, pct], null,
      label || _t("callQuote", "price outcome {i} at {p}x", { i: i + 1, p: (pct / 100).toFixed(2) }),
      this._pend(id, "quote", { outcome: i, od0: pct }));
  }

  back(b, i, stake, label) {
    const id = b.id;
    if (this.dapp.busy("back", this.idKey, id)) return notify(confirmingLabel());
    const why = this.refuseReason(b, i, stake);
    if (why) return alertBar(why);
    if (!canPay(this.dapp, stake, _t("thisBet", "This bet"))) return;
    this.dapp.call("back", [Number(id), i], stake,
      label || _t("callBack", "back outcome {i} at {p}x for {amt}",
        { i: i + 1, p: (b.odds[i] / 100).toFixed(2), amt: rawToNado(stake) }),
      this._pend(id, "back", { outcome: i }));
  }

  claim(id, label) {
    if (this.dapp.busy("bclaim", this.idKey, id)) return notify(confirmingLabel());
    this.dapp.call("bclaim", [Number(id)], null, label || _t("callClaim", "collect from the bank"),
      this._pend(id, "bclaim"));
  }

  sweep(id, label) {
    if (this.dapp.busy("bsweep", this.idKey, id)) return notify(confirmingLabel());
    this.dapp.call("bsweep", [Number(id)], null, label || _t("callSweep", "sweep the book"),
      this._pend(id, "bsweep"));
  }

  /**
   * settleInflight contribution: TRUE once the book action `f` is visible on-chain. Games OR this into
   * their own predicate. Without a real check the button sticks on the confirming spinner (the SDK only
   * releases the click guard on a game-seen effect or the timeout), so every phase here is covered.
   * `myBook` is the punter's own position when the game reads one (bet does; hamster has no view).
   */
  settled(f, b, myBook) {
    if (!f || String(f[this.idKey]) !== String(b && b.id)) return false;
    if (f.phase === "book") return !!b.bank;
    if (f.phase === "quote") return (b.odds[f.outcome] || 0) >= Number(f.od0 || 1);
    if (f.phase === "back") return myBook ? Number((myBook.stakes || [])[f.outcome] || 0) > 0 : b.taken > 0n;
    if (f.phase === "bclaim") return !!(myBook && myBook.claimed);
    if (f.phase === "bsweep") return !!b.swept;
    return false;
  }

  /** The five phases, for a game that wants to blanket-gate on "any book action in flight". */
  busy(id) {
    return ["book", "quote", "back", "bclaim", "bsweep"].some((p) => this.dapp.busy(p, this.idKey, id));
  }

  /**
   * OPTIONAL default panel — the four honest states of a book: nobody banks this yet · you are the bank ·
   * someone else banks it · settled. A game with its own layout (hamster prices its lane table in place)
   * simply does not call this.
   */
  panel(el, b, opts) {
    const o = opts || {};
    const labels = o.labels || b.odds.map((_x, i) => "#" + (i + 1));
    const signedIn = !!this.dapp.me;
    const settled = !!o.settled;
    const my = o.myBook || null;
    let h = "";
    if (!b.bank) {
      h += '<div class="small dim">' + _t("pitch",
        "Nobody is banking this. Put up a bankroll, publish your own prices, and you keep every losing stake — the contract holds your money and refuses any bet it could not pay, so your worst case is capped before you price anything.") + "</div>";
      if (signedIn && o.open) {
        h += '<div class="row mt"><input id="bookAmt" placeholder="' + esc(_t("bankrollPh", "bankroll (NADO)"))
          + '" inputmode="decimal" autocomplete="off">'
          + '<button class="primary" id="btnBook" style="flex:0 0 auto">'
          + (this.dapp.busy("book", this.idKey, b.id) ? confirmingLabel() : _t("becomeBank", "🏦 Become the bank"))
          + "</button></div>";
      } else if (!signedIn) {
        h += '<div class="small dim mt">' + _t("signInToBank", "Sign in to bank this.") + "</div>";
      } else {
        h += '<div class="small dim mt">' + _t("tooLate", "Betting is closed — a bank can only be posted while it is open.") + "</div>";
      }
    } else {
      h += '<div class="kv"><span class="k">' + _t("bankIs", "Bank") + '</span><span class="mono">'
        + esc(b.mine ? _t("youAreBank", "you") : disp(b.bank)) + "</span></div>"
        + '<div class="kv"><span class="k">' + _t("bankroll", "Bankroll") + '</span><span class="mono">'
        + rawToNado(b.bankroll) + " NADO</span></div>"
        + '<div class="kv"><span class="k">' + _t("taken", "Stakes taken") + '</span><span class="mono">'
        + rawToNado(b.taken) + " NADO</span></div>";
      if (b.mine) {
        h += '<div class="divlabel">' + _t("yourBook", "Your book — set a price per outcome") + "</div>"
          + '<div class="small dim">' + _t("yourBookNote",
            "A price of 2.50x pays a punter 2.50 NADO per 1 staked. Leave an outcome unpriced and nobody can back it. The row shows what you walk away with if that outcome wins.") + "</div>";
        h += labels.map((lab, i) =>
          '<div class="row mt" style="align-items:center">'
          + '<span style="flex:1 1 auto;min-width:0">' + esc(lab)
          + ' <span class="dim small">' + _t("ifWins", "if it wins: {amt}", { amt: rawToNado(this.pnl(b, i)) })
          + "</span></span>"
          + '<input class="bkPrice" data-o="' + i + '" style="max-width:90px" inputmode="decimal" placeholder="2.50" value="'
          + (b.odds[i] > 100 ? (b.odds[i] / 100).toFixed(2) : "") + '">'
          + '<button class="ghost bkSet" data-o="' + i + '" style="flex:0 0 auto">' + _t("setPrice", "Set")
          + "</button></div>").join("");
        if (o.open) h += '<div class="row mt"><input id="bookAmt" placeholder="' + esc(_t("topUpPh", "add to bankroll (NADO)"))
          + '" inputmode="decimal" autocomplete="off"><button class="ghost" id="btnBook" style="flex:0 0 auto">'
          + (this.dapp.busy("book", this.idKey, b.id) ? confirmingLabel() : _t("topUp", "Top up")) + "</button></div>";
        if (settled && !b.swept) h += '<button class="primary mt" id="btnSweep" style="width:100%">'
          + (this.dapp.busy("bsweep", this.idKey, b.id) ? confirmingLabel() : _t("sweep", "🧹 Sweep the book")) + "</button>";
        else if (b.swept) h += '<div class="small dim mt">' + _t("swept", "Book swept ✓") + "</div>";
      } else if (o.open) {
        const priced = labels.map((lab, i) => ({ lab, i, od: b.odds[i], max: this.maxBack(b, i) }))
          .filter((x) => x.od > 100);
        if (!priced.length) h += '<div class="small dim mt">' + _t("noPrices", "The bank hasn't published any prices yet.") + "</div>";
        else {
          h += '<div class="divlabel">' + _t("backHead", "Back an outcome at a fixed price") + "</div>";
          h += priced.map((x) =>
            '<div class="row mt" style="align-items:center">'
            + '<span style="flex:1 1 auto;min-width:0">' + esc(x.lab) + " <b>" + (x.od / 100).toFixed(2) + "×</b>"
            + '<span class="dim small"> · ' + _t("maxStake", "max {amt}", { amt: trimMax(x.max) }) + "</span></span>"
            + '<input class="bkStake" data-o="' + x.i + '" style="max-width:90px" inputmode="decimal" placeholder="1">'
            + '<button class="primary bkBack" data-o="' + x.i + '" style="flex:0 0 auto"'
            + (x.max <= 0n ? " disabled" : "") + ">" + _t("backIt", "Back") + "</button></div>").join("");
          if (this.dapp.busy("back", this.idKey, b.id)) h += '<div class="small dim mt">' + confirmingLabel() + "</div>";
        }
      }
      if (my && my.total > 0) {
        h += '<div class="divlabel">' + _t("yourBets", "Your bets against the bank") + "</div>"
          + my.stakes.map((s, i) => s > 0
            ? '<div class="pos"><span>' + esc(labels[i]) + " · " + rawToNado(s) + " NADO</span><span>"
              + _t("paysIf", "pays {amt}", { amt: rawToNado(my.pays[i]) }) + "</span></div>" : "").join("");
        if (settled) {
          const owed = o.voided ? my.total : (o.winner != null ? my.pays[o.winner] : 0);
          if (my.claimed) h += '<div class="small dim mt">' + _t("collected", "Collected from the bank ✓") + "</div>";
          else if (owed > 0) h += '<button class="primary pulse mt" id="btnBclaim" style="width:100%">'
            + (this.dapp.busy("bclaim", this.idKey, b.id) ? confirmingLabel()
               : _t("collect", "💰 Collect {amt} from the bank", { amt: rawToNado(owed) })) + "</button>";
          else h += '<div class="small dim mt">' + _t("noWin", "Nothing owed by the bank on this one.") + "</div>";
        }
      }
    }
    el.innerHTML = h;
    // wiring, so a caller only has to hand over the element
    if ($("btnBook")) $("btnBook").onclick = () => o.onPost && o.onPost($("bookAmt").value);
    el.querySelectorAll(".bkSet").forEach((btn) => btn.onclick = () => {
      const i = Number(btn.dataset.o);
      const pct = Math.round(parseFloat(el.querySelector('.bkPrice[data-o="' + i + '"]').value) * 100);
      this.quote(b.id, i, pct, o.quoteLabel && o.quoteLabel(i, pct));
    });
    el.querySelectorAll(".bkBack").forEach((btn) => btn.onclick = () => {
      const i = Number(btn.dataset.o);
      o.onBack && o.onBack(i, el.querySelector('.bkStake[data-o="' + i + '"]').value);
    });
    if ($("btnSweep")) $("btnSweep").onclick = () => this.sweep(b.id, o.sweepLabel);
    if ($("btnBclaim")) $("btnBclaim").onclick = () => this.claim(b.id, o.claimLabel);
  }
}

// A displayed ceiling must never be ROUNDED UP — a max the chain would refuse is worse than a slightly
// conservative one — so this floors to 4 decimals ("max 0.456521" reads like noise; "max 0.4565" reads
// like a limit).
export const trimMax = (raw) => String(Math.floor(Number(rawToNado(raw)) * 1e4) / 1e4);

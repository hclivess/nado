// lend.js — NADO Lend: peer-to-peer collateralised fixed-term loans on the execution layer, built on the
// shared game SDK (nadodapp.js). A lender posts terms — "I lend 100, I want 20 interest, you post 150
// collateral, you have 7 days" — and escrows the principal there and then. A borrower who likes those terms
// posts the collateral and leaves with the principal. Repay before the deadline and the collateral comes
// back; miss it and the lender takes it.
//
// There is NO price oracle and no variable rate: interest is an AMOUNT fixed at offer time and the only
// "liquidation" is a deadline passing, which the chain can see by itself. So nothing here needs a feed, and
// the UI never has to explain a health factor — a loan is open, live, repaid, defaulted or cancelled.
//
// Every exit belongs to the party owed it: the lender cancels an untaken offer, the borrower repays a live
// one, and ANYONE may default an expired one (the collateral is credited to the lender regardless of who
// clicked). That last one is why a lender who loses their key cannot freeze a borrower's collateral.
// Login + every signature is delegated to the NADO wallet; the key never touches this origin.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, gate, canPay, notify, confirmingLabel,
         wireWallet, renderWallet, stickyInputs, alertBar, loadQR, orderCards, installModes, playModes,
         fmtWhen, uiConfirm, disp } from "./nadodapp.js?v=99fc7471";

const CID = "1594ee26854cce0279bd31458955e7df";
const dapp = new NadoDapp({ cid: CID, app: "Lend" });

// The contract stores every amount in UNITs of 10^4 raw NADO (see execnode/games/lend.py). The UI speaks
// NADO everywhere and converts at the boundary, so a stray unit/raw mix-up cannot reach a call argument.
const UNIT = 10_000n;
const unitsToRaw = (u) => BigInt(u || 0) * UNIT;
const rawToUnits = (raw) => BigInt(raw) / UNIT;
const showUnits = (u) => rawToNado(unitsToRaw(u));

const ST_OPEN = 1, ST_TAKEN = 2, ST_REPAID = 3, ST_DEFAULT = 4, ST_CANCELLED = 5;
const DAY = 86400;

let lastSto = null, active = null;

// ---- reads: everything derived from the contract's storage maps -------------------------------------
const allIds = (sto) => Object.keys(_m(sto, "ln"));

function loanFrom(sto, id) {
  id = String(id);
  if (!_m(sto, "ln")[id]) return { exists: false };
  const st = _m(sto, "st")[id] || 0;
  const due = _m(sto, "dl")[id] || 0;
  const now = Math.floor(Date.now() / 1000);
  return {
    exists: true, id: Number(id), state: st,
    lender: _m(sto, "lr")[id] || "", borrower: _m(sto, "bw")[id] || "",
    principal: _m(sto, "pr")[id] || 0, interest: _m(sto, "it")[id] || 0,
    collateral: _m(sto, "co")[id] || 0, duration: _m(sto, "dr")[id] || 0,
    due, lenderClaim: _m(sto, "lc")[id] || 0, borrowerClaim: _m(sto, "bc")[id] || 0,
    // A live loan past its deadline is DEFAULTABLE but not yet defaulted — the state only changes when
    // somebody calls default(). Showing that distinction is the difference between "you lost it" and
    // "someone still has to press the button", and the second one is actionable.
    expired: st === ST_TAKEN && due > 0 && now >= due,
    secsLeft: st === ST_TAKEN && due > 0 ? due - now : 0,
  };
}

const stateLabel = (l) => {
  if (l.state === ST_OPEN) return window.t("lend.stOpen", "open");
  if (l.state === ST_TAKEN) return l.expired ? window.t("lend.stExpired", "overdue") : window.t("lend.stLive", "live");
  if (l.state === ST_REPAID) return window.t("lend.stRepaid", "repaid");
  if (l.state === ST_DEFAULT) return window.t("lend.stDefault", "defaulted");
  if (l.state === ST_CANCELLED) return window.t("lend.stCancelled", "cancelled");
  return "?";
};

function fmtDuration(secs) {
  secs = Number(secs || 0);
  if (secs % DAY === 0) return window.t("lend.nDays", "{n} days", { n: secs / DAY });
  const h = Math.round(secs / 3600);
  return window.t("lend.nHours", "{n} hours", { n: h });
}

function fmtLeft(secs) {
  if (secs <= 0) return window.t("lend.overdueNow", "overdue");
  if (secs >= DAY) return window.t("lend.leftDays", "{n} days left", { n: Math.floor(secs / DAY) });
  if (secs >= 3600) return window.t("lend.leftHours", "{n} hours left", { n: Math.floor(secs / 3600) });
  return window.t("lend.leftMins", "{n} min left", { n: Math.max(1, Math.floor(secs / 60)) });
}

// ---- offer-form sliders (the SDK percent primitive, one per amount) ---------------------------------
// Each slider resolves to a % of a LIVE max rather than a fixed ceiling, which is what keeps the three
// amounts coherent: you cannot lend more than you hold, and interest and collateral are expressed against
// the principal you actually chose. Chaining them this way also means moving the principal re-scales the
// other two instead of leaving stale absolute figures behind.
const SL_PRINCIPAL = { slider: "oPrincipalSlider", input: "oPrincipal" };
const SL_INTEREST = { slider: "oInterestSlider", input: "oInterest" };
const SL_COLLATERAL = { slider: "oCollateralSlider", input: "oCollateral" };

const principalRaw = () => { try { return nadoToRaw($("oPrincipal").value || "0"); } catch (e) { return 0n; } };
// Collateral must EXCEED the principal, so a 0..3x range puts the only valid region in the upper two
// thirds of the travel and makes an invalid offer visibly hard to build rather than merely rejected.
const collateralMax = () => principalRaw() * 3n;

function syncSliders() {
  dapp.syncPctSlider("lendPrincipal", SL_PRINCIPAL, dapp.exec || 0n);
  dapp.syncPctSlider("lendInterest", SL_INTEREST, principalRaw());
  dapp.syncPctSlider("lendCollateral", SL_COLLATERAL, collateralMax());
}

// ---- actions ----------------------------------------------------------------------------------------
async function postOffer() {
  const principal = rawToUnits(nadoToRaw($("oPrincipal").value || "0"));
  const interest = rawToUnits(nadoToRaw($("oInterest").value || "0"));
  const collateral = rawToUnits(nadoToRaw($("oCollateral").value || "0"));
  const days = parseInt($("oDays").value, 10) || 0;

  if (principal <= 0n) return notify(window.t("lend.needPrincipal", "Enter how much you want to lend."));
  if (collateral <= principal) {
    // Enforced on-chain too; catching it here turns a revert into a sentence that explains the rule.
    return notify(window.t("lend.needCollateral",
      "Collateral must be MORE than the principal — otherwise walking away costs the borrower nothing."));
  }
  if (days <= 0) return notify(window.t("lend.needDays", "Enter a loan length in days."));
  const stakeRaw = unitsToRaw(principal);
  if (!canPay(stakeRaw, notify)) return;

  const id = randId();
  active = id;
  dapp.call("offer", [id, Number(principal), Number(interest), Number(collateral), days * DAY], stakeRaw,
    window.t("lend.callOffer", "offer loan #{id} · lend {p} for {i} interest", {
      id, p: showUnits(principal), i: showUnits(interest) }),
    { loanId: id, phase: "offer" });
}

function takeLoan(l) {
  if (dapp.busy("take", "loanId", l.id)) return notify(confirmingLabel());
  const collRaw = unitsToRaw(l.collateral);
  if (!canPay(collRaw, notify)) return;
  active = l.id;
  dapp.call("take", [l.id], collRaw,
    window.t("lend.callTake", "borrow {p} against {c} collateral · loan #{id}", {
      p: showUnits(l.principal), c: showUnits(l.collateral), id: l.id }),
    { loanId: l.id, phase: "take" });
}

async function repayLoan(l) {
  if (dapp.busy("repay", "loanId", l.id)) return notify(confirmingLabel());
  const owed = unitsToRaw(BigInt(l.principal) + BigInt(l.interest));
  if (!canPay(owed, notify)) return;
  const ok = await uiConfirm(window.t("lend.confirmRepay",
    "Repay {a} NADO now to release your {c} NADO collateral?",
    { a: rawToNado(owed), c: showUnits(l.collateral) }));
  if (!ok) return;
  dapp.call("repay", [l.id], owed,
    window.t("lend.callRepay", "repay loan #{id} · {a}", { id: l.id, a: rawToNado(owed) }),
    { loanId: l.id, phase: "repay" });
}

const cancelOffer = (l) => {
  if (dapp.busy("cancel", "loanId", l.id)) return notify(confirmingLabel());
  dapp.call("cancel", [l.id], null,
    window.t("lend.callCancel", "withdraw offer #{id}", { id: l.id }), { loanId: l.id, phase: "cancel" });
};

const defaultLoan = (l) => {
  if (dapp.busy("default", "loanId", l.id)) return notify(confirmingLabel());
  dapp.call("default", [l.id], null,
    window.t("lend.callDefault", "close overdue loan #{id} (collateral to the lender)", { id: l.id }),
    { loanId: l.id, phase: "default" });
};

const claimLoan = (l) => {
  if (dapp.busy("claim", "loanId", l.id)) return notify(confirmingLabel());
  dapp.call("claim", [l.id], null,
    window.t("lend.callClaim", "collect from loan #{id}", { id: l.id }), { loanId: l.id, phase: "claim" });
};

// ---- rendering --------------------------------------------------------------------------------------
function loanRow(l, role) {
  const me = dapp.me;
  const terms = window.t("lend.terms", "{p} for {i} interest · {c} collateral · {d}", {
    p: showUnits(l.principal), i: showUnits(l.interest), c: showUnits(l.collateral),
    d: fmtDuration(l.duration) });

  const btns = [];
  if (l.state === ST_OPEN && role === "lender") {
    btns.push(`<button class="btn ghost" data-act="cancel" data-id="${l.id}">${window.t("lend.btnCancel", "Withdraw offer")}</button>`);
  }
  if (l.state === ST_OPEN && role !== "lender" && me && l.lender !== me) {
    btns.push(`<button class="btn" data-act="take" data-id="${l.id}">${window.t("lend.btnBorrow", "Borrow this")}</button>`);
  }
  if (l.state === ST_TAKEN && l.borrower === me && !l.expired) {
    btns.push(`<button class="btn" data-act="repay" data-id="${l.id}">${window.t("lend.btnRepay", "Repay")}</button>`);
  }
  if (l.state === ST_TAKEN && l.expired) {
    btns.push(`<button class="btn ghost" data-act="default" data-id="${l.id}">${window.t("lend.btnClose", "Close overdue loan")}</button>`);
  }
  const owed = (l.lender === me ? l.lenderClaim : 0) + (l.borrower === me ? l.borrowerClaim : 0);
  if (owed > 0) {
    btns.push(`<button class="btn" data-act="claim" data-id="${l.id}">${
      window.t("lend.btnCollect", "Collect {a}", { a: showUnits(owed) })}</button>`);
  }

  const when = l.state === ST_TAKEN
    ? `<span class="dim">${fmtLeft(l.secsLeft)}</span>`
    : (l.due ? `<span class="dim">${fmtWhen(l.due * 1000)}</span>` : "");

  return `<div class="loan">
    <div class="loanmain">
      <div class="loantop"><b>#${l.id}</b> <span class="pill ${l.expired ? "warn" : ""}">${stateLabel(l)}</span> ${when}</div>
      <div class="loanterms">${terms}</div>
      <div class="loanwho dim">${l.lender ? window.t("lend.byLender", "lender {a}", { a: disp(l.lender) }) : ""}${
        l.borrower ? " · " + window.t("lend.byBorrower", "borrower {a}", { a: disp(l.borrower) }) : ""}</div>
    </div>
    <div class="loanacts">${btns.join("")}</div>
  </div>`;
}

function render() {
  const sto = lastSto;
  const me = dapp.me;
  const signedIn = !!me;
  gate({ offerCard: signedIn, mineCard: signedIn, marketCard: true });

  if (!sto) {
    $("market").innerHTML = `<div class="dim">${window.t("lend.loading", "Loading loans…")}</div>`;
    return;
  }
  const loans = allIds(sto).map((id) => loanFrom(sto, id)).filter((l) => l.exists).sort((a, b) => b.id - a.id);

  // OPEN OFFERS — the shop window. Your own offers are excluded (you cannot take them, and the contract
  // refuses it) and shown under "your loans" instead, where the cancel button lives.
  const open = loans.filter((l) => l.state === ST_OPEN && l.lender !== me);
  $("market").innerHTML = open.length
    ? open.map((l) => loanRow(l, "browser")).join("")
    : `<div class="dim">${window.t("lend.noOffers", "No open offers yet — post the first one.")}</div>`;

  // YOUR LOANS — both sides, because the same person is often both, and splitting them into two cards
  // hides the one thing that matters: what needs doing right now.
  const mine = loans.filter((l) => me && (l.lender === me || l.borrower === me));
  $("mine").innerHTML = mine.length
    ? mine.map((l) => loanRow(l, l.lender === me ? "lender" : "borrower")).join("")
    : `<div class="dim">${window.t("lend.noneYours", "You have no loans yet.")}</div>`;

  renderWallet(dapp);
  syncSliders();          // after renderWallet, so the principal slider sees the refreshed playable balance
}

async function refresh() {
  try {
    const sto = await dapp.storage();
    if (sto) lastSto = sto;
  } catch (e) { /* transient relay blip — keep the last good view rather than blanking the page */ }
  render();
}

// ---- wiring -----------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp, render);
  stickyInputs(["oPrincipal", "oInterest", "oCollateral", "oDays"], "nado_lend_form");
  $("btnOffer").onclick = postOffer;

  // Bind each amount slider once. Moving the PRINCIPAL re-syncs the other two, because their maxes are
  // derived from it — without that the interest thumb would keep pointing at a percentage of a number
  // that is no longer on screen.
  dapp.wirePctSlider("lendPrincipal", SL_PRINCIPAL, () => dapp.exec || 0n, syncSliders);
  dapp.wirePctSlider("lendInterest", SL_INTEREST, principalRaw, syncSliders);
  dapp.wirePctSlider("lendCollateral", SL_COLLATERAL, collateralMax, syncSliders);
  syncSliders();

  // ONE delegated handler for every row button: rows are re-rendered on each poll, so per-button
  // listeners would be re-attached (and leak) three times a second.
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-act]");
    if (!b) return;
    const l = loanFrom(lastSto, b.dataset.id);
    if (!l.exists) return;
    ({ take: takeLoan, repay: repayLoan, cancel: cancelOffer, default: defaultLoan, claim: claimLoan })[b.dataset.act](l);
  });
}

dapp.onReturn((pend, ok, err) => {
  if (pend && pend.loanId != null) active = pend.loanId;
  dapp.showReturn(pend, ok, err, {
    offer: window.t("lend.offerSubmitted", "Offer posted — confirming…"),
    take: window.t("lend.takeSubmitted", "Borrowing — confirming…"),
    repay: window.t("lend.repaySubmitted", "Repayment sent — confirming…"),
    claim: window.t("lend.claimSubmitted", "Collecting…"),
  });
  refresh();
});

async function boot() {
  try { await dapp.init(); } catch (e) {
    alertBar(window.t("lend.cryptoFail", "Crypto bundle failed to load — reload."));
    return;
  }
  wireUI(); loadQR(); orderCards(["offerCard", "mineCard", "marketCard", "walletcard"]);
  const modes = installModes(dapp, { modes: playModes({ icon: "🏦", play: ["marketCard", "mineCard", "offerCard"] }) });
  render = modes.wrap(render);
  const q = new URLSearchParams(location.search).get("loan");
  if (q) active = parseInt(q, 10);
  refresh();
  setInterval(refresh, 3000);
}
boot();

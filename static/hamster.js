// hamster.js — NADO Hamster Racing: a provably-fair, PARIMUTUEL race between six hamsters, on the shared
// game SDK (nadodapp.js). A race pins three future block heights: at the GENE block each hamster's speed
// is fixed and shown (derived from that block's hash); betting stays open for a window; then the RACE blocks
// decide how far each hamster runs (step = HASH(blockhash, race, lane) % (speed+6) per block). The hamster
// with the greatest total distance wins, and its backers split the whole pot pro-rata. No house, no oracle:
// genes come from a block mined BEFORE betting closes (public), the run from blocks mined AFTER (unknown to
// every bettor) — so you read form + the live tote, exactly like a racetrack. The client mirrors the
// contract's alghash math (algHashn) to show genes and animate the run; the contract is the authority.
// Contract: execnode/games/hamster.py.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, orderCards, alertBar, notify, okBar, confirmingLabel, blocksToTime, wireWallet, stickyInputs, renderWallet, renderTopScores, recentChips, loadQR, resolveAliases, disp, share, shareInvite, algHashn, ALG_P, esc } from "./nadodapp.js";
import { todayIdx, anchorOf, ensureAnchor, entriesFrom, verifyEntries, provableSeed, packMoves } from "./provable.js";
import * as DERBY from "./hamster-daily.js";

const CID = "2f8cc0ce02bc5e02abb10e4dc3af28e7";   // execnode/games/hamster.py (zkVM)
const dapp = new NadoDapp({ cid: CID, app: "Hamster" });

// keep these in lockstep with execnode/games/hamster.py
const NH = 6, GENE_DELAY = 2, BET_BLOCKS = 20, RACE_LEN = 10, GENE_SPREAD = 8, STEP_BASE = 6;
// UNIT = raw NADO per pool unit. MIND THE UNITS — the two sources differ and mixing them up silently
// inflates every displayed amount by 10^4:
//   • raw STORAGE maps (tot/pl/...) hold UNITs      -> multiply by UNIT before rawToNado()
//   • the contract VIEWS (total_of / stake_of / claimable_of) already `mul UNIT` and return RAW NADO
//     -> pass them to rawToNado() as-is. (A double-multiply here showed a 13.78 NADO stake as 137798.1.)
const UNIT = 10000n, BLOCK_SECS = 6;
const P = ALG_P();

let lastSto = null, active = null, lastRace = null, myCache = {};
let mode = "bet";                     // "bet" (real parimutuel races) | "daily" (free Daily Derby)
let daily = { day: null, anchor: null, seed: null, races: null, picks: [], posted: false };
const LS_DAILY = "nado_hamster_daily";   // {day, picks} — resume today's run across reloads

// ---- the six racers: name + coat, derived from the gene (client-only flavor; speed is consensus) --------
const NAMES = ["Nibbles", "Peanut", "Biscuit", "Waffles", "Pebble", "Cheeko", "Tumble", "Marbles", "Sprocket",
  "Pippin", "Gizmo", "Noodle", "Bandit", "Truffle", "Bram", "Cinnamon", "Widget", "Momo", "Dashi", "Clover"];
const COATS = [["#e8b06b", "#c98a3e"], ["#d9d2c5", "#b3a892"], ["#8a5a3c", "#6b4128"], ["#f0e2c0", "#d8c48a"],
  ["#b9c0c7", "#8f9aa3"], ["#e0a89a", "#c07d6c"], ["#c9a24a", "#a07c2a"], ["#6f6f78", "#4c4c55"]];
const laneEmoji = ["🥕", "🌰", "🍪", "🧇", "🪨", "🐹"];

// gene(race, lane): { speed(1..8), name, coat[light,dark] } — MUST match the contract's speed derivation.
function geneOf(race, lane) {
  const g = geneRaw(race, lane);
  if (g == null) return null;
  const speed = 1 + Number((g & 0xFFFFFFFFn) % BigInt(GENE_SPREAD));
  const bits = g >> 32n;
  return { lane, speed, name: NAMES[Number(bits % BigInt(NAMES.length))], coat: COATS[Number((bits >> 8n) % BigInt(COATS.length))] };
}
// geneRaw: alghash(BLOCKHASH(gh), lane) — null until the gene block hash is cached.
function geneRaw(race, lane) {
  if (!lastRace || !lastRace.gh) return null;
  const h = dapp.bh(lastRace.gh); if (!h) return null;
  const seed = BigInt("0x" + h) % P;
  return algHashn([seed, BigInt(lane)]);
}
// step for one lane at one race block — matches the contract exactly.
function stepAt(race, lane, blockHeight, speed) {
  const h = dapp.bh(blockHeight); if (!h) return null;
  const seed = BigInt("0x" + h) % P;
  const roll = algHashn([seed, BigInt(race), BigInt(lane)]);
  return Number((roll & 0xFFFFFFFFn) % BigInt(speed + STEP_BASE));
}
// per-lane cumulative distance using every race block whose hash is cached (drives the animation + preview).
function standings(race) {
  const genes = []; for (let l = 0; l < NH; l++) genes.push(geneOf(race, l));
  if (genes.some((g) => !g)) return null;
  const rows = genes.map((g) => ({ ...g, dist: 0, blocks: 0 }));
  for (let bi = 1; bi <= RACE_LEN; bi++) {
    const bh = race.lk + bi;
    if (dapp.cursor == null || dapp.cursor < bh) break;      // block not reached yet
    let any = false;
    for (let l = 0; l < NH; l++) { const s = stepAt(race.id, l, bh, rows[l].speed); if (s != null) { rows[l].dist += s; rows[l].blocks = bi; any = true; } }
    if (!any) break;
  }
  return rows;
}
// the winner the CLIENT computes from cached hashes (argmax distance, ties -> lowest lane) — the contract's
// wn is authoritative once settled; before that this drives the live "leading" cue.
function leaderOf(rows) {
  let best = -1, w = 0;
  for (let l = 0; l < NH; l++) if (rows[l].dist > best) { best = rows[l].dist; w = l; }
  return w;
}

// ---- reads (hamster storage schema) --------------------------------------------------------------
function readRace(sto, id) {
  id = String(id); if (!_m(sto, "ra")[id]) return { id: Number(id), exists: false };
  const gh = Number(_m(sto, "gh")[id] || 0), lk = Number(_m(sto, "lk")[id] || 0), fh = Number(_m(sto, "fh")[id] || 0);
  const tot = BigInt(_m(sto, "tot")[id] || 0) * UNIT;
  const pools = [], di = [];
  for (let l = 0; l < NH; l++) { pools.push(BigInt(_m(sto, "pl")[Number(id) * NH + l] || 0) * UNIT); di.push(Number(_m(sto, "di")[Number(id) * NH + l] || 0)); }
  const sd = !!_m(sto, "sd")[id], vd = !!_m(sto, "vd")[id], wn = Number(_m(sto, "wn")[id] || 0);
  const cur = dapp.cursor;
  const phase = sd ? "done" : (cur != null && cur >= fh) ? "settling"
    : (cur != null && cur >= lk) ? "racing" : (cur != null && cur >= gh) ? "betting" : "incubating";
  return { id: Number(id), exists: true, gh, lk, fh, tot, pools, di, sd, vd, wn, cur, phase };
}
const allRaces = (sto) => Object.keys(_m(sto, "ra")).map((id) => readRace(sto, id)).filter((r) => r.exists);
// live tote odds for a lane: whole pot ÷ that lane's pool (what a winning unit pays back).
const oddsOf = (r, l) => r.pools[l] > 0n && r.tot > 0n ? Number(r.tot) / Number(r.pools[l]) : null;

async function refreshMy(r) {
  if (!dapp.me || !r || !r.exists) return;
  const c = myCache[r.id] || (myCache[r.id] = { stakes: [] });
  const [total, claimable, claimed] = await Promise.all([
    dapp.view("total_of", [r.id, dapp.me]), dapp.view("claimable_of", [r.id, dapp.me]), dapp.view("claimed_of", [r.id, dapp.me])]);
  if (total != null) c.total = BigInt(total);
  if (claimable != null) c.claimable = BigInt(claimable);
  if (claimed != null) c.claimed = Number(claimed);
  if (c.total > 0n) c.stakes = (await Promise.all([...Array(NH)].map((_x, l) => dapp.view("stake_of", [r.id, l, dapp.me])))).map((v) => BigInt(v || 0));
}

// ---- actions -------------------------------------------------------------------------------------
function openRace() {
  if (!dapp.me) return dapp.signIn();
  if (dapp.busy("open")) return notify(confirmingLabel());
  const r = randId();
  active = r;
  dapp.call("open", [r], null, window.t("hamster.callOpen", "start hamster race #{r}", { r }), { race: r, phase: "open" });
}
function placeBet(lane) {
  const r = lastRace; if (!r || !r.exists) return;
  if (r.phase !== "betting") return notify(window.t("hamster.notOpen", "Betting isn't open on this race right now."));
  if (dapp.busy("bet", "race", r.id)) return notify(confirmingLabel());
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) return alertBar(window.t("hamster.enterStake", "Enter a stake in NADO."));
  if (stake % UNIT !== 0n) return alertBar(window.t("hamster.unitStake", "Stakes are in whole units of {u} NADO — round to the nearest {u}.", { u: rawToNado(UNIT) }));
  if (!canPay(dapp, stake, window.t("hamster.whatBet", "This bet"))) return;
  const g = geneOf(r.id, lane);
  dapp.call("bet", [r.id, lane], stake, window.t("hamster.callBet", "back {name} (lane {l}) · {amt} NADO · race #{r}", { name: g ? g.name : ("#" + (lane + 1)), l: lane + 1, amt: rawToNado(stake), r: r.id }), { race: r.id, lane, phase: "bet" });
}
const settleRace = (id) => { if (dapp.busy("settle", "race", id)) return; dapp.call("settle", [id], null, window.t("hamster.callSettle", "photo-finish race #{r}", { r: id }), { race: id, phase: "settle" }); };
const claimRace = (id) => { if (dapp.busy("claim", "race", id)) return; dapp.call("claim", [id], null, window.t("hamster.callClaim", "collect race #{r} winnings", { r: id }), { race: id, phase: "claim" }); };

// AUTO-SETTLE a finished race, then AUTO-COLLECT my winnings (shared SDK tick — value-free, background-signs).
function maybeAuto() {
  if (!lastRace || !lastRace.exists) return;
  if (lastRace.phase === "settling") { dapp.autoCollect([{ g: lastRace.id }], () => settleRace(lastRace.id), { key: () => "settle:" + lastRace.id }); return; }
  if (lastRace.sd || lastRace.vd) {
    const c = myCache[lastRace.id] || {};
    if ((c.claimable || 0n) > 0n && !c.claimed) dapp.autoCollect([{ g: lastRace.id }], () => claimRace(lastRace.id), { key: () => "claim:" + lastRace.id });
  }
}

// ---- refresh loop --------------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  const sto = await dapp.storage({ append: ["ra", "sd", "vd", "wn"] });
  if (sto) {
    lastSto = sto;
    if (active != null) {
      lastRace = readRace(sto, active);
      // fetch the block hashes the client needs: the gene block + every race block that already exists.
      const want = [];
      if (lastRace.exists) {
        if (dapp.cursor != null && dapp.cursor >= lastRace.gh) want.push(lastRace.gh);
        for (let bi = 1; bi <= RACE_LEN; bi++) { const b = lastRace.lk + bi; if (dapp.cursor != null && dapp.cursor >= b) want.push(b); }
      }
      // PUBLIC, contract-re-validated randomness -> fast (provisional) is safe (a reorg just re-runs settle).
      if (want.length) await dapp.blockHashes(want, { fast: true });
      await refreshMy(lastRace);
    }
    renderLobby(sto);
    // keep the day's provable-board anchor seeded (permissionless upkeep) + render the daily leaderboard
    daily.anchor = anchorOf(sto, _m, todayIdx());
    if (!daily.anchor) { try { await ensureAnchor(dapp, base(), sto, _m, todayIdx()); } catch {} }
    await renderBoard(sto);
    dapp.settleInflight((f) => {
      const r = readRace(sto, f.race);
      return f.phase === "open" ? r.exists
        : f.phase === "bet" ? (dapp.cursor != null && r.exists)   // a bet lands within a block; tip-advance covers it
        : f.phase === "settle" ? r.sd
        : f.phase === "claim" ? !!(myCache[f.race] && myCache[f.race].claimed)
        : f.phase === "post" ? (myBestToday(todayIdx()) != null)
        : true;   // anchor upkeep etc. — release on any tip advance
    });
    await resolveAliases([dapp.me].filter(Boolean));
  }
  render();
  maybeAuto();
}

// ---- Daily Derby (free, provable, faucet-rewarded) -----------------------------------------------
function loadDailyPicks(day) {
  try { const d = JSON.parse(localStorage.getItem(LS_DAILY) || "{}"); if (d.day === day && Array.isArray(d.picks)) return d.picks; } catch {}
  return [];
}
function saveDailyPicks(day, picks) { try { localStorage.setItem(LS_DAILY, JSON.stringify({ day, picks })); } catch {} }

// build today's per-player slate once the anchor + wallet are known; picks resume from localStorage.
function ensureDaily() {
  const day = todayIdx();
  if (daily.day !== day) { daily = { day, anchor: null, seed: null, races: null, picks: [], posted: false }; }
  if (!daily.anchor || !dapp.me) return;
  const seed = provableSeed(DERBY.SLUG, day, daily.anchor, dapp.me);
  if (daily.seed !== seed) { daily.seed = seed; daily.races = DERBY.dailyRaces(seed); daily.picks = loadDailyPicks(day); }
}
function playPick(lane) {
  ensureDaily();
  if (!daily.races || daily.picks.length >= DERBY.RACES) return;
  daily.picks.push(lane); saveDailyPicks(daily.day, daily.picks); render();
}
function postDaily() {
  ensureDaily();
  if (!daily.races || daily.picks.length !== DERBY.RACES) return;
  if (dapp.busy("post")) return notify(confirmingLabel());
  const score = DERBY.scorePicks(daily.races, daily.picks);
  const word = packMoves(daily.picks, DERBY.PICK_BITS)[0] || 0;
  dapp.call("post", [daily.day, score, DERBY.RACES, word], null, window.t("hamster.callPost", "post my Daily Derby score ({s})", { s: score }), { phase: "post" });
  notify(window.t("hamster.posted", "Score submitted — it appears on the board once verified on-chain."));
}

// the daily leaderboard: read the day's claims, REPLAY-verify each (a forged score never ranks), rank by
// points, and render with the faucet prize taper (top finishers are paid automatically each day).
async function renderBoard(sto) {
  const el = $("scoreList"); if (!el) return;
  const day = todayIdx(), anchor = anchorOf(sto, _m, day);
  if (!anchor) { el.innerHTML = '<span class="dim">' + window.t("hamster.seeding", "Seeding today's derby from the chain — a moment…") + "</span>"; return; }
  const entries = entriesFrom(sto, _m, day, ["ew0"]);
  const rows = await verifyEntries(entries, (en) => DERBY.verifyClaim(day, en.n, en.words, anchor, en.addr));
  await renderTopScores(el, rows.map((r) => ({ addr: r.addr, score: r.score })), dapp.me,
    window.t("hamster.boardEmpty", "No runs yet today — play the Daily Derby and post the first score."),
    window.t("hamster.points", "Points"), true);
}
function renderDaily() {
  const c = $("dailyCard"); if (!c) return;
  if (!dapp.me) { $("derby").innerHTML = '<div class="dim">' + window.t("hamster.derbySignIn", "Sign in to play today's free Daily Derby — pick winners, top the board, and the faucet pays the daily leaders automatically.") + "</div>"; return; }
  ensureDaily();
  if (!daily.anchor) { $("derby").innerHTML = '<div class="dim">' + window.t("hamster.seeding", "Seeding today's derby from the chain — a moment…") + "</div>"; return; }
  if (!daily.races) { $("derby").innerHTML = '<div class="dim">' + window.t("hamster.loading", "Loading…") + "</div>"; return; }
  const i = daily.picks.length, done = i >= DERBY.RACES;
  const score = DERBY.scorePicks(daily.races, daily.picks);
  let h = '<div class="small dim" style="margin-bottom:8px">' + window.t("hamster.derbyIntro", "Race {n} of {t} · your score: {s} pts. Read each hamster's form (speed) and back one — a winning longshot pays its odds.", { n: Math.min(i + 1, DERBY.RACES), t: DERBY.RACES, s: score }) + "</div>";
  if (!done) {
    const race = daily.races[i];
    h += '<div class="derbyRace"><div class="small" style="margin-bottom:6px">🏁 <b>' + window.t("hamster.derbyPick", "Race {n} — pick your winner", { n: i + 1 }) + "</b></div>";
    h += race.speeds.map((sp, l) => '<div class="betrow"><span class="be">' + laneEmoji[l] + '</span><b>' + esc(DERBY.dailyName(daily.seed, i, l)) + '</b> <span class="dim">' + window.t("hamster.spd", "spd {s}", { s: sp }) + '</span><span class="odds">' + (race.odds[l] / 100).toFixed(1) + "×</span><button class='mini primary' data-pick='" + l + "'>" + window.t("hamster.pickBtn", "Pick") + "</button></div>").join("");
    h += "</div>";
  } else {
    const c2 = daily.races.reduce((n, race, r) => n + (daily.picks[r] === race.winner ? 1 : 0), 0);
    h += '<div class="derbyDone"><b>' + window.t("hamster.derbyDone", "Derby complete — {c}/{t} winners, {s} points!", { c: c2, t: DERBY.RACES, s: score }) + "</b>"
      + '<div class="small dim mt">' + window.t("hamster.derbyResults", "Results (your pick vs the winner):") + "</div>"
      + '<div class="small mono" style="margin-top:4px">' + daily.races.map((race, r) => (daily.picks[r] === race.winner ? "✅" : "❌") + " R" + (r + 1) + ": " + window.t("hamster.laneN", "lane {n}", { n: daily.picks[r] + 1 }) + " / " + window.t("hamster.wonN", "won {n}", { n: race.winner + 1 })).join("<br>") + "</div>";
    const mine = myBestToday(daily.day);
    if (mine != null) h += '<div class="b ok mt" style="display:inline-block">' + window.t("hamster.postedBest", "Posted: {s} pts", { s: mine }) + "</div>";
    else h += '<button class="primary mt" id="btnPost" style="width:100%">' + (dapp.busy("post") ? confirmingLabel() : window.t("hamster.postScore", "🏆 Post my {s} points to the board", { s: score })) + "</button>";
    h += '<button class="ghost mt" id="btnReplayDerby" style="width:100%">' + window.t("hamster.replay", "↺ Replay today (won't repost)") + "</button></div>";
  }
  $("derby").innerHTML = h;
  $("derby").querySelectorAll("[data-pick]").forEach((b) => b.onclick = () => playPick(parseInt(b.dataset.pick, 10)));
  if ($("btnPost")) $("btnPost").onclick = postDaily;
  if ($("btnReplayDerby")) $("btnReplayDerby").onclick = () => { daily.picks = []; saveDailyPicks(daily.day, []); render(); };
}
// my posted best score for the day (from the on-chain entries) — hides the Post button once I've posted.
function myBestToday(day) {
  if (!lastSto || !dapp.me) return null;
  const e = entriesFrom(lastSto, _m, day, ["ew0"]).filter((x) => x.addr === dapp.me);
  return e.length ? Math.max(...e.map((x) => x.score)) : null;
}

function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const races = allRaces(sto).filter((r) => !r.sd && !r.vd).sort((a, b) => b.id - a.id).slice(0, 24);
  el.innerHTML = races.length ? races.map((r) => {
    const tag = r.phase === "betting" ? window.t("hamster.lobBet", "🟢 betting") : r.phase === "racing" ? window.t("hamster.lobRun", "🏁 racing") : r.phase === "incubating" ? window.t("hamster.lobWarm", "🥚 warming up") : window.t("hamster.lobSettle", "📸 finishing");
    return '<button class="chip betting" data-r="' + r.id + '">🐹 #' + r.id + " · " + tag + (r.tot > 0n ? " · " + rawToNado(r.tot) + " NADO" : "") + "</button>";
  }).join(" ") : '<span class="dim">' + window.t("hamster.noRaces", "No races yet — start one below and let the tote fill up.") + "</span>";
  if (!el._deleg) { el._deleg = true; el.addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) { active = parseInt(b.dataset.r, 10); myCache = {}; refreshAll(); try { $("activeRace").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} } }); }
}

// ---- hamster art (a lane runner, coat from the gene) ---------------------------------------------
function hamsterSVG(coat, leading) {
  const [lt, dk] = coat || ["#e8b06b", "#c98a3e"];
  return '<svg viewBox="0 0 60 44" width="52" height="38" aria-hidden="true">'
    + '<ellipse cx="30" cy="40" rx="18" ry="3" fill="rgba(0,0,0,.25)"/>'
    + '<g class="hrun">'
    + '<ellipse cx="30" cy="26" rx="20" ry="14" fill="' + lt + '" stroke="#3a2a18" stroke-width="1.6"/>'   // body
    + '<path d="M14 26 Q22 18 30 20 Q22 30 14 30 Z" fill="' + dk + '" opacity=".5"/>'                       // haunch
    + '<circle cx="46" cy="20" r="9" fill="' + lt + '" stroke="#3a2a18" stroke-width="1.6"/>'               // head
    + '<circle cx="45" cy="12" r="3.4" fill="' + dk + '" stroke="#3a2a18" stroke-width="1.2"/>'             // ear
    + '<circle cx="49" cy="19" r="1.7" fill="#20242a"/>'                                                    // eye
    + '<circle cx="54.5" cy="22" r="1.6" fill="#e86d84"/>'                                                  // nose
    + '<path d="M52 25 q3 1 5 0 M52 22 q3 -1 5 -2" stroke="#3a2a18" stroke-width=".7" fill="none" opacity=".6"/>'  // whiskers
    + '<path d="M12 30 q-6 2 -8 6" stroke="#c98a3e" stroke-width="2.4" fill="none" stroke-linecap="round"/>'      // tail
    + (leading ? '<text x="30" y="8" font-size="9" text-anchor="middle">✨</text>' : '')
    + '</g></svg>';
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => dapp.exec, () => render());
  stickyInputs(dapp, ["stakeAmt", "bankAmt"]);
  if ($("btnNewRace")) $("btnNewRace").onclick = openRace;
  if ($("btnShare")) $("btnShare").onclick = () => share(base() + "/?race=" + active, window.t("hamster.shareText", "Bet on the hamsters at NADO — race #{r}:", { r: active }), $("btnShare"));
  if ($("tabBet")) $("tabBet").onclick = () => { mode = "bet"; render(); };
  if ($("tabDaily")) $("tabDaily").onclick = () => { mode = "daily"; render(); };
  dapp.wireAutoCollect();
}

function render() {
  const signedIn = renderWallet(dapp);
  dapp.reflectUrl("race", active);
  // mode toggle: BET (real parimutuel races) vs DAILY (free provable derby)
  const betMode = mode === "bet";
  if ($("tabBet")) $("tabBet").classList.toggle("on", betMode);
  if ($("tabDaily")) $("tabDaily").classList.toggle("on", !betMode);
  gate({ opencard: betMode, lobby: betMode, bankroll: betMode && signedIn, activeRace: betMode && active != null,
         dailyCard: !betMode });
  if (!betMode) { renderDaily(); return; }
  if (active == null) return;
  const r = lastRace;
  $("raceId").textContent = "#" + active;
  if (!r || !r.exists) { $("raceState").textContent = dapp.whereIs(window.t("hamster.raceWord", "race"), active); $("track").innerHTML = ""; $("betPanel").innerHTML = ""; shareInvite("race", null); return; }
  shareInvite("race", active, window.t("hamster.shareText", "Bet on the hamsters at NADO — race #{r}:", { r: active }), 170);
  const rows = standings(r);                     // null until genes are known
  const wnLane = r.sd ? r.wn - 1 : (rows ? leaderOf(rows) : -1);
  // state line + countdown (in blocks -> time)
  const toTime = (blocks) => blocksToTime(Math.max(0, blocks));
  let state;
  if (r.phase === "incubating") state = window.t("hamster.stWarm", "🥚 Warming up — genes lock at block {b} (~{t})", { b: r.gh, t: toTime(r.gh - (r.cur || r.gh)) });
  else if (r.phase === "betting") state = window.t("hamster.stBet", "🟢 Betting OPEN — closes at block {b} (~{t}). Read the form, then back a hamster!", { b: r.lk, t: toTime(r.lk - (r.cur || r.lk)) });
  else if (r.phase === "racing") { const lap = rows ? Math.max(0, ...rows.map((x) => x.blocks)) : 0; state = window.t("hamster.stRun", "🏁 And they're off — lap {k}/{n}! Each block nudges every hamster by its own step. Finish in ~{t}.", { k: lap, n: RACE_LEN, t: toTime(r.fh - (r.cur || r.fh)) }); }
  else if (r.phase === "settling") state = window.t("hamster.stPhoto", "📸 Photo finish — settling the result on-chain…");
  else state = r.vd ? window.t("hamster.stVoid", "↩ Void — no backers on the winning lane, every stake refunds 1:1.")
    : window.t("hamster.stDone", "🏆 {name} wins race #{r}!", { name: (rows && rows[wnLane]) ? rows[wnLane].name : ("Lane " + (wnLane + 1)), r: r.id });
  $("raceState").innerHTML = state;
  $("potLine").textContent = r.tot > 0n ? window.t("hamster.potLine", "Pot: {amt} NADO", { amt: rawToNado(r.tot) }) : window.t("hamster.potEmpty", "Pot: empty — be the first to bet.");

  // the track: one lane per hamster, position = distance / maxDistance
  const finalDist = r.sd ? r.di : null;                       // authoritative once settled
  const disp2 = rows ? rows.map((row, l) => ({ ...row, dist: finalDist ? finalDist[l] : row.dist })) : null;
  const maxD = disp2 ? Math.max(1, ...disp2.map((x) => x.dist), RACE_LEN * 3) : 1;
  $("track").innerHTML = disp2 ? disp2.map((row, l) => {
    const pct = Math.min(97, 3 + 94 * row.dist / maxD);
    const win = (r.sd || r.phase === "done") ? (l === wnLane && !r.vd) : (r.phase === "racing" && l === wnLane);
    const mine = (myCache[r.id] && myCache[r.id].stakes && (myCache[r.id].stakes[l] || 0n) > 0n);
    return '<div class="lane' + (win ? " win" : "") + (mine ? " mine" : "") + '">'
      + '<div class="laneHead"><b>' + esc(row.name) + '</b> <span class="dim">' + window.t("hamster.spd", "spd {s}", { s: row.speed }) + "</span>"
      + (mine ? ' <span class="b ok">' + window.t("hamster.yours", "yours") + "</span>" : "") + "</div>"
      + '<div class="rail"><div class="runner" style="left:' + pct + '%">' + hamsterSVG(row.coat, win) + '</div><div class="finish"></div></div>'
      + "</div>";
  }).join("") : '<div class="dim" style="padding:20px;text-align:center">' + window.t("hamster.genesLocking", "🎲 The chain is rolling the hamsters' genes… (locks at block {b})", { b: r.gh }) + "</div>";

  // the bet panel: one row per hamster with tote odds + a Back button (only in the betting phase)
  const bp = $("betPanel");
  if (r.phase === "betting" && rows) {
    dapp.syncPctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, dapp.exec);
    const busy = dapp.busy("bet", "race", r.id);
    bp.innerHTML = '<div class="small dim" style="margin-bottom:8px">' + window.t("hamster.toteHint", "Odds are the live tote — whole pot ÷ a lane's pool. They shift as bets come in. Speed is the hamster's form (higher = faster on average).") + "</div>"
      + rows.map((row, l) => {
        const o = oddsOf(r, l), myU = (myCache[r.id] && myCache[r.id].stakes && myCache[r.id].stakes[l]) || 0n;
        return '<div class="betrow"><span class="be">' + laneEmoji[l] + "</span><b>" + esc(row.name) + '</b> <span class="dim">' + window.t("hamster.spd", "spd {s}", { s: row.speed }) + "</span>"
          + '<span class="odds">' + (o ? o.toFixed(2) + "×" : window.t("hamster.noBets", "no bets")) + "</span>"
          + (myU > 0n ? '<span class="b ok" title="your stake">' + rawToNado(myU) + "</span>" : "")
          + '<button class="mini primary" data-back="' + l + '"' + (busy ? " disabled" : "") + ">" + (busy ? confirmingLabel() : window.t("hamster.back", "Back")) + "</button></div>";
      }).join("");
    bp.querySelectorAll("[data-back]").forEach((b) => b.onclick = () => placeBet(parseInt(b.dataset.back, 10)));
  } else if (r.phase === "incubating") {
    bp.innerHTML = '<div class="dim">' + window.t("hamster.warmHint", "Betting opens the moment the genes lock (block {b}). Hang tight.", { b: r.gh }) + "</div>";
  } else {
    // closed: show my position + claim
    const c = myCache[r.id] || {};
    let h = "";
    if ((c.total || 0n) > 0n) {
      h += '<div class="small">' + window.t("hamster.myStake", "Your stake: {amt} NADO", { amt: rawToNado(c.total) }) + "</div>";
      if ((r.sd || r.vd)) {
        const claimable = c.claimable || 0n;
        if (c.claimed) h += '<div class="b ok" style="margin-top:8px">' + window.t("hamster.claimed", "✓ Collected") + "</div>";
        else if (claimable > 0n) h += '<button class="primary" id="btnClaim" style="margin-top:8px">' + (dapp.busy("claim", "race", r.id) ? confirmingLabel() : window.t("hamster.claim", "💰 Collect {amt} NADO", { amt: rawToNado(claimable) })) + "</button>";
        else h += '<div class="dim" style="margin-top:8px">' + window.t("hamster.noWin", "No winnings on this race.") + "</div>";
      } else h += '<div class="dim" style="margin-top:8px">' + window.t("hamster.raceOn", "Race in progress — results settle automatically.") + "</div>";
    } else h = '<div class="dim">' + (r.phase === "racing" ? window.t("hamster.watchRun", "Betting closed — watch them run!") : window.t("hamster.settlingHint", "Settling the finish on-chain…")) + "</div>";
    bp.innerHTML = h;
    if ($("btnClaim")) $("btnClaim").onclick = () => claimRace(r.id);
  }
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.race != null) active = pend.race;
  dapp.showReturn(pend, ok, err, {
    open: window.t("hamster.rtOpen", "Starting the race — confirming…"), bet: window.t("hamster.rtBet", "Bet placed — confirming on-chain…"),
    settle: window.t("hamster.rtSettle", "Settling the finish…"), claim: window.t("hamster.rtClaim", "Collecting your winnings…"),
    post: window.t("hamster.rtPost", "Posting your Daily Derby score…") });
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("hamster.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR();
  orderCards(["activeRace", "lobby", "opencard", "walletcard", "bankroll", "scoreboard"]);
  const qs = new URLSearchParams(location.search);
  if (qs.get("race")) active = parseInt(qs.get("race"), 10);
  if (qs.get("daily") != null) mode = "daily";
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
if ($("btnNewRace")) boot();

// coinflip.js — NADO Coin Flip: a fair, STAKED 2-player game on the execution layer, built on the shared game
// SDK (nadodapp.js). COMMIT-REVEAL (execnode/games/coinflip.py): each player's browser draws a secret with the
// CSPRNG, stores it locally, and stakes with the commitment C = HASH(secret). Once both are in, each browser
// reveals its secret automatically and the coin is
//   result = HASH( s1 + s2 + gameId ) LO32 % 2   (0 -> heads/p1, 1 -> tails/p2)   == chainResultAlg(s1, s2, g, 2)
// Neither secret is known to the other player when they commit, so nobody can steer the sum. The reveal window
// closes REVEAL_WINDOW blocks after the join: a lone revealer then takes the whole pot (withholding a losing
// reveal gains nothing), and if nobody revealed both stakes are refunded. settle is permissionless.
// Games opened by the previous code (md == 0, no commitments) still resolve from BLOCKHASH(sh) + BLOCKHASH(sh+1).
// The stake is escrowed as call VALUE and paid by the contract's PAY. Login + every signature is delegated to
// the NADO wallet; the key never touches this origin.
import { NadoDapp, rawToNado, nadoToRaw, randId, rematchId, randSecret, algHashn, ALG_P, _m, $, base, gate, canPay, orderCards, chainResultAlg, blocksToTime, lsLoad, lsSave, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, alertBar, notify, confirmingLabel, loadQR, resolveAliases, disp, share, shareInvite , installModes , playModes} from "./nadodapp.js?v=a192d4c0";
import { Practice } from "./practice.js?v=4b10cba6";      // free in-browser practice (play chips, no chain)

const CID = "dd84238f53bcefcc69f965fced5ea856";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" fill="none" aria-hidden="true">     <ellipse cx="18" cy="27" rx="10.5" ry="12.5" fill="#c8901a" stroke="#8a6209" stroke-width="1.6"/>     <circle cx="28" cy="24" r="13" fill="#e3b341" stroke="#b5810f" stroke-width="2.4"/>     <circle cx="28" cy="24" r="8.6" stroke="#a9760a" stroke-width="1.3" fill="none"/>     <text x="28" y="29" text-anchor="middle" font-size="13" font-weight="800" fill="#7a5606" font-family="system-ui">N</text></svg>';
const dapp = new NadoDapp({ cid: CID, app: "Coin Flip" });
const BLOCK_SECS = 6;

const LS_G = "nado_coinflip_games";
const gamesLoad = () => lsLoad(LS_G);
const gamesSave = (g) => lsSave(LS_G, g);
let active = null, lastGame = null;
const stageCache = {};     // gid -> {settled, ncom, stake}

// ---- the per-game secret (commit-reveal) ------------------------------------------------------------
// INVARIANT: a commitment is only ever submitted for a secret that is already in localStorage, because bet()
// writes it and READS IT BACK before calling open/join — a commitment whose secret was lost can never be
// revealed, and an unrevealed player forfeits the pot at the deadline.
// Keyed by game AND address, so two wallets in one browser never share (or overwrite) a secret.
const REVEAL_WINDOW = 600;               // must match execnode/games/coinflip.py REVEAL_WINDOW (display only)
const SKEY = (g) => "nado_coinflip_secret_" + g + "_" + (dapp.me || "");
function storedSecret(g) {
  try { const s = localStorage.getItem(SKEY(g)); return s ? BigInt(s) : null; } catch { return null; }
}
function ensureSecret(g) {               // existing secret (a retried open/join reuses it) or a fresh CSPRNG one
  let s = storedSecret(g);
  if (s == null) {
    s = randSecret() % ALG_P();          // a field element, exactly what the VM hashes (randSecret = crypto.getRandomValues)
    try { localStorage.setItem(SKEY(g), s.toString()); } catch {}
  }
  return storedSecret(g) === s ? s : null;   // null: this browser could not keep it — do not commit
}
const commitOf = (s) => algHashn([s]);   // == the contract's `hash r3 <- r1` (tests/test_coinflip_commit_reveal_...)
const hex = (v) => BigInt(v).toString(16);

const shortfallMsg = (need, have) => window.t("coinflip.shortfall",
  "Not enough NADO to join — this game stakes {need}, but your exec balance is {have}. Deposit at least {more} more NADO below, then join.",
  { need: rawToNado(need), have: rawToNado(have), more: rawToNado(need - have) });

// ---- reads: all DERIVED from the contract's storage maps ----------------------------------------
const allGids = (sto) => Object.keys(_m(sto, "nn"));
function gameFrom(sto, gid) {
  gid = String(gid); const nn = _m(sto, "nn")[gid] || 0;
  if (!nn) return { exists: false };
  const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid], settled = !!_m(sto, "sd")[gid], ws = _m(sto, "ws")[gid] || 0;
  const players = {};
  if (p1) players[p1] = { slot: 1 };
  if (p2) players[p2] = { slot: 2 };
  const g = { exists: true, stake: _m(sto, "st")[gid] || 0, pot: _m(sto, "pt")[gid] || 0, settled,
              ncom: nn, sh: _m(sto, "sh")[gid] || 0, players, id: Number(gid) };
  const cur = dapp.cursor;
  if (_m(sto, "md")[gid]) {             // commit-reveal game
    g.cr = true; g.dl = _m(sto, "dl")[gid] || 0;
    g.commits = { 1: _m(sto, "c1")[gid] || null, 2: _m(sto, "c2")[gid] || null };
    g.revealed = { 1: !!_m(sto, "v1")[gid], 2: !!_m(sto, "v2")[gid] };
    const s1 = _m(sto, "s1")[gid] || 0, s2 = _m(sto, "s2")[gid] || 0;
    const both = g.revealed[1] && g.revealed[2];
    const coin = both ? chainResultAlg(hex(s1), hex(s2), gid, 2) : null;
    if (settled) {
      if (ws) { g.winner_slot = ws; if (coin != null) g.result = coin; else g.forfeit = true; }
      else g.refunded = true;
    } else if (nn === 2 && both && coin != null) { g.result = coin; g.winner_slot = coin === 0 ? 1 : 2; g.ready = true; }
    else if (nn === 2 && cur != null && cur >= g.dl) {
      g.ready = true;
      if (g.revealed[1] || g.revealed[2]) { g.winner_slot = g.revealed[1] ? 1 : 2; g.forfeit = true; }
      else g.refunded = true;
    } else if (nn === 2 && cur != null) { g.revealOpen = true; g.revealIn = g.dl - cur; }
    return g;
  }
  if (settled && ws) { g.winner_slot = ws; g.result = ws === 1 ? 0 : 1; }
  else if (nn === 2 && cur != null && cur >= g.sh + 1) { const r = chainResultAlg(dapp.bh(g.sh), dapp.bh(g.sh + 1), gid, 2); if (r != null) { g.result = r; g.winner_slot = r === 0 ? 1 : 2; g.ready = true; } }
  else if (nn === 2 && cur != null) g.flipsIn = g.sh + 1 - cur;
  return g;
}
function lobbyFrom(sto) {
  return allGids(sto).map((gid) => {
    const nn = _m(sto, "nn")[gid], settled = !!_m(sto, "sd")[gid];
    return { game: gid, stake: _m(sto, "st")[gid] || 0, settled, ncom: nn,
             stage: settled ? "done" : (nn >= 2 ? "live" : "open") };
  });
}
function boardFrom(sto) {
  const stats = {};
  for (const gid of allGids(sto)) {
    if (!_m(sto, "sd")[gid]) continue;
    const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid], ws = _m(sto, "ws")[gid];
    if (!p1 || !p2 || !ws) continue;
    const stake = _m(sto, "st")[gid] || 0, win = ws === 1 ? p1 : p2, lose = ws === 1 ? p2 : p1;
    scoreBump(stats, win, stake); scoreBump(stats, lose, -stake);
  }
  return scoreSort(stats);
}
async function fetchGame(gid) { const sto = await dapp.storage(); return sto ? gameFrom(sto, gid) : null; }

// ---- actions -------------------------------------------------------------------------------------
function bet(gameId, stakeRaw, method) {   // method: "open" (slot 1) or "join" (slot 2)
  if (dapp.busy("bet", "gameId", gameId)) return notify(confirmingLabel());   // this open/join is already confirming
  if (!dapp.me) return dapp.signIn();   // the secret is keyed by address — it needs one first
  // the secret is stored (and read back) BEFORE the commitment leaves this page — see ensureSecret
  const secret = ensureSecret(gameId);
  if (secret == null) return alertBar(window.t("coinflip.noStorage", "This browser cannot store your game secret (private mode or storage blocked). Without it you could not reveal and would forfeit — use a normal window."));
  const g = gamesLoad();
  g[gameId] = { role: method, ts: Date.now(), bet: (g[gameId] || {}).bet, stake: stakeRaw.toString() }; gamesSave(g);
  active = gameId; render();
  const betDesc = method === "open"
    ? window.t("coinflip.openDesc", "open game #{id} · {amt} NADO", { id: gameId, amt: rawToNado(stakeRaw) })
    : window.t("coinflip.joinDesc", "join game #{id} · {amt} NADO", { id: gameId, amt: rawToNado(stakeRaw) });
  dapp.call(method, [gameId, commitOf(secret)], stakeRaw, betDesc, { gameId, phase: "bet" });
}
async function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) return alertBar(window.t("coinflip.enterStake", "Enter a stake (NADO)."));
  if (!canPay(dapp, raw, "Opening this game")) return;
  bet(randId(), raw, "open");
}
async function joinGame() {
  const gid = parseInt($("joinId").value, 10);
  if (!gid) return;
  const g = await fetchGame(gid);
  if (!g || !g.exists) return alertBar(dapp.whereIs("game", gid));
  if (g.settled || g.ncom >= 2) return alertBar(window.t("coinflip.fullOrSettled", "That game is full or already settled."));
  await dapp.refresh();
  const need = BigInt(g.stake);
  if (!canPay(dapp, need, "Joining this game")) { render(); return; }
  bet(gid, need, "join");
}
async function joinActive() {
  if (active == null || !lastGame || !lastGame.exists) return;
  await dapp.refresh();
  const need = BigInt(lastGame.stake);
  if (!canPay(dapp, need, "Joining this game")) { render(); return; }
  bet(active, need, "join");
}
function reopenGame() {   // retry an open that never landed (same id is still fresh)
  const L = gamesLoad()[active]; if (!L || L.role !== "open" || !L.stake) return;
  const raw = BigInt(L.stake);
  if (!canPay(dapp, raw, "Re-opening this game")) return;
  bet(active, raw, "open");
}
const settle = () => { if (dapp.busy("settle", "gameId", active)) return; dapp.call("settle", [active], null, window.t("coinflip.settleDesc", "settle game #{id}", { id: active }), { gameId: active, phase: "settle" }); };
// A flip resolves from BHASH(sh)/BHASH(sh+1); once sh leaves the node's hash ring the coin can never be
// read and BOTH stakes are locked forever. reclaim voids the game and refunds them. WHEN that is the right
// action is dapp.horizonVerdict()'s call, not this file's: the contract's 18000-block gate opens ~2000
// blocks before the hash prunes, and reclaiming inside that overlap makes the WINNER hand the loser a
// free refund. See dice.js. Manual only — never auto-fired, because a settle pays someone and a refund
// pays no one.
const HORIZON = 18000;                   // must match the gate in execnode/games/coinflip.py
const reclaimGame = () => { if (dapp.busy("settle", "gameId", active)) return; dapp.call("reclaim", [active], null, window.t("coinflip.reclaimDesc", "void stuck game #{id} — refund both stakes", { id: active }), { gameId: active, phase: "settle" }); };
// reveal(): disclose MY secret for the active commit-reveal game. Fired automatically once both players are in
// (maybeAutoReveal) and offered as a button; refused locally when this browser's secret does not open my
// commitment (it would only revert on chain).
function reveal() {
  const lg = lastGame, mine = lg && (lg.players || {})[dapp.me], s = storedSecret(active);
  if (!lg || !lg.cr || !mine || s == null) return;
  if (dapp.busy("reveal", "gameId", active)) return;
  if (String(commitOf(s)) !== String(lg.commits[mine.slot])) return alertBar(window.t("coinflip.secretMismatch", "The secret saved in this browser does not match your commitment for game #{id}. Reveal from the browser you staked with.", { id: active }));
  dapp.call("reveal", [active, s], null, window.t("coinflip.revealDesc", "reveal your secret · game #{id}", { id: active }), { gameId: active, phase: "reveal" });
}
// AUTO-REVEAL: not gated by the auto-collect opt-out — a reveal that does not land by the deadline forfeits the
// pot, so it fires whenever it is mine to do, retried every 45 s while it is still missing on chain.
const revealTried = new Map();
function maybeAutoReveal() {
  const lg = lastGame;
  if (active == null || !lg || !lg.cr || lg.settled || lg.ncom !== 2 || !lg.revealOpen) return;
  const mine = (lg.players || {})[dapp.me];
  if (!mine || lg.revealed[mine.slot] || storedSecret(active) == null || dapp.busy("reveal", "gameId", active)) return;
  const at = revealTried.get(active);
  if (at != null && Date.now() - at < 45000) return;
  revealTried.set(active, Date.now());
  reveal();
}
// AUTO-COLLECT the WINNER's pot once the flip is decided (shared SDK tick — opt-out slider, autoTried dedup)
function maybeAutoSettle() {
  if (active == null) return;
  const lg = lastGame;
  if (!lg || !lg.exists || lg.settled || lg.ncom !== 2 || !lg.ready) return;
  const mine = (lg.players || {})[dapp.me];
  // only auto-collect MY winnings — or, past the deadline with no reveal at all, my refunded stake
  if (!mine || (lg.winner_slot !== mine.slot && !lg.refunded)) return;
  // phase-scoped — see dice.js: only another settle may hold this one.
  dapp.autoCollect([{ g: active }], () => settle(), { phase: "settle" });
}
const cancelGame = () => { if (dapp.busy("cancel", "gameId", active)) return; dapp.call("cancel", [active], null, window.t("coinflip.cancelDesc", "cancel game #{id}", { id: active }), { gameId: active, phase: "cancel" }); };
async function rematch() {
  const stake = (lastGame && lastGame.exists) ? BigInt(lastGame.stake) : ((gamesLoad()[active] || {}).stake ? BigInt(gamesLoad()[active].stake) : null);
  if (!stake) return alertBar(window.t("coinflip.openNewPanel", "Open a new game from the panel above."));
  if (!canPay(dapp, stake, "The rematch")) return;
  const rgid = rematchId(active), rg = await fetchGame(rgid);
  bet(rgid, stake, (rg && rg.exists && rg.ncom >= 1 && !rg.settled) ? "join" : "open");
}

let stuckGame = false;   // the active flip is past the horizon AND its hash is gone (dapp.horizonVerdict)
async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    // release the click guard the instant the effect is on-chain — MUST run with sto (tip-advance alone
    // no longer clears the guard): bet = my address committed, settle = flip recorded, cancel = game gone.
    dapp.settleInflight((f) => {
      const g = String(f.gameId);
      if (f.phase === "bet") return _m(sto, "p1")[g] === dapp.me || _m(sto, "p2")[g] === dapp.me;
      if (f.phase === "settle") return !!_m(sto, "sd")[g];
      if (f.phase === "reveal") { const me = dapp.me; return !!_m(sto, "sd")[g] || (_m(sto, "p1")[g] === me ? !!_m(sto, "v1")[g] : !!_m(sto, "v2")[g]); }
      if (f.phase === "cancel") return !_m(sto, "p1")[g] || !!_m(sto, "sd")[g];
      return false;
    });
    for (const gid of allGids(sto)) stageCache[gid] = { settled: !!_m(sto, "sd")[gid], ncom: _m(sto, "nn")[gid] || 0, stake: _m(sto, "st")[gid] || 0 };
    // fetch block hashes to resolve a LEGACY game's flip client-side (a commit-reveal game needs none)
    if (active != null) {
      const nn = _m(sto, "nn")[String(active)] || 0, sh = _m(sto, "sh")[String(active)] || 0, cur = dapp.cursor;
      const legacy = !_m(sto, "md")[String(active)];
      // FAST (provisional) hashes: the flip is PUBLIC randomness the settle re-validates on-chain, so a
      // reorg can only revert the settling tx visibly — never flip a coin silently. Result shows in one
      // block (~6-18s) instead of waiting ~90s for finality (same rule Farkle's dice use).
      if (legacy && nn === 2 && !_m(sto, "sd")[String(active)] && cur != null && cur >= sh + 1) await dapp.blockHashes([sh, sh + 1], { fast: true });
      lastGame = gameFrom(sto, active);
      // Only ask about a flip that is BOTH unresolvable here and past the contract's gate — the SDK makes
      // the final call and refuses to say "refund" on a transient miss.
      stuckGame = false;
      if (lastGame && lastGame.exists && !lastGame.cr && !lastGame.settled && lastGame.ncom === 2 && !lastGame.ready
          && lastGame.sh && dapp.cursor != null && dapp.cursor - lastGame.sh > HORIZON) {
        stuckGame = (await dapp.horizonVerdict(lastGame.sh, HORIZON)) === "refund";
      }
    }
    const gg = gamesLoad(); let pruned = false;
    for (const id of Object.keys(gg)) if (!stageCache[id] && Date.now() - (gg[id].ts || 0) > 600000) { delete gg[id]; pruned = true; }
    if (pruned) gamesSave(gg);
    renderLobby(lobbyFrom(sto)); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastGame && lastGame.players ? Object.keys(lastGame.players) : []));
  render();
  maybeAutoReveal();
  maybeAutoSettle();
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, window.t("coinflip.noFinished", "No finished games yet — be the first on the board."));
function renderLobby(games) {
  const el = $("lobbyList"); if (!el) return;
  const rank = { open: 0, live: 1, done: 2 }, tag = { open: "⏳", live: "▶", done: "✓" },
    verb = { open: window.t("coinflip.verbJoin", " · join"), live: window.t("coinflip.verbWatch", " · watch"), done: "" };
  const shown = (games || []).slice().sort((a, b) => rank[a.stage] - rank[b.stage]).slice(0, 24);
  if (!shown.length) { el.innerHTML = '<span class="dim">' + window.t("coinflip.noGamesOpenAbove", "No games yet — open one above.") + '</span>'; return; }
  el.innerHTML = shown.map((g) => '<button class="chip ' + g.stage + '" data-lg="' + g.game + '">' + tag[g.stage] + " #" + g.game + " · " + rawToNado(g.stake) + " NADO" + verb[g.stage] + "</button>").join(" ");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { active = parseInt(b.dataset.lg, 10); $("joinId").value = b.dataset.lg; refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => dapp.exec, render);   // play for stakes: % of your playable balance
  stickyInputs(dapp, ['stakeAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("joinId").oninput = () => render();
  $("btnSettle").onclick = settle;
  $("btnReveal").onclick = reveal;
  dapp.wireAutoCollect();
  $("btnShare").onclick = () => {
    const forPart = (lastGame && lastGame.exists) ? window.t("coinflip.shareFor", "for {amt} NADO ", { amt: rawToNado(lastGame.stake) }) : "";
    share(base() + "/?game=" + active, window.t("coinflip.shareMsg", "Flip me {for}on NADO — join game #{id}:", { for: forPart, id: active }), $("btnShare"));
  };
  $("btnRematch").onclick = rematch;
  $("btnJoinActive").onclick = joinActive;
  $("btnCancel").onclick = cancelGame;
  $("btnReopen").onclick = reopenGame;
}
const badge = (s) => s === "confirmed" ? '<span class="b ok">' + window.t("coinflip.confirmed", "confirmed ✓") + '</span>' : s === "pending" ? '<span class="b pend">' + window.t("coinflip.pending", "pending…") + '</span>' : '<span class="b dimb">—</span>';
var render = function render() {
  dapp.reflectUrl("game", active);   // address bar = the shareable link to the selected game
  dapp.syncPctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, dapp.exec);
  const rn = $("revealNote");   // re-set every render so a language switch re-localizes it
  if (rn) rn.textContent = window.t("coinflip.revealNote", "Your browser keeps a secret for each game and reveals it automatically once both players are in. Keep this browser until it has revealed: the reveal window is {t}, and a player who does not reveal in time forfeits the pot.", { t: blocksToTime(REVEAL_WINDOW) });
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankroll: signedIn, activeGame: active != null });
  const jid = ($("joinId").value || "").trim();
  const lgv = lastGame || {};
  let iAmIn = false, stageJoinable = true, needStake = null;
  if (jid && String(active) === jid && lgv.exists) { iAmIn = !!(lgv.players && lgv.players[dapp.me]); stageJoinable = !lgv.settled && lgv.ncom < 2; needStake = BigInt(lgv.stake || 0); }
  else if (jid) { const js = stageCache[jid]; if (js) { stageJoinable = !js.settled && js.ncom < 2; needStake = js.stake != null ? BigInt(js.stake) : null; } }
  const canAfford = !(signedIn && needStake != null && dapp.exec < needStake);
  const joiningById = dapp.busy("bet", "gameId", jid);
  const joinable = !!jid && !iAmIn && stageJoinable && canAfford && !joiningById;
  $("btnJoin").disabled = (!!jid && !joinable) || joiningById;
  $("btnJoin").textContent = joiningById ? window.t("coinflip.confirming", "⏳ Confirming…") : window.t("coinflip.join", "Join");
  $("btnJoin").classList.toggle("pulse", joinable && signedIn);
  $("btnSignIn").classList.toggle("pulse", joinable && !signedIn);
  const jh = $("joinHint");
  const showShortfall = !!jid && signedIn && !iAmIn && stageJoinable && needStake != null && dapp.exec < needStake;
  if (jh) { jh.textContent = showShortfall ? shortfallMsg(needStake, dapp.exec) : ""; jh.classList.toggle("hidden", !showShortfall); }
  const g = gamesLoad();
  const ids = Object.keys(g).sort((a, b) => g[b].ts - g[a].ts).slice(0, 8);
  $("recent").innerHTML = ids.length
    ? ids.map((id) => {
        const st = stageCache[id]; let cls = "", tag = "", title = "";
        if (st) { if (st.settled) { cls = " done"; tag = "✓ "; } else if (st.ncom >= 2) { cls = " live"; tag = "▶ "; } else { cls = " open"; tag = "⏳ "; } }
        else { cls = " pending"; tag = "⏳ "; title = ' title="' + window.t("coinflip.pendingTitle", "still confirming on-chain — your game hasn't vanished") + '"'; }
        return '<button class="chip' + cls + '" data-g="' + id + '"' + title + ">" + tag + "#" + id + " · " + rawToNado(g[id].stake || "0") + "</button>";
      }).join(" ")
    : '<span class="dim">' + window.t("coinflip.noGamesYet", "No games yet.") + '</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { active = parseInt(b.dataset.g, 10); $("joinId").value = String(active); notify(window.t("coinflip.gameSelected", "Game #{id} selected.", { id: active })); refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
  renderActive();
}
function renderActive() {
  if (active == null) return;
  const lg = lastGame || {}, local = gamesLoad()[active] || {}, mine = (lg.players || {})[dapp.me];
  $("gameId").textContent = "#" + active;
  shareInvite("game", active, window.t("coinflip.inviteText", "Flip me on NADO — join coin flip #{id}:", { id: active }));
  $("pot").textContent = lg.exists ? rawToNado(lg.pot) + " NADO" : "—";
  $("stakeShown").textContent = lg.exists ? rawToNado(lg.stake) + " NADO" : (local.stake ? rawToNado(local.stake) + " NADO" : "—");
  $("gStatus").textContent = lg.exists ? (window.t("coinflip.inCount", "{n}/2 in", { n: lg.ncom }) + (lg.settled ? window.t("coinflip.stSettled", " · settled") : lg.ncom === 2 ? (lg.cr ? window.t("coinflip.stRevealing", " · revealing") : window.t("coinflip.stFlipping", " · ⚡ flipping")) : window.t("coinflip.stWaiting", " · waiting"))) : dapp.whereIs("game", active, local.ts);
  const pl = lg.players || {};
  const byslot = Object.keys(pl).sort((a, b) => pl[a].slot - pl[b].slot);
  let playersHtml = byslot.map((a) => '<span class="chip">' + (a === dapp.me ? window.t("coinflip.you", "you ") : "") + disp(a) + window.t("coinflip.slotN", " · slot {n}", { n: pl[a].slot }) + "</span>").join(" ");
  const myJoinPending = !mine && local.bet === "pending" && lg.exists && lg.ncom < 2;
  if (myJoinPending) playersHtml += ' <span class="chip" style="opacity:.75">' + window.t("coinflip.youConfirming", "you · confirming…") + '</span>';
  $("players").innerHTML = playersHtml || '<span class="dim">' + window.t("coinflip.noPlayers", "no players yet") + '</span>';
  const showMine = !!mine || (local.bet === "pending" && !lg.settled);
  $("myBet").classList.toggle("hidden", !showMine);
  renderReveal(lg, mine);
  if (!mine && local.bet === "pending" && lg.exists && lg.ncom >= 2)
    $("myBet").innerHTML = window.t("coinflip.yourBet", "Your bet:") + ' <span class="b" style="background:rgba(248,81,73,.16);color:var(--danger)">' + window.t("coinflip.betDidntLand", "didn't land — game filled first (your stake is safe)") + '</span>';
  else $("myBet").innerHTML = window.t("coinflip.yourBet", "Your bet:") + " " + badge(mine ? "confirmed" : local.bet);
  // actions
  const resolved = lg.result === 0 || lg.result === 1;
  const forfeit = !resolved && lg.forfeit && lg.winner_slot, refund = !resolved && lg.refunded;
  $("btnSettle").classList.toggle("hidden", !(lg.exists && !lg.settled && lg.ncom === 2 && lg.ready));
  // The stuck-flip escape appears ONLY once the coin is provably unreadable (see reclaimGame): while
  // lg.ready holds, the flip still settles and someone still wins, so the refund must stay out of sight.
  const rb = $("btnRefundStuck");
  if (rb) {
    rb.classList.toggle("hidden", !stuckGame);
    if (stuckGame) {
      rb.textContent = window.t("coinflip.refundStuck", "↩ Void stuck game #{id} — refund both stakes", { id: lg.id });
      rb.onclick = reclaimGame;
    }
  }
  if (lg.ready) $("btnSettle").textContent = lg.refunded ? window.t("coinflip.refundBoth", "Refund both stakes")
    : (mine && lg.winner_slot === mine.slot) ? window.t("coinflip.collectPot", "💰 Collect the pot") : window.t("coinflip.payWinner", "Pay out the winner");
  $("btnCancel").classList.toggle("hidden", !(dapp.me && lg.exists && !lg.settled && lg.ncom === 1 && mine && mine.slot === 1));
  if (mine) dapp.clearInflight();                              // our seat is on-chain now — stop "confirming…"
  const joining = dapp.busy("bet", "gameId", active);          // just clicked join/open, not yet confirmed
  const canSeeJoinActive = !!(dapp.me && lg.exists && !lg.settled && lg.ncom < 2 && !mine && !joining);
  const needActive = lg.exists ? BigInt(lg.stake || 0) : 0n, shortActive = canSeeJoinActive && dapp.exec < needActive;
  $("btnJoinActive").classList.toggle("hidden", !(canSeeJoinActive || joining));
  $("btnJoinActive").disabled = shortActive || joining;
  $("btnJoinActive").classList.toggle("pulse", canSeeJoinActive && !shortActive && !joining);
  $("btnJoinActive").textContent = joining ? window.t("coinflip.joiningConfirm", "⏳ Joining — confirming on-chain…") : window.t("coinflip.joinThisGame", "Join this game");
  const jah = $("joinActiveHint"); if (jah) { jah.textContent = shortActive ? shortfallMsg(needActive, dapp.exec) : ""; jah.classList.toggle("hidden", !shortActive); }
  $("btnRematch").classList.toggle("hidden", !lg.settled);
  $("btnReopen").classList.toggle("hidden", !(local.role === "open" && local.stake && !lg.exists && local.ts && Date.now() - local.ts > 120000));
  // coin
  const coin = $("coin");
  if (resolved) {
    coin.className = "coin " + (lg.result === 0 ? "heads" : "tails"); coin.textContent = lg.result === 0 ? "H" : "T";
    const iWon = mine && lg.winner_slot === mine.slot;
    const face = lg.result === 0 ? window.t("coinflip.heads", "HEADS") : window.t("coinflip.tails", "TAILS");
    const outcome = mine
      ? (iWon ? window.t("coinflip.youWon", "you WON {amt} NADO 🎉", { amt: rawToNado(BigInt(lg.stake) * 2n) }) : window.t("coinflip.youLost", "you lost"))
      : window.t("coinflip.slotWon", "slot {n} won", { n: lg.winner_slot });
    const tail = lg.settled ? "" : window.t("coinflip.collectBelow", " · collect below");
    $("result").textContent = face + " — " + outcome + tail;
  } else if (forfeit || refund) {
    coin.className = "coin"; coin.textContent = "–";
    const iWon = forfeit && mine && lg.winner_slot === mine.slot;
    const msg = refund ? window.t("coinflip.noReveals", "Nobody revealed in time — both stakes are refunded")
      : mine ? (iWon ? window.t("coinflip.wonForfeit", "Your opponent did not reveal in time — you WON {amt} NADO", { amt: rawToNado(BigInt(lg.stake) * 2n) })
                     : window.t("coinflip.lostForfeit", "You did not reveal in time — the pot went to your opponent"))
      : window.t("coinflip.slotWonForfeit", "slot {n} won — the other player did not reveal", { n: lg.winner_slot });
    $("result").textContent = msg + (lg.settled ? "" : window.t("coinflip.collectBelow", " · collect below"));
  } else {
    coin.className = "coin spin"; coin.textContent = "?";
    $("result").textContent = (lg.ncom === 2 && lg.cr) ? window.t("coinflip.bothInReveal", "Both in — revealing secrets ({n}/2 revealed)", { n: (lg.revealed[1] ? 1 : 0) + (lg.revealed[2] ? 1 : 0) })
      : lg.ncom === 2 ? window.t("coinflip.bothInFlips", "Both in — the chain flips in {t}", { t: lg.flipsIn != null ? blocksToTime(lg.flipsIn) : "…" })
      : myJoinPending ? window.t("coinflip.joinConfirming", "Your join is confirming on-chain (~1 min)…") : window.t("coinflip.waitingSecond", "Waiting for a second player…");
  }
}

// the reveal panel: my reveal state, the deadline, and the forfeit rule — always visible while it matters
function renderReveal(lg, mine) {
  const el = $("myReveal"), btn = $("btnReveal");
  const live = !!(lg.cr && lg.ncom === 2 && !lg.settled);
  el.classList.toggle("hidden", !live);
  const myTurn = live && lg.revealOpen && mine && !lg.revealed[mine.slot];
  const revealing = dapp.busy("reveal", "gameId", active);
  btn.classList.toggle("hidden", !myTurn);
  btn.disabled = revealing || storedSecret(active) == null;
  btn.textContent = revealing ? window.t("coinflip.revealing", "Revealing — confirming on-chain…") : window.t("coinflip.revealBtn", "Reveal my secret");
  if (!live) { el.innerHTML = ""; return; }
  const st = (n) => lg.revealed[n] ? window.t("coinflip.revDone", "revealed") : window.t("coinflip.revWaiting", "not yet");
  let html = window.t("coinflip.revState", "Reveals — slot 1: {a} · slot 2: {b}", { a: st(1), b: st(2) });
  html += "<br>" + (lg.revealOpen
    ? window.t("coinflip.revDeadline", "Reveal window closes in {t} (block {dl}).", { t: blocksToTime(lg.revealIn), dl: lg.dl })
    : window.t("coinflip.revClosed", "The reveal window closed at block {dl}.", { dl: lg.dl }));
  html += "<br>" + window.t("coinflip.forfeitRule", "If only one player reveals in time, that player takes the whole pot. If neither does, both stakes are refunded.");
  if (mine && !lg.revealed[mine.slot] && lg.revealOpen && storedSecret(active) == null)
    html += '<br><span class="warn">' + window.t("coinflip.noSecretHere", "This browser does not hold your secret for game #{id} — reveal from the browser you staked with before the window closes, or your opponent takes the pot.", { id: active }) + "</span>";
  el.innerHTML = html;
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.gameId != null) active = pend.gameId;
  if (ok && pend && pend.phase === "bet") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].bet = "pending"; gamesSave(g); } }
  dapp.showReturn(pend, ok, err, { bet: window.t("coinflip.betSubmitted", "Bet submitted — confirming…"), settle: window.t("coinflip.settling", "Settling…") });
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("coinflip.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR(); orderCards(["activeGame","lobby","play","practice","walletcard","bankroll","scoreboard"]);

// ONE mode picker, from the SDK — the same control in every game. Practice used to be a card parked
// below the staked game with no way to switch to it; now it is a mode you choose, and ?mode=practice
// links straight to it.
const modes = installModes(dapp, {
  modes: playModes({ icon: "🪙", play: ["lobby", "play", "scoreboard"] }),
});
// mode gating layers OVER the game's own render, which gates cards by sign-in/table state
render = modes.wrap(render);   // re-apply the mode gating after every render
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (active == null) active = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();

// ---- PRACTICE MODE (free, fully in-browser — play chips, local RNG, nothing on-chain) -------------------
// The real game is PvP: two equal stakes, winner takes the whole pot — a fair 50/50 with NO house edge.
// Practice mirrors that as double-or-nothing vs Math.random (nothing is at stake, so no beacon needed).
const prac = new Practice("coinflip");
let pStreak = 0, pFlipping = false;
function pracStrip() { prac.strip($("pStrip"), { chips: true, onReset: pracStrip }); }
function pracFlip(pick) {   // 0 = heads, 1 = tails — same faces as the chain's parity flip
  if (pFlipping) return;
  const bet = parseInt($("pStake").value, 10) || 0;
  if (!prac.canBet(bet, notify)) return;
  pFlipping = true;
  prac.addChips(-bet);
  $("pCoin").className = "coin spin"; $("pCoin").textContent = "?";
  $("pResult").innerHTML = "";
  pracStrip();
  setTimeout(() => {
    pFlipping = false;
    const r = Math.random() < 0.5 ? 0 : 1;
    const win = r === pick;
    if (win) prac.addChips(bet * 2);   // winner takes the pot: your stake back + the same again (2×)
    pStreak = win ? pStreak + 1 : 0;
    $("pCoin").className = "coin " + (r === 0 ? "heads" : "tails"); $("pCoin").textContent = r === 0 ? "H" : "T";
    const face = r === 0 ? window.t("coinflip.heads", "HEADS") : window.t("coinflip.tails", "TAILS");
    $("pResult").innerHTML = win
      ? '<span style="color:var(--accent2);font-weight:800">🪙 ' + face + " — " + window.t("sdk.prFlipWin", "you WON +{n} play chips! 🎉", { n: bet }) + "</span>"
      : '<span style="color:var(--danger);font-weight:800">🪙 ' + face + " — " + window.t("sdk.prFlipLose", "lost {n} play chips.", { n: bet }) + "</span>";
    $("pStreak").textContent = window.t("sdk.prStreak", "Win streak: {n}", { n: pStreak });
    pracStrip();
  }, 700);
}
if ($("pStrip")) {
  $("pHeads").onclick = () => pracFlip(0);
  $("pTails").onclick = () => pracFlip(1);
  $("pStreak").textContent = window.t("sdk.prStreak", "Win streak: {n}", { n: 0 });
  pracStrip();
}

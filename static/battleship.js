// battleship.js — NADO Battleship: trustless hidden-board naval combat on the execution layer, on the shared
// SDK (nadodapp.js). Your fleet never leaves your browser: you commit a salted MERKLE-SUM root of your 100-cell
// board; every shot is answered by revealing just that one cell + its 7-node path, which the contract checks
// against your root — so nobody can lie about a hit/miss and nobody can hide ships (the same proof binds the
// ship count to exactly 17). 17 proven hits sinks the enemy fleet and takes the pot. No oracle, no reveal, no
// oracle beyond the math — field-native alghash, byte-identical to the zkVM contract's in-VM HASH
// (execnode/games/battleship.py; every method call is STARK-provable). See tests/test_games_e2e.py.
import { NadoDapp, rawToNado, nadoToRaw, randId, rematchId, algHashn, ALG_P, _m, $, base, gate, canPay, alertBar, notify, okBar,
         hoist, orderCards, lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore,
         scoreBump, scoreSort, recentChips, statusLabel, inviteGate, loadQR, drawQR, resolveAliases, disp, share, shareInvite,
         blocksToTime } from "./nadodapp.js";
import { Practice } from "./practice.js";   // free in-browser practice vs the computer

const CID = "9c3d01b6b70f507ecc0bbf75b0615940";   // execnode/games/battleship.py (zkVM, nonce "a5")
const dapp = new NadoDapp({ cid: CID, app: "Battleship" });
const N = 10, CELLS = 100, SHIPS = 17, WINDOW = 600, BLOCK_SECS = 6;
const FLEET = [5, 4, 3, 3, 2];                 // ship lengths (17 cells)
const LS_G = "nado_bs_games";                  // gameId -> { role, board:[128], salts:[128 dec-strings], stake, ts }
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---- merkle client (MUST byte-match the zkVM contract, execnode/games/battleship.py):
//   salt(seed,c) = H(1, seed, c) · leaf(c,ship,salt) = H(2, salt, 2c+ship) · node(L,R,s) = H(3, L, R, s)
// where H = the in-VM alghash (field-native, domain-tagged, ordered absorption = position-binding). ----
const TAG_SALT = 1n, TAG_LEAF = 2n, TAG_NODE = 3n;
const bitrev7 = (x) => { let r = 0; for (let i = 0; i < 7; i++) r = (r << 1) | ((x >> i) & 1); return r; };
function buildTree(board, salts) {                     // board:128 (0/1), salts:128 (BigInt) -> {root, levels}
  const leaves = new Array(128);
  for (let c = 0; c < 128; c++)
    leaves[bitrev7(c)] = { h: algHashn([TAG_LEAF, salts[c], BigInt(2 * c + board[c])]), s: board[c] };
  const levels = [leaves]; let cur = leaves;
  while (cur.length > 1) {
    const nxt = [];
    for (let i = 0; i < cur.length; i += 2) {
      const s = cur[i].s + cur[i + 1].s;
      nxt.push({ h: algHashn([TAG_NODE, cur[i].h, cur[i + 1].h, BigInt(s)]), s });
    }
    levels.push(nxt); cur = nxt;
  }
  return { root: cur[0].h, levels };
}
function cellProof(tree, cell) {                       // -> [sib0, ss0, ... sib6, ss6]
  let pos = bitrev7(cell); const out = [];
  for (let L = 0; L < 7; L++) { const sib = tree.levels[L][pos ^ 1]; out.push(sib.h, sib.s); pos >>= 1; }
  return out;
}
// Salts are derived from ONE random seed (salt[c]=H(1,seed,c)) so a reveal-at-claim carries just the seed,
// which the contract regenerates identically. Revealing a single cell's salt during a move can't leak the seed.
const randSeed = () => { let h = "0x"; for (const x of crypto.getRandomValues(new Uint8Array(8))) h += x.toString(16).padStart(2, "0"); return BigInt(h) % ALG_P(); };
const saltsFromSeed = (seed) => Array.from({ length: 128 }, (_, c) => algHashn([TAG_SALT, seed, BigInt(c)]));
// the placed fleet as [[anchor,orient]x5] in FLEET order — what claim() reveals (orient: 0 horiz, 1 vert)
const fleetSpec = () => ships.map((s) => [s.cells[0], (s.cells.length > 1 && s.cells[1] - s.cells[0] === 10) ? 1 : 0]);

// ---- fleet placement: the standard fleet as DISCRETE SHIPS you place (contiguous, non-overlapping, in 10x10).
// The classic Milton-Bradley fleet exactly matches FLEET [5,4,3,3,2]. Placement is purely a client concern —
// the 128-cell occupancy board it produces feeds the SAME merkle commitment, so the contract is untouched. ----
const SHIP_KEYS = ["carrier", "battleship", "cruiser", "submarine", "destroyer"];   // parallel to FLEET
const SHIP_EN = ["Carrier", "Battleship", "Cruiser", "Submarine", "Destroyer"];
const newFleet = () => FLEET.map((len, i) => ({ i, len, key: SHIP_KEYS[i], cells: null }));   // cells:null = unplaced
// the cells a ship of `len` occupies anchored (top-left) at `cell`, orientation h (horizontal); null if off-grid
function shipCells(cell, len, h) {
  const r = Math.floor(cell / N), c = cell % N;
  if (h ? c + len > N : r + len > N) return null;
  const out = []; for (let k = 0; k < len; k++) out.push(h ? cell + k : cell + k * N);
  return out;
}
const occupiedCells = (fl, exceptI) => { const s = new Set(); for (const sh of fl) if (sh.cells && sh.i !== exceptI) for (const c of sh.cells) s.add(c); return s; };
// place ship slot `idx` anchored at `cell` in orientation `h`; true on success (in-bounds + no overlap)
function placeAt(fl, idx, cell, h) {
  const cells = shipCells(cell, fl[idx].len, h); if (!cells) return false;
  const occ = occupiedCells(fl, idx); if (cells.some((c) => occ.has(c))) return false;
  fl[idx].cells = cells; return true;
}
const shipAt = (fl, cell) => fl.find((s) => s.cells && s.cells.includes(cell));
const firstUnplaced = (fl) => { const s = fl.find((x) => !x.cells); return s ? s.i : -1; };
const boardOf = (fl) => { const b = new Array(128).fill(0); for (const s of fl) if (s.cells) for (const c of s.cells) b[c] = 1; return b; };
function randFleetShips() {
  const fl = newFleet();
  for (const s of fl) for (let t = 0; t < 800; t++) {
    const h = Math.random() < 0.5, r = Math.floor(Math.random() * (h ? N : N - s.len + 1)), c = Math.floor(Math.random() * (h ? N - s.len + 1 : N));
    if (placeAt(fl, s.i, r * N + c, h)) break;
  }
  return fl;
}
const shipCount = (b) => { let n = 0; for (let i = 0; i < CELLS; i++) n += b[i]; return n; };
const coord = (cell) => "ABCDEFGHIJ"[Math.floor(cell / N)] + (cell % N + 1);

// ---- reads (battleship storage schema) -----------------------------------------------------------
function gameFrom(sto, g) {
  g = String(g); const p1 = _m(sto, "p1")[g];
  if (!p1) return { exists: false };
  const gm = { exists: true, id: Number(g), p1, p2: _m(sto, "p2")[g] || null, stake: String(_m(sto, "st")[g] || 0),
    pot: Number(_m(sto, "pt")[g] || 0), nn: Number(_m(sto, "nn")[g] || 0), sd: !!_m(sto, "sd")[g],
    pc: Number(_m(sto, "pc")[g] || 0), pex: !!_m(sto, "pex")[g], pf: Number(_m(sto, "pf")[g] || 0), tf: Number(_m(sto, "tf")[g] || 0),
    h1: Number(_m(sto, "h1")[g] || 0), h2: Number(_m(sto, "h2")[g] || 0), wr: Number(_m(sto, "wr")[g] || 0),
    dl: Number(_m(sto, "dl")[g] || 0), dc: !!_m(sto, "dc")[g], cd: Number(_m(sto, "cd")[g] || 0) };
  gm.mineSlot = dapp.me === gm.p1 ? 1 : dapp.me === gm.p2 ? 2 : 0;
  gm.over = gm.sd || gm.dc;                              // dc = winner decided (pot escrowed) · sd = pot paid out
  // FIRE/ANSWER model: pex=a shot awaits an answer, pf=who fired it, tf=whose turn to fire when nothing pending.
  gm.myTurn   = gm.nn === 2 && !gm.over && !gm.pex && gm.tf === gm.mineSlot;                 // my turn to FIRE
  gm.awaiting = gm.nn === 2 && !gm.over && gm.pex && gm.pf === gm.mineSlot;                  // my shot awaits their answer
  gm.toAnswer = gm.nn === 2 && !gm.over && gm.pex && gm.pf !== 0 && gm.pf !== gm.mineSlot;   // I must answer their shot
  return gm;
}
const allGids = (sto) => Object.keys(_m(sto, "p1"));
async function fetchGame(g) { const sto = await dapp.storage(); return sto ? gameFrom(sto, g) : null; }
const firedAt = (sto, slot, g, cell) => !!_m(sto, slot === 1 ? "fd1" : "fd2")[Number(g) * 100 + Number(cell)];
const resultAt = (sto, slot, g, cell) => Number(_m(sto, slot === 1 ? "rs1" : "rs2")[Number(g) * 100 + Number(cell)] || 0);   // 0 none · 1 miss · 2 hit
const myBoard = (g) => { const r = load(LS_G)[g]; return r && r.board ? { board: r.board, salts: r.salts.map((s) => BigInt(s)), seed: r.seed != null ? BigInt(r.seed) : null, spec: r.spec || null } : null; };

// ---- state ---------------------------------------------------------------------------------------
let lastSto = null, activeGame = null, lastGame = null, target = null;
// APPEND-ONLY optimistic shot views (keyed by game id). A signed shot shows the instant you fire and NEVER
// un-renders — the chain only CONFIRMS it (for the hit/miss result + payout). A provisional-tip wobble/rollback
// can drop a cell from the raw storage for a poll; we UNION chain state into these and never shrink, so nothing
// blips back and forth. myFired = my shots at the enemy · myRes = their proven results · oppFired = enemy shots at me.
let myFired = {}, myRes = {}, oppFired = {};
const setOf = (m, g) => m[g] || (m[g] = new Set());
function ingestShots(sto, g) {   // fold the chain's confirmed shots into the local views (union, monotonic)
  if (!sto || g == null) return;
  const gm = gameFrom(sto, g); if (!gm.exists || !gm.mineSlot) return;
  const opp = gm.mineSlot === 1 ? 2 : 1, mF = setOf(myFired, g), oF = setOf(oppFired, g), mR = myRes[g] || (myRes[g] = {});
  for (let c = 0; c < CELLS; c++) {
    if (firedAt(sto, gm.mineSlot, g, c)) mF.add(c);
    if (firedAt(sto, opp, g, c)) oF.add(c);
    const r = resultAt(sto, gm.mineSlot, g, c); if (r) mR[c] = r;
  }
}
let ships = randFleetShips();          // the fleet being placed (starts as a valid random layout)
let placing = boardOf(ships);          // 128-cell 0/1 board derived from `ships` — what commit() hashes
let selShip = 0;                       // ship slot the tray has "armed" for the next tap-to-place
let horiz = true;                      // placement orientation (↔ / ↕)
const syncFleet = () => { placing = boardOf(ships); };

// ---- actions -------------------------------------------------------------------------------------
function commit() { const board = placing.slice(), seed = randSeed(), salts = saltsFromSeed(seed), spec = fleetSpec(); return { root: buildTree(board, salts).root, board, salts, seed, spec }; }
function saveBoard(g, role, board, salts, stake, seed, spec) { const G = load(LS_G); G[g] = { role, board, salts: salts.map((s) => s.toString()), seed: seed.toString(), spec, stake: String(stake), ts: Date.now() }; save(LS_G, G); }
function openGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) return alertBar(window.t("bs.enterStake", "Enter your stake in NADO — your opponent matches it, winner takes both."));
  if (shipCount(placing) !== SHIPS) return alertBar(window.t("bs.placeFleet", "Place your whole fleet first (all {n} cells).", { n: SHIPS }));
  if (!canPay(dapp, raw, window.t("bs.whatOpen", "Opening this game"))) return;
  const g = randId(), { root, board, salts, seed, spec } = commit();
  saveBoard(g, 1, board, salts, raw, seed, spec); activeGame = g;
  dapp.call("open", [g, root], raw, "open battleship #" + g + " · stake " + rawToNado(raw) + " NADO", { game: g, phase: "open" });
}
async function joinGame() {
  const gm = lastGame; if (!gm || !gm.exists) { if (gm) dapp.clearInvite(); return; }
  if (gm.nn !== 1) { dapp.clearInvite(); return; }
  if (shipCount(placing) !== SHIPS) return alertBar(window.t("bs.placeFleet", "Place your whole fleet first (all {n} cells).", { n: SHIPS }));
  const stake = BigInt(gm.stake);
  if (!canPay(dapp, stake, window.t("bs.whatJoin", "Joining this game"))) return;
  dapp.clearInvite();
  const { root, board, salts, seed, spec } = commit();
  saveBoard(activeGame, 2, board, salts, gm.stake, seed, spec);
  dapp.call("join", [activeGame, root], stake, "join battleship #" + activeGame + " · " + rawToNado(stake) + " NADO stake", { game: activeGame, phase: "join" });
}
// am I looking at someone else's OPEN game that I can join? (drives the setup button's open-vs-join behaviour)
function joinableActive() { const gm = lastGame; return !!(gm && gm.exists && gm.nn === 1 && gm.mineSlot === 0 && dapp.me); }
function fire() {
  const gm = lastGame; if (!gm || !gm.myTurn) return alertBar(window.t("bs.notYourTurn", "It's not your turn."));
  if (dapp.busy("fire", "game", activeGame)) return;   // a shot is already in flight — never double-fire (the old dupes reverted)
  if (target == null) return alertBar(window.t("bs.pickTarget", "Tap an enemy cell to aim, then Fire."));
  if (setOf(myFired, activeGame).has(target)) return alertBar(window.t("bs.already", "You already fired there — pick another cell."));
  const t = target; target = null;
  setOf(myFired, activeGame).add(t);   // OPTIMISTIC: paint the shot now; it never blips out while the chain confirms
  render();
  // no proof — the RESULT comes from the enemy's answer() (auto-submitted by their client), so you see hit/miss fast
  dapp.call("fire", [activeGame, t], null, "fire at " + coord(t) + " · battleship #" + activeGame, { game: activeGame, phase: "fire", shot: t });
}
// as the player fired upon, AUTO-reveal the result of the enemy's pending shot against my board (background-signed,
// value-free) — so my opponent sees hit/miss within ~1 block instead of waiting for me to take a turn.
// auto-action guard: a per-game COOLDOWN (not a permanent flag) so we never double-submit, but ALSO never wedge —
// if an action fired against provisional state that then reorged, it retries after the cooldown. (Money is safe
// regardless: settlement reads the FINALIZED exec state, which can't roll back; this is purely to un-stick the UI.)
const RETRY_MS = 30000, answerAt = {}, claimAt = {};
const recently = (m, g) => m[g] != null && Date.now() - m[g] < RETRY_MS;
function autoAnswer(sto) {
  if (!sto || !dapp.me) return;
  for (const g of Object.keys(load(LS_G))) {
    const gm = gameFrom(sto, g); if (!gm.toAnswer) { delete answerAt[g]; continue; }
    const mine = myBoard(g); if (!mine) continue;                         // can't prove without my board (boardLost)
    if (recently(answerAt, g) || dapp.busy("answer", "game", Number(g))) continue;
    answerAt[g] = Date.now();
    const c = gm.pc, tree = buildTree(mine.board, mine.salts);
    const proof = [mine.board[c], mine.salts[c], ...cellProof(tree, c)];
    dapp.call("answer", [Number(g), ...proof], null, "answer the shot at " + coord(c) + " · battleship #" + g, { game: Number(g), phase: "answer" });
  }
}
const resign = () => dapp.call("resign", [activeGame], null, "resign battleship #" + activeGame, { game: activeGame, phase: "resign" });
const claimTimeout = () => dapp.call("timeout", [activeGame], null, "claim the stalled pot · battleship #" + activeGame, { game: activeGame, phase: "timeout" });
const cancelGame = () => dapp.call("cancel", [activeGame], null, "cancel battleship #" + activeGame, { game: activeGame, phase: "cancel" });
// reveal-at-claim: the WINNER collects a decided pot by revealing their 5 ship placements + salt-seed; the
// contract rebuilds the tree from them and pays only if it matches the committed root (a shape-cheat can't).
function claimWin(g) {
  const mine = myBoard(g);
  if (!mine || !mine.spec || mine.seed == null) return alertBar(window.t("bs.boardLost", "Your board for this game isn't on this device — play from the device that placed the fleet."));
  const args = [g]; for (const [a, o] of mine.spec) args.push(a, o); args.push(mine.seed);   // 5x(anchor,orient) + seed(BigInt)
  dapp.call("claim", args, null, "collect winnings · battleship #" + g, { game: g, phase: "claim" });
}
// if the winner never revealed a valid fleet by the deadline (e.g. a shape-cheater), the LOSER takes the pot.
const forfeitPot = (g) => dapp.call("forfeit", [g], null, "claim the unrevealed pot · battleship #" + g, { game: g, phase: "forfeit" });
// a decided win that's mine + unpaid → auto-reveal my fleet to collect (once). Runs each refresh over my games.
function autoSettle(sto) {
  if (!sto || !dapp.me) return;
  for (const g of Object.keys(load(LS_G))) {
    const gm = gameFrom(sto, g);
    if (!gm.exists || gm.sd || !gm.dc || !gm.mineSlot || gm.wr !== gm.mineSlot) { delete claimAt[g]; continue; }
    if (recently(claimAt, g) || dapp.busy("claim", "game", Number(g))) continue;
    claimAt[g] = Date.now();
    claimWin(Number(g));
  }
}
async function rematch() {
  const gm = lastGame; if (!gm || !gm.exists) return;
  const stake = BigInt(gm.stake);
  if (shipCount(placing) !== SHIPS) return alertBar(window.t("bs.placeFleet", "Place your whole fleet first (all {n} cells).", { n: SHIPS }));
  if (!canPay(dapp, stake, window.t("bs.whatRematch", "A rematch"))) return;
  const rid = rematchId(activeGame), rg = await fetchGame(rid), { root, board, salts, seed, spec } = commit();
  activeGame = rid; target = null;
  if (rg && rg.exists && rg.nn === 1 && !rg.over) { saveBoard(rid, 2, board, salts, gm.stake, seed, spec); dapp.call("join", [rid, root], stake, "join rematch battleship #" + rid, { game: rid, phase: "join" }); }
  else { saveBoard(rid, 1, board, salts, gm.stake, seed, spec); dapp.call("open", [rid, root], stake, "rematch battleship #" + rid, { game: rid, phase: "open" }); }
}

// ---- render --------------------------------------------------------------------------------------
function gridCell(cls, label, cell, clickable) {
  return '<div class="bcell ' + cls + '"' + (clickable ? ' data-fire="' + cell + '"' : "") + ' title="' + coord(cell) + '">' + label + "</div>";
}
function renderPlacement() {
  const el = $("placeGrid"); if (!el) return;
  const occ = new Set(); for (const s of ships) if (s.cells) for (const c of s.cells) occ.add(c);
  let h = "";
  for (let c = 0; c < CELLS; c++) h += '<div class="bcell ' + (occ.has(c) ? "ship" : "sea") + '" data-place="' + c + '" title="' + coord(c) + '"></div>';
  el.innerHTML = h;
  const tray = $("fleetTray");
  if (tray) tray.innerHTML = ships.map((s) => {
    const placed = !!s.cells, sel = s.i === selShip;
    return '<button type="button" class="shipbtn' + (sel ? " sel" : "") + (placed ? " placed" : "") + '" data-ship="' + s.i + '">'
      + '<span class="sname">' + window.t("bs.ship_" + s.key, SHIP_EN[s.i]) + "</span>"
      + '<span class="spips">' + "▮".repeat(s.len) + "</span>"
      + '<span class="stag">' + (placed ? "✓" : s.len) + "</span></button>";
  }).join("");
  const br = $("btnRotate"); if (br) br.textContent = (horiz ? "↔ " : "↕ ") + window.t("bs.rotate", "Rotate");
  const n = shipCount(placing);
  $("fleetCount").innerHTML = window.t("bs.fleetCount", "Fleet: <b>{n}/{total}</b> cells", { n, total: SHIPS })
    + (n === SHIPS ? ' <span class="b ok">' + window.t("bs.ready", "ready") + "</span>"
       : ' <span class="b pend">' + window.t("bs.placeShipHint", "pick a ship, tap the grid to place · tap a placed ship to move it") + "</span>");
}
function renderBoards(gm) {
  const mine = myBoard(gm.id);
  const mF = myFired[gm.id] || new Set(), mR = myRes[gm.id] || {}, oF = oppFired[gm.id] || new Set();
  // MY board: my ships + the opponent's shots at me — read from the append-only oppFired (never blips)
  let hm = "";
  for (let c = 0; c < CELLS; c++) {
    const ship = mine && mine.board[c], shot = oF.has(c);
    const cls = shot ? (ship ? "hit" : "miss") : (ship ? "ship" : "sea");
    hm += gridCell(cls, shot ? (ship ? "✸" : "•") : "", c, false);
  }
  $("myGrid").innerHTML = hm;
  // ENEMY board: my shots + their proven results — from the append-only myFired/myRes; a fired cell stays "…"
  // (optimistic) until the enemy proves the result, and never flickers back to fog on a provisional wobble.
  const canShoot = gm.myTurn && !dapp.busy("fire", "game", gm.id);   // no aiming while a shot is already in flight
  let he = "";
  for (let c = 0; c < CELLS; c++) {
    const r = mR[c] || 0, fired = mF.has(c);
    const sel = target === c ? " sel" : "";
    const cls = r === 2 ? "hit" : r === 1 ? "miss" : fired ? "pending" : "fog" + sel;
    he += gridCell(cls, r === 2 ? "✸" : r === 1 ? "•" : fired ? "…" : "", c, canShoot && !fired);
  }
  $("enemyGrid").innerHTML = he;
  $("enemyGrid").querySelectorAll("[data-fire]").forEach((el) => el.onclick = () => { target = Number(el.dataset.fire); render(); });
}
function renderActive(sto) {
  const ng = gameFrom(sto, activeGame);
  // good-faith anti-rollback: this game only moves forward (hits ↑, then decided, then settled), so ignore a dip.
  const prog = (ng.sd ? 2e9 : 0) + (ng.dc ? 1e9 : 0) + ng.h1 + ng.h2;
  if (dapp.accept("bs:" + activeGame, prog)) lastGame = ng;
  const gm = lastGame; if (!gm || !gm.exists) { gate({ activeGame: false }); return; }
  gate({ activeGame: true });
  $("gId").textContent = "#" + gm.id;
  $("gPot").textContent = rawToNado(gm.pot) + " NADO";
  // status line
  let st;
  const potAmt = rawToNado(gm.pot || BigInt(gm.stake) * 2n);
  if (gm.sd) st = gm.wr === 0 ? window.t("bs.over", "Game over.")
    : (gm.wr === gm.mineSlot ? window.t("bs.youWon", "🏆 You sank the enemy fleet — you won {amt} NADO!", { amt: potAmt })
       : window.t("bs.youLost", "☠ Your fleet was sunk — better luck next time."));
  else if (gm.dc)                                            // winner decided; pot released only on a valid-fleet claim
    st = gm.wr === gm.mineSlot
      ? window.t("bs.wonCollect", "🏆 You sank the enemy fleet! Revealing your fleet to collect {amt} NADO…", { amt: potAmt })
      : window.t("bs.youLost", "☠ Your fleet was sunk — better luck next time.")
        + (gm.cd && dapp.cursor != null && dapp.cursor > gm.cd ? window.t("bs.winnerStalled", " (winner never revealed a valid fleet — you can claim the pot)") : "");
  else if (gm.nn < 2) st = gm.mineSlot === 1 ? window.t("bs.waiting", "Waiting for an opponent — share the link below.") : window.t("bs.openSeat", "Open seat — join to play for {amt} NADO.", { amt: rawToNado(gm.stake) });
  else if (gm.toAnswer) st = window.t("bs.answering", "🛡 The enemy fired at {cell} — revealing your board…", { cell: coord(gm.pc) });   // auto-answered
  else if (gm.awaiting) st = window.t("bs.awaitAnswer", "🎯 Shot fired at {cell} — waiting for the enemy to call it…", { cell: coord(gm.pc) })
      + (gm.dl && dapp.cursor != null && dapp.cursor > gm.dl ? window.t("bs.stalled", " (stalled — you can claim the pot)") : "");
  else if (gm.myTurn) st = window.t("bs.yourTurnFire", "🎯 Your turn — fire!");
  else st = window.t("bs.oppTurn", "Waiting for the enemy to move…") + (gm.dl && dapp.cursor != null && dapp.cursor > gm.dl ? window.t("bs.stalled", " (stalled — you can claim the pot)") : "");
  $("gStatus").innerHTML = st;
  $("hitTally").textContent = window.t("bs.tally", "Your hits: {me}/{total} · Enemy hits: {them}/{total}",
    { me: gm.mineSlot === 1 ? gm.h1 : gm.h2, them: gm.mineSlot === 1 ? gm.h2 : gm.h1, total: SHIPS });
  gate({ boards: gm.nn === 2 });
  if (gm.nn === 2) renderBoards(gm);
  // controls
  const canJoin = gm.nn === 1 && gm.mineSlot === 0 && dapp.me;
  const canFire = gm.myTurn && target != null && !dapp.busy("fire", "game", gm.id);
  gate({ fireRow: gm.nn === 2 && !gm.over, joinRow: canJoin });
  const bf = $("btnFire"); if (bf) { bf.disabled = !canFire; bf.classList.toggle("pulse", canFire); bf.textContent = target != null ? window.t("bs.fireAt", "🔥 Fire at {cell}", { cell: coord(target) }) : window.t("bs.fire", "🔥 Fire"); }
  gate({ btnResign: gm.nn === 2 && !gm.over && gm.mineSlot, btnCancel: gm.nn === 1 && gm.mineSlot === 1,
         btnTimeout: gm.nn === 2 && !gm.over && !gm.myTurn && gm.mineSlot && gm.dl && dapp.cursor != null && dapp.cursor > gm.dl,
         btnForfeit: gm.dc && !gm.sd && gm.mineSlot && gm.wr !== gm.mineSlot && gm.wr !== 0 && gm.cd && dapp.cursor != null && dapp.cursor > gm.cd,
         btnRematch: gm.over && gm.mineSlot });
  shareInvite("game", gm.id, window.t("bs.shareText", "Play Battleship vs me on NADO:"), 180);
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const open = allGids(sto).map((g) => gameFrom(sto, g)).filter((g) => g.exists && g.nn === 1 && !g.sd).sort((a, b) => b.id - a.id);
  el.innerHTML = open.length ? open.slice(0, lobbyN).map((g) =>
    '<button class="chip betting" data-g="' + g.id + '">🚢 #' + g.id + " · " + window.t("bs.stakeChip", "stake {s}", { s: rawToNado(g.stake) }) + " · " + window.t("bs.byChip", "by {who}", { who: disp(g.p1) }) + "</button>").join(" ")
    : '<span class="dim">' + window.t("bs.noOpen", "No open games — start one below.") + "</span>";
  const bm = $("btnMoreLobby");
  if (bm) { bm.classList.toggle("hidden", open.length <= lobbyN); if (open.length > lobbyN) bm.textContent = window.t("bs.showMore", "Show more ({n} more)", { n: open.length - lobbyN }); }
  if (!el._deleg) { el._deleg = true; el.addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) selectGame(b.dataset.g); }); }
}
let lobbyN = 24;
function selectGame(id) { activeGame = Number(id); target = null; notify(window.t("bs.selected", "Game #{id} selected.", { id })); render(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} }
function render() {
  dapp.reflectUrl("game", activeGame);
  const signedIn = renderWallet(dapp);
  gate({ setup: true, bankroll: signedIn });
  renderPlacement();
  const sto = lastSto;
  if (sto) { renderLobby(sto); if (activeGame != null) renderActive(sto); else gate({ activeGame: false }); }
  else gate({ activeGame: false });
  const bo = $("btnOpen"); if (bo) bo.textContent = joinableActive()
    ? window.t("bs.joinThisBtn", "⚓ Place fleet & join #{id}", { id: activeGame }) : window.t("bs.openGame", "Open a battle");
  // my recent games
  const G = load(LS_G);
  const mine = Object.keys(G).map((g) => ({ id: +g, ts: G[g].ts, icon: "🚢", live: !!(sto && _m(sto, "p1")[g]) })).sort((a, b) => b.ts - a.ts).slice(0, 8);
  recentChips($("recent"), mine, selectGame, window.t("bs.noGamesYet", "No games yet."));
}

// ---- refresh loop --------------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  dapp.settleInflight((f) => {
    const g = gameFrom(lastSto || {}, f.game);
    return f.phase === "open" ? g.exists : f.phase === "join" ? g.nn === 2
         : f.phase === "fire" ? firedAt(lastSto, g.mineSlot, f.game, f.shot)     // my shot is on-chain
         : f.phase === "answer" ? !g.pex                                         // the pending shot got answered
         : (f.phase === "claim" || f.phase === "forfeit") ? g.sd                 // pot paid out
         : f.phase === "cancel" ? (g.sd || !g.exists)
         : (g.dc || g.sd || !g.exists);                                          // resign / timeout → decided
  });
  // sticky the APPEND-ONLY maps (fired flags, results, hit counts, settled/decided/winner, join) so they never
  // blip on a rollback; pex/pf/tf legitimately toggle, so they're left raw.
  const sto = await dapp.storage({ append: ["fd", "res", "h1", "h2", "sd", "dc", "wr", "p2", "nn"] });
  if (sto) { lastSto = sto; ingestShots(sto, activeGame); lsPrune(LS_G, allGids(sto)); await resolveAliases(allGids(sto).flatMap((g) => [_m(sto, "p1")[g], _m(sto, "p2")[g]]).filter(Boolean).slice(0, 40)); }
  autoSettle(sto);                                                               // reveal my fleet to collect any decided win
  autoAnswer(sto);                                                               // auto-reveal the result of any shot fired at me
  render();
}

// ---- boot ----------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => dapp.exec, render);
  stickyInputs(dapp, ["stakeAmt", "bankAmt"]);
  // when you've landed on someone's OPEN game (via a share link), the setup card's primary button JOINS that
  // game instead of opening a brand-new one — otherwise it's easy to accidentally start a fresh game.
  $("btnOpen").onclick = () => joinableActive() ? joinGame() : openGame();
  $("btnJoinGame").onclick = () => { if (!dapp.me) return dapp.signIn(); joinGame(); };
  $("btnFire").onclick = fire;
  $("btnRandom").onclick = () => { ships = randFleetShips(); selShip = 0; syncFleet(); render(); };
  if ($("btnRotate")) $("btnRotate").onclick = () => { horiz = !horiz; render(); };
  if ($("fleetTray")) $("fleetTray").addEventListener("click", (e) => { const b = e.target.closest("[data-ship]"); if (!b) return; const i = Number(b.dataset.ship); if (ships[i].cells) ships[i].cells = null; selShip = i; syncFleet(); render(); });
  $("btnResign").onclick = resign;
  $("btnTimeout").onclick = claimTimeout;
  if ($("btnForfeit")) $("btnForfeit").onclick = () => forfeitPot(activeGame);
  $("btnCancel").onclick = cancelGame;
  $("btnRematch").onclick = rematch;
  $("btnShare").onclick = () => share(base() + "/?game=" + activeGame, window.t("bs.shareThis", "Play this Battleship game on NADO:"), $("btnShare"));
  if ($("btnMoreLobby")) $("btnMoreLobby").onclick = () => { lobbyN += 48; if (lastSto) renderLobby(lastSto); };
  // ship-based placement: tap a placed ship to pick it up, or tap empty water to drop the armed ship (delegated)
  $("placeGrid").addEventListener("click", (e) => {
    const c = e.target.closest("[data-place]"); if (!c) return;
    const cell = Number(c.dataset.place), hit = shipAt(ships, cell);
    if (hit) { hit.cells = null; selShip = hit.i; syncFleet(); return render(); }   // pick up a ship
    let idx = (ships[selShip] && !ships[selShip].cells) ? selShip : firstUnplaced(ships);
    if (idx < 0) return notify(window.t("bs.allPlaced", "Whole fleet placed — tap a ship to move it, or 🎲 for a new layout."));
    if (!placeAt(ships, idx, cell, horiz)) return notify(window.t("bs.badPlace", "That ship won't fit there — rotate (↻) or pick another cell."));
    selShip = firstUnplaced(ships); if (selShip < 0) selShip = idx;
    syncFleet(); render();
  });
}
dapp.doneLabels({ open: window.t("bs.dnOpen", "✓ Game is on-chain — send the invite below."), join: window.t("bs.dnJoin", "✓ You're in — battle on!"),
  fire: window.t("bs.dnFire", "✓ Shot away."), resign: window.t("bs.dnResign", "✓ Resigned."), timeout: window.t("bs.dnTimeout", "✓ Pot claimed."), cancel: window.t("bs.dnCancel", "✓ Cancelled — stake refunded."),
  claim: window.t("bs.dnClaim", "✓ Fleet revealed — winnings collected!"), forfeit: window.t("bs.dnForfeit", "✓ Pot claimed — opponent never revealed a valid fleet.") });
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.game != null) activeGame = pend.game;
  if (!ok && pend && pend.phase === "fire" && pend.shot != null) { setOf(myFired, pend.game).delete(pend.shot); render(); }   // rejected → un-paint the optimistic shot
  if (!ok && pend && pend.phase === "answer") delete answerAt[pend.game];   // rejected at signing → let the auto-answer retry now
  dapp.showReturn(pend, ok, err, { open: window.t("bs.cfOpen", "Opening — confirming…"), join: window.t("bs.cfJoin", "Joining — confirming…"),
    fire: window.t("bs.cfFire", "Firing — confirming on-chain…"), resign: window.t("bs.cfResign", "Resigning…"), timeout: window.t("bs.cfTimeout", "Claiming…"), cancel: window.t("bs.cfCancel", "Cancelling…"),
    claim: window.t("bs.cfClaim", "Revealing your fleet to collect…"), forfeit: window.t("bs.cfForfeit", "Claiming the pot…") });
});
async function boot() {
  wireUI();
  orderCards(["activeGame", "setup", "lobby", "practice", "walletcard", "bankroll"]);
  render();                                     // draw the fleet-placement UI immediately (needs no crypto/network)
  try { await dapp.init(); } catch (e) { alertBar(window.t("bs.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  loadQR();
  const q = new URLSearchParams(location.search).get("game");
  if (q) { activeGame = parseInt(q, 10); if (!dapp.me) inviteGate(dapp, { kind: "game", id: activeGame, body: window.t("bs.inviteBody", "You've been challenged to a game of Battleship for NADO stakes."), onJoin: () => { const gm = lastGame; if (gm && gm.nn === 1) joinGame(); } }); }
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
if ($("btnOpen")) boot();

// ---- PRACTICE MODE (free, in-browser — random fleets, hunt/target computer; nothing on-chain) -----------
const prac = new Practice("battleship");
let pMyFleet, pMyBoard, pEnBoard, pMyShots, pEnShots, pQueue, pHits, pEnHits, pPracOver;
function pAiShot() {           // random hunt; after a hit, target adjacent cells until that ship sinks
  let c;
  while (pQueue.length && pEnShots.has(pQueue[0])) pQueue.shift();
  if (pQueue.length) c = pQueue.shift();
  else do { c = Math.floor(Math.random() * CELLS); } while (pEnShots.has(c));
  pEnShots.add(c);
  if (!pMyBoard[c]) return;
  pEnHits++;
  const ship = shipAt(pMyFleet, c);
  if (ship && ship.cells.every((x) => pEnShots.has(x))) { pQueue = []; return; }   // sunk — back to hunting
  const r = Math.floor(c / N), col = c % N;
  for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
    const nr = r + dr, nc = col + dc;
    if (nr >= 0 && nr < N && nc >= 0 && nc < N && !pEnShots.has(nr * N + nc)) pQueue.push(nr * N + nc);
  }
}
function pPracEnd(won) {
  pPracOver = true; prac.tally(won ? "w" : "l");
  $("pResult").innerHTML = won ? "🏆 " + window.t("sdk.prYouWin", "You win!") : "💀 " + window.t("sdk.prAiWins", "The computer wins.");
  pPracRender();
}
function pFire(c) {            // tap an enemy cell to fire; the computer answers with its own shot
  if (pPracOver || pMyShots.has(c)) return;
  pMyShots.add(c);
  if (pEnBoard[c] && ++pHits >= SHIPS) return pPracEnd(true);
  pAiShot();
  if (pEnHits >= SHIPS) return pPracEnd(false);
  pPracRender();
}
function pPracRender() {
  prac.strip($("pStrip"), { chips: false, tally: true });
  let he = "";                 // enemy waters: my shots + results (same cell CSS as the real boards)
  for (let c = 0; c < CELLS; c++) {
    const fired = pMyShots.has(c), hit = fired && pEnBoard[c];
    he += gridCell(fired ? (hit ? "hit" : "miss") : "fog", hit ? "✸" : fired ? "•" : "", c, !pPracOver && !fired);
  }
  $("pEnemyGrid").innerHTML = he;
  $("pEnemyGrid").querySelectorAll("[data-fire]").forEach((el) => el.onclick = () => pFire(Number(el.dataset.fire)));
  let hm = "";                 // my fleet + the computer's shots
  for (let c = 0; c < CELLS; c++) {
    const ship = pMyBoard[c], shot = pEnShots.has(c);
    hm += gridCell(shot ? (ship ? "hit" : "miss") : (ship ? "ship" : "sea"), shot ? (ship ? "✸" : "•") : "", c, false);
  }
  $("pMyGrid").innerHTML = hm;
  $("pTally").textContent = window.t("bs.tally", "Your hits: {me}/{total} · Enemy hits: {them}/{total}", { me: pHits, them: pEnHits, total: SHIPS });
  if (!pPracOver) $("pResult").textContent = window.t("bs.yourTurnFire", "🎯 Your turn — fire!");
}
function pNewBattle() {        // randomize YOUR fleet (same ship set + no-overlap rules) + a hidden enemy fleet
  pMyFleet = randFleetShips(); pMyBoard = boardOf(pMyFleet); pEnBoard = boardOf(randFleetShips());
  pMyShots = new Set(); pEnShots = new Set(); pQueue = []; pHits = 0; pEnHits = 0; pPracOver = false;
  pPracRender();
}
if ($("pEnemyGrid")) { $("pNew").onclick = pNewBattle; pNewBattle(); }

// pets.js — NADO Pets: tamagotchi NFTs on the execution layer, built on the shared game SDK (nadodapp.js).
// Every pet is an on-chain asset: a future block hash decides its species/rarity/stats at hatch (via
// pets-genes.js, byte-identical to the contract and differentially verified), it eats real NADO to stay
// alive, trains with a rarity-scaled limit-function success chance, battles other pets for stakes (loser
// has a 20% chance to die), and transfers between wallets like any NFT. All money moves happen in the
// contract (execnode/contracts/pets.json); this file is reads + UI + the wallet-signed calls.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, orderCards, alertBar, blocksToTime,
         lsLoad, lsSave, wireWallet, renderWallet, statusLabel,
         loadQR, resolveAliases, disp, shareInvite } from "./nadodapp.js";
import * as G from "./pets-genes.js";

const CID = "a5099d7f767cfe8e84855a7cb64994cb";   // execnode/contracts/pets.json, deployed by the node key
const dapp = new NadoDapp({ cid: CID, app: "Pets" });
const BLOCK_SECS = 6, BLOCKS_PER_DAY = 86400 / BLOCK_SECS;
const LS_P = "nado_pets_mine";                    // {pid: {ts, hatchPending?, trainPending?}} local flags
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let active = null, activeBattle = null;
let PETS = {}, BATTLES = {}, OFFERS = {}, hatchPlaying = false, battlePlaying = null;

// ---- SVG art (one <g> per animated part; CSS in pets.html does the moving) ------------------------
function eggSvg(cls, cracks) {
  return `<svg viewBox="0 0 120 120"><g class="${cls}">
    <g class="shellwrap${cracks >= 4 ? " popped" : ""}">
      <g class="shellL"><path d="M60 16 C38 16 26 44 26 70 C26 88 36 102 48 106 L60 104 L60 16 Z" fill="#f5e9d0" stroke="#c8a96a" stroke-width="2.5"/></g>
      <g class="shellR"><path d="M60 16 C82 16 94 44 94 70 C94 88 84 102 72 106 L60 104 L60 16 Z" fill="#efe0c0" stroke="#c8a96a" stroke-width="2.5"/></g>
      <circle cx="48" cy="46" r="4" fill="#d9c49a"/><circle cx="70" cy="66" r="5" fill="#d9c49a"/><circle cx="56" cy="84" r="3.4" fill="#d9c49a"/><circle cx="72" cy="34" r="3" fill="#d9c49a"/>
      <path class="crack${cracks >= 1 ? " show" : ""}" d="M52 40 l7 8 -6 7 8 9" stroke="#8a6f42" stroke-width="2.2" fill="none"/>
      <path class="crack${cracks >= 2 ? " show" : ""}" d="M72 52 l-6 9 7 6 -5 10" stroke="#8a6f42" stroke-width="2.2" fill="none"/>
      <path class="crack${cracks >= 3 ? " show" : ""}" d="M44 68 l9 6 -4 9 10 7" stroke="#8a6f42" stroke-width="2.2" fill="none"/>
    </g></g></svg>`;
}
function poodleSvg(cls, c) {
  return `<svg viewBox="0 0 120 120"><g class="${cls}">
    <g class="tail-wag"><circle cx="24" cy="78" r="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>
    <ellipse cx="52" cy="88" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
    <circle cx="38" cy="103" r="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
    <circle cx="64" cy="103" r="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
    <rect x="70" y="58" width="9" height="26" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <g class="head-tilt"><circle cx="80" cy="46" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <circle cx="66" cy="34" r="9" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="93" cy="34" r="9" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="80" cy="27" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <g class="blink"><circle cx="75" cy="45" r="2.6" fill="#2b2118"/><circle cx="87" cy="45" r="2.6" fill="#2b2118"/></g>
      <ellipse cx="81" cy="53" rx="3.4" ry="2.6" fill="#2b2118"/>
      <path d="M81 56 q0 4 -4 5 M81 56 q0 4 4 5" stroke="#2b2118" stroke-width="1.6" fill="none"/></g></g></svg>`;
}
function parrotSvg(cls, c) {
  return `<svg viewBox="0 0 120 120"><g class="${cls}">
    <path d="M46 104 l5 -12 4 12 Z M60 104 l5 -12 4 12 Z" fill="#6b6f76"/>
    <ellipse cx="58" cy="70" rx="24" ry="28" fill="${c.shade}" stroke="${c.line}" stroke-width="2.5"/>
    <g class="wing-flap"><path d="M42 56 C28 62 26 84 38 94 C46 88 48 68 42 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="wing-flap right"><path d="M74 56 C88 62 90 84 78 94 C70 88 68 68 74 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>
    <path d="M52 94 C50 106 54 114 60 118 C64 112 64 102 62 94 Z" fill="#d0362b" stroke="#8a1a12" stroke-width="2"/>
    <g class="head-tilt"><circle cx="60" cy="40" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <circle cx="54" cy="36" r="6.5" fill="#f2f4f6" stroke="${c.line}" stroke-width="1.6"/>
      <g class="blink"><circle cx="54" cy="36" r="2.6" fill="#20242a"/></g>
      <path d="M72 33 q12 3 10 12 q-2 8 -12 7 q-4 -1 -5 -6 Z" fill="#3a3f45" stroke="#20242a" stroke-width="1.8"/>
      <path d="M74 47 q4 5 1 8" stroke="#20242a" stroke-width="1.6" fill="none"/></g></g></svg>`;
}
function dragonSvg(cls, c) {
  return `<svg viewBox="0 0 120 120"><g class="${cls}">
    <path d="M28 92 C16 90 12 80 16 72 C22 78 30 80 36 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
    <g class="wing-flap"><path d="M40 52 C24 34 12 36 8 48 C20 46 26 54 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="wing-flap right"><path d="M74 52 C90 34 102 36 106 48 C94 46 88 54 84 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>
    <ellipse cx="57" cy="80" rx="26" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
    <path d="M40 62 l6 -9 6 9 Z M52 58 l6 -10 6 10 Z M64 62 l6 -9 6 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <ellipse cx="57" cy="86" rx="14" ry="10" fill="#bff2e4" opacity="0.5"/>
    <g class="head-tilt"><ellipse cx="82" cy="46" rx="17" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M72 34 l4 -10 6 8 Z M84 32 l5 -10 5 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <g class="blink"><circle cx="78" cy="44" r="3" fill="#083b32"/><circle cx="92" cy="44" r="3" fill="#083b32"/></g>
      <ellipse cx="86" cy="54" rx="9" ry="4.5" fill="${c.shade}"/>
      <circle cx="83" cy="53" r="1.2" fill="#083b32"/><circle cx="89" cy="53" r="1.2" fill="#083b32"/>
      <g class="smoke"><circle cx="101" cy="50" r="3.4" fill="#9fb8b2"/></g>
      <g class="smoke s2"><circle cx="103" cy="47" r="2.6" fill="#9fb8b2"/></g></g></g></svg>`;
}
function graveSvg() {
  return `<svg viewBox="0 0 120 120"><g>
    <ellipse cx="60" cy="104" rx="34" ry="8" fill="#1c2733"/>
    <path d="M38 104 L38 56 Q38 34 60 34 Q82 34 82 56 L82 104 Z" fill="#67788a" stroke="#43525f" stroke-width="2.5"/>
    <text x="60" y="62" text-anchor="middle" font-size="13" font-weight="800" fill="#2c3944" font-family="system-ui">RIP</text>
    <path d="M52 74 h16 M60 66 v16" stroke="#2c3944" stroke-width="3"/>
    <g class="ghostup"><text x="60" y="30" text-anchor="middle" font-size="16">👻</text></g></g></svg>`;
}
const PET_SVGS = { 1: poodleSvg, 2: parrotSvg, 3: dragonSvg };
const DEFAULT_COAT = { 1: G.COATS[1][0], 2: G.COATS[2][0], 3: G.COATS[3][0] };
// draw a pet with its gene-derived coat, wrapped in a rarity-aura span (glow/shimmer via CSS in pets.html)
function petBody(p, cls = "pet-idle") {
  const coat = p.gene ? G.coatOf(p.gene, p.sp) : DEFAULT_COAT[p.sp];
  const aura = p.gene ? G.auraOf(p.sp, coat.shiny) : "";
  return `<span class="aura ${aura}">${PET_SVGS[p.sp](cls, coat)}</span>`;
}
const petArt = (p, cls = "pet-idle") => p.dead ? graveSvg() : (p.hatched ? petBody(p, cls) : eggSvg(p.hatchReady ? "egg-ready egg-glow" : "egg-idle", 0));

// ---- reads: everything derives from the contract's storage maps -----------------------------------
function petsFrom(sto) {
  const ow = _m(sto, "ow"), cur = dapp.cursor, out = {};
  for (const pid of Object.keys(ow)) {
    const gs = _m(sto, "gs")[pid] || null;
    const p = { id: pid, owner: ow[pid], bh: _m(sto, "bh")[pid] || 0, gs, sp: _m(sto, "sp")[pid] || 0,
      ap: _m(sto, "ap")[pid] || 0, pw: _m(sto, "pw")[pid] || 0, fu: _m(sto, "fu")[pid] || 0,
      tf: _m(sto, "tf")[pid] || 0, nm: _m(sto, "nm")[pid] || "", th: _m(sto, "th")[pid] || 0,
      ti: _m(sto, "ti")[pid] || 0, tr: _m(sto, "tr")[pid] || 0, price: _m(sto, "mp")[pid] || 0,
      wins: _m(sto, "wins")[pid] || 0, loss: _m(sto, "loss")[pid] || 0 };
    p.hatched = !!gs; p.gene = gs ? BigInt(gs) : null;
    p.dead = cur != null && cur > p.fu;
    p.mine = dapp.me && p.owner === dapp.me;
    p.hatchReady = !p.hatched && !!(dapp.bh(p.bh) && dapp.bh(p.bh + 1));
    p.stale = !p.hatched && cur != null && cur >= p.bh + G.STALE;         // gene block pruned -> rebirth
    p.base = p.gene ? G.baseStats(p.gene, p.sp) : null;
    p.bonus = p.gene ? G.STAT_NAMES.map((_n, i) => _m(sto, "tb")[pid + "|" + i] || 0) : null;
    p.level = G.levelOf(p.tf || 0);
    p.label = p.nm ? p.nm : (p.hatched ? G.SPECIES[p.sp].name : "Egg") + " #" + String(pid).slice(-4);
    out[pid] = p;
  }
  return out;
}
function offersFrom(sto) {
  const os = _m(sto, "os"), out = {};
  for (const oid of Object.keys(os)) {
    out[oid] = { id: oid, buyer: String(_m(sto, "ob")[oid] || ""), pet: String(_m(sto, "op")[oid] || ""),
      value: _m(sto, "ov")[oid] || 0, state: _m(sto, "os")[oid] || 0 };
  }
  return out;
}
function battlesFrom(sto) {
  const wa = _m(sto, "wa"), out = {};
  for (const bid of Object.keys(wa)) {
    out[bid] = { id: bid, a: String(wa[bid]), b: String(_m(sto, "wb")[bid]), ws: _m(sto, "ws")[bid] || 0,
      wp: _m(sto, "wp")[bid] || 0, wh: _m(sto, "wh")[bid] || 0, wn: _m(sto, "wn")[bid] || 0,
      ww: String(_m(sto, "ww")[bid] || ""), wd: _m(sto, "wd")[bid] || 0 };
  }
  return out;
}
const myPets = () => Object.values(PETS).filter((p) => p.mine);
// effective stats (base gene stat + trained bonus) — what the turn-based battle actually fights with
const effOf = (p) => (p.base && p.bonus) ? p.base.map((b, i) => b + p.bonus[i]) : null;
const recordOf = (p) => (p.wins || 0) + "W–" + (p.loss || 0) + "L";
const lifeBlocks = (p) => dapp.cursor == null ? null : p.fu - dapp.cursor;
const lifeText = (p) => { const b = lifeBlocks(p); if (b == null) return "…"; if (b <= 0) return "none";
  const d = Math.floor(b / BLOCKS_PER_DAY), h = Math.floor((b % BLOCKS_PER_DAY) * BLOCK_SECS / 3600);
  return d > 0 ? d + "d " + h + "h" : h > 0 ? h + "h " + Math.floor((b * BLOCK_SECS % 3600) / 60) + "m" : blocksToTime(b) + " min"; };

// ---- actions ---------------------------------------------------------------------------------------
const L = () => lsLoad(LS_P), Lsave = (v) => lsSave(LS_P, v);
function mint() {
  if (!canPay(dapp, G.MINT_FEE, "Adopting an egg")) return;
  const pid = randId(); const l = L(); l[pid] = { ts: Date.now() }; Lsave(l); active = pid;
  dapp.call("mint", [pid], G.MINT_FEE, "adopt egg #" + pid + " · 1 NADO", { pid, phase: "mint" });
}
function hatch(pid) {
  const l = L(); (l[pid] = l[pid] || { ts: Date.now() }).hatchPending = 1; Lsave(l);
  dapp.call("hatch", [pid], null, "hatch egg #" + pid, { pid, phase: "hatch" });
}
const rebirth = (pid) => dapp.call("rebirth", [pid], null, "re-roll egg #" + pid, { pid, phase: "hatch" });
function feed(pid, raw) {
  const p = PETS[pid]; if (!p) return;
  const blocks = G.feedBlocks(raw, p.ap);
  if (blocks < 1) return alertBar("That meal is too small — it wouldn't buy a single block of life (this pet's appetite costs " + rawToNado(G.feedCost(1, p.ap)) + " NADO per block).");
  if (lifeBlocks(p) + blocks > G.BELLY_CAP) return alertBar("Too much food — the belly holds at most 7 days. Fill it with the preset instead.");
  if (!canPay(dapp, raw, "This meal")) return;
  dapp.call("feed", [Number(pid)], raw, "feed " + PETS[pid].label + " · " + rawToNado(raw) + " NADO (+" + (blocks / BLOCKS_PER_DAY).toFixed(1) + "d)", { pid, phase: "feed" });
}
function train(pid, i) {
  if (!canPay(dapp, G.TRAIN_FEE, "Training")) return;
  const l = L(); const r = (l[pid] = l[pid] || { ts: Date.now() }); r.trainPending = 1; r.trainStat = G.STAT_NAMES[i]; Lsave(l);
  dapp.call("train", [Number(pid), i], G.TRAIN_FEE, "train " + PETS[pid].label + " · " + G.STAT_NAMES[i] + " · 0.5 NADO", { pid, phase: "train" });
}
const trainResolve = (pid) => dapp.call("train_resolve", [Number(pid)], null, "reveal training result for " + PETS[pid].label, { pid, phase: "trainres" });
function challenge(theirPid) {
  const myPid = parseInt($("myPetSel").value, 10);
  if (!myPid) return alertBar("Pick which of your pets fights — you need a living, hatched pet (adopt one below).");
  const stake = $("stakeAmt").value.trim() === "" || $("stakeAmt").value.trim() === "0" ? 0n : nadoToRaw($("stakeAmt").value);
  if (stake == null) return alertBar("Enter a stake in NADO (0 for a friendly-but-deadly match).");
  if (stake > 0n && !canPay(dapp, stake, "This challenge")) return;
  const bid = randId();
  dapp.call("challenge", [bid, myPid, Number(theirPid)], stake > 0n ? stake : null,
    "challenge " + PETS[theirPid].label + " with " + PETS[myPid].label + (stake > 0n ? " · stake " + rawToNado(stake) + " NADO" : ""),
    { bid, phase: "challenge" }, { confirm: 1 });
}
function acceptBattle(bid) {
  const b = BATTLES[bid]; if (!b) return;
  const stake = BigInt(b.ws || 0);
  if (stake > 0n && !canPay(dapp, stake, "Accepting this battle")) return;
  dapp.call("accept", [Number(bid)], stake > 0n ? stake : null, "accept battle #" + bid + (stake > 0n ? " · stake " + rawToNado(stake) + " NADO" : ""), { bid, phase: "accept" }, { confirm: 1 });
}
const resolveBattle = (bid) => dapp.call("resolve_battle", [Number(bid)], null, "settle battle #" + bid, { bid, phase: "resolveb" });
const cancelBattle = (bid) => dapp.call("cancel_battle", [Number(bid)], null, "withdraw challenge #" + bid, { bid, phase: "cancelb" });
const refundBattle = (bid) => dapp.call("refund_battle", [Number(bid)], null, "reclaim stakes of battle #" + bid, { bid, phase: "cancelb" });
function nameIt(pid) {
  const name = $("nameInput").value.trim().slice(0, 24);
  if (!name) return alertBar("Pick a name — it's permanent, like a real pet's.");
  dapp.call("name", [Number(pid), name], null, 'name pet #' + pid + ' "' + name + '" (permanent)', { pid, phase: "rename" }, { confirm: 1 });
}
function listPet(pid) {
  const raw = nadoToRaw($("listPrice").value);
  if (!raw) return alertBar("Enter your ask price in NADO.");
  dapp.call("list", [Number(pid), raw], null, "sell " + PETS[pid].label + " · ask " + rawToNado(raw) + " NADO", { pid, phase: "market" }, { confirm: 1 });
}
const unlistPet = (pid) => dapp.call("unlist", [Number(pid)], null, "remove " + PETS[pid].label + " from the market", { pid, phase: "market" });
function buyPet(pid) {
  const p = PETS[pid]; if (!p || !p.price) return;
  const price = BigInt(p.price);
  if (!canPay(dapp, price, "Buying this pet")) return;
  dapp.call("buy", [Number(pid)], price, "buy " + p.label + " · " + rawToNado(price) + " NADO", { pid, phase: "buy" }, { confirm: 1 });
}
function makeOffer(pid) {
  const p = PETS[pid]; if (!p) return;
  const raw = nadoToRaw($("offerAmt").value);
  if (!raw) return alertBar("Enter your offer in NADO.");
  if (!canPay(dapp, raw, "This offer")) return;
  const oid = randId();
  dapp.call("offer", [oid, Number(pid)], raw, "offer " + rawToNado(raw) + " NADO for " + p.label, { pid, oid, phase: "offer" }, { confirm: 1 });
}
const acceptOffer = (oid, label) => dapp.call("accept_offer", [Number(oid)], null, "accept offer #" + oid + (label ? " for " + label : ""), { oid, phase: "offeract" }, { confirm: 1 });
const cancelOffer = (oid) => dapp.call("cancel_offer", [Number(oid)], null, "withdraw offer #" + oid, { oid, phase: "offeract" });
async function transfer(pid) {
  let to = $("xferTo").value.trim();
  if (to.startsWith("@")) {
    try { const r = await (await fetch(base() + "/resolve_alias?name=" + encodeURIComponent(to.slice(1)), { cache: "no-store" })).json(); to = r.address || r.owner || ""; }
    catch { to = ""; }
    if (!to) return alertBar("That @alias doesn't resolve to an address.");
  }
  if (!to || !to.startsWith("ndo")) return alertBar("Enter the receiving NADO address (ndo…) or a registered @alias.");
  if (to === dapp.me) return alertBar("That's you — pick another wallet.");
  dapp.call("transfer", [Number(pid), to], null, "transfer " + PETS[pid].label + " to " + to.slice(0, 10) + "…", { pid, phase: "xfer" }, { confirm: 1 });
}

// ---- refresh loop ----------------------------------------------------------------------------------
let BURNED = 0n;
async function refreshAll() {
  await dapp.refresh();
  try { BURNED = BigInt((await (await fetch(base() + "/exec/bridge?ns=default&provisional=1", { cache: "no-store" })).json()).balances.burn || 0); } catch {}
  const sto = await dapp.storage();
  if (sto) {
    BATTLES = battlesFrom(sto); OFFERS = offersFrom(sto);
    // hashes we need: the active egg's gene blocks, pending trainings, accepted battles
    const want = [];
    const pre = petsFrom(sto);
    for (const p of Object.values(pre)) {
      if (!p.hatched && dapp.cursor != null && dapp.cursor >= p.bh + 1 && dapp.cursor < p.bh + G.STALE) want.push(p.bh, p.bh + 1);
      if (p.th && dapp.cursor != null && dapp.cursor >= p.th + 1) want.push(p.th, p.th + 1);
    }
    for (const b of Object.values(BATTLES)) if (b.wn === 2 && dapp.cursor != null && dapp.cursor >= b.wh + 1) want.push(b.wh, b.wh + 1);
    if (want.length) await dapp.blockHashes(want.slice(0, 40));
    PETS = petsFrom(sto);                       // re-derive with hashes cached (hatchReady)
    // prune local records that never landed
    const l = L(); let ch = false;
    for (const pid of Object.keys(l)) if (!PETS[pid] && Date.now() - (l[pid].ts || 0) > 600000) { delete l[pid]; ch = true; }
    if (ch) Lsave(l);
    await resolveAliases(Object.values(PETS).map((p) => p.owner).concat([dapp.me]).filter(Boolean).slice(0, 60));
    // an in-flight action whose effect is now visible on-chain is done — stop showing "confirming…"
    const f = dapp.inflight;
    if (f && ((f.phase === "mint" && PETS[f.pid]) || (f.phase === "hatch" && PETS[f.pid] && PETS[f.pid].hatched)
        || (f.phase === "buy" && PETS[f.pid] && PETS[f.pid].mine)
        || (f.phase === "challenge" && BATTLES[f.bid]) || (f.phase === "accept" && BATTLES[f.bid] && BATTLES[f.bid].wn >= 2)
        || (f.phase === "resolveb" && BATTLES[f.bid] && BATTLES[f.bid].wn === 3))) dapp.clearInflight();
  }
  render();
}

// ---- render ----------------------------------------------------------------------------------------
function statRow(p, i) {
  const base = p.base[i], bonus = p.bonus[i], val = base + bonus, chance = G.trainChance(p.sp, val);
  const canTrain = p.mine && !p.dead && !p.th;
  // two-segment bar: teal = base (locked at hatch), gold = trained bonus you added
  const baseW = Math.min(100, base), bonusW = Math.min(100 - baseW, bonus);
  const bar = `<div class="bar sbar"><i style="width:${baseW}%"></i>${bonusW > 0 ? `<b style="width:${bonusW}%" title="+${bonus} from training"></b>` : ""}</div>`;
  return `<div class="statrow"><span>${G.STAT_ICONS[i]}</span><span>${G.STAT_NAMES[i]}</span>
    <span class="sv">${val}${bonus ? ` <span class="up">+${bonus}</span>` : ""}</span>
    ${bar}
    ${canTrain ? `<button class="mini train" data-train="${i}" title="Train ${G.STAT_NAMES[i]} — 0.5 NADO, ${chance.toFixed(0)}% chance to gain +1">🏋 Train · ${chance.toFixed(0)}%</button>` : `<span class="small dim" title="train success chance">${chance.toFixed(0)}%</span>`}
  </div>`;
}
function renderActive() {
  const p = PETS[active];
  gate({ activePet: active != null });
  if (active == null) return;
  const local = L()[active] || {};
  if (!p) {                                        // not on-chain (yet)
    $("petId").textContent = "#" + active; $("petRar").innerHTML = "";
    $("petStage").innerHTML = eggSvg("egg-idle", 0);
    $("petName").textContent = "Egg #" + String(active).slice(-4);
    $("petSpecies").textContent = "";
    $("petMsg").textContent = dapp.whereIs("pet", active, local.ts);
    gate({ lifeWrap: false, hatchRow: false, feedRow: false, statsWrap: false, challengeRow: false, ownRow: false });
    shareInvite("pet", null); return;
  }
  const sp = p.hatched ? G.SPECIES[p.sp] : null;
  $("petId").textContent = "#" + p.id;
  $("petRar").innerHTML = sp ? `<span class="rar r${p.sp}">${sp.rarity} · ${sp.pct}%</span>` : `<span class="rar r1">Egg</span>`;
  if (!hatchPlaying) {
    const mood = p.dead ? "dead" : "";
    $("activePet").className = "card " + mood;
    $("petStage").innerHTML = petArt(p);
  }
  $("petName").textContent = p.label + (p.dead ? " ✝" : "");
  const coat = p.gene ? G.coatOf(p.gene, p.sp) : null;
  $("petSpecies").innerHTML = p.hatched
    ? sp.emoji + " " + esc(coat.name) + " " + sp.name + (coat.shiny ? ' <span style="color:#ffd35a">✦ shiny</span>' : "") + (p.nm ? ' · <span class="dim">#' + p.id + "</span>" : "")
    : "Unhatched egg";
  $("petOwner").innerHTML = esc(disp(p.owner)) + (p.mine ? ' <span class="b ok">yours</span>' : "");
  $("petLp").textContent = p.hatched ? "Lv " + p.level + " · ⚡ " + p.pw + " · " + recordOf(p) : "—";
  $("petUpkeep").textContent = p.hatched ? p.ap + " · " + rawToNado(G.feedCost(BLOCKS_PER_DAY, p.ap)) + " NADO/day" : "decided at hatch";
  if ($("petInvested")) $("petInvested").textContent = p.hatched || p.tf ? rawToNado(p.tf) + " NADO" : "—";
  if ($("petGene")) { $("petGene").textContent = p.gs ? "0x" + p.gene.toString(16) : "—"; $("petGene").title = p.gs || ""; }
  // life bar
  const lb = lifeBlocks(p), pct = lb == null ? 0 : Math.max(0, Math.min(100, 100 * lb / G.BELLY_CAP));
  $("lifeBar").className = "bar" + (p.dead ? " crit" : lb < BLOCKS_PER_DAY / 6 ? " crit" : lb < BLOCKS_PER_DAY ? " low" : "");
  $("lifeBar").firstElementChild.style.width = pct + "%";
  $("lifeLabel").textContent = p.dead ? "☠ starved / fallen" : lifeText(p) + (lb != null && lb < BLOCKS_PER_DAY && !p.dead ? " — FEED SOON" : "");
  $("petMsg").textContent = p.dead ? (p.hatched ? "This pet has died. Its record stays on-chain forever." : "This egg expired unhatched.")
    : !p.hatched ? (p.hatchReady ? "The gene blocks are final — hatch it!" : p.stale ? "Its gene block was pruned — re-roll below." : "Incubating… the chain is minting its gene blocks (~2 min).") : "";
  // sections
  const canOffer = p.hatched && !p.dead && !p.mine && dapp.me;
  const incoming = Object.values(OFFERS).filter((o) => o.state === 1 && o.pet === p.id);
  gate({ lifeWrap: true, hatchRow: !p.hatched && !p.dead, feedRow: p.hatched && !p.dead,
         statsWrap: p.hatched, challengeRow: p.hatched && !p.dead && !p.mine && dapp.me,
         ownRow: p.mine && !p.dead, buyRow: !!p.price && !p.mine && !p.dead && dapp.me,
         offerRow: canOffer, offersInRow: p.mine && !p.dead && incoming.length > 0 });
  if (canOffer) {
    const mine = Object.values(OFFERS).filter((o) => o.state === 1 && o.pet === p.id && o.buyer === dapp.me);
    $("myOffersOut").innerHTML = mine.length
      ? "Your open offer: " + mine.map((o) => rawToNado(o.value) + " NADO <button class='mini ghost' data-canceloffer='" + o.id + "'>withdraw</button>").join(" ")
      : "Bid any amount; it's escrowed and refunded if you withdraw or it's never accepted.";
    $("myOffersOut").querySelectorAll("[data-canceloffer]").forEach((b) => b.onclick = () => cancelOffer(b.dataset.canceloffer));
  }
  if (p.mine && !p.dead && incoming.length) {
    incoming.sort((a, b) => b.value - a.value);
    $("offersInList").innerHTML = incoming.map((o) => '<div class="btl">💬 <b>' + rawToNado(o.value) + " NADO</b> from " + esc(disp(o.buyer))
      + ' <div class="act"><button class="mini primary" data-acceptoffer="' + o.id + '">Accept &amp; sell</button></div></div>').join("");
    $("offersInList").querySelectorAll("[data-acceptoffer]").forEach((b) => b.onclick = () => acceptOffer(b.dataset.acceptoffer, p.label));
  }
  if (p.price && !p.mine && !p.dead) {
    const busyBuy = dapp.busy("buy", "pid", p.id);
    $("btnBuy").textContent = busyBuy ? "⏳ Buying — confirming on-chain…" : "🛒 Buy " + p.label + " · " + rawToNado(p.price) + " NADO";
    $("btnBuy").disabled = busyBuy;
  }
  if (p.mine && !p.dead) {
    $("btnList").classList.toggle("hidden", !!p.price);
    $("listPrice").classList.toggle("hidden", !!p.price);
    $("btnUnlist").classList.toggle("hidden", !p.price);
    if (p.price) $("btnUnlist").textContent = "Remove listing (ask " + rawToNado(p.price) + " NADO)";
  }
  if (!p.hatched && !p.dead) {
    $("btnHatch").disabled = !p.hatchReady || dapp.busy("hatch", "pid", p.id);
    $("btnHatch").classList.toggle("pulse", p.hatchReady && !dapp.busy("hatch", "pid", p.id));
    $("btnHatch").textContent = dapp.busy("hatch", "pid", p.id) ? "⏳ Hatching — confirming on-chain…" : "🐣 Hatch the egg";
    $("hatchHint").textContent = p.hatchReady ? "Anyone may hatch it; the animal was already decided by blocks " + p.bh + "–" + (p.bh + 1) + "."
      : "Hatchable once blocks " + p.bh + "–" + (p.bh + 1) + " are finalized" + (dapp.cursor ? " (now at " + dapp.cursor + ", ~" + blocksToTime(Math.max(0, p.bh + 1 - dapp.cursor)) + " + finality)" : "") + ".";
    $("btnRebirth").classList.toggle("hidden", !(p.stale && p.mine));
  }
  if (p.hatched && !p.dead) {
    $("feed1d").textContent = "+1 day · " + rawToNado(G.feedCost(BLOCKS_PER_DAY, p.ap)) + " N";
    $("feed3d").textContent = "+3 days · " + rawToNado(G.feedCost(3 * BLOCKS_PER_DAY, p.ap)) + " N";
    const fillB = Math.max(0, G.BELLY_CAP - (lb || 0) - 60);
    $("feedFull").textContent = "fill belly · " + rawToNado(G.feedCost(fillB, p.ap)) + " N";
    $("feedFull").dataset.blocks = fillB;
    $("feedHint").textContent = "Appetite " + p.ap + ": 1 NADO buys " + (G.feedBlocks(10n ** 10n, p.ap) / BLOCKS_PER_DAY).toFixed(2) + " days. Anyone may feed any pet — a gift.";
  }
  if (p.hatched) {
    $("statList").innerHTML = G.STAT_NAMES.map((_n, i) => statRow(p, i)).join("");
    $("statList").querySelectorAll("[data-train]").forEach((b) => b.onclick = () => train(p.id, parseInt(b.dataset.train, 10)));
    const tp = $("trainPending");
    if (p.th && local.trainPending === 1) { const l = L(); l[p.id].trainPending = 2; Lsave(l); local.trainPending = 2; }   // session seen on-chain
    if (p.th) {
      const ready = dapp.cursor != null && dapp.cursor >= p.th + 1 && dapp.bh(p.th) && dapp.bh(p.th + 1);
      const i = p.ti - 1;
      tp.classList.remove("hidden");
      tp.innerHTML = "🏋 Training <b>" + G.STAT_NAMES[i] + "</b>… " + (ready
        ? '<button class="mini primary" id="btnTrainRes">Reveal the result</button>'
        : "result locked in blocks " + p.th + "–" + (p.th + 1) + " (~" + blocksToTime(Math.max(0, p.th + 1 - (dapp.cursor || p.th))) + " + finality)");
      if (ready) $("btnTrainRes").onclick = () => trainResolve(p.id);
    } else {
      tp.classList.add("hidden");
      if (local.trainPending === 2 && p.tr) {     // its resolve just landed — announce it once
        const ok = p.tr === 1;
        alertBar(ok ? "🎉 Training paid off — " + p.label + " got +1 " + (local.trainStat || "to a stat") + "!" : "Training didn't stick this time — the fee is spent, try again.");
        const l = L(); delete l[p.id].trainPending; delete l[p.id].trainStat; Lsave(l);
      }
    }
    $("trainHint").innerHTML = '<span style="color:var(--accent2)">▮ base</span> (locked at hatch) · <span style="color:var(--gold)">▮ trained</span> (your gains). '
      + "Each attempt costs 0.5 NADO. Success chance = 100·K/(K+stat), K=" + G.trainK(p.sp) + " for a " + (sp ? esc(sp.rarity.toLowerCase()) : "") + " — the better the stat, the harder the gain (no cap, ever). Rarer species train easier.";
  }
  if (p.hatched && !p.dead && !p.mine && dapp.me) {
    const mine = myPets().filter((x) => x.hatched && !x.dead);
    $("myPetSel").innerHTML = mine.length ? mine.map((x) => `<option value="${x.id}">${esc(x.label)} · ⚡${x.pw}</option>`).join("") : '<option value="">no living pet — adopt below</option>';
  }
  if (p.mine && !p.dead) {
    const named = !!p.nm;
    $("nameInput").classList.toggle("hidden", named);
    $("btnRename").classList.toggle("hidden", named);
  }
  shareInvite("pet", p.id, (p.hatched ? "Meet " + p.label + ", my " + sp.rarity + " " + sp.name + " on NADO Pets:" : "My NADO Pets egg is incubating:"));
  maybePlayHatch(p);
}
function petCard(p, sel) {
  const sp = p.hatched ? G.SPECIES[p.sp] : null;
  const cls = "pcard" + (p.dead ? " dead" : "") + (!p.hatched ? " egg" : "") + (sel ? " sel" : "");
  return `<div class="${cls}" data-pet="${p.id}">${petArt(p, "")}
    <div class="pn">${p.hatched ? sp.emoji + " " : "🥚 "}${esc(p.label)}</div>
    <div class="po">${p.hatched ? `<span style="color:${sp.color}">${sp.rarity}</span> · ⚡${p.pw}` : "incubating"}${p.dead ? " · ✝" : ""}</div>
    <div class="po">${p.price && !p.dead ? `🏷 ${rawToNado(p.price)} NADO` : esc(disp(p.owner))}</div></div>`;
}
// grid view state: search + sort + how many are shown (pagination keeps 10k pets browsable)
const VIEW = { g: { q: "", sort: "new", n: 24 }, m: { q: "", sort: "priceAsc", n: 24 } };
const SORTS = {
  new: (a, b) => b.bh - a.bh,                                        // mint block = age
  rarity: (a, b) => b.sp - a.sp || b.pw - a.pw,
  power: (a, b) => b.pw - a.pw,
  level: (a, b) => b.level - a.level || b.pw - a.pw,
  priceAsc: (a, b) => a.price - b.price,
  priceDesc: (a, b) => b.price - a.price,
};
function matches(p, q) {
  if (!q) return true;
  q = q.toLowerCase().replace(/^[@#]/, "");
  return (p.nm && p.nm.toLowerCase().includes(q)) || p.id.includes(q)
    || (p.hatched && G.SPECIES[p.sp].name.toLowerCase().includes(q))
    || (p.hatched && G.SPECIES[p.sp].rarity.toLowerCase().includes(q))
    || p.owner.toLowerCase().startsWith(q) || disp(p.owner).toLowerCase().replace(/^@/, "").includes(q);
}
function grid(el, moreBtn, list, v, empty) {
  const shown = list.slice(0, v.n);
  el.innerHTML = shown.map((p) => petCard(p, String(active) === p.id)).join("") || `<span class="dim small">${empty}</span>`;
  moreBtn.classList.toggle("hidden", list.length <= v.n);
  if (list.length > v.n) moreBtn.textContent = "Show more (" + (list.length - v.n) + " more)";
}
function renderGrids() {
  const all = Object.values(PETS);
  const mine = myPets();
  const pendings = Object.keys(L()).filter((pid) => !PETS[pid]);
  $("myPetGrid").innerHTML = (mine.map((p) => petCard(p, String(active) === p.id)).join("")
    + pendings.map((pid) => `<div class="pcard egg pending" data-pet="${pid}">${eggSvg("egg-idle", 0)}<div class="pn">🥚 #${String(pid).slice(-4)}</div><div class="po">confirming ⏳</div></div>`).join(""))
    || '<span class="dim small">No pets yet — adopt your first egg below.</span>';
  $("petCount").textContent = all.length ? "— " + all.length : "";
  grid($("gallery"), $("btnMoreGallery"),
    all.filter((p) => matches(p, VIEW.g.q)).sort(SORTS[VIEW.g.sort] || SORTS.new),
    VIEW.g, "No pets exist yet. Yours could be the very first.");
  grid($("marketGrid"), $("btnMoreMarket"),
    all.filter((p) => p.price && !p.dead && matches(p, VIEW.m.q)).sort(SORTS[VIEW.m.sort] || SORTS.priceAsc),
    VIEW.m, VIEW.m.q ? "No listed pet matches your search." : "Nothing for sale right now — list one of yours from its pet card.");
  document.querySelectorAll("[data-pet]").forEach((el) => el.onclick = () => { active = el.dataset.pet; render(); try { $("activePet").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
  // hall of fame
  const top = Object.values(PETS).filter((p) => p.hatched && !p.dead).sort((a, b) => b.pw - a.pw).slice(0, 10);
  $("fameList").innerHTML = top.length ? '<table class="score"><thead><tr><th>#</th><th>Pet</th><th>Rarity</th><th>Power</th><th>Owner</th></tr></thead><tbody>'
    + top.map((p, i) => `<tr${p.mine ? ' class="me"' : ""}><td>${i + 1}</td><td>${G.SPECIES[p.sp].emoji} ${esc(p.label)}</td><td style="color:${G.SPECIES[p.sp].color}">${G.SPECIES[p.sp].rarity}</td><td class="mono">⚡${p.pw} · Lv${p.level}</td><td>${esc(disp(p.owner))}</td></tr>`).join("") + "</tbody></table>"
    : '<span class="dim small">No living pets yet.</span>';
}
function renderBattles() {
  const rows = [];
  const mineIds = new Set(myPets().map((p) => p.id));
  const bs = Object.values(BATTLES).sort((a, b) => Number(b.id) - Number(a.id));
  for (const b of bs) {
    const pa = PETS[b.a], pb = PETS[b.b]; if (!pa || !pb) continue;
    const inc = mineIds.has(b.b), out = mineIds.has(b.a), involved = inc || out;
    const stakeTxt = b.ws ? rawToNado(b.ws) + " NADO each" : "no stake (still deadly)";
    if (b.wn === 1 && (involved || String(activeBattle) === b.id)) {
      rows.push(`<div class="btl"><span class="who">${esc(pa.label)}</span> ⚔ challenges <span class="who">${esc(pb.label)}</span> · ${stakeTxt}
        <div class="act">${inc ? `<button class="mini primary" data-acc="${b.id}">Accept the battle</button>` : ""}
        ${out ? `<button class="mini ghost" data-cxl="${b.id}">Withdraw</button>` : ""}
        <button class="mini ghost" data-view="${b.id}">View</button></div></div>`);
    } else if (b.wn === 2 && (involved || String(activeBattle) === b.id)) {
      rows.push(`<div class="btl">⚡ <span class="who">${esc(pa.label)}</span> vs <span class="who">${esc(pb.label)}</span> — fighting! · ${stakeTxt}
        <div class="act"><button class="mini primary" data-view="${b.id}">Watch the battle</button></div></div>`);
    } else if (b.wn === 3 && involved && rows.length < 14 && b.ww) {
      const w = PETS[b.ww];
      rows.push(`<div class="btl">✓ <span class="who">${esc(w ? w.label : "#" + b.ww)}</span> won ${esc(pa.label)} vs ${esc(pb.label)}${b.wd ? ` · ☠ ${esc((PETS[b.wd] || {}).label || "#" + b.wd)} died` : ""}
        <div class="act"><button class="mini ghost" data-view="${b.id}">Replay</button></div></div>`);
    }
  }
  $("battleList").innerHTML = rows.join("") || '<span class="dim small">No challenges. Pick a pet in the gallery and challenge it.</span>';
  document.querySelectorAll("[data-acc]").forEach((el) => el.onclick = () => acceptBattle(el.dataset.acc));
  document.querySelectorAll("[data-cxl]").forEach((el) => el.onclick = () => cancelBattle(el.dataset.cxl));
  document.querySelectorAll("[data-view]").forEach((el) => el.onclick = () => { activeBattle = el.dataset.view; battlePlaying = null; render(); try { $("arenaCard").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
}
function renderArena() {
  gate({ arenaCard: activeBattle != null });
  if (activeBattle == null) return;
  const b = BATTLES[activeBattle], hint = $("arenaHint");
  $("arenaId").textContent = "#" + activeBattle;
  if (!b) { hint.textContent = dapp.whereIs("battle", activeBattle); return; }
  const pa = PETS[b.a], pb = PETS[b.b]; if (!pa || !pb) return;
  if (battlePlaying !== activeBattle) {           // (re)stage the fighters, idle
    $("arenaL").innerHTML = pa.hatched ? petBody(pa, "pet-idle") : eggSvg("egg-idle", 0);
    $("arenaR").innerHTML = pb.hatched ? petBody(pb, "pet-idle") : eggSvg("egg-idle", 0);
  }
  $("arenaLName").textContent = pa.label; $("arenaRName").textContent = pb.label;
  $("arenaLPow").textContent = "⚡ " + pa.pw + " · " + recordOf(pa); $("arenaRPow").textContent = "⚡ " + pb.pw + " · " + recordOf(pb);
  const effA = effOf(pa), effB = effOf(pb);
  const res = (b.wh && effA && effB) ? G.battleOf(dapp.bh(b.wh), dapp.bh(b.wh + 1), Number(b.id), effA, effB) : null;
  gate({ btnResolve: b.wn === 2 && !!res && !dapp.busy("resolveb", "bid", b.id),
         btnCancelBattle: b.wn === 1 && pa.mine,
         btnRefundBattle: b.wn === 2 && !res && dapp.cursor != null && dapp.cursor > b.wh + G.STALE });
  $("btnResolve").onclick = () => resolveBattle(b.id);
  $("btnCancelBattle").onclick = () => cancelBattle(b.id);
  $("btnRefundBattle").onclick = () => refundBattle(b.id);
  if (b.wn === 1) { $("arenaVerdict").textContent = "Awaiting consent…"; hint.textContent = "The challenged pet's owner must accept (matching the stake) before the chain schedules the fight."; }
  else if (b.wn === 2 && !res) { $("arenaVerdict").textContent = "⚡ Fight locked to blocks " + b.wh + "–" + (b.wh + 1); hint.textContent = "Nobody can know the outcome until those blocks are finalized (~" + blocksToTime(Math.max(0, b.wh + 1 - (dapp.cursor || b.wh))) + " + finality)."; }
  else if ((b.wn === 2 && res) || b.wn === 3) {
    const aWins = b.wn === 3 ? b.ww === b.a : res.aWins;
    const died = b.wn === 3 ? b.wd : (res.dies ? (aWins ? b.b : b.a) : 0);
    playBattle(b, pa, pb, aWins, died, res);
    hint.textContent = b.wn === 3 ? "Settled on-chain." + (b.ws ? "" : " (friendly match — no stakes moved)") : "The chain has decided — settling records it and pays the pot" + (b.ws ? " (" + rawToNado(2 * b.ws) + " NADO) " : " ") + "to the winner's owner. Anyone may settle.";
  }
}
function playBattle(b, pa, pb, aWins, died, res) {
  if (battlePlaying === b.id) return;
  battlePlaying = b.id;
  const L_ = $("arenaL"), R_ = $("arenaR"), V = $("arenaVerdict"), LOG = $("arenaLog");
  const hpL = $("arenaLHP"), hpR = $("arenaRHP");
  const step = (el, cls, other, hurt) => { el.classList.remove("lungeL", "lungeR", "hitshake"); void el.offsetWidth; el.classList.add(cls); if (hurt) { other.classList.add("hitshake"); setTimeout(() => other.classList.remove("hitshake"), 380); } };
  // if we have the real turn log, play it out; otherwise fall back to a short flourish
  const log = res && res.log ? res.log.filter((e) => e.dmg > 0 || e.hit) : null;
  const hp0max = res ? res.hpA : 100, hp1max = res ? res.hpB : 100;
  if (hpL) hpL.style.width = "100%"; if (hpR) hpR.style.width = "100%";
  V.textContent = "⚔ FIGHT!"; if (LOG) LOG.textContent = "";
  let t = 300;
  const turns = log && log.length ? log.slice(0, 14) : [{ atk: aWins ? 0 : 1, dmg: 1, hit: 1 }];
  turns.forEach((e) => {
    setTimeout(() => {
      if (e.atk === 0) step(L_, "lungeL", R_, e.hit); else step(R_, "lungeR", L_, e.hit);
      if (res) {
        if (hpL) hpL.style.width = Math.max(0, 100 * e.h0 / hp0max) + "%";
        if (hpR) hpR.style.width = Math.max(0, 100 * e.h1 / hp1max) + "%";
      }
      if (LOG) LOG.textContent = (e.atk === 0 ? pa.label : pb.label) + (e.hit ? " hits for " + e.dmg : " misses");
    }, t);
    t += 560;
  });
  setTimeout(() => {
    const w = aWins ? L_ : R_, l = aWins ? R_ : L_;
    w.classList.add("winglow");
    if (died) l.innerHTML = graveSvg(); else l.classList.add("faint");
    const wp2 = aWins ? pa : pb, lp = aWins ? pb : pa;
    if (LOG) LOG.textContent = "";
    V.innerHTML = "🏆 <b>" + esc(wp2.label) + "</b> wins!" + (died
      ? " ☠ <b>" + esc(lp.label) + "</b> fell in battle."
      : " <b>" + esc(wp2.label) + "</b>'s owner claims <b>" + esc(lp.label) + "</b>.");
  }, t + 300);
}
let hatchDone = {};
function maybePlayHatch(p) {
  if (!p.hatched || hatchPlaying || hatchDone[p.id]) return;
  const l = L();
  if (!(l[p.id] && l[p.id].hatchPending)) return;
  delete l[p.id].hatchPending; Lsave(l);
  hatchDone[p.id] = 1; hatchPlaying = true;
  const stage = $("petStage");
  stage.innerHTML = eggSvg("egg-shake", 0);
  let t = 900;
  [1, 2, 3].forEach((c, i) => setTimeout(() => { stage.innerHTML = eggSvg("egg-shake", c); }, t + i * 450));
  t += 3 * 450 + 250;
  setTimeout(() => { stage.innerHTML = eggSvg("", 4); }, t);          // shells fly
  setTimeout(() => {
    stage.innerHTML = petBody(p, "pet-idle pet-pop flash");
    for (let s = 0; s < 8; s++) {
      const sp = document.createElement("span"); sp.className = "spark"; sp.textContent = ["✨", "⭐", "💫"][s % 3];
      sp.style.setProperty("--dx", (Math.cos(s * 0.785) * 70) + "px"); sp.style.setProperty("--dy", (Math.sin(s * 0.785) * 70 - 20) + "px");
      stage.style.position = "relative"; sp.style.left = "50%"; sp.style.top = "45%"; stage.appendChild(sp);
      setTimeout(() => sp.remove(), 1100);
    }
    const spc = G.SPECIES[p.sp], coat = G.coatOf(p.gene, p.sp);
    alertBar("🎉 It's a " + spc.rarity.toUpperCase() + " — " + coat.name + " " + spc.emoji + " " + spc.name
      + (coat.shiny ? " ✦ SHINY" : "") + "! Its coat, colour and 10 abilities are all written into its gene, locked forever. Name it, feed it, train it.");
  }, t + 600);
  setTimeout(() => { hatchPlaying = false; render(); }, t + 2400);
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ bankroll: signedIn, myPets: signedIn, adopt: signedIn, battlesCard: signedIn });
  $("btnMint").disabled = dapp.busy("mint");
  $("btnMint").textContent = dapp.busy("mint") ? "⏳ Egg confirming on-chain…" : "🥚 Adopt an egg · burn 1 NADO";
  if ($("burnTally")) $("burnTally").textContent = BURNED > 0n ? "🔥 " + rawToNado(BURNED) + " NADO burned by pets so far — adoption, food and training all destroy supply." : "";
  renderActive(); renderGrids(); renderBattles(); renderArena();
}

// ---- wire + boot -----------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  $("btnMint").onclick = mint;
  $("btnHatch").onclick = () => hatch(active);
  $("btnRebirth").onclick = () => rebirth(active);
  $("btnFeed").onclick = () => { const raw = nadoToRaw($("feedAmt").value); if (!raw) return alertBar("Enter how much NADO to feed."); feed(active, raw); };
  const preset = (blocks) => { const p = PETS[active]; if (p) feed(active, G.feedCost(blocks, p.ap)); };
  $("feed1d").onclick = () => preset(BLOCKS_PER_DAY);
  $("feed3d").onclick = () => preset(3 * BLOCKS_PER_DAY);
  $("feedFull").onclick = () => preset(parseInt($("feedFull").dataset.blocks || "0", 10));
  $("btnChallenge").onclick = () => challenge(active);
  $("btnRename").onclick = () => nameIt(active);
  $("btnTransfer").onclick = () => transfer(active);
  $("btnList").onclick = () => listPet(active);
  $("btnUnlist").onclick = () => unlistPet(active);
  $("btnBuy").onclick = () => buyPet(active);
  $("btnOffer").onclick = () => makeOffer(active);
  const wireView = (v, q, s, more) => {
    $(q).oninput = () => { v.q = $(q).value.trim(); v.n = 24; renderGrids(); };
    $(s).onchange = () => { v.sort = $(s).value; v.n = 24; renderGrids(); };
    $(more).onclick = () => { v.n += 48; renderGrids(); };
  };
  wireView(VIEW.g, "galleryQ", "gallerySort", "btnMoreGallery");
  wireView(VIEW.m, "marketQ", "marketSort", "btnMoreMarket");
}
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.pid != null) active = pend.pid;
  if (pend && pend.bid != null) activeBattle = pend.bid;
  if (ok && pend && pend.phase === "train") { const l = L(); if (l[pend.pid]) { l[pend.pid].trainPending = 1; Lsave(l); } }
  $("status").textContent = statusLabel(pend, ok, err, {
    mint: "Egg adopted — confirming on-chain (~1 min)…", hatch: "Hatching — confirming on-chain…",
    feed: "Nom nom — the meal is confirming…", train: "Training session booked — confirming…",
    trainres: "Revealing the result — confirming…", challenge: "Challenge sent — the owner must accept it.",
    accept: "Battle on! The chain decides in ~2 blocks…", resolveb: "Settling the battle…",
    cancelb: "Withdrawing…", rename: "Naming — it's for life; confirming…", xfer: "Transferring your pet — confirming…",
    market: "Updating the listing — confirming…", buy: "Buying — confirming on-chain (~1 min)…",
    offer: "Offer sent — escrowed until the owner accepts.", offeract: "Confirming…" });
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR();
  orderCards(["activePet", "arenaCard", "battlesCard", "myPets", "adopt", "marketCard", "galleryCard", "fameCard", "walletcard", "bankroll"]);
  const q = new URLSearchParams(location.search);
  if (q.get("pet")) active = q.get("pet");
  if (q.get("battle")) activeBattle = q.get("battle");
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
boot();

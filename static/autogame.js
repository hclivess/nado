// autogame.js — NADO Autogame: a side-scrolling warrior march paced by the chain, on the shared game SDK.
//
// One step per L1 block. A leg is 16 steps: BHASH(lh) generates the TERRAIN (drawn on the road strip below,
// already committed) and BHASH(lh+16) rolls the DICE sixteen blocks later. You queue reactions in between,
// which is the whole reason the game has skill in it and the whole reason nobody can cheat it.
//
// Everything generic lives in nadodapp.js — the wallet session, signing, storage reads, the click-time
// pending gate, alerts, the leaderboard chrome. What is here is only Autogame's own: reading its storage
// map, rendering the world, editing a plan, and the four calls that move a run.
//
// The step function is NOT here. It lives in autogame-engine.js, which is the same program as
// execnode/games/autogame.py and is diff-tested against it (tests/autogame_contract_test.py). The client
// uses it to preview and to animate; the contract remains the authority, and wherever the two disagree the
// chain wins and the view snaps to it.
import {
  NadoDapp, rawToNado, randId, _m, $, base, gate, canPay, alertBar, notify, okBar, wireWallet,
  renderWallet, resolveAliases, disp, share, algHashn, ALG_P, esc, blocksToTime, lsLoad, lsSave,
} from "./nadodapp.js";
import * as E from "./autogame-engine.js";
import { drawWarrior, unpackItem, MATERIALS, FRAME_W, FRAME_H } from "./autogame-art.js";

const CID = "e1642eac82cb17f08b43dc427ac2df1f";          // execnode/games/autogame.py (zkVM) — set by the deploy script
const dapp = new NadoDapp({ cid: CID, app: "Autogame" });
const P = ALG_P();
const BLOCK_SECS = 6;

// drawWarrior anchors the sprite's TOP-LEFT corner, but everything here thinks in ground coordinates —
// the warrior stands ON the road line, and the gear panel stands him on its floor. Converting once, here,
// keeps that mismatch from being re-derived (wrongly) at each call site.
const footX = (x, scale) => Math.round(x - (FRAME_W * scale) / 2);
const footY = (y, scale) => Math.round(y - FRAME_H * scale);

const t = (k, d, v) => (window.t ? window.t("autogame." + k, d, v) : d);

const SLOT_NAMES = ["Weapon", "Helm", "Body", "Shield", "Boots", "Cloak"];
const MAT_NAMES = ["bronze", "iron", "steel", "silver", "obsidian", "gold", "meteoric", "living"];
const TILE_ICON = ["🛣️", "⚔️", "💀", "🔥", "📦", "⛲", "🔨", "🔀", "💎", "👑"];
const ACT_ICON = ["", "⚡", "🛡️", "💨", "🧪", "🏃", "🔥", "🔀"];
const ACT_KEY = ["default", "strike", "guard", "dodge", "potion", "sprint", "rest", "right"];
const STANCE_KEY = ["balanced", "aggressive", "guarded", "evasive"];

let sto = null;                 // last contract storage view
let myId = null;                // my run id
let chain = null;               // the run exactly as the contract has it
let view = null;                // the run the ANIMATOR is showing; catches up to `chain`, snaps on mismatch
let road = [];                  // peekLeg() of the pending leg — the visible, committed terrain
let plan = new Array(E.LEG).fill(0);
let planAgg = 1;
let brush = E.A_STRIKE;         // which reaction a tile tap assigns
let queue = [];                 // settled step events waiting to be animated
let camera = 0;                 // fractional depth the camera is at
let lastLegSeen = -1;
// A committed plan word is HASH-KEYED on chain, so it is not in the storage view and the animator cannot
// read back what you queued. Your own browser knows, though — remembering it here is what lets a planned
// leg replay with your actual reactions instead of mismatching and snapping to the chain.
const LS_PLANS = "nado_autogame_plans";
const planKey = (run, leg) => `${run}:${leg}`;
const rememberPlan = (run, leg, word, agg) => {
  const all = lsLoad(LS_PLANS);
  all[planKey(run, leg)] = { word: String(word), agg, ts: Date.now() };
  for (const k of Object.keys(all)) {            // keep it small: a chapter is 32 legs
    if (Date.now() - (all[k].ts || 0) > 6 * 3600 * 1000) delete all[k];
  }
  lsSave(LS_PLANS, all);
};
const recallPlan = (run, leg) => lsLoad(LS_PLANS)[planKey(run, leg)] || null;

// ── reading the chain ───────────────────────────────────────────────────────────────────────────
/** My run: the live one if I have it, else my most recent. The contract's `ra` map is the owner index. */
function findMyRun(s) {
  // decode_view has no named-index output: the index only supplies the KEY SET for the maps, so the run
  // ids are the keys of any map. `ra` is the right one because every run has an owner, while a map like
  // `xp` is absent for a run still sitting at zero (a zero slot is a deleted slot).
  const ids = Object.keys(s.ra || {}).map(Number).filter((n) => n > 0);
  const mine = ids.filter((id) => String((s.ra || {})[id] || "").toLowerCase() === String(dapp.me || "").toLowerCase());
  if (!mine.length) return null;
  const live = mine.find((id) => Number((s.av || {})[id]) === 1 && !Number((s.dn || {})[id]) && !Number((s.rt || {})[id]));
  return live != null ? live : mine[mine.length - 1];
}

/** BHASH(h) as the contract sees it: the L1 hash reduced into the field. */
function hashField(h) {
  const hex = dapp.bh(h);
  return hex ? BigInt("0x" + hex) % P : null;
}

async function refreshAll() {
  await dapp.refresh();
  const s = await dapp.storage({ append: ["ra"] });
  if (!s) { render(); return; }
  sto = s;
  myId = findMyRun(s);
  chain = myId != null ? E.runFromStorage(s, myId) : null;

  if (chain) {
    // the terrain hash (already final) and the rolling hash (may not exist yet). Provisional is safe: the
    // contract re-validates both, so a reorg just replays the leg.
    const want = [];
    if (dapp.cursor != null && dapp.cursor >= chain.lh) want.push(chain.lh);
    if (dapp.cursor != null && dapp.cursor >= chain.nh) want.push(chain.nh);
    if (want.length) await dapp.blockHashes(want, { fast: true });
    syncView();
    rebuildRoad();
  }

  dapp.settleInflight((f) => {
    if (!chain) return false;
    switch (f.phase) {
      case "begin": return myId != null;
      case "plan": return Number(chain.leg) > Number(f.leg) || planOnChain(f.leg);
      case "advance": return Number(chain.leg) > Number(f.leg);
      case "retire": return !!chain.retired;
      case "stance": return Number(chain.stance) === Number(f.want);
      case "focus": return Number(chain.focus) === Number(f.want);
      case "orders": return Number(chain.healpct) === Number(f.want);
      default: return true;
    }
  });
  await resolveAliases([dapp.me].filter(Boolean));
  render();
  maybeAutoAdvance();
}

/** A committed plan is invisible in the flat storage view (it is hash-keyed), so a landed `plan` is
 *  confirmed by the leg advancing past it — or, while it is still pending, by nothing at all. */
function planOnChain(leg) { return false; }

/**
 * Walk `view` forward to wherever the chain is, replaying each settled leg through the engine so the
 * animator has per-step events to show. If the replay does not land exactly where the contract says, the
 * chain wins and the view snaps — a pretty animation that disagrees with settlement is a lie.
 */
function syncView() {
  if (!view || view.depth > chain.depth) { view = { ...chain, gear: [...chain.gear], mats: [...chain.mats] }; queue = []; camera = view.depth; lastLegSeen = chain.leg; return; }
  while (view.leg < chain.leg) {
    const tileH = hashField(view.lh), rollH = hashField(view.nh);
    if (tileH == null || rollH == null) break;                 // hashes not cached yet; try next poll
    // Replay with the plan this browser committed for that leg, if it has one. Without it a planned leg
    // never reproduces the contract's state, so the animation is thrown away and the view snaps — the
    // player would watch their own carefully queued reactions vanish.
    const p = recallPlan(myId, view.leg);
    const evs = E.playLeg(algHashn, view, myId, tileH, rollH, p ? p.word : null, p ? p.agg : 1);
    view.leg += 1;
    view.lh = view.nh; view.nh = view.nh + E.LEG;
    queue.push(...evs);
  }
  const same = view.depth === chain.depth && view.hp === chain.hp && view.xp === chain.xp;
  if (!same) {                                                  // replay diverged (queued reactions we
    queue = [];                                                 // cannot see) — trust the chain, not us
    view = { ...chain, gear: [...chain.gear], mats: [...chain.mats] };
    camera = Math.max(camera, view.depth - E.LEG);
  }
}

function rebuildRoad() {
  const tileH = hashField(chain.lh);
  road = tileH == null ? [] : E.peekLeg(algHashn, chain, myId, tileH);
  if (chain.leg !== lastLegSeen) { plan = new Array(E.LEG).fill(0); lastLegSeen = chain.leg; }
}

// ── the world ───────────────────────────────────────────────────────────────────────────────────
// Presentation only — none of this is consensus. It is derived from the same committed hashes so the
// picture and the rules agree, but the contract deliberately never computes it (doc/autogame.md §4).
const BIOMES = [
  { name: "plains", sky: ["#1b3a4b", "#2d5f6b"], hill: ["#1d3b2e", "#16302a"], ground: "#233a2b" },
  { name: "forest", sky: ["#16302c", "#245043"], hill: ["#143326", "#0f2a20"], ground: "#1b3324" },
  { name: "marsh", sky: ["#2a2f22", "#424a2f"], hill: ["#2b3320", "#212a19"], ground: "#2e3521" },
  { name: "ruins", sky: ["#2b2733", "#4a4356"], hill: ["#2e2a38", "#241f2c"], ground: "#332d3c" },
  { name: "ashlands", sky: ["#3a2320", "#5e3128"], hill: ["#33211d", "#281a17"], ground: "#3a2621" },
  { name: "underdark", sky: ["#12131f", "#1e2036"], hill: ["#171a2c", "#111324"], ground: "#1a1c2e" },
];
const biomeAt = (depth, scen) => BIOMES[(((depth / 64) | 0) + (scen % 3)) % BIOMES.length];

const smooth = (t) => t * t * (3 - 2 * t);
function skylineAt(x, seedRow) {
  // value noise: one control point per visible tile, smoothstep-interpolated, so the ridge is continuous
  // instead of jumping every block
  const i = Math.floor(x), f = x - i;
  const a = seedRow[((i % seedRow.length) + seedRow.length) % seedRow.length];
  const b = seedRow[(((i + 1) % seedRow.length) + seedRow.length) % seedRow.length];
  return a + (b - a) * smooth(f);
}

function drawWorld() {
  const cv = $("world"), ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.imageSmoothingEnabled = false;
  const depth = Math.floor(camera);
  const frac = camera - depth;
  const night = E.isNight(depth);
  const scen = road.length ? road[Math.min(road.length - 1, Math.max(0, depth - (chain ? chain.depth : 0)))].scen : 0;
  const bio = biomeAt(depth, scen);

  // sky
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, night ? "#080b14" : bio.sky[0]);
  g.addColorStop(1, night ? "#131a26" : bio.sky[1]);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  // stars at night — deterministic from depth so they do not crawl
  if (night) {
    ctx.fillStyle = "rgba(230,237,243,.5)";
    for (let k = 0; k < 40; k++) {
      const sx = ((k * 7919 + depth * 13) % W), sy = (k * 5261) % (H * 0.45);
      ctx.fillRect(sx, sy, 1, 1);
    }
  }

  // three parallax ridges from the visible tiles' scenery values
  const rows = road.length ? road.map((t) => t.scen) : [4096];
  const TILE = 44;                                     // pixels per step at 1x
  for (let layer = 0; layer < 3; layer++) {
    const par = 0.25 + layer * 0.3;
    const base = H * (0.45 + layer * 0.09);
    const amp = 26 - layer * 7;
    ctx.fillStyle = layer < 2 ? bio.hill[layer % 2] : bio.ground;
    ctx.beginPath(); ctx.moveTo(0, H);
    for (let px = 0; px <= W; px += 4) {
      const wx = (camera + px / TILE) * par + layer * 3.7;
      const n = (skylineAt(wx, rows) % 4096) / 4096;
      ctx.lineTo(px, base - n * amp);
    }
    ctx.lineTo(W, H); ctx.closePath(); ctx.fill();
  }

  // the road itself
  const GY = Math.round(H * 0.80);
  ctx.fillStyle = bio.ground; ctx.fillRect(0, GY, W, H - GY);
  ctx.fillStyle = "rgba(0,0,0,.25)"; ctx.fillRect(0, GY, W, 2);

  // tile markers scrolling past — what is coming, in world space
  const heroX = Math.round(W * 0.30);
  if (chain) {
    for (const t of road) {
      const x = heroX + Math.round((t.depth - camera) * TILE);
      if (x < -TILE || x > W + TILE) continue;
      if (t.tile === E.ROAD) continue;
      ctx.font = "20px system-ui"; ctx.textAlign = "center";
      ctx.globalAlpha = t.depth < camera ? 0.25 : 1;
      ctx.fillText(TILE_ICON[t.tile], x, GY - 6);
      ctx.globalAlpha = 1;
    }
    ctx.textAlign = "left";
  }

  // the warrior — always at the same screen x; the world moves, not him
  const frame = Math.floor((performance.now() / 140) % 4);
  const hurt = view && view.hp * 4 < view.maxhp;
  drawWarrior(ctx, footX(heroX, 3), footY(GY + 2, 3), {
    gear: view ? view.gear : new Array(6).fill(0),
    frame, scale: 3, facing: 1, hurt, dead: view ? !view.alive : false,
    attacking: queue.length > 0 && (queue[0].tile === E.MONSTER || queue[0].tile === E.ELITE || queue[0].tile === E.BOSS),
  });

  // night veil / weather
  if (night) { ctx.fillStyle = "rgba(6,10,20,.35)"; ctx.fillRect(0, 0, W, H); }
}

// the animation loop: the camera walks toward the settled depth, popping one event per tile as it passes
function tick() {
  if (view) {
    const target = view.depth;
    if (camera < target - 0.001) {
      const speed = Math.min(0.06, 0.006 + (target - camera) * 0.012);   // catch up faster when behind
      const before = Math.floor(camera);
      camera = Math.min(target, camera + speed);
      if (Math.floor(camera) !== before && queue.length) showEvent(queue.shift());
    }
  }
  drawWorld();
  requestAnimationFrame(tick);
}

function showEvent(ev) {
  const bits = [];
  if (ev.gain) bits.push(`<span style="color:var(--gold)">+${ev.gain} renown</span>`);
  if (ev.dmg) bits.push(`<span style="color:var(--danger)">−${ev.dmg} hp</span>`);
  if (ev.drain) bits.push(`<span style="color:var(--win)">+${ev.drain} drained</span>`);
  if (ev.item) {
    const it = unpackItem(ev.item);
    bits.push(`<span style="color:var(--accent2)">${MAT_NAMES[it.mat]} ${SLOT_NAMES[ev.slot].toLowerCase()} T${it.tier}` +
      (it.affix ? ` <b class="aff">${E.AFFIX_NAMES[it.affix]}</b>` : "") + "</span>");
  }
  if (ev.banked) bits.push(`<b style="color:var(--win)">checkpoint — ${ev.banked} banked</b>`);
  if (ev.easy) bits.push('<span class="faint">easy win, no healing</span>');
  if (ev.auto) bits.push('<span class="faint">auto-drank</span>');
  if (ev.craft) bits.push(`<span class="faint">forged ${ev.craft === 1 ? "weapon" : "armour"} +1</span>`);
  if (ev.died) bits.push('<b style="color:var(--danger)">you fell</b>');
  if (ev.chapter) bits.push('<b style="color:var(--win)">the road ends — chapter complete</b>');
  const el = $("stagemsg");
  if (el) el.innerHTML = `${TILE_ICON[ev.tile]} ${bits.join(" · ") || '<span class="faint">quiet road</span>'}`;
}

// ── rendering the panels ────────────────────────────────────────────────────────────────────────
function render() {
  renderWallet(dapp);
  const r = view || chain;

  // HUD
  if (r) {
    $("hpTxt").textContent = `${r.hp} / ${r.maxhp}`;
    $("hpBar").style.width = Math.max(0, Math.min(100, (r.hp * 100) / r.maxhp)) + "%";
    $("stamTxt").textContent = `${r.stam} / ${E.STAM_MAX}`;
    $("stamBar").style.width = ((r.stam * 100) / E.STAM_MAX) + "%";
    $("xpTxt").textContent = E.score(r).toLocaleString();
    $("streakTxt").textContent = r.streak > 0 ? `×${((E.STREAK_DIV + r.streak) / E.STREAK_DIV).toFixed(2)} streak` : "";
    $("depthTxt").textContent = `${r.depth} / ${E.CHAPTER}`;
    $("rankTxt").textContent = E.rankOf(E.score(r));
    $("bankedTxt").textContent = r.banked.toLocaleString();
    $("riskTxt").textContent = E.csub(r.xp, r.banked).toLocaleString();
  }

  // gate() takes a MAP of {elementId: shouldBeVisible} and toggles the `hidden` class — it is not an
  // enable/disable helper. Calling it per-element did nothing at all, which is why every button stayed
  // clickable and a signed-out tap on "Set out" silently went nowhere.
  const live = !!(chain && chain.alive && !chain.done && !chain.retired);
  const canSettle = live && dapp.cursor != null && dapp.cursor >= chain.nh;
  const canPlan = live && dapp.cursor != null && dapp.cursor < chain.nh;
  gate({ beginBtn: !live, advBtn: live, retireBtn: live, planBtn: live });
  // "Set out" stays clickable while signed out ON PURPOSE: the click routes through canPay(), which raises
  // the SDK's sign-in bar. Hiding it would leave a signed-out visitor staring at a page with no way in.
  $("beginBtn").disabled = dapp.busy("begin");
  $("advBtn").disabled = !canSettle || dapp.busy("advance");
  $("planBtn").disabled = !canPlan || dapp.busy("plan");
  $("retireBtn").disabled = !live || !chain.depth || dapp.busy("retire");
  $("advBtn").title = canSettle ? "" : t("advWait", "The dice for this leg have not landed yet.");

  // the clock: how long until this leg can be settled
  if (chain && live && dapp.cursor != null) {
    const left = chain.nh - dapp.cursor;
    $("clockHint").innerHTML = left > 0
      ? t("clockWait", "This leg resolves in {n} blocks (~{time}). Your plan is locked in when it does.",
          { n: left, time: blocksToTime(left, BLOCK_SECS) })
      : t("clockReady", "The dice have landed — settle the leg to see what happened.");
  } else if (chain && !live) {
    $("clockHint").innerHTML = chain.done
      ? t("clockDone", "Chapter complete. The road bonus is yours in full.")
      : chain.retired ? t("clockRetired", "Retired on your feet — you kept everything you were carrying.")
      : t("clockDead", "You fell. Only a quarter of the unbanked renown made it home.");
  } else {
    $("clockHint").textContent = "";
  }

  renderRoad();
  renderDials();
  renderGear(r);
  renderBoard();
}

function renderRoad() {
  const el = $("road");
  if (!el) return;
  if (!chain || !road.length) {
    el.innerHTML = `<div class="faint" style="grid-column:1/-1;padding:14px 0">${
      chain ? "Waiting for the terrain block…" : "Set out to see the road."}</div>`;
    return;
  }
  el.innerHTML = road.map((t, i) => {
    const cls = [t.tile === E.HAZARD || t.tile === E.ELITE || t.tile === E.BOSS ? "danger"
      : (t.tile === E.CACHE || t.tile === E.SHRINE || t.tile === E.RELIC) ? "good" : "",
      t.depth === (chain ? chain.depth : -1) ? "now" : ""].join(" ");
    const act = plan[i] ? `<span class="act">${ACT_ICON[plan[i]]}</span>` : "";
    return `<div class="tile ${cls}" data-i="${i}" title="${esc(E.TILE_NAMES[t.tile])}${t.swing ? " · swing " + t.swing : ""}">
      ${act}<span>${TILE_ICON[t.tile]}</span><span class="sw">${t.swing || ""}</span></div>`;
  }).join("");
  el.querySelectorAll(".tile").forEach((n) => n.onclick = () => {
    const i = Number(n.dataset.i);
    plan[i] = plan[i] === brush ? 0 : brush;            // tap again to clear
    renderRoad();
  });
}

/** The segmented controls are built after i18n's DOMContentLoaded pass, so they must be localized on
 *  creation or they stay English until the user toggles the language picker. */
function relocalize(root) {
  try { if (window.NADO_i18n && window.NADO_i18n.apply) window.NADO_i18n.apply(root); } catch (e) {}
}

function renderDials() {
  const seg = $("actseg");
  if (seg && !seg.dataset.built) {
    seg.dataset.built = "1";
    seg.innerHTML = [1, 2, 3, 4, 5, 6, 7].map((a) =>
      `<button data-a="${a}" data-i18n="autogame.act_${ACT_KEY[a]}">${ACT_KEY[a]}<span> ${ACT_ICON[a]}</span></button>`).join("");
    seg.querySelectorAll("button").forEach((b) => b.onclick = () => { brush = Number(b.dataset.a); renderDials(); });
    relocalize(seg);
  }
  if (seg) seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", Number(b.dataset.a) === brush));

  const ss = $("stanceseg");
  if (ss && !ss.dataset.built) {
    ss.dataset.built = "1";
    ss.innerHTML = STANCE_KEY.map((k, i) =>
      `<button data-s="${i}" data-i18n="autogame.stance_${k}">${k}</button>`).join("");
    relocalize(ss);
    ss.querySelectorAll("button").forEach((b) => b.onclick = () => setStance(Number(b.dataset.s)));
  }
  const r = chain;
  if (ss) ss.querySelectorAll("button").forEach((b) => b.classList.toggle("on", r && Number(b.dataset.s) === r.stance));
  if (r) {
    const [dn, xn, sg, cap] = E.STANCES[r.stance];
    $("stanceHint").textContent = cap === 0
      ? "Guarded takes a quarter less damage and can never build a greed streak — it wins by finishing, not by compounding."
      : `Damage ×${(dn / 4).toFixed(2)} · renown ×${(xn / 4).toFixed(2)} · streak +${sg} per fight, capped ×${((E.STREAK_DIV + cap) / E.STREAK_DIV).toFixed(1)}`;
    $("stanceVal").textContent = STANCE_KEY[r.stance];
  }
}

function renderGear(r) {
  // Draw the warrior even with no run: a signed-out visitor should see who they would be marching as, not
  // an empty box. The bare figure is exactly what an all-empty kit renders, so this costs nothing extra.
  const cv = $("hero");
  if (cv) {
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.imageSmoothingEnabled = false;
    drawWarrior(ctx, footX(cv.width / 2, 5), footY(cv.height - 10, 5),
      { gear: r ? r.gear : new Array(E.NSLOT).fill(0), frame: 0, scale: 5, facing: 1,
        dead: !!(r && !r.alive) });
  }
  const el = $("slots");
  if (!r && el) {
    el.innerHTML = new Array(E.NSLOT).fill(0).map((_x, i) =>
      `<div class="slot empty"><div class="nm">${esc(SLOT_NAMES[i])}</div><div class="it">—</div></div>`).join("");
  }
  if (el && r) {
    el.innerHTML = r.gear.map((g, i) => {
      const it = unpackItem(g);
      return `<div class="slot ${g ? "" : "empty"}"><div class="nm">${esc(SLOT_NAMES[i])}</div>
        <div class="it">${g ? `T${it.tier} ${esc(MAT_NAMES[it.mat])}${it.affix ? ` <span class="aff">${esc(E.AFFIX_NAMES[it.affix])}</span>` : ""}`
          : "—"}</div></div>`;
    }).join("");
  }
  const af = $("affixes");
  if (af && r) {
    const on = [];
    for (let a = 1; a <= 7; a++) if (E.hasAffix(r, a)) on.push(a);
    af.innerHTML = on.length
      ? on.map((a) => `<span class="affpill">${esc(E.AFFIX_NAMES[a])} <span>${esc(AFFIX_BLURB[a])}</span></span>`).join("")
      : `<span class="faint">No affixes yet. They are rare, and each one changes a rule rather than a number.</span>`;
  }
}

const AFFIX_BLURB = ["", "+6 streak cap", "absorb every swing", "hazards do nothing", "+2 stamina",
  "double lifesteal", "every kill drops", "potions keep the streak"];

function renderBoard() {
  const el = $("board");
  if (!el || !sto) return;
  const ids = Object.keys(sto.ra || {}).map(Number).filter((n) => n > 0);
  const rows = ids.map((id) => {
    const r = E.runFromStorage(sto, id);
    return { id, r, sc: E.score(r), who: (sto.ra || {})[id] };
  }).filter((x) => x.r.depth > 0).sort((a, b) => b.sc - a.sc).slice(0, 15);
  if (!rows.length) { el.innerHTML = '<p class="faint">No marches yet. Be the first out of the gate.</p>'; return; }
  el.innerHTML = `<table><thead><tr><th>#</th><th>Marcher</th><th class="num">Depth</th>
    <th class="num">Renown</th><th>Rank</th></tr></thead><tbody>` +
    rows.map((x, i) => {
      const me = String(x.who || "").toLowerCase() === String(dapp.me || "").toLowerCase();
      const state = x.r.done ? "🏁" : x.r.alive ? "🚶" : x.r.retired ? "🚪" : "💀";
      return `<tr class="${me ? "me" : ""}"><td>${i + 1}</td>
        <td>${state} ${esc(disp(x.who) || "—")}</td>
        <td class="num">${x.r.depth}</td><td class="num">${x.sc.toLocaleString()}</td>
        <td>${esc(E.rankOf(x.sc))}</td></tr>`;
    }).join("") + "</tbody></table>";
}

// ── actions ─────────────────────────────────────────────────────────────────────────────────────
/**
 * Every action goes through the SDK's two guards, in this order:
 *   canPay(dapp, 0n, what) — no wallet? raise the shared sign-in bar and stop. These calls escrow nothing,
 *                            so the amount is 0; what canPay is doing here is the SIGN-IN check.
 *   dapp.busy(phase)       — already clicked? stop. The guard is armed from the TAP, not from the receipt,
 *                            so a double-tap cannot submit twice while the first is in flight.
 * Doing this by hand per game is how games drift apart; this is the whole reason the SDK exists.
 */
function act(phase, what, fn, keyName, keyVal) {
  if (!canPay(dapp, 0n, what)) return false;
  if (dapp.busy(phase, keyName, keyVal)) return false;
  fn();
  render();                       // reflect the click-time guard immediately
  return true;
}

function begin() {
  act("begin", t("whatBegin", "Setting out"), () =>
    dapp.call("begin", [randId()], 0n, t("labelBegin", "Set out on a new march"), { phase: "begin" }));
}
function commitPlan() {
  if (!chain) return;
  const word = E.packPlan(plan);
  act("plan", t("whatPlan", "Committing a plan"), () => {
    rememberPlan(myId, chain.leg, word, planAgg);      // so the animator can replay YOUR leg, not a default
    dapp.call("plan", [myId, chain.leg, word, planAgg], 0n,
      t("labelPlan", "Commit the plan for leg {n}", { n: chain.leg }), { phase: "plan", leg: chain.leg });
  }, "leg", chain.leg);
}
function advance() {
  if (!chain) return;
  act("advance", t("whatAdvance", "Settling the leg"), () =>
    dapp.call("advance", [myId], 0n, t("labelAdvance", "Settle the leg"),
      { phase: "advance", leg: chain.leg }), "leg", chain.leg);
}
function retire() {
  if (!chain) return;
  act("retire", t("whatRetire", "Retiring"), () =>
    dapp.call("retire", [myId], 0n, t("labelRetire", "Retire on your feet"), { phase: "retire" }));
}
function setStance(s) {
  if (!chain) return;
  act("stance", t("whatStance", "Changing stance"), () =>
    dapp.call("stance", [myId, s], 0n, `${t("labelStance", "Stance")}: ${STANCE_KEY[s]}`,
      { phase: "stance", want: s }));
}

/** Anyone may settle a leg, so the client does it for you the moment the dice exist. This is upkeep, not
 *  an edge: the outcome was fixed by two already-final hashes and cannot be steered by who calls it. */
function maybeAutoAdvance() {
  if (!dapp.autoCollect || !chain) return;
  if (!chain.alive || chain.done || chain.retired) return;
  if (dapp.cursor != null && dapp.cursor >= chain.nh && !dapp.pending("advance")) advance();
}

// ── wiring ──────────────────────────────────────────────────────────────────────────────────────
function wireDials() {
  const agg = $("agg"), heal = $("heal"), focus = $("focus");
  agg.oninput = () => { planAgg = Number(agg.value); $("aggVal").textContent = planAgg; updateAggHint(); };
  heal.oninput = () => { $("healVal").textContent = heal.value + "%"; };
  heal.onchange = () => { if (!chain) return; act("orders", t("whatOrders", "Changing standing orders"),
    () => dapp.call("orders", [myId, Number(heal.value)], 0n,
      t("labelOrders", "Auto-drink below {n}%", { n: heal.value }),
      { phase: "orders", want: Number(heal.value) })); };
  focus.oninput = () => { $("focusVal").textContent = `${focus.value} / ${100 - focus.value}`; };
  focus.onchange = () => { if (!chain) return; act("focus", t("whatFocus", "Changing focus"),
    () => dapp.call("focus", [myId, Number(focus.value)], 0n,
      t("labelFocus", "Focus {n}% weapon", { n: focus.value }),
      { phase: "focus", want: Number(focus.value) })); };
}

/** Price the pull against the heaviest swing waiting in the visible leg — the number the dial exists for. */
function updateAggHint() {
  if (!chain || !road.length) return;
  const worst = Math.max(0, ...road.map((t) => t.swing));
  const absorb = E.armorPts(chain);
  const cost = Math.max(planAgg, planAgg * worst - absorb);
  const pct = chain.hp ? Math.round((cost * 100) / chain.hp) : 0;
  $("aggHint").innerHTML = worst
    ? `Heaviest swing on this stretch is <b>${worst}</b>. Pulling <b>${planAgg}</b> costs about <b>${cost}</b> hp there — <b>${pct}%</b> of what you have.`
    : "No fights on this stretch — pull what you like.";
}

async function boot() {
  wireWallet(dapp);
  dapp.onReturn((pend, ok, err) => {
    if (err) alertBar(err);
    else if (ok) okBar(pend && pend.label ? `${pend.label} — landed` : t("done", "Done"));
  });
  wireDials();
  $("beginBtn").onclick = begin;
  $("planBtn").onclick = commitPlan;
  $("advBtn").onclick = advance;
  $("retireBtn").onclick = retire;

  await dapp.init();
  await refreshAll();
  setInterval(refreshAll, 3000);
  requestAnimationFrame(tick);
}

boot().catch((e) => alertBar(String((e && e.message) || e)));

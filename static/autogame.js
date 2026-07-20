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
  renderWallet, resolveAliases, disp, share, algHashn, ALG_P, esc, blocksToTime,
} from "./nadodapp.js";
import * as E from "./autogame-engine.js";
import * as ART from "./autogame-art.js";
import { drawWarrior, unpackItem, FRAME_W, FRAME_H } from "./autogame-art.js";

const CID = "8b0754255991ec52566ddb91d68b8e37";          // execnode/games/autogame.py (zkVM) — set by the deploy script
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

// What every action actually DOES, and what it costs. Nothing in this game is guessable from an emoji, and
// a player choosing between seven unlabelled icons is not making a decision — they are guessing.
const ACT_INFO = [
  ["Nothing special", "Meet it head on. No stamina."],
  ["Strike", "+25% renown, but you take 25% more. 2 stamina."],
  ["Guard", "Take half the damage. 1 stamina."],
  ["Dodge", "Skip the tile entirely — no damage, but no loot or renown either. 2 stamina."],
  ["Potion", "Drink now. Heals, but forfeits your attack AND breaks your streak."],
  ["Sprint", "Run past. No damage, no reward. 3 stamina."],
  ["Rest", "Heal by spending renown. Breaks your streak."],
  ["Rally / right lane", "At a fork: take the greedier right lane. Anywhere else: a small heal that KEEPS your streak. 3 stamina."],
];
// What every tile IS. Ordered by how much the choice matters.
const TILE_INFO = [
  ["Open road", "Nothing happens. Breathing room."],
  ["Monster", "A fight. You pull as many as your aggression says."],
  ["Elite", "A harder fight, two levels up, and a guaranteed drop."],
  ["Hazard", "Chip damage you cannot fight — only avoid or absorb."],
  ["Cache", "Loot. Better gear the deeper you are."],
  ["Shrine", "Heals you — and costs you your streak, like every heal."],
  ["Forge", "Crafts a permanent weapon or armour level from your materials."],
  ["Fork", "The road splits. Right is greedier: it re-rolls as an elite."],
  ["Relic", "A guaranteed high-tier drop. Where the run-defining affixes come from."],
  ["Boss", "Every 128 steps. One big thing, huge renown — and a CHECKPOINT that banks everything you carry."],
];
const DOCTRINE_ORDER = [E.MONSTER, E.ELITE, E.BOSS, E.FORK, E.HAZARD, E.RELIC, E.CACHE, E.SHRINE,
                        E.FORGE, E.ROAD];

// WHICH ACTIONS ACTUALLY DO SOMETHING ON WHICH TILE. Offering all eight everywhere was a lie: the contract
// discards most of them on most tiles, so the menu was inviting choices that silently evaporate.
//   * On a FORK the contract forces the action to Default the instant the lane is picked — the ONLY thing
//     that survives is which lane, so that row offers exactly two options.
//   * Guard and Strike only touch a monster's swing, so they mean nothing outside a fight.
//   * Dodge and Sprint forfeit a tile, which is real on a shrine (keep your streak) and merely wasted
//     stamina on empty road.
//
// SPRINT IS NOT OFFERED ANYWHERE. In the rules it is byte-for-byte identical to Dodge — both set the same
// `skip` flag and forfeit the tile — but it costs 3 stamina against Dodge's 2. It is strictly dominated, so
// listing it is offering the player a worse version of a choice they already have. The rules should
// eventually give it a distinct effect or lose the action id; until then the menu tells the truth.
const A_ = E;
const COMBAT_ACTS = [0, E.A_STRIKE, E.A_GUARD, E.A_DODGE, E.A_POTION, E.A_RALLY, E.A_REST];
const HEALS = [0, E.A_POTION, E.A_RALLY, E.A_REST];        // available anywhere: they act on YOU, not the tile
const ACTS_FOR = {
  [E.MONSTER]: COMBAT_ACTS,
  [E.ELITE]:   COMBAT_ACTS,
  [E.BOSS]:    COMBAT_ACTS,
  // a fork discards every action the moment the lane is chosen, so the lane IS the only choice
  [E.FORK]:    [0, E.A_RIGHT],
  // Dodge is offered only where forfeiting the tile actually buys something: skipping a fight, or skipping
  // a shrine to protect the greed streak a heal would break
  [E.HAZARD]:  [0, E.A_DODGE, E.A_POTION, E.A_RALLY, E.A_REST],
  [E.SHRINE]:  [0, E.A_DODGE, E.A_POTION, E.A_RALLY, E.A_REST],
  [E.CACHE]:   HEALS,
  [E.RELIC]:   HEALS,
  [E.FORGE]:   HEALS,
  [E.ROAD]:    HEALS,
};
/** Action 7 is two different things depending on where you meet it, so it must not be labelled one way. */
function actName(a, tile) {
  if (a === E.A_RIGHT) {
    return tile === E.FORK ? t("actn_right_fork", "Take the right lane")
                           : t("actn_right_rally", "Rally");
  }
  return t("actn_" + ACT_KEY[a], ACT_INFO[a][0]);
}
function actDesc(a, tile) {
  if (a === E.A_RIGHT) {
    return tile === E.FORK
      ? t("actd_right_fork", "The greedier road: it re-rolls as an elite — harder, but a guaranteed drop.")
      : t("actd_right_rally", "A small heal that KEEPS your streak — the only one that does. 3 stamina.");
  }
  if (a === 0 && tile === E.FORK) return t("actd_left_fork", "The safer road: it re-rolls as an ordinary monster.");
  return t("actd_" + ACT_KEY[a], ACT_INFO[a][1]);
}
let doctrine = null;            // the 10 standing reactions being edited

let sto = null;                 // last contract storage view
let myId = null;                // my run id
let chain = null;               // the run exactly as the contract has it
let view = null;                // the run the ANIMATOR is showing; catches up to `chain`, snaps on mismatch
let road = [];                  // peekLeg() of the pending leg — the visible, committed terrain
let planAgg = 1;
let queue = [];                 // settled step events waiting to be animated
let camera = 0;                 // fractional depth the camera is at
let lastLegSeen = -1;
// Gore is part of the animation, not decoration: a fight you cannot see the cost of does not read as a
// fight. Each entry is anchored to a WORLD DEPTH so it scrolls with the road and stays where it happened.
let gore = [];
let fatality = null;            // {which, t0} once the hero falls
const GORE_MS = 1400;           // spray/spurt lifetime; pools and splatter persist until they scroll away

function addGore(depth, kind, amount, seed) {
  gore.push({ depth, kind, amount, seed, t0: performance.now() });
  if (gore.length > 120) gore.splice(0, gore.length - 120);   // the road is long; do not grow forever
}


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
      case "plan": return E.packDoctrine(chain.doctrine) === String(f.word) && Number(chain.agg) === Number(f.agg);
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
  settlePrompt();
}

/**
 * Walk `view` forward to wherever the chain is, replaying each settled leg through the engine so the
 * animator has per-step events to show. If the replay does not land exactly where the contract says, the
 * chain wins and the view snaps — a pretty animation that disagrees with settlement is a lie.
 */
function syncView() {
  if (!view || view.depth > chain.depth) {
    view = { ...chain, gear: [...chain.gear], mats: [...chain.mats] };
    queue = []; camera = view.depth; lastLegSeen = chain.leg;
    gore = []; fatality = null;                       // a new run starts on clean ground
    return;
  }
  while (view.leg < chain.leg) {
    const tileH = hashField(view.lh), rollH = hashField(view.nh);
    if (tileH == null || rollH == null) break;                 // hashes not cached yet; try next poll
    // Replay under the same orders the contract used for this leg: the doctrine, but only if it predates
    // the leg's rolling height (the POLH fence). Standing orders are readable from storage, so unlike the
    // old hash-keyed plan word the animator can reproduce a governed leg exactly.
    const governed = E.doctrineGoverns(chain, view.nh);
    const evs = E.playLeg(algHashn, view, myId, tileH, rollH,
                          governed ? chain.doctrine : null, governed ? chain.agg : 1);
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
  if (chain.leg !== lastLegSeen) lastLegSeen = chain.leg;
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
  // Pixels per step. This MUST exceed the sprite width or the road becomes a shoulder-to-shoulder lineup:
  // at 44px with 96px sprites every creature overlapped its neighbours and sixteen of them read as a zoo
  // rather than a world. At 120 only ~4 tiles ahead are on screen at once, which is what a side-scroller
  // should show — the road strip below already lists the whole leg.
  const TILE = 120;
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

  // What is coming, standing ON the road in world space. These used to be 20px EMOJI at half opacity next
  // to a hand-drawn pixel warrior, which read as the player swinging his sword at nothing.
  const heroX = Math.round(W * 0.30);
  const now = performance.now();
  const RANK = { [E.ELITE]: 1, [E.BOSS]: 2 };
  const PROP = { [E.HAZARD]: "hazard", [E.CACHE]: "cache", [E.SHRINE]: "shrine",
                 [E.FORGE]: "forge", [E.RELIC]: "relic", [E.FORK]: "fork" };
  let engaging = false;
  if (chain) {
    for (const t of road) {
      // Half a tile forward: a creature standing at exactly (depth - camera) sits ON the hero the moment he
      // reaches its tile, and the two sprites merge into an unreadable blob. Offsetting it to the far side
      // of its own tile means he WALKS INTO it, which is also what the fight is.
      const dx = t.depth - camera + 0.5;
      const x = heroX + Math.round(dx * TILE);
      if (x < -2 * TILE || x > W + 2 * TILE || t.tile === E.ROAD) continue;
      const passed = dx < -0.25;                       // already walked through: it is done for
      const combat = t.tile === E.MONSTER || t.tile === E.ELITE || t.tile === E.BOSS || t.tile === E.FORK;

      if (combat && ART.drawMonster) {
        const rank = RANK[t.tile] || 0;
        const scale = rank === 2 ? 4 : 3;
        const mw = (ART.MON_W || 32) * scale, mh = (ART.MON_H || 32) * scale;
        // frames 0..2 idle, 3 attack, 4 death — see autogame-art.js
        const near = Math.abs(dx) < 0.75;
        const frame = passed ? 4 : near ? 3 : Math.floor(now / 220) % 3;
        if (near) engaging = true;
        ART.drawMonster(ctx, Math.round(x - mw / 2), GY + 2 - mh,
          { family: t.fam, rank, level: t.ml, frame, scale, facing: -1, dead: passed });
      } else if (PROP[t.tile] && ART.drawProp) {
        const scale = 3;
        const pw = (ART.MON_W || 32) * scale, ph = (ART.MON_H || 32) * scale;
        ctx.globalAlpha = passed ? 0.35 : 1;
        ART.drawProp(ctx, Math.round(x - pw / 2), GY + 2 - ph,
          { kind: PROP[t.tile], frame: Math.floor(now / 220) % 3, scale });
        ctx.globalAlpha = 1;
      } else {
        // fallback while the sprite for this tile does not exist yet — never leave the road blank
        ctx.font = "22px system-ui"; ctx.textAlign = "center";
        ctx.globalAlpha = passed ? 0.3 : 1;
        ctx.fillText(TILE_ICON[t.tile], x, GY - 6);
        ctx.globalAlpha = 1; ctx.textAlign = "left";
      }
    }
  }

  // ground-level gore first, so sprites stand ON it
  if (ART.drawBlood) {
    for (const g of gore) {
      const gx = heroX + Math.round((g.depth - camera) * TILE);
      if (gx < -TILE || gx > W + TILE) continue;
      const age = now - g.t0;
      const lasting = g.kind === "pool" || g.kind === "splatter";
      if (!lasting && age > GORE_MS) continue;
      const frame = lasting ? Math.min(5, Math.floor(age / 160)) : Math.floor(age / (GORE_MS / 6));
      ART.drawBlood(ctx, gx, GY + 2, { kind: g.kind, frame, scale: 3, facing: 1,
                                       seed: g.seed, amount: g.amount });
    }
    gore = gore.filter((g) => g.kind === "pool" || g.kind === "splatter" || now - g.t0 <= GORE_MS
                              || g.depth > camera - 40);
  }

  // the warrior — always at the same screen x; the world moves, not him. He swings when something is
  // actually in front of him, not merely when the event queue happens to hold a fight.
  // He also STANDS STILL when the world is not moving: a walk cycle playing against a static background
  // reads as a treadmill, and this game spends most of its time waiting for the next block.
  const moving = camera > (drawWorld._lastCam ?? camera) + 0.0005;
  drawWorld._lastCam = camera;
  const frame = moving ? Math.floor((now / 140) % 4) : 0;
  const hurt = view && view.hp * 4 < view.maxhp;
  const dead = view ? !view.alive : false;
  if (dead && fatality && ART.drawFatality) {
    const fr = Math.floor((now - fatality.t0) / 130);
    const spec = ART.FATALITIES[fatality.which] || { frames: 8 };
    ART.drawFatality(ctx, footX(heroX, 3), footY(GY + 2, 3), {
      which: fatality.which, frame: Math.min(fr, (spec.frames || 8) - 1), scale: 3, facing: 1,
      gear: view ? view.gear : new Array(6).fill(0),
    });
  } else {
    drawWarrior(ctx, footX(heroX, 3), footY(GY + 2, 3), {
      gear: view ? view.gear : new Array(6).fill(0),
      frame, scale: 3, facing: 1, hurt, dead,
      attacking: engaging,
    });
  }

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
  idleMessage();
  requestAnimationFrame(tick);
}

/** What the stage says when nothing is being animated — otherwise the player stares at a silent picture
 *  and cannot tell whether the game is broken or simply waiting for a block. */
function idleMessage() {
  const el = $("stagemsg");
  if (!el || queue.length) return;
  if (!chain) { el.innerHTML = `<span class="faint">${esc(t("idleNoRun", "No march yet — set out to begin."))}</span>`; return; }
  if (!chain.alive) { el.innerHTML = `<b style="color:var(--danger)">${esc(t("idleDead", "You fell here."))}</b>`; return; }
  if (chain.done) { el.innerHTML = `<b style="color:var(--win)">${esc(t("idleDone", "The road is walked. Chapter complete."))}</b>`; return; }
  if (chain.retired) { el.innerHTML = `<span class="dim">${esc(t("idleRetired", "Retired, on your feet."))}</span>`; return; }
  const left = dapp.cursor != null ? chain.nh - dapp.cursor : null;
  el.innerHTML = left != null && left > 0
    ? `<span class="dim">${esc(t("idleWaiting", "Marching · depth {d}/{c} · the next {n} blocks decide this leg",
        { d: chain.depth, c: E.CHAPTER, n: left }))}</span>`
    : `<b style="color:var(--accent2)">${esc(t("idleReady", "The dice have landed — settle the leg."))}</b>`;
}

function showEvent(ev) {
  // spawn the blood this step earned, anchored where it happened
  const at = ev.depth != null ? ev.depth : Math.floor(camera);
  const seed = ((at * 2654435761) ^ (myId || 1)) >>> 0;
  if (ev.dmg) addGore(at, "hit", Math.min(8, 1 + Math.floor(ev.dmg / 6)), seed);
  if (ev.kill) {
    addGore(at, "spurt", Math.min(10, ev.foes || 1), seed ^ 0x9e37);
    addGore(at, "pool", Math.min(10, ev.foes || 1), seed ^ 0x51ed);
    addGore(at, "splatter", Math.min(10, ev.foes || 1), seed ^ 0x2f6d);
  }
  if (ev.died && ART.FATALITIES && ART.FATALITIES.length) {
    // deterministic: the same death always replays as the same fatality
    fatality = { which: seed % ART.FATALITIES.length, t0: performance.now() };
    addGore(at, "pool", 10, seed ^ 0xdead);
  }
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
  // Standing orders have NO window: they govern legs whose dice do not exist yet, and the contract's POLH
  // fence stops them touching a leg that already rolled. The old per-leg plan needed a 96-second window,
  // which is unreachable whenever the exec layer trails L1 by more than a leg — and it does.
  const canPlan = live;
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

  if (chain && !$("agg").dataset.touched) {
    $("agg").value = String(chain.agg || 1);
    planAgg = chain.agg || 1;
    $("aggVal").textContent = planAgg;
  }
  renderRoad();
  renderDoctrine();
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
    const act = (doctrine && doctrine[t.tile]) ? `<span class="act">${ACT_ICON[doctrine[t.tile]]}</span>` : "";
    // A canvas, not an emoji. The chip background is a dark blue-grey, and a stock ⚔️ glyph sitting in it
    // reads as clip-art in a blue box rather than as the monster you are about to fight.
    const art = ART.drawMonster
      ? `<canvas class="tico" width="${ART.MON_W || 32}" height="${ART.MON_H || 32}" data-i="${i}"></canvas>`
      : `<span>${TILE_ICON[t.tile]}</span>`;
    return `<div class="tile ${cls}" data-i="${i}" title="${esc(E.TILE_NAMES[t.tile])}${t.swing ? " · swing " + t.swing : ""}">
      ${act}${art}<span class="sw">${t.swing || ""}</span></div>`;
  }).join("");
  paintRoadIcons();
}

/** The segmented controls are built after i18n's DOMContentLoaded pass, so they must be localized on
 *  creation or they stay English until the user toggles the language picker. */
function relocalize(root) {
  try { if (window.NADO_i18n && window.NADO_i18n.apply) window.NADO_i18n.apply(root); } catch (e) {}
}

/** Paint each road chip with the SAME sprite the world uses, so the strip and the stage agree about what
 *  is standing on that tile. */
function paintRoadIcons() {
  if (!ART.drawMonster) return;
  const RANK = { [E.ELITE]: 1, [E.BOSS]: 2 };
  const PROP = { [E.HAZARD]: "hazard", [E.CACHE]: "cache", [E.SHRINE]: "shrine",
                 [E.FORGE]: "forge", [E.RELIC]: "relic", [E.FORK]: "fork" };
  document.querySelectorAll("#road .tico").forEach((cv) => {
    const t = road[Number(cv.dataset.i)];
    if (!t) return;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.imageSmoothingEnabled = false;
    if (t.tile === E.ROAD) return;                       // empty road draws nothing, on purpose
    const combat = t.tile === E.MONSTER || t.tile === E.ELITE || t.tile === E.BOSS || t.tile === E.FORK;
    if (combat) {
      ART.drawMonster(ctx, 0, 0, { family: t.fam, rank: RANK[t.tile] || 0, level: t.ml,
                                   frame: 0, scale: 1, facing: -1 });
    } else if (PROP[t.tile] && ART.drawProp) {
      ART.drawProp(ctx, 0, 0, { kind: PROP[t.tile], frame: 0, scale: 1 });
    }
  });
}

/** The doctrine editor: one row per tile class, each saying what the thing IS and offering what you can do
 *  about it, in words. This is the whole game's decision surface, so it explains itself. */
function renderDoctrine() {
  const el = $("doctrine");
  if (!el) return;
  if (!doctrine) doctrine = chain ? [...chain.doctrine] : new Array(E.NTILE).fill(0);
  if (!el.dataset.built) {
    el.dataset.built = "1";
    el.innerHTML = DOCTRINE_ORDER.map((tile) => `
      <div class="drow" data-t="${tile}">
        <canvas class="dico" width="${ART.MON_W || 32}" height="${ART.MON_H || 32}" data-t="${tile}"></canvas>
        <div class="what"><div class="nm">${esc(t("tile_" + tile, TILE_INFO[tile][0]))}</div>
          <div class="de">${esc(t("tiled_" + tile, TILE_INFO[tile][1]))}</div>
          <div class="de eff" data-t="${tile}"></div></div>
        <select data-t="${tile}">${(ACTS_FOR[tile] || [0]).map((a) =>
          `<option value="${a}">${esc(a === 0 && tile === E.FORK ? t("actn_left_fork", "Left lane")
                                     : a === 0 ? t("actn_default", ACT_INFO[0][0]) : actName(a, tile))}</option>`).join("")}</select>
      </div>`).join("");
    el.querySelectorAll("select").forEach((sel) => sel.onchange = () => {
      doctrine[Number(sel.dataset.t)] = Number(sel.value);
      renderRoad();
      renderDoctrine();
    });
    paintDoctrineIcons();
  }
  // the full effect of whatever is currently chosen, spelled out in the row — an option list wide enough
  // to hold these sentences would not fit on a phone, and a truncated one explains nothing
  el.querySelectorAll("select").forEach((sel) => { sel.value = String(doctrine[Number(sel.dataset.t)] || 0); });
  el.querySelectorAll(".eff").forEach((n) => {
    const tile = Number(n.dataset.t);
    const a = doctrine[tile] || 0;
    n.innerHTML = a ? `<b style="color:var(--accent2)">${esc(actName(a, tile))}</b> — ${esc(actDesc(a, tile))}`
                    : `<span class="faint">${esc(actDesc(0, tile))}</span>`;
  });
  const note = $("doctrineNote");
  if (note) {
    const dirty = chain && doctrine.some((v, i) => v !== chain.doctrine[i]) ;
    const aggDirty = chain && planAgg !== chain.agg;
    note.innerHTML = !chain ? esc(t("docNoRun", "Set out first — orders belong to a march."))
      : (dirty || aggDirty) ? `<b style="color:var(--gold)">${esc(t("docDirty", "Unsaved changes — commit them to make them law."))}</b>`
      : esc(t("docSaved", "These orders are in force from the next unresolved leg."));
  }
}

function paintDoctrineIcons() {
  if (!ART.drawMonster) return;
  const RANK = { [E.ELITE]: 1, [E.BOSS]: 2 };
  const PROP = { [E.HAZARD]: "hazard", [E.CACHE]: "cache", [E.SHRINE]: "shrine",
                 [E.FORGE]: "forge", [E.RELIC]: "relic", [E.FORK]: "fork" };
  document.querySelectorAll("#doctrine .dico").forEach((cv) => {
    const tile = Number(cv.dataset.t);
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.imageSmoothingEnabled = false;
    if (tile === E.ROAD) return;
    if (PROP[tile] && ART.drawProp) ART.drawProp(ctx, 0, 0, { kind: PROP[tile], frame: 0, scale: 1 });
    else ART.drawMonster(ctx, 0, 0, { family: 1, rank: RANK[tile] || 0, level: 3, frame: 0, scale: 1, facing: -1 });
  });
}

function renderDials() {
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
  // drop any entry the tile cannot actually use, so what is committed is exactly what will happen
  const clean = (doctrine || []).map((a, tile) => ((ACTS_FOR[tile] || [0]).includes(a) ? a : 0));
  const word = E.packDoctrine(clean);
  act("plan", t("whatPlan", "Committing your doctrine"), () => {
    dapp.call("plan", [myId, word, planAgg], 0n,
      t("labelPlan", "Commit doctrine"), { phase: "plan", word, agg: planAgg });
  }, "word", word);
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

/**
 * DELIBERATELY NOT AUTOMATIC.
 *
 * Settling is permissionless, so it is tempting to have the client just do it the moment the dice exist.
 * That shipped, and it was a trap: dapp.call() falls back to a full WALLET REDIRECT when it cannot sign in
 * the background, so the page bounced to get.nadochain.com on load, came back, fired again, and bounced
 * again — an infinite redirect loop with no way to reach the game. "Looks stuck, I can't progress."
 *
 * Nothing is lost by waiting for a tap: the leg's outcome was fixed by two already-final block hashes, so
 * settling it now or in an hour gives the identical result, and anyone at all can settle it. So the button
 * simply lights up and says so.
 */
function settlePrompt() {
  if (!chain || !chain.alive || chain.done || chain.retired) return;
  const ready = dapp.cursor != null && dapp.cursor >= chain.nh;
  if (ready && !dapp.busy("advance")) $("advBtn").classList.add("pulse");
  else $("advBtn").classList.remove("pulse");
}

// ── wiring ──────────────────────────────────────────────────────────────────────────────────────
function wireDials() {
  const agg = $("agg"), heal = $("heal"), focus = $("focus");
  agg.oninput = () => { agg.dataset.touched = "1"; planAgg = Number(agg.value);
                        $("aggVal").textContent = planAgg; updateAggHint(); renderDoctrine(); };
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

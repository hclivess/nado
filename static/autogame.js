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
  NadoDapp, randId, $, base, gate, guardedAction, relocalize, alertBar, okBar, wireWallet,
  renderWallet, renderTopScores, resolveAliases, disp, algHashn, ALG_P, esc, blocksToTime, modeBar,
  confirmingLabel,
} from "./nadodapp.js?v=4984604e";
import * as E from "./autogame-engine.js?v=eb6129b3";
import { ACTS_FOR } from "./autogame-rules.js?v=e7abffe6";
import * as ART from "./autogame-art.js?v=f4f6ab41";
import { drawWarrior, unpackItem, FRAME_W, FRAME_H } from "./autogame-art.js?v=f4f6ab41";
import { createDaily } from "./autogame-dailyui.js?v=4b37106c";
import * as D from "./autogame-daily.js?v=950a49cd";
import { createAudio } from "./autogame-audio.js?v=afd7538c";

const CID = "ba8bebc9693f5aaec0e338a13d5812c4";          // execnode/games/autogame.py (zkVM) — set by the deploy script
const dapp = new NadoDapp({ cid: CID, app: "Autogame" });
const P = ALG_P();
const BLOCK_SECS = 6;

// drawWarrior anchors the sprite's TOP-LEFT corner, but everything here thinks in ground coordinates —
// the warrior stands ON the road line, and the gear panel stands him on its floor. Converting once, here,
// keeps that mismatch from being re-derived (wrongly) at each call site.
const footX = (x, scale) => Math.round(x - (FRAME_W * scale) / 2);
const footY = (y, scale) => Math.round(y - FRAME_H * scale);

// The fallback has to interpolate too. i18n.js normally wins the race and does the {var} substitution for
// us, but on the frame where it has not, the English default was printed RAW: the death line came out as
// "A level {l} {who} is standing over your body", and so does every other string in here that takes a var.
const t = (k, d, v) => (window.t ? window.t("autogame." + k, d, v)
  : String(d).replace(/\{(\w+)\}/g, (m, n) => (v && v[n] != null ? String(v[n]) : m)));

const SLOT_NAMES = ["Weapon", "Helm", "Body", "Shield", "Boots", "Cloak"];
const MAT_NAMES = ["bronze", "iron", "steel", "silver", "obsidian", "gold", "meteoric", "living"];
const WKIND_NAMES = ["sword", "axe", "maul", "spear"];
/** The name of an item's SLOT — but the weapon slot names the weapon's CLASS instead ("spear", not the
 *  generic "weapon"), because the class is a real, fight-changing property the road rolled onto it. */
function slotLabel(slot, it) {
  if (slot === E.G_WEAPON && it && it.tier >= 0)
    return t("wk_" + WKIND_NAMES[it.kind | 0], WKIND_NAMES[it.kind | 0]);
  return SLOT_NAMES[slot];
}
/** The weapon class's one-line fighting character — the tooltip that tells a player WHY this iron matters. */
const wkindHint = (k) => t("wkh_" + WKIND_NAMES[k | 0], "");
const TILE_ICON = ["🛣️", "⚔️", "🐺", "💀", "🗡️", "🎁", "🔥", "🪤", "🕳️", "🌪️", "⛓️", "📦", "⚰️", "🛡️",
                   "⛏️", "🌿", "⛲", "🪣", "🏕️", "🗿", "🕯️", "🔨", "🔀", "💎", "👑"];
const ACT_ICON = ["", "⚡", "🛡️", "💨", "🧪", "🏃", "🔥", "🔀"];
const ACT_KEY = ["default", "strike", "guard", "dodge", "potion", "sprint", "rest", "right"];
const STANCE_KEY = ["balanced", "aggressive", "guarded", "evasive"];

// What every action actually DOES, and what it costs. Nothing in this game is guessable from an emoji, and
// a player choosing between seven unlabelled icons is not making a decision — they are guessing.
const ACT_INFO = [
  ["Nothing special", "Meet it head on. No stamina."],
  ["Strike", "+25% renown, but you take 25% more. 2 stamina."],
  ["Guard", "Your shield takes half of up to TWO foes' swings — a duel truly halved, a crowd barely dented. Blocks an ambush's sting. Pauses your streak. 2 stamina."],
  ["Dodge", "Skip the tile entirely — except a horde, which it only thins back to a normal pull. No damage, no loot. 2 stamina (1 in evasive stance)."],
  ["Potion", "Drink now. Heals, but forfeits your attack AND breaks your streak."],
  ["Sprint", "Run past — the ONLY thing that slips a horde. No damage, no reward. 3 stamina (2 in evasive stance)."],
  ["Rest", "Heal by spending renown. Breaks your streak."],
  ["Rally / right lane", "At a fork: take the greedier right lane. Anywhere else: a small heal that KEEPS your streak. 3 stamina."],
];
// What every tile IS. Ordered by how much the choice matters.
// What each tile IS, in words — shown under the strip when you tap one, so the road explains itself the
// same way the brush palette explains actions. (This table died once as "dead code" when the doctrine
// editor was removed; it is back because the road strip is now the whole game surface and a bare icon
// grid tells a new player nothing.)
const TILE_INFO = [
  ["Open road", "Nothing happens. Breathing room."],
  ["Monster", "A fight. You pull as many as your aggression says."],
  ["Horde", "A pack: DOUBLE your pull, one level down. Dodge can't slip it — it only thins the pack back to a normal pull. Only Sprint gets you past."],
  ["Elite", "A harder fight, two levels up, and a guaranteed drop."],
  ["Ambush", "It strikes FIRST — a sting straight through your armour unless you Guard or Dodge. The fight pays +25% renown for the danger."],
  ["Mimic", "The chest that bites. One body at elite level, twice its family's teeth — and it ALWAYS drops boss-grade loot. Dodge slips it; it cannot chase."],
  ["Hazard", "Chip damage you cannot fight — only avoid or absorb."],
  ["Snare", "A trap that eats 3 STAMINA. Guard springs it on your shield instead: no loss, +1 scrap."],
  ["Quag", "Deep mud: chip damage armour can't stop, and 2 stamina gone. Dodge hops the stones. Evasive wades it at half."],
  ["Gale", "A storm that rides with you for three steps: +25% renown out AND +25% damage in. Dodge shelters from it."],
  ["Tollgate", "The reeve's chain. Walk through and pay renown. STRIKE robs the strongbox — and the strongbox BITES: a mimic fight, but it always drops. Dashing past (Dodge/Sprint) takes the lash."],
  ["Cache", "Loot. Better gear the deeper you are."],
  ["Barrow", "Dig the mound for a +1-tier item — and eat the grave-curse straight through armour. Guard braces it to half; warding voids it."],
  ["Armory", "A fallen soldier's rack: an item roll FORCED to your weapon slot."],
  ["Vein", "An ore lode. Strike swings the pick: scrap out of the rock. Anything else walks past scenery."],
  ["Grove", "A spirit ring. Rally COMMUNES with it: essence on top of Rally's own heal."],
  ["Shrine", "Heals you — and costs you your streak, like every heal."],
  ["Well", "A waystone spring. Rest drinks deep: stamina to FULL plus a heal. Potion BOTTLES it instead: +1 flask, streak kept."],
  ["Camp", "A cold firepit. Rest here heals DOUBLE and costs no renown — the one free rest on the road."],
  ["Idol", "An old god's idol. Strike SMASHES it for renown — the bloodier you are, the more it pays. Offering a potion pays TRIPLE."],
  ["Pyre", "An unlit beacon. Strike lights it: the next 3 steps pay +25% renown — the gale's generous twin, and they stack."],
  ["Forge", "Crafts a permanent weapon or armour level from your materials."],
  ["Crossroads", "The road parts. The right-hand way is greedier: it re-rolls as an elite."],
  ["Relic", "A guaranteed high-tier drop. Where the run-defining affixes come from."],
  ["Boss", "Every 128 steps. One big thing, huge renown — and a CHECKPOINT that banks everything you carry."],
];

// WHICH ACTIONS ACTUALLY DO SOMETHING ON WHICH TILE. Offering all eight everywhere was a lie: the contract
// discards most of them on most tiles, so the menu was inviting choices that silently evaporate.
//   * On a FORK the contract forces the action to Default the instant the lane is picked — the ONLY thing
//     that survives is which lane, so that row offers exactly two options.
//   * Guard and Strike only touch a monster's swing, so they mean nothing outside a fight.
//   * Dodge and Sprint forfeit a tile, which is real on a shrine (keep your streak) and merely wasted
//     stamina on empty road.
// WHICH ACTIONS DO SOMETHING ON WHICH TILE — imported, not written here. ACTS_FOR is DERIVED from the rules
// by tests/autogame_action_matrix.py: for every (tile, action) it runs the reference model against plain
// Default across many worlds and keeps only the actions that change something OTHER than their own stamina
// cost, dropping any that are strictly dominated by a cheaper action with identical effect.
//
// I wrote this table by hand once and got it wrong both ways — offering "Strike forge" (a pure 2-stamina
// waste), offering "take the right lane" on shrines where action 7 means something else entirely, and
// removing Dodge from caches where forfeiting the loot IS a real choice. Deriving it means the menu can no
// longer disagree with the game.
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
let sto = null;                 // last contract storage view
let myId = null;                // my run id
let chain = null;               // the run exactly as the contract has it
let view = null;                // the run the ANIMATOR is showing; catches up to `chain`, snaps on mismatch
let road = [];                  // peekLeg() of the pending leg — the visible, committed terrain
let roadBase = 0;               // the depth road[0] stands at (a leg boundary marching; the step you are
                                // on in the Gauntlet). drawWorld used chain.depth for this, which is only
                                // the same number in one of the two modes.
let mode = "march";             // "march" = the staked, chain-paced run · "daily" = the free Daily Gauntlet
let daily = null;               // the Gauntlet controller (autogame-dailyui.js), built at boot
const audio = createAudio();
let planAgg = 1;
// staged locally until saved: tune all four dials, then one plan() call makes them law
let pendStance = 0, pendFocus = 50, pendHeal = 35;
// ANY dial interaction (stance seg, aggression, focus, heal) parks the chain-sync of the dials card.
// Only the agg slider used to set this (via a dataset flag), so clicking GUARDED or EVASIVE held for
// at most one 3-second state poll before the render stomped it back to the saved stance.
let dialsTouched = false;
// YOUR ANSWER TO THE SIXTEEN TILES IN FRONT OF YOU. 0 IS an action — A_DEFAULT, walk in and fight
// plainly — so a blank tile is an unspent choice, never a trap. This is the game's ONLY action surface.
// It exists because the dice for a leg are not scheduled until you commit it, so an answer can never be
// racing a roll — see the RNH == 0 note in execnode/games/autogame.py.
let answers = new Array(E.LEG).fill(0);
let selTile = -1;               // index of the last-tapped road tile — its story shows under the strip
// The brush palette. Action 7 does double duty in the RULES (on a FORK it picks the greedy lane, anywhere
// else it is Rally, the streak-preserving heal) — but one button wearing both names was genuinely
// unreadable, so the palette splits it: same 3-bit value, two entries, each gated to the tiles where its
// meaning applies. The chip icon follows the tile too, so Rally never wears the fork glyph.
const BRUSHES = [
  { a: E.A_DEFAULT, icon: "🚶", nameKey: "actn_default", only: null },
  { a: E.A_STRIKE, icon: "⚡", nameKey: "actn_strike", only: null },
  { a: E.A_GUARD, icon: "🛡️", nameKey: "actn_guard", only: null },
  { a: E.A_DODGE, icon: "💨", nameKey: "actn_dodge", only: null },
  { a: E.A_POTION, icon: "🧪", nameKey: "actn_potion", only: null },
  { a: E.A_RALLY, icon: "✨", nameKey: "actn_right_rally", notTile: E.FORK },
  { a: E.A_RIGHT, icon: "🔀", nameKey: "actn_right_fork", onlyTile: E.FORK },
  { a: E.A_REST, icon: "🔥", nameKey: "actn_rest", only: null },
];
const chipIcon = (a, tile) => (a === E.A_RIGHT ? (tile === E.FORK ? "🔀" : "✨") : ACT_ICON[a]);
// Words I committed, keyed by leg number, so the animator can replay a settled leg even when the chain's
// cw/cl mirror has already moved on to the next one (localStorage: they survive a redirect round-trip).
const LS_WORDS = "nado_autogame_words";
function wordsLoad() { try { return JSON.parse(localStorage.getItem(LS_WORDS) || "{}") || {}; } catch (e) { return {}; } }
function wordFor(runId, leg) {
  if (chain && Number(chain.cl) === Number(leg) && String(chain.cw || "0") !== "0") return chain.cw;
  return (wordsLoad()[runId + ":" + leg]) || 0;
}
function wordSave(runId, leg, word) {
  try {
    const w = wordsLoad(); w[runId + ":" + leg] = String(word);
    const keys = Object.keys(w);
    if (keys.length > 80) for (const k of keys.slice(0, keys.length - 80)) delete w[k];
    localStorage.setItem(LS_WORDS, JSON.stringify(w));
  } catch (e) {}
}
let brush = 1;                  // index into BRUSHES (1 = Strike) — which entry a tile tap stamps
let queue = [];                 // settled step events waiting to be animated
let camera = 0;                 // fractional depth the camera is at
let lastLegSeen = -1;
let previewed = "";             // "runId:leg" already played optimistically — see previewLeg()
// Answers for the NEXT leg, taken while the previous leg's close is still in flight. Held (not cleared on
// send) until the chain shows the dice scheduled, so a pool-wiped auto-commit simply re-sends.
let queuedWord = null;          // {leg, word}
// ── ADAPTIVE POLL CADENCE ── every wait in this game is block-physics (inclusion + the anti-steering
// cursor+2 pin) EXCEPT the client's own polling, which used to add up to a flat 3s on top of every
// transition. While something of ours is in flight the storage poll runs HOT (1s); poke() opens/extends
// the window and it decays back to 3s on its own — never a permanent fast poll against the node.
let hotUntil = 0;
let refreshing = false;         // serialises refreshAll across the two loops that may now both call it
const poke = () => { hotUntil = performance.now() + 20000; };
/** PIPELINING: the current leg's dice have landed and been previewed; only its close is outstanding. The
 *  next terrain (= this leg's roll hash) is therefore already knowable, so the player can answer the next
 *  sixteen RIGHT NOW instead of watching a spinner — the march continues the second anything is in flight. */
const pipel = () => mode === "march" && chain && !!chain.nh && previewed === myId + ":" + chain.leg
  && view && view.alive && !view.done;
/** THE march is holding for YOUR answers. A live run whose current leg has terrain (lh set) but no dice
 *  scheduled (nh==0) and nothing already in flight — OR the pipelined next leg. The alive/done/retired gate
 *  is load-bearing: `nh` PARKS AT 0 the instant you die, so without it a corpse (lh still set, nh 0) read
 *  as "your move" and the commit bar reopened over the body — "I was allowed to commit while dead", and the
 *  stale previous-leg tiles that came back after a refresh. The animator's live-view death (view.alive) is
 *  covered too: previewLeg shows you dead a settlement before the chain agrees, and you must not commit in
 *  that window either. pipel() already carries its own view.alive guard. */
const liveRun = () => !!(chain && chain.alive && !chain.done && !chain.retired && (!view || view.alive));
const canAnswer = () => (liveRun() && !!chain.lh && !chain.nh && !dapp.busy("commit"))
  || (pipel() && !queuedWord);
/** THE single source of truth for "the player may submit a commit for this leg RIGHT NOW". canAnswer() is
 *  the run-state gate; this adds the two things the COMMIT BUTTON also required but the "your move" prompt
 *  did not — so the two used to disagree ("Your move…" printed over a greyed button):
 *    • road.length — the terrain has actually rendered tiles to answer (chain.lh can be set a poll before
 *      its hash is fetched and the road built);
 *    • !queuedWord / !busy("commit") — nothing is already queued or in flight for this leg.
 *  The button, the prompt, the clickable-tiles state and the answer bar all derive from this now. */
const canCommitNow = () => road.length > 0 && !queuedWord && !dapp.busy("commit") && canAnswer();
// Gore is part of the animation, not decoration: a fight you cannot see the cost of does not read as a
// fight. Each entry is anchored to a WORLD DEPTH so it scrolls with the road and stays where it happened.
let gore = [];
let scene = [];                 // {depth, tile, fam, ml} — what stands on the road, from events + road
let actFx = null;               // {act, t0, depth, drank} — the action effect playing on the current tile
const ACTFX_MS = 700;
function sceneAddEvents(evs) {
  for (const e of (evs || [])) {
    if (!e || e.skip || e.depth == null) continue;
    // Derive the KILL flag the whole choreography keys on — the engine never emits one, it only
    // reports the spoils. A fight (foes set) that paid out (renown or drops) with the hero still
    // standing IS a kill. Without this, deadAt was never set, no creature ever played its collapse,
    // and every kill staged as a mere trade of blows.
    if (!e.died && e.foes && (e.gain > 0 || e.drops)) e.kill = 1;
    scene = scene.filter((x) => x.depth !== e.depth);         // the resolved outcome replaces any preview
    scene.push({ depth: e.depth, tile: e.tile, fam: e.fam, ml: e.ml, biome: e.biome });
  }
}
// THE DEATH SCENE, retained from the moment the killing step is animated: which finisher plays, when it
// started, WHICH TILE it happened on, and WHAT DID IT. The killer has to be kept here because nothing else
// keeps it — the world layer draws `road`, which is always the leg AHEAD of the run, so the tile that killed
// you has already dropped out of it by the time the corpse is on screen. That is the bug this holds:
// "i died on a tile that had nothing on it? there is no victorious enemy cheering over my dead corpse".
let fatality = null;            // {which, t0, depth, killer:{family,rank,level}|null, prop, cause}
const GORE_MS = 1400;           // spray/spurt lifetime; pools and splatter persist until they scroll away
let hitFlash = null;            // {t0} — the hero just took a hit: a brief flinch + red flash
let shakeT0 = 0, shakeAmp = 0;  // world screen-shake: set on kills/deaths, decays over SHAKE_MS
let attackT0 = 0;               // when the hero's current swing began — drives the 3-frame attack clip
const SHAKE_MS = 240;
const HITFLASH_MS = 260;
const DEATH_SWING_MS = 460;     // on the killing step the hero SWINGS first, THEN the fatality plays —
                                // dying mid-lunge with no last blow was "swing before the death, not after"
// How far in front of the corpse the killer plants itself, in tiles. Far enough apart that the two sprites
// do not merge into one unreadable blob, close enough that it is unmistakably standing OVER the body rather
// than waiting on the next tile along.
const KILLER_STEP = 0.6;
// A hazard is not standing anywhere, so it barely moves off the tile at all: just far enough that its flames
// clear the corpse's chest and the pit is still legibly the thing the body is lying in.
const HAZARD_STEP = 0.3;
// It holds the finishing lunge for as long as the fatality runs, then drops back into the idle menace loop:
// a monster frozen mid-swing forever reads as a rendering fault, one that keeps breathing over your corpse
// reads as a monster that won.
const KILLER_LUNGE_MS = 1600;

function addGore(depth, kind, amount, seed, delay = 0) {
  // `delay` schedules blood for a LATER blow of the same exchange — a four-swing boss fight bleeds four
  // times, not once; the draw loop skips entries whose time has not come
  gore.push({ depth, kind, amount, seed, t0: performance.now() + delay });
  if (gore.length > 140) gore.splice(0, gore.length - 140);   // the road is long; do not grow forever
}

/** The blood-and-finisher seed for a tile. A pure function of (tile, run) on purpose: the same death picks
 *  the same fatality and lays down the same splatter every time it is drawn — including on a page that
 *  loads long after it happened and only ever sees the aftermath. */
const goreSeed = (depth) => ((depth * 2654435761) ^ (myId || 1)) >>> 0;


// ── reading the chain ───────────────────────────────────────────────────────────────────────────
/** My run: the live one if I have it, else my most recent. The contract's `ra` map is the owner index. */
function findMyRun(s) {
  // decode_view has no named-index output: the index only supplies the KEY SET for the maps, so the run
  // ids are the keys of any map. `ra` is the right one because every run has an owner, while a map like
  // `xp` is absent for a run still sitting at zero (a zero slot is a deleted slot).
  const ids = Object.keys(s.ra || {}).map(Number).filter((n) => n > 0);
  const mine = ids.filter((id) => String((s.ra || {})[id] || "").toLowerCase() === String(dapp.me || "").toLowerCase());
  if (!mine.length) return null;
  const live = mine.find((id) => Number((s.lv || {})[id]) === 1 && !Number((s.dn || {})[id]) && !Number((s.rt || {})[id]));
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
    if (chain.lh && dapp.cursor != null && dapp.cursor >= chain.lh) want.push(chain.lh);
    // nh is 0 whenever the march is parked waiting on your answers — 0 is not a height, don't fetch it
    if (chain.nh && dapp.cursor != null && dapp.cursor >= chain.nh) want.push(chain.nh);
    if (want.length) await dapp.blockHashes(want, { fast: true });
    syncView();
    rebuildRoad();
  }

  // anything still queued keeps the poll hot — the queue drains at chain speed, and noticing that a
  // second late defeats the point of queueing
  if (queuedPlan || queuedWord || dapp.inflight) poke();
  // QUEUED ORDERS: dials the player set that are not yet on the chain — sent (and resent after a
  // drop) ahead of any queued answers, so the leg is always governed by the orders it was answered
  // under. Cleared the moment the chain state reflects them.
  if (mode === "march" && chain && queuedPlan) {
    if (!dialsDirty()) queuedPlan = false;                 // landed (or the player dialed back)
    else if (!dapp.busy("plan")) commitPlan();             // act() itself refuses while anything is inflight
  }
  // QUEUED ANSWERS: taken during the pipeline window, sent the moment the leg closes (chain parked at
  // the queued leg). Held until the chain SHOWS the dice scheduled, so a pool-wiped send just retries.
  // They also WAIT for queued orders above — answers never overtake the orders they were made under.
  if (mode === "march" && chain && queuedWord && !queuedPlan) {
    if (!chain.alive || chain.done || chain.retired || queuedWord.leg < chain.leg
        || (chain.nh && chain.leg === queuedWord.leg)) {
      queuedWord = null;                                   // landed, or the run moved on without it
    } else if (!chain.nh && chain.leg === queuedWord.leg && !dapp.busy("commit")) {
      const w = queuedWord;
      act("commit", t("whatCommit", "Answering this stretch of road"), () =>
        dapp.call("commit", [myId, w.word], 0n, t("labelCommit", "Commit your answers"),
          { phase: "commit", leg: w.leg }), "leg", w.leg);
    }
  }

  // INSTANT SETTLEMENT VIEW + AUTO-SETTLE (march only). "This leg resolves in 14 blocks... [click]" was
  // the wrong mechanism and a player said so: every other game derives the outcome from PROVISIONAL chain
  // data the moment it exists and lets the settle tx trail behind. A leg is a pure function of two hashes
  // the exec node already serves, so: dice block exists -> replay it NOW into the animator -> auto-fire
  // advance() through dapp.autoCollect (background-signed, opt-out shared with every game). The preview is
  // deterministic-equal to settlement, so when the real advance lands, syncView sees identical state and
  // nothing re-animates.
  if (mode === "march" && chain && chain.alive && !chain.done && !chain.retired && chain.nh
      && dapp.cursor != null && dapp.cursor >= chain.nh) {
    const before = previewed;
    previewLeg();
    if (previewed !== before) rebuildRoad();   // the pipeline road opens the same instant the dice land
    dapp.autoCollect([{ g: myId + ":" + chain.leg }], () =>
      dapp.call("advance", [myId], 0n, t("labelAdvance", "Settle the leg"),
        { phase: "advance", leg: chain.leg }), { key: (x) => x.g });
  }

  dapp.settleInflight((f) => {
    if (!chain) return false;
    switch (f.phase) {
      // Landed = THE run this click created is on-chain (its id rides in the pend). The fallback (a pend
      // from before the rid was stamped) demands a run that is actually alive — never the corpse.
      case "begin": return f.rid != null ? Number(myId) === Number(f.rid)
        : myId != null && chain.alive && !chain.done && !chain.retired;
      case "plan": return Number(chain.agg) === Number(f.agg) && Number(chain.stance) === Number(f.stance)
        && Number(chain.focus) === Number(f.focus) && Number(chain.healpct) === Number(f.heal);
      case "advance": return Number(chain.leg) > Number(f.leg);
      case "commit": return !!chain.nh || Number(chain.leg) > Number(f.leg);
      case "retire": return !!chain.retired;
      default: return true;
    }
  });
  if (daily) {
    // Permissionless upkeep of today's anchor runs in BOTH modes: a player who never opens the Gauntlet
    // still helps pin the day, and one who does finds it already pinned. It is a value-free background
    // call, so it costs the player nothing but a fee-less signature.
    daily.ensure(async () => sto).then(() => {
      daily.syncPosted(sto);
      if (mode === "daily") { syncDailyView(!view); render(); }
    }).catch(() => {});
  }
  await resolveAliases([dapp.me].filter(Boolean));
  render();
}

/**
 * Walk `view` forward to wherever the chain is, replaying each settled leg through the engine so the
 * animator has per-step events to show. If the replay does not land exactly where the contract says, the
 * chain wins and the view snaps — a pretty animation that disagrees with settlement is a lie.
 */
function syncView() {
  // An optimistic preview runs one leg AHEAD of the chain on purpose (previewLeg): the dice exist, the
  // outcome is already determined, only the settle tx is in flight. Both the "view is ahead -> reset" and
  // the tail mismatch-snap must stand down for exactly that window, or every poll rewinds the animation
  // the player is watching and then replays it — a stutter loop until the settlement lands.
  const previewAhead = view && chain && view.leg === chain.leg + 1
    && previewed === myId + ":" + chain.leg;
  if (previewAhead) return;
  if (!view || view.depth > chain.depth) {
    view = { ...chain, gear: [...chain.gear], mats: [...chain.mats] };
    queue = []; camera = view.depth; lastLegSeen = chain.leg;
    stepFrom = view.depth; stepAt = 0; holdUntil = 0;
    gore = []; fatality = null; scene = []; actFx = null; hitFlash = null;   // a new run starts on clean ground
    if (!view.alive && view.depth > 0) restingDeath();
    return;
  }
  // Replay AT MOST the one leg we can still know the dice for. Manual-only commits each roll height from
  // the cursor, so `nh` is not an arithmetic series any more — a page two or more legs behind cannot
  // reconstruct the intermediate heights and must snap. One leg behind is also the only state a live page
  // ever sees (it polls every 3s and the march parks between legs), so nothing real is lost.
  if (view.leg === chain.leg - 1) {
    const tileH = hashField(view.lh), rollH = hashField(view.nh);
    if (tileH != null && rollH != null) {
      // the ANSWER WORD you committed for this leg (the contract mirrors the latest into cw/cl precisely
      // so this replay can exist; older legs come from our own localStorage) and whichever generation of
      // DIALS governed it — the same fence choice the contract makes
      const evs = E.playLeg(algHashn, view, myId, tileH, rollH, E.dialsFor(chain, view.nh),
                            wordFor(myId, view.leg));
      view.leg += 1;
      view.lh = view.nh; view.nh = chain.nh;     // parked (0) or the height of your next commit
      queue.push(...evs); sceneAddEvents(evs);
    }
  }
  const same = view.depth === chain.depth && view.hp === chain.hp && view.xp === chain.xp;
  if (!same) {                                                  // replay diverged (queued reactions we
    queue = [];                                                 // cannot see) — trust the chain, not us
    view = { ...chain, gear: [...chain.gear], mats: [...chain.mats] };
    camera = Math.max(camera, view.depth - E.LEG);
  }
}

/**
 * Play the just-rolled leg from provisional data, ahead of its settle tx. Only when this page can KNOW the
 * outcome: it needs both hashes and the committed answer word (chain-mirrored cw/cl, or our own
 * localStorage). A spectator without the word simply waits for the real settlement and snaps.
 */
function previewLeg() {
  const tag = myId + ":" + chain.leg;
  if (previewed === tag || !view || view.leg !== chain.leg) return;
  const tileH = hashField(chain.lh), rollH = hashField(chain.nh);
  if (tileH == null || rollH == null) return;
  const word = wordFor(myId, chain.leg);
  if (Number(chain.cl) !== Number(chain.leg) && !word) return;
  previewed = tag;
  const evs = E.playLeg(algHashn, view, myId, tileH, rollH, E.dialsFor(chain, chain.nh), word);
  view.leg = chain.leg + 1;
  view.lh = chain.nh;
  view.nh = 0;                                  // post-settle the march parks; mirror it optimistically
  queue.push(...evs); sceneAddEvents(evs);
}

/**
 * The aftermath of a death this page never watched — a run that was already over when you loaded it.
 *
 * Nothing in storage records what killed you: the contract keeps the run, not the step, and the leg's
 * terrain hash has already been slid out of `lh` by the time the death is settled. So the body and its blood
 * are laid on the tile it actually fell on (a step increments the depth as its last act, so that tile is
 * always `depth - 1`) and the killer is left ABSENT — inventing one would be a lie about the run, and the
 * whole complaint that started this was a death scene that did not match what happened.
 */
function restingDeath() {
  const at = view.depth - 1;
  const seed = goreSeed(at);
  const nfat = (ART.FATALITIES || []).length;
  fatality = {
    which: nfat ? seed % nfat : 0,
    t0: performance.now() - 60000,      // long finished: every fatality clamps to its resting corpse frame
    depth: at, killer: null, prop: null, cause: null,
  };
  addGore(at, "pool", 10, seed ^ 0xdead);
  addGore(at, "splatter", 10, seed ^ 0x2f6d);
}

function rebuildRoad() {
  if (pipel()) {
    // the previewed leg's roll hash is the NEXT leg's terrain — final, readable, answerable now
    const tileH = hashField(chain.nh);
    road = tileH == null ? [] : E.peekLeg(algHashn, view, myId, tileH);
    roadBase = view.depth;
    if (chain.leg + 1 !== lastLegSeen) { answers = new Array(E.LEG).fill(0); lastLegSeen = chain.leg + 1; selTile = -1; }
    return;
  }
  const tileH = hashField(chain.lh);
  road = tileH == null ? [] : E.peekLeg(algHashn, chain, myId, tileH);
  roadBase = chain.depth;
  if (chain.leg !== lastLegSeen) { answers = new Array(E.LEG).fill(0); lastLegSeen = chain.leg; selTile = -1; }
}

// ── the world ───────────────────────────────────────────────────────────────────────────────────
// Presentation only — none of this is consensus. It is derived from the same committed hashes so the
// picture and the rules agree, but the contract deliberately never computes it (doc/autogame.md §4).
// THE FIVE REALMS — the biome is ROLLED BY THE CHAIN per leg (engine biomeFor, from the same terrain
// hash the tiles come from) and rides on every road/scene tile as `t.biome`. This table only says what
// each realm looks like; which realm you are IN was decided by a block hash, like everything else here.
const REALMS = [
  { name: "greenwood", sky: ["#173a33", "#2c5c48"], hill: ["#143326", "#0f2a20"], ground: "#1c3425" },
  { name: "fen",       sky: ["#232e1f", "#3d4a2c"], hill: ["#28331e", "#1e2a18"], ground: "#2b3520" },
  { name: "crags",     sky: ["#1e2733", "#37485c"], hill: ["#242e3c", "#1b232e"], ground: "#28303c" },
  { name: "ashway",    sky: ["#331f1a", "#5c3020"], hill: ["#301f19", "#251813"], ground: "#372419" },
  { name: "nether",    sky: ["#150f22", "#2a2044"], hill: ["#1c1630", "#141024"], ground: "#1e1833" },
];
/** the realm the camera stands in: read off the nearest road/scene tile (the chain put it there) */
function realmAt(depth) {
  let b = 0, best = 1e9;
  for (const t of scene) if (t && t.biome != null && Math.abs(t.depth - depth) < best) { best = Math.abs(t.depth - depth); b = t.biome; }
  for (const t of road) if (t && t.biome != null && Math.abs(t.depth - depth) < best) { best = Math.abs(t.depth - depth); b = t.biome; }
  return REALMS[Math.max(0, Math.min(REALMS.length - 1, b))];
}

const smooth = (t) => t * t * (3 - 2 * t);
// deterministic 0..1 hash for backdrop scatter (celestial jitter, clouds, silhouettes, ground detail)
function bgH(n) {
  let a = (Math.floor(n) | 0) ^ 0x9e3779b9;
  a = Math.imul(a ^ (a >>> 15), 0x2c1b3c6d); a = Math.imul(a ^ (a >>> 12), 0x297a2d39);
  return ((a ^ (a >>> 15)) >>> 0) / 4294967295;
}

function skylineAt(x, seedRow) {
  // value noise: one control point per visible tile, smoothstep-interpolated, so the ridge is continuous
  // instead of jumping every block
  const i = Math.floor(x), f = x - i;
  const a = seedRow[((i % seedRow.length) + seedRow.length) % seedRow.length];
  const b = seedRow[(((i + 1) % seedRow.length) + seedRow.length) % seedRow.length];
  return a + (b - a) * smooth(f);
}

// ── per-tile action effects ─────────────────────────────────────────────────────────────────────
// Every action a player CHOSE gets a visible tell drawn on its tile: a guard spark, a dodge blur, a heal
// bloom, a rally aura. Pure canvas primitives so it needs no sprite sheet; keyed off E.A_* and eased by
// `fx` (0→1). `x` is screen-x of the tile, `gy` the ground row.
function drawActionFx(ctx, x, gy, fx, info) {
  const a = info.act;
  const cy = gy - 74;                                  // roughly chest height on the 5× hero
  const ease = fx < 0.5 ? fx * 2 : (1 - fx) * 2;       // rise-and-fall for glows
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  if (a === E.A_GUARD) {
    // a brace: a bright shield arc in front of the hero with a hard spark where the blow is turned
    ctx.globalAlpha = 0.85 * (1 - fx);
    ctx.strokeStyle = "#cfe6ff"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(x + 24, cy + 10, 34 + fx * 14, -1.1, 1.1); ctx.stroke();
    ctx.fillStyle = "#ffffff"; ctx.globalAlpha = ease;
    for (const [dx, dy] of [[27, -10], [34, 14], [20, 27]]) ctx.fillRect(x + dx, cy + dy, 5, 5);
  } else if (a === E.A_DODGE) {
    // afterimages sliding off the far side — a blur that reads as "not there when it hit"
    ctx.fillStyle = "#7fd0c0";
    for (let k = 1; k <= 3; k++) {
      ctx.globalAlpha = 0.28 * (1 - fx) / k;
      ctx.fillRect(x - 10 - k * 17 - fx * 34, cy - 10, 17, 50);
    }
  } else if (a === E.A_POTION || info.drank) {
    // the draught: a dark-red rush up through him and a few crimson motes — medicine that tastes of iron,
    // not a videogame '+'
    ctx.globalAlpha = 0.55 * ease; ctx.fillStyle = "#5c1620";
    ctx.fillRect(x - 8, cy - 20 + (1 - ease) * 30, 17, 44);
    ctx.globalAlpha = 0.9 * ease; ctx.fillStyle = "#c02034";
    for (const [dx, ph] of [[-12, 0], [2, 14], [12, 6]]) {
      ctx.fillRect(x + dx, cy + 14 - ph - fx * 38, 3, 6);
      ctx.fillRect(x + dx + 1, cy + 11 - ph - fx * 38, 1, 3);
    }
  } else if (a === E.A_RALLY) {
    // old gold, not fairy dust: one dim ring and embers pulled UP into him — resolve, gathered
    ctx.globalAlpha = 0.7 * (1 - fx); ctx.strokeStyle = "#a87c24"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x + 7, cy + 14, 12 + fx * 42, 0, 6.3); ctx.stroke();
    ctx.globalAlpha = 0.8 * ease; ctx.fillStyle = "#d4a83c";
    for (const [dx, ph] of [[-14, 4], [0, 0], [13, 8]])
      ctx.fillRect(x + dx, cy + 30 - ph - fx * 34, 2, 5);
  } else if (a === E.A_REST) {
    // breath in cold air: two grey wisps curling off him and gone — no cartoon 'z'
    ctx.globalAlpha = 0.5 * ease; ctx.fillStyle = "#6a7280";
    for (const [dx, ph] of [[6, 0], [-4, 10]]) {
      const wy = cy - 6 - ph - fx * 30;
      ctx.fillRect(x + dx + Math.round(Math.sin(fx * 9 + ph) * 4), wy, 3, 8);
      ctx.fillRect(x + dx + 1 + Math.round(Math.sin(fx * 9 + ph + 1) * 4), wy - 8, 2, 6);
    }
  }
  // A_STRIKE draws NOTHING here on purpose: the blade's own wake (in the art, pouring off the edge)
  // is the strike effect. The old floating white slash across the tile was a second, disconnected
  // flash stacked behind the sword — the exact "effects behind the sword" complaint, twice over.
  ctx.restore();
  ctx.globalAlpha = 1;
}

function drawWorld() {
  const cv = $("world"), ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.imageSmoothingEnabled = false;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  {  // kill/death screen-shake: a fast decaying jolt. Applied as a transform so EVERYTHING kicks once.
    const sa = performance.now() - shakeT0;
    if (sa < SHAKE_MS && shakeAmp) {
      const k = (1 - sa / SHAKE_MS) * shakeAmp;
      ctx.translate(Math.round(Math.sin(sa * 0.09) * k), Math.round(Math.cos(sa * 0.13) * k * 0.6));
    }
  }
  const depth = Math.floor(camera);
  const frac = camera - depth;
  const night = E.isNight(depth);
  const bio = realmAt(depth);

  // sky
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, night ? "#080b14" : bio.sky[0]);
  g.addColorStop(1, night ? "#131a26" : bio.sky[1]);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  // stars at night — deterministic from depth so they do not crawl
  if (night) {
    for (let k = 0; k < 110; k++) {
      const sx = ((k * 7919 + depth * 13) % W), sy = (k * 5261) % (H * 0.45);
      const b = k % 7 === 0 ? 0.85 : k % 3 === 0 ? 0.55 : 0.3;
      ctx.fillStyle = `rgba(230,237,243,${b})`;
      ctx.fillRect(sx, sy, k % 11 === 0 ? 2 : 1, k % 11 === 0 ? 2 : 1);
    }
  }

  // a SUN or MOON: a soft disc low over the horizon, creeping with a very slow parallax so distance reads
  {
    const cx = W * 0.72 - (camera * 6) % (W * 1.5);
    const cy = H * (night ? 0.18 : 0.24);
    const rad = night ? 28 : 38;
    ctx.save();
    for (let r = rad + 18; r > rad; r--) {                 // a bloomed halo, no blur filter needed
      ctx.globalAlpha = 0.04; ctx.fillStyle = night ? "#cdd7e6" : "#ffe9b0";
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, 6.3); ctx.fill();
    }
    ctx.globalAlpha = 1; ctx.fillStyle = night ? "#d7dfe8" : "#ffdf8c";
    ctx.beginPath(); ctx.arc(cx, cy, rad, 0, 6.3); ctx.fill();
    if (night) {                                            // crescent bite
      ctx.fillStyle = night ? "#0e1420" : "#000";
      ctx.beginPath(); ctx.arc(cx + 12, cy - 7, rad, 0, 6.3); ctx.fill();
    }
    ctx.restore();
  }

  // drifting cloud bands — two parallax layers of soft blobs, deterministic per cell so they never crawl
  ctx.save();
  for (let layer = 0; layer < 2; layer++) {
    const par = 0.05 + layer * 0.05, span = 460;
    const yBand = H * (0.14 + layer * 0.12);
    const off = (camera * par * 40) % span;
    ctx.globalAlpha = night ? 0.10 + layer * 0.04 : 0.16 + layer * 0.06;
    ctx.fillStyle = night ? "#9fb0c6" : "#e8eef5";
    for (let c = -1; c < Math.ceil(W / span) + 1; c++) {
      const seed = ((Math.floor(camera * par / (span / 40)) + c) | 0);
      const cx = c * span - off + bgH(seed) * 120;
      const cy = yBand + bgH(seed * 3 + 1) * 26;
      const wparts = 4 + Math.floor(bgH(seed * 7 + 2) * 3);
      for (let b = 0; b < wparts; b++) {
        const bx = cx + b * 38 + bgH(seed * 13 + b) * 17;
        const by = cy + (bgH(seed * 17 + b) - 0.5) * 14;
        const br = 20 + bgH(seed * 19 + b) * 20;
        ctx.beginPath(); ctx.ellipse(bx, by, br, br * 0.55, 0, 0, 6.3); ctx.fill();
      }
    }
  }
  ctx.restore(); ctx.globalAlpha = 1;

  // a haze band right on the horizon — pushes the ridges back and softens the join
  { const hy = H * 0.44, hg = ctx.createLinearGradient(0, hy - 42, 0, hy + 42);
    hg.addColorStop(0, "rgba(0,0,0,0)"); hg.addColorStop(0.5, night ? "rgba(120,140,170,.10)" : "rgba(210,225,235,.16)");
    hg.addColorStop(1, "rgba(0,0,0,0)"); ctx.fillStyle = hg; ctx.fillRect(0, hy - 42, W, 84); }

  // three parallax ridges from the visible tiles' scenery values
  const rows = road.length ? road.map((t) => t.scen) : [4096];
  // Pixels per step. This MUST exceed the sprite width or the road becomes a shoulder-to-shoulder lineup:
  // at 44px with 96px sprites every creature overlapped its neighbours and sixteen of them read as a zoo
  // rather than a world. At 120 only ~4 tiles ahead are on screen at once, which is what a side-scroller
  // should show — the road strip below already lists the whole leg.
  const TILE = 240;   // canvas is 2x now (1440x600): same physical tile width, art pixels half the size
  for (let layer = 0; layer < 3; layer++) {
    const par = 0.25 + layer * 0.3;
    const base = H * (0.45 + layer * 0.09);
    const amp = 48 - layer * 13;
    ctx.fillStyle = layer < 2 ? bio.hill[layer % 2] : bio.ground;
    ctx.beginPath(); ctx.moveTo(0, H);
    for (let px = 0; px <= W; px += 4) {
      const wx = (camera + px / TILE) * par + layer * 3.7;
      const n = (skylineAt(wx, rows) % 4096) / 4096;
      ctx.lineTo(px, base - n * amp);
    }
    ctx.lineTo(W, H); ctx.closePath(); ctx.fill();

    // distant silhouettes standing on the middle ridge — trees / peaks / ruined columns / spires by biome,
    // deterministic per world-cell so they scroll but never flicker
    if (layer === 1) {
      const par = 0.55, baseY = H * 0.54;
      const kind = bio.name;
      ctx.fillStyle = night ? "#0c1420" : bio.hill[1];
      for (let cell = -1; cell < Math.ceil(W / (TILE * par)) + 2; cell++) {
        const wcell = Math.floor(camera * par) + cell;
        if (bgH(wcell * 31 + 5) > 0.55) continue;               // ~half the cells are bare
        const sx = Math.round((wcell - camera * par) * TILE * par + bgH(wcell * 3) * 70);
        if (sx < -50 || sx > W + 50) continue;
        const hh = 38 + bgH(wcell * 7) * 52;
        if (kind === "ashway") {                                 // charred snags and smoke-thin spires
          ctx.beginPath(); ctx.moveTo(sx - 12, baseY); ctx.lineTo(sx, baseY - hh); ctx.lineTo(sx + 12, baseY);
          ctx.closePath(); ctx.fill();
          ctx.fillRect(sx - 1, baseY - hh - 10, 3, 12);
        } else if (kind === "nether") {                          // leaning gravestones and a bone arch
          ctx.fillRect(sx - 5, baseY - hh * 0.6, 10, hh * 0.6);
          ctx.fillRect(sx - 8, baseY - hh * 0.6 - 5, 16, 6);
          if (bgH(wcell * 11) > 0.6) { ctx.fillRect(sx + 16, baseY - hh, 5, hh); ctx.fillRect(sx + 14, baseY - hh - 4, 20, 5); }
        } else if (kind === "crags") {                           // hard peaks
          ctx.beginPath(); ctx.moveTo(sx - 20, baseY); ctx.lineTo(sx - 4, baseY - hh); ctx.lineTo(sx + 3, baseY - hh * 0.6);
          ctx.lineTo(sx + 10, baseY - hh * 0.85); ctx.lineTo(sx + 22, baseY); ctx.closePath(); ctx.fill();
        } else if (kind === "fen") {                             // drowned willows: a lean trunk, a droop
          ctx.fillRect(sx - 2, baseY - hh * 0.8, 4, hh * 0.8);
          ctx.beginPath(); ctx.ellipse(sx, baseY - hh * 0.8, 20, 10, 0, 0, 6.3); ctx.fill();
          ctx.fillRect(sx - 14, baseY - hh * 0.8 + 6, 3, hh * 0.35);
          ctx.fillRect(sx + 12, baseY - hh * 0.8 + 4, 3, hh * 0.45);
        } else {                                                 // greenwood conifer
          ctx.fillRect(sx - 2, baseY - hh, 5, hh);
          for (let t = 0; t < 3; t++) {
            const ty = baseY - hh + t * (hh / 3), tw = 10 + t * 7;
            ctx.beginPath(); ctx.moveTo(sx - tw, ty + 14); ctx.lineTo(sx, ty - 7); ctx.lineTo(sx + tw, ty + 14);
            ctx.closePath(); ctx.fill();
          }
        }
      }
    }
  }

  // the road itself
  const GY = Math.round(H * 0.80);
  ctx.fillStyle = bio.ground; ctx.fillRect(0, GY, W, H - GY);
  ctx.fillStyle = "rgba(0,0,0,.25)"; ctx.fillRect(0, GY, W, 2);
  // texture on the dirt: little tufts and pebbles fixed to WORLD position, so they scroll under the hero
  // and sell the motion instead of a flat bar. Deterministic per world cell.
  for (let i = -2; i < Math.ceil(W / 26) + 2; i++) {
    const wcell = Math.floor(camera * TILE / 26) + i;
    const gx = Math.round(i * 26 - ((camera * TILE) % 26) + bgH(wcell * 5) * 22);
    if (gx < -6 || gx > W + 6) continue;
    const gy2 = GY + 6 + Math.floor(bgH(wcell * 11) * (H - GY - 10));
    const r = bgH(wcell * 3);
    if (r < 0.4) {                                            // a grass tuft
      ctx.strokeStyle = night ? "#12251a" : "#2c4a34"; ctx.lineWidth = 1; ctx.beginPath();
      ctx.moveTo(gx, gy2); ctx.lineTo(gx - 3, gy2 - 6); ctx.moveTo(gx, gy2); ctx.lineTo(gx, gy2 - 8);
      ctx.moveTo(gx, gy2); ctx.lineTo(gx + 3, gy2 - 6); ctx.stroke();
    } else if (r < 0.6) {                                     // a pebble
      ctx.fillStyle = night ? "#10161f" : "rgba(0,0,0,.28)";
      ctx.fillRect(gx, gy2, 2 + Math.floor(bgH(wcell * 9) * 2), 2);
    }
  }

  // What is coming, standing ON the road in world space. These used to be 20px EMOJI at half opacity next
  // to a hand-drawn pixel warrior, which read as the player swinging his sword at nothing.
  const heroX = Math.round(W * 0.30);
  const now = performance.now();
  const RANK = { [E.ELITE]: 1, [E.BOSS]: 2 };
  const PROP = { [E.HAZARD]: "hazard", [E.SNARE]: "snare", [E.QUAG]: "quag", [E.GALE]: "gale",
                 [E.TOLLGATE]: "tollgate", [E.CACHE]: "cache", [E.BARROW]: "barrow",
                 [E.ARMORY]: "armory", [E.VEIN]: "vein", [E.GROVE]: "grove", [E.SHRINE]: "shrine",
                 [E.WELL]: "well", [E.CAMP]: "camp", [E.IDOL]: "idol", [E.PYRE]: "pyre",
                 [E.FORGE]: "forge", [E.FORK]: "fork", [E.RELIC]: "relic" };
  let engaging = false;
  // Is the world walking this frame? Computed HERE, before the road loop, because both the hero's
  // stride and a creature's pre-fight bristle key off it — when the march stops, everything must
  // go STILL instead of fencing with the air forever.
  const moving = camera > (drawWorld._lastCam ?? camera) + 0.0005;
  drawWorld._lastCam = camera;
  // Once the hero is down there IS no road ahead — the run is over and nothing will ever walk it. Leaving it
  // drawn put an unrelated monster from the next (never-to-be-walked) leg a tile and a half past the corpse,
  // which is worse than an empty tile: two creatures on screen and no way to tell which one killed you.
  if ((chain || demoOn || (isDaily() && daily && (daily.st.run || daily.st.world))) && !fatality) {
    // Draw from the SCENE (resolved outcomes near the camera) merged with the answering ROAD (upcoming,
    // still-unresolved tiles), keyed by depth so the resolved version wins. This is what fixed the "skips
    // everything" downgrade: the leg being WALKED now always has its creatures, because they come from the
    // events that produced it — not from `road`, which the pipeline points at the next leg.
    const byDepth = new Map();
    for (const t of road) if (t && t.depth != null) byDepth.set(t.depth, t);
    for (const t of scene) byDepth.set(t.depth, t);            // scene overrides: the tile actually walked
    const lo = Math.floor(camera) - 3, hi = Math.floor(camera) + Math.ceil((W / TILE) + 2);
    for (const t of byDepth.values()) {
      if (t.depth < lo || t.depth > hi) continue;
      // Half a tile forward: a creature standing at exactly (depth - camera) sits ON the hero the moment he
      // reaches its tile, and the two sprites merge into an unreadable blob. Offsetting it to the far side
      // of its own tile means he WALKS INTO it, which is also what the fight is.
      const dx = t.depth - camera + 0.5;
      const x = heroX + Math.round(dx * TILE);
      if (x < -2 * TILE || x > W + 2 * TILE || t.tile === E.ROAD) continue;
      const passed = dx < -0.25;                       // already walked through: it is done for
      // FORK is a prop, not a creature: the split is what you can SEE; which monster waits in the lane is
      // decided only when the leg resolves. The old lumping drew a goblin on every fork — and then gave it
      // a death frame as you walked past, killing a creature that never existed.
      const combat = t.tile === E.MONSTER || t.tile === E.HORDE || t.tile === E.ELITE
        || t.tile === E.AMBUSH || t.tile === E.MIMIC || t.tile === E.BOSS;

      if (combat && ART.drawMonster) {
        const rank = RANK[t.tile] || 0;
        // the art's native grid DOUBLED (MON box 48 -> 96), so scale 3 here is 1.2x yesterday's scale 5
        // on screen — deliberately a fifth larger, at twice the source resolution
        const scale = rank === 2 ? 4 : 3;
        const mw = (ART.MON_W || 32) * scale, mh = (ART.MON_H || 32) * scale;
        ctx.save(); ctx.globalAlpha = 0.30; ctx.fillStyle = "#000";
        ctx.beginPath(); ctx.ellipse(x, GY + 5, 34 * (scale / 2.5), 7, 0, 0, 6.3); ctx.fill(); ctx.restore();
        // The STAGED fight (showEvent): fightAt = the swing begins, deadAt = the swing LANDS. It dies to
        // the blow, in front of the hero — never behind him as he strolls on. wonFight = it killed HIM.
        // dead ONLY if a kill was staged and the swing has landed. A monster he dodged/sprinted past was
        // never fought and stays ALIVE behind him — showing it dead was its own small lie.
        const deadNow = !t.wonFight && !!t.deadAt && now >= t.deadAt;
        const exLen = (t.rounds || 1) * SWING_MS + 200;
        // an exchange FIGHTS for exactly its staged length; the proximity clause only bristles a
        // creature the hero is still WALKING INTO. Bare proximity used to hold `fighting` forever
        // once the march stopped next to something alive — an eternal shadow-boxing loop.
        const exchange = !deadNow && !!t.fightAt && now - t.fightAt < exLen;
        const fighting = exchange || (!deadNow && !t.fightAt && Math.abs(dx) < 0.75 && moving);
        // the clips, by index (autogame-art.js exports the map): 0..2 breathe, 3 wind-up, 4 strike,
        // 5 crumple, 6 settled heap. A fight ALTERNATES 3->4 once per SWING_MS round — the exchange —
        // and the creature FLINCHES (hurt wash) as each of the hero's blows lands mid-round.
        // Death plays in THREE beats, not a jump-cut: the blow rocks it back (hurt wash + stagger),
        // the knees go (crumple), then the heap settles.
        const sinceDead = deadNow ? now - t.deadAt : 0;
        const settled = deadNow && sinceDead >= 520;
        const phase = t.fightAt ? (now - t.fightAt) % SWING_MS : 0;
        const frame = deadNow ? (sinceDead < 170 ? 0
                                : settled ? (ART.MON_DEATH_FRAME || 6) : (ART.MON_CRUMPLE_FRAME || 5))
          : fighting ? (t.fightAt && phase >= SWING_MS * 0.55 ? (ART.MON_STRIKE_FRAME || 4)
                                                              : (ART.MON_ATTACK_FRAME || 3))
          : idleAt(now, t.depth);
        const flinch2 = fighting && t.fightAt && phase >= SWING_MS * 0.34 && phase < SWING_MS * 0.55;
        const stagger = deadNow && sinceDead < 170 ? Math.round(6 * sinceDead / 170) : 0;
        // only a STAGED exchange arms the hero's swing. Bare proximity used to set it too, which had
        // him mid-attack-clip while a sprinted-past creature slid THROUGH his sprite — unreadable.
        if (exchange) engaging = true;
        // a HORDE is a PACK: the same creature drawn thrice, staggered into the tile, the back rank
        // dimmer — one sprite on a "double pull" tile undersold what you were about to wade into.
        // An AMBUSH lurks: drawn half-faded until the fight is actually joined, because the whole tile
        // is a thing you did not see coming.
        const pack = t.tile === E.HORDE ? 3 : 1;
        for (let p = pack - 1; p >= 0; p--) {
          const px2 = x + p * Math.round(TILE * 0.17) + (p ? 0 : stagger),
                lurk = t.tile === E.AMBUSH && !fighting && !deadNow;
          ctx.globalAlpha = (p ? 0.55 + 0.15 * (pack - p) : 1) * (lurk ? 0.55 : 1) * (passed && deadNow ? 0.9 : 1);
          ART.drawMonster(ctx, Math.round(px2 - mw / 2), GY + 2 - mh,
            { family: t.fam, rank, level: t.ml, biome: t.biome || 0, mimic: t.tile === E.MIMIC,
              frame: p && !fighting && !deadNow ? (frame + p) % (ART.MON_IDLE_FRAMES || 3) : frame,
              scale, facing: -1, dead: settled,
              hurt: !p && (flinch2 || (deadNow && sinceDead < 170)) });
        }
        ctx.globalAlpha = 1;
      } else if (PROP[t.tile] && ART.drawProp) {
        const scale = 3;
        const pw = (ART.MON_W || 32) * scale, ph = (ART.MON_H || 32) * scale;
        ctx.save(); ctx.globalAlpha = 0.22; ctx.fillStyle = "#000";
        ctx.beginPath(); ctx.ellipse(x, GY + 5, 36, 7, 0, 0, 6.3); ctx.fill(); ctx.restore();
        ctx.globalAlpha = passed ? 0.35 : 1;
        ART.drawProp(ctx, Math.round(x - pw / 2), GY + 2 - ph,
          { kind: PROP[t.tile], frame: Math.floor(now / 340 + t.depth * 1.9) % (ART.PROP_FRAMES || 3), scale });
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
    // Blood is drawn in the SAME box as a monster (BLOOD_W × BLOOD_H, ground row MON_GROUND_Y), so it takes
    // the same corner conversion. It was being handed the ground point directly, which put the whole frame
    // one box BELOW the road line — 144px down, off the bottom of a 300px canvas. Every drop of blood this
    // game has ever spilled was drawn underground, which is the other half of "i died on a tile that had
    // nothing on it": there was never a pool under the corpse to see.
    const bw = (ART.BLOOD_W || 48) * 3, bh = (ART.BLOOD_H || 48) * 3;
    for (const g of gore) {
      const gx = heroX + Math.round((g.depth - camera) * TILE);
      if (gx < -TILE || gx > W + TILE) continue;
      const age = now - g.t0;
      if (age < 0) continue;                    // scheduled for a LATER blow of the exchange
      const lasting = g.kind === "pool" || g.kind === "splatter";
      if (!lasting && age > GORE_MS) continue;
      const frame = lasting ? Math.min(5, Math.floor(age / 160)) : Math.floor(age / (GORE_MS / 6));
      ART.drawBlood(ctx, Math.round(gx - bw / 2), GY + 2 - bh,
                    { kind: g.kind, frame, scale: 3, facing: 1, seed: g.seed, amount: g.amount });
    }
    gore = gore.filter((g) => g.kind === "pool" || g.kind === "splatter" || now - g.t0 <= GORE_MS
                              || g.depth > camera - 40);
  }

  // the ACTION EFFECT for this tile — every non-plain choice gets a visible tell, drawn at the tile the
  // hero is standing on so "something was chosen here" is never invisible.
  if (actFx && now - actFx.t0 < ACTFX_MS) {
    const fx = (now - actFx.t0) / ACTFX_MS;                   // 0..1 progress
    const ax = heroX + Math.round((actFx.depth - camera) * TILE);
    drawActionFx(ctx, ax, GY, fx, actFx);
  } else if (actFx) actFx = null;

  // the victor, after the blood so it stands in it and before the body so the body lies in front of it
  drawKiller(ctx, GY, heroX, TILE, now);

  // the warrior — always at the same screen x; the world moves, not him. He swings when something is
  // actually in front of him, not merely when the event queue happens to hold a fight.
  // He also STANDS STILL when the world is not moving (`moving`, measured before the road loop): a walk
  // cycle playing against a static background reads as a treadmill, and this game spends most of its
  // time waiting for the next block.
  // BOSS MUSIC: swap the theme while a boss looms within ~2 tiles ahead (or is being fought). Cheap check
  // over the same scene+road the world already draws; the audio engine no-ops if the state is unchanged.
  {
    let near = false;
    const around = (t) => t && t.tile === E.BOSS && t.depth >= Math.floor(camera) - 1 && t.depth <= Math.floor(camera) + 2;
    for (const t of scene) if (around(t)) { near = true; break; }
    if (!near) for (const t of road) if (around(t)) { near = true; break; }
    audio.setBoss(near && !!view && view.alive);
  }
  // stride keyed to DISTANCE, not the clock — wall-clock frames made his feet slide over the ground
  // whenever the camera speed changed (catch-up, dwells, the approach into a fight)
  const frame = moving ? Math.floor((camera * TILE) / 56) % 4 : 0;
  // footfalls, keyed to the SAME stride as the legs: the two plant frames each land a soft scuff.
  // The walk was mute — a marching game where the march made no sound.
  if (moving && frame !== drawWorld._stride) {
    drawWorld._stride = frame;
    if (frame & 1) audio.sfx("step");
  }
  const hurt = view && view.hp * 4 < view.maxhp;
  const dead = view ? !view.alive : false;
  // The DEATH plays only after the hero's last swing: while now < fatality.t0 he is still on his feet,
  // mid-lunge, and the killer is landing the blow — then the fatality takes over.
  const dying = dead && fatality && now < fatality.t0;
  // a hit flinch: a couple of frames of shake + a red wash, self-expiring
  const flinch = hitFlash && now - hitFlash.t0 < HITFLASH_MS;
  const shake = flinch ? (Math.floor((now - hitFlash.t0) / 40) % 2 ? 3 : -3) : 0;
  if (dead && fatality && !dying && ART.drawFatality) {
    const fr = Math.floor((now - fatality.t0) / 130);
    const spec = ART.FATALITIES[fatality.which] || { frames: 8 };
    // A fatality is drawn in the GORE box (FAT_W × FAT_H, the monster/blood box), not the warrior's own
    // 32×32 cell, precisely so the corpse, the pool and the killer share one ground line. Placing it with
    // footX/footY — the warrior conversion — sank the whole finisher a box below the road, so the death the
    // art file spends 300 lines on was being drawn under the dirt.
    const fw = (ART.FAT_W || 48) * 3, fh = (ART.FAT_H || 48) * 3;
    ART.drawFatality(ctx, Math.round(heroX - fw / 2), GY + 2 - fh, {
      which: fatality.which, frame: Math.min(fr, (spec.frames || 8) - 1), scale: 3, facing: 1,
      gear: view ? view.gear : new Array(6).fill(0),
    });
  } else {
    // grounded: a contact shadow, a two-pixel walk bob synced to the stride, and a LUNGE into the enemy
    // while the swing plays — the attack now visibly moves INTO the thing it kills.
    const bob = moving ? (frame === 1 || frame === 3 ? -3 : 0) : 0;
    const attacking = engaging || dying;
    // the swing is a 3-frame clip: cocked -> lunge-strike -> follow-through, keyed off when the fight
    // (or the death swing) began; the lunge rides the strike frame only
    const swingT = dying ? now - (fatality ? fatality.swingStart : now)
      : attackT0 ? now - attackT0 : 0;
    // the swing LOOPS for the length of the exchange — raise, cleave, carry, again — then holds the
    // follow-through; one capped clip made every fight look like a single tap
    const nR = dying ? 1 : Math.max(1, attackRounds);
    const atkFrame = swingT < nR * SWING_MS
      ? Math.min(2, Math.floor((swingT % SWING_MS) / (SWING_MS / 3)))
      : (ART.ATTACK_FRAMES || 3) - 1;
    // he fights at RANGE: fall back off the creature's sprite for the whole exchange, and let a
    // deeper lunge close the distance on the strike frame — standing inside the monster read as
    // the hero trampling the thing he was fencing with
    const back = attacking ? 36 : 0;
    const lunge = attacking && atkFrame === 1 ? 26 : 0;
    const hx2 = heroX + shake - back + lunge;
    ctx.save(); ctx.globalAlpha = 0.32; ctx.fillStyle = "#000";
    ctx.beginPath(); ctx.ellipse(hx2, GY + 5, 30, 7, 0, 0, 6.3); ctx.fill(); ctx.restore();
    drawWarrior(ctx, footX(hx2, 3), footY(GY + 2 + bob, 3), {
      gear: view ? view.gear : new Array(6).fill(0),
      frame: attacking ? atkFrame : frame, scale: 3, facing: 1,
      hurt: hurt || !!flinch, dead: false,
      attacking,                              // his final blow lands before he falls
    });
    if (flinch) {                              // a red wash over the flinching hero
      ctx.save(); ctx.globalAlpha = 0.35 * (1 - (now - hitFlash.t0) / HITFLASH_MS);
      ctx.fillStyle = "#c0202a";
      ctx.fillRect(heroX - 41 + shake, GY - 192, 82, 192); ctx.restore(); ctx.globalAlpha = 1;
    } else if (hitFlash && now - hitFlash.t0 >= HITFLASH_MS) hitFlash = null;
  }

  drawHazardTile(ctx, GY, heroX, TILE, now);   // in FRONT of the body: see the note on the function

  // night veil / weather
  if (night) { ctx.fillStyle = "rgba(6,10,20,.35)"; ctx.fillRect(0, 0, W, H); }
}

/** Where the death happened, in screen x. The camera holds on that depth (see tick), so this settles exactly
 *  on the hero's own fixed screen x — the body, its blood and whatever killed it end up ONE group, instead
 *  of three things a tile apart. */
const deathX = (heroX, TILE) => heroX + Math.round((fatality.depth - camera) * TILE);

/**
 * The victor: whatever killed the hero, still standing on the tile where it did it.
 *
 * The killer used to vanish the instant its combat event stopped animating, because the world layer only
 * ever draws `road` — the leg AHEAD of the run — and the tile you died on is behind you the moment the step
 * resolves. The run therefore ended with a corpse alone on bare ground: "i died on a tile that had nothing
 * on it? there is no victorious enemy cheering over my dead corpse". `fatality.killer` is the identity kept
 * back from the killing step (showEvent), and this draws it for as long as the corpse is drawn.
 *
 * Drawn BEFORE the body, so the body lies in front of the thing that made it.
 */
function drawKiller(ctx, GY, heroX, TILE, now) {
  if (!fatality || !fatality.killer || !ART.drawMonster) return;
  const k = fatality.killer;
  const scale = k.rank === 2 ? 4 : 3;                    // a boss looms here exactly as it looms on the road
  const mw = (ART.MON_W || 48) * scale, mh = (ART.MON_H || 48) * scale;
  const lungeT = now - fatality.t0;
  const frame = lungeT < KILLER_LUNGE_MS
    ? (lungeT < 220 ? (ART.MON_ATTACK_FRAME || 3) : (ART.MON_STRIKE_FRAME || 4))
    : idleAt(now, fatality.depth || 0);
  ART.drawMonster(ctx, Math.round(deathX(heroX, TILE) + KILLER_STEP * TILE - mw / 2), GY + 2 - mh,
    { family: k.family, rank: k.rank, level: k.level, biome: k.biome || 0, mimic: !!k.mimic,
      frame, scale, facing: -1 });
}

/**
 * The other way to die: a HAZARD, where nobody is standing over you because nobody was ever there. Drawing a
 * monster on that tile would be a lie about how the run ended, so the cause is the tile itself.
 *
 * Drawn AFTER the body, unlike the killer, and half a body to the side. The pit is a low sprite and a corpse
 * lies flat across it, so behind the body it is a pit you cannot see — which is precisely the bare-tile death
 * this whole change exists to fix. Flames in front of the legs read as a body lying IN it.
 */
function drawHazardTile(ctx, GY, heroX, TILE, now) {
  if (!fatality || !fatality.prop || !ART.drawProp) return;
  const pw = (ART.PROP_W || 48) * 3, ph = (ART.PROP_H || 48) * 3;
  ART.drawProp(ctx, Math.round(deathX(heroX, TILE) + HAZARD_STEP * TILE - pw / 2), GY + 2 - ph,
               { kind: fatality.prop, frame: Math.floor(now / 340 + (fatality.depth || 0) * 1.9) % (ART.PROP_FRAMES || 3), scale: 3 });
}

// the animation loop: the camera walks toward the settled depth, popping one event per tile as it passes
// The walk is TIME-BASED and DWELLS on what matters. Each step takes WALK_MS to cross, and a step that
// LANDED A FIGHT holds for FIGHT_MS on top so you actually see the blow and the blood before moving on —
// gliding smoothly past every tile at a constant speed was the "too quick, hard to see" complaint. The
// hero still catches up on a long backlog by shortening the cross time, never by skipping a tile.
const WALK_MS = 620;            // ms to cross one ordinary tile
const FIGHT_MS = 560;           // hold on a tile where a blow landed (he trades, then moves on)
const KILL_MS = 950;            // hold on a KILL: the last swing + the body drops + a beat of blood
const SWING_MS = 420;           // one full TRADE of the exchange: his raise-cleave, its wind-up-strike
let attackRounds = 1;           // how many trades the current exchange runs (set per fight by showEvent)
// The breath loop: most of the cycle is frame 0 — dead still — with one slow swell and one weight shift.
// A flat 3-frame ping-pong at 220ms read as a wind-up toy; menace is stillness, and no two creatures on
// the road breathe in phase (the depth de-phases them).
const IDLE_SEQ = [0, 0, 0, 0, 1, 1, 2, 0];
const idleAt = (now2, depth2) => IDLE_SEQ[Math.floor(now2 / 300 + depth2 * 2.7) % IDLE_SEQ.length];
let exchangeRounds = 1;         // the same number, read by the camera-hold logic in tick()
let holdUntil = 0;              // wall-clock until which the camera pauses on the current tile
let stepFrom = 0, stepAt = 0;   // the walk animation: from depth `stepFrom` (fractional), started at `stepAt`
// Where the hero's sword visually meets the thing standing at depth+0.5, in tiles short of it. The
// monster is half a tile into its own tile; the hero's reach (lunge + blade at scale 3) covers the rest.
const CONTACT = 0.22;
/** The camera depth at which an event FIRES. Position, not counting — events used to pop only when a
 *  whole tile-cross completed, which put every fight half a tile BEHIND the hero. */
function popPointOf(ev) {
  if (ev.died || ev.kill || ev.dmg || ev.sting) return ev.depth + CONTACT;   // at sword-contact, in FRONT
  if (ev.tile !== E.ROAD) return ev.depth + 0.5;                             // standing ON the prop
  return ev.depth + 0.999;                                                   // nothing here: the far edge
}
// ── ATTRACT MODE ────────────────────────────────────────────────────────────────────────────────
// With no run on screen the stage used to be a still frame, which made every animation bug invisible
// until a real player hit it. The demo march runs the REAL pipeline — engine leg replay, event queue,
// contact staging, the same draw calls — on a deterministic local seed, so the page demonstrates the
// game to visitors and every visual change is verifiable by screenshot without a wallet or a chain.
let demoOn = false, demoLeg = 0;
const DEMO_SEED = 20260721, DEMO_RID = 777;
function demoStep(now) {
  const active = !isDaily() && !(chain && (chain.lh || chain.depth));
  if (!active) {
    if (demoOn) { demoOn = false; view = null; queue = []; scene = []; gore = []; fatality = null; camera = 0; }
    return;
  }
  if (demoOn && view && !view.alive && now > holdUntil + 2600) demoOn = false;   // fell: linger, then again
  if (!demoOn) {
    demoOn = true; demoLeg = 0;
    view = Object.assign(E.newRun({}), { leg: 0, lh: 0, nh: 0 });
    view.agg = 4;
    camera = 0; stepFrom = 0; stepAt = 0; holdUntil = 0;
    queue = []; scene = []; gore = []; fatality = null; actFx = null; hitFlash = null;
  }
  // roll the next leg the moment the walk catches up — the demo never parks
  if (view.alive && !queue.length && camera >= view.depth - 0.05 && now > holdUntil) {
    const th = algHashn([DEMO_SEED, demoLeg * 2 + 1]);
    const rh = algHashn([DEMO_SEED, demoLeg * 2 + 2]);
    const SHOW = { [E.MONSTER]: E.A_STRIKE, [E.HORDE]: E.A_SPRINT, [E.ELITE]: E.A_GUARD,
                   [E.AMBUSH]: E.A_GUARD, [E.HAZARD]: E.A_DODGE, [E.GALE]: E.A_DODGE,
                   [E.IDOL]: E.A_POTION, [E.FORK]: E.A_RIGHT };
    const acts = [];
    for (let i = 0; i < E.LEG; i++) {
      const { a } = E.sliceTile(E.words(algHashn, th, DEMO_RID, i));
      const cls = E.tileOf(a, view.depth + i);
      // alternate strike/plain on ordinary monsters so both reads of a fight get shown
      acts.push(cls === E.MONSTER && i % 2 ? E.A_DEFAULT : (SHOW[cls] ?? E.A_DEFAULT));
    }
    const evs = E.playLeg(algHashn, view, DEMO_RID, th, rh, { agg: 4 }, E.packLeg(acts));
    demoLeg += 1; view.leg = demoLeg;
    queue.push(...evs); sceneAddEvents(evs);
  }
}

function tick() {
  const now = performance.now();
  demoStep(now);
  if (view) {
    const target = view.alive ? view.depth : Math.max(0, view.depth - 1);
    if (now < holdUntil) {
      // dwelling — hold the camera still so the fight reads
    } else if (camera < target - 0.001) {
      const behind = target - camera;
      // constant stride; it quickens (down to a floor) only when a real backlog has piled up.
      // MARCH ONLY: in the Gauntlet the whole answered stretch resolves instantly, so "behind" is
      // always the full sixteen — the catch-up rule read that as a backlog and sprinted the hero
      // through the field. The daily walks at the SAME anchored WALK_MS-per-tile + per-event dwells
      // as the march, every time, regardless of how much road is waiting.
      const dur = isDaily() ? WALK_MS : Math.max(180, WALK_MS - Math.max(0, behind - 2) * 70);
      if (!stepAt) { stepFrom = camera; stepAt = now; }                 // begin a fresh stretch of walking
      let next = Math.min(target, stepFrom + (now - stepAt) / dur);
      if (queue.length) {
        const stop = Math.min(popPointOf(queue[0]), target);
        if (next >= stop - 1e-9) {
          next = Math.max(camera, stop);                                // arrive AT the event, not past it
          const ev = queue.shift();
          stepFrom = next; stepAt = 0;                                  // the dwell restarts the stride
          showEvent(ev);
          if (ev.died) holdUntil = now + DEATH_SWING_MS + 900;
          // the camera holds for the WHOLE exchange: a four-swing boss fight gets four swings' worth
          else if (ev.kill) holdUntil = now + KILL_MS + (exchangeRounds - 1) * SWING_MS;
          else if (ev.dmg || ev.sting) holdUntil = now + FIGHT_MS + (exchangeRounds - 1) * SWING_MS * 0.7;
          // non-combat events do not hold: the shimmer/gust plays as he walks through
        }
      }
      camera = next;
      if (camera >= target - 1e-9) stepAt = 0;
      scene = scene.filter((x) => x.depth >= Math.floor(camera) - 3);
    } else if (queue.length) {
      // arrived with events still queued (e.g. the death on the final tile) — pop where we stand
      showEvent(queue.shift());
    } else if (camera > target + 0.35) {
      // a dead hero rests where his last swing stopped him (CONTACT past the integer target); only a
      // real overshoot beyond that snaps back
      camera = target;
    }
  }
  drawWorld();
  highlightWalkTile();
  idleMessage();
  requestAnimationFrame(tick);
}

/** The road strip tracks the WALK, live: the tile under the hero's feet burns gold, tiles already
 *  walked dim behind him. Keyed to the camera, not the settled depth — the settled depth sits at the
 *  end of the leg the whole time the animation is still walking there. */
function highlightWalkTile() {
  const el = $("road");
  if (!el) return;
  const idx = Math.floor(camera) - roadBase;
  el.querySelectorAll(".tile").forEach((n) => {
    const i = Number(n.dataset.i);
    n.classList.toggle("walk", i === idx);
    n.classList.toggle("done", i < idx);
  });
}

/** The strip under the stage ALWAYS says what is going on. An event's own line (the fight, the loot,
 *  the death) holds it for its dwell; past that it never goes stale or blank — every state has words. */
let stageMsgAt = 0;             // when an event last wrote the strip
function idleMessage() {
  const el = $("stagemsg");
  if (!el) return;
  if (stageMsgAt && performance.now() - stageMsgAt < 2600) return;   // the event's line, still fresh
  // animating a backlog: narrate the walk itself, live, at the camera's own depth
  const target2 = view ? (view.alive ? view.depth : Math.max(0, view.depth - 1)) : 0;
  if (queue.length || (view && camera < target2 - 0.01)) {
    if (demoOn) {
      el.innerHTML = `<span class="faint">${esc(t("idleDemo", "The road plays itself while you watch — set out to march for real."))}</span>`;
    } else if (isDaily()) {
      el.innerHTML = `<span class="dim">${esc(t("idleDailyPlaying", "Gauntlet · step {d}/{n} · walking it out",
        { d: Math.min(Math.floor(camera), D.STEPS), n: D.STEPS }))}</span>`;
    } else {
      el.innerHTML = `<span class="dim">${esc(t("idleMarching", "Marching · depth {d}/{c} · playing out the road",
        { d: Math.floor(camera), c: E.CHAPTER }))}</span>`;
    }
    return;
  }
  if (isDaily()) {
    const dr = arun();
    if (!dr || !(daily && daily.st.started)) {
      // the idle line tells the TRUTH about why the walk has not begun: sign in first, road still
      // pinning, or genuinely ready — "press Set out" over a greyed Set out was a taunt
      const msg = !dapp.me
        ? t("idleDailySignIn", "Sign in and set out — today's road is free to walk.")
        : !(daily && daily.st.world)
          ? t("clockDailyPinning", "Pinning today's road to the chain — a few seconds, then press "
              + "\"Set out\".")
          : t("idleDailyIdle", "The Daily Gauntlet — press Set out to walk today's road.");
      el.innerHTML = `<span class="faint">${esc(msg)}</span>`;
    } else if (daily.over()) {
      el.innerHTML = dr.alive
        ? `<span class="dim">${esc(t("idleDailyStopped", "Stopped, on your feet. Post your score below."))}</span>`
        : `<b style="color:var(--danger)">${esc(t("idleDead", "You fell here."))}</b>`
          + (fatality && fatality.cause ? ` <span class="dim">${esc(fatality.cause)}</span>` : "");
    } else {
      el.innerHTML = `<span class="dim">${esc(t("idleDailyWalk", "Gauntlet · step {d}/{n} · answer the tiles and walk",
        { d: dr.depth, n: D.STEPS }))}</span>`;
    }
    return;
  }
  // The CHAIN's own health outranks every promise below. The node halting (blocks not being made) or the
  // API dropping out doesn't stop this strip from rendering — it stops the numbers in it from ever being
  // true again: a frozen "the dice land in 3 blocks", a "confirming…" that can't confirm. The SDK already
  // measures both (dapp.online / dapp.chainStalled()); saying so is the strip's whole job.
  if (dapp.online === false) {
    el.innerHTML = `<span class="dim">${esc(t("idleOffline", "Can't reach the chain right now — reconnecting. Your march and funds are safe on-chain."))}</span>`;
    return;
  }
  const stalled = dapp.chainStalled();
  if (stalled) {
    el.innerHTML = `<span class="dim">${esc(t("idleStalled", "The chain isn't making blocks right now ({m} min and counting) — the march resumes the moment they flow again.",
      { m: Math.max(1, Math.round(stalled / 60000)) }))}</span>`;
    return;
  }
  // A clicked Set out owns the strip until ITS run is on-chain — otherwise the corpse line ("You fell
  // here") sits under a button that was just pressed, which reads as the click having done nothing.
  if (dapp.busy("begin")) {
    el.innerHTML = `<span class="dim">${esc(t("idleBeginPending", "Setting out — your new march is confirming on-chain…"))}</span>`;
    return;
  }
  if (!chain) {
    el.innerHTML = `<span class="faint">${esc(demoOn
      ? t("idleDemo", "The road plays itself while you watch — set out to march for real.")
      : t("idleNoRun", "No march yet — set out to begin."))}</span>`;
    return;
  }
  if (!chain.lh) { el.innerHTML = `<span class="dim">${esc(t("idleUnarmed", "Waiting on your orders — the march starts when you commit them."))}</span>`; return; }
  if (!chain.alive || (view && !view.alive)) {
    // Name the cause. This covers the PREVIEW window too — the client shows the death the instant the
    // dice land, while the chain still says alive until the close settles. Without this the strip read
    // "the dice are down — playing it out" over a corpse.
    el.innerHTML = `<b style="color:var(--danger)">${esc(t("idleDead", "You fell here."))}</b>`
      + (fatality && fatality.cause ? ` <span class="dim">${esc(fatality.cause)}</span>` : "");
    return;
  }
  if (chain.done) { el.innerHTML = `<b style="color:var(--win)">${esc(t("idleDone", "The road is walked. Chapter complete."))}</b>`; return; }
  if (chain.retired) { el.innerHTML = `<span class="dim">${esc(t("idleRetired", "Retired, on your feet."))}</span>`; return; }
  // "your move" — the SAME condition the road strip uses to open the tiles, INCLUDING the pipelined
  // case: the last leg already previewed, its nh still sits on the chain state, and the next sixteen
  // wait on the player. Keying on !chain.nh alone made the strip claim "the dice are down — playing
  // it out" at the exact moment nothing was owed but the player's own answers.
  if (canCommitNow()) {
    el.innerHTML = `<b style="color:var(--accent2)">${esc(t("idleYourMove", "Your move — answer the sixteen tiles below and commit them."))}</b>`;
    return;
  }
  // it IS your move, but the terrain block's hash hasn't rendered the tiles yet — never say "your move"
  // (the button is greyed until there are tiles) or "sending your answers" (nothing was sent) here
  if (canAnswer() && !road.length) {
    el.innerHTML = `<span class="dim">${esc(t("roadEmptyWaiting", "Waiting for the terrain block… a few seconds."))}</span>`;
    return;
  }
  if (!chain.nh || queuedWord) {                 // answers in flight (or queued behind the leg's close)
    el.innerHTML = `<span class="dim">${esc(t("idleCommitting", "Sending your answers — the dice get scheduled the moment they land."))}</span>`;
    return;
  }
  const left = dapp.cursor != null ? chain.nh - dapp.cursor : null;
  el.innerHTML = left == null
    ? `<span class="dim">${esc(t("idleWaitingDice", "Marching · depth {d}/{c} · waiting on the dice block",
        { d: chain.depth, c: E.CHAPTER }))}</span>`
    : left > 0
    ? `<span class="dim">${esc(left === 1
        ? t("idleWaitingOne", "Marching · depth {d}/{c} · the dice land next block", { d: chain.depth, c: E.CHAPTER })
        : t("idleWaiting2", "Marching · depth {d}/{c} · the dice land in {n} blocks",
            { d: chain.depth, c: E.CHAPTER, n: left }))}</span>`
    : `<b style="color:var(--accent2)">${esc(t("idleReady2", "The dice are down — playing it out."))}</b>`;
}

/** What to call the thing that killed you — the art file's own family names, so the words on the stage and
 *  the sprite standing over the body are talking about the same creature. */
/** "each hit ≈ N hp" — module-level ON PURPOSE: renderRoad's map callback names its tile `t`, which
 *  shadows the translator; calling t("tileSwing") in there was a live "t is not a function". */
const swingLabel = (s) => " · " + t("tileSwing", "each hit ≈ {s} hp before armour", { s });
const tileName = (i) => t("tile_" + i, (TILE_INFO[i] || ["?"])[0]);

/** The creature's PROPER NAME — "barghest", not "monster". Species is (biome, family, rank); the i18n
 *  key is derived from the English name so translators can (optionally) localize the bestiary, and the
 *  English name is always the fallback. */
function speciesLabel(tile, fam, biome, forHorde = false) {
  if (tile === E.MIMIC) return t("sp_mimic", "mimic");
  if (!ART.speciesOf) return E.TILE_NAMES[tile];
  const rank = tile === E.BOSS ? 2 : tile === E.ELITE ? 1 : 0;
  const s = ART.speciesOf(biome | 0, fam | 0, rank);
  const nm = t("sp_" + s.name.replace(/[^a-z0-9]+/g, "_"), s.name);
  return forHorde && tile === E.HORDE ? t("packOf", "pack of {who}s", { who: nm }) : nm;
}
const COMBAT_TILES = () => [E.MONSTER, E.HORDE, E.ELITE, E.AMBUSH, E.MIMIC, E.BOSS];

function killerName(ev) {
  // name the SPECIES that did it, not the stat family: "a level 9 knucker" beats "a level 9 brute"
  if (ev.tile === E.MIMIC) return "mimic";
  if (ART.speciesOf) {
    const rank = ev.tile === E.BOSS ? 2 : ev.tile === E.ELITE ? 1 : 0;
    const s = ART.speciesOf(ev.biome | 0, ev.fam | 0, rank);
    return ev.tile === E.HORDE ? "pack of " + s.name + "s" : ev.tile === E.AMBUSH ? "lurking " + s.name : s.name;
  }
  const fam = (ART.FAMILY_NAMES || ["grunt", "brute", "cannon"])[ev.fam | 0] || "monster";
  return ev.tile === E.BOSS ? "boss " + fam : ev.tile === E.ELITE ? "elite " + fam
    : ev.tile === E.HORDE ? "pack of " + fam + "s" : ev.tile === E.AMBUSH ? "lurking " + fam : fam;
}

function showEvent(ev) {
  // the HUD ticks WITH the walk: each event carries the run's stats as of that step, and this is the
  // moment the player watches the step happen — so this is the moment the numbers change
  if (ev.hp != null) {
    animHud = { hp: ev.hp, maxhp: ev.maxhp, stam: ev.stam, potions: ev.pots,
                xp: ev.xp2, banked: ev.bank2, streak: ev.strk, gale: ev.gale2, depth: ev.dp2 };
    const base = view || arun();
    if (base) renderHud(Object.assign({}, base, animHud));
  }
  // spawn the blood this step earned, anchored where it happened. COMBAT gore lands where the MONSTER
  // stands — half a tile past the tile start — not at the tile boundary; anchoring it at the boundary put
  // every kill's blood behind the hero's back ("enemies die BEHIND the hero").
  const isCombatEv = ev.tile === E.MONSTER || ev.tile === E.HORDE || ev.tile === E.ELITE
    || ev.tile === E.AMBUSH || ev.tile === E.BOSS;
  // Where this event's effects live in the world. Everything on a tile STANDS at depth+0.5 (monster,
  // prop, and the hero himself when a non-combat event pops) — except a death, whose corpse must land
  // exactly where the camera stopped: at sword-contact, CONTACT short of the thing that killed him.
  const at = (ev.depth != null ? ev.depth : Math.floor(camera)) + (ev.died ? CONTACT : 0.5);
  const seed = goreSeed(Math.floor(at));
  // stage the fight on the creature itself: it fights BACK for the length of the swing, then — if this
  // event killed it — it dies exactly when the swing lands, in FRONT of the hero, and he walks past a
  // corpse. Before this the death frame was keyed on "hero already walked past", which is the wrong order.
  if (isCombatEv) {
    // THE EXCHANGE: a fight is swings TRADED, not one tap. Bosses take four blows to fell, elites and
    // mimics three, a fight that actually hurt you two, chaff one — the rules resolve in a single step,
    // but the picture owes the fight its length. Everything downstream (hero swing loop, monster
    // wind-up/strike alternation, flinches, per-blow blood, camera hold) keys off `rounds`.
    const rounds = ev.tile === E.BOSS ? 4
      : (ev.tile === E.ELITE || ev.tile === E.MIMIC) ? 3
      : ev.tile === E.HORDE ? Math.min(4, 1 + Math.ceil((ev.foes || 1) / 5))
      : ev.dmg ? 2 : 1;
    attackT0 = performance.now();
    attackRounds = rounds;
    exchangeRounds = rounds;
    const sc = scene.find((x) => x.depth === ev.depth);
    if (sc) {
      sc.fightAt = performance.now();
      sc.rounds = rounds;
      if (ev.kill && !ev.died) sc.deadAt = performance.now() + rounds * SWING_MS - 120;  // dies to the LAST blow
      if (ev.died) sc.wonFight = true;               // it killed the hero: it never dies, it stands over him
    }
    audio.sfx("snarl");                              // the creature answers the challenge as it winds up
    // the monster's OWN blow lands mid-round (the hero's flinch): give it the grunt it earns
    if (ev.dmg && !ev.died) setTimeout(() => audio.sfx("hurt"), SWING_MS * 0.6);
    for (let k2 = 1; k2 < rounds; k2++) {            // each later blow lands its own blood and its own sound
      addGore(at, "hit", Math.min(9, 2 + Math.floor((ev.dmg || 4) / 5)), seed ^ (k2 * 0x515), k2 * SWING_MS);
      setTimeout(() => {
        const last = k2 === rounds - 1 && ev.kill;
        audio.sfx(last ? "kill" : "hit");
        if (last) { shakeT0 = performance.now(); shakeAmp = 5; }   // the screen jolts WITH the killing blow
      }, k2 * SWING_MS);
    }
  }
  const foes = ev.foes || 1;
  // sound mirrors the picture: the swing/impact, the kill stab, the heal shimmer, the flinch
  if (ev.act === E.A_STRIKE || ev.act === E.A_RIGHT) audio.sfx("swing");
  else if (ev.act === E.A_GUARD) audio.sfx("guard");
  else if (ev.act === E.A_DODGE) audio.sfx("dodge");
  else if (ev.act === E.A_POTION || ev.drank || ev.auto) audio.sfx("heal");
  else if (ev.act === E.A_RALLY) audio.sfx("rally");
  if (ev.sting) audio.sfx("hurt");                       // the ambush lands BEFORE the fight
  if (ev.gale) audio.sfx("dodge");                       // the storm arms: a whoosh is the closest thing to wind
  if (ev.lash || ev.curse || ev.quag || ev.snare) audio.sfx("hurt");
  if (ev.well || ev.bottled) audio.sfx("heal");
  if (ev.pyre) audio.sfx("rally");                       // the beacon catches: a bright note
  if (ev.mined || ev.sprung) audio.sfx("guard");         // iron on iron
  // the QUIET tiles get their voices too — a silent chest made half the road feel like dead UI.
  // Loot waits for the body when it came off a kill; everything else chimes as it happens.
  const lootIsh = ev.item || ev.drops
    || (ev.gain && [E.CACHE, E.RELIC, E.BARROW, E.ARMORY].includes(ev.tile));
  if (lootIsh) setTimeout(() => audio.sfx("loot"), ev.kill ? exchangeRounds * SWING_MS + 250 : 0);
  if (ev.toll) audio.sfx("coin");                        // the chain takes its cut
  if (ev.tile === E.IDOL && ev.gain && !lootIsh) audio.sfx("coin");   // robbed or offered: renown moves
  if (ev.rest || (ev.heal && !ev.drank && !ev.auto && !ev.well && !ev.bottled)) audio.sfx("heal");
  if (ev.craft || ev.bought) audio.sfx("guard");         // the forge rings like iron because it is
  if (ev.banked || ev.chapter)                           // the milestone fanfare, after any kill plays out
    setTimeout(() => audio.sfx("bank"), ev.kill ? exchangeRounds * SWING_MS + 400 : 0);
  // the death scream belongs to the KILLING blow. A one-round fight kills instantly; a longer
  // exchange opens with an ordinary hit — its last scheduled round (above) carries the scream and
  // the screen jolt. It used to scream at round one AND round last, dying twice per boss.
  if (ev.kill && exchangeRounds === 1) { audio.sfx("kill"); shakeT0 = performance.now(); shakeAmp = 5; }
  else if (ev.kill || (ev.dmg && !ev.died)) audio.sfx("hit");
  if (ev.died) { audio.sfx("death"); shakeT0 = performance.now(); shakeAmp = 9; }
  if (ev.dmg) {
    // a landed blow: spray scaled to how hard it hit, plus a chunk torn loose on the heavy ones
    addGore(at, "hit", Math.min(12, 2 + Math.floor(ev.dmg / 4)), seed);
    if (ev.dmg >= 12) addGore(at, "gib", Math.min(6, 1 + Math.floor(ev.dmg / 12)), seed ^ 0x1234);
    if (ev.dmg >= 8) addGore(at, "mist", Math.min(8, foes + 1), seed ^ 0x77aa);
  }
  if (ev.kill) {
    // a KILL empties the body: arterial jet, a bloom of mist, chunks of meat, a spreading pool, and dried
    // splatter left on the road you fought over. Volume rides the pull — a 16-foe horde paints the tile.
    addGore(at, "spurt", Math.min(16, foes * 2 + 2), seed ^ 0x9e37);
    addGore(at, "gib", Math.min(16, foes * 2 + 2), seed ^ 0xb17e);
    addGore(at, "mist", Math.min(16, foes * 3), seed ^ 0x3c1d);
    addGore(at, "pool", Math.min(16, foes * 2 + 4), seed ^ 0x51ed);
    addGore(at, "splatter", Math.min(16, foes * 2 + 3), seed ^ 0x2f6d);
  }
  // the action you chose plays on this tile, whatever it was (guard spark, dodge blur, potion, rally…)
  if (ev.act) { actFx = { act: ev.act, t0: performance.now(), depth: at, drank: ev.drank || ev.auto }; }
  // a blow that landed but did NOT kill: the hero flinches (shake + red flash)
  if ((ev.dmg || ev.sting) && !ev.died) hitFlash = { t0: performance.now() };
  if (ev.died) {
    // WHAT KILLED HIM, kept past the event that carried it. There are exactly two ways step() can take the
    // last of your hp: a fight, and a HAZARD. `fam`/`ml` only exist on a fight, so a scene with no monster in
    // it is not a missing sprite — it is a death nobody was standing over, and it draws the pit instead.
    const combat = ev.tile === E.MONSTER || ev.tile === E.HORDE || ev.tile === E.ELITE
      || ev.tile === E.AMBUSH || ev.tile === E.MIMIC || ev.tile === E.BOSS;
    const nfat = (ART.FATALITIES || []).length;
    // the tiles that can kill WITHOUT a body standing over you: each draws its own prop as the cause
    const DEATH_PROP = { [E.HAZARD]: "hazard", [E.SNARE]: "snare", [E.QUAG]: "quag",
                         [E.TOLLGATE]: "tollgate", [E.BARROW]: "barrow" };
    hitFlash = null;                                     // the death supersedes any pending flinch
    fatality = {
      which: nfat ? seed % nfat : 0,          // deterministic: the same death always replays the same way
      // t0 is when the FATALITY starts — one swing from now, so the hero's last blow plays first
      t0: performance.now() + DEATH_SWING_MS, swingStart: performance.now(), depth: at,
      killer: combat ? { family: ev.fam | 0, level: ev.ml || 1, biome: ev.biome | 0,
                         mimic: ev.tile === E.MIMIC,
                         rank: ev.tile === E.BOSS ? 2 : ev.tile === E.ELITE ? 1 : 0 } : null,
      prop: !combat ? DEATH_PROP[ev.tile] || null : null,
      // the stage line is rewritten every frame by idleMessage() once the queue drains, so the cause has to
      // live on the scene rather than in the bits below or it is gone a frame after it is written
      cause: combat ? t("deathBy", "A level {l} {who} is standing over your body.",
                        { l: ev.ml || 1, who: killerName(ev) })
        : DEATH_PROP[ev.tile] ? t("deathHazard",
            "The hazard on this tile finished you — there was nobody here to fight.")
        : null,
    };
    addGore(at, "spurt", 16, seed ^ 0xfa7a);
    addGore(at, "gib", 16, seed ^ 0x6ead);
    addGore(at, "mist", 16, seed ^ 0x4c1d);
    addGore(at, "pool", 16, seed ^ 0xdead);
    addGore(at, "splatter", 16, seed ^ 0x2f6d);
  }
  const bits = [];
  // the fight names its creature — "knucker ×3 · lvl 7", never an anonymous exchange
  if (ev.foes && COMBAT_TILES().includes(ev.tile)) {
    bits.push(`<b>${esc(speciesLabel(ev.tile, ev.fam, ev.biome, false))}</b>` +
      (ev.foes > 1 ? ` ×${ev.foes}` : "") + (ev.ml ? ` · lvl ${ev.ml}` : ""));
  }
  if (ev.gain) bits.push(`<span style="color:var(--gold)">+${ev.gain} renown</span>`);
  if (ev.dmg) bits.push(`<span style="color:var(--danger)">−${ev.dmg} hp</span>`);
  if (ev.drain) bits.push(`<span style="color:var(--win)">+${ev.drain} drained</span>`);
  if (ev.item) {
    const it = unpackItem(ev.item);
    bits.push(`<span style="color:var(--accent2)">${MAT_NAMES[it.mat]} ${slotLabel(ev.slot, it).toLowerCase()} T${it.tier}` +
      (it.affix ? ` <b class="aff">${E.AFFIX_NAMES[it.affix]}</b>` : "") + "</span>");
  }
  if (ev.sting) bits.push(`<span style="color:var(--danger)">${t("evSting", "ambushed! −{n} hp through armour", { n: ev.sting })}</span>`);
  if (ev.gale) bits.push(`<span style="color:var(--accent2)">${t("evGale", "the gale rides with you — 3 steps of +25% renown and +25% damage")}</span>`);
  if (ev.offered) bits.push(`<span style="color:var(--gold)">${t("evOffered", "potion offered to the idol — triple renown")}</span>`);
  if (ev.lash) bits.push(`<span style="color:var(--danger)">${t("evLash", "the reeve's lash — −{n} hp for dashing the chain", { n: ev.lash })}</span>`);
  if (ev.toll) bits.push(`<span style="color:var(--danger)">${t("evToll", "toll paid — −{n} renown", { n: ev.toll })}</span>`);
  if (ev.curse) bits.push(`<span style="color:var(--danger)">${t("evCurse", "the grave-curse — −{n} hp through armour", { n: ev.curse })}</span>`);
  if (ev.sprung) bits.push(`<span style="color:var(--accent2)">${t("evSprung", "snare sprung on the shield — +1 scrap")}</span>`);
  if (ev.snare) bits.push(`<span style="color:var(--danger)">${t("evSnare", "snared! −3 stamina")}</span>`);
  if (ev.quag) bits.push(`<span style="color:var(--danger)">${t("evQuag", "the bog drags — −{n} hp and −2 stamina", { n: ev.quag })}</span>`);
  if (ev.mined) bits.push(`<span style="color:var(--gold)">${t("evMined", "the vein pays — +{n} scrap", { n: ev.mined })}</span>`);
  if (ev.commune) bits.push(`<span style="color:var(--accent2)">${t("evCommune", "the grove answers — +{n} essence", { n: ev.commune })}</span>`);
  if (ev.well) bits.push(`<span style="color:var(--accent2)">${t("evWell", "drank deep — stamina refilled")}</span>`);
  if (ev.bottled) bits.push(`<span style="color:var(--gold)">${t("evBottled", "spring bottled — +1 potion, streak kept")}</span>`);
  if (ev.camp) bits.push(`<span style="color:var(--accent2)">${t("evCamp", "a free rest by the cold fire")}</span>`);
  if (ev.pyre) bits.push(`<span style="color:var(--gold)">${t("evPyre", "the beacon burns — 3 steps of +25% renown")}</span>`);
  if (ev.banked) bits.push(`<b style="color:var(--win)">checkpoint — ${ev.banked} banked</b>`);
  if (ev.easy) bits.push('<span class="faint">easy win, no healing</span>');
  if (ev.auto) bits.push('<span class="faint">auto-drank</span>');
  if (ev.craft) bits.push(`<span class="faint">forged ${ev.craft === 1 ? "weapon" : "armour"} +1</span>`);
  if (ev.died) bits.push('<b style="color:var(--danger)">you fell</b>');
  if (ev.chapter) bits.push('<b style="color:var(--win)">the road ends — chapter complete</b>');
  const el = $("stagemsg");
  if (el) {
    el.innerHTML = `${TILE_ICON[ev.tile]} ${bits.join(" · ") || '<span class="faint">quiet road</span>'}`;
    stageMsgAt = performance.now();          // the event's line holds the strip through its dwell
  }
}

// ── rendering the panels ────────────────────────────────────────────────────────────────────────
let animHud = null;   // stat overrides as of the last ANIMATED step — the HUD follows the fight
/** The HUD numbers and bars, from whatever run-shaped object is currently the truth on screen. */
function renderHud(r) {
  $("hpTxt").textContent = `${r.hp} / ${r.maxhp}`;
  $("hpBar").style.width = Math.max(0, Math.min(100, (r.hp * 100) / r.maxhp)) + "%";
  $("stamTxt").textContent = `${r.stam} / ${E.STAM_MAX}`;
  $("stamBar").style.width = ((r.stam * 100) / E.STAM_MAX) + "%";
  $("xpTxt").textContent = E.score(r).toLocaleString();
  $("streakTxt").textContent = (r.streak > 0 ? `×${((E.STREAK_DIV + r.streak) / E.STREAK_DIV).toFixed(2)} streak` : "")
    + (r.gale > 0 ? `${r.streak > 0 ? " · " : ""}🌪️ ${r.gale}` : "");
  // potions are a COUNTED resource — you start with a few and find more at wells and camps. The
  // count was invisible ("not quite obvious if you have infinite potions or if you collect them"),
  // so the flask sits in the HUD with its number, and goes red when the satchel is empty.
  if ($("potTxt")) {
    $("potTxt").textContent = `🧪 ${r.potions}`;
    $("potTxt").style.color = r.potions ? "" : "var(--danger)";
  }
  $("depthTxt").textContent = `${r.depth} / ${isDaily() ? D.STEPS : E.CHAPTER}`;
  $("rankTxt").textContent = E.rankOf(E.score(r));
  $("bankedTxt").textContent = r.banked.toLocaleString();
  $("riskTxt").textContent = E.csub(r.xp, r.banked).toLocaleString();
}

function render() {
  renderWallet(dapp);
  const r = view || arun();

  // HUD — only once a run exists in THIS mode. Before that the hp/stam bars over the stage read as a run
  // already in progress ("i'm seeing the field with health and stamina even before the game starts").
  const hasRun = isDaily() ? !!(daily && daily.st.started && r) : !!(chain && r);
  gate({ hud: hasRun });
  // While a leg is ANIMATING, the HUD shows the stats as of the last step the player has actually
  // watched (animHud, set per event) — not the leg's settled end state. Health used to sit frozen
  // at the final number through every fight on the way there.
  const animating = !!animHud && (queue.length > 0
    || (view && camera < (view.alive ? view.depth : view.depth - 1) - 0.01));
  if (r && hasRun) renderHud(animating ? Object.assign({}, r, animHud) : r);

  // gate() takes a MAP of {elementId: shouldBeVisible} and toggles the `hidden` class — it is not an
  // enable/disable helper. Calling it per-element did nothing at all, which is why every button stayed
  // clickable and a signed-out tap on "Set out" silently went nowhere.
  if (isDaily()) {
    // the run card serves the Gauntlet with the SAME buttons meaning the same things: "Set out" starts
    // today's walk, retire is the cash-out, and settle does not exist because nothing here waits on a
    // block. The only transaction this mode ever sends is the end-of-run proof-of-moves post.
    const dr = arun();
    const walking = dailyAnswering();
    const started = !!(daily && daily.st.started);
    const overD = !!(daily && daily.over());
    const canStop = walking && !!(dr && dr.depth);
    // Every run-card button stays VISIBLE in both modes: a button that vanishes reads as a broken
    // page ("why does the set out button exist but is hidden??????"), a greyed one explains itself.
    // March-only actions sit disabled here with the reason in their tooltip.
    for (const id of ["beginBtn", "retireBtn", "stopBankBtn"])
      if ($(id)) $(id).classList.remove("hidden");
    // planBtn is NOT part of the flow anymore (orders ride the commit); it exists only as the
    // march's legacy-rescue "Begin the march", so in the Gauntlet it simply is not there
    $("planBtn").classList.add("hidden");
    $("retireBtn").textContent = t("retire", "Retire");
    $("retireBtn").disabled = true;
    $("retireBtn").title = t("btnMarchOnly", "The March only — switch modes above");
    $("retireBtn").classList.remove("pulse");
    // signed-out stays CLICKABLE (the click raises the sign-in bar); it only greys while today's
    // road is actually being pinned, or once the walk is running / done
    $("beginBtn").disabled = !daily || started || overD || (!!dapp.me && !daily.st.world);
    $("beginBtn").title = "";
    $("beginBtn").classList.toggle("pulse", !started && !overD && !!(daily && daily.st.world));
    if ($("stopBankBtn")) {
      $("stopBankBtn").textContent = t("stopBank", "Stop & bank it");
      $("stopBankBtn").disabled = !canStop;
      $("stopBankBtn").title = "";
    }
    $("clockHint").innerHTML = !daily || !daily.st.started
      ? esc(!daily || !daily.st.world
          ? t("clockDailyPinning", "Pinning today's road to the chain — a few seconds, then press "
              + "\"Set out\".")
          : t("clockDailyIdle", "Press \"Set out\" to walk today's road — free, no clock, and nothing "
              + "goes on-chain until you post your score at the end."))
      : daily.over()
        ? esc(t("clockDailyDone", "Today's run is finished. Post it to the board, or replay for practice."))
        : esc(t("clockDailyWalk", "Answer the tiles below and walk. Every step forward raises what "
                + "stopping is worth; dying forfeits the road bonus."));
    renderRoad(); renderAnswerBar(); renderDials(); renderGear(arun() || E.newRun()); renderBoard();
    renderMode();
    return;
  }
  const live = !!(chain && chain.alive && !chain.done && !chain.retired);
  // begin() arms on-chain now, so `armed` is only ever false for a run begun under the OLD contract —
  // three real players are stuck in exactly that state, and for them the plan call is the rescue that arms.
  const armed = !!(chain && chain.lh);
  const rolling = !!(chain && chain.nh);         // dice scheduled: the leg is in flight (used by the clock)
  // There is no manual settle. The client previews the leg the instant the dice land and files the close
  // itself through the SDK's auto-collect, which retries on every refresh — a button was pure noise.
  // The death is previewed locally the instant the dice land — the CHAIN still says alive until the
  // auto-collect settles the close. begin() claims a FRESH run id and never asks about the corpse, so
  // "Set out" must open the moment the player watches himself fall, not a settlement later.
  const deadLocal = !!(view && !view.alive);
  // Every run-card button stays VISIBLE: it greys out with a reason instead of vanishing.
  for (const id of ["beginBtn", "planBtn", "retireBtn", "stopBankBtn"])
    if ($(id)) $(id).classList.remove("hidden");
  if ($("stopBankBtn")) {
    $("stopBankBtn").textContent = t("stopBank", "Stop & bank it");
    $("stopBankBtn").disabled = true;
    $("stopBankBtn").title = t("btnDailyOnly", "Daily Gauntlet only — switch modes above");
  }
  $("retireBtn").textContent = t("retire", "Retire");
  // ONE button commits decisions AND battle orders ("why are there two buttons?") — planBtn survives
  // solely as the legacy rescue: a pre-upgrade run that was begun but never armed needs one plan()
  // call to arm, and its road does not even exist until then.
  const legacyRescue = live && !deadLocal && !armed;
  $("planBtn").classList.toggle("hidden", !legacyRescue);
  $("planBtn").textContent = t("beginMarch", "Begin the march");
  $("planBtn").classList.toggle("pulse", legacyRescue && !dapp.busy("plan"));
  $("planBtn").disabled = !legacyRescue || dapp.busy("plan");
  $("planBtn").title = "";
  // "Set out" stays clickable while signed out ON PURPOSE: the click routes through canPay(), which raises
  // the SDK's sign-in bar. Hiding it would leave a signed-out visitor staring at a page with no way in.
  const beginBusy = dapp.busy("begin");
  $("beginBtn").disabled = beginBusy || (live && !deadLocal);
  // the SDK's ⏳ label while the click is in flight — a greyed "Set out" alone reads as "still an option
  // that happens to be stuck", not "already done, confirming"
  $("beginBtn").textContent = beginBusy ? confirmingLabel() : t("begin", "Set out");
  $("beginBtn").title = live && !deadLocal ? t("btnRunLive", "A march is already under way") : "";
  $("beginBtn").classList.toggle("pulse", deadLocal && !beginBusy);
  $("retireBtn").disabled = !live || deadLocal || !chain.depth || dapp.busy("retire");
  $("retireBtn").title = live ? "" : t("btnNoRun", "No march under way — press Set out");

  // the clock: what the march is waiting on, in every state it can be in
  if (beginBusy) {
    // never tell a player to press the button they just pressed
    $("clockHint").innerHTML = t("idleBeginPending", "Setting out — your new march is confirming on-chain…");
  } else if (chain && live && deadLocal) {
    $("clockHint").innerHTML = t("clockDeadLocal",
      "You fell. The settlement files itself in the background — press \"Set out\" to march again "
      + "right now.");
  } else if (chain && live && !armed) {
    $("clockHint").innerHTML = t("clockLegacy",
      "This run was set out under the old rules and never started. Press \"Begin the march\" below — "
      + "your road appears a few seconds later.");
  } else if (chain && live && !rolling) {
    $("clockHint").innerHTML = t("clockYourMove",
      "The march is holding for you. Answer the sixteen tiles below and commit — the dice are not even "
      + "scheduled until you do.");
  } else if (chain && live && dapp.cursor != null) {
    const left = chain.nh - dapp.cursor;
    $("clockHint").innerHTML = left > 0
      ? t("clockWait", "The dice land in {n} blocks (~{time}). Your answers are locked in.",
          { n: left, time: blocksToTime(left, BLOCK_SECS) })
      : t("clockAuto", "The dice are down — playing it out now; the settlement files itself.");
  } else if (chain && !live) {
    $("clockHint").innerHTML = chain.done
      ? t("clockDone", "Chapter complete. The road bonus is yours in full.")
      : chain.retired ? t("clockRetired", "Retired on your feet — you kept everything you were carrying.")
      : t("clockDead", "You fell. Only a quarter of the unbanked renown made it home.");
  } else {
    $("clockHint").textContent = "";
  }

  if (chain && !dialsTouched) {
    $("agg").value = String(chain.agg || 1);
    planAgg = chain.agg || 1;
    $("aggVal").textContent = planAgg;
    pendStance = chain.stance; pendFocus = chain.focus; pendHeal = chain.healpct;
    $("focus").value = String(pendFocus); $("focusVal").textContent = `${pendFocus} / ${100 - pendFocus}`;
    $("heal").value = String(pendHeal); $("healVal").textContent = pendHeal + "%";
  }
  renderRoad();
  renderAnswerBar();
  renderDials();
  renderGear(r);
  renderBoard();
  renderMode();
}

// ── the two modes ───────────────────────────────────────────────────────────────────────────────
// MARCH is the staked run the chain paces; GAUNTLET is the free daily. They share the stage, the art, the
// engine and the action matrix — the only differences are where the world comes from and what "one step"
// costs you. Everything below is the SDK's shared mode bar plus a gate() over the cards each mode owns, so
// switching cannot leave a panel from the other mode on screen (the bug that made twelve other games show
// an empty board when this decision was made per-game).
// The play surfaces — stage, road strip, run card, gear card — are SHARED between the modes, because the
// Gauntlet IS the march at your own pace and shipping it as a separate emoji panel was a mistake a player
// called out on sight ("why is daily gauntlet completely different from the march?"). Only the config and
// board cards differ: the march has the dials card and the staked board, the Gauntlet has its day card
// (pitch/loadout/score/post) and the verified daily board.
const MARCH_CARDS = ["runcard", "roadcard", "dialscard", "gearcard", "marchBoardWrap"];
const DAILY_CARDS = ["dailyWrap", "runcard", "roadcard", "dialscard", "gearcard", "dailyBoardWrap"];
const isDaily = () => mode === "daily";
/** The run the page is ABOUT in the current mode — the Gauntlet's local run or the chain's. */
const arun = () => (isDaily() ? (daily && daily.st.run) || null : chain);
const dailyAnswering = () => isDaily() && !!(daily && daily.st.started && daily.st.world && !daily.over());

function renderMode() {
  const g = {};
  for (const id of new Set([...MARCH_CARDS, ...DAILY_CARDS])) {
    g[id] = (mode === "march" ? MARCH_CARDS : DAILY_CARDS).includes(id);
  }
  gate(g);
  if (mode === "daily" && daily) {
    daily.renderCard($("dailyCard"));
    daily.renderBoard($("dailyBoard"), sto);
  }
}

function setMode(m) {
  if (m === mode) return;
  mode = m;
  try { localStorage.setItem("nado_autogame_mode", m); } catch (e) {}
  // Each mode animates a different run on the same canvas, so the animator is reset rather than left to
  // interpolate between two unrelated depths — which reads as the hero teleporting.
  view = null; queue = []; camera = 0; road = []; roadBase = 0; gore = []; fatality = null; scene = []; actFx = null; hitFlash = null;
  buildModeBar();
  if (mode === "daily") syncDailyView(true);
  else if (chain) { syncView(); rebuildRoad(); }
  render();
}

function buildModeBar() {
  modeBar($("modes"), [
    { key: "march", icon: "⚔️", label: t("tabMarch", "The march"),
      hint: t("tabMarchHint", "Your staked run, one leg per sixteen blocks, for as long as you keep walking.") },
    { key: "daily", icon: "🏆", label: t("tabDaily", "Daily Gauntlet"), badge: (window.t ? window.t("sdk.free", "free") : "free"),
      hint: t("tabDailyHint", "Today's free 124-step road. Post your score; the faucet pays the top of it.") },
  ], mode, setMode);
}

/** Point the animator at the Gauntlet run. `snap` adopts the current depth outright, which is what a run
 *  resumed from localStorage needs — otherwise the camera would re-walk sixty steps it has no events for. */
function syncDailyView(snap) {
  const r = daily && daily.st.run;
  if (!r) {
    view = null;
    // The road is COMMITTED before the walk starts — so SHOW it. An empty field before "Set out"
    // read as a broken page; now the hero stands at the trailhead with today's actual first
    // sixteen tiles waiting on the ground ahead of him.
    road = daily && daily.st.world ? D.roadAhead(daily.st.world, E.newRun({}), 0, E.LEG) : [];
    roadBase = 0;
    if (snap) { camera = 0; queue = []; }
    return;
  }
  view = { ...r, gear: [...r.gear], mats: [...r.mats] };
  road = daily.st.world ? D.roadAhead(daily.st.world, r, r.depth, E.LEG) : [];
  roadBase = r.depth;
  if (snap) { camera = r.alive ? r.depth : Math.max(0, r.depth - 1); queue = []; }
}

/** One Gauntlet step happened (or the panel changed). A new event is handed to the SAME animation queue the
 *  settled march uses, so a free run looks exactly like a staked one — including the death scene. */
function onDailyChange(ev) {
  if (ev) { const evs = Array.isArray(ev) ? ev : [ev]; queue.push(...evs); sceneAddEvents(evs); }
  syncDailyView(!ev && !view);
  render();
}

function renderRoad() {
  const el = $("road");
  if (!el) return;
  const r = arun();
  if (!r || !road.length) {
    el.innerHTML = `<div class="faint" style="grid-column:1/-1;padding:14px 0">${
      isDaily() ? esc(t("roadEmptyDaily2", "Set your build in the Battle orders card, then press "
                          + "\"Set out\" — today's sixteen tiles appear right here."))
      : !chain ? esc(t("roadEmptyNoRun", "Set out to see the road."))
      : !chain.lh ? esc(t("roadEmptyLegacy", "No road yet — press \"Begin the march\" below to wake this run."))
      : esc(t("roadEmptyWaiting", "Waiting for the terrain block… a few seconds."))}</div>`;
    return;
  }
  const answering = isDaily() ? dailyAnswering() : canCommitNow();
  el.classList.toggle("answering", answering);
  el.innerHTML = road.map((t, i) => {
    const cls = [[E.HAZARD, E.HORDE, E.ELITE, E.AMBUSH, E.MIMIC, E.SNARE, E.QUAG, E.TOLLGATE,
                  E.BARROW, E.GALE, E.BOSS].includes(t.tile) ? "danger"
      : [E.CACHE, E.SHRINE, E.IDOL, E.RELIC, E.WELL, E.CAMP, E.ARMORY, E.VEIN, E.GROVE, E.PYRE].includes(t.tile) ? "good" : "",
      t.depth === (r ? r.depth : -1) ? "now" : ""].join(" ");
    // your answer, worn on the tile. Blank = A_DEFAULT (walk in, fight plainly) — an action in its own
    // right, so nothing is ever "unset"; it is just the plainest choice.
    const mine = answers[i];
    const act = mine ? `<span class="act">${chipIcon(mine, t.tile)}</span>` : "";
    // A canvas, not an emoji. The chip background is a dark blue-grey, and a stock ⚔️ glyph sitting in it
    // reads as clip-art in a blue box rather than as the monster you are about to fight.
    const art = ART.drawMonster
      ? `<canvas class="tico" width="${ART.MON_W || 32}" height="${Math.round((ART.MON_H || 32) * 1.5)}" data-i="${i}"></canvas>`
      : `<span>${TILE_ICON[t.tile]}</span>`;
    // the hover title carries the creature's PROPER NAME — "barghest · lvl 4 · swing 9", never "monster"
    const label = COMBAT_TILES().includes(t.tile)
      ? `${speciesLabel(t.tile, t.fam, t.biome, true)}${t.ml ? " · lvl " + t.ml : ""}`
      : tileName(t.tile);
    // "swing" was pure jargon on the surface — the number is WHAT ONE HIT COSTS, so say that
    const swingBit = t.swing ? swingLabel(t.swing) : "";
    return `<div class="tile ${cls}" data-i="${i}" title="${esc(label + swingBit)}">
      ${act}${art}<span class="sw">${t.swing ? "⚔" + t.swing : ""}</span></div>`;
  }).join("");
  paintRoadIcons();
  if (answering) {
    el.querySelectorAll(".tile").forEach((n) => n.onclick = () => {
      const i = Number(n.dataset.i);
      selTile = i;                                          // every tap explains the tile it touched
      const b = BRUSHES[brush] || BRUSHES[0];
      const allowed = ACTS_FOR[road[i].tile] || [0];
      const fits = allowed.includes(b.a)
        && (b.onlyTile == null || road[i].tile === b.onlyTile)
        && (b.notTile == null || road[i].tile !== b.notTile);
      if (!fits) {                                          // this tile cannot use that action — SAY so
        n.classList.remove("deny"); void n.offsetWidth; n.classList.add("deny");
        renderAnswerBar();                                  // …and still tell its story below
        return;
      }
      answers[i] = answers[i] === b.a ? 0 : b.a;            // same action again = take it back off
      renderRoad();
      renderAnswerBar();
    });
  } else {
    el.querySelectorAll(".tile").forEach((n) => n.onclick = () => {
      selTile = Number(n.dataset.i); renderAnswerBar();
    });
  }
}

/** Paint each road chip with the SAME sprite the world uses, so the strip and the stage agree about what
 *  is standing on that tile. */
function paintRoadIcons() {
  if (!ART.drawMonster) return;
  const RANK = { [E.ELITE]: 1, [E.BOSS]: 2 };
  const PROP = { [E.HAZARD]: "hazard", [E.SNARE]: "snare", [E.QUAG]: "quag", [E.GALE]: "gale",
                 [E.TOLLGATE]: "tollgate", [E.CACHE]: "cache", [E.BARROW]: "barrow",
                 [E.ARMORY]: "armory", [E.VEIN]: "vein", [E.GROVE]: "grove", [E.SHRINE]: "shrine",
                 [E.WELL]: "well", [E.CAMP]: "camp", [E.IDOL]: "idol", [E.PYRE]: "pyre",
                 [E.FORGE]: "forge", [E.FORK]: "fork", [E.RELIC]: "relic" };
  document.querySelectorAll("#road .tico").forEach((cv) => {
    const t = road[Number(cv.dataset.i)];
    if (!t) return;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.imageSmoothingEnabled = false;
    if (t.tile === E.ROAD) return;                       // empty road draws nothing, on purpose
    // A FORK is NOT combat here. It used to be lumped in and drew a goblin — but a fork is a road split,
    // a CHOICE, and the monster behind it is not even decided until you pick a lane (the tile re-rolls as
    // monster or elite at resolve time). Drawing any creature on it claims knowledge nobody has.
    const combat = t.tile === E.MONSTER || t.tile === E.HORDE || t.tile === E.ELITE
      || t.tile === E.AMBUSH || t.tile === E.MIMIC || t.tile === E.BOSS;
    // the ZOOM, measured: draw the entity offscreen, find its bounding box, blit that window centered
    // into the chip. A hardcoded crop cut forward-leaning creatures off at the edge and made every
    // body plan sit differently — measuring is what makes sixteen chips read as one set.
    const boss = (RANK[t.tile] || 0) === 2;
    const S = boss ? 1 : 2;                       // the boss shows WHOLE — the chapter climax reads entire
    const off = chipOff(96 * S, 96 * S);
    const octx = off.getContext("2d");
    octx.clearRect(0, 0, off.width, off.height);
    octx.imageSmoothingEnabled = false;
    if (combat) {
      ART.drawMonster(octx, 0, 0, { family: t.fam, rank: RANK[t.tile] || 0, level: t.ml,
                                    biome: t.biome || 0, mimic: t.tile === E.MIMIC,
                                    frame: 0, scale: S, facing: -1 });
      if (t.tile === E.HORDE) {                   // the pack: a second head behind the first
        octx.globalAlpha = 0.6;
        ART.drawMonster(octx, 14, 0, { family: t.fam, rank: 0, level: t.ml, biome: t.biome || 0,
                                       frame: 1, scale: 2, facing: -1 });
        octx.globalAlpha = 1;
      }
    } else if (PROP[t.tile] && ART.drawProp) {
      ART.drawProp(octx, 0, 0, { kind: PROP[t.tile], frame: 0, scale: S });
    } else return;
    // measure the painted mass
    const img = octx.getImageData(0, 0, off.width, off.height).data;
    let x0 = off.width, x1 = 0, y0 = off.height, y1 = 0;
    for (let y = 0; y < off.height; y++)
      for (let x = 0; x < off.width; x++)
        if (img[(y * off.width + x) * 4 + 3] > 8) {
          if (x < x0) x0 = x; if (x > x1) x1 = x;
          if (y < y0) y0 = y; if (y > y1) y1 = y;
        }
    if (x1 < x0) return;                          // nothing painted (never expected, but never crash)
    if (boss) {
      // the boss chip: head and shoulders at the SAME zoom as everyone else. Whole-at-native made
      // the chapter climax read smaller than a rat. It faces left, so the head is the bbox's top-left.
      const sx = Math.max(0, x0 - 2), sy = Math.max(0, y0 - 2);
      const sw2 = Math.min(48, off.width - sx), sh2 = Math.min(72, off.height - sy);
      ctx.drawImage(off, sx, sy, sw2, sh2, 0, 0, sw2 * 2, sh2 * 2);
      return;
    }
    // window: chip-sized, centered on the mass, feet held near the chip floor
    const sy1 = Math.min(off.height, y1 + 5), sy0 = Math.max(0, sy1 - cv.height);
    const sx0 = Math.max(0, Math.min(off.width - cv.width, ((x0 + x1) >> 1) - (cv.width >> 1)));
    const dh = sy1 - sy0, dw = Math.min(cv.width, off.width - sx0);
    if (t.tile === E.AMBUSH) ctx.globalAlpha = 0.7;   // the lurker reads faded, not invisible
    ctx.drawImage(off, sx0, sy0, dw, dh, (cv.width - dw) >> 1, cv.height - dh, dw, dh);
    ctx.globalAlpha = 1;
  });
}

/** One reusable offscreen for chip measuring — allocated once per size, not sixteen times a repaint. */
const chipOffCache = {};
function chipOff(w, h) {
  const k = w + "x" + h;
  if (!chipOffCache[k]) {
    chipOffCache[k] = document.createElement("canvas");
    chipOffCache[k].width = w; chipOffCache[k].height = h;
  }
  return chipOffCache[k];
}

/** The answer bar: a brush picker plus the commit that SCHEDULES THE DICE. */
function renderAnswerBar() {
  const answering = isDaily() ? (road.length > 0 && dailyAnswering()) : canCommitNow();
  gate({ answerBar: answering || (mode === "march" && !!queuedWord) });
  // The heading follows the state too — "your move" when it is, so the road strip reads as a thing to act
  // on rather than a diagram to look at (the whole point the player kept missing).
  const h = $("roadH");
  if (h) {
    h.textContent = answering
      ? t("roadHAnswer", "Your move — choose an action for each tile")
      : isDaily() ? t("roadHDaily", "Today's road — the same rules, at your own pace")
      : t("roadH", "The road ahead — already fixed, not yet rolled");
  }
  // The help line has to tell the TRUTH in every state, because the states look alike (a road strip is on
  // screen in most of them). It used to collapse four situations into one "the dice are scheduled, nothing
  // can change this leg" — which it also showed while merely WAITING for the terrain block, i.e. the exact
  // moment you are about to answer. That single wrong sentence is why answering looked impossible.
  const help = $("roadHelp");
  if (help) {
    let msg, gold = false;
    if (isDaily()) {
      if (answering) {
        gold = true;
        msg = t("roadAnswerDaily", "Your move: pick an action below, tap the tiles you want it on, then "
          + "walk the stretch — it resolves on the spot. Stop any time to bank what you carry.");
      } else {
        msg = t("roadDailyIdle2", "The Gauntlet is the march at your own pace: same tiles, same rules, no "
          + "waiting on blocks. Press \"Set out\" to start.");
      }
      help.innerHTML = gold ? `<b style="color:var(--gold)">${esc(msg)}</b>` : esc(msg);
    } else if (chain && chain.lh && !chain.nh && dapp.busy("commit")) {
      msg = t("roadInFlight", "Your answers are on their way to a block. The dice get pinned the moment "
        + "they land — nothing to do but watch.");
      help.innerHTML = esc(msg);
    } else if (pipel() && queuedWord) {
      msg = t("roadQueued", "Next answers queued — they send themselves the moment the last leg closes.");
      help.innerHTML = esc(msg);
    } else if (pipel()) {
      msg = t("roadPipeline", "Answer the NEXT sixteen now — the last leg is closing itself in the "
        + "background. The march never waits for paperwork.");
      help.innerHTML = `<b style="color:var(--gold)">${esc(msg)}</b>`;
    } else if (!chain) {
      msg = t("roadNoRun", "Set out and the next sixteen tiles of your road appear here, each one waiting "
        + "for your answer.");
    } else if (!chain.lh) {
      msg = t("roadLegacy", "This run predates the current rules and never started walking. "
        + "\"Begin the march\" below wakes it; the road appears seconds later.");
    } else if (chain.nh) {
      msg = t("roadRolling", "Your answers are locked in and the dice for this leg are scheduled. Nothing "
        + "can change it now — settle it to see what happens.");
    } else if (!road.length) {
      // armed, auto off, roll unscheduled, terrain not mined YET — the answer window is about to open
      msg = t("roadPinning", "Pinning your road to a mined block… you'll pick an action for each tile the "
        + "moment it appears, in a second or two.");
    } else {
      gold = true;
      msg = t("roadAnswer", "Your move: pick an action below, then tap the tiles you want it on. Commit "
        + "when the sixteen read right — the dice aren't scheduled until you do, so you're never racing a "
        + "roll. A blank tile just walks in and fights plainly.");
    }
    help.innerHTML = gold ? `<b style="color:var(--gold)">${esc(msg)}</b>` : esc(msg);
  }
  const seg = $("ansSeg");
  if (seg && !seg.dataset.built) {
    seg.dataset.built = "1";
    seg.innerHTML = BRUSHES.map((b, k) =>
      `<button data-k="${k}">${esc(b.onlyTile === E.FORK ? t("actn_right_fork", "Take the right lane")
          : b.notTile === E.FORK ? t("actn_right_rally", "Rally")
          : t("actn_" + ACT_KEY[b.a], ACT_INFO[b.a][0]))}<span> ${b.icon}</span></button>`).join("");
    seg.querySelectorAll("button").forEach((b) => b.onclick = () => { brush = Number(b.dataset.k); selTile = -1; renderAnswerBar(); });
    relocalize(seg);
  }
  if (seg) seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", Number(b.dataset.k) === brush));
  // The line under the strip explains, in priority order: the TILE you just tapped (name, what it is,
  // and what you answered on it), else the armed brush. Tapping the road answers the player's actual
  // question — "what IS this thing?" — which a bare icon grid never did.
  const hint = $("ansHint");
  if (hint) {
    const sel = selTile >= 0 ? road[selTile] : null;
    if (sel) {
      // combat tiles introduce themselves BY NAME: "Elite — knucker", never a bare stat class
      let nm = t("tile_" + sel.tile, TILE_INFO[sel.tile][0]);
      if (COMBAT_TILES().includes(sel.tile) && sel.tile !== E.MIMIC) {
        nm += " — " + speciesLabel(sel.tile, sel.fam, sel.biome, false);
      }
      const de = t("tiled_" + sel.tile, TILE_INFO[sel.tile][1]);
      const mine = answers[selTile];
      const actBit = mine
        ? " · " + t("yourAnswer", "Your answer:") + " " + actName(mine, sel.tile) + " — " + actDesc(mine, sel.tile)
        : sel.ml ? " · " + t("tileLevel", "level {l}", { l: sel.ml }) + (sel.swing ? " · " + t("tileSwing", "each hit ≈ {s} hp before armour", { s: sel.swing }) : "") : "";
      hint.innerHTML = `<b>${esc(nm)}</b> — ${esc(de)}${esc(actBit)}`;
    } else {
      const b = BRUSHES[brush] || BRUSHES[0];
      hint.textContent = actDesc(b.a, b.onlyTile != null ? b.onlyTile : E.MONSTER);
    }
  }
  const cb = $("commitBtn");
  if (cb) {
    cb.textContent = isDaily() ? t("walkLeg", "Walk these sixteen")
      : queuedWord ? t("queuedBtn", "Queued — sends itself")
      : t("commitLeg", "Commit these sixteen");
    cb.disabled = !answering;   // `answering` (march = canCommitNow) already excludes busy/queued
  }
}

/** The Gauntlet's loadout is locked from the first step: a claim carries exactly one build. */
const dailyLocked = () => !daily || !daily.st || daily.st.started || daily.st.stopped;

function renderDials() {
  const ss = $("stanceseg");
  if (ss && !ss.dataset.built) {
    ss.dataset.built = "1";
    ss.innerHTML = STANCE_KEY.map((k, i) =>
      `<button data-s="${i}" data-i18n="autogame.stance_${k}">${k}</button>`).join("");
    relocalize(ss);
    ss.querySelectorAll("button").forEach((b) => b.onclick = () => setStance(Number(b.dataset.s)));
  }
  // ONE card, two masters. Daily drives the sliders from the claim's tier values (they SNAP to the eight
  // rungs — showing a position the claim cannot carry would be a small lie repeated forever) and locks the
  // lot once the walk starts; the march keeps its continuous values and its Save button. The player asked
  // for exactly this: "why is daily gauntlet not sliders but buttons?" — because it was wrong, that's why.
  const dTiers = isDaily() && daily ? daily.st.tiers : null;
  const lock = isDaily() && dailyLocked();
  const stSel = dTiers ? dTiers[0] : pendStance;
  if (dTiers) {
    $("agg").value = String(D.AGG_OF(dTiers[1]));
    $("aggVal").textContent = D.AGG_OF(dTiers[1]);
    $("focus").value = String(D.PCT_OF(dTiers[2]));
    $("focusVal").textContent = `${D.PCT_OF(dTiers[2])} / ${100 - D.PCT_OF(dTiers[2])}`;
    $("heal").value = String(D.PCT_OF(dTiers[3]));
    $("healVal").textContent = D.PCT_OF(dTiers[3]) + "%";
  }
  // The MARCH locks the card too, exactly while there is nothing the dials could govern: answers are
  // committed (in flight or queued) or the dice are rolling, and the next stretch has not opened. An
  // editable dial there implied the roll could still be steered — it can't; edits only ever ride with
  // the NEXT commit. The card re-opens the moment the next answering window does (including pipelining).
  const answeringNow = canCommitNow();
  const mLock = !isDaily() && !!chain && chain.alive && !chain.done && !chain.retired && !!chain.lh
    && !answeringNow;
  for (const id of ["agg", "focus", "heal"]) if ($(id)) $(id).disabled = (isDaily() && lock) || mLock;
  if (ss) ss.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("on", Number(b.dataset.s) === stSel);
    b.disabled = (isDaily() && lock) || mLock;
  });
  const note = $("dialsNote");
  if (note) {
    note.textContent = !isDaily()
      ? (mLock ? t("ordersLocked", "Locked in — the dice are rolling. The dials open again with your next stretch of road.")
               : t("ordersRide", "Changed orders ride along with your next commit — nothing extra to press."))
      : lock ? t("dialsDailyLocked", "Locked — this build is baked into today's claim.")
      : t("dialsDailySnap", "The dials snap to the eight rungs a claim can carry, and lock when you set out.");
  }
  {
    const [dn, xn, sg, cap] = E.STANCES[stSel];
    $("stanceHint").textContent = cap === 0
      ? t("stanceGuardedHint", "Guarded takes a quarter less damage and can never build a greed streak — it wins by finishing, not by compounding.")
      : `Damage ×${(dn / 4).toFixed(2)} · renown ×${(xn / 4).toFixed(2)} · streak +${sg} per fight, capped ×${((E.STREAK_DIV + cap) / E.STREAK_DIV).toFixed(1)}`
        + (stSel === E.ST_EVASIVE ? " · " + t("stanceEvasiveHint", "footwork: Dodge and Sprint cost 1 less") : "");
    $("stanceVal").textContent = STANCE_KEY[stSel];
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
    drawWarrior(ctx, footX(cv.width / 2, 2), footY(cv.height - 10, 2),
      { gear: r ? r.gear : new Array(E.NSLOT).fill(0), frame: 0, scale: 2, facing: 1,
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
      const nm = esc(slotLabel(i, it));
      const tip = (i === E.G_WEAPON && g) ? ` title="${esc(wkindHint(it.kind))}"` : "";
      return `<div class="slot ${g ? "" : "empty"}"${tip}><div class="nm">${nm}</div>
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
  // the SDK's shared high-score table: it resolves aliases, highlights you, and looks identical to every
  // other game's board. `tag` carries what is specific to a march.
  renderTopScores(el, rows.map((x) => ({
    addr: x.who,
    score: x.sc.toLocaleString(),
    tag: `${x.r.done ? "🏁" : x.r.alive ? "🚶" : x.r.retired ? "🚪" : "💀"} ${t("depthLabel", "Depth")} ${x.r.depth} · ${E.rankOf(x.sc)}`,
  })), dapp.me, t("boardEmpty", "No marches yet. Be the first out of the gate."),
     t("renownLabel", "Renown"));
}

// ── actions ─────────────────────────────────────────────────────────────────────────────────────
/** Every action goes through the SDK's guarded-action wrapper (sign-in check, then the click-time pending
 *  guard), then re-renders so the guard is visible immediately. */
function act(phase, what, fn, keyName, keyVal) {
  const fired = guardedAction(dapp, phase, what, fn, keyName, keyVal);
  if (fired) { poke(); render(); }
  return fired;
}

function begin() {
  if (isDaily()) {
    if (!daily) return;
    // Signed out, the click RAISES THE SIGN-IN BAR, exactly like the march's Set out. The daily world
    // is seeded per-player, so without this a signed-out visitor stared at a greyed button under a
    // strip telling them to press it.
    if (!dapp.me) { act("begin", t("whatBegin", "Setting out"), () => daily.start()); return; }
    daily.start();
    return;
  }
  // The fresh run id rides in the pend so the landed-check can recognise THIS march. "myId != null" was
  // the check, and a dead player still HAS a run — so the ✓ toast fired on the corpse one poll after the
  // click and released the button, over a screen still showing you dead.
  const rid = randId();
  act("begin", t("whatBegin", "Setting out"), () =>
    dapp.call("begin", [rid], 0n, t("labelBegin", "Set out on a new march"), { phase: "begin", rid }));
}
function commitPlan() {
  if (!chain) return false;
  // ONE call carries all four dials, because they are one decision and four transactions is forty minutes
  // on this chain. For a legacy run stuck unarmed (begun before begin() armed), this same call arms it.
  return act("plan", t("whatPlan", "Saving your battle orders"), () => {
    dapp.call("plan", [myId, planAgg, pendStance, pendFocus, pendHeal], 0n,
      t("labelPlan", "Save battle orders"),
      { phase: "plan", agg: planAgg, stance: pendStance, focus: pendFocus, heal: pendHeal });
  }, "agg", planAgg);
}
/** Do the dials on the run differ from what the player has set locally? Then the next commit owes a
 *  plan() ahead of itself — the ONE button submits both. */
function dialsDirty() {
  return !!chain && dialsTouched && (Number(chain.agg) !== Number(planAgg)
    || Number(chain.stance) !== Number(pendStance)
    || Number(chain.focus) !== Number(pendFocus)
    || Number(chain.healpct) !== Number(pendHeal));
}
let queuedPlan = false;   // orders owed to the chain — sent (and resent) by the pump until they land
/** Commit your answers to the sixteen visible tiles — and thereby schedule their dice. */
function commitLeg() {
  const clean = answers.map((a, i) => {
    const allowed = ACTS_FOR[road[i] ? road[i].tile : E.ROAD] || [0];
    return allowed.includes(a) ? a : 0;
  });
  if (isDaily()) {
    // the SAME answers, the SAME engine — just resolved here and now instead of sixteen blocks from now.
    // That single difference is the entire free mode.
    if (!dailyAnswering()) return;
    daily.walk(clean.slice(0, Math.max(0, D.STEPS - daily.stepIdx())));
    answers = new Array(E.LEG).fill(0);
    selTile = -1;
    return;
  }
  if (!chain) return;
  // Defense in depth: never submit a commit for a run that isn't holding for answers. The gates above
  // (canAnswer) already hide the button, but a stale click, a queued sender, or a keyboard path must not
  // slip a commit onto a corpse — the contract would reject it, but the player would see a phantom
  // "confirming…" and a wasted round-trip. The chain would reject it anyway; we refuse it here first.
  if (!canAnswer()) return;
  const word = E.packLeg(clean);
  // ONE click submits BOTH: touched dials ride ahead of the answers as a plan() call, and the commit
  // queues itself right behind through the same pump that handles the pipelined case. The pump holds
  // the answers until the orders are on the chain, so they always govern the leg they were set for.
  const dirty = dialsDirty();
  if (dirty) { queuedPlan = true; commitPlan(); }
  if (pipel()) {
    // the previous leg's close is still in flight, so this commit would revert (nh != 0). Queue it: it
    // sends itself the moment the chain parks. The player's flow never blocks on bookkeeping.
    if (queuedWord) return;
    queuedWord = { leg: chain.leg + 1, word };
    wordSave(myId, chain.leg + 1, word);
    okBar(t("queuedCommit", "Answers queued — they send the moment the leg closes."));
    render();
    return;
  }
  wordSave(myId, chain.leg, word);        // the animator replays this leg from it once it settles
  if (dirty) {
    queuedWord = { leg: chain.leg, word };
    okBar(t("queuedAfterOrders", "Orders sent — your answers follow the moment they land."));
    render();
    return;
  }
  act("commit", t("whatCommit", "Answering this stretch of road"), () =>
    dapp.call("commit", [myId, word], 0n, t("labelCommit", "Commit your answers"),
      { phase: "commit", leg: chain.leg }), "leg", chain.leg);
}

function retire() {
  audio.sfx("bank");
  if (isDaily()) { if (daily) daily.stopHere(); return; }
  if (!chain) return;
  act("retire", t("whatRetire", "Retiring"), () =>
    dapp.call("retire", [myId], 0n, t("labelRetire", "Retire on your feet"), { phase: "retire" }));
}
function setStance(s) {
  if (isDaily()) { if (daily) daily.setTier(0, s); renderDials(); return; }
  dialsTouched = true;
  pendStance = s; renderDials();
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

// ── wiring ──────────────────────────────────────────────────────────────────────────────────────
function wireDials() {
  const agg = $("agg"), heal = $("heal"), focus = $("focus");
  // tier quantizers — the inverse of D.AGG_OF / D.PCT_OF, clamped to the claim's 3-bit range
  const aggTier = (v) => Math.max(0, Math.min(D.TIERS - 1, Math.round((Number(v) - 1) / 2)));
  const pctTier = (v) => Math.max(0, Math.min(D.TIERS - 1, Math.round(Number(v) / 14)));
  agg.oninput = () => {
    if (isDaily()) { if (daily && daily.setTier(1, aggTier(agg.value))) renderDials(); return; }
    dialsTouched = true; planAgg = Number(agg.value);
    $("aggVal").textContent = planAgg; updateAggHint();
  };
  heal.oninput = () => {
    if (isDaily()) { if (daily && daily.setTier(3, pctTier(heal.value))) renderDials(); return; }
    dialsTouched = true;
    $("healVal").textContent = heal.value + "%"; pendHeal = Number(heal.value);
  };
  heal.onchange = () => { if (!isDaily()) pendHeal = Number(heal.value); };
  focus.oninput = () => {
    if (isDaily()) { if (daily && daily.setTier(2, pctTier(focus.value))) renderDials(); return; }
    dialsTouched = true;
    $("focusVal").textContent = `${focus.value} / ${100 - focus.value}`;
    pendFocus = Number(focus.value);
  };
  focus.onchange = () => { if (!isDaily()) pendFocus = Number(focus.value); };
}

/** Price the pull against the heaviest swing waiting in the visible leg — the number the dial exists for. */
function updateAggHint() {
  if (!chain || !road.length) return;
  const worst = Math.max(0, ...road.map((t) => t.swing));
  const absorb = E.armorPts(chain);
  const cost = Math.max(planAgg, planAgg * worst - absorb);
  const pct = chain.hp ? Math.round((cost * 100) / chain.hp) : 0;
  $("aggHint").innerHTML = worst
    ? `The hardest hitter on this stretch strikes for <b>${worst}</b> hp a blow. Pulling <b>${planAgg}</b> costs about <b>${cost}</b> hp there — <b>${pct}%</b> of what you have.`
    : "No fights on this stretch — pull what you like.";
}

async function boot() {
  wireWallet(dapp);
  // The SDK's two-stage lifecycle instead of a hand-rolled toast: a signed action reads "confirming…",
  // and the ✓ line fires only when settleInflight's own landed-check SEES it on-chain. The old okBar here
  // said "— landed" at sign time, when the tx had merely been submitted — the one lie the status work was
  // about removing. (Rejections already raise the SDK's loud toast in _applyReturn; nothing to add here.)
  dapp.doneLabels({
    begin: t("doneBegin", "✓ You're on the road — the march has begun."),
    plan: t("donePlan", "✓ Battle orders are live on the chain."),
    commit: t("doneCommit", "✓ Answers committed — the dice are scheduled."),
    retire: t("doneRetire", "✓ Retired on your feet — renown banked."),
    // advance stays silent on land: it settles every leg, and the animation IS its feedback
  });
  dapp.onReturn((pend, ok, err) => { poke(); dapp.showReturn(pend, ok, err, {
    begin: t("confBegin", "Setting out — confirming on-chain…"),
    plan: t("confPlan", "Sending your battle orders — confirming on-chain…"),
    commit: t("confCommit", "Sending your answers — confirming on-chain…"),
    advance: t("confAdvance", "Settling the leg — confirming on-chain…"),
    retire: t("confRetire", "Retiring — confirming on-chain…"),
  }); });
  wireDials();
  $("beginBtn").onclick = begin;
  $("commitBtn").onclick = commitLeg;
  $("planBtn").onclick = commitPlan;
  $("retireBtn").onclick = retire;
  if ($("stopBankBtn")) $("stopBankBtn").onclick = retire;   // daily: Stop & bank routes through retire()

  // sound: a header toggle, and a one-time gesture hook so a player who had it ON last visit gets it back
  // the instant they touch the page (browsers block audio until a real gesture — we cannot start it sooner)
  const paintSound = () => { const b = $("soundBtn"); if (b) b.textContent = audio.isOn() ? "🔊" : "🔇"; };
  if ($("soundBtn")) $("soundBtn").onclick = () => { audio.toggle(); paintSound(); };
  paintSound();
  const firstGesture = () => {
    window.removeEventListener("pointerdown", firstGesture);
    if (audio.wanted()) { audio.setOn(true); paintSound(); } else audio.ensure();
  };
  window.addEventListener("pointerdown", firstGesture, { once: true });

  daily = createDaily({
    dapp, t, onChange: onDailyChange,
    actLabel: (a, tile) => ACT_ICON[a] + " " + actName(a, tile),
    tileIcon: (cls) => TILE_ICON[cls],
  });
  try { mode = localStorage.getItem("nado_autogame_mode") === "daily" ? "daily" : "march"; } catch (e) {}
  buildModeBar();

  // Paint ONCE before touching the network. The stance picker and the gear figure need no chain data — a
  // default warrior is a warrior — and the first refreshAll() waits behind dapp.init() + two calls to a node
  // that trails L1 by a finality window. Without this the page sits with a blank gear canvas and no stance
  // control for as long as the node is slow, which reads as broken (and is exactly what the signed-out UI
  // test caught: everything the SDK wires at boot worked, everything render() draws was still empty).
  render();

  await dapp.init();
  await refreshAll();
  // the heavy poll, at an ADAPTIVE cadence: 1s while poke() says something of ours is in flight, 3s idle
  const heavyLoop = async () => {
    if (!refreshing) { refreshing = true; try { await refreshAll(); } catch (e) {} refreshing = false; }
    setTimeout(heavyLoop, performance.now() < hotUntil ? 1000 : 3000);
  };
  setTimeout(heavyLoop, 3000);
  // FAST LANE: the cheap endpoints (cursor + balances) every 1.5s, so countdowns tick and the "dice are
  // down" moment is noticed at block speed even when the heavy storage poll is slow. Snappy is a feature:
  // with the two-block dice gap, answer→animation is bounded by how fast this loop notices, not by design.
  setInterval(async () => {
    const c0 = dapp.cursor;
    try { await dapp.refresh(); } catch (e) {}
    if (dapp.cursor === c0) return;
    render();
    // the tip just CROSSED the dice height → pull full state right now instead of waiting out the heavy
    // poll's slot: the preview (and with it the animation) starts the same second the dice exist
    if (mode === "march" && chain && chain.alive && !chain.done && !chain.retired && chain.nh
        && dapp.cursor != null && dapp.cursor >= chain.nh && previewed !== myId + ":" + chain.leg
        && !refreshing) {
      refreshing = true; try { await refreshAll(); } catch (e) {} refreshing = false;
    }
  }, 1500);
  requestAnimationFrame(tick);
}

boot().catch((e) => alertBar(String((e && e.message) || e)));

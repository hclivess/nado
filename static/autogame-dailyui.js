// autogame-dailyui.js — the Daily Gauntlet's UI half: today's free road, the loadout, the per-step choice,
// and the replay-verified board. The RULES live in autogame-daily.js (shared with the faucet oracle) and
// the drawing lives in autogame.js's animator; this file is only the panel and the wiring between them.
//
// It is a separate module for one reason: every frame of it is SDK. The card is nadodapp's dailyFrame, the
// board is renderTopScores over provable.js's verifyEntries, the anchor upkeep is seedDaily, the click
// guards are guardedAction. Keeping it out of autogame.js makes it obvious at a glance that nothing here
// re-implements something the SDK already does — and if a line ever does, it will stick out.
import { dailyFrame, renderTopScores, guardedAction, confirmingLabel, notify, esc, relocalize } from "./nadodapp.js?v=77a0d4df";
import { todayIdx, anchorOf, seedDaily, pendingDaily, entriesFrom, verifyEntries, provableSeed, unpackMoves } from "./provable.js?v=a13bb487";
import * as E from "./autogame-engine.js?v=eb6129b3";
import * as D from "./autogame-daily.js?v=e7c3c3fb";

const LS = "nado_autogame_gauntlet";      // {day, tiers, actions} — a Gauntlet survives a reload

/**
 * createDaily({dapp, t, actLabel, tileIcon, onChange})
 * `actLabel(action, tileClass)` and `tileIcon(tileClass)` come from the march's own renderer. They are
 * passed in rather than rebuilt here because the names are already translated (autogame.actn_*), already
 * handle the two meanings of the right-hand action (take the right FORK vs RALLY), and a second copy would
 * be a second thing to keep in step with the rules.
 */
export function createDaily(o) {
  const { dapp, t, actLabel, tileIcon, onChange, onReplay } = o;
  const st = {
    day: null, anchor: null, seed: null, world: null,
    tiers: [0, 1, 3, 2], actions: [], run: null, started: false, seeding: false, lastEvent: null,
  };

  function save() {
    try {
      localStorage.setItem(LS, JSON.stringify({ day: st.day, tiers: st.tiers, actions: st.actions,
                                                stopped: !!st.stopped }));
    } catch (e) {}
  }
  function load(day) {
    try {
      const v = JSON.parse(localStorage.getItem(LS) || "null");
      if (v && v.day === day) {
        st.tiers = v.tiers; st.actions = v.actions || []; st.stopped = !!v.stopped;
        return v.actions.length > 0;
      }
    } catch (e) {}
    return false;
  }

  /** Rebuild the run from the recorded actions. The Gauntlet is a pure function of (seed, loadout, actions),
   *  so replaying is how the panel gets its state — there is no second copy of the run to drift. The run is
   *  replayed OPEN (not retired): mid-walk it is a live march, and the score shown is what stopping now
   *  would bank (D.scoreIfStopped), which is also exactly the march's cash-out meter. */
  function recompute() {
    if (!st.seed) { st.run = null; return; }
    const r = D.play(st.seed, st.tiers, st.actions, true);
    st.run = r.run;
    st.lastEvent = r.events.length ? r.events[r.events.length - 1] : null;
    st.score = D.scoreIfStopped(r.run);
    st.events = r.events;
  }

  // `stopped` is part of over(): banking mid-road ENDS the day's run. It used to be a side flag the
  // score footer never consulted, so stopping showed no post button at all — you could quit but not score.
  const over = () => !!(st.stopped || (st.run && (!st.run.alive || st.run.done
                                                  || st.actions.length >= D.STEPS)));
  const stepIdx = () => st.actions.length;

  /** The tile the player is standing in front of, sliced exactly as the contract slices it. */
  function currentTile() {
    if (!st.world || over() || !st.run) return null;
    return D.roadAhead(st.world, st.run, stepIdx(), 1)[0] || null;
  }

  // ── anchor upkeep ──────────────────────────────────────────────────────────────────────────────
  // Today's road cannot be derived until the day has an on-chain anchor, and the FIRST player of the day
  // is the one who pays for pinning it. seedDaily carries that intent across a wallet round-trip, which is
  // the case that matters: a brand-new account has to register before it can make any call, and that is a
  // full redirect that would otherwise destroy an await-loop mid-flight.
  async function ensure(getStorage) {
    const day = todayIdx();
    if (st.day !== day) { st.day = day; st.anchor = null; st.seed = null; st.world = null; st.actions = [];
                          st.started = false; st.stopped = false; load(day); }
    const sto = await getStorage();
    if (sto) st.anchor = anchorOf(sto, (s, n) => s[n] || {}, day);
    if (!st.anchor && dapp.me && (st.seeding || pendingDaily(D.SLUG, day))) return;
    if (!st.anchor && dapp.me) {
      st.seeding = true;
      try {
        st.anchor = await seedDaily(dapp, {
          slug: D.SLUG, day, base: location.origin, getStorage,
          _m: (s, n) => s[n] || {},
          onProgress: () => { if (onChange) onChange(); },
        });
      } finally { st.seeding = false; }
    }
    if (st.anchor && dapp.me) {
      const seed = provableSeed(D.SLUG, day, st.anchor, dapp.me);
      if (st.seed !== seed) {
        st.seed = seed;
        st.world = D.dailyWorld(seed);
        st.started = load(day);
        recompute();
      }
    }
  }

  // ── the panel ──────────────────────────────────────────────────────────────────────────────────
  function bodyHtml() {
    const r = st.run || {};
    const head = '<div class="grow"><span>' + esc(t("gauntletStep", "Step {i} of {n}",
        { i: stepIdx(), n: D.STEPS })) + '</span><span class="mono">'
      + esc(t("gauntletHp", "{hp}/{mx} hp", { hp: r.hp | 0, mx: r.maxhp | 0 })) + '</span><span class="mono">'
      + esc(t("gauntletRenown", "{n} renown", { n: (r.xp | 0).toLocaleString() })) + "</span></div>";
    if (!st.started) {
      // The card shows its controls even while the day's road is still being pinned — a signed-in player
      // once opened this and found NOTHING to press, because the whole body hid behind the anchor. The
      // build picker needs no anchor; only the walk itself does, so only the walk button waits.
      const pinning = !st.world;
      // No start button of its own: "Set out" on the run card starts today's walk, exactly as it starts a
      // march. This card only explains the day and, at the end, posts the proof.
      return head + '<p class="hint">' + esc(t("gauntletPitch3",
        "The march, at your own pace: same road, same rules, nothing on-chain until the end — then you "
        + "post your moves as a claim every browser can replay, and the faucet pays yesterday's verified "
        + "best. Set your build below (the dials snap to the eight rungs a claim can carry, and lock when "
        + "you set out), then press Set out above.")) + "</p>"
        + (pinning ? '<p class="hint">' + esc(t("gauntletPinning",
            "⏳ Pinning today's road to the chain — a few seconds…")) + "</p>" : "");
    }
    if (over()) return head;
    // Mid-walk the card is only a status line: the actual play surface is the SAME road strip, brush
    // palette and canvas the march uses — the free mode is the march at your own pace, not a second game
    // (shipping it as a separate emoji panel was the mistake this line is the tombstone of).
    return head + '<p class="hint">' + esc(t("gauntletWalking",
      "Answer the tiles on the road above and commit — each stretch resolves instantly. Stop any time to "
      + "bank what you carry.")) + "</p>";
  }

  function renderCard(el) {
    const done = over();
    dailyFrame(dapp, {
      el,
      name: t("gauntletName", "Daily Gauntlet"),
      signedOut: t("gauntletSignIn",
        "Sign in to walk today's free Gauntlet — no stake, 124 steps of your own road, and the faucet pays "
        + "the top of yesterday's board automatically."),
      ready: !!dapp.me,
      seeding: t("gauntletSeeding",
        "Pinning today's road to a block nobody could predict — this takes a moment the first time each day."),
      body: bodyHtml(),
      done,
      score: st.score,
      scoreLabel: st.run && !st.run.alive
        ? t("gauntletFell", "You fell at step {n}. Final renown: {s}", { n: st.run.depth, s: st.score })
        : t("gauntletStood", "You walked off at step {n}, on your feet. Final renown: {s}",
            { n: st.run ? st.run.depth : 0, s: st.score }),
      posted: st.posted != null ? st.posted : null,
      postLabel: t("gauntletPost", "🏆 Post this run to the board"),
      onPost: post,
      onReplay: () => { st.actions = []; st.started = false; st.posted = null; st.stopped = false;
                        recompute(); save(); if (onChange) onChange(); },
      wire: (root) => {
      },
    });
    relocalize(el);
  }

  /** Take one step. The engine decides what happens; this only records the choice and lets the caller
   *  animate the event it produced — the panel never computes an outcome of its own. */
  function choose(a) {
    if (over() || !st.world) return;
    const before = st.events ? st.events.length : 0;
    st.actions.push(a);
    recompute();
    save();
    if (onChange) onChange(st.events && st.events.length > before ? st.events.slice(before) : null);
  }

  /** Walk an answered stretch in one go — the march's "commit these sixteen", resolved on the spot
   *  instead of sixteen blocks later. Same answers, same engine, no waiting: that is the whole point of
   *  the free mode, and the ONLY difference from the staked one. */
  function walk(acts) {
    if (over() || !st.world) return;
    const before = st.events ? st.events.length : 0;
    for (const a of acts) {
      if (over()) break;
      st.actions.push(a & 7);
      recompute();                    // per-step: death mid-stretch must stop consuming answers
    }
    save();
    if (onChange) onChange(st.events && st.events.length > before ? st.events.slice(before) : null);
  }

  /** Stop while standing: the run is scored as retired at this depth, which is a real decision — the road
   *  bonus is pro-rata, so every further step raises it and dying forfeits it. */
  function stopHere() {
    if (!st.run || over()) return;
    st.stopped = true;
    if (st.run.alive && !st.run.done) st.run.retired = 1;   // so every panel reads it as a clean walk-off
    st.score = E.score(st.run);
    save();
    if (onChange) onChange();
  }

  function post() {
    if (!over()) return;
    if (!guardedAction(dapp, "post", t("whatPost", "Posting your Gauntlet score"), () => {
      const words = D.packClaim(st.tiers, st.actions);
      dapp.call("post", [st.day, st.score, D.HEAD + st.actions.length, ...words], 0n,
        t("labelPost", "post my Daily Gauntlet score ({s})", { s: st.score }), { phase: "post" });
    })) return;
    notify(confirmingLabel());
    if (onChange) onChange();
  }

  // ── the board ──────────────────────────────────────────────────────────────────────────────────
  // Every row is REPLAYED here before it can appear. A posted score is a claim, not a result: the contract
  // stores it without judging it (it cannot — replaying a 124-step march is not something a proof budget
  // should pay for), and the browser plus the faucet oracle are what make it true.
  async function renderBoard(el, sto) {
    if (!el) return;
    const day = st.day || todayIdx();
    const m = (s, n) => s[n] || {};
    const anchor = sto ? anchorOf(sto, m, day) : null;
    if (!anchor) {
      el.innerHTML = '<span class="dim">' + esc(t("gauntletNoAnchor",
        "Today's road has not been pinned yet — the first player of the day pins it.")) + "</span>";
      return;
    }
    const words = Array.from({ length: D.WORDS }, (_, k) => "ew" + k);
    const rows = await verifyEntries(entriesFrom(sto, m, day, words),
      (en) => D.verifyClaim(day, en.n, en.words, anchor, en.addr));
    // Every row carries WHEN it was posted (ts, chain-minted; day as the fallback stamp) and the whole
    // verified entry, so a click can rebuild the exact run from (seed, loadout, moves) and replay it.
    await renderTopScores(el, rows.map((r) => ({
        addr: r.addr, score: r.score.toLocaleString(), ts: r.ts, day: r.day, en: r,
      })), dapp.me,
      t("gauntletBoardEmpty", "Nobody has finished today's Gauntlet yet. Be the first name on it."),
      t("renownLabel", "Renown"), null,
      onReplay ? (row) => replayEntry(row.en, anchor) : null);
  }

  /** Rebuild a posted claim into a live run+events and hand it to the stage animator. The claim is a pure
   *  function of (seed, loadout, moves): the seed comes from the day's anchor and the POSTER's address, the
   *  loadout+moves are unpacked from the entry words — exactly what D.verifyClaim replays to score it, but
   *  kept as the run and its per-step events so the run can be watched, not just scored. */
  function replayEntry(en, anchor) {
    if (!en || !onReplay) return;
    try {
      const seed = provableSeed(D.SLUG, en.day, anchor, en.addr);
      const syms = unpackMoves(en.words, D.ACT_BITS, en.n);
      const res = D.play(seed, syms.slice(0, D.HEAD), syms.slice(D.HEAD));   // { run, events, score }
      onReplay({ run: res.run, events: res.events, world: D.dailyWorld(seed),
                 addr: en.addr, score: res.score, walk: true });
    } catch (e) {}
  }

  /** My best VERIFIED score today, so the card can show "posted" instead of offering to post again. */
  function syncPosted(sto) {
    const day = st.day || todayIdx();
    const m = (s, n) => s[n] || {};
    let best = null;
    for (const [e, d] of Object.entries(m(sto, "eday"))) {
      if (Number(d) !== day || m(sto, "eaddr")[e] !== dapp.me) continue;
      const sc = Number(m(sto, "escore")[e] || 0);
      if (best == null || sc > best) best = sc;
    }
    st.posted = best;
  }

  /** Start today's walk — wired to the SAME "Set out" button the march uses. */
  function start() {
    if (!st.world || st.started || over()) return;
    st.started = true;
    recompute();
    save();
    if (onChange) onChange();
  }

  /** Set one loadout tier from the shared dials card. Refused once the walk has begun: a claim carries
   *  exactly one build, so the dials lock the moment you set out — re-tuning mid-road would make the
   *  replayed claim disagree with the run you actually walked. */
  function setTier(idx, tier) {
    if (st.started || st.stopped) return false;
    st.tiers[idx] = Math.max(0, Math.min(D.TIERS - 1, tier | 0));
    if (idx === 0) st.tiers[0] = Math.max(0, Math.min(3, st.tiers[0]));
    save();
    recompute();
    if (onChange) onChange();
    return true;
  }

  return { st, ensure, renderCard, renderBoard, syncPosted, over, stepIdx, currentTile, choose, walk,
           stopHere, setTier, start };
}

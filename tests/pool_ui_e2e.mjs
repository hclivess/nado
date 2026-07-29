/*
 * pool_ui_e2e.mjs — drives the REAL Pool page over CDP the way a human does: start a practice frame,
 * drag on the canvas to aim, set power and English, arm-and-fire the shot, and assert the engine
 * advanced. This is the layer the headless engine tests cannot reach — canvas pointer events → aim
 * state → payload encoding → applyMove → repaint — plus the free-frame stake, the ball-in-hand drag,
 * playback timing, the aim-assist switch and the invariant that a visible instrument is a usable one.
 *
 * Practice mode only: nothing is signed, nothing is staked, nothing touches the chain.
 * Run:  node tests/pool_ui_e2e.mjs [url]        (needs chromium; default url is the local node)
 */
import { spawn } from "node:child_process";

const PORT = 9372;
const URL0 = process.argv[2] || "http://127.0.0.1:9173/static/pool.html";
// A FRESH profile per run, and the HTTP cache off below. A persistent --user-data-dir served a stale
// pool.js from an earlier run and produced three phantom failures (pointer events "not firing") that
// were nothing but a cached bundle.
const PROFILE = "/tmp/cdp-pool-ui-" + process.pid;
const chrome = spawn("chromium-browser", ["--headless", "--disable-gpu", "--no-sandbox",
  "--remote-debugging-port=" + PORT, "--user-data-dir=" + PROFILE, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0, pend = new Map(), sid;
const send = (m, p) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
const pageErrors = [];

async function evl(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails.exception).slice(0, 300));
  return r.result.result.value;
}
let fails = 0;
async function scenario(name, fn) {
  try { await fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + (e.message || e)); }
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

// pointer gestures on the canvas, in TABLE units (the page maps them back through its own metrics())
const drag = (fromU, toU) => evl(`(() => {
  const cv = document.getElementById("table"), r = cv.getBoundingClientRect();
  const E = window.__pool.E, RAIL = 78, sc = r.width / (E.W + 2 * RAIL);
  const pt = (u) => ({ clientX: r.left + (u[0] + RAIL) * sc, clientY: r.top + (u[1] + RAIL) * sc });
  const mk = (t, u, buttons) => cv.dispatchEvent(new PointerEvent(t, { bubbles: true, buttons, pointerId: 1, ...pt(u) }));
  cv.setPointerCapture = () => {};
  mk("pointerdown", ${JSON.stringify(fromU)}, 1);
  mk("pointermove", ${JSON.stringify(toU)}, 1);
  mk("pointerup", ${JSON.stringify(toU)}, 0);
  return true;
})()`);
const snap = () => evl(`(() => { const e = window.__duel.eng; return e ? {
  mi: e.mi, turn: e.turn, over: e.over, corrupt: e.corrupt, why: e.corruptWhy, open: e.open,
  inHand: e.inHand, breakShot: e.breakShot, shots: e.log.length,
  cue: [Math.trunc(e.b[0].x / 1024), Math.trunc(e.b[0].y / 1024)],
  onTable: e.b.filter((b) => b.on).length } : null; })()`);
const aimState = () => evl(`({ ...window.__pool.aim })`);
// the shot button is arm-then-fire: two taps
const shoot = async () => { await evl(`document.getElementById("btnShoot").click()`); await sleep(120);
                            await evl(`document.getElementById("btnShoot").click()`); };
const waitStill = async (tries = 80) => { for (let i = 0; i < tries; i++) { if (!(await evl(`window.__pool.busy()`))) return; await sleep(150); } };
const aimAtApex = () => evl(`(() => { const e = window.__duel.eng, E = window.__pool.E;
  let apex = 1, ax = 1e9;
  for (let i = 1; i < E.BALLS; i++) if (e.b[i].on && e.b[i].x / 1024 < ax) { ax = e.b[i].x / 1024; apex = i; }
  const cv = document.getElementById("table"), r = cv.getBoundingClientRect(), RAIL = 78;
  const sc = r.width / (E.W + 2 * RAIL);
  cv.setPointerCapture = () => {};
  cv.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, buttons: 1, pointerId: 1,
    clientX: r.left + (Math.trunc(e.b[apex].x / 1024) + RAIL) * sc,
    clientY: r.top + (Math.trunc(e.b[apex].y / 1024) + RAIL) * sc }));
  cv.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, buttons: 0, pointerId: 1 }));
  return true; })()`);
const setPower = (v) => evl(`(() => { const r = document.getElementById("powerRange"); r.value = "${v}";
                                      r.dispatchEvent(new Event("input")); })()`);

try {
  let v = null;
  for (let i = 0; i < 30 && !v; i++) {
    await sleep(1500);
    try { v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch {}
  }
  if (!v) throw new Error("chromium debugger never came up on :" + PORT);
  ws = new WebSocket(v.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const d = JSON.parse(m.data);
    if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
    if (d.method === "Runtime.exceptionThrown") { const ex = d.params.exceptionDetails;
      pageErrors.push(String((ex.exception && ex.exception.description) || ex.text).slice(0, 200)); } };
  const t = await send("Target.createTarget", { url: URL0 });
  const a = await send("Target.attachToTarget", { targetId: t.result.targetId, flatten: true });
  sid = a.result.sessionId;
  await send("Runtime.enable", {});
  await send("Network.enable", {});
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Page.enable", {});
  await send("Page.reload", { ignoreCache: true });
  await sleep(8000);

  await scenario("the page boots with the module hooks live", async () => {
    assert(await evl(`!!window.__duel`), "no __duel hook — old bundle cached?");
    assert(await evl(`!!window.__pool && !!window.__pool.E`), "no __pool hook");
    assert(await evl(`!!document.getElementById("table").getContext("2d")`), "no canvas context");
  });

  // A stake of ZERO is the free game — there is no separate control. Typing it and dragging the SDK's
  // injected stake slider to 0% must both get there.
  await scenario("a zero stake is the free frame", async () => {
    const set = (val) => evl(`(() => { const i = document.getElementById("stakeAmt");
      i.value = ${JSON.stringify(val)}; i.dispatchEvent(new Event("input")); return i.value; })()`);
    await set("1");
    assert(await evl(`window.__duel.freeMode() === false`), "a 1 NADO stake read as free");
    await set("0");
    assert(await evl(`window.__duel.freeMode() === true`), "a 0 stake did not read as free");
    await set("0.0");
    assert(await evl(`window.__duel.freeMode() === true`), "0.0 did not read as free");
    await set("");
    assert(await evl(`window.__duel.freeMode() === false`), "an EMPTY stake must be an error, not a free game");
    assert(await evl(`!!document.getElementById("stakeSlider")`), "the SDK stake slider was not injected");
    await set("1");
    assert(await evl(`window.__duel.amt(0n) !== "0 NADO"`), "a zero pot must render as 'free', not '0 NADO'");
  });

  await scenario("a practice frame racks 16 balls with the break to take", async () => {
    await evl(`document.getElementById("btnPractice").click()`);
    await sleep(1500);
    const s = await snap();
    assert(s, "no engine after starting practice");
    assert(s.onTable === 16, "expected a full rack, got " + s.onTable + " balls");
    assert(s.breakShot && s.inHand, "the break must start with the cue ball in hand");
    assert(s.cue[0] <= 635, "the cue ball must rack behind the head string, got x=" + s.cue[0]);
  });

  // NOTE: while the cue ball is in hand, a drag that STARTS on it moves the ball instead of aiming
  // (that is the whole point of the halo), so an aim drag has to begin away from it.
  await scenario("dragging on the canvas aims the cue", async () => {
    const before = await aimState();
    await drag([1500, 900], [2400, 900]);
    await sleep(200);
    const after = await aimState();
    assert(after.angle !== before.angle, "the aim angle did not move with the drag");
    const want = await evl(`(() => { const e = window.__duel.eng, E = window.__pool.E;
      return E.angleOf(2400 - Math.trunc(e.b[0].x / 1024), 900 - Math.trunc(e.b[0].y / 1024)); })()`);
    assert(after.angle === want, `aim landed at ${after.angle}, the drag target is ${want}`);
  });

  await scenario("ball in hand: dragging the cue ball moves it and records the placement", async () => {
    const s0 = await snap();
    assert(s0.inHand, "expected ball in hand on the break");
    await drag([s0.cue[0], s0.cue[1]], [520, 900]);
    await sleep(200);
    const s1 = await snap(), aim = await aimState();
    assert(Math.abs(s1.cue[0] - 520) < 60 && Math.abs(s1.cue[1] - 900) < 60,
           "cue ball did not follow the drag: " + JSON.stringify(s1.cue));
    assert(s1.cue[0] <= 635 - 28, "the break placement must stay behind the head string");
    assert(aim.px != null && aim.py != null, "the placement was not captured into the shot payload");
  });

  await scenario("power and English controls feed the shot payload", async () => {
    await setPower(63);
    assert((await aimState()).power === 63, "power slider did not reach the aim state");
    await evl(`(() => { const p = document.getElementById("spinPad"), r = p.getBoundingClientRect();
      p.setPointerCapture = () => {};
      p.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 2,
        clientX: r.left + r.width * 0.5, clientY: r.top + r.height * 0.1 })); })()`);
    assert((await aimState()).fwd > 0, "tapping the top of the cue-ball widget should set top spin");
    await evl(`document.getElementById("btnSpinClear").click()`);
    const cleared = await aimState();
    assert(cleared.side === 0 && cleared.fwd === 0, "centre-ball did not clear the English");
  });

  await scenario("arming and firing plays the break, and the bot answers", async () => {
    const before = await snap();
    await evl(`document.getElementById("btnShoot").click()`);    // first tap arms
    await sleep(150);
    assert(await evl(`(window.__duel.armed || {}).key === "shoot"`), "the shot button did not arm");
    await evl(`document.getElementById("btnShoot").click()`);    // second tap fires
    await sleep(3000);
    const after = await snap();
    assert(!after.corrupt, "the engine went corrupt: " + after.why);
    assert(after.shots > before.shots, "the shot never reached the engine");
    assert(!after.breakShot, "the break flag should be cleared after the first shot");
  });

  // The bug this guards: only the LAST shot used to animate, so your break teleported the rack into
  // place and then a single ball rolled (the opponent's reply). Every shot must play, in order.
  await scenario("the break animates the whole rack, not one ball", async () => {
    await waitStill();
    await evl(`document.getElementById("btnPractice").click()`);
    await sleep(1500);
    // a new frame must come up with a CLEAN aim — no angle or placement carried over from the last one
    const fresh = await aimState();
    assert(fresh.angle === 0 && fresh.px == null && fresh.py == null && fresh.call == null,
           "a new frame inherited the previous frame's aim: " + JSON.stringify(fresh));
    await aimAtApex();
    await setPower(63);
    await shoot();
    await sleep(300);
    assert(await evl(`window.__pool.busy()`), "no playback started after the break");
    const moved = new Set();
    let prev = await evl(`window.__pool.shown()`);
    for (let i = 0; i < 40; i++) {
      await sleep(120);
      const now = await evl(`window.__pool.shown()`);
      if (!now) break;
      for (let b = 0; b < now.length; b++) {
        if (prev[b] && (now[b].x !== prev[b].x || now[b].y !== prev[b].y)) moved.add(b);
      }
      prev = now;
      if (!(await evl(`window.__pool.busy()`))) break;
    }
    assert(moved.size >= 5, "only " + moved.size + " ball(s) moved on screen during the break");
    assert(moved.has(0), "the cue ball never moved on screen");
    await waitStill();
  });

  // Playback speed must track the SHOT (a long shot takes longer than a short one) and must be driven by
  // the WALL CLOCK, not by a per-frame counter. The old counter made duration depend on the device's
  // frame rate and let a stale loop from an interrupted animation double-step the next one — the "too
  // fast" report. Timing the real elapsed playback against the schedule pins both down.
  await scenario("playback is real-time: duration tracks the shot and matches the wall clock", async () => {
    await waitStill();
    const log = await evl(`window.__pool.playLog.map((p) => ({ n: p.n, dur: p.dur }))`);
    assert(log.length >= 2, "expected at least two shots played by now");
    for (const p of log) {
      const want = Math.max(700, Math.min(8000, (p.n * 1000) / 110));
      assert(Math.abs(p.dur - want) < 2, `a ${p.n}-frame shot was scheduled for ${p.dur}ms, expected ${want}ms`);
    }
    const long = log.reduce((x, y) => (y.n > x.n ? y : x));
    const short = log.reduce((x, y) => (y.n < x.n ? y : x));
    if (long.n > short.n * 1.5) assert(long.dur > short.dur, "a longer shot must take longer to play");
    // interrupt mid-animation, then time a fresh shot end to end
    await evl(`document.getElementById("btnPractice").click()`);
    await sleep(400);
    await evl(`document.getElementById("btnPractice").click()`);
    await sleep(1200);
    const before = await evl(`window.__pool.playLog.length`);
    await aimAtApex();
    await setPower(63);
    await shoot();
    await sleep(200);
    const t0 = Date.now();
    await waitStill();
    const wall = Date.now() - t0;
    const played = await evl(`window.__pool.playLog.slice(${before}).map((p) => p.dur)`);
    assert(played.length >= 1, "the shot after the interruptions never played");
    const scheduled = played.reduce((x, y) => x + y, 0);
    assert(wall > scheduled * 0.6,
           `playback finished in ${wall}ms against ${scheduled}ms scheduled — something is over-stepping it`);
    const ceiling = scheduled + 420 * played.length + 3000;   // BEAT between shots + polling slack
    assert(wall < ceiling,
           `playback took ${wall}ms against ${scheduled}ms scheduled — duration is tracking the frame rate, not the clock`);
  });

  // Watching the opponent should show HOW they played it: their angle, power and English, read-only.
  // Hand the table over deliberately: a fresh rack broken at ZERO power cannot reach the pack, which is
  // a no-contact foul and passes the turn. Hoping a normal shot misses is how this flaked — potting
  // keeps you at the table, and then the opponent never shoots at all.
  await scenario("the opponent's shot replays with their own instruments", async () => {
    await waitStill();
    const panel = () => evl(`(() => ({ busy: window.__pool.busy(), side: window.__pool.side(),
      power: Number(document.getElementById("powerRange").value),
      angle: (document.getElementById("angleVal") || {}).textContent || "",
      disabled: document.getElementById("powerRange").disabled,
      shootLabel: document.getElementById("btnShoot").textContent,
      barHidden: document.getElementById("shotBar").classList.contains("hidden") }))()`);
    let theirs = null;
    await evl(`document.getElementById("btnPractice").click()`); await sleep(1500);
    await setPower(0);
    await shoot();
    for (let i = 0; i < 200; i++) {
      await sleep(150);
      const info = await panel();
      if (info.busy && info.side === 1) { theirs = info; break; }        // side 1 = the opponent
      if (!info.busy && i > 20) break;
    }
    assert(theirs, "the opponent never took a shot to watch");
    assert(!theirs.barHidden, "the instrument panel was hidden while the opponent's shot replayed");
    assert(theirs.disabled, "the replayed instruments must be read-only");
    assert(/watching/i.test(theirs.shootLabel), "the shoot button should say it is watching, got " + theirs.shootLabel);
    assert(theirs.angle.trim().length > 0, "the replay showed no aim angle");
    assert(theirs.power >= 0 && theirs.power <= 63, "the replay showed no usable power reading");
    // ...and once every queued shot has finished, the panel is live and yours again. (duel.canAct() knows
    // nothing about playback, so this has to wait for the animation to drain before judging.)
    await waitStill();
    const back = await evl(`({ disabled: document.getElementById("powerRange").disabled,
                               busy: window.__pool.busy(), canAct: window.__duel.canAct() })`);
    assert(!back.busy, "playback had not finished");
    if (back.canAct) assert(!back.disabled, "the instruments stayed read-only after the replay ended");
  });

  // The aim preview is an assist, so it has an off switch — and nothing it draws may survive into the
  // playback, which is what "artifacts remain after shooting" meant.
  await scenario("the aim assist slider turns the preview off, and nothing lingers into the shot", async () => {
    await waitStill();
    if (await evl(`!!(window.__duel.eng && window.__duel.eng.over) || !window.__duel.canAct()`)) {
      await evl(`document.getElementById("btnPractice").click()`); await sleep(1500);
    }
    // Count LIGHT pixels. The balls are identical between samples, so the delta is the preview alone.
    // The threshold has to sit below the drawn line's actual colour: white at 72% alpha over the cloth
    // lands near rgb(189,213,205), so a 195 cut-off counts none of it and the measurement reads flat.
    const ink = () => evl(`(() => {
      const cv = document.getElementById("table"), g = cv.getContext("2d");
      const d = g.getImageData(0, 0, cv.width, cv.height).data;
      let n = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i] > 150 && d[i + 1] > 150 && d[i + 2] > 150) n++;
      return n; })()`);
    await aimAtApex();
    await evl(`window.__pool.setAssist(2); window.__duel.render()`);
    await sleep(250);
    const full = await ink();
    await evl(`window.__pool.setAssist(0); window.__duel.render()`);
    await sleep(250);
    const off = await ink();
    assert(off < full, `turning the assist off drew as much as full assist (${off} vs ${full})`);
    assert(await evl(`window.__pool.assist() === 0`), "the assist setting did not stick");
    assert(await evl(`document.getElementById("assistRange").value === "0"`), "the slider did not follow");
    await evl(`window.__duel.render()`);
    assert(await evl(`window.__pool.assist() === 0`), "a re-render reset the assist setting");
    // back to full, then shoot: while the balls roll, the preview must be gone
    await evl(`window.__pool.setAssist(2); window.__duel.render()`);
    await sleep(200);
    const aimed = await ink();
    await shoot();
    await sleep(600);
    assert(await evl(`window.__pool.busy()`), "expected the shot to be playing");
    const during = await ink();
    assert(during < aimed, `the aim preview is still on the cloth during the shot (${during} vs ${aimed})`);
    await waitStill();
  });

  await scenario("the shot log and HUD render after a shot", async () => {
    const log = await evl(`document.getElementById("shotLog").textContent`);
    assert(log && log.trim().length > 0, "the shot log stayed empty");
    const hud = await evl(`document.getElementById("hud").textContent`);
    assert(hud && hud.length > 0, "the HUD stayed empty");
  });

  await scenario("a full practice frame plays out through the UI without corrupting", async () => {
    for (let i = 0; i < 20; i++) {
      const s = await snap();
      if (s.over || s.corrupt) break;
      if (s.turn !== 0) { await sleep(400); continue; }
      if (await evl(`document.getElementById("shotBar").classList.contains("hidden")`)) { await waitStill(); continue; }
      const picked = await evl(`(() => { const b = document.querySelector('#potBtns [data-pot]');
        if (b) { b.click(); return true; } return false; })()`);
      if (!picked) await drag([200, 300], [2400, 900]);
      await setPower(34);
      const need = await evl(`!document.getElementById("callRow").classList.contains("hidden")`);
      if (need) await evl(`(() => { const b = document.querySelector('#callBtns [data-call]'); if (b) b.click(); })()`);
      await shoot();
      await sleep(2000);
      await waitStill();
    }
    const s = await snap();
    assert(!s.corrupt, "the frame corrupted through the UI: " + s.why);
    assert(s.shots >= 3, "the UI only managed " + s.shots + " shots");
  });

  // THE reported failure: the badge said it was your shot and the aiming instrument was not there. The
  // shot bar is gated behind playback, so anything that strands an animation strands the whole control
  // set. This asserts the invariant directly, and then breaks playback on purpose to prove it recovers.
  await scenario("whenever it is your shot, the instrument is actually there", async () => {
    await waitStill();
    const state = () => evl(`(() => {
      const badge = (document.querySelector("#hud .turnbadge") || {}).textContent || "";
      return { badge, barHidden: document.getElementById("shotBar").classList.contains("hidden"),
               frozen: document.getElementById("powerRange").disabled,
               busy: window.__pool.busy(), canAct: window.__duel.canAct(),
               over: !!(window.__duel.eng && window.__duel.eng.over) }; })()`);
    const check = (s, where) => {
      if (s.over) return;
      if (/YOUR SHOT$/.test(s.badge.trim())) assert(!s.barHidden, `badge "${s.badge}" but the shot bar is hidden (${where})`);
      if (!s.busy && s.canAct) {
        assert(!s.barHidden, `it is your shot and nothing is playing, yet the bar is hidden (${where})`);
        assert(!s.frozen, `the instrument is showing on your turn but its controls are disabled (${where})`);
      }
      if (s.busy) assert(!/YOUR SHOT$/.test(s.badge.trim()), `badge "${s.badge}" while a shot is still playing (${where})`);
    };
    check(await state(), "at rest");
    for (let i = 0; i < 3; i++) {
      const s0 = await state();
      if (s0.over) break;
      if (s0.barHidden) { await waitStill(); continue; }
      await evl(`(() => { const b = document.querySelector('#potBtns [data-pot]'); if (b) b.click(); })()`);
      const need = await evl(`!document.getElementById("callRow").classList.contains("hidden")`);
      if (need) await evl(`(() => { const b = document.querySelector('#callBtns [data-call]'); if (b) b.click(); })()`);
      await shoot();
      for (let k = 0; k < 60; k++) { await sleep(200); check(await state(), "shot " + i + " sample " + k);
                                     if (!(await evl(`window.__pool.busy()`))) break; }
      await waitStill();
      check(await state(), "after shot " + i);
    }
  });

  // Two ways playback used to strand the shot bar, injected for real:
  //   (a) a render that throws killed the rAF loop outright;
  //   (b) requestAnimationFrame does not fire at all in a background tab.
  // Either way the instrument has to come back. (b) is what the watchdog exists for — remove it and this
  // scenario hangs on to a "busy" playback for ever.
  await scenario("a broken or frozen playback still gives the instrument back", async () => {
    await waitStill();
    const fresh = async () => { await evl(`document.getElementById("btnPractice").click()`); await sleep(1500); };
    const aimAndFire = async () => {
      await evl(`(() => { const b = document.querySelector('#potBtns [data-pot]'); if (b) b.click(); })()`);
      const need = await evl(`!document.getElementById("callRow").classList.contains("hidden")`);
      if (need) await evl(`(() => { const b = document.querySelector('#callBtns [data-call]'); if (b) b.click(); })()`);
      await shoot();
    };
    // (a) a throwing render — save and restore the REAL bound render, wrapper and all
    await fresh();
    await evl(`(() => { const d = window.__duel; d.__saved = d.render; let n = 0;
      d.render = function () { if (n++ < 20) throw new Error("injected render fault"); return d.__saved.call(d); }; })()`);
    await aimAndFire();
    await sleep(1500);
    await evl(`(() => { const d = window.__duel; if (d.__saved) { d.render = d.__saved; delete d.__saved; } })()`);
    for (let i = 0; i < 60 && (await evl(`window.__pool.busy()`)); i++) await sleep(250);
    assert(!(await evl(`window.__pool.busy()`)), "playback stayed stuck after a throwing render");

    // (b) a frozen tab: rAF never calls back. Only the poll's render can rescue the instrument.
    await waitStill();
    await fresh();
    await evl(`(() => { window.__rafSaved = window.requestAnimationFrame;
                        window.requestAnimationFrame = function () { return 0; }; })()`);
    await aimAndFire();
    assert(await evl(`window.__pool.busy()`), "expected playback to be pending with rAF frozen");
    let freed = false;
    for (let i = 0; i < 40; i++) {                    // stand in for the 3s poll render
      await sleep(400);
      await evl(`try { window.__duel.render(); } catch (e) {}`);
      if (!(await evl(`window.__pool.busy()`))) { freed = true; break; }
    }
    await evl(`(() => { if (window.__rafSaved) { window.requestAnimationFrame = window.__rafSaved; delete window.__rafSaved; } })()`);
    assert(freed, "a frozen tab left the playback pending for ever — the shot bar never comes back");
    await evl(`window.__duel.render()`);
    const barHidden = await evl(`document.getElementById("shotBar").classList.contains("hidden")`);
    if (await evl(`window.__duel.canAct()`)) assert(!barHidden, "the shot bar never came back");
  });

  await scenario("no uncaught page errors", async () => {
    // the fault-injection scenario above throws on purpose — those are not the page's errors
    const real = pageErrors.filter((e) => !e.includes("injected render fault"));
    assert(real.length === 0, real.length + " page error(s): " + real.slice(0, 3).join(" | "));
  });
} catch (e) {
  fails++;
  console.log("FATAL " + (e.stack || e));
} finally {
  try { chrome.kill(); } catch {}
  try { (await import("node:fs")).rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}
console.log(fails ? "\n" + fails + " FAILED" : "\nALL PASS");
process.exit(fails ? 1 : 0);

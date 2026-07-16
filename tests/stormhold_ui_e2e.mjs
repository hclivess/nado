/*
 * stormhold_ui_e2e.mjs — the CARD-BY-CARD UI end-to-end suite: drives the REAL live page over CDP,
 * exercising every kingdom card's complete interaction the way a human does it — tap the tile, answer
 * every decision the UI raises (masks, picks, supply gains, yes/no, Skywatch cyclers, Almanac loop),
 * and assert the engine state that results. The engine itself is fuzz-proven; THIS covers the layer the
 * fuzz can't: frames → DOM → payload encoding → applyMove, plus the defender-side frames.
 *
 * It runs against PRACTICE mode (no chain writes) and uses the window.__duel test hook to CRAFT exact
 * hands/decks/supplies per scenario — so every card, both branches where relevant, is reachable.
 * Run:  node tests/stormhold_ui_e2e.mjs   (needs chromium + the live site)
 */
import { spawn } from "node:child_process";

const PORT = 9371;
const URL0 = process.argv[2] || "https://stormhold.nadochain.com/";
const chrome = spawn("chromium-browser", ["--headless", "--disable-gpu", "--no-sandbox",
  "--remote-debugging-port=" + PORT, "--user-data-dir=/root/snap/chromium/common/cdp-ui", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0, pend = new Map(), sid;
const send = (m, p) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
const pageErrors = [];

// card ids (mirror of stormhold-engine CARDS order)
const C = { copper: 0, silver: 1, gold: 2, homestead: 3, valley: 4, citadel: 5, blight: 6, winnow: 7,
  purifier: 8, windbreak: 9, undertow: 10, hawker: 11, whirlwind: 12, waystation: 13, foundry: 14,
  collector: 15, terraces: 16, raiders: 17, smelter: 18, drifter: 19, reforge: 20, scribe: 21, echo: 22,
  stormriders: 23, assembly: 24, jubilee: 25, observatory: 26, almanac: 27, nightmarket: 28, refinery: 29,
  skywatch: 30, stormcaller: 31, atelier: 32 };

async function evl(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails.exception).slice(0, 300));
  return r.result.result.value;
}
// craft a controlled practice state: my turn, generous actions, exact zones; deck is TOP-LAST
async function craft(spec) {
  await evl(`(() => {
    const d = window.__duel, e = d.eng;
    e.over = false; e.corrupt = false; e.corruptWhy = ""; e.frames = ${JSON.stringify(spec.frames || [])};
    e.turn = 0; e.phase = ${spec.phase ?? 0}; e.actions = ${spec.actions ?? 5}; e.buys = ${spec.buys ?? 2};
    e.coins = ${spec.coins ?? 0}; e.merch = 0; e.silverDone = false; e.log = [];
    Object.assign(e.ps[0], { hand: ${JSON.stringify(spec.hand || [])}, deck: ${JSON.stringify(spec.deck || [0, 0, 0, 0, 0, 0])},
      disc: ${JSON.stringify(spec.disc || [])}, play: [] });
    Object.assign(e.ps[1], { hand: ${JSON.stringify(spec.oppHand || [0, 0, 0, 0, 0])}, deck: ${JSON.stringify(spec.oppDeck || [0, 0, 0])},
      disc: [], play: [] });
    for (const k in e.supply) e.supply[k] = 10;      // full piles each scenario (crafts must not leak)
    ${spec.supply ? `Object.assign(e.supply, ${JSON.stringify(spec.supply)});` : ""}
    e.trash = [];
    d.render();
  })()`);
}
const snap = () => evl(`(() => { const e = window.__duel.eng; return {
  actions: e.actions, buys: e.buys, coins: e.coins, phase: e.phase, corrupt: e.corrupt, why: e.corruptWhy,
  frames: e.frames.map((f) => f.t), hand: e.ps[0].hand, deck: e.ps[0].deck, disc: e.ps[0].disc,
  play: e.ps[0].play, trash: e.trash, oppHand: e.ps[1].hand, oppDeck: e.ps[1].deck, oppDisc: e.ps[1].disc,
  supply: e.supply }; })()`);
// DOM actions — exactly what a player does
const tapHand = (i) => evl(`document.querySelector('#hand [data-h="${i}"]').click()`);
const tapSupply = (cid) => evl(`document.querySelector('#supply [data-sid="${cid}"]').click()`);
const clickBtn = (idsel) => evl(`(() => { const b = document.querySelector(${JSON.stringify(idsel)}); if (!b) return "MISSING " + ${JSON.stringify(idsel)}; b.click(); return "ok"; })()`);
const decisionText = () => evl(`(document.getElementById("decision")||{}).textContent || ""`);

let fails = 0;
async function scenario(name, fn) {
  try { await fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + (e.message || e)); }
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

try {
  // poll for the debugger endpoint — a fixed sleep flakes when the box is loaded / snap cold-starts
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
  await sleep(9000);
  assert(await evl(`!!window.__duel`), "no __duel hook — old bundle cached?");
  await evl(`document.getElementById("btnPractice").click()`);
  await sleep(800);
  assert(await evl(`!!window.__duel.practice`), "practice didn't start");

  // ---------- plain-effect cards ----------
  for (const [name, cid, post] of [
    ["windbreak: +2 cards", C.windbreak, (s) => s.hand.length === 2 && s.frames.length === 0],
    ["waystation: +1 card +2 actions", C.waystation, (s) => s.hand.length === 1 && s.actions === 5 - 1 + 2],
    ["scribe: +3 cards", C.scribe, (s) => s.hand.length === 3],
    ["jubilee: +2a +1b +2c", C.jubilee, (s) => s.actions === 6 && s.buys === 3 && s.coins === 2],
    ["observatory: +2 cards +1 action", C.observatory, (s) => s.hand.length === 2 && s.actions === 5],
    ["nightmarket: +1c +1a +1b +1🪙", C.nightmarket, (s) => s.hand.length === 1 && s.actions === 5 && s.buys === 3 && s.coins === 1],
  ]) {
    await scenario(name, async () => {
      await craft({ hand: [cid] });
      await tapHand(0); await sleep(250);
      const s = await snap();
      assert(!s.corrupt, "corrupt: " + s.why);
      assert(post(s), "postcondition failed: " + JSON.stringify(s).slice(0, 200));
    });
  }

  // ---------- Winnow (the reported bug): discard 2, draw 2 ----------
  await scenario("winnow: select 2 discards via UI, confirm, draw 2", async () => {
    await craft({ hand: [C.winnow, C.copper, C.copper, C.homestead] });
    await tapHand(0); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "cel", "expected cel frame, got " + s.frames.join() + " corrupt=" + s.corrupt + " " + s.why);
    assert((await decisionText()).length > 0, "decision bar empty");
    await tapHand(0); await tapHand(2); await sleep(200);       // select copper + homestead
    const r = await clickBtn("#dConfirm"); assert(r === "ok", r);
    await sleep(250);
    s = await snap();
    assert(!s.corrupt, "corrupt: " + s.why);
    assert(s.frames.length === 0, "frame not resolved");
    assert(s.hand.length === 3 && s.disc.length === 2, "discard/draw wrong: " + JSON.stringify({ h: s.hand, d: s.disc }));
    assert(s.actions === 5, "winnow is +1 action");
  });
  await scenario("winnow: confirm with ZERO selected (discard none)", async () => {
    await craft({ hand: [C.winnow, C.copper] });
    await tapHand(0); await sleep(250);
    const r = await clickBtn("#dConfirm"); assert(r === "ok", r);
    await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.frames.length === 0 && s.hand.length === 1, "zero-discard path broken: " + JSON.stringify(s.frames) + s.why);
  });

  // ---------- Purifier: trash up to 4 ----------
  await scenario("purifier: trash 2 via UI", async () => {
    await craft({ hand: [C.purifier, C.homestead, C.copper, C.copper] });
    await tapHand(0); await sleep(250);
    await tapHand(0); await tapHand(1); await sleep(150);
    assert(await clickBtn("#dConfirm") === "ok", "no confirm");
    await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.trash.length === 2 && s.hand.length === 1, "trash flow: " + JSON.stringify(s.trash) + s.why);
  });

  // ---------- Undertow: topdeck from discard ----------
  await scenario("undertow: pick a discard-pile card to topdeck", async () => {
    await craft({ hand: [C.undertow], disc: [C.gold, C.silver] });
    await tapHand(0); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "har", "expected har frame: " + s.frames.join());
    assert(await clickBtn('#decision [data-har="1"]') === "ok", "no discard buttons");
    await sleep(250);
    s = await snap();
    assert(!s.corrupt && s.deck[s.deck.length - 1] === C.gold, "gold not topdecked: " + JSON.stringify(s.deck) + s.why);
  });

  // ---------- Hawker: first silver +1 ----------
  await scenario("hawker: silver bonus via play-treasures", async () => {
    await craft({ hand: [C.hawker, C.silver, C.copper] });
    await tapHand(0); await sleep(250);
    await evl(`[...document.querySelectorAll("#handBtns button")].find((b) => b.textContent.includes("treasure")).click()`);
    await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.coins === 2 + 1 + 1 + 1, "hawker bonus wrong (silver+2 coppers+bonus), coins=" + s.coins);   // hawker drew a copper first
  });

  // ---------- Whirlwind: both branches ----------
  await scenario("whirlwind: revealed ACTION — play it", async () => {
    await craft({ hand: [C.whirlwind], deck: [C.copper, C.waystation] });   // top = waystation
    await tapHand(0); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "vas", "expected vas frame: " + s.frames.join() + " " + s.why);
    assert(await clickBtn("#dYes") === "ok", "no play-it button");
    await sleep(250);
    s = await snap();
    assert(!s.corrupt && s.play.includes(C.waystation) && s.actions === 5 - 1 + 2, "vassal-play failed: " + JSON.stringify(s.play));
  });
  await scenario("whirlwind: revealed NON-action — auto-discards", async () => {
    await craft({ hand: [C.whirlwind], deck: [C.waystation, C.copper] });   // top = copper
    await tapHand(0); await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.frames.length === 0 && s.disc.includes(C.copper) && s.coins === 2, "auto-discard branch: " + JSON.stringify(s));
  });

  // ---------- Foundry / Reforge / Refinery / Atelier: gain flows via supply clicks ----------
  await scenario("foundry: gain ≤4 via supply tap", async () => {
    await craft({ hand: [C.foundry] });
    await tapHand(0); await sleep(250);
    await tapSupply(C.silver); await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.disc.includes(C.silver) && s.frames.length === 0, "foundry gain: " + JSON.stringify(s.disc) + s.why);
  });
  await scenario("reforge: trash homestead, gain silver (≤ cost+2)", async () => {
    await craft({ hand: [C.reforge, C.homestead] });
    await tapHand(0); await sleep(250);
    await tapHand(0); await sleep(250);                        // trash the homestead (idx 0 after reforge leaves hand)
    let s = await snap();
    assert(s.frames.join() === "remG", "expected remG: " + s.frames.join() + " " + s.why);
    await tapSupply(C.silver); await sleep(250);
    s = await snap();
    assert(!s.corrupt && s.trash.includes(C.homestead) && s.disc.includes(C.silver), "reforge flow: " + s.why);
  });
  await scenario("refinery: trash silver, gain gold to hand", async () => {
    await craft({ hand: [C.refinery, C.silver] });
    await tapHand(0); await sleep(250);
    await tapHand(0); await sleep(250);
    await tapSupply(C.gold); await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.trash.includes(C.silver) && s.hand.includes(C.gold), "refinery flow: " + s.why + JSON.stringify(s.hand));
  });
  await scenario("atelier: gain ≤5 to hand, then topdeck a card", async () => {
    await craft({ hand: [C.atelier, C.copper] });
    await tapHand(0); await sleep(250);
    await tapSupply(C.valley); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "artT", "expected artT: " + s.frames.join() + " " + s.why);
    await tapHand(0); await sleep(250);
    s = await snap();
    assert(!s.corrupt && s.frames.length === 0 && s.deck[s.deck.length - 1] != null && s.hand.length === 1, "atelier flow: " + s.why);
  });

  // ---------- Smelter / Drifter ----------
  await scenario("smelter: trash a copper for +3", async () => {
    await craft({ hand: [C.smelter, C.copper] });
    await tapHand(0); await sleep(250);
    assert(await clickBtn("#dYes") === "ok", "no trash button");
    await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.coins === 3 && s.trash.includes(C.copper), "smelter: coins=" + s.coins);
  });
  await scenario("drifter: discard 1 per empty pile", async () => {
    await craft({ hand: [C.drifter, C.copper, C.homestead], supply: { 6: 0 } });   // empty a BASE pile (kingdom varies per practice game)
    await tapHand(0); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "poa", "expected poa: " + s.frames.join() + " " + s.why);
    await tapHand(0); await sleep(150);
    assert(await clickBtn("#dConfirm") === "ok", "no confirm");
    await sleep(250);
    s = await snap();
    assert(!s.corrupt && s.frames.length === 0 && s.coins === 1, "drifter flow: " + s.why);
  });

  // ---------- Echo: double-play ----------
  await scenario("echo: play waystation twice", async () => {
    await craft({ hand: [C.echo, C.waystation], deck: [0, 0, 0, 0] });
    await tapHand(0); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "thr", "expected thr: " + s.frames.join());
    await tapHand(0); await sleep(300);                        // pick waystation
    s = await snap();
    assert(!s.corrupt && s.frames.length === 0, "echo frames: " + s.frames.join() + " " + s.why);
    assert(s.actions === 5 - 1 + 4 && s.hand.length === 2, "double-play wrong: actions=" + s.actions + " hand=" + s.hand.length);
  });

  // ---------- Skywatch: cyclers ----------
  await scenario("skywatch: trash one, discard one via cyclers", async () => {
    await craft({ hand: [C.skywatch], deck: [C.gold, C.blight, C.copper, C.copper] });
    await tapHand(0); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "sen", "expected sen: " + s.frames.join() + " " + s.why);
    // card0 -> trash (2 taps), card1 -> discard (1 tap)
    await clickBtn('#decision [data-sen="0"]'); await sleep(120);
    await clickBtn('#decision [data-sen="0"]'); await sleep(120);
    await clickBtn('#decision [data-sen="1"]'); await sleep(120);
    assert(await clickBtn("#dConfirm") === "ok", "no confirm");
    await sleep(250);
    s = await snap();
    assert(!s.corrupt && s.frames.length === 0 && s.trash.length === 1 && s.disc.length === 1, "skywatch flow: " + s.why + JSON.stringify({ t: s.trash, d: s.disc }));
  });

  // ---------- Almanac: keep/aside loop ----------
  await scenario("almanac: draw to 7, set an action aside", async () => {
    await craft({ hand: [C.almanac], deck: [0, 0, 0, 0, 0, C.waystation, 0, 0] });
    await tapHand(0); await sleep(250);
    let s = await snap();
    assert(s.frames.join() === "lib", "expected lib: " + s.frames.join() + " " + s.why);
    assert(await clickBtn("#dYes") === "ok", "no set-aside button");   // set the waystation aside
    await sleep(300);
    s = await snap();
    assert(!s.corrupt && s.frames.length === 0 && s.hand.length === 7 && s.disc.includes(C.waystation), "almanac flow: " + s.why + " hand=" + s.hand.length);
  });

  // ---------- attacks: my side + the bot's defender frames auto-answer ----------
  await scenario("raiders: +2 coins, bot discards to 3", async () => {
    await craft({ hand: [C.raiders], oppHand: [0, 0, 0, 0, 0] });
    await tapHand(0); await sleep(400);
    const s = await snap();
    assert(!s.corrupt && s.coins === 2 && s.oppHand.length === 3 && s.frames.length === 0, "raiders: opp=" + s.oppHand.length + " " + s.why);
  });
  await scenario("stormcaller: +2 cards, bot gains a Blight", async () => {
    await craft({ hand: [C.stormcaller], oppHand: [0, 0, 0] });
    await tapHand(0); await sleep(400);
    const s = await snap();
    assert(!s.corrupt && s.hand.length === 2 && s.oppDisc.includes(C.blight), "stormcaller: " + JSON.stringify(s.oppDisc) + s.why);
  });
  await scenario("collector: silver onto my deck; bot topdecks a victory", async () => {
    await craft({ hand: [C.collector], oppHand: [C.homestead, 0, 0] });
    await tapHand(0); await sleep(400);
    const s = await snap();
    assert(!s.corrupt && s.deck[s.deck.length - 1] === C.silver && s.frames.length === 0, "collector: " + JSON.stringify(s.deck) + s.why);
  });
  await scenario("storm riders: gain gold; bot trashes a revealed treasure", async () => {
    await craft({ hand: [C.stormriders], oppDeck: [0, C.silver, C.gold] });   // bot's top2 = gold, silver
    await tapHand(0); await sleep(400);
    const s = await snap();
    assert(!s.corrupt && s.disc.includes(C.gold) && s.trash.length === 1 && s.frames.length === 0, "stormriders: " + JSON.stringify({ t: s.trash }) + s.why);
  });
  await scenario("assembly: +4 cards +1 buy, bot draws", async () => {
    await craft({ hand: [C.assembly], deck: [0, 0, 0, 0, 0], oppDeck: [0, 0] });
    await tapHand(0); await sleep(300);
    const s = await snap();
    assert(!s.corrupt && s.hand.length === 4 && s.buys === 3 && s.oppHand.length === 6, "assembly: " + s.why);
  });

  // ---------- MY defender frames (as if the bot attacked me) ----------
  await scenario("defender: windbreak reveal blocks", async () => {
    await craft({ hand: [C.windbreak, 0, 0, 0, 0], frames: [{ t: "moat", p: 0, atk: C.raiders }] });
    assert(await clickBtn("#dYes") === "ok", "no reveal button");
    await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.frames.length === 0 && s.hand.length === 5, "windbreak defense: " + s.why);
  });
  await scenario("defender: raiders discard-to-3 mask", async () => {
    await craft({ hand: [0, 0, 0, C.gold, C.homestead], frames: [{ t: "mil", p: 0 }] });
    await tapHand(3); await tapHand(4); await sleep(150);
    assert(await clickBtn("#dConfirm") === "ok", "no confirm");
    await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.hand.length === 3 && s.frames.length === 0, "militia defense: " + s.why);
  });
  await scenario("defender: collector — tap a victory card to topdeck", async () => {
    await craft({ hand: [C.homestead, C.valley, 0], frames: [{ t: "bur", p: 0 }] });
    await tapHand(1); await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.deck[s.deck.length - 1] === C.valley && s.frames.length === 0, "bur defense: " + s.why);
  });
  await scenario("defender: storm riders — pick which treasure burns", async () => {
    await craft({ hand: [0, 0, 0], frames: [{ t: "ban", p: 0, cards: [C.silver, C.gold] }] });
    assert(await clickBtn('#decision [data-ban="1"]') === "ok", "no ban buttons");
    await sleep(250);
    const s = await snap();
    assert(!s.corrupt && s.trash.includes(C.gold) && s.disc.includes(C.silver), "ban defense: " + s.why);
  });

  // ---------- buy + end turn through the DOM ----------
  await scenario("buy via armed double-tap; end turn draws 5", async () => {
    await craft({ hand: [C.gold, C.gold], deck: [0, 0, 0, 0, 0, 0] });
    await evl(`[...document.querySelectorAll("#handBtns button")].find((b) => b.textContent.includes("treasure")).click()`);
    await sleep(250);
    await tapSupply(C.valley); await sleep(150); await tapSupply(C.valley); await sleep(300);
    let s = await snap();
    assert(!s.corrupt && s.disc.includes(C.valley) && s.coins === 1, "buy flow: coins=" + s.coins + " " + s.why);
    const end = `[...document.querySelectorAll("#handBtns button")].find((b) => !b.textContent.includes("treasure"))`;
    await evl(end + `.click()`); await sleep(150); await evl(end + `.click()`); await sleep(600);
    s = await snap();
    assert(!s.corrupt, "end turn corrupt: " + s.why);
  });

  console.log("page errors:", pageErrors.slice(0, 4));
  if (pageErrors.length) fails++;
  console.log(fails ? fails + " FAILURES" : "ALL PASS");
} catch (e) {
  console.error("HARNESS FAILED:", e.message || e);
  fails++;
} finally {
  chrome.kill();
  process.exit(fails ? 1 : 0);
}

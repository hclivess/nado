/*
 * test_sound_cues_are_synthesised_for_a_hit_a_charge_a_pickup_and_steps_and_open_only_after_a_gesture.mjs — #113
 * (playtest 2026-11-11: no audio code at all; a charge and a strike made no sound). static/land-sound.js on a fake
 * AudioContext, and static/land.js read as text:
 *   1. four cues — hit, charge, pickup, step — each a few oscillator notes through a gain envelope that rises in 8 ms
 *      and dies away by the note's length; the hit carries a noise click; a charge is three rising pulses;
 *   2. Sound opens its context only on enable() (the first gesture) and plays nothing before; a cue repeated within its
 *      gap is dropped; the sound setting silences it;
 *   3. the page enables it on the first click (lockPointer) and the first touch, cues a hit on `hurt`, a charge on
 *      `charge`, a pickup when an inventory count rose, a footfall every 0.35 m walked on the ground; the setting is
 *      on by default, in the Settings panel, named in 17 languages.
 * Run: node tests/test_sound_cues_are_synthesised_for_a_hit_a_charge_a_pickup_and_steps_and_open_only_after_a_gesture.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Snd = await import(join(ROOT, "static", "land-sound.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// a fake AudioContext that records what is made
class Param { constructor() { this.value = 0; this.ramps = []; } setValueAtTime(v, t) { this.ramps.push(["set", v, t]); } exponentialRampToValueAtTime(v, t) { this.ramps.push(["exp", v, t]); } }
class Node { constructor(ctx) { this.ctx = ctx; this.to = null; } connect(n) { this.to = n; return n; } }
class Osc extends Node { constructor(ctx) { super(ctx); this.type = "sine"; this.frequency = new Param(); this.started = null; this.stopped = null; } start(t) { this.started = t; } stop(t) { this.stopped = t; } }
class GainNode extends Node { constructor(ctx) { super(ctx); this.gain = new Param(); } }
class Src extends Node { constructor(ctx) { super(ctx); this.buffer = null; this.started = null; } start(t) { this.started = t; } }
class FakeCtx {
  constructor() { this.currentTime = 10; this.sampleRate = 48000; this.destination = { dest: true }; this.state = "running"; this.made = []; }
  createOscillator() { const o = new Osc(this); this.made.push(o); return o; }
  createGain() { const g = new GainNode(this); this.made.push(g); return g; }
  createBufferSource() { const s = new Src(this); this.made.push(s); return s; }
  createBuffer(ch, len, rate) { const d = new Float32Array(len); return { getChannelData: () => d, length: len }; }
}

// 1. the cues
ok(["hit", "charge", "pickup", "step"].every((k) => Snd.CUES[k] && Snd.CUES[k].notes.length >= 1), "four cues: hit, charge, pickup, step");
const ctx = new FakeCtx(), nodes = Snd.play(ctx, "charge", 1);
const oscs = nodes.filter((n) => n instanceof Osc), gains = nodes.filter((n) => n instanceof GainNode);
ok(oscs.length === 3 && oscs.every((o, i) => i === 0 || o.frequency.value > oscs[i - 1].frequency.value) && oscs.every((o, i) => i === 0 || o.started > oscs[i - 1].started), "a charge is three rising pulses, one after another");
ok(gains.every((g) => g.gain.ramps[0][0] === "set" && g.gain.ramps[1][0] === "exp" && Math.abs(g.gain.ramps[1][2] - g.gain.ramps[0][2] - 0.008) < 1e-9 && g.gain.ramps[2][1] < 0.001 && g.gain.ramps[2][2] > g.gain.ramps[1][2]), "every note rises in 8 ms and dies away by its length");
ok(oscs.every((o) => o.to instanceof GainNode && o.to.to === ctx.destination && o.stopped > o.started), "every oscillator plays through its gain into the destination and is stopped");
const hit = Snd.play(new FakeCtx(), "hit", 0.5);
ok(hit.some((n) => n instanceof Src && n.buffer && n.started === 10) && hit.filter((n) => n instanceof Osc)[0].type === "sawtooth", "the hit is a saw with a noise click");
ok(Snd.play(new FakeCtx(), "nothing").length === 0 && Snd.play(null, "hit").length === 0, "an unknown cue, or no context, plays nothing");

// 2. the gesture, the gap, the setting
let on = true;
const s = new Snd.Sound(() => on, FakeCtx);
ok(s.ctx === null && s.cue("hit") === false, "before enable() there is no context and a cue plays nothing");
s.enable();
ok(s.ctx instanceof FakeCtx && s.cue("hit") === true && s.ctx.made.length > 0, "enable() opens the context (the first gesture) and a cue plays");
ok(s.cue("hit", 1, 60) === false, "the same cue within its gap is dropped");
on = false;
ok(s.cue("pickup") === false, "the sound setting off silences it");
on = true;
const none = new Snd.Sound(() => true, undefined); none.enable();
ok(none.ctx === null && none.cue("hit") === false, "a browser without AudioContext plays nothing and throws nothing");

// 3. the page
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
ok(/import \{ Sound \} from "\.\/land-sound\.js";/.test(land) && /const sound = new Sound\(\(\) => !!SET\.sound\);/.test(land), "the page makes one Sound bound to the setting");
ok(/function lockPointer\(\) \{\n  sound\.enable\(\);/.test(land) && /document\.addEventListener\("touchstart", \(\) => sound\.enable\(\), \{ once: true, passive: true \}\);/.test(land), "it is enabled on the first click and the first touch");
ok(/setTimeout\(\(\) => f\.classList\.remove\("on"\), 120\);\n      sound\.cue\("hit"\);/.test(land) && /m\.t === "charge"\) \{\n      sound\.cue\("charge", 1, 1500\);/.test(land), "a hit cues on `hurt`, a charge on `charge`");
ok(/some\(\(\[k, n\]\) => n > \(inv\.items\[k\] \|\| 0\)\)\) sound\.cue\("pickup", 1, 150\);/.test(land), "a pickup cues when an inventory count rose");
ok(/if \(P\.ground && !P\.fly\) \{ stepDist \+= Math\.hypot\(P\.vu \|\| 0, P\.vv \|\| 0\) \* dt; if \(stepDist >= 0\.35\) \{ stepDist = 0; sound\.cue\("step", 0\.8, 120\); \} \} else stepDist = 0;/.test(land), "a footfall every 0.35 m walked on the ground, none in the air or in flight");
ok(/sound: 1 \}/.test(land.slice(land.indexOf("const SET_DEF"), land.indexOf("const SET_DEF") + 300)) && /sound: \[0, 1\]/.test(land) && /sel\("sound", T\("gSound"/.test(land), "the setting is on by default, bounded, and in the Settings panel");
ok(Object.keys(I).length === 17 && Object.keys(I).every((l) => typeof I[l]["land.gSound"] === "string" && I[l]["land.gSound"].length > 3), "the setting's label is in all 17 languages");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);

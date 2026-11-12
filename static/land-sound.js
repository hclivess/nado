// land-sound.js — SOUND CUES, SYNTHESISED (#113, playtest 2026-11-11: "the game is completely silent — an animal's charge
// and strike make no sound, so with a panel open the first a player knows of a stag is the death card"). No sound
// files: every cue is a few oscillators through a gain envelope, made on an AudioContext the browser lets us open only
// after the player's first click or key (land.js lockPointer / the touch wiring call enable()). Four cues:
//   hit     — a short low saw with a click: you were struck
//   charge  — three rising pulses: something is coming at you (the "A deer is charging you!" moment)
//   pickup  — two quick rising blips: something went into the bag
//   step    — a soft thud: a footfall on the ground, every half gait cycle
// Pure: no DOM; the test builds the cues on a fake context and reads the envelopes back.
export const CUES = {
  hit: { wave: "sawtooth", notes: [[140, 0.0, 0.11]], gain: 0.5, click: true },
  charge: { wave: "square", notes: [[220, 0.0, 0.09], [277, 0.14, 0.09], [330, 0.28, 0.12]], gain: 0.22 },
  pickup: { wave: "sine", notes: [[660, 0.0, 0.06], [990, 0.07, 0.08]], gain: 0.18 },
  step: { wave: "triangle", notes: [[70, 0.0, 0.045]], gain: 0.12 },
};
/** Play cue `name` on `ctx` at `at` seconds (ctx.currentTime by default), scaled by `vol` 0..1. Returns the nodes made. */
export function play(ctx, name, vol = 1, at = null) {
  const c = CUES[name];
  if (!c || !ctx) return [];
  const t0 = at == null ? ctx.currentTime : at, made = [];
  for (const [hz, dt, len] of c.notes) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = c.wave; o.frequency.value = hz;
    g.gain.setValueAtTime(0.0001, t0 + dt);
    g.gain.exponentialRampToValueAtTime(c.gain * vol, t0 + dt + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + len);
    o.connect(g); g.connect(ctx.destination);
    o.start(t0 + dt); o.stop(t0 + dt + len + 0.02);
    made.push(o, g);
  }
  if (c.click) {                                            // the strike's click: a burst of noise
    const n = ctx.createBufferSource(), buf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 0.03), ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / d.length);
    const g = ctx.createGain(); g.gain.value = 0.3 * vol;
    n.buffer = buf; n.connect(g); g.connect(ctx.destination); n.start(t0); made.push(n, g);
  }
  return made;
}
/** The page's sound: enable() on the first gesture (the context cannot open before one), cue() afterwards, silenced by
 *  `on()` false (the sound setting). A cue repeated within `gap` ms is dropped (a strike a frame does not stutter). */
export class Sound {
  constructor(on, Ctx = globalThis.AudioContext || globalThis.webkitAudioContext) {
    this.on = on; this.Ctx = Ctx; this.ctx = null; this.last = {};
  }
  enable() {
    if (this.ctx || !this.Ctx) return;
    try { this.ctx = new this.Ctx(); } catch (e) { this.ctx = null; }
    if (this.ctx && this.ctx.state === "suspended" && this.ctx.resume) this.ctx.resume().catch(() => {});
  }
  cue(name, vol = 1, gap = 60) {
    if (!this.ctx || !this.on()) return false;
    const now = performance.now();
    if (now - (this.last[name] || -1e9) < gap) return false;
    this.last[name] = now;
    play(this.ctx, name, vol);
    return true;
  }
}

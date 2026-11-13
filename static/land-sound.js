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
// THE WIND (#113: "ambience sounds in general"; the X fighter had no rush of air at speed): a bed of noise through a
// low-pass filter, looped, always there once the context opens — a breath on the ground, more in the open high up, a
// roar at a craft's speed. windLevel gives its level 0..1 from the height over the ground (m) and the speed (m/s); the
// filter opens with it (a gale is bright, a breeze dull). Synthesised: no sound file to choose.
export const WIND = { base: 0.04, high: 0.12, highAt: 80, fast: 0.84, fastAt: 150, gain: 0.22, hz0: 250, hz1: 3000 };
export function windLevel(above, speed) {
  const h = Math.min(1, Math.max(0, above) / WIND.highAt), v = Math.min(1, Math.max(0, speed) / WIND.fastAt);
  return Math.min(1, WIND.base + WIND.high * h + WIND.fast * v ** 1.5);
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
  /** The wind at `level` (windLevel), eased over a fifth of a second; silent with the setting off. Built on first use. */
  wind(level) {
    if (!this.ctx || !this.ctx.createBiquadFilter) return false;
    const c = this.ctx, lv = this.on() ? Math.max(0, Math.min(1, level)) : 0;
    if (!this.windG) {
      const n = Math.floor(c.sampleRate * 2), buf = c.createBuffer(1, n, c.sampleRate), d = buf.getChannelData(0);
      let b = 0; for (let i = 0; i < n; i++) { b = 0.97 * b + 0.03 * (Math.random() * 2 - 1); d[i] = b * 4; }   // a brown-ish noise: the low rumble of air
      const src = c.createBufferSource(); src.buffer = buf; src.loop = true;
      this.windF = c.createBiquadFilter(); this.windF.type = "lowpass"; this.windF.frequency.value = WIND.hz0;
      this.windG = c.createGain(); this.windG.gain.value = 0;
      src.connect(this.windF); this.windF.connect(this.windG); this.windG.connect(c.destination); src.start();
    }
    this.windG.gain.setTargetAtTime(WIND.gain * lv, c.currentTime, 0.2);
    this.windF.frequency.setTargetAtTime(WIND.hz0 + (WIND.hz1 - WIND.hz0) * lv ** 0.8, c.currentTime, 0.2);
    return true;
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

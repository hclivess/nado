// autogame-audio.js — a self-contained chiptune engine. No files (the artifact CSP + the game's own
// same-origin policy forbid external audio anyway); everything is synthesised with WebAudio, so it ships
// as pure code. Off by default and started only on a real user gesture (autoplay policy), with a mute
// toggle persisted in localStorage ("nado_autogame_sound").
//
// v2 — higher fidelity + variation:
//  • lookahead scheduler: a 100 ms setInterval schedules ~0.3 s ahead on ctx.currentTime, so tempo never
//    jitters with the event loop (the old version fired notes at interval time).
//  • richer voices: the lead is a detuned oscillator PAIR (a few cents apart), the bass carries a
//    sub-octave sine, the master runs through a gentle lowpass + compressor, and a low-mixed feedback
//    delay (~0.28 s, fb 0.25) gives the whole thing space. Velocity + timing are humanised per note.
//  • percussion: kick (sine pitch-drop) on downbeats, snare (bandpass noise) on backbeats, closed hat
//    (short hipass noise) on eighths — subtle under the march, driving under the boss.
//  • structure: each theme has TWO 16-bar sections (A/B) shuffled deterministically by a hash of the
//    elapsed-section counter (no jump-cuts), a snare-fill bar every 8 bars with a crash after, occasional
//    rest bars for breathing, and occasional octave-up echoes of the lead phrase.
//  • screams: synthesised monster death screams (3 variants — pitch-diving saw + vibrato + formant
//    bandpass sweep + breath noise), a longer darker hero dying scream (wired into "death"), and a
//    waveshaper-distorted boss roar fired on setBoss(true).

const A4 = 440;
const NOTE = (n) => A4 * Math.pow(2, (n - 69) / 12);           // MIDI note number → Hz
const LS = "nado_autogame_sound";
const rnd = Math.random;
// deterministic 32-bit hash — structure decisions (sections/fills/rests) come from this, not Math.random,
// so the arrangement is stable per elapsed-bar counter and never jump-cuts.
function h32(n) {
  n = ((n | 0) + 0x9e3779b9) | 0;
  n = Math.imul(n ^ (n >>> 16), 0x21f0aaad);
  n = Math.imul(n ^ (n >>> 15), 0x735a2d97);
  return (n ^ (n >>> 15)) >>> 0;
}

export function createAudio() {
  let ctx = null, master = null, musicGain = null, delaySend = null, on = false, timer = null;

  function ensure() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return false;
      ctx = new AC();
      // master chain: master(fade) → gentle lowpass → soft compressor → out. The compressor is a safety
      // net against stacked one-shots clipping; the lowpass takes the digital edge off the squares.
      let out = ctx.destination;
      try {
        const cp = ctx.createDynamicsCompressor();
        cp.threshold.value = -14; cp.knee.value = 22; cp.ratio.value = 5;
        cp.attack.value = 0.004; cp.release.value = 0.18;
        cp.connect(ctx.destination); out = cp;
      } catch (e) {}
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass"; lp.frequency.value = 11000; lp.Q.value = 0.5; lp.connect(out);
      master = ctx.createGain(); master.gain.value = 0; master.connect(lp);
      musicGain = ctx.createGain(); musicGain.gain.value = 0.15; musicGain.connect(master);
      // feedback delay send — notes tap into delaySend; the wet return sits low under the music bus.
      delaySend = ctx.createGain(); delaySend.gain.value = 1;
      const dly = ctx.createDelay(1.0); dly.delayTime.value = 0.28;
      const damp = ctx.createBiquadFilter(); damp.type = "lowpass"; damp.frequency.value = 2400;
      const fb = ctx.createGain(); fb.gain.value = 0.25;
      delaySend.connect(dly); dly.connect(damp); damp.connect(fb); fb.connect(dly);
      const wet = ctx.createGain(); wet.gain.value = 0.5;
      dly.connect(wet); wet.connect(musicGain);
    }
    if (ctx.state === "suspended") ctx.resume();
    return true;
  }

  // ── voices ───────────────────────────────────────────────────────────────────────────────────────
  // one enveloped oscillator — returns the osc so callers can ramp its frequency
  function voice(freq, t0, dur, type, peak, dest) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(peak, t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g); g.connect(dest || master);
    o.start(t0); o.stop(t0 + dur + 0.02);
    return o;
  }
  // detuned pair — the "fat" lead. Two oscillators a few cents apart into one envelope, with an
  // optional tap into the delay send for space.
  function duo(freq, t0, dur, type, peak, dest, det, send) {
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(peak * 0.62, t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    const d = det == null ? 5 : det;
    for (const dt of [d, -d]) {
      const o = ctx.createOscillator();
      o.type = type; o.frequency.setValueAtTime(freq, t0);
      o.detune.value = dt + (rnd() - 0.5) * 2;
      o.connect(g); o.start(t0); o.stop(t0 + dur + 0.02);
    }
    g.connect(dest || master);
    if (send && delaySend) { const sg = ctx.createGain(); sg.gain.value = send; g.connect(sg); sg.connect(delaySend); }
    return g;
  }
  // a filtered noise burst from one shared buffer (random read offset = free variation).
  // filt: number = lowpass cutoff, or { type, freq, to?, q? } for a swept/shaped band.
  let nbuf = null;
  function noise(t0, dur, peak, filt, dest) {
    if (!nbuf) {
      const n = Math.floor(ctx.sampleRate * 2);   // 2s: max read offset 0.8 + longest tail 1.0 still fits
      nbuf = ctx.createBuffer(1, n, ctx.sampleRate);
      const d = nbuf.getChannelData(0);
      let s = 0x2545f491;
      for (let i = 0; i < n; i++) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; d[i] = ((s >>> 0) / 4294967295) * 2 - 1; }
    }
    const src = ctx.createBufferSource(); src.buffer = nbuf;
    const f = ctx.createBiquadFilter();
    if (typeof filt === "number" || !filt) {
      f.type = "lowpass"; f.frequency.setValueAtTime(filt || 1800, t0);
    } else {
      f.type = filt.type || "lowpass"; f.frequency.setValueAtTime(filt.freq, t0);
      if (filt.to) f.frequency.exponentialRampToValueAtTime(filt.to, t0 + dur);
      if (filt.q) f.Q.value = filt.q;
    }
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(peak, t0 + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    src.connect(f); f.connect(g); g.connect(dest || master);
    src.start(t0, rnd() * 0.8); src.stop(t0 + dur + 0.02);
  }
  // impact body — a sine that drops in pitch (kick / thud)
  function thud(t0, v, f0, f1, dest) {
    const o = ctx.createOscillator(); o.type = "sine";
    o.frequency.setValueAtTime(f0, t0);
    o.frequency.exponentialRampToValueAtTime(f1, t0 + 0.09);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(v, t0 + 0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.18);
    o.connect(g); g.connect(dest || master);
    o.start(t0); o.stop(t0 + 0.22);
  }

  // ── percussion (music bus) ───────────────────────────────────────────────────────────────────────
  function kick(t0, v)  { thud(t0, v, 150, 42, musicGain); }
  function snare(t0, v) {
    noise(t0, 0.13, v, { type: "bandpass", freq: 1850, q: 0.8 }, musicGain);
    voice(185, t0, 0.06, "triangle", v * 0.5, musicGain);
  }
  function hat(t0, v)   { noise(t0, 0.032, v, { type: "highpass", freq: 6800 }, musicGain); }
  function bassN(freq, t0, dur, type, peak) {
    voice(freq, t0, dur, type, peak, musicGain);
    voice(freq / 2, t0, dur * 0.9, "sine", peak * 0.55, musicGain);   // sub-octave under the bass
  }

  // ── screams ──────────────────────────────────────────────────────────────────────────────────────
  // pitch-diving sawtooth + vibrato + a formant-ish bandpass sweeping down + breath noise.
  function screamCore(t0, p) {
    const f = ctx.createBiquadFilter();
    f.type = "bandpass"; f.Q.value = p.q;
    f.frequency.setValueAtTime(p.bp0, t0);
    f.frequency.exponentialRampToValueAtTime(p.bp1, t0 + p.dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(p.peak, t0 + 0.025);
    g.gain.linearRampToValueAtTime(p.peak * 0.8, t0 + p.dur * 0.55);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + p.dur);
    f.connect(g); g.connect(master);
    if (delaySend) { const sg = ctx.createGain(); sg.gain.value = 0.3; g.connect(sg); sg.connect(delaySend); }
    const lfo = ctx.createOscillator(); lfo.type = "sine"; lfo.frequency.value = p.vibHz;
    const lg = ctx.createGain(); lg.gain.value = p.vibDepth; lfo.connect(lg);
    for (const fm of p.sub ? [1, 0.5] : [1]) {
      const o = ctx.createOscillator(); o.type = "sawtooth";
      o.frequency.setValueAtTime(p.f0 * fm, t0);
      o.frequency.linearRampToValueAtTime(p.f0 * fm * 1.13, t0 + p.dur * 0.16);       // the upward jerk
      o.frequency.exponentialRampToValueAtTime(Math.max(30, p.f1 * fm), t0 + p.dur);  // the dive
      lg.connect(o.frequency);
      o.connect(f); o.start(t0); o.stop(t0 + p.dur + 0.05);
    }
    lfo.start(t0); lfo.stop(t0 + p.dur + 0.05);
    noise(t0 + 0.01, p.dur * 0.8, p.peak * 0.35, { type: "bandpass", freq: p.bp0, to: p.bp1 * 0.9, q: 1.2 }, master);
  }
  const SCREAMS = [   // 3 monster variants so kills never sound identical
    { f0: 760, f1: 130, dur: 0.55, vibHz: 33, vibDepth: 42, bp0: 1500, bp1: 480, q: 4,   peak: 0.26 },
    { f0: 620, f1: 100, dur: 0.68, vibHz: 26, vibDepth: 55, bp0: 1250, bp1: 380, q: 5,   peak: 0.24 },
    { f0: 880, f1: 170, dur: 0.45, vibHz: 40, vibDepth: 34, bp0: 1750, bp1: 600, q: 3.5, peak: 0.25 },
  ];
  function monsterScreamAt(t0) { screamCore(t0, SCREAMS[(rnd() * SCREAMS.length) | 0]); }
  function heroScreamAt(t0) {   // longer, darker, with a sub-octave and a final fall
    screamCore(t0, { f0: 430, f1: 66, dur: 1.25, vibHz: 7, vibDepth: 26, bp0: 1050, bp1: 260, q: 5, peak: 0.30, sub: true });
    noise(t0 + 0.05, 0.9, 0.14, 700, master);
    thud(t0 + 1.0, 0.28, 120, 40, master);
  }
  function bossRoarAt(t0) {     // low, long, waveshaper-distorted
    const dur = 1.35;
    const sh = ctx.createWaveShaper();
    const cn = 1024, curve = new Float32Array(cn);
    for (let i = 0; i < cn; i++) { const x = (i / (cn - 1)) * 2 - 1; curve[i] = Math.tanh(3 * x); }
    sh.curve = curve;
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 760; lp.Q.value = 0.7;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(0.30, t0 + 0.06);
    g.gain.linearRampToValueAtTime(0.24, t0 + dur * 0.6);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    sh.connect(lp); lp.connect(g); g.connect(master);
    if (delaySend) { const sg = ctx.createGain(); sg.gain.value = 0.25; g.connect(sg); sg.connect(delaySend); }
    const pre = ctx.createGain(); pre.gain.value = 0.9; pre.connect(sh);
    const lfo = ctx.createOscillator(); lfo.type = "sine"; lfo.frequency.value = 4.5;
    const lg = ctx.createGain(); lg.gain.value = 7; lfo.connect(lg);
    for (const [fq, tp] of [[60, "sawtooth"], [89, "sawtooth"], [33, "square"]]) {
      const o = ctx.createOscillator(); o.type = tp;
      o.frequency.setValueAtTime(fq, t0);
      o.frequency.linearRampToValueAtTime(fq * 0.76, t0 + dur);
      lg.connect(o.frequency);
      o.connect(pre); o.start(t0); o.stop(t0 + dur + 0.05);
    }
    lfo.start(t0); lfo.stop(t0 + dur + 0.05);
    for (let i = 0; i < 10; i++)   // pulsed growl grit over the tone
      noise(t0 + i * 0.11, 0.09, 0.07 * (1 - i / 12), { type: "bandpass", freq: 300 + i * 15, q: 1.2 }, master);
  }

  // ── two THEMES, each with two 16-bar sections. A bar is { b: bassMIDI, c: [chord…],
  //   l: [4 eighth-note lead slots, 0 = rest] }. MARCH is a heroic A-minor line through a real
  //   progression; BOSS is faster, lower, chromatic.
  let boss = false;
  const AM = [57, 60, 64], F = [53, 57, 60], C = [48, 52, 55], G = [55, 59, 62],
        DM = [50, 53, 57], E = [52, 56, 59];
  const marchA = [
    { b: 45, c: AM, l: [69, 72, 76, 72] }, { b: 45, c: AM, l: [71, 69, 67, 69] },
    { b: 41, c: F,  l: [72, 76, 77, 76] }, { b: 41, c: F,  l: [74, 72, 69, 72] },
    { b: 48, c: C,  l: [76, 79, 76, 72] }, { b: 48, c: C,  l: [74, 72, 71, 67] },
    { b: 43, c: G,  l: [67, 71, 74, 71] }, { b: 43, c: G,  l: [72, 71, 69, 62] },
    { b: 50, c: DM, l: [69, 74, 77, 74] }, { b: 50, c: DM, l: [72, 69, 65, 69] },
    { b: 40, c: E,  l: [64, 68, 71, 68] }, { b: 40, c: E,  l: [72, 71, 68, 64] },
    { b: 45, c: AM, l: [69, 72, 76, 81] }, { b: 41, c: F,  l: [80, 76, 72, 69] },
    { b: 43, c: G,  l: [67, 71, 74, 79] }, { b: 40, c: E,  l: [71, 68, 64, 0] },
  ];
  const marchB = [ // the answer phrase — higher register, leans on the relative major before falling home
    { b: 45, c: AM, l: [76, 74, 72, 74] }, { b: 45, c: AM, l: [76, 79, 81, 79] },
    { b: 43, c: G,  l: [79, 78, 76, 74] }, { b: 43, c: G,  l: [71, 74, 79, 74] },
    { b: 41, c: F,  l: [77, 76, 74, 72] }, { b: 41, c: F,  l: [69, 72, 77, 72] },
    { b: 40, c: E,  l: [68, 71, 76, 71] }, { b: 40, c: E,  l: [76, 74, 71, 68] },
    { b: 45, c: AM, l: [81, 0, 79, 76] },  { b: 48, c: C,  l: [79, 76, 72, 76] },
    { b: 50, c: DM, l: [77, 74, 69, 74] }, { b: 43, c: G,  l: [74, 71, 67, 71] },
    { b: 41, c: F,  l: [72, 74, 76, 77] }, { b: 40, c: E,  l: [76, 74, 71, 68] },
    { b: 45, c: AM, l: [69, 72, 76, 72] }, { b: 40, c: E,  l: [64, 68, 71, 0] },
  ];
  const bossA = [ // low pedal dread, tritone colour, a prowling chromatic lead
    { b: 33, c: [57, 60, 63], l: [69, 68, 69, 72] }, { b: 33, c: [57, 60, 63], l: [71, 69, 68, 65] },
    { b: 34, c: [56, 59, 62], l: [68, 71, 74, 71] }, { b: 34, c: [56, 59, 62], l: [70, 68, 65, 62] },
    { b: 33, c: [57, 60, 63], l: [69, 72, 75, 72] }, { b: 33, c: [57, 60, 63], l: [74, 71, 68, 69] },
    { b: 32, c: [55, 58, 61], l: [64, 67, 70, 67] }, { b: 32, c: [55, 58, 61], l: [66, 64, 61, 0] },
    { b: 33, c: [57, 60, 63], l: [81, 80, 77, 75] }, { b: 33, c: [57, 60, 63], l: [74, 72, 69, 68] },
    { b: 36, c: [60, 63, 66], l: [72, 75, 78, 75] }, { b: 36, c: [60, 63, 66], l: [74, 71, 68, 65] },
    { b: 32, c: [55, 58, 61], l: [64, 68, 71, 74] }, { b: 31, c: [55, 58, 62], l: [73, 70, 67, 64] },
    { b: 33, c: [57, 60, 63], l: [69, 68, 69, 68] }, { b: 33, c: [57, 60, 63], l: [67, 64, 60, 0] },
  ];
  const bossB = [ // the low prowl — the lead drops into the pedal register, then claws back up
    { b: 33, c: [57, 60, 63], l: [57, 60, 63, 60] }, { b: 33, c: [57, 60, 63], l: [64, 63, 60, 57] },
    { b: 31, c: [55, 58, 61], l: [55, 58, 61, 64] }, { b: 31, c: [55, 58, 61], l: [62, 61, 58, 55] },
    { b: 34, c: [58, 61, 64], l: [58, 61, 64, 67] }, { b: 34, c: [58, 61, 64], l: [66, 64, 61, 58] },
    { b: 33, c: [57, 60, 63], l: [69, 68, 66, 63] }, { b: 32, c: [56, 59, 62], l: [62, 59, 56, 0] },
    { b: 33, c: [57, 60, 63], l: [75, 74, 72, 69] }, { b: 33, c: [57, 60, 63], l: [68, 69, 72, 74] },
    { b: 35, c: [59, 62, 65], l: [71, 74, 77, 74] }, { b: 35, c: [59, 62, 65], l: [72, 69, 66, 62] },
    { b: 32, c: [56, 59, 62], l: [68, 67, 64, 62] }, { b: 31, c: [55, 58, 61], l: [61, 58, 55, 58] },
    { b: 33, c: [57, 60, 63], l: [63, 64, 68, 69] }, { b: 33, c: [57, 60, 63], l: [72, 69, 63, 0] },
  ];
  const THEMES = {
    march: { A: marchA, B: marchB, spb: 0.205, leadType: "square",   bassType: "triangle", drive: false, seed: 11 },
    boss:  { A: bossA,  B: bossB,  spb: 0.150, leadType: "sawtooth", bassType: "square",   drive: true,  seed: 47 },
  };
  function sectionFor(th, si) {   // deterministic loose shuffle of A/B per 16-bar section
    if (si === 0) return th.A;
    let useB = (si & 1) === 1;
    if (h32(si + th.seed) % 5 === 0) useB = !useB;
    return useB ? th.B : th.A;
  }

  // ── lookahead scheduler ──────────────────────────────────────────────────────────────────────────
  let barIdx = 0, stepIdx = 0, nextTime = 0;
  const LOOKAHEAD = 0.3, TICK_MS = 100;

  function scheduleStep(t, th) {
    const sec = sectionFor(th, barIdx >> 4);
    const m = sec[barIdx & 15];
    const spb = th.spb, dr = th.drive;
    const fill = (barIdx & 7) === 7;                                        // every 8th bar: snare fill
    const rest = !fill && (barIdx & 15) !== 0 && h32(barIdx * 3 + th.seed) % 11 === 7;   // breathing bar
    const echo = !rest && !fill && h32(barIdx * 5 + th.seed + 1) % 4 === 0; // octave-up echo bar
    const vj = () => 0.85 + rnd() * 0.2;                                    // humanise velocity…
    const tj = () => t + (rnd() - 0.5) * 0.008;                             // …and timing (audio-only)

    // percussion
    if (stepIdx === 0) kick(tj(), (dr ? 0.5 : 0.42) * vj());
    if (dr && stepIdx === 2) kick(tj(), 0.34 * vj());
    if (fill) {                                                              // 16th-note snare build
      snare(tj(), (0.10 + stepIdx * 0.05) * vj());
      snare(t + spb * 0.5, (0.13 + stepIdx * 0.05) * vj());
    } else if (stepIdx === 2) snare(tj(), (dr ? 0.30 : 0.20) * vj());
    hat(tj(), (stepIdx & 1 ? 0.055 : 0.085) * (dr ? 1.5 : 1) * vj());
    if (stepIdx === 0 && barIdx > 0 && (barIdx & 7) === 0)                   // crash out of the fill
      noise(t, 0.45, 0.08, { type: "highpass", freq: 5000 }, musicGain);

    // bass + sub
    if (stepIdx === 0) bassN(NOTE(m.b), t, dr ? 0.30 : 0.46, th.bassType, (dr ? 0.55 : 0.48) * vj());
    if (dr && (stepIdx & 1)) voice(NOTE(m.b), tj(), 0.12, "square", 0.18 * vj(), musicGain); // boss 8th pulse

    // chords
    if (!rest) {
      if (stepIdx === 0) for (const c of m.c) voice(NOTE(c), t, 0.22, "square", (dr ? 0.07 : 0.055) * vj(), musicGain);
      else if (stepIdx === 2 && !fill) for (const c of m.c) voice(NOTE(c), t, 0.18, "square", 0.045 * vj(), musicGain);
    }

    // lead (detuned pair + delay send); rests during fills and breathing bars
    if (!rest && !fill) {
      const ln = m.l[stepIdx];
      if (ln) {
        const pk = (dr ? 0.105 : 0.085) * vj();
        duo(NOTE(ln), tj(), stepIdx === 3 ? 0.26 : 0.18, th.leadType, pk, musicGain, 5, 0.5);
        if (echo) duo(NOTE(ln + 12), t + spb * 0.55, 0.12, th.leadType, pk * 0.4, musicGain, 5, 0.7);
      }
    }
  }
  function tick() {
    if (!ctx || !on) return;
    if (nextTime < ctx.currentTime) nextTime = ctx.currentTime + 0.02;   // resumed after a stall: don't machine-gun
    while (nextTime < ctx.currentTime + LOOKAHEAD) {
      const th = THEMES[boss ? "boss" : "march"];
      try { scheduleStep(nextTime, th); } catch (e) {}
      nextTime += th.spb;
      stepIdx = (stepIdx + 1) & 3;
      if (stepIdx === 0) barIdx++;
    }
  }
  function startMusic() {
    if (timer) return;
    barIdx = 0; stepIdx = 0; nextTime = ctx.currentTime + 0.05;
    timer = setInterval(tick, TICK_MS);
  }
  function stopMusic() { if (timer) { clearInterval(timer); timer = null; } }
  function setBoss(v) {
    if (boss === !!v) return;
    boss = !!v; barIdx = 0; stepIdx = 0;
    if (v && on && ctx) { try { bossRoarAt(ctx.currentTime); } catch (e) {} }
  }

  // ── one-shot SFX ─────────────────────────────────────────────────────────────────────────────────
  const SFX = {
    swing() {                                        // whoosh: swept bandpass noise + rising saw
      const t = ctx.currentTime;
      noise(t, 0.16, 0.20, { type: "bandpass", freq: 700, to: 3200, q: 1.1 });
      const o = voice(340, t, 0.12, "sawtooth", 0.045);
      o.frequency.exponentialRampToValueAtTime(900, t + 0.12);
    },
    hit() {                                          // thud + crunch + snap
      const t = ctx.currentTime;
      thud(t, 0.30, 170, 55);
      noise(t, 0.09, 0.30, 1100);
      noise(t, 0.05, 0.16, { type: "bandpass", freq: 2400, q: 1.5 });
    },
    kill() {                                         // impact + a monster death scream
      const t = ctx.currentTime;
      thud(t, 0.34, 200, 60);
      noise(t, 0.18, 0.32, 1500);
      monsterScreamAt(t + 0.03);
    },
    hurt() {                                         // grunt: falling saw + throaty band + body
      const t = ctx.currentTime;
      const o = voice(270, t, 0.20, "sawtooth", 0.17);
      o.frequency.exponentialRampToValueAtTime(150, t + 0.20);
      noise(t, 0.10, 0.14, { type: "bandpass", freq: 640, q: 1.3 });
      thud(t, 0.12, 140, 70);
    },
    heal() {
      const t = ctx.currentTime;
      [60, 64, 67, 72].forEach((n, i) => duo(NOTE(n), t + i * 0.05, 0.24, "triangle", 0.13, master, 3, 0.6));
      voice(NOTE(84), t + 0.2, 0.3, "sine", 0.05);
    },
    rally() {
      const t = ctx.currentTime;
      [67, 71, 74, 79].forEach((n, i) => duo(NOTE(n), t + i * 0.04, 0.26, "square", 0.11, master, 4, 0.5));
      thud(t, 0.2, 140, 60);
    },
    guard() {                                        // metallic ring: inharmonic bell partials + tick
      const t = ctx.currentTime, f0 = 740;
      [[1, 0.10, 0.30], [2.76, 0.066, 0.22], [5.40, 0.05, 0.15], [8.93, 0.034, 0.10]]
        .forEach(([r, p, d]) => voice(f0 * r, t, d, "sine", p * (0.9 + rnd() * 0.2)));
      noise(t, 0.04, 0.12, { type: "highpass", freq: 5200 });
    },
    dodge() {
      const t = ctx.currentTime;
      const o = voice(950, t, 0.16, "sine", 0.09);
      o.frequency.exponentialRampToValueAtTime(280, t + 0.16);
      noise(t, 0.12, 0.10, { type: "highpass", freq: 2500, to: 900 });
    },
    loot() {                                         // a pickup: two bright ticks and a high ring
      const t = ctx.currentTime;
      voice(NOTE(88), t, 0.07, "square", 0.10);
      voice(NOTE(93), t + 0.07, 0.16, "square", 0.09);
      voice(NOTE(100), t + 0.07, 0.22, "sine", 0.04);
    },
    coin() {                                         // renown changes hands: one dull clink
      const t = ctx.currentTime;
      voice(NOTE(81), t, 0.05, "square", 0.08);
      voice(NOTE(76), t + 0.05, 0.12, "triangle", 0.07);
      noise(t, 0.03, 0.06, { type: "highpass", freq: 6000 });
    },
    snarl() {                                        // the creature winds up: a short throaty growl
      const t = ctx.currentTime;
      const o = voice(130, t, 0.24, "sawtooth", 0.15);
      o.frequency.exponentialRampToValueAtTime(72, t + 0.24);
      noise(t, 0.2, 0.11, { type: "bandpass", freq: 420, q: 1.4 });
      thud(t + 0.02, 0.08, 90, 55);
    },
    death() {                                        // the hero dies: long dark scream + doom notes
      const t = ctx.currentTime;
      heroScreamAt(t);
      [50, 45].forEach((n, i) => voice(NOTE(n), t + 0.35 + i * 0.3, 0.5, "sawtooth", 0.10));
    },
    bank() {
      const t = ctx.currentTime;
      [72, 76, 79, 84].forEach((n, i) => duo(NOTE(n), t + i * 0.06, 0.3, "triangle", 0.14, master, 3, 0.6));
      voice(NOTE(88), t + 0.26, 0.35, "sine", 0.05);
    },
    step() { noise(ctx.currentTime, 0.04, 0.05, 380 + rnd() * 250); },
    scream()     { monsterScreamAt(ctx.currentTime); },
    heroScream() { heroScreamAt(ctx.currentTime); },
    bossRoar()   { bossRoarAt(ctx.currentTime); },
  };
  function sfx(name) { if (!on || !ensure()) return; const f = SFX[name]; if (f) try { f(); } catch (e) {} }

  function setOn(v) {
    if (!ensure()) return;
    on = v;
    try { localStorage.setItem(LS, v ? "1" : "0"); } catch (e) {}
    master.gain.cancelScheduledValues(ctx.currentTime);
    master.gain.linearRampToValueAtTime(v ? 0.85 : 0, ctx.currentTime + 0.2);
    if (v) startMusic(); else stopMusic();
  }
  function toggle() { setOn(!on); return on; }
  function isOn() { return on; }
  function wanted() { try { return localStorage.getItem(LS) === "1"; } catch (e) { return false; } }

  return { sfx, setOn, toggle, isOn, wanted, ensure, setBoss };
}

// v0.4.58 Background music: where the music plays and how it loops — the same layout as the
// export (music.py; tests/test_music.py checks both give the same answer), and the preview player.
//
// The timeline is authoritative: the music is cut to it and never changes the documentary.
// The preview streams the original file through two <audio> elements (one per alternate pass, so
// a loop can crossfade) routed through WebAudio gains: the pass envelopes, the music volume (a
// real-time gain with a short ramp — no request, no re-render) and the export's own ducking curve.

export const MUSIC_FPS = 24;
export const MUSIC_MODES = [
  { id: "whole", label: "The whole documentary" },
  { id: "range", label: "From… to… (a range)" },
  { id: "once", label: "Once, from a point" },
  { id: "scenes", label: "Chosen chapters / scenes" },
];
export const MUSIC_DEFAULTS = {
  mode: "whole", start: 0, end: null, loop: true, crossfade: 2.0, fade_in: 1.5, fade_out: 2.0, duck: true,
  offset: 0, until: null, chapters: [], scenes: [],
};
export const MUSIC_LIMITS = { crossfade: [0, 10], fade_in: [0, 15], fade_out: [0, 15] };
const MIN_PART = 1.0;
// the export's music compressor (renderer.MUSIC_DUCK): its ratio, for the immediate approximation
export const MUSIC_DUCK_RATIO = 8;

const num = (v, lo, hi, d) => {
  const x = Number(v);
  if (v === null || v === undefined || v === "" || !Number.isFinite(x)) return d;
  return Math.min(hi ?? Infinity, Math.max(lo ?? -Infinity, x));
};
const r3 = (x) => Math.round(x * 1000) / 1000;
const r4 = (x) => Math.round(x * 10000) / 10000;

export function normaliseMusic(value) {
  const v = value && typeof value === "object" ? value : {};
  const out = {
    mode: MUSIC_MODES.some((m) => m.id === v.mode) ? v.mode : MUSIC_DEFAULTS.mode,
    start: r3(num(v.start, 0, null, 0)),
    end: v.end === null || v.end === undefined || v.end === "" ? null : r3(num(v.end, 0, null, 0)),
    loop: v.loop === undefined ? true : !!v.loop,
    duck: v.duck === undefined ? true : !!v.duck,
    offset: r3(num(v.offset, 0, null, 0)),
    until: v.until === null || v.until === undefined || v.until === "" ? null : r3(num(v.until, 0, null, 0)),
    chapters: (Array.isArray(v.chapters) ? v.chapters : []).filter((c) => typeof c === "string").map((c) => c.slice(0, 200)).slice(0, 100),
    scenes: (Array.isArray(v.scenes) ? v.scenes : []).filter((s) => typeof s === "string" || typeof s === "number").map((s) => String(s).slice(0, 64)).slice(0, 400),
  };
  for (const [k, [lo, hi]] of Object.entries(MUSIC_LIMITS)) out[k] = r3(num(v[k], lo, hi, MUSIC_DEFAULTS[k]));
  if (out.end !== null && out.end <= out.start) out.end = null;
  return out;
}

/** The timeline length the export uses (each scene a whole number of frames). */
export function timelineTotal(scenes) {
  return (scenes || []).reduce((t, s) => t + Math.max(1, Math.round((+s.duration || 0) * MUSIC_FPS)) / MUSIC_FPS, 0);
}

function sceneSpans(scenes) {
  const out = [];
  let t = 0;
  for (const s of scenes || []) {
    const n = Math.max(1, Math.round((+s.duration || 0) * MUSIC_FPS));
    out.push([String(s.id ?? ""), String(s.chapter || ""), t, t + n / MUSIC_FPS]);
    t += n / MUSIC_FPS;
  }
  return out;
}

/** [start, end] of the used part of a `track`-second file. */
export function musicPart(settings, track) {
  const m = normaliseMusic(settings);
  track = +track || 0;
  if (track <= 0) return [0, 0];
  const a = Math.min(m.start, Math.max(0, track - MIN_PART));
  let b = m.end === null ? track : Math.min(track, m.end);
  if (b - a < MIN_PART) b = Math.min(track, a + MIN_PART);
  return [r4(a), r4(b)];
}

export function musicStretches(settings, total, scenes) {
  const m = normaliseMusic(settings);
  let out;
  if (m.mode === "whole") out = [[0, total]];
  else if (m.mode === "range" || m.mode === "once") {
    const a = Math.min(m.offset, total);
    const b = m.mode === "once" || m.until === null ? total : Math.min(total, m.until);
    out = b - a > 0 ? [[a, b]] : [];
  } else {
    const chosen = new Set(m.scenes), chapters = new Set(m.chapters);
    out = [];
    for (const [sid, chapter, a, b] of sceneSpans(scenes)) {
      if (chosen.has(sid) || (chapter && chapters.has(chapter))) {
        if (out.length && Math.abs(out[out.length - 1][1] - a) < 1e-6) out[out.length - 1][1] = b;
        else out.push([a, b]);
      }
    }
    out = out.filter(([a]) => a < total).map(([a, b]) => [a, Math.min(b, total)]);
  }
  return out.map(([a, b]) => [r4(a), r4(b)]).filter(([a, b]) => b - a > 1e-3);
}

/** Where the music plays: {part, crossfade, runs: [{at, end, fade_in, fade_out, iters: [{at, src, len}]}]}.
 *  Pure; the same as music.layout() in the export. */
export function musicLayout(settings, track, total, scenes = []) {
  const m = normaliseMusic(settings);
  const [a, b] = musicPart(m, track);
  const length = b - a;
  const out = { part: [a, b], crossfade: 0, runs: [] };
  if (length <= 0) return out;
  const x = r4(m.loop && m.mode !== "once" ? Math.min(m.crossfade, Math.max(0, length / 2 - 0.01)) : 0);
  out.crossfade = x;
  const period = length - x;
  for (const [s, e] of musicStretches(m, total, scenes)) {
    const span = e - s;
    const iters = [];
    if (m.mode !== "once" && m.loop && span > length + 1e-6) {
      const n = 1 + Math.ceil((span - length) / period - 1e-9);
      for (let k = 0; k < n; k++) {
        const at = s + k * period;
        iters.push({ at: r4(at), src: a, len: r4(Math.min(length, e - at)) });
      }
    } else iters.push({ at: s, src: a, len: r4(Math.min(length, span)) });
    const last = iters[iters.length - 1];
    const end = r4(last.at + last.len);
    const heard = end - s;
    out.runs.push({ at: s, end, fade_in: r4(Math.min(m.fade_in, heard / 2)), fade_out: r4(Math.min(m.fade_out, heard / 2)), iters });
  }
  return out;
}

/** The gain of pass `k` of `run` at timeline time t (its crossfades and the run's fades). */
export function passGain(lay, run, k, t) {
  const it = run.iters[k], x = lay.crossfade, u = t - it.at;
  if (!(u >= 0 && u < it.len) || !(t >= run.at && t < run.end)) return 0;
  let g = 1;
  if (run.fade_in > 0) g *= Math.min(1, (t - run.at) / run.fade_in);
  if (run.fade_out > 0) g *= Math.min(1, (run.end - t) / run.fade_out);
  if (k > 0 && x > 0 && u < x) g *= Math.sin((Math.PI / 2) * (u / x));
  if (k < run.iters.length - 1 && x > 0 && u > it.len - x) g *= Math.cos((Math.PI / 2) * ((u - (it.len - x)) / x));
  return g;
}

/** The music's envelope at t (equal power across a crossfade) — the same as music.gain_at(). */
export function musicGainAt(lay, t) {
  for (const run of lay.runs) {
    if (!(t >= run.at && t < run.end)) continue;
    let p = 0;
    run.iters.forEach((_, k) => { const g = passGain(lay, run, k, t); p += g * g; });
    return Math.sqrt(p);
  }
  return 0;
}

/** Every pass in time order: {run, k, at, src, len, i (global index: its preview element = i % 2)}. */
export function musicPasses(lay) {
  const out = [];
  for (const run of lay?.runs || []) run.iters.forEach((it, k) => out.push({ ...it, run, k, i: out.length }));
  return out;
}

/** v0.4.58 An immediate approximation of a ducking curve after the narration level changed by
 *  `ratio` (new / the level the curve was made with), until the exact one is made in the
 *  background: above the threshold a compressor's gain reduction moves by (1 - 1/r) of the
 *  change of the key level. Pure. */
export function approxDuck(curve, ratio, compRatio) {
  if (!curve || !curve.gain) return curve;
  if (Math.abs(ratio - 1) < 1e-4) return curve;
  const g = curve.gain, out = new Float32Array(g.length);
  if (ratio <= 0.001) { out.fill(1); return { ...curve, gain: out, approx: true }; }
  const shift = 20 * Math.log10(ratio) * (1 - 1 / compRatio);
  for (let i = 0; i < g.length; i++) {
    if (g[i] >= 0.999) { out[i] = 1; continue; }
    const gr = -20 * Math.log10(Math.max(1e-4, g[i])) + shift;
    out[i] = gr <= 0 ? 1 : Math.pow(10, -gr / 20);
  }
  return { ...curve, gain: out, approx: true };
}

/** The ducking automation for a gain param from a curve ({rate, gain}). Pure (see sound.js duckEvents). */
function curveEvents(curve, t, now, horizon = 4) {
  if (!curve || !curve.gain || !curve.gain.length) return [[now, 1]];
  const { rate, gain } = curve;
  const at = (i) => now + ((i + 0.5) / rate - t);
  const first = Math.max(0, Math.floor(t * rate - 0.5));
  if (first >= gain.length) return [[now, 1]];
  const last = Math.min(gain.length - 1, Math.ceil((t + horizon) * rate));
  const x = t * rate - 0.5, i0 = Math.max(0, Math.min(gain.length - 1, Math.floor(x))), i1 = Math.min(gain.length - 1, i0 + 1);
  const f = Math.max(0, Math.min(1, x - i0));
  const out = [[now, gain[i0] * (1 - f) + gain[i1] * f]];
  for (let i = first; i <= last; i++) if (at(i) > now) out.push([at(i), gain[i]]);
  return out;
}

// ------------------------------------------------------------------ the preview player

/** v0.4.59 The envelope of preview element `slot` (0 / 1: the alternate passes) at timeline time t:
 *  the gain of the pass of that parity under t (crossfades and the run's fades), 0 between them.
 *  Two passes of one parity never overlap (a crossfade is at most half a pass). Pure. */
export function slotGain(lay, slot, t) {
  let i = 0;
  for (const run of lay?.runs || []) {
    for (let k = 0; k < run.iters.length; k++, i++) {
      if (i % 2 !== slot) continue;
      const it = run.iters[k];
      if (t >= it.at && t < it.at + it.len) return passGain(lay, run, k, t);
    }
  }
  return 0;
}

/** v0.4.59 Gain automation for element `slot`: [[audioTime, value]] from timeline time t (= audio
 *  time `now`) for `horizon` seconds — every `step` seconds plus every point where the envelope
 *  bends (pass and crossfade edges, fade ends), so linear ramps between them trace the export's
 *  equal-power crossfades and fades. The preview's gains are then scheduled on the audio clock,
 *  exactly where the export has them, instead of chased once per frame. Pure. */
export function envEvents(lay, slot, t, now, horizon = 3, step = 0.02) {
  const pts = new Set();
  for (let u = 0; u <= horizon + 1e-9; u += step) pts.add(+(t + u).toFixed(6));
  const x = lay?.crossfade || 0, eps = 1e-4;
  const edge = (v) => { if (v > t && v < t + horizon) { pts.add(+v.toFixed(6)); pts.add(+(v - eps).toFixed(6)); } };
  for (const run of lay?.runs || []) {
    edge(run.at); edge(run.end); edge(run.at + run.fade_in); edge(run.end - run.fade_out);
    for (const it of run.iters) { edge(it.at); edge(it.at + it.len); edge(it.at + x); edge(it.at + it.len - x); }
  }
  return [...pts].sort((a, b) => a - b).map((tt) => [now + (tt - t), slotGain(lay, slot, tt)]);
}

/** v0.4.59 How to bring a playing element back in step: {seek: position} | {rate} (1 = in step).
 *  `drift` = element position - where it should be (s); `gain` = how loud it is now. A seek is
 *  heard as a jump, so small errors are trimmed with the playback rate (±3 %, pitch kept) and a
 *  seek is only made where the music is (nearly) silent or the error is large. Pure. */
export function syncStep(drift, gain, target) {
  const a = Math.abs(drift);
  if (a > 0.25 || (gain < 0.15 && a > 0.03)) return { seek: target };
  if (a <= 0.008) return { rate: 1 };
  return { rate: Math.min(1.03, Math.max(0.97, 1 - drift * 0.6)) };
}

export class MusicPreview {
  /** `host`: the SfxPreview (one AudioContext for the whole preview). */
  constructor(host) {
    this.host = host;
    this.els = [];
    this.url = null;
    this.lay = null;
    this.passes = [];
    this.volume = 0.12;
    this.muted = false;
    this.duck = null;
    this.duckUntil = 0;
    this.nodes = null;
    this.anchor = null; // timeline time t is audio time `at` (the audio clock drives everything)
    this.envUntil = [0, 0]; // per element: its gain automation is scheduled up to this audio time
    this.lat = 0.03; // measured delay between play() and the element really playing (s)
    this.starting = [null, null]; // per element: {req, pos} while play() is starting
  }
  _graph() {
    if (this.nodes) return this.nodes;
    const ctx = this.host?.ensure?.();
    if (!ctx) return null;
    const bus = ctx.createGain(), duck = ctx.createGain();
    bus.gain.value = this.muted ? 0 : this.volume;
    bus.connect(duck).connect(ctx.destination);
    this.nodes = { ctx, bus, duck, pass: [] };
    this.els.forEach((el, i) => this._attach(el, i));
    return this.nodes;
  }
  _attach(el, i) {
    const n = this.nodes;
    if (!n || n.pass[i]) return;
    try {
      const g = n.ctx.createGain();
      g.gain.value = 0;
      n.ctx.createMediaElementSource(el).connect(g).connect(n.bus);
      el.volume = 1;
      n.pass[i] = g;
    } catch {
      n.pass[i] = null; // no WebAudio for this element: its own volume is used
    }
  }
  setSource(url) {
    if (url === this.url) return;
    this.url = url;
    if (!url) { this.els.forEach((el) => { el.pause(); el.removeAttribute("src"); el.load(); }); return; }
    while (this.els.length < 2) {
      const el = new Audio();
      el.preload = "auto";
      el.preservesPitch = true; // a rate trim keeps the pitch
      this.els.push(el);
      if (this.nodes) this._attach(el, this.els.length - 1);
    }
    this.els.forEach((el) => { el.src = url; });
  }
  setLayout(lay) {
    this.lay = lay;
    this.passes = musicPasses(lay);
    this.envUntil = [0, 0]; // the new layout's envelope is scheduled from now on
  }
  /** Real time: a gain ramp, nothing else. */
  setVolume(v) {
    this.volume = Math.max(0, +v || 0);
    this._applyBus();
  }
  _applyBus() {
    const n = this.nodes;
    if (!n) return;
    n.bus.gain.setTargetAtTime(this.muted ? 0 : this.volume, n.ctx.currentTime, 0.03);
  }
  setDuck(curve) {
    this.duck = curve;
    this.duckUntil = 0;
    const n = this.nodes;
    if (!n) return;
    if (this.anchor) this._scheduleDuck(this.anchor.t + (n.ctx.currentTime - this.anchor.at), n.ctx.currentTime, true);
    else { n.duck.gain.cancelScheduledValues(0); n.duck.gain.setValueAtTime(1, n.ctx.currentTime); }
  }
  _scheduleDuck(t, now, reset) {
    const p = this.nodes.duck.gain;
    const from = reset ? t : t + (this.duckUntil - now);
    const ev = curveEvents(this.duck, from, reset ? now : this.duckUntil, 4);
    if (reset) { p.cancelScheduledValues(0); p.setValueAtTime(ev[0][1], now); }
    for (const [at, v] of ev.slice(1)) p.linearRampToValueAtTime(v, at);
    this.duckUntil = ev.length > 1 ? ev[ev.length - 1][0] : now + 4;
  }
  /** v0.4.59 Element `slot`'s envelope as automation on the audio clock (from the anchor). */
  _scheduleEnv(slot, now, reset) {
    const g = this.nodes?.pass[slot];
    if (!g || !this.lay || !this.anchor) return;
    const p = g.gain;
    const from = reset ? now : Math.max(now, this.envUntil[slot]);
    const t = this.anchor.t + (from - this.anchor.at);
    const ev = envEvents(this.lay, slot, t, from, 3);
    if (reset) { p.cancelScheduledValues(0); p.setValueAtTime(ev[0][1], now); }
    for (const [at, v] of ev.slice(1)) p.linearRampToValueAtTime(v, at);
    this.envUntil[slot] = ev[ev.length - 1][0];
  }
  stop() {
    this.els.forEach((el) => { el.pause(); el.playbackRate = 1; });
    if (this.nodes) this.nodes.pass.forEach((g) => { if (g) { g.gain.cancelScheduledValues(0); g.gain.setValueAtTime(0, this.nodes.ctx.currentTime); } });
    this.anchor = null;
    this.envUntil = [0, 0];
    this.starting = [null, null];
  }
  /** Called on every preview clock tick. */
  tick(t, playing, muted) {
    if (muted !== this.muted) { this.muted = muted; this._applyBus(); }
    if (!this.url || !this.passes.length || !playing) { if (this.anchor || this.els.some((el) => !el.paused)) this.stop(); return; }
    const n = this._graph();
    const now = n ? n.ctx.currentTime : performance.now() / 1000;
    const expect = this.anchor ? this.anchor.t + (now - this.anchor.at) : null;
    // the audio clock keeps the time between frames; the preview clock (picture, narration) only
    // re-anchors it when it really moved (a seek, a jump) or drifted, not on every frame's jitter
    const jumped = expect === null || Math.abs(expect - t) > 0.25;
    const moved = jumped || Math.abs(expect - t) > 0.05;
    if (moved) this.anchor = { t, at: now };
    // v0.4.60 a steady small offset (under 50 ms) is followed too, a tenth per tick (~0.2 s at 60
    // ticks/s): the music was left wherever the last re-anchor put it, up to 50 ms from the narration
    // after a seek, pause or edit. The average is followed, not each frame's jitter, so no seek.
    else this.anchor.t += (t - expect) * 0.1;
    const te = this.anchor.t + (now - this.anchor.at); // timeline time on the audio clock
    if (n && (jumped || this.duckUntil - now < 1.5)) this._scheduleDuck(te, now, jumped);
    for (let slot = 0; slot < 2; slot++) {
      if (n && n.pass[slot] && (moved || this.envUntil[slot] - now < 1.0)) this._scheduleEnv(slot, now, moved || this.envUntil[slot] < now);
      const el = this.els[slot];
      if (!el) continue;
      // this element's pass: the one under the playhead, or the next within 1 s (made ready)
      let p = null;
      for (const x of this.passes) {
        if (x.i % 2 !== slot) continue;
        if (te >= x.at && te < x.at + x.len) { p = x; break; }
        if (x.at > te && x.at - te < 1.0) { p = x; break; }
      }
      if (!p) {
        if (!el.paused) el.pause();
        this.starting[slot] = null;
        continue;
      }
      const target = p.src + (te - p.at); // where the element should be now (before the pass: a pre-roll)
      this._measure(slot, el, now);
      if (te < p.at && target < 0) {
        // the pass starts at the very top of the part: nothing to pre-roll — wait at its start and
        // call play() early by the measured start-up delay, so it really starts on its time
        if (!el.seeking && Math.abs(el.currentTime - p.src) > 0.02) el.currentTime = p.src;
        if (p.at - te <= this.lat + 0.005) this._play(slot, el, now);
        else if (!el.paused) el.pause();
        continue;
      }
      if (el.paused) {
        if (!el.seeking && Math.abs(el.currentTime - target) > 0.02) el.currentTime = target + this.lat;
        this._play(slot, el, now);
      } else if (!el.seeking && !this.starting[slot]) {
        const step = syncStep(el.currentTime - target, n && n.pass[slot] ? slotGain(this.lay, slot, te) : 1, target);
        if (step.seek !== undefined) { el.currentTime = step.seek; el.playbackRate = 1; }
        else if (el.playbackRate !== step.rate) el.playbackRate = step.rate;
      }
      if (!n || !n.pass[slot]) {
        let duck = 1;
        if (this.duck?.gain?.length) duck = this.duck.gain[Math.min(this.duck.gain.length - 1, Math.max(0, Math.floor(te * this.duck.rate)))];
        el.volume = Math.max(0, Math.min(1, slotGain(this.lay, slot, te) * (this.muted ? 0 : this.volume) * duck));
      }
    }
  }
  _play(slot, el, now) {
    if (!el.paused) return;
    this.starting[slot] = { req: now, pos: el.currentTime };
    el.play().catch(() => { this.starting[slot] = null; });
  }
  /** The start-up delay of play(), learnt from the elements themselves (a running average). */
  _measure(slot, el, now) {
    const s = this.starting[slot];
    if (!s || el.paused) return;
    const ran = el.currentTime - s.pos;
    if (ran > 0.001) {
      const lat = Math.max(0, Math.min(0.3, now - s.req - ran));
      this.lat = this.lat * 0.7 + lat * 0.3;
      this.starting[slot] = null;
    } else if (now - s.req > 1) this.starting[slot] = null;
  }
}

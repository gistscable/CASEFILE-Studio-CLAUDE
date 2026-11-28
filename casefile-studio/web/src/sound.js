// v0.4.56 Intelligent sound design: the editor side. The plan is made by the server (sound.py);
// this file keeps the settings in range, applies presets, and plays the planned sounds in the
// preview with WebAudio, scheduled against the editor's own clock (no stem is rendered for the
// preview, so editing one sound never rebuilds anything).
import SPEC_ALL from "./effectsSpec.json" with { type: "json" };

export const SFX = SPEC_ALL.sound;
const clamp = (v, [lo, hi], d) => (v !== null && v !== "" && Number.isFinite(+v) ? Math.min(hi, Math.max(lo, +v)) : d);

export const KIND_LABEL = Object.fromEntries(SFX.kinds);
export const PRESETS = Object.fromEntries(SFX.presets.map((p) => [p.id, p]));

/** A light copy of sound.normalise (the server's is the one that counts). */
export function normaliseSound(v) {
  const D = SFX.defaults, L = SFX.limits;
  v = v && typeof v === "object" ? v : {};
  return {
    enabled: v.enabled === undefined ? D.enabled : !!v.enabled,
    mode: ["auto", "manual"].includes(v.mode) ? v.mode : D.mode,
    preset: PRESETS[v.preset] ? v.preset : D.preset,
    master: clamp(v.master, L.master, D.master),
    intensity: clamp(v.intensity, L.intensity, D.intensity),
    density: clamp(v.density, L.density, D.density),
    lead: clamp(v.lead, L.lead, D.lead),
    duck: v.duck === undefined ? D.duck : !!v.duck,
    variation: v.variation === undefined ? D.variation : !!v.variation,
    flavour: v.flavour === undefined ? D.flavour !== false : !!v.flavour, // v0.4.76 the niche's own sound families
    kinds: Object.fromEntries(Object.keys(D.kinds).map((k) => [k, (v.kinds || {})[k] === undefined ? D.kinds[k] : !!v.kinds[k]])),
    items: Array.isArray(v.items) ? v.items : [],
  };
}

/** The settings with a preset applied (its intensity, density and kinds; "custom" keeps yours). */
export function withPreset(s, id) {
  const p = PRESETS[id];
  if (!p || id === "custom") return { ...s, preset: id };
  return { ...s, preset: id, intensity: p.intensity, density: p.density, kinds: { ...s.kinds, ...(p.kinds || {}) } };
}

/** The stored item for a planned sound with your change applied. Only what is stored is kept
 *  through later re-plans (in automatic mode a planned sound is stored once you change it). */
export function editItem(settings, item, patch) {
  const keys = ["id", "anchor", "kind", "sound", "gain", "offset", "fade_in", "fade_out", "length", "status", "source", "reason", "label"];
  const base = Object.fromEntries(keys.filter((k) => item[k] !== undefined).map((k) => [k, item[k]]));
  const next = { ...base, ...patch, edited: true };
  const items = settings.items.some((x) => x.id === item.id)
    ? settings.items.map((x) => (x.id === item.id ? { ...x, ...patch, edited: true } : x))
    : [...settings.items, next];
  return { ...settings, items };
}

/** v0.4.57 The motion graphic a sound belongs to: {gid, role} for anchors "mg:<gid>:<role>:<k>"
 *  (typing "mg:<gid>:...:type" counts as its role), else null. */
export function graphicOf(item) {
  const m = /^mg:([^:]+):([^:]+):/.exec(item?.anchor || "");
  return m ? { gid: m[1], role: m[2] } : null;
}

/** The planned sounds an edit applies to: "this" sound, the same "role" in its graphic (every line,
 *  every marker…), or the whole "graphic". Pure. */
export function scopeItems(planItems, item, scope) {
  const g = graphicOf(item);
  if (!g || scope === "this") return [item];
  return (planItems || []).filter((x) => {
    const o = graphicOf(x);
    return o && o.gid === g.gid && (scope === "graphic" || o.role === g.role);
  });
}

/** editItem for several sounds at once: one stored change each, one undo step for the caller.
 *  `patch` is an object, or a function (item) -> object (e.g. a relative volume change). */
export function editItems(settings, items, patch) {
  let s = settings;
  for (const it of items) s = editItem(s, it, typeof patch === "function" ? patch(it) : patch);
  return s;
}

/** v0.4.57 The ducking automation for the preview: [[ctxTime, gain]] from timeline time `t` (at
 *  context time `now`) up to `horizon` seconds ahead, from the server's curve ({rate, gain: 0..1
 *  values, each the mean of its 1/rate window, so centred at (i + 0.5) / rate}). Pure. */
export function duckEvents(duck, t, now, horizon = 4) {
  if (!duck || !duck.gain || !duck.gain.length) return [[now, 1]];
  const { rate, gain } = duck;
  const at = (i) => now + ((i + 0.5) / rate - t);
  const first = Math.max(0, Math.floor(t * rate - 0.5));
  const last = Math.min(gain.length - 1, Math.ceil((t + horizon) * rate));
  const out = [];
  // the value right now (between two points) first, then every point ahead
  const x = t * rate - 0.5, i0 = Math.max(0, Math.min(gain.length - 1, Math.floor(x))), i1 = Math.min(gain.length - 1, i0 + 1);
  const f = Math.max(0, Math.min(1, x - i0));
  out.push([now, gain[i0] * (1 - f) + gain[i1] * f]);
  for (let i = first; i <= last; i++) if (at(i) > now) out.push([at(i), gain[i]]);
  if (first >= gain.length) return [[now, 1]];
  return out;
}

/** The server's {gain: base64 uint8} as numbers 0..1. */
export function decodeDuck(d) {
  if (!d || d.status !== "ready" || !d.gain) return null;
  const bin = typeof atob === "function" ? atob(d.gain) : Buffer.from(d.gain, "base64").toString("binary");
  const g = new Float32Array(bin.length);
  for (let i = 0; i < bin.length; i++) g[i] = bin.charCodeAt(i) / 255;
  return { rate: d.rate, gain: g, key: d.key };
}

/** v0.4.58 A small waveform: `n` peak values 0..1 of a decoded sound. Pure. */
export function peaks(buf, n = 48) {
  if (!buf) return [];
  const ch = buf.getChannelData(0), step = Math.max(1, Math.floor(ch.length / n)), out = [];
  for (let i = 0; i < n; i++) {
    let m = 0;
    for (let j = i * step, e = Math.min(ch.length, (i + 1) * step); j < e; j++) { const v = Math.abs(ch[j]); if (v > m) m = v; }
    out.push(m);
  }
  const top = Math.max(1e-6, ...out);
  return out.map((v) => v / top);
}

export function soundUrl(projectId, sid) {
  return sid.startsWith("a:") ? `/api/projects/${projectId}/sound/custom/${sid.slice(2)}.wav` : `/api/sound/lib/${sid}.wav`;
}

/** Every sound start in the plan as [start, sid, gain, item] (typing: one per key). Pure. */
export function schedule(items, mutedKinds = {}) {
  const out = [];
  for (const it of items || []) {
    if (it.status !== "approved" || it.t == null || it.gone || mutedKinds[it.kind]) continue;
    const g = Math.pow(10, (it.level ?? 0) / 20);
    if (it.keys && it.keys.length) {
      for (const [t, sid, kg] of it.keys) out.push([t - (it.t - it.start), sid, g * kg, it]);
    } else out.push([it.start, it.sound, g, it]);
  }
  return out.sort((a, b) => a[0] - b[0]);
}

// ------------------------------------------------------------------ WebAudio preview

export class SfxPreview {
  constructor() {
    this.ctx = null;
    this.buffers = new Map();
    this.loading = new Map();
    this.live = [];
    this.out = null;
    this.next = 0; // index into the schedule of the next sound to start
    this.list = [];
    this.anchor = null; // {t, at}: timeline time t was at ctx time `at`
    this.duck = null; // v0.4.57: {rate, gain} — the export's ducking, applied in the preview
    this.duckUntil = 0; // ctx time up to which the ducking is scheduled
    this.narr = new WeakMap(); // <audio> -> its gain node, when the narration is boosted over 100%
    this.master = 1; // v0.4.58: the effects volume now / the one the plan's levels were made with
    this.override = new Map(); // item id -> a live volume factor while its slider moves (not saved yet)
    this.itemGains = new Map(); // item id -> the gain nodes of its sounds playing now
    this.horizon = -1; // every sound starting before this timeline time has been started
    this.aud = null; // the one audition playing: {src, sid, onEnd}
  }
  /** v0.4.58 The effects volume, in real time: a short ramp on the output, no new plan. */
  setMaster(ratio) {
    this.master = Math.max(0, Number.isFinite(+ratio) ? +ratio : 1);
    if (this.out && this.ctx) this.out.gain.setTargetAtTime(this.master, this.ctx.currentTime, 0.03);
  }
  /** v0.4.58 One sound's volume while its slider moves (factor; null = back to its saved level). */
  setItemGain(id, factor) {
    if (factor === null || factor === undefined) this.override.delete(id);
    else this.override.set(id, Math.max(0, +factor || 0));
    const f = this.override.get(id) ?? 1;
    for (const [g, base] of this.itemGains.get(id) || []) if (this.ctx) g.gain.setTargetAtTime(base * f, this.ctx.currentTime, 0.02);
  }
  setDuck(d) {
    this.duck = d;
    this.duckUntil = 0;
    if (this.anchor && this.ctx) this.scheduleDuck(this.anchor.t + (this.ctx.currentTime - this.anchor.at), this.ctx.currentTime, true);
    else if (this.duckNode && this.ctx) { this.duckNode.gain.cancelScheduledValues(0); this.duckNode.gain.setValueAtTime(1, this.ctx.currentTime); }
  }
  scheduleDuck(t, now, reset) {
    if (!this.duckNode) return;
    const p = this.duckNode.gain;
    const from = reset ? t : t + (this.duckUntil - now);
    const ev = duckEvents(this.duck, from, reset ? now : this.duckUntil, 4);
    if (reset) {
      p.cancelScheduledValues(0);
      p.setValueAtTime(ev[0][1], now);
    }
    for (const [at, v] of ev.slice(1)) p.linearRampToValueAtTime(v, at);
    this.duckUntil = ev.length > 1 ? ev[ev.length - 1][0] : now + 4;
  }
  /** v0.4.57 The narration level in the preview: the element's own volume up to 100%, a WebAudio
   *  gain above (an <audio> element cannot go over 1). */
  narration(el, level) {
    if (!el) return;
    const v = Math.max(0, Math.min(2, Number.isFinite(+level) ? +level : 1));
    let g = this.narr.get(el);
    if (v <= 1 && !g) { el.volume = v; return; }
    if (!g) {
      const ctx = this.ensure();
      if (!ctx) { el.volume = Math.min(1, v); return; }
      try {
        g = ctx.createGain();
        ctx.createMediaElementSource(el).connect(g).connect(ctx.destination);
        this.narr.set(el, g);
      } catch { el.volume = Math.min(1, v); return; }
    }
    el.volume = 1;
    if (Math.abs(g.gain.value - v) > 1e-4) g.gain.setTargetAtTime(v, this.ctx.currentTime, 0.03);
  }
  ensure() {
    if (!this.ctx) {
      const C = window.AudioContext || window.webkitAudioContext;
      if (!C) return null;
      this.ctx = new C({ latencyHint: "interactive" });
      this.out = this.ctx.createGain();
      this.out.gain.value = this.master;
      this.out.connect(this.ctx.destination);
      this.audOut = this.ctx.createGain(); // auditions: their own volume, not the mix's
      this.audOut.connect(this.ctx.destination);
      this.duckNode = this.ctx.createGain(); // every effect goes through the ducking, then the volume
      this.duckNode.connect(this.out);
    }
    if (this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
    return this.ctx;
  }
  load(url) {
    if (this.buffers.has(url)) return Promise.resolve(this.buffers.get(url));
    if (!this.loading.has(url)) {
      const ctx = this.ensure();
      if (!ctx) return Promise.resolve(null);
      this.loading.set(url, fetch(url, { credentials: "same-origin" })
        .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(r.status))))
        .then((b) => ctx.decodeAudioData(b))
        .then((buf) => (this.buffers.set(url, buf), buf))
        .catch(() => null)
        .finally(() => this.loading.delete(url)));
    }
    return this.loading.get(url);
  }
  preload(projectId, list) {
    for (const sid of new Set(list.map((x) => x[1]))) this.load(soundUrl(projectId, sid));
  }
  play(buf, when, offset, gain, it, ducked = false) {
    const ctx = this.ctx, src = ctx.createBufferSource(), g = ctx.createGain();
    src.buffer = buf;
    const len = it && it.length ? Math.min(buf.duration, it.length) : buf.duration;
    const base = gain;
    if (ducked && it?.id && this.override.has(it.id)) gain *= this.override.get(it.id);
    g.gain.value = gain;
    const fi = it?.fade_in || 0, fo = it?.fade_out || (it?.length ? 0.015 : 0);
    if (fi > offset) {
      g.gain.setValueAtTime(0.0001, when);
      g.gain.linearRampToValueAtTime(gain, when + fi - offset);
    }
    if (fo) {
      g.gain.setValueAtTime(gain, when + Math.max(0, len - fo - offset));
      g.gain.linearRampToValueAtTime(0.0001, when + Math.max(0.001, len - offset));
    }
    src.connect(g).connect(ducked ? this.duckNode : this.audOut); // auditions are not ducked
    src.start(when, Math.max(0, offset), Math.max(0.001, len - offset));
    if (!ducked) return src; // an audition: not one of the timeline's sounds
    this.live.push(src);
    const key = it?.id;
    if (key && !fi && !fo) { // a live volume change follows it (fades keep their own automation)
      if (!this.itemGains.has(key)) this.itemGains.set(key, new Map());
      this.itemGains.get(key).set(g, base);
    }
    src.onended = () => {
      this.live = this.live.filter((s) => s !== src);
      if (key) this.itemGains.get(key)?.delete(g);
    };
    return src;
  }
  /** v0.4.58 Audition one sound now (the library, "play this sound"): only one at a time — a new
   *  one stops the last. Nothing is added to the project. Resolves with its length in seconds.
   *  `onEnd` is called when it stops (ended or stopped). */
  async audition(projectId, sid, gain = 0.8, it = null, onEnd = null) {
    const ctx = this.ensure();
    if (!ctx) return null;
    this.stopAudition();
    const token = {};
    this.aud = { token, sid, onEnd };
    const buf = await this.load(soundUrl(projectId, sid));
    if (!buf || this.aud?.token !== token) { if (this.aud?.token === token) this.stopAudition(); return buf ? buf.duration : null; }
    const src = this.play(buf, ctx.currentTime + 0.02, 0, gain, it ? { ...it, id: undefined } : null);
    this.aud.src = src;
    src.onended = () => { if (this.aud?.src === src) { const cb = this.aud.onEnd; this.aud = null; cb?.(); } };
    return buf.duration;
  }
  stopAudition() {
    const a = this.aud;
    this.aud = null;
    if (!a) return;
    try { a.src?.stop(); } catch { /* already ended */ }
    a.onEnd?.();
  }
  /** v0.4.58 The audition volume, in real time. */
  setAuditionVolume(v) {
    this.ensure();
    if (this.audOut) this.audOut.gain.setTargetAtTime(Math.max(0, +v || 0), this.ctx.currentTime, 0.02);
  }
  stop() {
    for (const s of this.live) try { s.stop(); } catch { /* already ended */ }
    this.live = [];
    this.itemGains.clear();
    this.anchor = null;
    this.horizon = -1;
  }
  /** Called on every preview clock tick: starts the sounds that fall in the next moment. */
  tick(projectId, list, t, playing) {
    if (!playing || !list.length) {
      if (this.anchor) this.stop();
      return;
    }
    if (!this.ensure()) return;
    const now = this.ctx.currentTime;
    const expect = this.anchor ? this.anchor.t + (now - this.anchor.at) : null;
    if (expect !== null && Math.abs(expect - t) <= 0.25 && this.list !== list) {
      // v0.4.58 the plan changed while playing (an edit): carry on — the sounds already started
      // play on, the new plan continues from the first sound not yet started (no restart, no gap)
      this.list = list;
      this.next = list.findIndex((x) => x[0] >= this.horizon - 1e-6);
      if (this.next < 0) this.next = list.length;
    } else if (expect === null || Math.abs(expect - t) > 0.25) {
      // started or seeked: begin again from here
      this.stop();
      this.list = list;
      this.scheduleDuck(t, now, true);
      this.next = list.findIndex((x) => x[0] + 0.02 >= t);
      if (this.next < 0) this.next = list.length;
      // a longer sound that began just before the playhead plays on from its middle
      for (const x of list.slice(Math.max(0, this.next - 12), this.next)) {
        const buf = this.buffers.get(soundUrl(projectId, x[1]));
        if (buf && x[0] + buf.duration > t + 0.05) this.play(buf, now + 0.01, t - x[0], x[2], x[3], true);
      }
    }
    this.anchor = { t, at: now };
    if (this.duckUntil - now < 1.5) this.scheduleDuck(t, now, false);
    const ahead = 0.3;
    while (this.next < list.length && list[this.next][0] < t + ahead) {
      const [s, sid, g, it] = list[this.next++];
      const buf = this.buffers.get(soundUrl(projectId, sid));
      if (!buf) { this.load(soundUrl(projectId, sid)); continue; }
      const when = now + (s - t);
      if (when >= now) this.play(buf, when, 0, g, it, true);
      else if (now - when < buf.duration) this.play(buf, now, now - when, g, it, true);
    }
    this.horizon = t + ahead;
  }
}

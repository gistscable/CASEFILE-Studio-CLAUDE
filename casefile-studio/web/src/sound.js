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
  }
  ensure() {
    if (!this.ctx) {
      const C = window.AudioContext || window.webkitAudioContext;
      if (!C) return null;
      this.ctx = new C({ latencyHint: "interactive" });
      this.out = this.ctx.createGain();
      this.out.connect(this.ctx.destination);
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
  play(buf, when, offset, gain, it) {
    const ctx = this.ctx, src = ctx.createBufferSource(), g = ctx.createGain();
    src.buffer = buf;
    const len = it && it.length ? Math.min(buf.duration, it.length) : buf.duration;
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
    src.connect(g).connect(this.out);
    src.start(when, Math.max(0, offset), Math.max(0.001, len - offset));
    this.live.push(src);
    src.onended = () => (this.live = this.live.filter((s) => s !== src));
  }
  /** One sound now (the library browser, "play this sound"). */
  async audition(projectId, sid, gain = 0.8, it = null) {
    const ctx = this.ensure();
    if (!ctx) return;
    const buf = await this.load(soundUrl(projectId, sid));
    if (buf) this.play(buf, ctx.currentTime + 0.02, 0, gain, it);
  }
  stop() {
    for (const s of this.live) try { s.stop(); } catch { /* already ended */ }
    this.live = [];
    this.anchor = null;
  }
  /** Called on every preview clock tick: starts the sounds that fall in the next moment. */
  tick(projectId, list, t, playing, volume = 1) {
    const ctx = this.ctx;
    if (!playing || !list.length) {
      if (this.anchor) this.stop();
      return;
    }
    if (!this.ensure()) return;
    this.out.gain.value = volume;
    const now = this.ctx.currentTime;
    const expect = this.anchor ? this.anchor.t + (now - this.anchor.at) : null;
    if (this.list !== list || expect === null || Math.abs(expect - t) > 0.25) {
      // started, seeked or the plan changed: begin again from here
      this.stop();
      this.list = list;
      this.next = list.findIndex((x) => x[0] + 0.02 >= t);
      if (this.next < 0) this.next = list.length;
      // a longer sound that began just before the playhead plays on from its middle
      for (const x of list.slice(Math.max(0, this.next - 12), this.next)) {
        const buf = this.buffers.get(soundUrl(projectId, x[1]));
        if (buf && x[0] + buf.duration > t + 0.05) this.play(buf, now + 0.01, t - x[0], x[2], x[3]);
      }
    }
    this.anchor = { t, at: now };
    const ahead = 0.3;
    while (this.next < list.length && list[this.next][0] < t + ahead) {
      const [s, sid, g, it] = list[this.next++];
      const buf = this.buffers.get(soundUrl(projectId, sid));
      if (!buf) { this.load(soundUrl(projectId, sid)); continue; }
      const when = now + (s - t);
      if (when >= now) this.play(buf, when, 0, g, it);
      else if (now - when < buf.duration) this.play(buf, now, now - when, g, it);
    }
  }
}

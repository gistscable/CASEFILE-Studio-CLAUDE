// v0.4.29 Subscribe call-to-action, preview side. Same timeline numbers as
// cta.py (effectsSpec.json), so the preview moves like the export.
import SPEC from "./effectsSpec.json" with { type: "json" };

const C = SPEC.cta;
const FPS = 24;

export function normaliseCta(v) {
  const o = v && typeof v === "object" ? v : {};
  const n = (x, [lo, hi], d) => (Number.isFinite(Number(x)) ? Math.min(hi, Math.max(lo, Number(x))) : d);
  return {
    ...C.defaults,
    enabled: o.enabled === true,
    asset_id: o.asset_id || null,
    button: Array.isArray(o.button) && o.button.length === 4 ? o.button.map(Number) : null,
    opacity: n(o.opacity, C.limits.opacity, C.defaults.opacity),
    seconds: n(o.seconds, C.limits.seconds, C.defaults.seconds),
    mode: o.mode === "scenes" ? "scenes" : "auto",
    // v0.4.35: your own animated file, and a blurred video behind.
    style: o.style === "blur" ? "blur" : "overlay",
    source: o.source === "file" ? "file" : "casefile",
    file_id: o.file_id || null,
    size: n(o.size, C.limits.size, C.defaults.size),
    y: n(o.y, C.limits.y, C.defaults.y),
    x: n(o.x, C.limits.x, C.defaults.x),
    // v0.4.49: every place it shows (see cta.py normalise).
    spots: Object.fromEntries(
      Object.entries(o.spots && typeof o.spots === "object" ? o.spots : {})
        .filter(([k, sp]) => /^s:[\w-]{1,64}$/.test(k) && sp && typeof sp === "object")
        .slice(0, 60)
        .map(([k, sp]) => [k, normaliseSpot(sp)]),
    ),
    extra: (Array.isArray(o.extra) ? o.extra : [])
      .filter((sp) => sp && typeof sp === "object" && Number.isFinite(Number(sp.start)))
      .slice(0, 20)
      .map((sp, i) => ({
        id: String(sp.id || "").replace(/[^\w-]/g, "").slice(0, 24) || `x${i + 1}`,
        start: Math.round(Math.min(86400, Math.max(0, Number(sp.start))) * 1000) / 1000,
        ...normaliseSpot(sp),
      })),
  };
}

function normaliseSpot(sp) {
  const num = (x, lo, hi) => (x !== null && x !== undefined && x !== "" && Number.isFinite(Number(x)) ? Math.round(Math.min(hi, Math.max(lo, Number(x))) * 1000) / 1000 : null);
  return {
    on: sp.on !== false,
    nudge: num(sp.nudge, -30, 30) || 0,
    length: num(sp.length, C.place_length[0], C.file_max_seconds),
    scene_end: sp.scene_end === true,
  };
}

// Same as cta.file_seconds: your file plays once, 1 to 15 s.
export function ctaFileSeconds(asset) {
  const d = Number(asset?.video_duration || asset?.duration || 0);
  return Math.min(C.file_max_seconds, Math.max(1, d || 5));
}

export function ctaLength(c, assets = []) {
  return c.source === "file" ? ctaFileSeconds(assets.find((a) => a.id === c.file_id)) : c.seconds;
}

export function ctaReady(c, assets = []) {
  if (!c.enabled) return false;
  if (c.source === "file") return !!(c.file_id && assets.some((a) => a.id === c.file_id));
  return !!c.asset_id;
}

// Same as cta.card: the banner as a card, `size` of the width, centred at `y`.
export function ctaCard(fw, fh, iw, ih, size, y, x = 0.5) {
  let w = fw * size;
  let h = (w * ih) / iw;
  if (h > fh * 0.9) {
    h = fh * 0.9;
    w = (h * iw) / ih;
  }
  const top = Math.min(Math.max(0, y * fh - h / 2), fh - h);
  return { x: Math.min(Math.max(0, x * fw - w / 2), fw - w), y: top, w, h };
}

// How strongly the blur shows `t` seconds into a CTA lasting `seconds`.
export function ctaBlurFade(t, seconds) {
  const fi = Math.min(C.blur.fade_in, seconds / 3);
  const fo = Math.min(C.blur.fade_out, seconds / 3);
  if (t < fi) return Math.max(0, t / fi);
  if (t > seconds - fo) return Math.max(0, (seconds - t) / fo);
  return 1;
}

export const CTA_BLUR = C.blur;

const ease = (x) => {
  const t = Math.min(1, Math.max(0, x));
  return t * t * (3 - 2 * t);
};

export function ctaState(t, seconds) {
  let fade = t < C.fade_in ? Math.min(1, t / C.fade_in) : 1;
  if (t > seconds - C.fade_out) fade = Math.max(0, (seconds - t) / C.fade_out);
  const [m0, m1] = C.move;
  const [r0, r1] = C.ripple;
  const [w0, w1] = C.wiggle;
  let bell = 0;
  if (t >= w0 && t < w1) {
    const q = (t - w0) / (w1 - w0);
    bell = 18 * Math.sin(2 * Math.PI * 4 * q) * (1 - q);
  }
  return {
    fade,
    move: ease((t - m0) / (m1 - m0)),
    pressed: t >= C.click && t < C.click + C.press,
    subscribed: t >= C.click + 0.1,
    ripple: t >= r0 && t < r1 ? (t - r0) / (r1 - r0) : null,
    bell: t >= C.bell_in,
    bellAngle: bell,
  };
}

export function ctaPlacement(fw, fh, iw, ih) {
  if (Math.abs(iw / ih / (fw / fh) - 1) < 0.06) return { x: 0, y: 0, w: fw, h: fh };
  let w = fw * 0.92;
  let h = (w * ih) / iw;
  if (h > fh * 0.92) {
    h = fh * 0.92;
    w = (h * iw) / ih;
  }
  return { x: (fw - w) / 2, y: (fh - h) / 2, w, h };
}

const isCtaScene = (s) => /subscri|\bCTA\b|call to action/i.test(`${s.chapter || ""} ${s.title || ""}`);

// Same as cta.events: [[start, end]] on the whole timeline. `captionsOf`
// gives a scene's captions as the exporter times them.
// v0.4.49 Same as cta.spots: every place the animation can show, in time order.
// `shown` ones are drawn; one cut short (its length, the end of its scene or the
// next place) fades out instead of stopping hard.
export function ctaSpots(project, offsets, captionsOf, readyOnly = true) {
  const c = normaliseCta(project?.cta);
  const assets = project?.assets || [];
  if (readyOnly && !ctaReady(c, assets)) return [];
  const natural = ctaLength(c, assets);
  const scenes = project?.scenes || [];
  const len = (s) => Math.round(Number(s.duration) * FPS) / FPS;
  const total = scenes.reduce((a, s) => a + len(s), 0);
  const heads = scenes.map((s, i) => (isCtaScene(s) ? i : -1)).filter((i) => i >= 0);
  const said = scenes.map((s, i) => (/subscri/i.test(s.narration || "") ? i : -1)).filter((i) => i >= 0);
  const ticked = scenes.map((s, i) => (s.cta ? i : -1)).filter((i) => i >= 0);
  let defaults;
  if (c.mode === "scenes") defaults = new Set(ticked);
  else {
    const both = heads.filter((i) => said.includes(i));
    defaults = new Set((both.length ? both : heads.length ? heads : said).slice(0, 1));
  }
  const cueStart = (s) => {
    const cue = captionsOf(s).find((x) => /subscri/i.test(x.text));
    return cue ? Math.max(0, cue.start - C.lead) : 0;
  };
  const rows = [...new Set([...heads, ...said, ...ticked])]
    .sort((a, b) => a - b)
    .map((i) => {
      const key = `s:${scenes[i].id || i}`;
      return { key, i, start: (offsets[i] || 0) + cueStart(scenes[i]), sp: c.spots[key], def: defaults.has(i), auto: true };
    });
  for (const e of c.extra) {
    let i = scenes.findIndex((s, k) => e.start < (offsets[k] || 0) + len(s));
    if (i < 0) i = scenes.length - 1;
    rows.push({ key: e.id, i: Math.max(0, i), start: e.start, sp: e, def: true, auto: false });
  }
  const out = [];
  for (const r of rows) {
    const sp = r.sp || { on: r.def, nudge: 0, length: null, scene_end: false };
    const begin = Math.max(0, r.start + (r.auto ? sp.nudge : 0));
    const run = sp.length ? Math.min(natural, sp.length) : natural;
    let end = begin + run;
    if (sp.scene_end && scenes[r.i]) end = Math.min(end, (offsets[r.i] || 0) + len(scenes[r.i]));
    end = Math.min(end, total);
    if (end - begin < 1 / FPS) continue;
    out.push({
      key: r.key, start: Math.round(begin * 1000) / 1000, end: Math.round(end * 1000) / 1000, natural,
      fade_out: end < begin + natural - 1e-3, on: sp.on, auto: r.auto, scene: r.i,
      label: scenes[r.i]?.title || `Scene ${r.i + 1}`, spot: sp, found: r.start,
    });
  }
  out.sort((a, b) => a.start - b.start);
  let shownEnd = -1;
  for (const r of out) {
    r.shown = !!(r.on && r.start >= shownEnd - 1e-6);
    if (r.shown) shownEnd = r.end;
  }
  return out;
}

// [[start, end, spot]] that show.
export function ctaEvents(project, offsets, captionsOf) {
  return ctaSpots(project, offsets, captionsOf).filter((r) => r.shown).map((r) => [r.start, r.end, r]);
}

// Same as cta.alpha_at: 1 while the place shows, fading out when it was cut short.
export function ctaSpotAlpha(t, start, end, natural) {
  if (t < start || t >= end) return 0;
  if (end >= start + natural - 1e-3) return 1;
  const fo = Math.min(C.fade_out, (end - start) / 3);
  return fo > 0 ? Math.max(0, Math.min(1, (end - t) / fo)) : 1;
}

export const CTA_FALLBACK = C.fallback_button;

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
export function ctaCard(fw, fh, iw, ih, size, y) {
  let w = fw * size;
  let h = (w * ih) / iw;
  if (h > fh * 0.9) {
    h = fh * 0.9;
    w = (h * iw) / ih;
  }
  const top = Math.min(Math.max(0, y * fh - h / 2), fh - h);
  return { x: (fw - w) / 2, y: top, w, h };
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
export function ctaEvents(project, offsets, captionsOf) {
  const c = normaliseCta(project?.cta);
  if (!ctaReady(c, project.assets || [])) return [];
  const seconds = ctaLength(c, project.assets || []);
  const scenes = project.scenes || [];
  const total = scenes.reduce((a, s) => a + Math.round(Number(s.duration) * FPS) / FPS, 0);
  let picks;
  if (c.mode === "scenes") picks = scenes.map((s, i) => (s.cta ? i : -1)).filter((i) => i >= 0);
  else {
    const heads = scenes.map((s, i) => (isCtaScene(s) ? i : -1)).filter((i) => i >= 0);
    const said = scenes.map((s, i) => (/subscri/i.test(s.narration || "") ? i : -1)).filter((i) => i >= 0);
    const both = heads.filter((i) => said.includes(i));
    picks = (both.length ? both : heads.length ? heads : said).slice(0, 1);
  }
  const out = [];
  for (const i of picks) {
    const cue = captionsOf(scenes[i]).find((x) => /subscri/i.test(x.text));
    const start = (offsets[i] || 0) + (cue ? Math.max(0, cue.start - C.lead) : 0);
    const end = Math.min(total, start + seconds);
    if (!out.length || start >= out[out.length - 1][1]) out.push([start, end]);
  }
  return out;
}

export const CTA_FALLBACK = C.fallback_button;

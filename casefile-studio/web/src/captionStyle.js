// v0.4.25 Caption styles for the preview. Mirrors captionstyle.py and
// renderer.scene_captions so what you see is what the export burns in.
import SPEC from "./captionPresets.json" with { type: "json" };
import FX from "./effectsSpec.json" with { type: "json" };

// v0.4.28 Same as effects.text_unit / caption_bottom: 16:9 sizes come from the
// height (unchanged); 9:16 from the width x 1.6, with captions kept above the
// app buttons at the bottom of Shorts, TikTok and Reels.
export function textUnit(width, height) {
  return Math.min(width, height) * (height > width ? FX.formats["9:16"].text_scale : 1);
}
export function captionBottom(position, width, height) {
  return Math.max(position, height > width ? FX.formats["9:16"].safe_bottom : 0);
}

export const FONTS = SPEC.fonts;
export const PRESETS = SPEC.presets;
export const DEFAULTS = SPEC.defaults;
export const LIMITS = SPEC.limits;
const HEX = /^#[0-9A-Fa-f]{6}$/;

export function normaliseStyle(style) {
  const s = style && typeof style === "object" ? style : {};
  const preset = PRESETS.some((p) => p.id === s.preset) ? s.preset : DEFAULTS.preset;
  const out = { ...DEFAULTS, ...PRESETS.find((p) => p.id === preset).style, preset };
  for (const [k, v] of Object.entries(s)) {
    if (!(k in DEFAULTS) || k === "preset") continue;
    if (k in LIMITS) {
      const n = Number(v);
      if (!Number.isFinite(n)) continue;
      const [lo, hi] = LIMITS[k];
      const c = Math.min(hi, Math.max(lo, n));
      out[k] = k === "words" ? Math.round(c) : Math.round(c * 1e5) / 1e5;
    } else if (["color", "highlight", "outline_color", "box_color"].includes(k)) {
      if (typeof v === "string" && HEX.test(v)) out[k] = v.toUpperCase();
    } else if (k === "box" || k === "uppercase") out[k] = v === true;
    else if (k === "font" && FONTS[v]) out[k] = v;
    else if (k === "animation" && SPEC.animations.includes(v)) out[k] = v;
  }
  return out;
}

// Choosing a preset replaces the look but keeps where you put the captions,
// unless the preset has its own position.
export function applyPreset(current, id) {
  const p = PRESETS.find((x) => x.id === id);
  if (!p) return normaliseStyle(current);
  const keep = "position" in p.style ? {} : { position: normaliseStyle(current).position };
  return normaliseStyle({ ...DEFAULTS, ...p.style, ...keep, preset: id });
}

const plainWords = (t) => String(t || "").replace(/[\\{}]/g, "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);

// renderer.scene_captions: exact captions, else 9-word groups timed by word count.
export function sceneCaptions(scene, clean = (s) => s) {
  const duration = Number(scene?.duration) || 5;
  if (scene?.captions_exact || scene?.captions?.length) {
    return (scene.captions || [])
      .filter((c) => Number(c.start) < duration && Number(c.end) > Number(c.start))
      .map((c) => ({ start: Math.max(0, Number(c.start)), end: Math.min(duration, Number(c.end)), text: clean(c.text) }));
  }
  const words = plainWords(clean(scene?.narration || ""));
  if (!words.length) return [];
  const out = [];
  let cursor = 0;
  for (let i = 0; i < words.length; i += 9) {
    const g = words.slice(i, i + 9);
    const start = (duration * cursor) / words.length;
    cursor += g.length;
    out.push({ start, end: (duration * cursor) / words.length, text: g.join(" ") });
  }
  return out;
}

export function wordTimes(start, end, words) {
  const weights = words.map((w) => Math.max(1, w.length) + 1);
  const total = weights.reduce((a, b) => a + b, 0) || 1;
  let t = start;
  return weights.map((k) => {
    const d = ((end - start) * k) / total;
    const span = [t, t + d];
    t += d;
    return span;
  });
}

export function chunks(cues, wordsPer) {
  const out = [];
  for (const c of cues) {
    const words = plainWords(c.text);
    if (!words.length || c.end <= c.start) continue;
    if (!wordsPer || words.length <= wordsPer) {
      out.push({ start: c.start, end: c.end, words });
      continue;
    }
    const times = wordTimes(c.start, c.end, words);
    for (let i = 0; i < words.length; i += wordsPer) {
      const part = words.slice(i, i + wordsPer);
      out.push({ start: times[i][0], end: times[i + part.length - 1][1], words: part });
    }
  }
  return out;
}

// What is on screen at `local` seconds into the scene.
export function captionAt(scene, local, style, clean) {
  const s = normaliseStyle(style);
  const chunk = chunks(sceneCaptions(scene, clean), s.words).find((c) => local >= c.start && local < c.end);
  if (!chunk) return null;
  const words = s.uppercase ? chunk.words.map((w) => w.toUpperCase()) : chunk.words;
  let active = -1;
  if (s.animation === "highlight") {
    const times = wordTimes(chunk.start, chunk.end, words);
    active = times.findIndex(([a, b], i) => local >= a && (local < b || i === times.length - 1));
  }
  return { key: `${chunk.start.toFixed(3)}`, words, active };
}

const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

// CSS for a frame `height` px tall and `width` px wide. libass sizes a font by
// winAscent + winDescent, so a line is size / ratio tall: that is the CSS
// line-height that matches the export.
export function captionCss(style, width, height) {
  const s = normaliseStyle(style);
  const f = FONTS[s.font];
  const unit = textUnit(width, height);
  const px = (v) => `${(v * unit).toFixed(2)}px`;
  const wrap = {
    position: "absolute",
    left: `${6.25}%`,
    right: `${6.25}%`,
    bottom: `${(captionBottom(s.position, width, height) * height).toFixed(2)}px`,
    textAlign: "center",
    fontFamily: `"cf-${s.font}", sans-serif`,
    fontSize: px(s.size),
    lineHeight: (1 / f.ratio).toFixed(4),
    color: s.color,
    fontWeight: "normal",
    pointerEvents: "auto",
    cursor: "ns-resize",
    userSelect: "none",
    zIndex: 4,
  };
  const text = {};
  if (s.box) {
    text.background = rgba(s.box_color, s.box_opacity);
    text.padding = `0 ${px(s.outline)}`;
    text.boxDecorationBreak = "clone";
    text.WebkitBoxDecorationBreak = "clone";
  } else if (s.outline > 0) {
    text.WebkitTextStroke = `${(2 * s.outline * height).toFixed(2)}px ${s.outline_color}`;
    text.paintOrder = "stroke fill";
  }
  if (s.shadow > 0) text.textShadow = `${px(s.shadow)} ${px(s.shadow)} 0 rgba(0,0,0,0.6)`;
  return { wrap, text, highlight: s.highlight, animation: s.animation };
}

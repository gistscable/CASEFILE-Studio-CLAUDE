// v0.4.52 Motion graphics: the editor side (the server draws every frame; see motion.py).
import SPEC_ALL from "./effectsSpec.json" with { type: "json" };

export const MG = SPEC_ALL.motion;
export const TEMPLATES = Object.fromEntries(MG.templates.map((t) => [t.id, t]));
const ids = (opts) => opts.map((o) => (Array.isArray(o) ? o[0] : o));
const clamp = (v, [lo, hi], d) => (Number.isFinite(+v) && v !== null && v !== "" ? Math.min(hi, Math.max(lo, +v)) : d);

// v0.4.62 A story-aware (cinematic) graphic: its words, timing and design come from the server
// (cinematic.py); the editor changes only its place, status, captions and photos. Its length is the
// narration it covers (dur) plus the fade, at the export's 24 fps — the same rule as the server.
export const CINEMATIC_FPS = 24;
export function normaliseCinematic(it) {
  if (!it || it.template !== "cinematic" || !it.category || !Array.isArray(it.words) || !it.words.length) return null;
  const start = clamp(it.start, [0, 86400], 0);
  const dur = clamp(it.dur, [0.5, 600], 8);
  const photos = {};
  for (const [k, v] of Object.entries(it.photos && typeof it.photos === "object" ? it.photos : {})) {
    if (v && typeof v === "object") photos[k] = { asset_id: v.asset_id || "", credit: v.credit || "", month: v.month || "", auto: v.auto === true };
  }
  return {
    ...it,
    status: ["suggested", "draft", "approved"].includes(it.status) ? it.status : "draft",
    start,
    // the server's frames_of: the whole graphic, or up to where the next one covers it (`cut`, set by the server)
    end: Math.round((start + Math.min(Math.round((dur + 0.6) * CINEMATIC_FPS), it.cut > 0 ? Math.round(it.cut) : Infinity) / CINEMATIC_FPS) * 1000) / 1000,
    dur,
    photos,
    hide_captions: it.hide_captions !== false,
  };
}

// A light copy of motion.normalise_item (the server's is the one that counts).
export function normaliseItem(it) {
  if (it && it.template === "cinematic") return normaliseCinematic(it);
  if (!it || !TEMPLATES[it.template]) return null;
  const D = MG.defaults;
  const start = clamp(it.start, [0, 86400], 0);
  const end = clamp(it.end, [start + MG.limits.length[0], start + MG.limits.length[1]], start + 8);
  return {
    ...it,
    status: ["suggested", "draft", "approved"].includes(it.status) ? it.status : "draft",
    start,
    end,
    heading: it.heading || "",
    title: it.title || "",
    lines: (it.lines || []).map((l) => ({ text: l.text || "", label: l.label || "", kind: l.kind || "", emphasis: !!l.emphasis, at: clamp(l.at, [start, end], start) })),
    layout: ids(MG.layouts[it.template]).includes(it.layout) ? it.layout : "auto",
    background: ids(MG.backgrounds).includes(it.background) ? it.background : D.background,
    photo_id: it.photo_id || "",
    dim: clamp(it.dim, MG.limits.dim, D.dim),
    font: ids(MG.fonts).includes(it.font) ? it.font : D.font,
    size: clamp(it.size, MG.limits.size, D.size),
    accent: /^#[0-9a-f]{6}$/i.test(it.accent || "") ? it.accent : D.accent,
    text_color: /^#[0-9a-f]{6}$/i.test(it.text_color || "") ? it.text_color : D.text_color,
    align: it.align === "center" ? "center" : "left",
    x: clamp(it.x, MG.limits.xy, 0),
    y: clamp(it.y, MG.limits.xy, 0),
    speed: clamp(it.speed, MG.limits.speed, D.speed),
    enter: ids(MG.enters).includes(it.enter) ? it.enter : D.enter,
    exit: ids(MG.exits).includes(it.exit) ? it.exit : D.exit,
    hide_captions: it.hide_captions !== false,
  };
}

export function normaliseMotion(m) {
  const v = m && typeof m === "object" ? m : {};
  const items = (v.items || []).map(normaliseItem).filter(Boolean).sort((a, b) => a.start - b.start);
  const out = { enabled: v.enabled === true, items };
  if (v.present === true) out.present = true; // v0.4.65 automatic presentation proposals (off unless ticked)
  const look = cleanLook(v.look);
  if (Object.keys(look).length) out.look = look; // v0.4.63 the cinematic graphics' project look (the server checks it)
  return out;
}

// v0.4.63 A look keeps only the choices made: an empty one follows the project (a graphic) or the designs (the project).
export function cleanLook(look) {
  const out = {};
  for (const [k, v] of Object.entries(look && typeof look === "object" ? look : {})) {
    if (v === undefined || v === null || v === "" || (v === false && k !== "mirror")) continue; // v0.4.64: mirror false = as designed (a graphic)
    if (k === "palettes") {
      const p = Object.fromEntries(Object.entries(v || {}).filter(([, x]) => x));
      if (Object.keys(p).length) out.palettes = p;
    } else out[k] = v;
  }
  if (!out.vary) delete out.seed;
  if (out.background !== "photo") delete out.photo_id;
  if (out.background !== "still") delete out.still_at;
  if (!out.background || out.background === "own") delete out.dim;
  if (out.place && typeof out.place !== "object") delete out.place;
  return out;
}

// What the preview shows at `time`: the graphic you are editing (even a suggestion or a draft),
// else the approved graphics that will be exported.
export function graphicAt(motion, time, selectedId) {
  const m = normaliseMotion(motion);
  const inside = (x) => time >= x.start && time < x.end;
  const sel = m.items.find((x) => x.id === selectedId);
  if (sel && inside(sel)) return { item: sel, exported: m.enabled && sel.status === "approved" };
  const ap = m.enabled && m.items.find((x) => x.status === "approved" && inside(x));
  return ap ? { item: ap, exported: true } : null;
}

// v0.4.62 Every graphic on screen at `time`, bottom first, as the export stacks them: back-to-back cinematic
// graphics overlap while the later one fades in over the earlier one. The one you are editing shows alone.
export function graphicsAt(motion, time, selectedId) {
  const m = normaliseMotion(motion);
  const inside = (x) => time >= x.start && time < x.end;
  const sel = m.items.find((x) => x.id === selectedId);
  if (sel && inside(sel)) return [{ item: sel, exported: m.enabled && sel.status === "approved" }];
  if (!m.enabled) return [];
  return m.items.filter((x) => x.status === "approved" && inside(x)).sort((a, b) => a.start - b.start).map((item) => ({ item, exported: true }));
}

export const STATUS = { suggested: "Suggested", draft: "Draft", approved: "Approved" };
export const optionLabel = (opts, id) => {
  const o = opts.find((x) => (Array.isArray(x) ? x[0] : x) === id);
  return Array.isArray(o) ? o[1] : id;
};

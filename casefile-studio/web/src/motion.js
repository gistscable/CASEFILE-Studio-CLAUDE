// v0.4.52 Motion graphics: the editor side (the server draws every frame; see motion.py).
import SPEC_ALL from "./effectsSpec.json";

export const MG = SPEC_ALL.motion;
export const TEMPLATES = Object.fromEntries(MG.templates.map((t) => [t.id, t]));
const ids = (opts) => opts.map((o) => (Array.isArray(o) ? o[0] : o));
const clamp = (v, [lo, hi], d) => (Number.isFinite(+v) && v !== null && v !== "" ? Math.min(hi, Math.max(lo, +v)) : d);

// A light copy of motion.normalise_item (the server's is the one that counts).
export function normaliseItem(it) {
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
  return { enabled: v.enabled === true, items };
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

export const STATUS = { suggested: "Suggested", draft: "Draft", approved: "Approved" };
export const optionLabel = (opts, id) => {
  const o = opts.find((x) => (Array.isArray(x) ? x[0] : x) === id);
  return Array.isArray(o) ? o[1] : id;
};

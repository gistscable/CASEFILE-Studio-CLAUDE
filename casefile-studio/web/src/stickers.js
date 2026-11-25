// v0.4.49 Stickers over the picture: the same data and maths as stickers.py.
import SPEC from "./effectsSpec.json" with { type: "json" };
import { interpolate, PIC } from "./picture.js";

export const ST = SPEC.stickers;
export const CATALOG = Object.fromEntries(ST.catalog.map((c) => [c.id, c]));
const FPS = 24;
const num = (v, [lo, hi], d) => (v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v)) ? Math.min(hi, Math.max(lo, Number(v))) : d);
const r = (n, k = 4) => Math.round(n * 10 ** k) / 10 ** k;

export function normaliseStickers(list, assets = null) {
  if (!Array.isArray(list)) return [];
  const L = ST.limits;
  const out = [];
  list.slice(0, ST.max).forEach((s, i) => {
    if (!s || typeof s !== "object") return;
    if (s.kind === "image") {
      if (!s.asset_id || (assets && !assets.some((a) => a.id === s.asset_id && a.kind === "image"))) return;
    } else if (!CATALOG[s.kind]) return;
    const cat = CATALOG[s.kind] || { size: 0.25, x: 0.5, y: 0.5 };
    const length = num(s.length, L.length, ST.defaults.length);
    const st = {
      id: String(s.id || "").replace(/[^\w-]/g, "").slice(0, 24) || `st${i + 1}`,
      kind: s.kind,
      start: r(num(s.start, [0, 86400], 0), 3),
      length: r(length, 3),
      x: r(num(s.x, L.xy, cat.x)),
      y: r(num(s.y, L.xy, cat.y)),
      size: r(num(s.size, L.size, cat.size)),
      opacity: r(num(s.opacity, L.opacity, ST.defaults.opacity), 3),
    };
    if (s.kind === "image") st.asset_id = String(s.asset_id);
    st.keyframes = normaliseStickerKeys(s.keyframes, length, st);
    out.push(st);
  });
  return out;
}

export function normaliseStickerKeys(v, length, base) {
  if (!Array.isArray(v)) return [];
  const L = ST.limits;
  const out = new Map();
  for (const k of v.slice(0, PIC.keyframes.max * 2)) {
    if (!k || typeof k !== "object") continue;
    const t = num(k.t, [0, length], null);
    if (t === null) continue;
    out.set(r(t, 3), {
      t: r(t, 3),
      x: r(num(k.x, L.xy, base.x)),
      y: r(num(k.y, L.xy, base.y)),
      size: r(num(k.size, L.size, base.size)),
      opacity: r(num(k.opacity, L.opacity, base.opacity), 3),
      ease: k.ease === "linear" ? "linear" : "smooth",
    });
  }
  return [...out.keys()].sort((a, b) => a - b).map((t) => out.get(t)).slice(0, PIC.keyframes.max);
}

// Same as stickers.sample: where and how strong `local` seconds after it starts
// (it pops in, and fades out quickly at its end).
export function stickerAt(st, local) {
  const v = interpolate(st.keyframes, local, ["x", "y", "size", "opacity"]) || { x: st.x, y: st.y, size: st.size, opacity: st.opacity };
  const f = Math.min(ST.fade, st.length / 4);
  const a = f > 0 ? Math.min(1, Math.max(0, (st.length - local) / f)) : 1;
  return { ...v, opacity: v.opacity * a, raw: v.opacity };
}

export function stickerAspect(st, assets = []) {
  if (st.kind === "image") {
    const a = assets.find((x) => x.id === st.asset_id) || {};
    return (Number(a.width) || 1) / (Number(a.height) || 1);
  }
  return CATALOG[st.kind]?.aspect || 1;
}

export function cycleFrames(kind) {
  const c = CATALOG[kind];
  return c && c.animated ? Math.max(1, Math.round(c.cycle * FPS)) : 1;
}

export function stickerFrameUrl(kind, local) {
  const n = cycleFrames(kind);
  const i = n > 1 ? ((Math.floor(Math.max(0, local) * FPS) % n) + n) % n : 0;
  return `/api/stickers/${kind}/${i}.png`;
}

export function stickerLabel(st, assets = []) {
  if (st.kind === "image") return assets.find((a) => a.id === st.asset_id)?.name || "Your sticker";
  return CATALOG[st.kind]?.label || st.kind;
}

export function newSticker(kind, start, assetId, existing = []) {
  const cat = CATALOG[kind] || { size: 0.25, x: 0.5, y: 0.5 };
  let n = existing.length + 1;
  while (existing.some((s) => s.id === `st${n}`)) n++;
  return {
    id: `st${n}`,
    kind,
    ...(assetId ? { asset_id: assetId } : {}),
    start: Math.round(start * 1000) / 1000,
    length: ST.defaults.length,
    x: cat.x,
    y: cat.y,
    size: cat.size,
    opacity: ST.defaults.opacity,
    keyframes: [],
  };
}

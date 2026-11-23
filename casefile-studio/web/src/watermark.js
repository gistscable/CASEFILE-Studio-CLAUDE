// v0.4.36 Logo watermark, preview side. Same numbers as watermark.py.
import SPEC from "./effectsSpec.json" with { type: "json" };

const W = SPEC.watermark;
export const WM_POSITIONS = W.positions;
export const WM_DEFAULTS = W.defaults;

export function normaliseWatermark(v) {
  const o = v && typeof v === "object" ? v : {};
  const n = (x, [lo, hi], d) => (x !== null && x !== "" && Number.isFinite(Number(x)) ? Math.min(hi, Math.max(lo, Number(x))) : d);
  return {
    ...W.defaults,
    enabled: o.enabled === true,
    asset_id: o.asset_id || null,
    position: W.positions.includes(o.position) ? o.position : W.defaults.position,
    size: n(o.size, W.limits.size, W.defaults.size),
    opacity: n(o.opacity, W.limits.opacity, W.defaults.opacity),
  };
}

export function watermarkBox(fw, fh, iw, ih, position, size) {
  const short = Math.min(fw, fh);
  let w = short * size;
  let h = (w * ih) / Math.max(1, iw);
  if (h > short * size) {
    h = short * size;
    w = (h * iw) / Math.max(1, ih);
  }
  const m = short * W.margin;
  let row = "middle",
    col = "center";
  if (position !== "center") [row, col] = position.split("-");
  const x = { left: m, center: (fw - w) / 2, right: fw - m - w }[col];
  const y = { top: m, middle: (fh - h) / 2, bottom: fh - m - h }[row];
  return { x, y, w, h };
}

// v0.4.49 Crop, fill and keyframes for a scene's picture: the same maths as
// picture.py (numbers in effectsSpec.json), so the preview matches the export.
import SPEC from "./effectsSpec.json" with { type: "json" };

export const PIC = SPEC.picture;
export const FIT_IDS = PIC.fits.map((f) => f.id);
const num = (v, lo, hi, d) => (v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v)) ? Math.min(hi, Math.max(lo, Number(v))) : d);
const r = (n, k = 4) => Math.round(n * 10 ** k) / 10 ** k;

export function normaliseCrop(v) {
  if (!Array.isArray(v) || v.length !== 4) return null;
  const n = v.map((x) => num(x, 0, 1, null));
  if (n.some((x) => x === null)) return null;
  const [x0, x1] = [Math.min(n[0], n[2]), Math.max(n[0], n[2])];
  const [y0, y1] = [Math.min(n[1], n[3]), Math.max(n[1], n[3])];
  if (x1 - x0 < PIC.crop_min || y1 - y0 < PIC.crop_min) return null;
  const box = [r(x0), r(y0), r(x1), r(y1)];
  return box.join() === "0,0,1,1" ? null : box;
}

export const cropOf = (asset) => normaliseCrop(asset?.crop);

// Same as picture.fit_of: a cropped file shows over a blur of itself unless
// the scene picks cover.
export function fitOf(project, scene, asset) {
  if (FIT_IDS.includes(scene?.fit)) return scene.fit;
  if (project?.aspect === "9:16" && (project?.vertical_fit || "blur") === "blur") return "legacy-blur";
  return normaliseCrop(asset?.crop) ? "blur" : "cover";
}

// The whole source picture, placed so its crop covers a W x H frame (centred).
export function coverBox(W, H, sw, sh, crop) {
  const [x0, y0, x1, y1] = crop || [0, 0, 1, 1];
  const cw = sw * (x1 - x0);
  const ch = sh * (y1 - y0);
  const s = Math.max(W / cw, H / ch);
  return { left: W / 2 - (sw * x0 + cw / 2) * s, top: H / 2 - (sh * y0 + ch / 2) * s, width: sw * s, height: sh * s };
}

// The crop shown whole, inside `inset` of the frame: a window, and the source inside it.
export function containBox(W, H, sw, sh, crop, inset = 1) {
  const [x0, y0, x1, y1] = crop || [0, 0, 1, 1];
  const cw = sw * (x1 - x0);
  const ch = sh * (y1 - y0);
  const s = Math.min((W * inset) / cw, (H * inset) / ch);
  const ww = cw * s;
  const wh = ch * s;
  return {
    box: { left: (W - ww) / 2, top: (H - wh) / 2, width: ww, height: wh },
    img: { left: -sw * x0 * s, top: -sh * y0 * s, width: sw * s, height: sh * s },
  };
}

// ---------------------------------------------------------------- keyframes

// v0.4.74/75 keyframe speed — same as picture.ease / EASES / STICKER_EASES.
export const EASES = ["linear", "smooth", "in", "out", "snap", "bounce", "hold"];
export const STICKER_EASES = [...EASES, "anticipate", "overshoot", "elastic"];
export const EASE_LABELS = {
  linear: "Steady", smooth: "Smooth", in: "Speed up", out: "Slow down", snap: "Fast middle", bounce: "Bounce",
  hold: "Jump", anticipate: "Pull back", overshoot: "Overshoot", elastic: "Spring",
};
export const EASE_HINTS = {
  linear: "The same speed all the way",
  smooth: "Starts and ends gently",
  in: "Starts slow, ends fast",
  out: "Starts fast, ends slow",
  snap: "Very gentle start and end, quick in the middle",
  bounce: "Lands and bounces, like a ball",
  hold: "Stays still, then jumps at the next keyframe",
  anticipate: "Moves back a little first, then goes",
  overshoot: "Goes a little past, then settles",
  elastic: "Wobbles into place, like a spring",
};
export const easeKind = (v, allowed = EASES) => (allowed.includes(v) ? v : "smooth");

const B1 = 1.70158, B3 = 2.70158, N1 = 7.5625, D1 = 2.75, C4 = (2 * Math.PI) / 3, LN2x10 = 10 * Math.log(2);
export function ease(u, kind) {
  const x = Math.min(1, Math.max(0, u));
  switch (kind) {
    case "linear": return x;
    case "in": return x * x * x;
    case "out": return 1 - (1 - x) ** 3;
    case "snap": return x < 0.5 ? 16 * x ** 5 : 1 - (2 - 2 * x) ** 5 / 2;
    case "bounce": {
      if (x < 1 / D1) return N1 * x * x;
      if (x < 2 / D1) { const v = x - 1.5 / D1; return N1 * v * v + 0.75; }
      if (x < 2.5 / D1) { const v = x - 2.25 / D1; return N1 * v * v + 0.9375; }
      const v = x - 2.625 / D1;
      return N1 * v * v + 0.984375;
    }
    case "hold": return x >= 1 ? 1 : 0;
    case "anticipate": return B3 * x * x * x - B1 * x * x;
    case "overshoot": { const v = x - 1; return 1 + B3 * v * v * v + B1 * v * v; }
    case "elastic": return Math.exp(-LN2x10 * x) * Math.sin((10 * x - 0.75) * C4) + 1;
    default: return x * x * (3 - 2 * x);
  }
}

// v0.4.75 manual speed: one move (keyframe i → i+1) takes `seconds`; the later keyframes shift with it.
// null when it would run past `length`.
export function setSegment(keys, i, seconds, length) {
  if (!keys?.[i + 1]) return null;
  const d = Math.max(0.05, Math.round(seconds * 1000) / 1000) - (keys[i + 1].t - keys[i].t);
  const out = keys.map((k, j) => (j > i ? { ...k, t: Math.round((k.t + d) * 1000) / 1000 } : k));
  return out[out.length - 1].t > length + 1e-6 ? null : out;
}

// v0.4.75 the whole move takes `seconds` (first to last keyframe), every part in proportion.
export function setSpan(keys, seconds, length) {
  if (!keys || keys.length < 2) return null;
  const span = keys[keys.length - 1].t - keys[0].t;
  return span > 0 ? retimeKeys(keys, seconds / span, length) : null;
}

// v0.4.74 keyframe speed for the whole move: the keyframes closer together (factor < 1, faster)
// or further apart (slower), from the first one. null when it would run past `length`.
export function retimeKeys(keys, factor, length) {
  if (!keys?.length || keys.length < 2) return null;
  const t0 = keys[0].t;
  const out = keys.map((k) => ({ ...k, t: Math.round((t0 + (k.t - t0) * factor) * 1000) / 1000 }));
  if (out[out.length - 1].t > length + 1e-6) return null;
  if (out.some((k, i) => i && k.t - out[i - 1].t < 0.04)) return null; // too close to tell apart
  return out;
}

// Same as picture.interpolate.
export function interpolate(keys, t, fields) {
  if (!keys?.length) return null;
  const pick = (k) => Object.fromEntries(fields.map((f) => [f, k[f]]));
  if (t <= keys[0].t) return pick(keys[0]);
  for (let i = 0; i + 1 < keys.length; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (t < b.t) {
      const span = b.t - a.t;
      const e = ease(span > 0 ? (t - a.t) / span : 1, a.ease);
      return Object.fromEntries(fields.map((f) => [f, a[f] + (b[f] - a[f]) * e]));
    }
  }
  return pick(keys[keys.length - 1]);
}

const clampCentre = (c, z) => Math.min(1 - 0.5 / z, Math.max(0.5 / z, c));

// Same as picture.normalise_keyframes.
export function normaliseKeyframes(v, length = 600) {
  if (!Array.isArray(v)) return [];
  const [zl, zh] = PIC.keyframes.zoom;
  const out = new Map();
  for (const k of v.slice(0, PIC.keyframes.max * 2)) {
    if (!k || typeof k !== "object") continue;
    const t = num(k.t, 0, length, null);
    if (t === null) continue;
    const z = num(k.zoom, zl, zh, 1);
    out.set(r(t, 3), {
      t: r(t, 3),
      zoom: r(z),
      x: r(clampCentre(num(k.x, 0, 1, 0.5), z)),
      y: r(clampCentre(num(k.y, 0, 1, 0.5), z)),
      ease: easeKind(k.ease),
    });
  }
  return [...out.keys()].sort((a, b) => a - b).map((t) => out.get(t)).slice(0, PIC.keyframes.max);
}

export const cameraAt = (keys, t) => interpolate(keys, t, ["zoom", "x", "y"]) || { zoom: 1, x: 0.5, y: 0.5 };

// CSS for the frame-sized picture layer (transform-origin 0 0): shows the part
// of the frame around (x, y), `zoom` times bigger — as zoompan does.
export function cameraTransform(cam) {
  const z = cam.zoom;
  const x = clampCentre(cam.x, z);
  const y = clampCentre(cam.y, z);
  return `translate(${((0.5 - x * z) * 100).toFixed(3)}%, ${((0.5 - y * z) * 100).toFixed(3)}%) scale(${z.toFixed(4)})`;
}

// Put a keyframe at `t` (replacing one within 0.05 s), keeping them in order.
export function upsertKey(keys, t, values, normalise) {
  const near = (keys || []).find((k) => Math.abs(k.t - t) < 0.05);
  const at = near ? near.t : Math.round(t * 1000) / 1000;
  const rest = (keys || []).filter((k) => k !== near);
  return normalise([...rest, { ...(near || {}), ...values, t: at }]);
}

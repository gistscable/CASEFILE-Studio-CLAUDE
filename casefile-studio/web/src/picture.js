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

export function ease(u, kind) {
  const x = Math.min(1, Math.max(0, u));
  return kind === "linear" ? x : x * x * (3 - 2 * x);
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
      ease: k.ease === "linear" ? "linear" : "smooth",
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

// v0.4.72 Follow something on screen: a sticker that stays on a face, a car or a spot while
// it moves. The preview steps through the sticker's time; each picture is grabbed small and
// grey, and the patch under the sticker is found again in the next picture (normalised cross
// correlation, searched near where it was). The path becomes the sticker's keyframes, so you
// can fix any of them by hand, and the export draws exactly that.
import ST_SPEC from "./effectsSpec.json" with { type: "json" };

export const TRACK = {
  width: 240, // the picture is grabbed this wide
  step: 1 / 12, // seconds between pictures
  patch: [20, 48], // the patch followed (px at `width`), from the sticker's size (enough context
  // that a repeating pattern — windows, fence posts — is not mistaken for the next post along)
  search: 22, // px each way it may move between pictures
  lost: 0.42, // below this match, the thing is lost (it left the picture or the shot changed)
  learn: 0.12, // how much the patch takes after each picture (slow changes: light, turning)
  stay: 0.25, // a match this far from where it was heading costs up to this much score
  max: ST_SPEC.stickers.keyframes_max,
};

// RGBA (Uint8ClampedArray, w*h*4) to luma (Float32Array, w*h)
export function grey(rgba, w, h) {
  const g = new Float32Array(w * h);
  for (let i = 0, j = 0; i < g.length; i++, j += 4) g[i] = 0.299 * rgba[j] + 0.587 * rgba[j + 1] + 0.114 * rgba[j + 2];
  return g;
}

// the size×size patch whose top-left is (x0, y0); null when it does not fit
export function patchAt(img, w, h, x0, y0, size) {
  if (x0 < 0 || y0 < 0 || x0 + size > w || y0 + size > h) return null;
  const p = new Float32Array(size * size);
  for (let y = 0; y < size; y++) p.set(img.subarray((y0 + y) * w + x0, (y0 + y) * w + x0 + size), y * size);
  return p;
}

function stats(p) {
  let m = 0;
  for (let i = 0; i < p.length; i++) m += p[i];
  m /= p.length;
  let v = 0;
  for (let i = 0; i < p.length; i++) v += (p[i] - m) ** 2;
  return [m, Math.sqrt(v)];
}

// best match of `tpl` (size×size) in `img` with its centre within `radius` px of (cx, cy):
// { x, y, score } (centre, pixels; score -1..1). `stay`: a far match loses up to this much
// (stay × (distance / radius)²), so it does not jump to a look-alike nearby.
export function match(img, w, h, tpl, size, cx, cy, radius, stay = 0) {
  const [tm, ts] = stats(tpl);
  const t0 = new Float32Array(tpl.length);
  for (let i = 0; i < tpl.length; i++) t0[i] = tpl[i] - tm;
  const half = size / 2;
  let best = { x: cx, y: cy, score: -2, fit: -9 };
  const xa = Math.max(0, Math.round(cx - half - radius));
  const xb = Math.min(w - size, Math.round(cx - half + radius));
  const ya = Math.max(0, Math.round(cy - half - radius));
  const yb = Math.min(h - size, Math.round(cy - half + radius));
  for (let y0 = ya; y0 <= yb; y0++) {
    for (let x0 = xa; x0 <= xb; x0++) {
      let s = 0;
      let sum = 0;
      let sq = 0;
      for (let y = 0; y < size; y++) {
        const row = (y0 + y) * w + x0;
        const tr = y * size;
        for (let x = 0; x < size; x++) {
          const v = img[row + x];
          s += v * t0[tr + x];
          sum += v;
          sq += v * v;
        }
      }
      const n = size * size;
      const sd = Math.sqrt(Math.max(0, sq - (sum * sum) / n));
      // a flat patch (no detail) matches nothing well: treat it as a weak match
      const score = ts < 1e-3 || sd < 1e-3 ? 0 : s / (ts * sd);
      const d = Math.hypot(x0 + half - cx, y0 + half - cy);
      const fit = score - (stay ? stay * (d / Math.max(1, radius)) ** 2 : 0);
      // ties go to the nearer place, so a still picture does not drift
      if (fit > best.fit + 1e-6 || (Math.abs(fit - best.fit) <= 1e-6 && d < Math.hypot(best.x - cx, best.y - cy)))
        best = { x: x0 + half, y: y0 + half, score, fit };
    }
  }
  return best;
}

// The patch size (px at `w`) for a sticker `size` (fraction of the frame width) wide
export function patchSize(size, w = TRACK.width) {
  const [lo, hi] = TRACK.patch;
  return Math.max(lo, Math.min(hi, Math.round(size * w))) & ~1;
}

// A tracker: `start(frame, x, y, size)` then `next(frame)` for each picture.
// `frame` is { data: Float32Array luma, w, h }; positions are fractions of the frame.
export function makeTracker() {
  let tpl = null;
  let size = 0;
  let at = null;
  let vel = { x: 0, y: 0 }; // px per picture, smoothed: where it is heading
  return {
    start(f, x, y, sz) {
      size = Math.min(patchSize(sz, f.w), (Math.min(f.w, f.h) - 2) & ~1);
      at = { x: x * f.w, y: y * f.h };
      const x0 = Math.round(at.x - size / 2);
      const y0 = Math.round(at.y - size / 2);
      const cx0 = Math.max(0, Math.min(f.w - size, x0));
      const cy0 = Math.max(0, Math.min(f.h - size, y0));
      tpl = patchAt(f.data, f.w, f.h, cx0, cy0, size);
      // the point you marked, relative to the patch (it may sit off-centre at the frame edge)
      at.dx = at.x - (cx0 + size / 2);
      at.dy = at.y - (cy0 + size / 2);
      at.x = cx0 + size / 2;
      at.y = cy0 + size / 2;
      vel = { x: 0, y: 0 };
      return !!tpl;
    },
    next(f) {
      const px = at.x + vel.x;
      const py = at.y + vel.y;
      const m = match(f.data, f.w, f.h, tpl, size, px, py, Math.round((TRACK.search * f.w) / TRACK.width), TRACK.stay);
      if (m.score < TRACK.lost) return { lost: true, score: m.score };
      vel = { x: 0.5 * vel.x + 0.5 * (m.x - at.x), y: 0.5 * vel.y + 0.5 * (m.y - at.y) };
      at = { ...at, x: m.x, y: m.y };
      const p = patchAt(f.data, f.w, f.h, Math.round(m.x - size / 2), Math.round(m.y - size / 2), size);
      if (p) for (let i = 0; i < tpl.length; i++) tpl[i] = tpl[i] * (1 - TRACK.learn) + p[i] * TRACK.learn;
      return { lost: false, score: m.score, x: (m.x + at.dx) / f.w, y: (m.y + at.dy) / f.h };
    },
  };
}

// Fewer keyframes, same path: drop a point when the line between its neighbours passes within
// `tol` (fraction of the frame) of it, then at most `max` (Ramer–Douglas–Peucker on x, y over t).
export function simplifyPath(pts, tol = 0.004, max = TRACK.max) {
  if (pts.length <= 2) return pts.slice();
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const err = (a, b, i) => {
    const p = pts[i];
    const q = (p.t - pts[a].t) / (pts[b].t - pts[a].t || 1);
    return Math.hypot(pts[a].x + (pts[b].x - pts[a].x) * q - p.x, pts[a].y + (pts[b].y - pts[a].y) * q - p.y);
  };
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let worst = -1;
    let d = tol;
    for (let i = a + 1; i < b; i++) {
      const e = err(a, b, i);
      if (e > d) [d, worst] = [e, i];
    }
    if (worst >= 0) {
      keep[worst] = 1;
      stack.push([a, worst], [worst, b]);
    }
  }
  let out = pts.filter((_, i) => keep[i]);
  if (out.length > max) {
    // still too many (a long, busy path): even spacing through what is left
    const n = out.length;
    out = Array.from({ length: max }, (_, i) => out[Math.round((i * (n - 1)) / (max - 1))]);
  }
  return out;
}

// v0.4.72 Grab the picture (no stickers, captions or graphics) from the preview frame `box`:
// every scene <img>/<video> drawn where the page draws it (its movement and crop included).
export function grabFrame(box, w = TRACK.width) {
  const fr = box.getBoundingClientRect();
  if (!fr.width || !fr.height) return null;
  const h = Math.max(8, Math.round((w * fr.height) / fr.width));
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, w, h);
  const k = w / fr.width;
  for (const el of box.querySelectorAll(".fx-media .pic-media")) {
    if (el.closest(".pic-bg")) continue;
    const ready = el.tagName === "VIDEO" ? el.readyState >= 2 : el.complete && el.naturalWidth;
    if (!ready) continue;
    const r = el.getBoundingClientRect();
    const win = el.closest(".pic-window")?.getBoundingClientRect();
    ctx.save();
    if (win) {
      ctx.beginPath();
      ctx.rect((win.left - fr.left) * k, (win.top - fr.top) * k, win.width * k, win.height * k);
      ctx.clip();
    }
    try {
      ctx.drawImage(el, (r.left - fr.left) * k, (r.top - fr.top) * k, r.width * k, r.height * k);
    } catch {
      ctx.restore();
      return null;
    }
    ctx.restore();
  }
  try {
    return { data: grey(ctx.getImageData(0, 0, w, h).data, w, h), w, h };
  } catch {
    return null; // a picture from another site the browser will not let us read
  }
}

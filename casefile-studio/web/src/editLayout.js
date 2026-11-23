// v0.4.24 Edit page layout helpers (CapCut-style): panel sizes the producer
// drags, ruler ticks that suit the zoom, and caption blocks for the T1 track.

export const LAYOUT_DEFAULTS = {
  left: 240,
  right: 300,
  timeline: 262,
  showLeft: true,
  showRight: true,
  compact: true,
  director: true,
};

export const LIMITS = {
  left: [170, 460],
  right: [240, 480],
  timeline: [150, 620],
};

const clampNum = (v, [lo, hi], fallback) => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, Math.round(n))) : fallback;
};

export function normaliseLayout(raw) {
  let v = raw;
  if (typeof raw === "string") {
    try {
      v = JSON.parse(raw);
    } catch {
      v = null;
    }
  }
  v = v && typeof v === "object" ? v : {};
  const out = { ...LAYOUT_DEFAULTS };
  for (const k of ["left", "right", "timeline"]) out[k] = clampNum(v[k], LIMITS[k], LAYOUT_DEFAULTS[k]);
  for (const k of ["showLeft", "showRight", "compact", "director"])
    if (typeof v[k] === "boolean") out[k] = v[k];
  return out;
}

// Keep the preview usable: the timeline may not take more than the grid
// height minus `minTop`.
export function timelineHeight(wanted, gridHeight, minTop = 230) {
  const [lo, hi] = LIMITS.timeline;
  const room = Math.max(lo, (gridHeight || 0) - minTop);
  return Math.max(lo, Math.min(hi, room, wanted));
}

const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];

// Major ticks at least `minPx` apart, with up to 4 minor ticks between.
export function rulerTicks(duration, widthPx, minPx = 90) {
  if (!(duration > 0) || !(widthPx > 0)) return { step: 0, major: [], minor: [] };
  const pxPerSec = widthPx / duration;
  const step = STEPS.find((s) => s * pxPerSec >= minPx) || STEPS[STEPS.length - 1];
  const sub = step >= 60 ? (step / 60 >= 5 ? 5 : step / 60 >= 2 ? 4 : 4) : step >= 10 ? 5 : step >= 2 ? 4 : 2;
  const major = [];
  const minor = [];
  for (let t = 0; t <= duration + 1e-6; t += step) {
    major.push(Number(t.toFixed(3)));
    for (let k = 1; k < sub; k++) {
      const m = t + (step * k) / sub;
      if (m < duration) minor.push(Number(m.toFixed(3)));
    }
  }
  return { step, major, minor };
}

// Caption blocks across the whole timeline, from each scene's exact captions
// when it has them, otherwise in even 9-word chunks of its narration (the
// same chunks the preview shows).
export function captionBlocks(scenes, offsets, clean = (s) => s) {
  const out = [];
  scenes.forEach((s, i) => {
    const base = offsets[i] || 0;
    if (s.captions?.length) {
      s.captions.forEach((c, k) => {
        const start = Math.max(0, Number(c.start) || 0);
        const end = Math.min(s.duration, Number(c.end) || 0);
        if (end > start) out.push({ key: `${s.id}-${k}`, sceneId: s.id, index: i, start: base + start, end: base + end, text: c.text || "" });
      });
      return;
    }
    const words = clean(s.narration || "").split(/\s+/).filter(Boolean);
    if (!words.length || !(s.duration > 0)) return;
    const chunks = Math.ceil(words.length / 9);
    for (let k = 0; k < chunks; k++) {
      out.push({
        key: `${s.id}-${k}`,
        sceneId: s.id,
        index: i,
        start: base + (s.duration * k) / chunks,
        end: base + (s.duration * (k + 1)) / chunks,
        text: words.slice(k * 9, k * 9 + 9).join(" "),
      });
    }
  });
  return out;
}

// Zoom around the pointer: returns the new scrollLeft that keeps the time
// under the pointer in place.
export function zoomScroll(scrollLeft, pointerX, oldZoom, newZoom) {
  const at = (scrollLeft + pointerX) / oldZoom;
  return Math.max(0, at * newZoom - pointerX);
}

// v0.4.26 Effects and transitions for the preview. Shares effectsSpec.json
// with effects.py; the export is exact, the preview shows the same idea.
import SPEC from "./effectsSpec.json" with { type: "json" };
import { FONTS, textUnit } from "./captionStyle.js";

export const TRANSITIONS = SPEC.transitions;
export const MOTIONS = SPEC.motions;
export const LOOKS = SPEC.looks;
export const LT = SPEC.lower_third;
export const FORMATS = SPEC.formats;
export const FITS = SPEC.fits;
export const aspectOf = (project) => (FORMATS[project?.aspect] ? project.aspect : "16:9");
export const fitOf = (project) => (FITS.some((f) => f.id === project?.vertical_fit) ? project.vertical_fit : "blur");

export function transitionId(v) {
  const id = SPEC.legacy_transitions[v] || v;
  return TRANSITIONS.some((t) => t.id === id) ? id : "none";
}

// Same rule as effects.transition_length.
export function transitionLength(scene, duration) {
  const id = transitionId(scene?.transition);
  if (id === "none") return 0;
  let d = Number(scene?.transition_duration) || 0;
  if (d <= 0) d = 0.5;
  return Math.round(Math.max(0, Math.min(d, duration / 2, 2)) * 1000) / 1000;
}

export function normaliseEffects(v) {
  const o = v && typeof v === "object" ? v : {};
  const n = (x, d) => (Number.isFinite(Number(x)) ? Math.min(1, Math.max(0, Number(x))) : d);
  return { grain: n(o.grain, 0), vignette: n(o.vignette, 0), letterbox: o.letterbox === true };
}

export function lookOf(id) {
  return LOOKS.find((l) => l.id === id) || LOOKS.find((l) => l.id === "noir");
}

// The transform the export's zoompan makes at progress p (0..1) of the scene.
export function motionTransform(motion, p) {
  const t = Math.min(1, Math.max(0, p));
  switch (motion) {
    case "slow-zoom":
      return `scale(${1 + 0.075 * t})`;
    case "slow-zoom-out":
      return `scale(${1.075 - 0.075 * t})`;
    case "pan-left":
      return `translateX(${((t - 0.5) * 8).toFixed(3)}%) scale(1.08)`;
    case "pan-right":
      return `translateX(${((0.5 - t) * 8).toFixed(3)}%) scale(1.08)`;
    case "pan-up":
      return `translateY(${((t - 0.5) * 8).toFixed(3)}%) scale(1.08)`;
    case "pan-down":
      return `translateY(${((0.5 - t) * 8).toFixed(3)}%) scale(1.08)`;
    case "ken-burns": {
      const z = 1 + 0.1 * t;
      return `translateX(${((z - 1) * (0.15 - 0.3 * t) * 100).toFixed(3)}%) scale(${z})`;
    }
    default:
      return undefined;
  }
}

// How the incoming scene looks at progress q (0..1) of its transition.
export function transitionStyle(id, q) {
  const e = Math.min(1, Math.max(0, q));
  switch (transitionId(id)) {
    case "dissolve":
    case "fade":
      return { opacity: e };
    case "dip-black":
      return { opacity: Math.max(0, e * 2 - 1) };
    case "dip-white":
      return { opacity: Math.max(0, e * 2 - 1) };
    case "slide-left":
      return { transform: `translateX(${(1 - e) * 100}%)` };
    case "slide-up":
      return { transform: `translateY(${(1 - e) * 100}%)` };
    case "wipe-left":
      return { clipPath: `inset(0 0 0 ${(1 - e) * 100}%)` };
    case "zoom":
      return { opacity: e, transform: `scale(${1.25 - 0.25 * e})` };
    case "circle": {
      // ffmpeg's circleopen has a soft edge; a soft mask matches it.
      const r = Math.min(110, e * 150);
      const mask = `radial-gradient(circle farthest-corner at 50% 50%, #000 ${Math.max(0, r - 18).toFixed(2)}%, transparent ${r.toFixed(2)}%)`;
      return { WebkitMaskImage: mask, maskImage: mask };
    }
    case "pixelize":
      return { filter: `blur(${((1 - e) * 10).toFixed(2)}px)`, opacity: 0.4 + 0.6 * e };
    default:
      return {};
  }
}

// What shows under the incoming scene: the previous scene (dissolve, slide,
// wipe…), black (dips and fades) or white (flash).
export function transitionUnder(id, q) {
  const t = transitionId(id);
  if (t === "dip-black" || t === "fade") return { colour: "#000", prevOpacity: t === "dip-black" ? Math.max(0, 1 - q * 2) : 0 };
  if (t === "dip-white") return { colour: "#fff", prevOpacity: Math.max(0, 1 - q * 2) };
  return { colour: null, prevOpacity: 1 };
}

// Same as effects.lower_third_bottom: above a footage label, with a gap.
export function lowerThirdBottom(width, height, lift = false) {
  const f = FORMATS[height > width ? "9:16" : "16:9"];
  return lift ? Math.max(f.lower_third_bottom, 1 - f.label_top + 0.03) : f.lower_third_bottom;
}

export function splitWho(who) {
  const w = String(who || "").replace(/\s+/g, " ").trim();
  const m = w.match(/^(.*?)\s*[([](.+?)[)\]]\s*$/);
  const [name, role] = m ? [m[1], m[2]] : [w, ""];
  return { name: name.slice(0, 80), role: role ? (role[0].toUpperCase() + role.slice(1)).slice(0, 100) : "" };
}

export function normaliseNameCards(v) {
  const o = v && typeof v === "object" ? v : {};
  const people = {};
  for (const [sid, p] of Object.entries(o.people || {})) {
    if (!/^[A-Z]{1,3}\d{1,3}$/.test(sid) || !p || typeof p !== "object") continue;
    const name = String(p.name || "").replace(/\s+/g, " ").trim().slice(0, 80);
    const role = String(p.role || "").replace(/\s+/g, " ").trim().slice(0, 100);
    if (name || role) people[sid] = { name, role, on: p.on !== false };
  }
  return { auto: o.auto === true, people };
}

const sceneSource = (s) => s.guide_source_id || s.guide_primary_source_id || "";

// Same as effects.effective_lower_thirds: {scene index: card}.
export function effectiveLowerThirds(project) {
  const nc = normaliseNameCards(project?.name_cards);
  const out = {};
  const seen = new Set();
  (project?.scenes || []).forEach((s, i) => {
    const own = s.lower_third && (s.lower_third.name || s.lower_third.role) ? s.lower_third : null;
    const sid = sceneSource(s);
    if (own) {
      out[i] = own;
      if (sid) seen.add(sid);
    } else if (nc.auto && sid && !seen.has(sid)) {
      const p = nc.people[sid];
      if (p && p.on) {
        out[i] = { name: p.name, role: p.role, auto: true };
        seen.add(sid);
      }
    }
  });
  return out;
}

export function lowerThirdCss(width, height, lift = false) {
  const f = FONTS[LT.font];
  const unit = textUnit(width, height);
  const bottom = lowerThirdBottom(width, height, lift);
  return {
    wrap: {
      position: "absolute",
      left: `${LT.x * 100}%`,
      bottom: `${bottom * 100}%`,
      background: `rgba(0,0,0,${LT.box_opacity})`,
      padding: `${(LT.pad * unit).toFixed(2)}px`,
      fontFamily: `"cf-${LT.font}", sans-serif`,
      lineHeight: (1 / f.ratio).toFixed(4),
      color: "#fff",
      zIndex: 3,
      pointerEvents: "none",
    },
    name: { fontSize: `${(LT.name_size * unit).toFixed(2)}px`, display: "block" },
    role: { fontSize: `${(LT.role_size * unit).toFixed(2)}px`, color: "#E6E3D9", display: "block" },
  };
}

// Lower third visibility and slide-in at `local` seconds into the scene.
export function lowerThirdAt(lower, local, duration) {
  if (!lower || !(lower.name || lower.role)) return null;
  const end = Math.min(duration, LT.seconds);
  const start = Math.min(0.3, end / 4);
  if (local < start || local >= end) return null;
  const tIn = Math.min(1, (local - start) / 0.3);
  const fadeIn = Math.min(1, (local - start) / 0.25);
  const fadeOut = Math.min(1, (end - local) / 0.3);
  return { opacity: Math.min(fadeIn, fadeOut), shift: (1 - tIn) * -3 };
}

export const letterboxBar = (width, height) => (width > height ? Math.max(0, (height - width / 2.35) / 2) : 0);

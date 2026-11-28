import React from "react";
import { normaliseStickers, stickerAt, stickerAspect, stickerFrameUrl, cycleFrames, CATALOG, ST, regionOf, strengthOf, blurPx } from "./stickers.js";

// v0.4.49 Animated stickers load every frame once, so playback does not flicker.
const LOADED = new Set();
function preload(kind) {
  if (LOADED.has(kind) || !CATALOG[kind]) return;
  LOADED.add(kind);
  for (let i = 0; i < cycleFrames(kind); i++) {
    const im = new Image();
    im.src = `/api/stickers/${kind}/${i}.png`;
  }
}

const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));

// v0.4.72 the spotlight's dark layer: the same soft ellipse as stickers.region_frame
export function spotlightCss(cx, cy, rx, ry, alpha) {
  const soft = Math.round(ST.region_soft * 100);
  return `radial-gradient(${rx.toFixed(1)}px ${ry.toFixed(1)}px at ${cx.toFixed(1)}px ${cy.toFixed(1)}px, rgba(0,0,0,0) ${soft}%, rgba(0,0,0,${alpha.toFixed(3)}) 100%)`;
}

// v0.4.49 Your stickers over the preview, where the export puts them.
// Drag one to move it (with keyframes, that moves it at this moment).
// v0.4.72 The selected one has handles: the corner resizes it; on a box, a bar, a blur or a
// spotlight the right and bottom edges change its width or height. Regions draw as the export
// does: the spotlight darkens everything else, the blur blurs what is under it. `picking`: the
// next click on the picture is the thing to follow (onPick(x, y), fractions of the frame).
export default function StickerLayer({ project, time, width: W, height: H, selectedId, onSelect, onMove, onResize, picking = false, onPick, disabled }) {
  const assets = project.assets || [];
  const list = normaliseStickers(project.stickers, assets);
  const [drag, setDrag] = React.useState(null);
  React.useEffect(() => {
    list.forEach((s) => preload(s.kind));
  }, [project.stickers]);
  const shown = list.filter((s) => time >= s.start && time < s.start + s.length);
  if (!shown.length && !picking) return null;
  // one pointer gesture: move, or resize from a handle ("corner" | "right" | "bottom")
  const gesture = (e, s, v, mode) => {
    if (disabled || picking) return;
    e.preventDefault();
    e.stopPropagation();
    onSelect?.(s.id);
    const el = e.currentTarget;
    el.setPointerCapture?.(e.pointerId);
    const local = time - s.start;
    const ratio = stickerAspect(s, assets);
    const from = { px: e.clientX, py: e.clientY, x: v.x, y: v.y, size: v.size, ratio };
    const box = el.closest(".sticker-layer")?.getBoundingClientRect();
    const scale = box && box.width ? W / box.width : 1; // the frame may be drawn smaller (CSS)
    let last = null;
    const move = (ev) => {
      const dx = ((ev.clientX - from.px) * scale) / W;
      const dy = ((ev.clientY - from.py) * scale) / H;
      if (mode === "move") last = { id: s.id, x: from.x + dx, y: from.y + dy, size: from.size, ratio: from.ratio };
      else {
        const w0 = from.size * W;
        const h0 = w0 / from.ratio;
        let w = w0;
        let h = h0;
        if (mode === "corner") {
          const k = Math.max((w0 / 2 + dx * W) / (w0 / 2), (h0 / 2 + dy * H) / (h0 / 2));
          w = w0 * k;
          h = h0 * k;
        } else if (mode === "right") w = w0 + 2 * dx * W;
        else h = h0 + 2 * dy * H;
        const size = clamp(w / W, ST.limits.size);
        const r = mode === "corner" ? from.ratio : clamp((size * W) / Math.max(4, h), ST.limits.ratio);
        last = { id: s.id, x: from.x, y: from.y, size, ratio: r };
      }
      setDrag(last);
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      setDrag(null);
      if (!last) return;
      if (mode === "move") {
        if (Math.abs(last.x - from.x) > 0.002 || Math.abs(last.y - from.y) > 0.002) onMove?.(s.id, last.x, last.y, local);
      } else if (Math.abs(last.size - from.size) > 0.002 || Math.abs(last.ratio - from.ratio) > 0.005) {
        onResize?.(s.id, { size: last.size, ...(mode === "corner" ? {} : { ratio: last.ratio }) }, local);
      }
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  };
  return (
    <div className={`sticker-layer ${picking ? "picking" : ""}`}>
      {shown.map((s) => {
        const local = time - s.start;
        const v = stickerAt(s, local);
        const d = drag?.id === s.id ? drag : null;
        const pos = d ? { ...v, x: d.x, y: d.y, size: d.size } : v;
        const ratio = d ? d.ratio : stickerAspect(s, assets);
        const w = pos.size * W;
        const h = w / ratio;
        const region = regionOf(s);
        const cx = pos.x * W;
        const cy = pos.y * H;
        const sel = selectedId === s.id;
        const src = region ? null : s.kind === "image" ? assets.find((a) => a.id === s.asset_id)?.url : stickerFrameUrl(s.kind, local, d ? { ...s, ratio: undefined } : s);
        return (
          <React.Fragment key={s.id}>
            {region === "spot" && (
              <div className="sticker-spot" aria-hidden="true" style={{ background: spotlightCss(cx, cy, w / 2, h / 2, strengthOf(s) * v.opacity) }} />
            )}
            <div
              className={`sticker ${region ? `sticker-region r-${region}` : ""} ${sel ? "selected" : ""}`}
              title="Drag to move · drag a handle to resize · settings on the right"
              data-sticker={s.id}
              onPointerDown={(e) => gesture(e, s, v, "move")}
              style={{ left: cx - w / 2, top: cy - h / 2, width: w, height: h }}
            >
              {region === "blur" && (
                <i className="sticker-blur" style={{ backdropFilter: `blur(${blurPx(s, W).toFixed(1)}px)`, WebkitBackdropFilter: `blur(${blurPx(s, W).toFixed(1)}px)`, opacity: v.opacity }} />
              )}
              {src && <img src={src} alt="" draggable={false} style={{ opacity: v.opacity, objectFit: d && CATALOG[s.kind]?.ratio ? "fill" : undefined }} />}
              {sel && !disabled && !picking && (
                <>
                  <b className="st-handle corner" aria-label="Resize" onPointerDown={(e) => gesture(e, s, v, "corner")} />
                  {CATALOG[s.kind]?.ratio && (
                    <>
                      <b className="st-handle right" aria-label="Make it wider or narrower" onPointerDown={(e) => gesture(e, s, v, "right")} />
                      <b className="st-handle bottom" aria-label="Make it taller or shorter" onPointerDown={(e) => gesture(e, s, v, "bottom")} />
                    </>
                  )}
                </>
              )}
            </div>
          </React.Fragment>
        );
      })}
      {picking && (
        <div
          className="sticker-pick"
          role="button"
          aria-label="Click the thing to follow"
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            const r = e.currentTarget.getBoundingClientRect();
            onPick?.((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
          }}
        >
          <span>Click the thing to follow</span>
        </div>
      )}
    </div>
  );
}

import React from "react";
import { normaliseStickers, stickerAt, stickerAspect, stickerFrameUrl, cycleFrames, CATALOG } from "./stickers.js";

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

// v0.4.49 Your stickers over the preview, where the export puts them.
// Drag one to move it (with keyframes, that moves it at this moment).
export default function StickerLayer({ project, time, width: W, height: H, selectedId, onSelect, onMove, disabled }) {
  const assets = project.assets || [];
  const list = normaliseStickers(project.stickers, assets);
  const [drag, setDrag] = React.useState(null);
  React.useEffect(() => {
    list.forEach((s) => preload(s.kind));
  }, [project.stickers]);
  const shown = list.filter((s) => time >= s.start && time < s.start + s.length);
  if (!shown.length) return null;
  return (
    <div className="sticker-layer">
      {shown.map((s) => {
        const local = time - s.start;
        const v = stickerAt(s, local);
        const pos = drag?.id === s.id ? { ...v, x: drag.x, y: drag.y } : v;
        const w = pos.size * W;
        const h = w / stickerAspect(s, assets);
        const src = s.kind === "image" ? assets.find((a) => a.id === s.asset_id)?.url : stickerFrameUrl(s.kind, local);
        const start = (e) => {
          if (disabled) return;
          e.preventDefault();
          e.stopPropagation();
          onSelect?.(s.id);
          const el = e.currentTarget;
          el.setPointerCapture?.(e.pointerId);
          const from = { px: e.clientX, py: e.clientY, x: v.x, y: v.y };
          let last = null;
          const move = (ev) => {
            last = { id: s.id, x: from.x + (ev.clientX - from.px) / W, y: from.y + (ev.clientY - from.py) / H };
            setDrag(last);
          };
          const up = () => {
            el.removeEventListener("pointermove", move);
            el.removeEventListener("pointerup", up);
            el.removeEventListener("pointercancel", up);
            setDrag(null);
            if (last && (Math.abs(last.x - from.x) > 0.002 || Math.abs(last.y - from.y) > 0.002)) onMove?.(s.id, last.x, last.y, local);
          };
          el.addEventListener("pointermove", move);
          el.addEventListener("pointerup", up);
          el.addEventListener("pointercancel", up);
        };
        return (
          <div
            key={s.id}
            className={`sticker ${selectedId === s.id ? "selected" : ""}`}
            title="Drag to move · adjust it in the Stickers tab"
            onPointerDown={start}
            style={{ left: pos.x * W - w / 2, top: pos.y * H - h / 2, width: w, height: h }}
          >
            {src && <img src={src} alt="" draggable={false} style={{ opacity: v.opacity }} />}
          </div>
        );
      })}
    </div>
  );
}

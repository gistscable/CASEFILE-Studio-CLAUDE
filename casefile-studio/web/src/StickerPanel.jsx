import React from "react";
import { Plus, Trash2, Copy } from "lucide-react";
import { normaliseStickers, normaliseStickerKeys, stickerAt, stickerLabel, stickerFrameUrl, ST } from "./stickers.js";
import { upsertKey } from "./picture.js";
import { Step, clock, parseClock } from "./Effects.jsx";

const pct = (v) => `${Math.round(v * 100)}%`;

// v0.4.49 Stickers tab of the inspector: every sticker, and − / + for the selected one.
export default function StickerPanel({ project, time, selectedId, onSelect, onChange, onOpenDialog, onSeek, disabled }) {
  const assets = project.assets || [];
  const list = normaliseStickers(project.stickers, assets);
  const sorted = [...list].sort((a, b) => a.start - b.start);
  const sel = list.find((s) => s.id === selectedId);
  const save = (next) => onChange(next);
  const update = (id, patch) => save(list.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  // With keyframes, a change applies at the playhead (adding a keyframe there).
  const setLook = (s, patch) => {
    if (!s.keyframes.length) return update(s.id, patch);
    const local = Math.max(0, Math.min(s.length, time - s.start));
    const v = stickerAt(s, local);
    const near = s.keyframes.find((k) => Math.abs(k.t - local) < 0.05);
    update(s.id, { keyframes: upsertKey(s.keyframes, local, { x: v.x, y: v.y, size: v.size, opacity: v.raw, ...(near ? { ease: near.ease } : {}), ...patch }, (k) => normaliseStickerKeys(k, s.length, s)) });
  };
  return (
    <div className="inspector-content cs">
      <div className="section-label">
        <span>STICKERS</span>
        <button className="btn" disabled={disabled} onClick={onOpenDialog}>
          <Plus size={12} /> Add at the playhead
        </button>
      </div>
      {!list.length && <p className="micro-note block">No stickers yet. Click “Add at the playhead”, then drag the sticker in the preview to move it.</p>}
      <div className="st-list">
        {sorted.map((s) => (
          <button key={s.id} className={`st-item ${s.id === selectedId ? "on" : ""} ${time >= s.start && time < s.start + s.length ? "now" : ""}`}
            onClick={() => { onSelect(s.id); if (!(time >= s.start && time < s.start + s.length)) onSeek(s.start + 0.05); }}>
            <img src={s.kind === "image" ? assets.find((a) => a.id === s.asset_id)?.url : stickerFrameUrl(s.kind, 1.5)} alt="" />
            <span>{stickerLabel(s, assets)}</span>
            <small>{clock(s.start)} · {s.length.toFixed(1)} s{s.keyframes.length ? ` · ◆${s.keyframes.length}` : ""}</small>
          </button>
        ))}
      </div>
      {sel && (() => {
        const local = Math.max(0, Math.min(sel.length, time - sel.start));
        const inside = time >= sel.start && time < sel.start + sel.length;
        const v = stickerAt(sel, local);
        const at = sel.keyframes.find((k) => Math.abs(k.t - local) < 0.05);
        return (
          <div className="st-edit">
            <div className="section-label sub">
              <span>{stickerLabel(sel, assets).toUpperCase()}</span>
            </div>
            <Step label="Starts at" value={sel.start} display={clock(sel.start)} typed={parseClock} step={0.1} min={0} max={86400} disabled={disabled} onChange={(x) => update(sel.id, { start: x })} />
            <Step label="Length" value={sel.length} display={`${sel.length.toFixed(1)} s`} step={0.5} min={ST.limits.length[0]} max={ST.limits.length[1]} disabled={disabled}
              onChange={(x) => update(sel.id, { length: x, keyframes: sel.keyframes.filter((k) => k.t <= x) })} />
            <button className="text-link" disabled={disabled} onClick={() => update(sel.id, { start: Math.round(time * 1000) / 1000 })}>Start it at the playhead ({clock(time)})</button>
            <Step label="Size" value={v.size} display={pct(v.size)} step={0.01} min={ST.limits.size[0]} max={ST.limits.size[1]} disabled={disabled} onChange={(x) => setLook(sel, { size: x })} />
            <Step label="Opacity" value={v.raw} display={pct(v.raw)} step={0.05} min={ST.limits.opacity[0]} max={1} disabled={disabled} onChange={(x) => setLook(sel, { opacity: x })} />
            <Step label="Left ↔ right" value={v.x} display={pct(v.x)} step={0.01} min={ST.limits.xy[0]} max={ST.limits.xy[1]} disabled={disabled} onChange={(x) => setLook(sel, { x })} />
            <Step label="Up ↕ down" value={v.y} display={pct(v.y)} step={0.01} min={ST.limits.xy[0]} max={ST.limits.xy[1]} disabled={disabled} onChange={(y) => setLook(sel, { y })} />
            <div className="section-label sub">
              <span>KEYFRAMES · MAKE IT MOVE</span>
            </div>
            <p className="micro-note block">
              {sel.keyframes.length
                ? `Position, size and opacity follow the keyframes. At ${local.toFixed(2)} s: changes ${at ? "edit this keyframe" : "add a keyframe here"}. Dragging it in the preview does the same.`
                : "Add a keyframe, move the playhead, then drag the sticker or change a value: it moves between keyframes (for example an arrow that follows someone)."}
            </p>
            <div className="kf-list">
              {sel.keyframes.map((k, i) => (
                <div key={k.t} className={`kf-item ${at === k ? "on" : ""}`}>
                  <button className="kf-time" onClick={() => onSeek(sel.start + k.t + 0.001)}>◆ {k.t.toFixed(2)} s</button>
                  <span>{pct(k.x)}, {pct(k.y)} · {pct(k.size)}</span>
                  {i < sel.keyframes.length - 1 && (
                    <button className="text-link" disabled={disabled}
                      onClick={() => update(sel.id, { keyframes: sel.keyframes.map((x) => (x === k ? { ...x, ease: x.ease === "linear" ? "smooth" : "linear" } : x)) })}>
                      {k.ease === "linear" ? "Steady" : "Smooth"}
                    </button>
                  )}
                  <button className="danger-link" aria-label={`Remove keyframe at ${k.t.toFixed(2)} s`} disabled={disabled}
                    onClick={() => update(sel.id, { keyframes: sel.keyframes.filter((x) => x !== k) })}>×</button>
                </div>
              ))}
            </div>
            <div className="kf-actions">
              <button className="btn" disabled={disabled || !inside || !!at}
                onClick={() => update(sel.id, { keyframes: upsertKey(sel.keyframes, local, { x: v.x, y: v.y, size: v.size, opacity: v.raw }, (k) => normaliseStickerKeys(k, sel.length, sel)) })}>
                ◆ Add keyframe {inside ? `(${local.toFixed(2)} s)` : "(move the playhead onto it)"}
              </button>
              {sel.keyframes.length > 0 && <button className="text-link" disabled={disabled} onClick={() => update(sel.id, { keyframes: [] })}>Clear keyframes</button>}
            </div>
            <div className="st-actions">
              <button className="btn" disabled={disabled} onClick={() => {
                let n = list.length + 1;
                while (list.some((x) => x.id === `st${n}`)) n++;
                save([...list, { ...sel, id: `st${n}`, start: Math.round(time * 1000) / 1000 }]);
                onSelect(`st${n}`);
              }}>
                <Copy size={12} /> Copy at the playhead
              </button>
              <button className="danger-link" disabled={disabled} onClick={() => { save(list.filter((x) => x.id !== sel.id)); onSelect(null); }}>
                <Trash2 size={12} /> Remove sticker
              </button>
            </div>
          </div>
        );
      })()}
      <p className="micro-note block">Stickers sit over the picture and the subscribe animation; captions and your logo stay on top. Download MP4 includes them.</p>
    </div>
  );
}

import React from "react";
import { X, Upload, Plus } from "lucide-react";
import { ST } from "./stickers.js";

const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

// v0.4.69 The sticker tiles of one tab (Subscribe, Arrows & shapes, Yours). The Stickers tab
// on the left shows them as a grid (as CapCut does); the "Add at the playhead" dialog too.
export function StickerGallery({ tab, assets = [], onAdd, onUpload, grid = "sticker-grid" }) {
  const fileRef = React.useRef(null);
  const yours = assets.filter((a) => a.kind === "image" && (a.sticker || /\.png$|\.webp$|\.gif$/i.test(a.name || "")));
  const all = assets.filter((a) => a.kind === "image");
  const [showAll, setShowAll] = React.useState(false);
  const mine = showAll ? all : yours;
  return (
    <>
      {tab === "mark" && (
        <p className="micro-note block st-mark-note">
          Point at, box, blur or spotlight anything. Add one, drag it onto the face or object, then “Click what to follow” keeps it there while it moves.
        </p>
      )}
      <div className={grid}>
        {tab !== "yours" &&
          ST.catalog
            .filter((c) => c.tab === tab)
            .map((c) => (
              <button key={c.id} className="sticker-card" aria-label={`Add sticker ${c.label}`} title={`Add “${c.label}” at the playhead`} onClick={() => onAdd(c.id)}>
                {c.animated && <span className="sticker-badge">Animated</span>}
                <img src={`/api/stickers/${c.id}/${c.animated ? Math.round(c.cycle * 24 * 0.6) : 0}.png`} alt="" draggable={false}
                  style={{ maxWidth: c.aspect >= 1.5 ? "86%" : "56%" }} />
                <span>{c.label}</span>
                <i className="tile-add" aria-hidden="true"><Plus size={13} /></i>
              </button>
            ))}
        {tab === "yours" && (
          <>
            <button className="sticker-card sticker-upload" onClick={() => fileRef.current?.click()}>
              <Upload size={22} />
              <span>Upload a sticker</span>
              <small>PNG or WebP with a transparent background</small>
            </button>
            <input ref={fileRef} type="file" accept="image/png,image/webp,image/gif,image/jpeg" hidden
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onUpload(f); }} />
            {mine.map((a) => (
              <button key={a.id} className="sticker-card" aria-label={`Add sticker ${a.name}`} title={`Add “${a.name}” at the playhead`} onClick={() => onAdd("image", a.id)}>
                <img src={a.thumbnail && !/\.png$|\.webp$|\.gif$/i.test(a.name || "") ? a.thumbnail : a.url} alt="" draggable={false} style={{ maxWidth: "70%", maxHeight: "60%" }} />
                <span>{a.name}</span>
                <i className="tile-add" aria-hidden="true"><Plus size={13} /></i>
              </button>
            ))}
          </>
        )}
      </div>
      {tab === "yours" && all.length > yours.length && (
        <button className="text-link" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Show only stickers" : "Show all my pictures"}
        </button>
      )}
    </>
  );
}

// v0.4.49 "Stickers · add at the playhead": built-in stickers and your own.
export default function StickerDialog({ time, assets = [], onAdd, onUpload, onClose }) {
  const [tab, setTab] = React.useState("mark");
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal sticker-modal" role="dialog" aria-label="Stickers">
        <header className="sticker-head">
          <div>
            <span className="eyebrow">ADD AT THE PLAYHEAD</span>
            <h2>Stickers</h2>
          </div>
          <button className="icon-btn" aria-label="Close stickers" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <div className="sticker-tabs" role="tablist">
          {ST.tabs.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <StickerGallery tab={tab} assets={assets} onAdd={onAdd} onUpload={onUpload} />
        <p className="sticker-foot">
          Click a sticker to add it at the playhead ({fmt(time)}). Then adjust it with − / + in the Stickers tab, or drag it in the preview.
        </p>
      </div>
    </div>
  );
}

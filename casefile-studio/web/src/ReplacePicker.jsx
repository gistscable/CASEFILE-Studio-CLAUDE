import React, { useMemo, useRef, useState } from "react";
import { X, Upload, Search, CheckCircle2 } from "lucide-react";

// v0.4.33 Replace a scene's picture: thumbnails of every photo, clip and base
// image in the project, an upload, and where a clip should start. The scene
// keeps its exact length and narration; only the picture changes.

const isBase = (a) => /^BASE[-_]/i.test(a.name || "") || !!a.base_fill;

export default function ReplacePicker({ scene, assets, onPick, onUpload, onClose }) {
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState(scene.asset_id || null);
  const [start, setStart] = useState(0);
  const fileRef = useRef(null);
  const list = useMemo(
    () =>
      assets
        .filter((a) => ["image", "video"].includes(a.kind))
        .filter((a) => (filter === "all" ? true : filter === "base" ? isBase(a) : filter === "clips" ? a.kind === "video" : a.kind === "image" && !isBase(a)))
        .filter((a) => !q || (a.name || "").toLowerCase().includes(q.toLowerCase())),
    [assets, filter, q],
  );
  const pick = assets.find((a) => a.id === chosen);
  const long = pick?.kind === "video" ? Number(pick.video_duration || pick.duration || 0) : 0;
  return (
    <div className="modal-backdrop" role="dialog" aria-label="Replace the picture" onClick={onClose}>
      <div className="rp" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <h3>Replace the picture</h3>
            <p>
              Scene keeps its {Number(scene.duration).toFixed(1)} s and its narration; only the picture changes. Rebuilding from the guide keeps your choice.
            </p>
          </div>
          <button className="icon-button" aria-label="Close" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <div className="rp-bar">
          {[["all", "All"], ["base", "Base images"], ["clips", "Clips"], ["photos", "Photos"]].map(([k, l]) => (
            <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
              {l}
            </button>
          ))}
          <label className="rp-search">
            <Search size={12} />
            <input aria-label="Search media" placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <button className="btn" onClick={() => fileRef.current?.click()}>
            <Upload size={12} /> Upload new
          </button>
          <input ref={fileRef} type="file" accept="image/*,video/*" hidden onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) {
              const id = await onUpload(f);
              if (id) setChosen(id);
            }
          }} />
        </div>
        <div className="rp-grid">
          {list.map((a) => (
            <button key={a.id} className={`rp-item ${chosen === a.id ? "on" : ""} ${scene.asset_id === a.id ? "current" : ""}`} aria-label={`Use ${a.name}`} onClick={() => { setChosen(a.id); setStart(0); }}>
              <span className="rp-thumb" style={{ backgroundImage: a.thumbnail || a.kind === "image" ? `url("${a.thumbnail || a.url}")` : undefined }}>
                {a.kind === "video" && <i>{Math.round(Number(a.video_duration || a.duration || 0))}s</i>}
                {chosen === a.id && <CheckCircle2 size={16} />}
              </span>
              <span className="rp-name">{a.name}</span>
              {scene.asset_id === a.id && <small>now</small>}
            </button>
          ))}
          {!list.length && <p className="micro-note block">Nothing here. Upload a picture or clip.</p>}
        </div>
        <footer>
          {pick?.kind === "video" && (
            <label className="rp-start">
              Start the clip at
              <input type="number" aria-label="Start the clip at" min="0" step="0.1" max={Math.max(0, long - scene.duration)} value={start} onChange={(e) => setStart(Math.max(0, Number(e.target.value) || 0))} />
              s {long ? <small>(clip is {long.toFixed(1)} s; the scene needs {Number(scene.duration).toFixed(1)} s)</small> : null}
            </label>
          )}
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" aria-label="Use this picture" disabled={!chosen || (chosen === scene.asset_id && !start)} onClick={() => onPick(chosen, start)}>
            Use this picture
          </button>
        </footer>
      </div>
    </div>
  );
}

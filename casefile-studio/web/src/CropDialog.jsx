import React from "react";
import { X } from "lucide-react";
import { normaliseCrop, cropOf, PIC } from "./picture.js";
import PictureLayer from "./PictureLayer.jsx";

const WHOLE = [0, 0, 1, 1];

// v0.4.49 "Adjust crop": keep only the real photo of a media file. Every scene
// using the file gets the crop; the original file is not changed.
export default function CropDialog({ asset, fitFor = () => "cover", aspect = "16:9", api, projectId, onSaved, onClose, notify }) {
  const [box, setBox] = React.useState(cropOf(asset) || WHOLE);
  const [busy, setBusy] = React.useState("");
  const [note, setNote] = React.useState("");
  const paneRef = React.useRef(null);
  const src = asset.kind === "video" ? asset.thumbnail || asset.url : asset.url;
  const sw = Number(asset.width) || 16;
  const sh = Number(asset.height) || 9;
  // the Original pane: the whole picture, as large as fits 360 x 240
  const pw = Math.min(360, (240 * sw) / sh);
  const ph = (pw * sh) / sw;
  const [rw, rh] = aspect === "9:16" ? [135, 240] : [360, 202.5];
  const drag = (mode) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    const from = { x: e.clientX, y: e.clientY, b: [...box] };
    const el = e.currentTarget;
    el.setPointerCapture?.(e.pointerId);
    const m = PIC.crop_min;
    const move = (ev) => {
      const dx = (ev.clientX - from.x) / pw;
      const dy = (ev.clientY - from.y) / ph;
      let [x0, y0, x1, y1] = from.b;
      if (mode === "move") {
        const w = x1 - x0;
        const h = y1 - y0;
        x0 = Math.min(1 - w, Math.max(0, x0 + dx));
        y0 = Math.min(1 - h, Math.max(0, y0 + dy));
        x1 = x0 + w;
        y1 = y0 + h;
      } else {
        if (mode.includes("w")) x0 = Math.min(x1 - m, Math.max(0, x0 + dx));
        if (mode.includes("e")) x1 = Math.max(x0 + m, Math.min(1, x1 + dx));
        if (mode.includes("n")) y0 = Math.min(y1 - m, Math.max(0, y0 + dy));
        if (mode.includes("s")) y1 = Math.max(y0 + m, Math.min(1, y1 + dy));
      }
      setBox([x0, y0, x1, y1]);
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
  };
  const auto = async () => {
    setBusy("auto");
    try {
      const r = await api(`/api/projects/${projectId}/assets/${asset.id}/autocrop`, "POST", {});
      setBox(r.crop);
      setNote(r.found ? "Found and cut away bars or plain borders. Drag the box if it needs more." : "No black bars or plain borders found. Drag the box to cut away panels or logos.");
    } catch (e) {
      notify?.(e.message || String(e), "error");
    } finally {
      setBusy("");
    }
  };
  const save = async () => {
    setBusy("save");
    try {
      const p = await api(`/api/projects/${projectId}/assets/${asset.id}`, "PATCH", { crop: normaliseCrop(box) });
      onSaved(p);
    } catch (e) {
      notify?.(e.message || String(e), "error");
      setBusy("");
    }
  };
  const [x0, y0, x1, y1] = box;
  const crop = normaliseCrop(box);
  // how the selected scene shows this file once cropped (and its text below)
  const fit = fitFor(crop || [0.1, 0.1, 0.9, 0.9]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal crop-modal" role="dialog" aria-label="Adjust crop">
        <header className="sticker-head">
          <div>
            <span className="eyebrow">{asset.name}</span>
            <h2>Adjust crop</h2>
          </div>
          <button className="icon-btn" aria-label="Close crop" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <p className="crop-help">
          Drag the box to keep only the real photo. Everything outside it (news panels, channel logos, black bars) is cut away.
          {fit === "blur" || fit === "legacy-blur" ? " The photo is then centred over a blur of itself." : " The photo then fills the frame."} Your original file is not changed.
          Every scene using this file gets this crop.
        </p>
        <div className="crop-panes">
          <div>
            <span className="crop-label">ORIGINAL</span>
            <div className="crop-original" ref={paneRef} style={{ width: pw, height: ph }}>
              <img src={src} alt="" draggable={false} />
              <div className="crop-shade" style={{ clipPath: `polygon(0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${x0 * 100}% ${y0 * 100}%, ${x0 * 100}% ${y1 * 100}%, ${x1 * 100}% ${y1 * 100}%, ${x1 * 100}% ${y0 * 100}%, ${x0 * 100}% ${y0 * 100}%)` }} />
              <div className="crop-box" aria-label="Crop box" onPointerDown={drag("move")}
                style={{ left: x0 * pw, top: y0 * ph, width: (x1 - x0) * pw, height: (y1 - y0) * ph }}>
                {["nw", "ne", "sw", "se"].map((c) => (
                  <i key={c} className={`crop-handle ${c}`} onPointerDown={drag(c)} />
                ))}
              </div>
            </div>
          </div>
          <div>
            <span className="crop-label">RESULT</span>
            <div className="crop-result" style={{ width: rw, height: rh }}>
              <PictureLayer asset={asset.kind === "video" ? { ...asset, kind: "image", url: src } : asset} crop={crop} fit={fit} width={rw} height={rh} />
            </div>
          </div>
        </div>
        {note && <p className="micro-note block">{note}</p>}
        <div className="crop-actions">
          <button className="btn" disabled={!!busy} onClick={auto}>
            {busy === "auto" ? "Looking…" : "Automatic"}
          </button>
          <button className="btn" disabled={!!busy} onClick={() => { setBox(WHOLE); setNote(""); }}>
            Whole picture
          </button>
          <button className="btn primary" disabled={!!busy} onClick={save}>
            {busy === "save" ? "Saving…" : "Save my crop"}
          </button>
        </div>
      </div>
    </div>
  );
}

import React from "react";
import { Plus, Trash2, Copy, Crosshair, Square } from "lucide-react";
import { normaliseStickers, normaliseStickerKeys, stickerAt, stickerLabel, stickerFrameUrl, stickerAspect, textOf, strengthOf, cleanText, cleanLine, linesOf, CATALOG, ST } from "./stickers.js";
import { upsertKey, STICKER_EASES } from "./picture.js";
import { Step, clock, parseClock } from "./Effects.jsx";
import { KeyframeList } from "./KeyframeUI.jsx";
import { usePresets, savePreset, moveOnto } from "./presets.js";
import { SavePresetForm, PresetRow } from "./PresetUI.jsx";

const pct = (v) => `${Math.round(v * 100)}%`;

// v0.4.72 The words on a sticker. You type freely (spaces too); what is kept is one tidy line.
function StickerText({ sticker, disabled, onChange }) {
  const saved = textOf(sticker);
  const [draft, setDraft] = React.useState(saved);
  React.useEffect(() => {
    if (cleanText(draft) !== saved) setDraft(saved);
  }, [sticker.id, saved]);
  return (
    <label className="st-text">
      <span>Words on it</span>
      <input
        aria-label="Words on the sticker"
        value={draft}
        maxLength={ST.limits.text + 8}
        disabled={disabled}
        placeholder={CATALOG[sticker.kind]?.text}
        onChange={(e) => {
          setDraft(e.target.value);
          onChange(cleanText(e.target.value) || CATALOG[sticker.kind]?.text);
        }}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
      <small>{Array.from(cleanText(draft)).length}/{ST.limits.text}</small>
    </label>
  );
}

// v0.4.49 Stickers tab of the inspector: every sticker, and − / + for the selected one.
// v0.4.75 Your saved stickers & text templates (Stickers › Saved, and on top of Text › Templates)
export function SavedStickers({ onAdd, only, disabled, empty = true }) {
  const list = usePresets("sticker").filter((p) => !only || only(p.data));
  if (!list.length)
    return empty ? (
      <p className="micro-note block">
        Nothing saved yet. Select a sticker or text template on your video and click “Save this sticker as a preset” (under its keyframes): its words, size, place and move are kept for every project.
      </p>
    ) : null;
  return (
    <div className="preset-list">
      {list.map((p) => {
        const c = CATALOG[p.data.kind];
        const src = c && !c.region ? stickerFrameUrl(p.data.kind, c.once ? 1e6 : c.animated ? c.cycle * 0.6 : 0, p.data) : null;
        return (
          <PresetRow key={p.id} preset={p} useLabel="+ Add" disabled={disabled} onUse={(x) => onAdd(x.data)}
            preview={<span className="preset-thumb">{src ? <img src={src} alt="" /> : <small>{c?.label || p.data.kind}</small>}{p.data.keyframes?.length > 1 && <i title="Has a move">◆</i>}</span>} />
        );
      })}
    </div>
  );
}

// v0.4.75 Save this sticker (with its words, size, place and move) to use again in any project,
// or put a saved move on it (the same path and speeds, from where it is now).
function StickerPresets({ sel, v, disabled, onKeys }) {
  const moves = usePresets("sticker").filter((p) => p.data.keyframes?.length > 1);
  const [pick, setPick] = React.useState("");
  const { id, start, ...data } = sel; // eslint-disable-line no-unused-vars
  return (
    <div className="st-presets">
      <div className="section-label sub">
        <span>PRESETS · USE IT AGAIN</span>
      </div>
      {sel.kind === "image" ? (
        <p className="micro-note">Your own pictures belong to this project, so they cannot be saved as presets.</p>
      ) : (
        <SavePresetForm label="Save this sticker as a preset" placeholder={stickerLabel(sel)} disabled={disabled} onSave={(name) => savePreset("sticker", name, data)} />
      )}
      {moves.length > 0 && (
        <div className="preset-apply">
          <select aria-label="Use a saved move" value={pick} disabled={disabled} onChange={(e) => setPick(e.target.value)}>
            <option value="">Use a saved move…</option>
            {moves.map((p) => (
              <option key={p.id} value={p.id}>{p.name} ({p.data.keyframes.length} keyframes)</option>
            ))}
          </select>
          <button className="btn subtle" disabled={disabled || !pick} title="The same path and speeds, starting from where this sticker is now" onClick={() => {
            const p = moves.find((x) => x.id === pick);
            if (p) onKeys(normaliseStickerKeys(moveOnto(p.data.keyframes, { x: v.x, y: v.y, size: v.size }, sel.length), sel.length, sel));
            setPick("");
          }}>Apply</button>
        </div>
      )}
    </div>
  );
}

// v0.4.73 A text template's paragraphs (CapCut's "The 1st … 4th paragraph"), one box each.
function StickerLines({ sticker, disabled, onChange }) {
  const cat = CATALOG[sticker.kind];
  const saved = linesOf(sticker);
  const [draft, setDraft] = React.useState(saved);
  React.useEffect(() => {
    if (draft.length !== saved.length || draft.some((d, i) => cleanLine(d) !== saved[i])) setDraft(saved);
  }, [sticker.id, saved.join("\u0001")]);
  return (
    <div className="st-lines">
      {cat.fields.map((name, i) => (
        <label key={i} className="st-text">
          <span>{name}</span>
          <input
            aria-label={`${name} (line ${i + 1} of the text)`}
            value={draft[i] ?? ""}
            maxLength={ST.limits.line + 8}
            disabled={disabled}
            placeholder={cat.lines[i]}
            onChange={(e) => {
              const next = draft.map((d, j) => (j === i ? e.target.value : d));
              setDraft(next);
              onChange(next.map(cleanLine));
            }}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          />
          <small>{Array.from(cleanLine(draft[i] ?? "")).length}/{ST.limits.line}</small>
        </label>
      ))}
      {saved.some((x, i) => x !== cat.lines[i]) && (
        <button className="text-link" disabled={disabled} onClick={() => onChange(cat.lines)}>Back to the template’s words</button>
      )}
    </div>
  );
}

// v0.4.72 tracking: { id, progress, note } while the preview follows something; onFollow(id, pick)
// follows from where the sticker is (pick false) or after you click the thing (pick true).
export default function StickerPanel({ project, time, selectedId, onSelect, onChange, onOpenDialog, onSeek, disabled, focus = false, listOnly = false, tracking = null, picking = false, onFollow, onStopFollow }) {
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
      {/* v0.4.70 focus: the right panel shows only the selected sticker */}
      {focus && !sel && <p className="micro-note block">This sticker is gone. Pick another on the timeline.</p>}
      {!focus && (<>
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
            <img src={s.kind === "image" ? assets.find((a) => a.id === s.asset_id)?.url : stickerFrameUrl(s.kind, 1.5, s)} alt="" />
            <span>{stickerLabel(s, assets)}</span>
            <small>{clock(s.start)} · {s.length.toFixed(1)} s{s.keyframes.length ? ` · ◆${s.keyframes.length}` : ""}</small>
          </button>
        ))}
      </div>
      </>)}
      {sel && listOnly && <p className="micro-note block cc-right-hint">Its settings are in the right panel.</p>}
      {sel && !listOnly && (() => {
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
            {CATALOG[sel.kind]?.text && <StickerText sticker={sel} disabled={disabled} onChange={(text) => update(sel.id, { text })} />}
            {CATALOG[sel.kind]?.lines && <StickerLines sticker={sel} disabled={disabled} onChange={(lines) => update(sel.id, { lines })} />}
            <Step label="Size" value={v.size} display={pct(v.size)} step={0.01} min={ST.limits.size[0]} max={ST.limits.size[1]} disabled={disabled} onChange={(x) => setLook(sel, { size: x })} />
            {CATALOG[sel.kind]?.ratio && (() => {
              const ratio = stickerAspect(sel, assets);
              return (
                <Step label="Shape (wide ↔ tall)" value={ratio} display={ratio >= 1 ? `${ratio.toFixed(1)} : 1` : `1 : ${(1 / ratio).toFixed(1)}`}
                  step={ratio >= 1.5 ? 0.25 : 0.1} min={ST.limits.ratio[0]} max={ST.limits.ratio[1]} disabled={disabled} onChange={(x) => update(sel.id, { ratio: x })} />
              );
            })()}
            {CATALOG[sel.kind]?.region && (
              <Step label={CATALOG[sel.kind].region === "spot" ? "Darken the rest" : "Blur amount"} value={strengthOf(sel)} display={pct(strengthOf(sel))}
                step={0.05} min={ST.limits.strength[0]} max={ST.limits.strength[1]} disabled={disabled} onChange={(x) => update(sel.id, { strength: x })} />
            )}
            <Step label="Opacity" value={v.raw} display={pct(v.raw)} step={0.05} min={ST.limits.opacity[0]} max={1} disabled={disabled} onChange={(x) => setLook(sel, { opacity: x })} />
            <Step label="Left ↔ right" value={v.x} display={pct(v.x)} step={0.01} min={ST.limits.xy[0]} max={ST.limits.xy[1]} disabled={disabled} onChange={(x) => setLook(sel, { x })} />
            <Step label="Up ↕ down" value={v.y} display={pct(v.y)} step={0.01} min={ST.limits.xy[0]} max={ST.limits.xy[1]} disabled={disabled} onChange={(y) => setLook(sel, { y })} />
            <div className="section-label sub">
              <span>FOLLOW SOMETHING ON SCREEN</span>
            </div>
            {tracking?.id === sel.id && !tracking.done ? (
              <div className="st-track busy" role="status">
                <div className="st-track-bar"><i style={{ width: pct(tracking.progress || 0) }} /></div>
                <span>Following… {pct(tracking.progress || 0)}</span>
                <button className="btn" onClick={onStopFollow}><Square size={11} /> Stop</button>
              </div>
            ) : picking ? (
              <div className="st-track busy" role="status">
                <span>Click the face, object or spot in the preview.</span>
                <button className="text-link" onClick={onStopFollow}>Cancel</button>
              </div>
            ) : (
              <>
                <p className="micro-note block">
                  {tracking?.done && tracking.id === sel.id ? tracking.note : "Mark a face, a car or any spot: the sticker stays on it while it moves, from the playhead to the sticker’s end. It writes keyframes, so you can fix any of them below."}
                </p>
                <div className="st-track">
                  <button className="btn primary" disabled={disabled || !inside || !onFollow} onClick={() => onFollow(sel.id, true)} title="Then click the thing in the preview">
                    <Crosshair size={12} /> Click what to follow
                  </button>
                  <button className="btn" disabled={disabled || !inside || !onFollow} onClick={() => onFollow(sel.id, false)} title="Follows what is under the sticker now">
                    Follow from here
                  </button>
                </div>
                {!inside && <p className="micro-note block">Move the playhead onto this sticker first.</p>}
              </>
            )}
            <div className="section-label sub">
              <span>KEYFRAMES · MAKE IT MOVE</span>
            </div>
            <p className="micro-note block">
              {sel.keyframes.length
                ? `Position, size and opacity follow the keyframes. At ${local.toFixed(2)} s: changes ${at ? "edit this keyframe" : "add a keyframe here"}. Dragging it in the preview does the same.`
                : "Add a keyframe, move the playhead, then drag the sticker or change a value: it moves between keyframes (for example an arrow that follows someone)."}
            </p>
            <KeyframeList keys={sel.keyframes} kinds={STICKER_EASES} length={sel.length} at={at} disabled={disabled}
              describe={(k) => `${pct(k.x)}, ${pct(k.y)} · ${pct(k.size)}`}
              onSeek={(k) => onSeek(sel.start + k.t + 0.001)}
              onChange={(keyframes) => update(sel.id, { keyframes })} />
            <div className="kf-actions">
              <button className="btn" disabled={disabled || !inside || !!at}
                onClick={() => update(sel.id, { keyframes: upsertKey(sel.keyframes, local, { x: v.x, y: v.y, size: v.size, opacity: v.raw }, (k) => normaliseStickerKeys(k, sel.length, sel)) })}>
                ◆ Add keyframe {inside ? `(${local.toFixed(2)} s)` : "(move the playhead onto it)"}
              </button>
              {sel.keyframes.length > 0 && <button className="text-link" disabled={disabled} onClick={() => update(sel.id, { keyframes: [] })}>Clear keyframes</button>}
            </div>
            <StickerPresets sel={sel} v={v} disabled={disabled} onKeys={(keyframes) => update(sel.id, { keyframes })} />
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
      {!focus && <p className="micro-note block">Stickers sit over the picture and the subscribe animation; captions and your logo stay on top. Download MP4 includes them.</p>}
    </div>
  );
}

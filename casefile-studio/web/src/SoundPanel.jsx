import React from "react";
import { Play, Sparkles, Trash2, RotateCcw, Shuffle, Volume2, VolumeX, Headphones, Plus, Upload, Undo2 } from "lucide-react";
import { SFX, PRESETS, KIND_LABEL, normaliseSound, withPreset, editItem } from "./sound.js";
import { Step, clock } from "./Effects.jsx";

const pct = (v) => `${Math.round(v * 100)}%`;
const db = (v) => `${v > 0 ? "+" : ""}${v.toFixed(1)} dB`;
const FRAME = 1 / SFX.fps;

// v0.4.56 Sound tab of the inspector: the intelligent sound design. Off by default; the plan is
// made from the timeline (graphics, transitions, chapters, the narration, the subscribe animation),
// every sound says why it is there, and the moments left silent say why too. Editing one sound
// changes only that sound.
export default function SoundPanel({ project, plan, planError, time, playing, selectedId, onSelect, onChange, onGenerate, onSeek, onPlayFrom,
                                     preview, mute, solo, onMute, onSolo, onUploadSound, disabled }) {
  const s = normaliseSound(project.sound);
  const [catalog, setCatalog] = React.useState(null);
  const [browse, setBrowse] = React.useState(false);
  const [category, setCategory] = React.useState("whoosh");
  const [showSilent, setShowSilent] = React.useState(false);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const fileRef = React.useRef(null);
  const items = plan?.items || [];
  const sel = items.find((x) => x.id === selectedId);
  const save = (patch) => onChange({ ...s, ...patch });
  const edit = (it, patch) => onChange(editItem(s, it, patch));
  const label = (sid) => (sid?.startsWith("a:") ? (project.assets || []).find((a) => a.id === sid.slice(2))?.name || "Your sound" : catalog?.byId[sid]?.label || sid);
  const mine = (project.assets || []).filter((a) => a.kind === "audio" && (a.sfx || (a.duration || 99) <= 30));

  React.useEffect(() => {
    if (!s.enabled && !browse) return;
    if (catalog) return;
    fetch("/api/sound/catalog", { credentials: "same-origin" })
      .then((r) => r.json())
      .then((d) => setCatalog({ ...d, byId: Object.fromEntries(d.sounds.map((x) => [x.id, x])) }))
      .catch(() => setCatalog({ sounds: [], categories: [], byId: {} }));
  }, [s.enabled, browse]);

  const run = async (what, fn) => {
    setBusy(what);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy("");
    }
  };

  // where a sound added at the playhead is anchored: its scene, so it follows the scene when moved
  const anchorAt = (t) => {
    let start = 0;
    for (const sc of project.scenes || []) {
      const len = Math.max(1, Math.round((+sc.duration || 0) * SFX.fps)) / SFX.fps;
      if (t < start + len) return `sc:${sc.id}:${(Math.max(0, t - start)).toFixed(3)}`;
      start += len;
    }
    return `t:${t.toFixed(3)}`;
  };
  const addAt = (sid, name) => {
    const id = `m${Date.now().toString(36)}`;
    onChange({ ...s, items: [...s.items, { id, anchor: anchorAt(time), kind: "manual", sound: sid, gain: 0, status: "approved", source: "manual", label: name || label(sid), reason: "added by you" }] });
    onSelect(id);
  };
  const variation = (it) => {
    const cat = catalog?.byId[it.sound]?.category;
    const pool = (catalog?.sounds || []).filter((x) => x.category === cat && !/shutter|-seq/.test(x.id)).map((x) => x.id);
    if (pool.length < 2) return null;
    return pool[(pool.indexOf(it.sound) + 1) % pool.length];
  };
  const stored = (it) => s.items.find((x) => x.id === it.id);
  const resetToPlan = (it) => onChange({ ...s, items: s.items.filter((x) => x.id !== it.id) });

  return (
    <div className="inspector-content cs sfx">
      <div className="section-label">
        <span>INTELLIGENT SOUND DESIGN</span>
      </div>
      <label className="cs-check">
        <input type="checkbox" aria-label="Add sound design to the export" checked={s.enabled} disabled={disabled} onChange={(e) => save({ enabled: e.target.checked })} />
        Add sound design to the export
      </label>
      <p className="micro-note block">
        Restrained effects placed on the animation itself: graphics, diagrams, typing, transitions, chapter changes, verified developments and the subscribe animation.
        Never on soundbites, the victim or family, or grief and violence in the narration. Your narration and soundbites are never changed.
      </p>
      {s.enabled && (
        <>
          <label className="field mg-field">
            Preset
            <select aria-label="Preset" value={s.preset} disabled={disabled} onChange={(e) => onChange(withPreset(s, e.target.value))}>
              {SFX.presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
          <p className="micro-note">{PRESETS[s.preset]?.about}</p>
          <label className="field mg-field">
            Mode
            <select aria-label="Mode" value={s.mode} disabled={disabled} onChange={(e) => save({ mode: e.target.value })}>
              <option value="auto">Automatic: follows the timeline as you edit</option>
              <option value="manual">Manual: only the sounds you keep</option>
            </select>
          </label>
          <div className="st-actions">
            <button className="btn" disabled={disabled || !!busy} title="Plan again from the timeline (your own sounds, edits and removals stay)" onClick={() => run("gen", onGenerate)}>
              <Sparkles size={12} /> {busy === "gen" ? "Planning…" : s.mode === "manual" ? "Generate plan" : "Plan again"}
            </button>
            <button className={`btn ${mute ? "on" : ""}`} aria-pressed={mute} title="Preview without the effects" onClick={() => onMute(!mute)}>
              {mute ? <VolumeX size={12} /> : <Volume2 size={12} />} {mute ? "Muted" : "Mute"}
            </button>
            <button className={`btn ${solo ? "on" : ""}`} aria-pressed={solo} title="Preview the effects alone" onClick={() => onSolo(!solo)}>
              <Headphones size={12} /> Solo
            </button>
          </div>
          {error && <p className="micro-note block mg-error">{error}</p>}

          <div className="section-label sub"><span>MIX</span></div>
          <Step label="Effects volume" value={s.master} display={pct(s.master)} step={0.05} min={SFX.limits.master[0]} max={SFX.limits.master[1]} disabled={disabled}
            onChange={(v) => save({ master: v })} />
          <Step label="Intensity" value={s.intensity} display={pct(s.intensity)} step={0.05} min={0} max={1} disabled={disabled}
            onChange={(v) => save({ intensity: v, preset: "custom" })} />
          <Step label="Density" value={s.density} display={pct(s.density)} step={0.05} min={0} max={1} disabled={disabled}
            onChange={(v) => save({ density: v, preset: "custom" })} />
          <Step label="Timing (all)" value={s.lead} display={`${s.lead > 0 ? "+" : ""}${Math.round(s.lead * 1000)} ms`} step={FRAME / 2} min={SFX.limits.lead[0]} max={SFX.limits.lead[1]} disabled={disabled}
            onChange={(v) => save({ lead: v })} />
          <label className="cs-check">
            <input type="checkbox" checked={s.duck} disabled={disabled} onChange={(e) => save({ duck: e.target.checked })} />
            Dialogue protection (effects dip under the voice)
          </label>
          <label className="cs-check">
            <input type="checkbox" checked={s.variation} disabled={disabled} onChange={(e) => save({ variation: e.target.checked })} />
            Prevent repetition (rotate variations)
          </label>
          <div className="sfx-kinds">
            {Object.keys(s.kinds).map((k) => (
              <label key={k} className="cs-check">
                <input type="checkbox" checked={s.kinds[k]} disabled={disabled} onChange={(e) => save({ kinds: { ...s.kinds, [k]: e.target.checked }, preset: "custom" })} />
                {KIND_LABEL[k]}
              </label>
            ))}
          </div>

          <div className="section-label sub">
            <span>THE PLAN</span>
            <small>{plan ? `${items.filter((x) => x.status === "approved" && !x.gone).length} sounds · ${plan.silenced.length} left silent` : planError ? "" : "Reading the timeline…"}</small>
          </div>
          {planError && <p className="micro-note block mg-error">{planError}</p>}
          {plan && !items.length && <p className="micro-note block">Nothing on this timeline calls for a sound yet (graphics, transitions, chapter changes or the subscribe animation).</p>}
          <div className="st-list sfx-list">
            {items.map((x) => (
              <button key={x.id} className={`st-item sfx-item ${x.id === selectedId ? "on" : ""} ${x.status !== "approved" ? "off" : ""} ${x.gone ? "gone" : ""} ${x.t != null && Math.abs(time - x.t) < 0.25 ? "now" : ""}`}
                onClick={() => { onSelect(x.id); if (x.t != null) onSeek(Math.max(0, x.t - 0.02)); }}>
                <i className={`sfx-kind ${x.kind}`}>{x.t != null ? clock(x.t).slice(0, -2) : "—"}</i>
                <span>{x.label || label(x.sound)}</span>
                <small>{label(x.sound)}{x.status === "removed" ? " · removed" : x.status === "suggested" ? " · suggested" : ""}{x.edited ? " · edited" : ""}{x.gone ? ` · ${x.gone}` : ""}</small>
              </button>
            ))}
          </div>
          {plan && plan.silenced.length > 0 && (
            <>
              <button className="text-link" onClick={() => setShowSilent(!showSilent)}>{showSilent ? "Hide" : "Show"} the {plan.silenced.length} moments left silent, and why</button>
              {showSilent && (
                <div className="sfx-silent">
                  {plan.silenced.map((x, i) => (
                    <button key={i} className="text-link" onClick={() => onSeek(x.t)}><small>{clock(x.t).slice(0, -2)}</small> {x.label} — {x.why}</button>
                  ))}
                </div>
              )}
            </>
          )}

          {sel && (
            <div className="st-edit">
              <div className="section-label sub">
                <span>{(KIND_LABEL[sel.kind] || "Sound").toUpperCase()}</span>
                <small>{sel.t != null ? clock(sel.t) : "not placed"}</small>
              </div>
              {sel.reason && <p className="micro-note block">Why: {sel.reason}.</p>}
              {sel.gone && <p className="micro-note block mg-warn">Left out of the export: {sel.gone}.</p>}
              <div className="st-actions">
                <button className="btn" onClick={() => preview.audition(project.id, sel.sound, Math.pow(10, (sel.level ?? sel.gain) / 20), sel)}>
                  <Play size={12} /> Sound
                </button>
                <button className="btn" disabled={sel.t == null} onClick={() => onPlayFrom(Math.max(0, sel.t - 2))}>
                  <Play size={12} /> In context
                </button>
                <button className="btn" disabled={disabled || !variation(sel)} title="Another variation of the same kind of sound" onClick={() => edit(sel, { sound: variation(sel) })}>
                  <Shuffle size={12} /> Another
                </button>
                {sel.status === "removed" ? (
                  <button className="btn" disabled={disabled} onClick={() => edit(sel, { status: "approved" })}><Undo2 size={12} /> Restore</button>
                ) : sel.status === "suggested" ? (
                  <button className="btn primary" disabled={disabled} onClick={() => edit(sel, { status: "approved" })}>Keep</button>
                ) : null}
                {sel.status !== "removed" && (
                  <button className="btn danger" disabled={disabled} onClick={() => (sel.source === "manual" ? onChange({ ...s, items: s.items.filter((x) => x.id !== sel.id) }) : edit(sel, { status: "removed" }))}>
                    <Trash2 size={12} /> Remove
                  </button>
                )}
                {sel.source === "auto" && stored(sel) && (
                  <button className="btn" disabled={disabled} title="Back to what the plan chose" onClick={() => resetToPlan(sel)}><RotateCcw size={12} /> Reset</button>
                )}
              </div>
              <label className="field mg-field">
                Sound
                <select aria-label="Sound" value={sel.sound} disabled={disabled} onChange={(e) => edit(sel, { sound: e.target.value })}>
                  {mine.length > 0 && (
                    <optgroup label="Your sounds">
                      {mine.map((a) => <option key={a.id} value={`a:${a.id}`}>{a.name}</option>)}
                    </optgroup>
                  )}
                  {(catalog?.categories || []).map((c) => (
                    <optgroup key={c} label={c}>
                      {catalog.sounds.filter((x) => x.category === c).map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
                    </optgroup>
                  ))}
                  {!catalog && <option value={sel.sound}>{sel.sound}</option>}
                </select>
              </label>
              <Step label="Volume" value={sel.gain} display={db(sel.gain)} step={1} min={SFX.limits.gain[0]} max={SFX.limits.gain[1]} disabled={disabled}
                onChange={(v) => edit(sel, { gain: v })} />
              <Step label="Move" value={sel.offset || 0} display={`${(sel.offset || 0) >= 0 ? "+" : ""}${((sel.offset || 0) * SFX.fps).toFixed(1)} fr`} step={FRAME} min={SFX.limits.offset[0]} max={SFX.limits.offset[1]} disabled={disabled}
                onChange={(v) => edit(sel, { offset: Math.round(v * 10000) / 10000 })} />
              <Step label="Fade in" value={sel.fade_in || 0} display={`${(sel.fade_in || 0).toFixed(2)} s`} step={0.05} min={0} max={SFX.limits.fade[1]} disabled={disabled}
                onChange={(v) => edit(sel, { fade_in: v })} />
              <Step label="Fade out" value={sel.fade_out || 0} display={`${(sel.fade_out || 0).toFixed(2)} s`} step={0.05} min={0} max={SFX.limits.fade[1]} disabled={disabled}
                onChange={(v) => edit(sel, { fade_out: v })} />
              <p className="micro-note">Drag it on the Sound FX lane of the timeline to move it; it stays tied to {sel.anchor.startsWith("mg:") ? "its graphic" : sel.anchor.startsWith("tr:") ? "its transition" : sel.anchor.startsWith("cta:") ? "the subscribe animation" : "its scene"} when you edit.</p>
            </div>
          )}

          <div className="section-label sub"><span>LIBRARY</span></div>
          <div className="st-actions">
            <button className="btn" onClick={() => setBrowse(!browse)}>{browse ? "Close the library" : "Browse the library"}</button>
            <button className="btn" disabled={disabled} onClick={() => fileRef.current?.click()}><Upload size={12} /> Import a sound</button>
            <input ref={fileRef} type="file" accept=".wav,.mp3,.m4a,.aac,.ogg,.flac,audio/*" hidden
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) run("upload", () => onUploadSound(f)); }} />
          </div>
          {busy === "upload" && <p className="micro-note">Importing…</p>}
          {browse && catalog && (
            <div className="sfx-lib">
              <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
                {mine.length > 0 && <option value="mine">Your sounds</option>}
                {catalog.categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              {(category === "mine" ? mine.map((a) => ({ id: `a:${a.id}`, label: a.name, intensity: 0 })) : catalog.sounds.filter((x) => x.category === category)).map((x) => (
                <div key={x.id} className="sfx-lib-row">
                  <button className="icon-btn" aria-label={`Play ${x.label}`} onClick={() => preview.audition(project.id, x.id, 0.8)}><Play size={11} /></button>
                  <span>{x.label}{x.intensity ? <small> · {"•".repeat(x.intensity)}</small> : null}</span>
                  <button className="text-link" disabled={disabled} title="Add it at the playhead" onClick={() => addAt(x.id, x.label)}><Plus size={11} /> at {clock(time).slice(0, -2)}</button>
                </div>
              ))}
              {category === "shutter" && <p className="micro-note mg-warn">A camera shutter can suggest a real police or press photograph. It is never placed automatically; use it only where that is not implied.</p>}
              <p className="micro-note">Every built-in sound is made on this computer by Casefile (no downloads, no licences to track). Imported sounds are yours: use only sounds you have the right to use.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

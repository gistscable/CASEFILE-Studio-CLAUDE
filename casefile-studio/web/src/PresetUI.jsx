import React from "react";
import { renamePreset, deletePreset } from "./presets.js";

// the little "Save as preset" form: a name and Save
export function SavePresetForm({ label = "Save as preset", placeholder, onSave, disabled }) {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  if (!open)
    return (
      <span className="preset-save">
        <button className="btn subtle" disabled={disabled} onClick={() => { setOpen(true); setMsg(""); setName(placeholder || ""); }}>
          ☆ {label}
        </button>
        {msg && <small className="preset-msg">{msg}</small>}
      </span>
    );
  const go = async () => {
    setBusy(true);
    try {
      await onSave(name.trim() || placeholder || "My preset");
      setOpen(false);
      setMsg("Saved — find it under Saved, in any project.");
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="preset-save open">
      <input aria-label="Preset name" autoFocus value={name} maxLength={40} placeholder="Name it" onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") go(); if (e.key === "Escape") setOpen(false); }} />
      <button className="btn primary" disabled={busy} onClick={go}>{busy ? "Saving…" : "Save"}</button>
      <button className="text-link" onClick={() => setOpen(false)}>Cancel</button>
      {msg && <small className="preset-msg">{msg}</small>}
    </span>
  );
}

// a saved preset in a list: use it, rename it, delete it
export function PresetRow({ preset, onUse, useLabel = "Use", disabled, preview }) {
  const [edit, setEdit] = React.useState(false);
  const [name, setName] = React.useState(preset.name);
  return (
    <div className="preset-row">
      {preview}
      {edit ? (
        <input aria-label="New name" autoFocus value={name} maxLength={40} onChange={(e) => setName(e.target.value)}
          onBlur={() => { setEdit(false); if (name.trim() && name !== preset.name) renamePreset(preset.id, name); }}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { setName(preset.name); setEdit(false); } }} />
      ) : (
        <span className="preset-name" title="Double-click to rename" onDoubleClick={() => setEdit(true)}>{preset.name}</span>
      )}
      <button className="btn subtle" disabled={disabled} onClick={() => onUse(preset)}>{useLabel}</button>
      <button className="icon-btn" aria-label={`Rename preset ${preset.name}`} title="Rename" onClick={() => setEdit(true)}>✎</button>
      <button className="icon-btn" aria-label={`Delete preset ${preset.name}`} title="Delete" onClick={() => { if (window.confirm(`Delete the preset “${preset.name}”?`)) deletePreset(preset.id); }}>×</button>
    </div>
  );
}

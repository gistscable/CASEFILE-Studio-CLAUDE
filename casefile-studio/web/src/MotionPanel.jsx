import React from "react";
import { Plus, Trash2, Check, RotateCcw, Play, Sparkles, X } from "lucide-react";
import { MG, TEMPLATES, STATUS, normaliseMotion, optionLabel } from "./motion.js";
import { Step, clock, parseClock } from "./Effects.jsx";

const pct = (v) => `${Math.round(v * 100)}%`;
const round3 = (t) => Math.round(t * 1000) / 1000;

function Choice({ label, value, options, onChange, disabled }) {
  return (
    <label className="field mg-field">
      {label}
      <select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => {
          const [id, text] = Array.isArray(o) ? o : [o, o];
          return <option key={id} value={id}>{text}</option>;
        })}
      </select>
    </label>
  );
}

function Swatches({ label, value, options, onChange, disabled }) {
  return (
    <div className="mg-swatches">
      <span>{label}</span>
      {options.map(([c, name]) => (
        <button key={c} title={name} aria-label={`${label}: ${name}`} className={value === c ? "on" : ""} disabled={disabled}
          style={{ background: c }} onClick={() => onChange(c)} />
      ))}
    </div>
  );
}

// v0.4.52 Motion tab of the inspector: suggestions from the narration, graphics you make from a
// passage you choose, and everything about the selected graphic. Only approved graphics go into
// the export, and only while "Add to the export" is on (off by default).
export default function MotionPanel({ project, time, playing, selectedId, onSelect, onChange, onSuggest, onDraft, onSeek, onPlayFrom, disabled, previewStatus }) {
  const m = normaliseMotion(project.motion);
  const sel = m.items.find((x) => x.id === selectedId);
  const images = (project.assets || []).filter((a) => a.kind === "image");
  const [busy, setBusy] = React.useState("");
  const [narration, setNarration] = React.useState(null);
  const [pick, setPick] = React.useState(null); // {template, from, to} while choosing a passage
  const [error, setError] = React.useState("");
  const save = (patch) => onChange({ ...m, ...patch });
  const setItems = (items) => save({ items });
  const update = (id, patch) => setItems(m.items.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const scenesKey = (project.scenes || []).map((s) => `${s.id}:${s.duration}:${(s.narration || "").length}`).join("|");

  React.useEffect(() => {
    if (!pick) return;
    let live = true;
    fetch(`/api/projects/${project.id}/motion/narration`, { credentials: "same-origin" })
      .then((r) => r.json())
      .then((d) => live && setNarration(d))
      .catch(() => live && setNarration({ sentences: [] }));
    return () => {
      live = false;
    };
  }, [!!pick, scenesKey]);

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

  const sentences = narration?.sentences || [];
  const nowIndex = Math.max(0, sentences.findIndex((s) => s.end > time));
  const shown = sentences.slice(Math.max(0, nowIndex - 3), nowIndex + 12);

  const create = () =>
    run("draft", async () => {
      const a = sentences[Math.min(pick.from, pick.to)], b = sentences[Math.max(pick.from, pick.to)];
      const item = await onDraft({ template: pick.template, start: a.start, end: b.end });
      setItems([...m.items, item]);
      onSelect(item.id);
      setPick(null);
      onSeek(item.start);
    });

  const regenerate = (it, template = it.template) =>
    run("regen", async () => {
      const fresh = await onDraft({ template, start: it.lines[0]?.at ?? it.start, end: Math.max(it.start + 1, it.end - MG.timing.hold), id: it.id });
      const keep = Object.fromEntries(["background", "photo_id", "dim", "font", "size", "accent", "text_color", "align", "x", "y", "speed", "enter", "exit", "hide_captions"].map((k) => [k, it[k]]));
      update(it.id, { ...fresh, ...keep, id: it.id, status: "draft", source: it.source, reason: it.reason, template });
    });

  return (
    <div className="inspector-content cs mg">
      <div className="section-label">
        <span>MOTION GRAPHICS</span>
      </div>
      <label className="cs-check">
        <input type="checkbox" aria-label="Add approved motion graphics to the export" checked={m.enabled} disabled={disabled} onChange={(e) => save({ enabled: e.target.checked })} />
        Add approved graphics to the export
      </label>
      <p className="micro-note block">
        Animated findings, timelines, conflicting accounts and legal outcomes, made from your narration's own words. Each line appears when the narrator says it.
        Nothing changes your scenes, narration or soundbites; remove a graphic and the picture is back.
      </p>
      <div className="st-actions">
        <button className="btn" disabled={disabled || !!busy} onClick={() => run("suggest", onSuggest)}>
          <Sparkles size={12} /> {busy === "suggest" ? "Reading the narration…" : "Suggest from the narration"}
        </button>
        <button className="btn" disabled={disabled || !!busy} onClick={() => setPick(pick ? null : { template: "findings", from: null, to: null })}>
          <Plus size={12} /> New from a passage
        </button>
      </div>
      {error && <p className="micro-note block mg-error">{error}</p>}

      {pick && (
        <div className="mg-pick">
          <Choice label="Template" value={pick.template} options={MG.templates.map((t) => [t.id, t.label])} disabled={disabled} onChange={(v) => setPick({ ...pick, template: v })} />
          <p className="micro-note">Click the first and the last sentence of the passage{narration && !narration.exact ? " (times from the captions)" : ""}.</p>
          <div className="mg-sentences">
            {!narration && <p className="micro-note">Reading the narration…</p>}
            {narration && !sentences.length && <p className="micro-note">This project has no narration yet.</p>}
            {shown.map((s) => {
              const i = sentences.indexOf(s);
              const lo = Math.min(pick.from ?? -1, pick.to ?? pick.from ?? -1), hi = Math.max(pick.from ?? -1, pick.to ?? pick.from ?? -1);
              const on = pick.from !== null && i >= lo && i <= hi;
              return (
                <button key={i} className={`mg-sentence ${on ? "on" : ""} ${time >= s.start && time < s.end ? "now" : ""}`}
                  onClick={() => setPick(pick.from === null || pick.to !== null ? { ...pick, from: i, to: null } : { ...pick, to: i })}>
                  <small>{clock(s.start)}</small> {s.text}
                </button>
              );
            })}
          </div>
          <div className="st-actions">
            <button className="btn primary" disabled={disabled || pick.from === null || !!busy} onClick={create}>
              {busy === "draft" ? "Making…" : `Make ${TEMPLATES[pick.template].label.toLowerCase()}`}
            </button>
            <button className="text-link" onClick={() => setPick(null)}>Cancel</button>
          </div>
        </div>
      )}

      {!m.items.length && !pick && (
        <p className="micro-note block">No graphics yet. “Suggest from the narration” reads the whole script and proposes a few where they help (none if nothing calls for one); or make one from a passage you choose.</p>
      )}
      <div className="st-list">
        {m.items.map((x) => (
          <button key={x.id} className={`st-item mg-item ${x.id === selectedId ? "on" : ""} ${time >= x.start && time < x.end ? "now" : ""}`}
            onClick={() => { onSelect(x.id); if (!(time >= x.start && time < x.end)) onSeek(x.start); }}>
            <i className={`mg-badge ${x.status}`}>{STATUS[x.status]}</i>
            <span>{x.title || TEMPLATES[x.template].label}</span>
            <small>{TEMPLATES[x.template].label} · {clock(x.start)} · {(x.end - x.start).toFixed(1)} s</small>
          </button>
        ))}
      </div>
      {m.items.some((x) => x.status === "approved") && !m.enabled && (
        <p className="micro-note block mg-warn">Approved graphics are not exported until “Add approved graphics to the export” is on.</p>
      )}

      {sel && (
        <div className="st-edit">
          <div className="section-label sub">
            <span>{TEMPLATES[sel.template].label.toUpperCase()}</span>
            <small className={`mg-badge ${sel.status}`}>{STATUS[sel.status]}</small>
          </div>
          {sel.reason && <p className="micro-note block">Why here: {sel.reason}</p>}
          <div className="st-actions">
            <button className="btn" disabled={disabled} onClick={() => onPlayFrom(Math.max(0, sel.start - 0.5))}>
              <Play size={12} /> Play it
            </button>
            {sel.status !== "approved" ? (
              <button className="btn primary" disabled={disabled} onClick={() => update(sel.id, { status: "approved" })}>
                <Check size={12} /> Approve
              </button>
            ) : (
              <button className="btn" disabled={disabled} onClick={() => update(sel.id, { status: "draft" })}>
                Unapprove
              </button>
            )}
            <button className="btn" disabled={disabled || !!busy} title="Make it again from the narration (keeps the style)" onClick={() => regenerate(sel)}>
              <RotateCcw size={12} /> {busy === "regen" ? "…" : "Regenerate"}
            </button>
            <button className="btn danger" disabled={disabled} onClick={() => { setItems(m.items.filter((x) => x.id !== sel.id)); onSelect(null); }}>
              {sel.status === "suggested" ? <><X size={12} /> Reject</> : <><Trash2 size={12} /> Remove</>}
            </button>
          </div>
          {previewStatus === "preparing" && <p className="micro-note">Preparing the preview…</p>}

          <Choice label="Template" value={sel.template} options={MG.templates.map((t) => [t.id, t.label])} disabled={disabled || !!busy}
            onChange={(v) => regenerate(sel, v)} />
          <Choice label="Layout" value={sel.layout} options={MG.layouts[sel.template]} disabled={disabled} onChange={(v) => update(sel.id, { layout: v })} />

          <div className="section-label sub"><span>TEXT</span></div>
          <label className="field mg-field">
            Heading
            <input aria-label="Heading" key={sel.id + "h" + sel.heading} defaultValue={sel.heading} maxLength={MG.limits.heading} disabled={disabled}
              onBlur={(e) => e.target.value !== sel.heading && update(sel.id, { heading: e.target.value })} />
          </label>
          <label className="field mg-field">
            Title
            <input aria-label="Title" key={sel.id + "t" + sel.title} defaultValue={sel.title} maxLength={MG.limits.title} disabled={disabled}
              onBlur={(e) => e.target.value !== sel.title && update(sel.id, { title: e.target.value })} />
          </label>
          {sel.lines.map((l, i) => {
            const setLine = (patch) => update(sel.id, { lines: sel.lines.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
            return (
              <div key={i} className="mg-line">
                <div className="mg-line-head">
                  <b>{TEMPLATES[sel.template].line_label} {i + 1}</b>
                  <button className="text-link" disabled={disabled} title="Show this line from the playhead" onClick={() => setLine({ at: round3(Math.max(sel.start, Math.min(sel.end, time))) })}>
                    at {clock(l.at)} · set to playhead
                  </button>
                  <button className="icon-btn" aria-label={`Remove line ${i + 1}`} disabled={disabled} onClick={() => update(sel.id, { lines: sel.lines.filter((_, j) => j !== i) })}>
                    <Trash2 size={11} />
                  </button>
                </div>
                {(sel.template === "timeline" || sel.template === "legal" || sel.template === "contrast") && (
                  sel.template === "legal" ? (
                    <select aria-label={`Label ${i + 1}`} value={l.label} disabled={disabled} onChange={(e) => setLine({ label: e.target.value })}>
                      <option value="">No label</option>
                      {MG.legal_labels.map((x) => <option key={x} value={x}>{x}</option>)}
                    </select>
                  ) : (
                    <input aria-label={`Label ${i + 1}`} placeholder={sel.template === "timeline" ? "Date or time" : "Who said it (optional)"} key={sel.id + i + "l" + l.label}
                      defaultValue={l.label} maxLength={MG.limits.label} disabled={disabled} onBlur={(e) => e.target.value !== l.label && setLine({ label: e.target.value })} />
                  )
                )}
                {sel.template === "contrast" && (
                  <div className="mg-row">
                    <select aria-label={`Kind ${i + 1}`} value={l.kind || "statement"} disabled={disabled} onChange={(e) => setLine({ kind: e.target.value })}>
                      {MG.contrast_kinds.map(([id, t]) => <option key={id} value={id}>{t === "Statement" ? "What was said" : "What was found"}</option>)}
                    </select>
                    <label className="cs-check"><input type="checkbox" checked={l.emphasis} disabled={disabled} onChange={(e) => setLine({ emphasis: e.target.checked })} /> Emphasise</label>
                  </div>
                )}
                <textarea aria-label={`Line ${i + 1}`} rows={2} key={sel.id + i + "x" + l.text} defaultValue={l.text} maxLength={MG.limits.text} disabled={disabled}
                  onBlur={(e) => e.target.value.trim() && e.target.value !== l.text && setLine({ text: e.target.value })} />
              </div>
            );
          })}
          {sel.lines.length < TEMPLATES[sel.template].max_lines && (
            <button className="text-link" disabled={disabled}
              onClick={() => update(sel.id, { lines: [...sel.lines, { text: "New line", label: "", kind: "finding", emphasis: false, at: round3(Math.max(sel.start, Math.min(sel.end - 1, time))) }] })}>
              + Add a line at the playhead
            </button>
          )}

          <div className="section-label sub"><span>TIMING</span></div>
          <Step label="Starts at" value={sel.start} display={clock(sel.start)} typed={parseClock} step={0.1} min={0} max={86400} disabled={disabled}
            onChange={(x) => { const d = x - sel.start; update(sel.id, { start: x, end: sel.end + d, lines: sel.lines.map((l) => ({ ...l, at: round3(l.at + d) })) }); }} />
          <Step label="Ends at" value={sel.end} display={clock(sel.end)} typed={parseClock} step={0.5} min={sel.start + MG.limits.length[0]} max={sel.start + MG.limits.length[1]} disabled={disabled}
            onChange={(x) => update(sel.id, { end: x })} />
          <Step label="Animation speed" value={sel.speed} display={`${sel.speed.toFixed(2)}×`} step={0.25} min={MG.limits.speed[0]} max={MG.limits.speed[1]} disabled={disabled} onChange={(x) => update(sel.id, { speed: x })} />
          <Choice label="Entrance" value={sel.enter} options={MG.enters} disabled={disabled} onChange={(v) => update(sel.id, { enter: v })} />
          <Choice label="Exit" value={sel.exit} options={MG.exits} disabled={disabled} onChange={(v) => update(sel.id, { exit: v })} />
          <label className="cs-check">
            <input type="checkbox" checked={sel.hide_captions} disabled={disabled} onChange={(e) => update(sel.id, { hide_captions: e.target.checked })} />
            Hide captions while it is on screen
          </label>

          <div className="section-label sub"><span>LOOK</span></div>
          <Choice label="Background" value={sel.background} options={MG.backgrounds.filter(([id]) => id !== "photo" || images.length)} disabled={disabled}
            onChange={(v) => update(sel.id, { background: v, photo_id: v === "photo" ? sel.photo_id || images[0]?.id || "" : "" })} />
          {sel.background === "photo" && (
            <Choice label="Photo (from your project)" value={sel.photo_id} options={images.map((a) => [a.id, a.name])} disabled={disabled} onChange={(v) => update(sel.id, { photo_id: v })} />
          )}
          {sel.background !== "charcoal" && (
            <Step label="Darken" value={sel.dim} display={pct(sel.dim)} step={0.05} min={MG.limits.dim[0]} max={MG.limits.dim[1]} disabled={disabled} onChange={(x) => update(sel.id, { dim: x })} />
          )}
          <Choice label="Font" value={sel.font} options={MG.fonts} disabled={disabled} onChange={(v) => update(sel.id, { font: v })} />
          <Step label="Text size" value={sel.size} display={pct(sel.size)} step={0.05} min={MG.limits.size[0]} max={MG.limits.size[1]} disabled={disabled} onChange={(x) => update(sel.id, { size: x })} />
          <Swatches label="Accent" value={sel.accent} options={MG.accents} disabled={disabled} onChange={(c) => update(sel.id, { accent: c })} />
          <Swatches label="Text" value={sel.text_color} options={MG.text_colors} disabled={disabled} onChange={(c) => update(sel.id, { text_color: c })} />
          <Choice label="Align" value={sel.align} options={[["left", "Left"], ["center", "Centre"]]} disabled={disabled} onChange={(v) => update(sel.id, { align: v })} />
          <Step label="Left ↔ right" value={sel.x} display={pct(sel.x)} step={0.01} min={MG.limits.xy[0]} max={MG.limits.xy[1]} disabled={disabled} onChange={(x) => update(sel.id, { x })} />
          <Step label="Up ↕ down" value={sel.y} display={pct(sel.y)} step={0.01} min={MG.limits.xy[0]} max={MG.limits.xy[1]} disabled={disabled} onChange={(y) => update(sel.id, { y })} />
        </div>
      )}
    </div>
  );
}

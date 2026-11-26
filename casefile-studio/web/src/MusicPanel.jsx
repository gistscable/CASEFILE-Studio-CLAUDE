import React from "react";
import { Play, Crosshair } from "lucide-react";
import LiveRange from "./LiveRange.jsx";
import { MUSIC_MODES, normaliseMusic, musicLayout, timelineTotal } from "./music.js";

const clock = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
function parseClock(s) {
  const m = String(s).trim().match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  return m ? Number(m[1] || 0) * 60 + Number(m[2]) : null;
}

/** A time field: type 1:02.5 or 62.5; Enter or leaving the field saves. */
function TimeField({ label, value, placeholder, onSet, disabled, now, nowLabel = "Playhead" }) {
  return (
    <div className="music-time">
      <span>{label}</span>
      <input aria-label={label} key={value ?? "none"} defaultValue={value === null || value === undefined ? "" : clock(value)} placeholder={placeholder} disabled={disabled}
        onBlur={(e) => { const raw = e.target.value.trim(); if (!raw) return onSet(null); const v = parseClock(raw); if (v !== null) onSet(Math.round(v * 1000) / 1000); }}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()} />
      {now !== undefined && (
        <button className="icon-btn" title={`Set to the ${nowLabel.toLowerCase()} (${clock(now)})`} aria-label={`${label}: ${nowLabel}`} disabled={disabled} onClick={() => onSet(Math.round(now * 1000) / 1000)}>
          <Crosshair size={11} />
        </button>
      )}
    </div>
  );
}

// v0.4.58 Where the background music plays and how it loops. Everything here is heard at once in
// the preview (the layout is made here and handed to the player); a change is saved on release.
// The documentary's length never changes: the music is cut to the timeline.
export default function MusicPanel({ project, music, scenes, time, selected, disabled, preview, onSave, onPlayFrom,
                                     volume, onLiveVolume, onCommitVolume }) {
  const saved = normaliseMusic(project.music);
  const [draft, setDraft] = React.useState(null); // settings while a slider moves
  const m = draft || saved;
  const total = React.useMemo(() => timelineTotal(scenes), [scenes]);
  const track = +music?.duration || 0;
  const lay = React.useMemo(() => musicLayout(m, track, total, scenes), [JSON.stringify(m), track, total, scenes]);
  const live = (patch) => {
    const next = normaliseMusic({ ...m, ...patch });
    setDraft(next);
    preview?.setLayout(musicLayout(next, track, total, scenes));
  };
  const commit = (patch) => {
    setDraft(null);
    onSave(normaliseMusic({ ...saved, ...patch }));
  };
  const chapters = React.useMemo(() => [...new Set((scenes || []).map((s) => s.chapter).filter(Boolean))], [scenes]);
  const heard = lay.runs.reduce((a, r) => a + (r.end - r.at), 0);
  const passes = lay.runs.reduce((a, r) => a + r.iters.length, 0);
  const seams = lay.runs.flatMap((r) => r.iters.slice(1).map((it) => it.at));
  const [a, b] = lay.part;
  // v0.4.59 chosen scenes / chapters no longer in the timeline (removed, or rebuilt with nothing to
  // follow): kept so an undo brings their music back, but shown, never silently dropped
  const ids = new Set((scenes || []).map((s) => String(s.id)));
  const goneScenes = saved.scenes.filter((x) => !ids.has(x));
  const goneChapters = saved.chapters.filter((c) => !chapters.includes(c));
  const inScene = (sc) => !!sc && (saved.scenes.includes(String(sc.id)) || (sc.chapter && saved.chapters.includes(sc.chapter)));

  if (!music) return null;
  return (
    <div className="music-panel">
      <LiveRange label="Music level" ariaLabel="Music level" value={volume} min={0} max={0.5} step={0.01} disabled={disabled}
        format={(v) => `${Math.round(v * 100)}%`} onLive={onLiveVolume} onCommit={onCommitVolume} />
      <label className="field">
        Where it plays
        <select aria-label="Where the music plays" value={m.mode} disabled={disabled} onChange={(e) => commit({ mode: e.target.value })}>
          {MUSIC_MODES.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
      </label>
      {(m.mode === "range" || m.mode === "once") && (
        <div className="music-row">
          <TimeField label="From" value={m.offset} disabled={disabled} now={time} onSet={(v) => commit({ offset: v ?? 0 })} />
          {m.mode === "range" && (
            <TimeField label="To" value={m.until} placeholder="the end" disabled={disabled} now={time} onSet={(v) => commit({ until: v })} />
          )}
        </div>
      )}
      {m.mode === "scenes" && (
        <div className="music-scenes">
          {selected && (
            <label className="cs-check">
              <input type="checkbox" checked={saved.scenes.includes(String(selected.id))} disabled={disabled}
                onChange={(e) => commit({ scenes: e.target.checked ? [...saved.scenes, String(selected.id)] : saved.scenes.filter((x) => x !== String(selected.id)) })} />
              The selected scene{selected.title ? ` (${selected.title.slice(0, 40)})` : ""}
            </label>
          )}
          {chapters.length > 0 && <p className="micro-note">Chapters (every scene of the chapter, kept when scenes are rebuilt):</p>}
          {chapters.map((c) => (
            <label key={c} className="cs-check">
              <input type="checkbox" checked={saved.chapters.includes(c)} disabled={disabled}
                onChange={(e) => commit({ chapters: e.target.checked ? [...saved.chapters, c] : saved.chapters.filter((x) => x !== c) })} />
              {c}
            </label>
          ))}
          {(goneScenes.length > 0 || goneChapters.length > 0) && (
            <p className="micro-note mg-warn" role="status">
              {goneScenes.length > 0 && `${goneScenes.length} chosen scene${goneScenes.length > 1 ? "s are" : " is"} no longer in the timeline`}
              {goneScenes.length > 0 && goneChapters.length > 0 && " and "}
              {goneChapters.length > 0 && `chapter${goneChapters.length > 1 ? "s" : ""} ${goneChapters.map((c) => `“${c}”`).join(", ")} no longer exist${goneChapters.length > 1 ? "" : "s"}`}
              {" — no music plays there. Undo brings it back. "}
              <button type="button" className="link-btn" disabled={disabled}
                onClick={() => commit({ scenes: saved.scenes.filter((x) => ids.has(x)), chapters: saved.chapters.filter((c) => chapters.includes(c)) })}>Forget them</button>
            </p>
          )}
          {!lay.runs.length && !saved.scenes.length && !saved.chapters.length && <p className="micro-note mg-warn">No scene or chapter chosen yet: no music plays.</p>}
          {selected && saved.scenes.length > 0 && !inScene(selected) && <p className="micro-note">{saved.scenes.length} scene{saved.scenes.length > 1 ? "s" : ""} chosen individually.</p>}
        </div>
      )}
      <div className="section-label sub"><span>PART OF THE TRACK</span><small>{track ? `track ${clock(track)}` : "length unknown"}</small></div>
      <div className="music-row">
        <TimeField label="Start" value={saved.start} disabled={disabled} onSet={(v) => commit({ start: v ?? 0 })} />
        <TimeField label="End" value={saved.end} placeholder="track end" disabled={disabled} onSet={(v) => commit({ end: v })} />
      </div>
      <p className="micro-note">Uses {clock(a)}–{clock(b)} ({clock(b - a)}). The file itself is never cut or copied.</p>
      <label className="cs-check">
        <input type="checkbox" checked={m.loop} disabled={disabled || m.mode === "once"} onChange={(e) => commit({ loop: e.target.checked })} />
        Loop when the stretch is longer than the part
      </label>
      <LiveRange label="Loop crossfade" value={m.crossfade} min={0} max={10} step={0.1} disabled={disabled || !m.loop || m.mode === "once"}
        format={(v) => `${v.toFixed(1)} s`} onLive={(v) => live({ crossfade: v })} onCommit={(v) => commit({ crossfade: v })} />
      <LiveRange label="Fade in" value={m.fade_in} min={0} max={15} step={0.1} disabled={disabled}
        format={(v) => `${v.toFixed(1)} s`} onLive={(v) => live({ fade_in: v })} onCommit={(v) => commit({ fade_in: v })} />
      <LiveRange label="Fade out" value={m.fade_out} min={0} max={15} step={0.1} disabled={disabled}
        format={(v) => `${v.toFixed(1)} s`} onLive={(v) => live({ fade_out: v })} onCommit={(v) => commit({ fade_out: v })} />
      <label className="cs-check">
        <input type="checkbox" checked={m.duck} disabled={disabled} onChange={(e) => commit({ duck: e.target.checked })} />
        Auto ducking (dips under the narration and soundbites)
      </label>
      <p className="micro-note block music-summary">
        {lay.runs.length
          ? `Music under ${clock(heard)} of ${clock(total)}${lay.runs.length > 1 ? ` in ${lay.runs.length} stretches` : ""} · ${passes} pass${passes > 1 ? "es" : ""}${seams.length ? ` · ${seams.length} loop seam${seams.length > 1 ? "s" : ""}, ${lay.crossfade.toFixed(1)} s crossfade` : ""}. The documentary stays ${clock(total)}.`
          : "The music does not play anywhere with these settings."}
      </p>
      {seams.length > 0 && (
        <button className="btn" disabled={disabled} title="Hear the first loop seam in context" onClick={() => onPlayFrom(Math.max(0, seams[0] - 3))}>
          <Play size={12} /> Hear the loop seam ({clock(seams[0])})
        </button>
      )}
    </div>
  );
}

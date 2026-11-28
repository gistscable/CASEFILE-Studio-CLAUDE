import React, { useEffect, useState } from "react";
import { useFetchJob } from "./DownloadRows.jsx";
import { Trophy, CheckCircle2, AlertTriangle, Info, ScanSearch, Layers, Clapperboard, Music2, Palette, Sparkles } from "lucide-react";
import { SPORTS_NICHES } from "./motion.js";
import "./sportsedit.css";

// v0.4.79 Sports (football, boxing & MMA, wrestling): the settings of the sports engine. The video itself is built on
// the Edit page (the editing guide, the fetched clips, the crops and the auto-fit decide the shots); the engine adds
// to that timeline and everything it adds is visible and adjustable there:
//   graphics      Edit › Graphics › Sports: suggested from the narration, approved one by one, exported with the video
//   empty scenes  only scenes the guide left without a clip: a shot from the project's own footage, applied when you say
//   style         the storytelling style's look, chapter transitions and an original music bed, applied when you say
// Nothing is fetched or invented: words from the narration, pictures from this project. Every change can be undone.

export { SPORTS_NICHES };

const show = (s) => {
  const m = Math.floor((s || 0) / 60);
  const r = Math.round((s || 0) - m * 60);
  return `${m}:${r < 10 ? "0" : ""}${r}`;
};
const MOOD = { nostalgic: "Nostalgic", minimal: "Minimal", tension: "Tension", build: "Build", peak: "Peak", triumph: "Triumph" };
const LOOK = { natural: "Natural", warm: "Warm", cold: "Cold", archive: "Archive (faded colour)", punchy: "High contrast", noir: "Documentary", crime: "Crime doc", bw: "Black and white", sepia: "Sepia", faded: "Faded film" };
const TRANS = { dissolve: "dissolve", "dip-black": "dip to black" };
const KIND = { wide: "wide", action: "action", close: "close-up", crowd: "crowd", dark: "low-key", photo: "photo" };

export default function SportsEdit({ project, api, locked, onProject, onError, onNotify, onOpenEdit }) {
  const [view, setView] = useState(null);
  const [saving, setSaving] = useState(false);
  const reload = () =>
    api(`/api/projects/${project.id}/sportsedit`)
      .then(setView)
      .catch((e) => onError(e.message));
  const { job, running, follow } = useFetchJob(
    api,
    project.id,
    async (j) => {
      if (j.status === "done") onNotify?.(j.result?.summary || "Done");
      else if (j.status === "error") onError(j.message);
      try {
        onProject(await api(`/api/projects/${project.id}`));
      } catch (e) {
        /* the view still reloads */
      }
      reload();
    },
    "sportsedit",
  );
  const scenesKey = (project.scenes || []).map((s) => `${s.id}:${s.asset_id || ""}:${s.duration}:${s.transition || ""}`).join("|");
  const graphicsKey = (project.motion?.items || []).map((x) => `${x.id}:${x.status}`).join("|");
  useEffect(() => {
    reload();
  }, [project.id, (project.assets || []).length, project.narration_id, project.music_id, project.look, project.episode?.timings?.hash, scenesKey, graphicsKey]);

  const head = (
    <div className="rc-head">
      <Trophy size={22} />
      <div>
        <h2>Sports</h2>
        <p>
          The video is built on the Edit page: the editing guide places the shots, fetches the clips, renames and crops them and fits them to the
          narration. The sports engine adds the editorial graphics, fills only the scenes the guide left without a clip, and gives the edit its
          storytelling style. Everything it adds shows on the Edit timeline and can be changed or undone there. Every word on screen comes from your
          narration and every picture from this project: nothing is fetched or invented.
        </p>
      </div>
    </div>
  );
  if (!view) return <div className="rc se">{head}<p className="rc-note">Loading…</p></div>;
  if (!view.eligible)
    return (
      <div className="rc se">
        {head}
        <section className="rc-card">
          <p className="rc-note">
            <Info size={12} /> The sports tools are for football, boxing &amp; MMA and wrestling projects. Choose the niche in Episode setup; other
            projects are not changed.
          </p>
        </section>
      </div>
    );

  const off = locked || running || saving;
  const s = view.settings;
  const nar = view.narration || {};
  const g = view.graphics || {};
  const fill = view.fill || { proposals: [], waiting: [], problems: [], gaps: 0 };
  const st = view.style || { look: [], transitions: [], music: { sections: [] } };
  const seg = view.segmentation;
  const lib = view.library || [];
  const pct = running ? job?.progress || 0 : 0;

  async function patch(body) {
    setSaving(true);
    try {
      setView(await api(`/api/projects/${project.id}/sportsedit`, "PATCH", body));
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }
  async function act(path, body, done) {
    setSaving(true);
    try {
      const r = await api(`/api/projects/${project.id}/sportsedit/${path}`, "POST", body || {});
      if (r.job_id) follow(r.job_id);
      if (r.project) onProject(r.project);
      if (done) onNotify?.(done(r));
      reload();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }
  async function suggest() {
    setSaving(true);
    try {
      const r = await api(`/api/projects/${project.id}/motion/suggest`, "POST", { engine: "sports" });
      onProject(r.project);
      onNotify?.(r.added ? `${r.added} sports graphic${r.added > 1 ? "s" : ""} suggested. Review them on the Edit page (Graphics), then approve.` : "Nothing new in the narration calls for a sports graphic.");
      reload();
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rc se">
      {head}

      <section className="rc-card">
        <h3>Storytelling style</h3>
        <div className="se-styles" role="radiogroup" aria-label="Storytelling style">
          {view.styles.map((x) => (
            <label key={x.key} className={"se-style" + (s.style === x.key ? " on" : "")}>
              <input type="radio" name="se-style" checked={s.style === x.key} disabled={off} onChange={() => patch({ style: x.key })} />
              <b>
                {x.label}
                {x.key === "auto" && s.style === "auto" && view.resolved ? <small> · {view.resolved.label}</small> : null}
              </b>
              <span>{x.about}</span>
            </label>
          ))}
        </div>
        <p className="rc-note">The style decides how many graphics are suggested and what “Apply the style” below proposes. Nothing changes until you apply it.</p>
      </section>

      <section className="rc-card">
        <h3>
          <Sparkles size={14} /> Graphics on the Edit timeline
        </h3>
        <p className="rc-note">
          {nar.words ? `${nar.words} narrated words${nar.exact ? " (exact word timing)" : " (timing estimated from the captions: import word timing for exact sync)"}; ` : "No narration on the timeline yet; "}
          {nar.found ? `${nar.found} moment${nar.found > 1 ? "s" : ""} the narration supports a graphic.` : "no moment that calls for a graphic yet."}
        </p>
        <p className="rc-note">
          {g.total ? `${g.total} sports graphic${g.total > 1 ? "s" : ""} on the timeline: ${g.approved} approved, ${g.suggested} suggested, ${g.draft} draft.` : "No sports graphics on the timeline yet."}
          {g.approved > 0 && !g.export ? " Approved graphics are exported once “Add approved graphics to the export” is on (Edit › Graphics)." : ""}
        </p>
        <div className="rc-row">
          <button className="btn primary" disabled={off || !nar.found} onClick={suggest}>
            <Sparkles size={13} /> Suggest sports graphics
          </button>
          {onOpenEdit && (
            <button className="btn" onClick={onOpenEdit}>
              <Clapperboard size={13} /> Review them on the Edit page
            </button>
          )}
        </div>
        <h3 className="se-h">
          <Layers size={14} /> Text behind the player
        </h3>
        {seg?.available ? (
          <p className="se-ok">
            <CheckCircle2 size={13} /> Segmentation is available: the player's name and stacked stats go behind the player, in the preview and the export.
          </p>
        ) : (
          <>
            <p className="rc-warn">
              <AlertTriangle size={12} /> Segmentation is not available ({seg?.reason}). The graphics still preview and export, with the type in front of the player.
            </p>
            <ol className="se-how">
              {(seg?.how || []).map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ol>
            <p className="rc-note">{seg?.license}</p>
          </>
        )}
      </section>

      <section className="rc-card">
        <h3>
          <ScanSearch size={14} /> Scenes the guide left without a clip
        </h3>
        <p className="rc-note">
          Only these scenes are touched: a shot from this project's own footage (including the clips the guide fetched), chosen for what is said
          there. Scenes with a clip from the guide are never changed. A filled scene is an ordinary scene afterwards: change it on the Edit page; if
          the guide later supplies its own clip, the guide's clip wins.
        </p>
        {view.filled > 0 && <p className="rc-note">{view.filled} scene{view.filled > 1 ? "s" : ""} filled so far.</p>}
        {fill.gaps === 0 ? (
          <p className="se-ok">
            <CheckCircle2 size={13} /> Every scene has a picture.
          </p>
        ) : (
          <>
            <p className="rc-note">
              {fill.gaps} scene{fill.gaps > 1 ? "s" : ""} without a clip.
              {fill.waiting.length ? ` ${fill.waiting.length} file${fill.waiting.length > 1 ? "s are" : " is"} not analysed yet (${fill.waiting.slice(0, 3).join(", ")}${fill.waiting.length > 3 ? "…" : ""}).` : ""}
            </p>
            {fill.problems.map((p) => (
              <p key={p} className="rc-warn">
                <AlertTriangle size={12} /> {p}
              </p>
            ))}
            <div className="rc-row">
              <button className="btn" disabled={off || !lib.length || !fill.waiting.length} onClick={() => act("analyse")}>
                <ScanSearch size={13} /> Analyse footage
              </button>
              <button className="btn primary" disabled={off || !fill.proposals.length} onClick={() => act("fill", {}, (r) => `${r.filled} scene${r.filled > 1 ? "s" : ""} filled. Undo puts them back.`)}>
                Fill {fill.proposals.length || ""} scene{fill.proposals.length === 1 ? "" : "s"}
              </button>
            </div>
            {fill.proposals.length > 0 && (
              <div className="se-table se-cuts">
                {fill.proposals.map((c) => (
                  <div key={c.scene_id} className="se-row">
                    <img alt="" loading="lazy" src={`/api/projects/${project.id}/sportsedit/frame/${c.asset_id}?t=${(c.in + 0.5).toFixed(1)}`} />
                    <div className="se-cut-time">
                      <span className="se-t">{show(c.start)}</span>
                      <small>scene {c.index + 1} · {(c.end - c.start).toFixed(1)} s</small>
                    </div>
                    <div className="se-main">
                      <b>
                        {c.name} <span className="se-kind">{c.photo ? "photo" : `${KIND[c.kind] || c.kind || "shot"} from ${show(c.in)}`}</span>
                      </b>
                      <small>{c.why}</small>
                      <small>{c.need}</small>
                      <button className="text-link" disabled={off} onClick={() => act("fill", { scene_ids: [c.scene_id] }, () => `Scene ${c.index + 1} filled.`)}>
                        Fill only this scene
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      <section className="rc-card">
        <h3>
          <Palette size={14} /> Apply the style: {view.resolved?.label}
        </h3>
        <ul className="se-inputs">
          <li className={st.look[0] === st.look[1] ? "ok" : ""}>
            <Palette size={12} /> Look: {LOOK[st.look[1]] || st.look[1]}
            {st.look[0] === st.look[1] ? " (applied)" : ` (now ${LOOK[st.look[0]] || st.look[0]})`}
          </li>
          <li>
            <Layers size={12} />{" "}
            {st.transitions.length
              ? `A ${TRANS[st.transitions[0].to] || st.transitions[0].to} where ${st.transitions.length > 1 ? `each of the ${st.transitions.length} new chapters begins` : "the new chapter begins"} (only where no transition is chosen)`
              : "Transitions: none to add (cuts between chapters, or chosen by you)"}
          </li>
        </ul>
        <div className="rc-row">
          <button className="btn" disabled={off || st.look[0] === st.look[1]} onClick={() => act("style", { parts: ["look"] }, () => "Look applied. Undo puts it back.")}>
            Apply the look
          </button>
          <button className="btn" disabled={off || !st.transitions.length} onClick={() => act("style", { parts: ["transitions"] }, (r) => `${r.transitions} transition${r.transitions === 1 ? "" : "s"} added. Undo removes them.`)}>
            Add the chapter transitions
          </button>
        </div>
        <h3 className="se-h">
          <Music2 size={14} /> Music that follows the story
        </h3>
        {st.music.sections.length > 0 ? (
          <div className="se-music">
            <span className="rc-note">Arc:</span>
            {st.music.sections.map(([a, b, m]) => (
              <span key={a} className="se-mood" style={{ flexGrow: Math.max(1, b - a) }} title={`${show(a)}–${show(b)}`}>
                {MOOD[m] || m}
              </span>
            ))}
          </div>
        ) : (
          <p className="rc-note">Build the edit first: the music follows the timeline.</p>
        )}
        <p className="rc-note">
          An original music bed made for this timeline (no samples), following the arc above; it becomes the project's music, ducked under the voice
          as usual. {st.music.current ? `It replaces “${st.music.current}” as the music (the file stays in Media; undo switches back).` : ""}
        </p>
        <div className="rc-row">
          <button className="btn" disabled={off || !st.music.sections.length} onClick={() => act("music")}>
            <Music2 size={13} /> Make the music
          </button>
        </div>
      </section>

      {running && (
        <section className="rc-card">
          <div className="se-progress" aria-live="polite">
            <div className="se-bar">
              <i style={{ width: `${pct}%` }} />
            </div>
            <span className="rc-note">
              {pct}% · {job?.message || "Starting"}
            </span>
          </div>
          <button className="btn subtle" onClick={() => api(`/api/jobs/${job.id}/cancel`, "POST").catch((e) => onError(e.message))}>
            Stop
          </button>
        </section>
      )}
    </div>
  );
}

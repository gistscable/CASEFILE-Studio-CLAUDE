import React, { useEffect, useRef, useState } from "react";
import { useFetchJob } from "./DownloadRows.jsx";
import { Trophy, Upload, Download, CheckCircle2, AlertTriangle, Info, Play, RotateCcw, ScanSearch, Layers } from "lucide-react";
import "./sportsedit.css";

// v0.4.78 Sports edit: the producer's own footage cut together with the editorial graphics
// (sportsedit.py). Every word on screen comes from the narration and every picture from the
// project; the review step lets the producer switch graphics off, move a cut or swap a shot.

export const SPORTS_NICHES = ["football", "boxing", "wrestling"];

const show = (s) => {
  const m = Math.floor((s || 0) / 60);
  const r = (s || 0) - m * 60;
  return `${m}:${r < 10 ? "0" : ""}${r.toFixed(2)}`;
};
const read = (v) => {
  const parts = String(v).trim().replace(",", ".").split(":").map(Number);
  if (!parts.length || parts.some((n) => !Number.isFinite(n))) return null;
  return parts.reduce((a, b) => a * 60 + b, 0);
};

function Time({ value, onChange, label, disabled }) {
  const [text, setText] = useState(show(value));
  useEffect(() => setText(show(value)), [value]);
  return (
    <input
      className="rc-time"
      aria-label={label}
      value={text}
      disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      onBlur={() => {
        const n = read(text);
        if (n === null || Math.abs(n - value) < 0.005) setText(show(value));
        else onChange(n);
      }}
    />
  );
}

const KIND = { wide: "Wide", action: "Action", close: "Close-up", crowd: "Crowd", dark: "Low-key", photo: "Photo" };
const MOOD = { nostalgic: "Nostalgic", minimal: "Minimal", tension: "Tension", build: "Build", peak: "Peak", triumph: "Triumph" };
const emptyOverrides = () => ({ graphics: {}, moves: {}, shots: {} });

export default function SportsEdit({ project, api, locked, onProject, onError, onNotify }) {
  const [view, setView] = useState(null);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);
  const reload = () =>
    api(`/api/projects/${project.id}/sportsedit`)
      .then(setView)
      .catch((e) => onError(e.message));
  const { job, running, follow } = useFetchJob(
    api,
    project.id,
    (j) => {
      if (j.status === "done") onNotify?.(j.result?.summary || "Done");
      else if (j.status === "error") onError(j.message);
      reload();
    },
    "sportsedit",
  );
  useEffect(() => {
    reload();
  }, [project.id, (project.assets || []).length, project.narration_id, project.episode?.timings?.hash]);

  if (!view) return <div className="rc se"><p className="rc-note">Loading…</p></div>;
  const off = locked || running || saving;

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
  const ov = view.settings.overrides || emptyOverrides();
  const setOv = (fn) => {
    const next = { graphics: { ...ov.graphics }, moves: { ...ov.moves }, shots: { ...ov.shots } };
    fn(next);
    patch({ overrides: next });
  };
  async function start(path) {
    try {
      const r = await api(`/api/projects/${project.id}/sportsedit/${path}`, "POST");
      follow(r.job_id);
    } catch (e) {
      onError(e.message);
    }
  }
  async function upload(files) {
    if (!files?.length) return;
    const form = new FormData();
    for (const f of files) form.append("files", f);
    setSaving(true);
    try {
      onProject(await api(`/api/projects/${project.id}/upload`, "POST", form));
    } catch (e) {
      onError(e.message);
    } finally {
      setSaving(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const head = (
    <div className="rc-head">
      <Trophy size={22} />
      <div>
        <h2>Sports edit</h2>
        <p>
          Cuts your own footage and photos together with the editorial graphics, timed to the narration's words. Every word on screen comes
          from your narration and every picture from this project: nothing is fetched or invented.
        </p>
      </div>
    </div>
  );
  if (!view.eligible)
    return (
      <div className="rc se">
        {head}
        <section className="rc-card">
          <p className="rc-note">
            <Info size={12} /> The sports edit is for football, boxing &amp; MMA and wrestling projects. Choose the niche in Episode setup; other
            projects are not changed.
          </p>
        </section>
      </div>
    );

  const s = view.settings;
  const inp = view.inputs || {};
  const plan = view.plan;
  const lib = view.library || [];
  const videos = lib.filter((x) => x.kind === "video");
  const seg = view.segmentation;
  const changes = Object.keys(ov.graphics).length + Object.keys(ov.moves).length + Object.keys(ov.shots).length;
  const pct = running ? job?.progress || 0 : 0;
  const latest = (view.renders || [])[0];

  return (
    <div className="rc se">
      {head}

      <section className="rc-card">
        <div className="se-switch">
          <button className={"toggle" + (s.enabled ? " on" : "")} aria-label="Make the sports edit" aria-pressed={s.enabled} disabled={off} onClick={() => patch({ enabled: !s.enabled })}>
            <span />
          </button>
          <div>
            <b>Make the sports edit for this project</b>
            <p className="rc-note">The finished episode is not changed: the sports edit is rendered as its own video.</p>
          </div>
        </div>
        <label className="rc-check se-crop">
          <input type="checkbox" checked={!!s.crop} disabled={off} onChange={(e) => patch({ crop: e.target.checked })} />
          <span>Crop in slightly (keeps a broadcaster's corner logo out of shot)</span>
        </label>
        <h3 className="se-h">Storytelling style</h3>
        <div className="se-styles" role="radiogroup" aria-label="Storytelling style">
          {view.styles.map((st) => (
            <label key={st.key} className={"se-style" + (s.style === st.key ? " on" : "")}>
              <input type="radio" name="se-style" checked={s.style === st.key} disabled={off} onChange={() => patch({ style: st.key })} />
              <b>
                {st.label}
                {st.key === "auto" && plan && s.style === "auto" ? <small> · {plan.style_label}</small> : null}
              </b>
              <span>{st.about}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="rc-card">
        <h3>What the edit is made from</h3>
        <ul className="se-inputs">
          <Check ok={!!inp.narration} label={inp.narration ? `Narration: ${inp.narration.name} (${show(inp.narration.duration || 0)})` : "Narration audio"} />
          <Check ok={inp.timings > 0} label={inp.timings ? `Word timing: ${inp.timings} words` : "Word timing (Voice tab, Timing)"} />
          <Check ok={!!inp.script} label="Script (all the words on screen)" />
          <Check ok={lib.length > 0} label={lib.length ? `${videos.length} clip${videos.length === 1 ? "" : "s"}, ${lib.length - videos.length} photo${lib.length - videos.length === 1 ? "" : "s"}` : "Your own footage or photos"} />
        </ul>
        {(inp.problems || []).map((p) => (
          <p key={p} className="rc-warn">
            <AlertTriangle size={12} /> {p}
          </p>
        ))}
        {lib.length > 0 && (
          <div className="se-lib">
            {lib.map((x) => (
              <div key={x.id} className="se-lib-item">
                <img alt="" loading="lazy" src={`/api/projects/${project.id}/sportsedit/frame/${x.id}?t=${x.kind === "video" ? Math.min(5, (x.duration || 10) / 3).toFixed(1) : 0}`} />
                <span title={x.name}>{x.name}</span>
                <small>{x.missing ? "file missing" : !x.analysed ? "not analysed yet" : x.kind === "video" ? `${x.shots.length} shots` : "photo"}</small>
              </div>
            ))}
          </div>
        )}
        <div className="rc-row">
          <button className="btn" disabled={off} onClick={() => fileRef.current?.click()}>
            <Upload size={13} /> Add footage or photos
          </button>
          <input ref={fileRef} type="file" hidden multiple accept="video/*,image/*" onChange={(e) => upload(e.target.files)} />
          <button className="btn" disabled={off || !lib.some((x) => !x.analysed && !x.missing)} onClick={() => start("analyse")}>
            <ScanSearch size={13} /> Analyse footage
          </button>
        </div>
        <p className="rc-note">
          Photos are used only where their file name matches what the narration says (e.g. <i>camp_nou_2010.jpg</i> when "Camp Nou" is spoken).
          Footage is described from its pictures (wide, action, close-up, crowd, low-key), never identified.
        </p>
      </section>

      {plan && (
        <section className="rc-card">
          <div className="se-review-head">
            <h3>Review before rendering</h3>
            <span className="rc-note">
              {plan.style_label} · {show(plan.duration)} · {plan.cuts.length} shots · {plan.graphics.filter((g) => g.on).length} graphics
            </span>
            {changes > 0 && (
              <button className="btn subtle" disabled={off} onClick={() => patch({ overrides: emptyOverrides() })}>
                <RotateCcw size={12} /> Undo my {changes} change{changes === 1 ? "" : "s"}
              </button>
            )}
          </div>
          {(plan.problems || []).map((p) => (
            <p key={p} className="rc-warn">
              <AlertTriangle size={12} /> {p}
            </p>
          ))}
          {plan.stale?.length > 0 && (
            <p className="rc-warn">
              <Info size={12} /> {plan.stale.length} of your changes no longer match a cut (the plan changed). They are ignored until you undo them.
            </p>
          )}

          <h4 className="se-sub">
            <Layers size={13} /> Graphics (text from the narration)
          </h4>
          <div className="se-table se-graphics">
            {plan.graphics.map((g) => (
              <div key={g.key} className={"se-row" + (g.on ? "" : " off")}>
                <button
                  className={"toggle" + (g.on ? " on" : "")}
                  aria-label={`${g.on ? "Switch off" : "Switch on"} ${g.label} at ${show(g.t_in)}`}
                  aria-pressed={g.on}
                  disabled={off}
                  onClick={() => setOv((n) => (n.graphics[g.key] = !g.on))}
                >
                  <span />
                </button>
                <span className="se-t">{show(g.t_in)}</span>
                <div className="se-main">
                  <b>{g.label}</b>
                  <span className="se-text">{g.text}</span>
                  <small>
                    {g.why}
                    {g.note ? ` · ${g.note}` : ""}
                  </small>
                  {g.warning && (
                    <small className="se-warn">
                      <AlertTriangle size={11} /> {g.warning}
                    </small>
                  )}
                </div>
              </div>
            ))}
          </div>

          <h4 className="se-sub">
            <Play size={13} /> Shots
          </h4>
          <div className="se-table se-cuts">
            {plan.cuts.map((c, i) => {
              const hand = !!(ov.moves[c.key] !== undefined || ov.shots[c.key]);
              return (
                <div key={c.key} className={"se-row" + (c.asset_id ? "" : " off")}>
                  {c.asset_id ? (
                    <img alt="" loading="lazy" src={`/api/projects/${project.id}/sportsedit/frame/${c.asset_id}?t=${c.photo ? 0 : (c.in + 0.3).toFixed(1)}`} />
                  ) : (
                    <div className="se-noimg">no footage</div>
                  )}
                  <div className="se-cut-time">
                    {i === 0 ? (
                      <span className="se-t">{show(c.t)}</span>
                    ) : (
                      <Time value={c.t} label={`Cut ${i + 1} time`} disabled={off} onChange={(v) => setOv((n) => (n.moves[c.key] = v))} />
                    )}
                    <small>{(c.end - c.t).toFixed(1)} s</small>
                  </div>
                  <div className="se-main">
                    <b>
                      {KIND[c.kind] || "Shot"}
                      {c.speed < 0.95 ? ` · ${c.speed}× slow motion` : ""} <span className="se-grade">{c.grade.replace("_", " ")}</span>
                      {c.moved && <span className="badge amber">moved</span>}
                      {c.hand && <span className="badge amber">your pick</span>}
                    </b>
                    <small>{c.need}</small>
                    <small>Why this shot: {c.why}</small>
                    <div className="se-swap">
                      <select
                        aria-label={`Shot for cut ${i + 1}`}
                        disabled={off}
                        value=""
                        onChange={(e) => {
                          const [aid, t0] = e.target.value.split("|");
                          if (aid) setOv((n) => (n.shots[c.key] = { asset_id: aid, in: Number(t0) + 0.15 }));
                        }}
                      >
                        <option value="">Swap shot: {c.name ? `${c.name}${c.photo ? "" : " @ " + show(c.in)}` : "choose"}</option>
                        {lib
                          .filter((x) => x.analysed)
                          .map((x) =>
                            x.kind === "image" ? (
                              <option key={x.id} value={`${x.id}|0`}>
                                Photo: {x.name}
                              </option>
                            ) : (
                              <optgroup key={x.id} label={x.name}>
                                {x.shots.map((sh) => (
                                  <option key={sh.t0} value={`${x.id}|${sh.t0}`}>
                                    {show(sh.t0)}–{show(sh.t1)} {KIND[sh.kind] || sh.kind}
                                  </option>
                                ))}
                              </optgroup>
                            ),
                          )}
                      </select>
                      {c.asset_id && !c.photo && (
                        <label className="se-in">
                          from
                          <Time value={c.in} label={`Cut ${i + 1} source start`} disabled={off} onChange={(v) => setOv((n) => (n.shots[c.key] = { asset_id: c.asset_id, in: v }))} />
                        </label>
                      )}
                      {hand && (
                        <button
                          className="text-link"
                          disabled={off}
                          onClick={() =>
                            setOv((n) => {
                              delete n.moves[c.key];
                              delete n.shots[c.key];
                            })
                          }
                        >
                          <RotateCcw size={11} /> automatic
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="se-music">
            <span className="rc-note">Music arc:</span>
            {plan.music.map(([a, b, m]) => (
              <span key={a} className="se-mood" style={{ flexGrow: Math.max(1, b - a) }} title={`${show(a)}–${show(b)}`}>
                {MOOD[m] || m}
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="rc-card">
        <h3>Render</h3>
        <div className="rc-row">
          <button className="btn primary" disabled={off || !s.enabled || !plan || (inp.problems || []).length > 0 || !lib.length} onClick={() => start("render")}>
            <Play size={13} /> {latest ? "Render again" : "Render the sports edit"}
          </button>
          {running && (
            <button className="btn subtle" onClick={() => api(`/api/jobs/${job.id}/cancel`, "POST").catch((e) => onError(e.message))}>
              Stop
            </button>
          )}
          {!s.enabled && <span className="rc-note">Switch the sports edit on first.</span>}
        </div>
        {running && (
          <div className="se-progress" aria-live="polite">
            <div className="se-bar">
              <i style={{ width: `${pct}%` }} />
            </div>
            <span className="rc-note">
              {pct}% · {job?.message || "Starting"}
            </span>
          </div>
        )}
        <p className="rc-note">
          The picture is rendered in parts. A change re-renders only the parts it touches, so the second render after a review change is much
          faster. On a Mac with VideoToolbox the hardware encoder is used.
        </p>
        {latest && (
          <div className="rc-result se-result">
            <video controls preload="metadata" src={latest.file} />
            <p>
              <CheckCircle2 size={12} /> {show(latest.duration)} · {latest.style} · {latest.cuts} shots · {latest.graphics} graphics
              {latest.behind ? " · type behind the players" : ""} · rendered in {Math.round(latest.seconds / 60)} min
              {latest.reused ? ` (${latest.reused} parts reused)` : ""}
            </p>
            <a className="btn" href={latest.file} download>
              <Download size={13} /> Download
            </a>
          </div>
        )}
        {(view.renders || []).length > 1 && (
          <details className="rc-paste">
            <summary>Earlier renders</summary>
            {view.renders.slice(1).map((r) => (
              <p key={r.id}>
                <a className="text-link" href={r.file} download>
                  <Download size={11} /> {new Date(r.at).toLocaleString()} · {show(r.duration)} · {r.style}
                </a>
              </p>
            ))}
          </details>
        )}
      </section>

      <section className="rc-card">
        <h3>Text behind the players</h3>
        {seg.available ? (
          <p className="se-ok">
            <CheckCircle2 size={12} /> Available: names and stats can sit behind the player (model {seg.model?.split("/").pop()}).
          </p>
        ) : (
          <>
            <p className="rc-note">
              <Info size={12} /> Not available here ({seg.reason}). The edit still renders and the text goes in front of the players instead.
            </p>
            <ol className="se-how">
              {seg.how.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ol>
            <p className="rc-note">{seg.license}</p>
          </>
        )}
      </section>
    </div>
  );
}

function Check({ ok, label }) {
  return (
    <li className={ok ? "ok" : "missing"}>
      {ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />} {label}
    </li>
  );
}

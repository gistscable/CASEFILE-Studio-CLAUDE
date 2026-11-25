import React, { useEffect, useRef, useState } from "react";
import DownloadRows, { useFetchJob } from "./DownloadRows.jsx";
import { splitWho } from "./effects.js";
import { Scissors, Upload, Download, CheckCircle2, AlertTriangle, Info, ExternalLink, Plus, Trash2 } from "lucide-react";

// v0.4.22 Re-cut: put the real voices into a finished video. At each insert the
// video stops ("at"), the original clip plays with its own picture and sound,
// and the video carries on from "until", skipping the narrator's version.

const show = (s) => {
  const m = Math.floor((s || 0) / 60);
  const r = (s || 0) - m * 60;
  return `${m}:${r < 10 ? "0" : ""}${Number.isInteger(r) ? r : r.toFixed(2)}`;
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
      onBlur={() => {
        const n = read(text);
        if (n === null) setText(show(value));
        else onChange(n);
      }}
    />
  );
}

// The first chosen clip of each person (in playing order) gets the name card.
function cardKeys(rows) {
  const keys = new Set();
  const seen = new Set();
  for (const r of rows.filter((x) => x.include).sort((a, b) => a.at - b.at)) {
    if (!seen.has(r.source_id)) {
      seen.add(r.source_id);
      keys.add(r.key);
    }
  }
  return keys;
}

// v0.4.38 What the server needs to plan an insert's picture cutaways.
const planInput = (r, card) => ({
  start: r.start, end: r.end, who: r.who || "", words: r.words || "", cutaways: r.cutaways || [], card, off: r.cut_off || [], pick: r.cut_pick || {},
});

// v0.4.38 The picture cutaways of one insert: the speaker's sound plays on underneath.
function Cutaways({ n, plan, pictures, disabled, onToggle, onPick }) {
  if (!plan) return null;
  const off = new Set(plan.off || []);
  if (!plan.cutaways.length && !off.size && !plan.warnings.length) return null;
  return (
    <div className="rc-cuts">
      <span className="rc-cuts-title">
        Cutaways {plan.auto ? <em>automatic</em> : <em>from your list</em>} · the speaker is heard throughout
      </span>
      {plan.auto && plan.why && plan.cutaways.length > 0 && <span className="rc-note rc-cuts-why">{plan.why}</span>}
      <div className="rc-cuts-row">
        {plan.cutaways.map((c) => (
          <div key={c.n} className="rc-cut">
            <div className="rc-cut-pic" style={{ backgroundImage: c.thumb ? `url("${c.thumb}")` : undefined }} />
            <div className="rc-cut-text">
              <b>
                {show(c.from)}–{show(c.to)}
              </b>
              <select aria-label={`Insert ${n + 1} cutaway at ${show(c.from)} picture`} value={c.asset_id} disabled={disabled} onChange={(e) => onPick(c.n, e.target.value)}>
                {!pictures.some((p) => p.id === c.asset_id) && <option value={c.asset_id}>{c.name}</option>}
                {pictures.filter((p) => plan.speaker !== "family" || p.bucket !== "S").map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <button className="rc-cut-x" aria-label={`Insert ${n + 1} turn off cutaway at ${show(c.from)}`} title="Stay on the speaker here" disabled={disabled} onClick={() => onToggle(c.n)}>
              ×
            </button>
          </div>
        ))}
        {[...off].map((i) => (
          <button key={"off" + i} className="rc-cut-off" disabled={disabled} aria-label={`Insert ${n + 1} turn cutaway ${i + 1} back on`} onClick={() => onToggle(i)}>
            Cutaway {i + 1} off · turn back on
          </button>
        ))}
      </div>
      {plan.warnings.map((w, i) => (
        <p key={i} className="rc-note">
          <Info size={11} /> {w}
        </p>
      ))}
    </div>
  );
}

// v0.4.39 Play exactly the part of the file this insert will use, so you see its own picture first.
function ClipPreview({ src, n, start, end }) {
  const ref = useRef(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const stop = () => {
      if (v.currentTime >= end) v.pause();
    };
    v.addEventListener("timeupdate", stop);
    return () => v.removeEventListener("timeupdate", stop);
  }, [open, end]);
  if (!src?.url) return null;
  return (
    <div className="rc-preview">
      {!open ? (
        <button className="btn" aria-label={`Preview the clip of insert ${n + 1}`} onClick={() => setOpen(true)}>
          ▶ See this clip ({show(start)}–{show(end)} of {src.id})
        </button>
      ) : (
        <>
          <video
            ref={ref}
            controls
            autoPlay
            preload="auto"
            src={`${src.url}#t=${start.toFixed(2)},${end.toFixed(2)}`}
            onLoadedMetadata={(e) => {
              e.currentTarget.currentTime = start;
            }}
          />
          <span className="rc-note">This is the picture and sound that will play at this insert, from {src.name}.</span>
        </>
      )}
    </div>
  );
}

export default function Recut({ project, api, locked, onProject, onError, onNotify }) {
  const [view, setView] = useState(null);
  const [video, setVideo] = useState("");
  const [text, setText] = useState("");
  const [rows, setRows] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [jobKind, setJobKind] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cards, setCards] = useState(false); // v0.4.30 optional name cards from the Who column
  const [autoCut, setAutoCut] = useState(false); // v0.4.38 automatic cutaways on long clips (off unless you tick it)
  const [plans, setPlans] = useState({});
  const [pictures, setPictures] = useState([]);
  const listRef = useRef(null);
  const videoRef = useRef(null);
  const base = `/api/projects/${project.id}/recut`;

  const toRows = (inserts) =>
    inserts.map((i, n) => ({ ...i, key: `${n}-${i.source_id}-${i.at}`, include: !i.optional && !!i.file, audio_ok: false, card: splitWho(i.who) }));
  const accept = (v, replaceRows) => {
    setView(v);
    setVideo((cur) => (cur && v.videos.some((x) => x.kind + ":" + x.id === cur) ? cur : v.videos[0] ? v.videos[0].kind + ":" + v.videos[0].id : ""));
    if (replaceRows) setRows(toRows(v.inserts));
  };
  const load = (replaceRows) => api(base).then((v) => accept(v, replaceRows)).catch(onError);
  // v0.4.27: the clip downloads, each with its own bar and Retry.
  const fetchJob = useFetchJob(api, project.id, async (j) => {
    try {
      onProject(await api(`/api/projects/${project.id}`));
      const v = await api(base);
      accept(v, false);
      // Clips that just arrived are ticked, as they would have been if they were here at the start.
      const here = new Set(v.sources.map((s) => s.id));
      setRows((rs) => rs.map((r) => (!r.file && here.has(r.source_id) ? { ...r, file: true, include: !r.optional } : r)));
    } catch (e) {
      /* the next refresh shows it */
    }
    const failed = (j.result?.results || []).filter((x) => !x.ok);
    onNotify(
      j.status === "done" ? (j.result?.summary || "Clips fetched.") + (failed.length ? " Use Retry on the ones that failed." : "") : j.message || "The download did not finish.",
      j.status === "done" && !failed.length ? "success" : "info",
    );
  }, "clip-fetch");
  useEffect(() => {
    load(true);
  }, [project.id]);
  useEffect(() => {
    if (view) load(false);
  }, [project.assets.length, project.exports?.length]);
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = (await api(`/api/projects/${project.id}/jobs`)).find((x) => x.id === jobId);
        if (stop) return;
        if (j && !["running", "queued"].includes(j.status)) {
          setJobId(null);
          load(false);
          onNotify(j.status === "done" ? j.result?.summary || "Re-cut ready." : j.message || "The re-cut did not finish.", j.status === "done" ? "success" : "info");
          return;
        }
      } catch (e) {
        /* keep polling */
      }
      if (!stop) setTimeout(tick, 1500);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [jobId]);

  // v0.4.38 Ask the server which pictures each insert will cut away to.
  const planKey = JSON.stringify([autoCut, cards, rows.map((r) => [r.key, r.include, r.start, r.end, r.who, r.cut_off, r.cut_pick, r.source_id, r.card])]);
  useEffect(() => {
    if (!rows.length) return;
    const keys = cardKeys(rows);
    const timer = setTimeout(() => {
      api(`${base}/cutaways`, "POST", {
        auto: autoCut,
        inserts: rows.map((r) => planInput(r, cards && keys.has(r.key) && !!(r.card?.name || r.card?.role))),
      })
        .then((res) => {
          const next = {};
          rows.forEach((r, i) => (next[r.key] = res.plans[i]));
          setPlans(next);
          setPictures(res.pictures || []);
        })
        .catch(() => {});
    }, 350);
    return () => clearTimeout(timer);
  }, [planKey]);

  if (!view) return <div className="rc"><p className="rc-note">Loading…</p></div>;
  const off = locked || busy || !!jobId || fetchJob.running || project.is_demo;
  const set = (key, patch) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const sourceOf = (id) => view.sources.find((s) => s.id === id);
  const chosen = rows.filter((r) => r.include);
  const firstOf = cardKeys(rows);
  // v0.4.46 The inserts the "all" audio tick covers: ticked, with their clip here and sound in it.
  const audioRows = chosen.filter((r) => sourceOf(r.source_id)?.has_audio);
  const ready = video && chosen.length > 0 && chosen.every((r) => sourceOf(r.source_id) && r.audio_ok && r.end > r.start);
  const added = chosen.reduce((a, r) => a + Math.max(0, r.end - r.start) - Math.max(0, (r.until ?? r.at) - r.at), 0);

  async function readList(value) {
    setBusy(true);
    try {
      const v = await api(`${base}/list`, "POST", { text: value });
      accept(v, true);
      setText("");
      onNotify(`${v.inserts.length} insert${v.inserts.length === 1 ? "" : "s"} read from the list. Check the times, then tick the ones to use.`);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  async function uploadVideo(file) {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("files", file);
      onProject(await api(`/api/projects/${project.id}/upload`, "POST", form));
      onNotify("Video added. Choose it under “The video to re-cut”.");
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  function start() {
    const [kind, id] = video.split(":");
    api(`${base}/render`, "POST", {
      video: { kind, id },
      inserts: chosen.map((r) => ({
        at: r.at, until: r.until ?? r.at, source_id: r.source_id, start: r.start, end: r.end, audio_ok: r.audio_ok,
        ...(cards && firstOf.has(r.key) && (r.card?.name || r.card?.role) ? { lower_third: r.card } : {}),
        ...planInput(r, false),
      })),
      auto_cutaways: autoCut,
    })
      .then((r) => {
        setJobKind("render");
        setJobId(r.job_id);
      })
      .catch(onError);
  }
  function fetchClips(only) {
    api(`${base}/fetch`, "POST", { confirm_responsibility: agree || view.fetch_acknowledged, ...(only ? { only } : {}) })
      .then((r) => {
        fetchJob.follow(r.job_id);
        onNotify(only ? `Retrying ${only.join(", ")}.` : "Downloading the clips. Each clip shows its own progress below.");
      })
      .catch(onError);
  }
  const todo = (view.fetch || []).filter((f) => f.status === "todo");
  const manual = (view.fetch || []).filter((f) => f.status === "manual");

  return (
    <div className="rc">
      <header className="rc-head">
        <Scissors size={20} />
        <div>
          <h2>Re-cut</h2>
          <p>
            Put the real voices into a finished video. At each insert the video stops, the original clip plays with its
            own picture and sound, and the video carries on after the narrator’s version of the same words. Each line is
            heard once, from the real speaker.
          </p>
        </div>
      </header>

      <section className="rc-card">
        <h3>1 · The video to re-cut</h3>
        <div className="rc-row">
          <select aria-label="The video to re-cut" value={video} disabled={off} onChange={(e) => setVideo(e.target.value)}>
            {view.videos.length === 0 && <option value="">No finished video in this project yet</option>}
            {view.videos.map((v) => (
              <option key={v.kind + v.id} value={v.kind + ":" + v.id}>
                {v.label} · {show(Math.round(v.duration || 0))}
              </option>
            ))}
          </select>
          <button className="btn" disabled={off} onClick={() => videoRef.current?.click()}>
            <Upload size={13} /> Upload a video instead
          </button>
          <input ref={videoRef} type="file" accept="video/mp4,video/quicktime,.mp4,.mov,.mkv,.webm" hidden
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadVideo(f); }} />
        </div>
        <p className="rc-note">Videos you rendered here are listed automatically, newest first.</p>
      </section>

      <section className="rc-card">
        <h3>2 · Where the real clips go</h3>
        <div className="rc-row">
          <button className="btn primary" disabled={off} onClick={() => listRef.current?.click()}>
            <Upload size={13} /> Load my re-cut list
          </button>
          <input ref={listRef} type="file" accept=".md,.txt,text/markdown,text/plain" hidden
            onChange={async (e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) readList(await f.text()); }} />
          <button
            className="btn"
            disabled={off || !view.sources.length}
            onClick={() =>
              setRows((rs) => [...rs, { key: "new" + Date.now(), at: 0, until: 0, source_id: view.sources[0].id, start: 0, end: 5, who: "", words: "", include: true, audio_ok: false, file: view.sources[0].name }])
            }
          >
            <Plus size={13} /> Add one by hand
          </button>
        </div>
        <details className="rc-paste">
          <summary>or paste the list</summary>
          <textarea aria-label="Paste the re-cut list" value={text} disabled={off} onChange={(e) => setText(e.target.value)} placeholder="Paste the whole re-cut list here." />
          <button className="btn" disabled={off || !text.trim()} onClick={() => readList(text)}>
            Read the list
          </button>
        </details>

        {(todo.length > 0 || manual.length > 0) && (
          <div className="rc-fetch">
            <p>
              <Download size={14} />{" "}
              {todo.length > 0 ? (
                <>
                  <b>
                    {todo.length} clip{todo.length === 1 ? " is" : "s are"} not in the project yet
                  </b>{" "}
                  ({todo.map((f) => f.id).join(", ")}). Casefile can download {todo.length === 1 ? "it" : "them"} from YouTube
                  for you and name {todo.length === 1 ? "it" : "them"} so the inserts find {todo.length === 1 ? "it" : "them"}.
                </>
              ) : (
                <b>Some clips have no YouTube link.</b>
              )}
            </p>
            {todo.length > 0 && !view.fetch_acknowledged && (
              <label className="rc-check">
                <input type="checkbox" aria-label="I accept the download notice" checked={agree} disabled={off} onChange={(e) => setAgree(e.target.checked)} />
                <span className="rc-note">{view.fetch_notice}</span>
              </label>
            )}
            {todo.length > 0 && (
              <div className="rc-row">
                <button className="btn primary" aria-label="Fetch these clips" disabled={off || (!agree && !view.fetch_acknowledged)} onClick={() => fetchClips()}>
                  <Download size={13} /> {fetchJob.running ? "Downloading…" : `Fetch ${todo.length === 1 ? "this clip" : `these ${todo.length} clips`}`}
                </button>
              </div>
            )}
            {manual.map((f) => (
              <p key={f.id} className="rc-warn">
                <AlertTriangle size={12} /> {f.note}
              </p>
            ))}
          </div>
        )}
        <DownloadRows
          job={fetchJob.job}
          running={fetchJob.running}
          disabled={off}
          onRetry={(ids) => fetchClips(ids)}
          onStop={() => fetchJob.job && api(`/api/jobs/${fetchJob.job.id}/cancel`, "POST").catch(onError)}
        />
        {rows.length > 0 && (
          <label className="rc-check rc-cards">
            <input type="checkbox" aria-label="Name cards on the clips" checked={cards} disabled={off} onChange={(e) => setCards(e.target.checked)} />
            Add a name card when each person first speaks (from the list’s “Who” column; check the names below)
          </label>
        )}
        {rows.length > 0 && (
          <label className="rc-check">
            <input type="checkbox" aria-label="Automatic cutaways on long clips" checked={autoCut} disabled={off} onChange={(e) => setAutoCut(e.target.checked)} />
            Cut away on long clips (12 s or more) that have no cutaways in the list, to base images of what the clip is about: the victim when family, the judge or the prosecution speaks; the suspect for the defence; the place for the defendant, police and witnesses; the subject of the words when the list gives them. Never a courtroom picture. The speaker’s sound plays on; the picture starts and ends on their face.
          </label>
        )}
        {audioRows.length > 1 && (
          <label className="rc-check rc-all-audio">
            <input
              type="checkbox"
              aria-label="I may play the original audio of every ticked insert"
              checked={audioRows.every((r) => r.audio_ok)}
              disabled={off}
              onChange={(e) => {
                const keys = new Set(audioRows.map((r) => r.key));
                const on = e.target.checked;
                setRows((rs) => rs.map((r) => (keys.has(r.key) ? { ...r, audio_ok: on } : r)));
              }}
            />
            <b>I may play the original audio of all {audioRows.length} ticked inserts in my video</b>
            <span className="rc-note">(ticks each one below; untick any you have not cleared)</span>
          </label>
        )}
        {rows.length === 0 && <p className="rc-note">No inserts yet. Load the re-cut list your guide writer gave you, or add one by hand.</p>}
        {rows.map((r, n) => {
          const src = sourceOf(r.source_id);
          return (
            <div key={r.key} className={"rc-insert" + (r.include ? "" : " off")}>
              <label className="rc-check">
                <input type="checkbox" aria-label={`Use insert ${n + 1}`} checked={r.include} disabled={off} onChange={(e) => set(r.key, { include: e.target.checked })} />
                <b>Insert {n + 1}</b>
                {r.optional && <span className="rc-tag">optional</span>}
              </label>
              <div className="rc-body">
                <p className="rc-note rc-skip">
                  {(r.until ?? r.at) > r.at
                    ? `The video skips ${show(Math.round(((r.until ?? r.at) - r.at) * 100) / 100)} here: the narrator’s version of these words is left out, so the line is heard once.`
                    : "Nothing is skipped here: the clip is added and the video carries on from the same point."}
                </p>
                {(r.who || r.words) && (
                  <p className="rc-who">
                    {r.who && <b>{r.who}</b>} {r.words && <i>“{r.words}”</i>}
                  </p>
                )}
                <div className="rc-fields">
                  <label>
                    <span>Stop the video at</span>
                    <Time label={`Insert ${n + 1} time in the video`} value={r.at} disabled={off} onChange={(v) => set(r.key, { at: v, until: Math.max(r.until ?? v, v) })} />
                  </label>
                  <label>
                    <span>and continue it from</span>
                    <Time label={`Insert ${n + 1} continue from`} value={r.until ?? r.at} disabled={off} onChange={(v) => set(r.key, { until: Math.max(v, r.at) })} />
                  </label>
                  <label>
                    <span>Play this clip</span>
                    <select aria-label={`Insert ${n + 1} clip`} value={r.source_id} disabled={off} onChange={(e) => set(r.key, { source_id: e.target.value })}>
                      {!src && <option value={r.source_id}>{r.source_id || "choose"} (not in the project)</option>}
                      {view.sources.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.id} · {s.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>from</span>
                    <Time label={`Insert ${n + 1} clip start`} value={r.start} disabled={off} onChange={(v) => set(r.key, { start: v })} />
                  </label>
                  <label>
                    <span>to</span>
                    <Time label={`Insert ${n + 1} clip end`} value={r.end} disabled={off} onChange={(v) => set(r.key, { end: v })} />
                  </label>
                  {r.video_id && (
                    <a href={`https://www.youtube.com/watch?v=${r.video_id}&t=${Math.floor(r.start)}s`} target="_blank" rel="noreferrer">
                      Listen on YouTube <ExternalLink size={11} />
                    </a>
                  )}
                  <button className="btn rc-remove" aria-label={`Remove insert ${n + 1}`} disabled={off} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                    <Trash2 size={12} />
                  </button>
                </div>
                {!src ? (
                  <p className="rc-warn">
                    <AlertTriangle size={12} /> {r.source_id || "This clip"} is not in the project yet. {todo.some((f) => f.id === r.source_id) ? `Use “Fetch ${todo.length === 1 ? "this clip" : "these clips"}” above, or upload it named ${r.source_id}.mp4.` : `Upload it named ${r.source_id || "S01"}.mp4.`}
                  </p>
                ) : !src.has_audio ? (
                  <p className="rc-warn">
                    <AlertTriangle size={12} /> {src.name} has no sound.
                  </p>
                ) : (
                  <>
                    {r.approximate && (
                      <p className="rc-note">
                        <Info size={12} /> These clip times are approximate. Listen on YouTube and set “from” and “to” to the exact words.
                      </p>
                    )}
                    {cards && r.include && firstOf.has(r.key) && (
                      <div className="rc-card-fields">
                        <input aria-label={`Insert ${n + 1} name card name`} placeholder="Name" value={r.card?.name || ""} disabled={off} onChange={(e) => set(r.key, { card: { ...r.card, name: e.target.value } })} />
                        <input aria-label={`Insert ${n + 1} name card role`} placeholder="Who they are" value={r.card?.role || ""} disabled={off} onChange={(e) => set(r.key, { card: { ...r.card, role: e.target.value } })} />
                      </div>
                    )}
                    <ClipPreview src={src} n={n} start={r.start} end={r.end} />
                    {r.include && (
                      <Cutaways
                        n={n}
                        plan={plans[r.key]}
                        pictures={pictures}
                        disabled={off}
                        onToggle={(i) => {
                          const cur = new Set(r.cut_off || []);
                          cur.has(i) ? cur.delete(i) : cur.add(i);
                          set(r.key, { cut_off: [...cur] });
                        }}
                        onPick={(i, id) => set(r.key, { cut_pick: { ...(r.cut_pick || {}), [i]: id } })}
                      />
                    )}
                    <label className="rc-check">
                      <input type="checkbox" aria-label={`I may play the original audio of insert ${n + 1}`} checked={r.audio_ok} disabled={off || !r.include} onChange={(e) => set(r.key, { audio_ok: e.target.checked })} />
                      I may play this clip’s original audio in my video
                    </label>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </section>

      <section className="rc-card">
        <h3>3 · Make it</h3>
        <div className="rc-row">
          <button className="btn primary" aria-label="Make the re-cut" disabled={off || !ready} onClick={start}>
            <Scissors size={13} /> {jobId && jobKind === "render" ? "Re-cutting…" : `Make the re-cut${chosen.length ? ` (${chosen.length} clip${chosen.length === 1 ? "" : "s"}, ${added >= 0 ? "+" : "−"}${show(Math.round(Math.abs(added)))})` : ""}`}
          </button>
          {!ready && !jobId && (
            <span className="rc-note">
              {!video ? "Choose a video first." : !chosen.length ? "Tick at least one insert." : "Each ticked insert needs its clip in the project and the audio tick."}
            </span>
          )}
        </div>
        {view.recuts.map((r) => (
          <div key={r.id} className="rc-result">
            <p>
              <CheckCircle2 size={13} /> Re-cut made {new Date(r.at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} · {show(Math.round(r.duration))} · {r.inserts.length} clip{r.inserts.length === 1 ? "" : "s"} · {(r.size / 1048576).toFixed(0)} MB
            </p>
            <video controls preload="none" src={r.url} />
            {r.checks?.length > 0 && (
              <div className="rc-proof">
                <span className="rc-note">
                  <CheckCircle2 size={12} /> Picture check passed: each clip shows its own picture in the finished video. Click a frame to jump there.
                </span>
                <div className="rc-proof-row">
                  {r.checks.map((c) => (
                    <button
                      key={c.n}
                      className="rc-proof-item"
                      aria-label={`Jump to clip ${c.n}`}
                      onClick={(e) => {
                        const v = e.currentTarget.closest(".rc-result").querySelector("video");
                        v.currentTime = c.at + 0.5;
                        v.play().catch(() => {});
                      }}
                    >
                      {c.proof && <img alt="" src={`/api/projects/${project.id}/recut/check/${r.id}/${c.proof}`} />}
                      <span>
                        Clip {c.n} · {show(Math.round(c.at))}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <a className="btn" href={r.url} download>
              <Download size={13} /> Download the re-cut
            </a>
          </div>
        ))}
      </section>
    </div>
  );
}

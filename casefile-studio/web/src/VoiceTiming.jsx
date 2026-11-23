import React, { useEffect, useRef, useState } from "react";
import { Mic, Clock3, Download, CheckCircle2, AlertTriangle, Info, Settings2, Upload, ExternalLink } from "lucide-react";

// v0.4.21 Voice and timing. Two choices each, in every way of working:
//   voice  = your own recording (upload) or your cloned voice (generated here);
//   timing = CapCut's SRT/JSON (upload) or Whisper on this computer.
// Everything generated can be downloaded.

const clock = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.round((s || 0) % 60)).padStart(2, "0")}`;
const SOURCE_LABEL = {
  locked: "The locked script from the Case desk",
  script: "The script in Episode setup",
  text: "Narration I paste here",
};

export default function VoiceTiming({ project, api, disabled, onProject, onError, onNotify }) {
  const [view, setView] = useState(null);
  const [source, setSource] = useState("");
  const [text, setText] = useState("");
  const [model, setModel] = useState("base.en");
  const [job, setJob] = useState(null); // {id, kind}
  const [settings, setSettings] = useState(false);
  const [form, setForm] = useState({ base: "", key: "", model: "" });
  const base = `/api/projects/${project.id}/voice`;
  const sampleRef = useRef(null);
  const resultRef = useRef(null);
  const [busy, setBusy] = useState("");

  const accept = (v) => {
    setView(v);
    setSource((cur) => cur || (v.sources.locked ? "locked" : v.sources.script ? "script" : "text"));
    setForm((f) => ({ base: f.base || v.settings.base, key: "", model: f.model || v.settings.model }));
  };
  const load = () => api(base).then(accept).catch(() => {});
  useEffect(() => {
    load();
  }, [project.id, project.narration_id, project.episode?.script?.hash]);
  useEffect(() => {
    if (!job) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = (await api(`/api/projects/${project.id}/jobs`)).find((x) => x.id === job.id);
        if (stop) return;
        if (j && !["running", "queued"].includes(j.status)) {
          setJob(null);
          onProject(await api(`/api/projects/${project.id}`));
          load();
          onNotify(j.status === "done" ? j.result?.summary || "Done." : j.message || "It did not finish.", j.status === "done" ? "success" : "info");
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
  }, [job?.id]);

  if (!view) return null;
  const off = disabled || project.is_demo || !!job || !!busy;
  const colab = view.colab;
  const send = async (path, file, what) => {
    setBusy(what);
    try {
      const form = new FormData();
      form.append("files", file);
      if (what === "result") form.append("model", model);
      const v = await api(`${base}/colab/${path}`, "POST", form);
      accept(v);
      if (what === "sample") onNotify(`Voice sample saved: ${v.colab.sample.seconds} seconds.`);
      if (what === "result") {
        onProject(await api(`/api/projects/${project.id}`));
        if (v.job_id) {
          setJob({ id: v.job_id, kind: "timing" });
          onNotify("The Colab MP3 is now the narration. Making the timing…");
        } else onNotify("The Colab MP3 is now the narration. " + (v.timing_note || ""), "info");
      }
    } catch (e) {
      onError(e);
    } finally {
      setBusy("");
    }
  };
  const makePack = async () => {
    setBusy("pack");
    try {
      const v = await api(`${base}/colab/pack`, "POST", { source, text });
      accept(v);
      window.location.href = v.colab.pack.url;
      onNotify(`Voice pack ready: ${v.colab.pack.words} words in ${v.colab.pack.parts} parts. Now run the notebook on Colab.`);
    } catch (e) {
      onError(e);
    } finally {
      setBusy("");
    }
  };
  const patch = (body) => api(base, "PATCH", body).then(accept).catch(onError);
  const start = (path, body, kind) =>
    api(`${base}/${path}`, "POST", body)
      .then((r) => setJob({ id: r.job_id, kind }))
      .catch(onError);
  const words = source === "text" ? text.trim().split(/\s+/).filter(Boolean).length : view.sources[source]?.words || 0;
  const made = view.made_timing;

  return (
    <section className="vt" aria-label="Narration voice and timing">
      <div className="vt-card">
        <h3>
          <Mic size={16} /> 1 · The voice
        </h3>
        <p className="vt-now">
          {view.narration ? (
            <>
              <CheckCircle2 size={13} /> Narration in this project: <b>{view.narration.name}</b> · {clock(view.narration.duration)}
              {view.narration.generated ? " · cloned voice" : " · your upload"}{" "}
              <a className="btn" href={view.narration.url} download>
                <Download size={12} /> Download the audio
              </a>
            </>
          ) : (
            <>
              <Info size={13} /> No narration audio yet. Choose one of the ways below.
            </>
          )}
        </p>
        <div className="vt-choices">
          <div className="vt-choice">
            <h4>Use my own recording</h4>
            <p>Record it yourself, then upload the MP3 or WAV with “Choose recording” above.</p>
          </div>
          <div className="vt-choice vt-colab">
            <h4>
              My cloned voice on free Google Colab <span className="vt-tag">recommended</span>
            </h4>
            <p>
              Google’s free GPU reads the narration in your voice. Casefile packs everything into one file; on Colab you
              press ▶ twice. About 20 minutes for a 20-minute script.
            </p>
            <ol className="vt-steps">
              <li>
                <span>Your voice sample, 10 to 20 seconds of only you speaking:</span>{" "}
                {colab.sample ? (
                  <>
                    <CheckCircle2 size={12} /> {colab.sample.name} · {colab.sample.seconds} s{" "}
                    <audio controls preload="none" src={colab.sample.url} />
                  </>
                ) : null}
                <button className="btn" disabled={off} onClick={() => sampleRef.current?.click()}>
                  <Upload size={12} /> {busy === "sample" ? "Saving…" : colab.sample ? "Change it" : "Choose my voice clip"}
                </button>
                <input ref={sampleRef} type="file" accept="audio/*,.mp3,.m4a,.wav" hidden
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) send("sample", f, "sample"); }} />
                {colab.sample && colab.sample.seconds < 8 && <span className="vt-hint"> Short: 10 to 20 seconds copies the voice better.</span>}
              </li>
              <li>
                <span>Read this:</span>{" "}
                <select aria-label="What Colab reads" value={source} disabled={off} onChange={(e) => setSource(e.target.value)}>
                  {["locked", "script", "text"].map((k) => (
                    <option key={k} value={k} disabled={k !== "text" && !view.sources[k]}>
                      {SOURCE_LABEL[k]}
                      {k !== "text" ? (view.sources[k] ? ` (${view.sources[k].words} words)` : " (none yet)") : ""}
                    </option>
                  ))}
                </select>
                {source === "text" && (
                  <textarea aria-label="Narration for Colab" placeholder="Paste the narration here. Headings, [VISUAL] lines and re-cut notes are left out." value={text} disabled={off} onChange={(e) => setText(e.target.value)} />
                )}
                <div className="vt-row">
                  <label>
                    <span>Pace</span>
                    <select aria-label="Pace" value={String(colab.settings.pace)} disabled={off} onChange={(e) => patch({ pace: Number(e.target.value) })}>
                      <option value="0.3">Slower</option>
                      <option value="0.4">A little slower</option>
                      <option value="0.5">Normal</option>
                    </select>
                  </label>
                  <label>
                    <span>Feeling</span>
                    <select aria-label="Feeling" value={String(colab.settings.emotion)} disabled={off} onChange={(e) => patch({ emotion: Number(e.target.value) })}>
                      <option value="0.4">Calm</option>
                      <option value="0.5">Normal</option>
                      <option value="0.6">More feeling</option>
                    </select>
                  </label>
                </div>
              </li>
              <li>
                <button className="btn primary" aria-label="Download the voice pack" disabled={off || !colab.sample || !words} onClick={makePack}>
                  <Download size={12} /> {busy === "pack" ? "Packing…" : `Download the voice pack${words ? ` (${words} words)` : ""}`}
                </button>
                {colab.pack && (
                  <span className="vt-hint">
                    {" "}Last pack: {colab.pack.words} words, {colab.pack.parts} parts, about {colab.pack.minutes} min of speech.
                  </span>
                )}
              </li>
              <li>
                <span>
                  On Colab: open the Casefile notebook (first time:{" "}
                  <a href={colab.notebook_url} download>download it</a>, then in Colab <b>File → Upload notebook</b>). Set{" "}
                  <b>Runtime → Change runtime type → T4 GPU</b>. Press ▶ on <b>Step 1</b>, wait for the restart, press ▶ on{" "}
                  <b>Step 2</b> and choose the voice pack. The MP3 downloads when it is done.
                </span>{" "}
                <a className="btn" href="https://colab.research.google.com/" target="_blank" rel="noreferrer">
                  <ExternalLink size={12} /> Open Google Colab
                </a>
              </li>
              <li>
                <button className="btn primary" aria-label="Add the MP3 from Colab" disabled={off} onClick={() => resultRef.current?.click()}>
                  <Upload size={12} /> {busy === "result" ? "Adding…" : "Add the MP3 from Colab"}
                </button>
                <input ref={resultRef} type="file" accept="audio/mpeg,.mp3,.wav,.m4a" hidden
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) send("result", f, "result"); }} />
                <span className="vt-hint"> It becomes the narration, and the timing is made straight away.</span>
              </li>
            </ol>
          </div>
          <div className="vt-choice">
            <h4>VoiceStudio on this Mac</h4>
            <p>
              If you have VoiceStudio running, it reads the narration in a voice you cloned there. Nothing leaves your
              machine.
            </p>
            <p className={"vt-status " + (view.server.ready ? "ok" : "bad")}>
              {view.server.ready ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />} {view.server.detail}
            </p>
            <label>
              <span>Read this</span>
              <select aria-label="What to read" value={source} disabled={off} onChange={(e) => setSource(e.target.value)}>
                {["locked", "script", "text"].map((k) => (
                  <option key={k} value={k} disabled={k !== "text" && !view.sources[k]}>
                    {SOURCE_LABEL[k]}
                    {k !== "text" ? (view.sources[k] ? ` (${view.sources[k].words} words)` : " (none yet)") : ""}
                  </option>
                ))}
              </select>
            </label>
            {source === "text" && (
              <textarea
                aria-label="Narration to read"
                placeholder="Paste the narration here."
                value={text}
                disabled={off}
                onChange={(e) => setText(e.target.value)}
              />
            )}
            <label>
              <span>In this voice</span>
              <select
                aria-label="Voice"
                value={view.settings.voice}
                disabled={off || !view.server.ready}
                onChange={(e) => patch({ voice: e.target.value })}
              >
                <option value="">{view.voices.length ? "choose a voice" : "no voices found"}</option>
                {view.voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
                {view.settings.voice && !view.voices.some((v) => v.id === view.settings.voice) && (
                  <option value={view.settings.voice}>{view.settings.voice}</option>
                )}
              </select>
            </label>
            <div className="vt-row">
              <button
                className="btn primary"
                aria-label="Generate the narration"
                disabled={off || !view.server.ready || !view.settings.voice || !words}
                onClick={() => start("generate", { source, text }, "voice")}
              >
                <Mic size={13} /> {job?.kind === "voice" ? "Generating…" : `Generate the narration${words ? ` (${words} words)` : ""}`}
              </button>
              <button className="btn" onClick={() => setSettings(!settings)}>
                <Settings2 size={13} /> Voice server settings
              </button>
            </div>
            {settings && (
              <div className="vt-settings">
                <label>
                  <span>Server address</span>
                  <input aria-label="Voice server address" value={form.base} onChange={(e) => setForm({ ...form, base: e.target.value })} />
                </label>
                <label>
                  <span>API key{view.settings.key_saved ? " (saved)" : ""}</span>
                  <input
                    type="password"
                    aria-label="Voice server API key"
                    autoComplete="off"
                    placeholder={view.settings.key_saved ? "••••••" : "the key you gave VoiceStudio"}
                    value={form.key}
                    onChange={(e) => setForm({ ...form, key: e.target.value })}
                  />
                </label>
                <label>
                  <span>Engine</span>
                  <input aria-label="Voice engine" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
                </label>
                <button
                  className="btn"
                  onClick={() => patch({ base: form.base, model: form.model, ...(form.key ? { key: form.key } : {}) }).then(() => onNotify("Voice server settings saved."))}
                >
                  Save and test
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="vt-card">
        <h3>
          <Clock3 size={16} /> 2 · The timing
        </h3>
        <p className="vt-now">
          {view.has_timing ? (
            <>
              <CheckCircle2 size={13} /> Timing is loaded in this project.
            </>
          ) : (
            <>
              <Info size={13} /> No timing yet. Choose one of the two ways below.
            </>
          )}
        </p>
        <div className="vt-choices">
          <div className="vt-choice">
            <h4>Use the SRT and JSON from CapCut</h4>
            <p>
              Put the audio in CapCut, export both files, and upload them with “Choose SRT / word-timing JSON” above.
            </p>
          </div>
          <div className="vt-choice">
            <h4>Make the timing from the audio</h4>
            <p>
              Whisper on this computer listens to the narration for when each word is said. The spelling of every word,
              name and figure is taken from your script, not from what it heard.
            </p>
            {!view.whisper.ready && (
              <p className="vt-status bad">
                <AlertTriangle size={12} /> Whisper cannot load in this container
                {view.whisper.error ? `: ${view.whisper.error}` : "."} Rebuild the Docker image (see Troubleshooting in VOICE-AND-TIMING.md).
              </p>
            )}
            <label>
              <span>Listening quality</span>
              <select aria-label="Listening quality" value={model} disabled={off} onChange={(e) => setModel(e.target.value)}>
                <option value="base.en">Faster (good for clear narration)</option>
                <option value="small.en">More careful (slower)</option>
                <option value="medium.en">Most careful (much slower)</option>
              </select>
            </label>
            <div className="vt-row">
              <button
                className="btn primary"
                aria-label="Make the timing"
                disabled={off || !view.whisper.ready || !view.narration}
                onClick={() => start("timing", { model }, "timing")}
              >
                <Clock3 size={13} /> {job?.kind === "timing" ? "Listening…" : "Make the timing"}
              </button>
              {!view.narration && <span className="vt-hint">Add the narration audio first.</span>}
            </div>
            {made && (
              <div className="vt-made">
                <p>
                  <CheckCircle2 size={12} /> Made from <b>{made.narration}</b>: {Math.round(made.match * 100)}% of the
                  script matched, {made.differences} place{made.differences === 1 ? "" : "s"} where the audio and the
                  script differ.{made.applied ? " Loaded into this project." : ""}
                </p>
                <div className="vt-row">
                  {[
                    ["captions.srt", "Captions (SRT)"],
                    ["word_timings.json", "Word timing (JSON)"],
                    ["differences.txt", "Places to check"],
                  ].map(([k, label]) => (
                    <a key={k} className="btn" href={made.files[k]} download>
                      <Download size={12} /> {label}
                    </a>
                  ))}
                </div>
                {made.examples?.length > 0 && (
                  <ul>
                    {made.examples.map((d, i) => (
                      <li key={i}>
                        {clock(d.at)} · script says <b>{d.script}</b>, audio sounded like <i>{d.heard}</i>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

import React, { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Check,
  CheckCircle2,
  AlertTriangle,
  Info,
  Search,
  Upload,
  ExternalLink,
  RefreshCw,
  LockKeyhole,
} from "lucide-react";

// v0.4.20 Case Desk: the script workflow's gates with automatic checks and
// paste-ready messages, plus free YouTube footage search. No AI model is used:
// the producer's own chats do the research and writing.

const LEVEL_ICON = { fail: AlertTriangle, warn: AlertTriangle, info: Info, ok: CheckCircle2 };
const STATUS_WORD = { empty: "not started", submitted: "pasted", approved: "approved", sent_back: "sent back" };
const VERDICT_WORD = { pass: "checks pass", warn: "check the warnings", fail: "problems found" };
const REVIEW_WORD = { approve: "APPROVE", changes: "APPROVE WITH CHANGES", send_back: "SEND BACK", unclear: "not clear (no VERDICT line found)" };
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

function Findings({ list }) {
  if (!list?.length) return null;
  return (
    <ul className="desk-findings">
      {list.map((f, i) => {
        const Icon = LEVEL_ICON[f.level] || Info;
        return (
          <li key={i} className={"is-" + f.level}>
            <Icon size={13} /> <span>{f.detail}</span>
          </li>
        );
      })}
    </ul>
  );
}

export default function CaseDesk({ project, api, locked, onError, onNotify }) {
  const [view, setView] = useState(null);
  const [gate, setGate] = useState(null);
  const [chapter, setChapter] = useState(1);
  const [draft, setDraft] = useState("");
  const [reviewDraft, setReviewDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [queries, setQueries] = useState("");
  const [jobId, setJobId] = useState(null);
  const [show, setShow] = useState("candidate");
  const [caseForm, setCaseForm] = useState(null);
  const fileRef = useRef(null);
  const base = `/api/projects/${project.id}/casedesk`;

  const accept = (v) => {
    setView(v);
    setCaseForm((cur) => cur || { ...v.case });
    setGate((cur) => cur || v.current);
    setQueries((cur) => cur || v.suggested_searches.slice(0, 6).join("\n"));
  };
  useEffect(() => {
    let live = true;
    api(base)
      .then((v) => live && accept(v))
      .catch(onError);
    return () => {
      live = false;
    };
  }, [project.id]);
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const job = (await api(`/api/projects/${project.id}/jobs`)).find((j) => j.id === jobId);
        if (stop) return;
        if (job && !["running", "queued"].includes(job.status)) {
          setJobId(null);
          accept(await api(base));
          onNotify(job.result?.summary || job.message || "Search finished.", job.status === "done" ? "success" : "info");
          (job.result?.errors || []).slice(0, 2).forEach((e) => onNotify(e, "info"));
          return;
        }
      } catch (e) {
        /* keep polling */
      }
      if (!stop) setTimeout(tick, 1200);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [jobId]);

  if (!view) return <div className="desk"><p className="desk-note">Loading the Case Desk…</p></div>;
  const g = view.gates.find((x) => x.id === gate) || view.gates[0];
  const isChapters = g.id === "G6";
  const chapters = g.chapters || [];
  const ch = isChapters ? chapters.find((c) => c.n === chapter) || { n: chapter, findings: [], status: "empty" } : null;
  const current = isChapters ? ch : g;
  const off = locked || busy || project.is_demo;

  async function call(fn, message) {
    setBusy(true);
    try {
      const r = await fn();
      if (r?.gates) accept(r);
      if (message) onNotify(message);
      return r;
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  const body = (extra) => ({ ...(isChapters ? { chapter } : {}), ...extra });
  const submit = (text, filename) =>
    call(() => api(`${base}/gate/${g.id}`, "POST", body({ text, filename })), "Checked.").then((r) => r && setDraft(""));
  const decide = (status) =>
    call(
      () => api(`${base}/gate/${g.id}`, "POST", body({ status })),
      status === "approved" ? "Approved. The next message for your chat is ready to copy." : "Marked as sent back.",
    );
  async function copy(kind, label, where) {
    const r = await call(() => api(`${base}/packet`, "POST", { gate: g.id, kind, chapter: isChapters ? chapter : undefined }));
    if (!r?.text) return;
    try {
      await navigator.clipboard.writeText(r.text);
      onNotify(`${label} copied. Paste it into your ${where || "WRITER"} chat.`);
    } catch (e) {
      setDraft(r.text);
      onNotify(`${label} is in the box below; select it and copy.`, "info");
    }
  }
  async function download(kind, name) {
    const r = await call(() => api(`${base}/packet`, "POST", { kind }));
    if (!r?.text) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([r.text], { type: "text/markdown" }));
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  const shown = view.candidates
    .filter((c) => show === "all" || c.status === show)
    .sort((a, b) => (b.score || 0) - (a.score || 0) || (b.views || 0) - (a.views || 0));
  const count = (s) => view.candidates.filter((c) => c.status === s).length;

  return (
    <div className="desk">
      <header className="desk-head">
        <BookOpen size={20} />
        <div>
          <h2>Case Desk</h2>
          <p>
            Your script gates in one place. You keep two chats open: a <b>WRITER</b> chat that researches and writes, and a{" "}
            <b>REVIEWER</b> chat that checks its work. Every button here says which chat its text goes into. No AI and no
            paid service runs here.
          </p>
        </div>
      </header>

      <section className="desk-case" aria-label="Case details">
        {[
          ["name", "Case (name, place, dates)", "text"],
          ["channel", "Channel", "text"],
          ["target_words", "Target words", "number"],
          ["wpm", "Words a minute", "number"],
        ].map(([key, label, type]) => (
          <label key={key} className={"desk-field desk-field-" + key}>
            <span>{label}</span>
            <input
              type={type}
              aria-label={label}
              value={caseForm?.[key] ?? ""}
              disabled={off}
              onChange={(e) => setCaseForm({ ...caseForm, [key]: e.target.value })}
              onBlur={() =>
                String(caseForm[key]) !== String(view.case[key]) &&
                call(() => api(`${base}/case`, "PATCH", { [key]: caseForm[key] }))
              }
            />
          </label>
        ))}
        <span className="desk-runtime">
          about {clock(Math.round(((Number(caseForm?.target_words) || 0) / (Number(caseForm?.wpm) || 145)) * 60))}
        </span>
      </section>

      <div className="desk-body">
        <nav className="desk-gates" aria-label="Gates">
          {view.gates.map((x, i) => (
            <button
              key={x.id}
              className={`${x.id === g.id ? "selected" : ""} is-${x.status}`}
              onClick={() => {
                setGate(x.id);
                setDraft("");
                setReviewDraft("");
              }}
            >
              <span className="desk-step">{x.status === "approved" ? <Check size={12} /> : i + 1}</span>
              <span>
                <b>{x.name}</b>
                <small>
                  {STATUS_WORD[x.status]}
                  {x.verdict && x.status !== "approved" ? ` · ${VERDICT_WORD[x.verdict]}` : ""}
                </small>
              </span>
            </button>
          ))}
          <button className="btn desk-reviewer" disabled={busy} onClick={() => copy("reviewer_prompt", "Reviewer start prompt", "REVIEWER")}>
            Start a REVIEWER chat (copy its prompt)
          </button>
        </nav>

        <section className="desk-gate" aria-label={g.name}>
          <h3>
            Gate {g.id.slice(1)}: {g.name}
          </h3>
          <p className="desk-note">{g.what}</p>
          {isChapters && (
            <div className="desk-chapters">
              {(chapters.length ? chapters : [{ n: 1, status: "empty" }]).map((c) => (
                <button
                  key={c.n}
                  className={`${c.n === chapter ? "selected" : ""} is-${c.status}`}
                  onClick={() => {
                    setChapter(c.n);
                    setDraft("");
                  }}
                >
                  Chapter {c.n}
                  {c.status === "approved" ? " ✓" : c.verdict === "fail" ? " !" : ""}
                </button>
              ))}
              <button onClick={() => setChapter((chapters[chapters.length - 1]?.n || 0) + 1)}>+ chapter</button>
              {ch.budget ? (
                <span className="desk-note">
                  Budget {ch.budget} words · IDs {ch.ids?.join(", ") || "none"}
                </span>
              ) : (
                <span className="desk-note">Paste the outline at gate 5 to fill in budgets and IDs.</span>
              )}
            </div>
          )}

          <div className="desk-step-box">
            <h4>
              <span className="desk-num">1</span> Ask for it <span className="desk-to writer">paste into your WRITER chat</span>
            </h4>
            <button className="btn" disabled={busy} onClick={() => copy("start", "Prompt", "WRITER")}>
              Copy the prompt
            </button>
          </div>

          <div className="desk-step-box">
            <h4>
              <span className="desk-num">2</span> Bring the writer’s answer here
            </h4>
            <textarea
              aria-label={`Paste ${isChapters ? "chapter " + chapter : g.name}`}
              placeholder={
                current.has_text
                  ? `Pasted${current.filename ? " from " + current.filename : ""}. Paste a new version here to replace it.`
                  : "Paste the whole document your writer chat produced, or load its .md file."
              }
              value={draft}
              disabled={off}
              onChange={(e) => setDraft(e.target.value)}
            />
            <div className="desk-actions">
              <button className="btn primary" disabled={off || !draft.trim()} onClick={() => submit(draft, "")}>
                Check it
              </button>
              <button className="btn" disabled={off} onClick={() => fileRef.current?.click()}>
                <Upload size={13} /> Load a .md file
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".md,.txt,text/markdown,text/plain"
                hidden
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) submit(await f.text(), f.name);
                }}
              />
            </div>
            {current.has_text && (
              <>
                <p className="desk-sub">
                  What the automatic checks found{" "}
                  <span className={"desk-verdict is-" + current.verdict}>{VERDICT_WORD[current.verdict]}</span>
                </p>
                <Findings list={current.findings} />
              </>
            )}
          </div>

          {current.has_text && (
            <>
              <div className="desk-step-box">
                <h4>
                  <span className="desk-num">3</span> Get it reviewed{" "}
                  <span className="desk-to reviewer">paste into your REVIEWER chat</span>
                </h4>
                <div className="desk-actions">
                  <button className="btn" disabled={busy} onClick={() => copy("review", "Reviewer packet", "REVIEWER")}>
                    Copy the packet
                  </button>
                  <span className="desk-note">It holds this document and what was already checked.</span>
                </div>
                <textarea
                  className="desk-review"
                  aria-label="Paste the reviewer's reply"
                  placeholder={
                    current.reviewed
                      ? "The reviewer's reply is saved. Paste a new one here to replace it."
                      : "Then paste the reviewer's whole reply here (it starts with VERDICT)."
                  }
                  value={reviewDraft}
                  disabled={off}
                  onChange={(e) => setReviewDraft(e.target.value)}
                />
                <div className="desk-actions">
                  <button
                    className="btn primary"
                    disabled={off || !reviewDraft.trim()}
                    onClick={() =>
                      call(() => api(`${base}/gate/${g.id}`, "POST", body({ review: reviewDraft })), "Reviewer's reply read.").then(
                        (r) => r && setReviewDraft(""),
                      )
                    }
                  >
                    Read the reply
                  </button>
                </div>
                {current.reviewed && (
                  <div className={"desk-reviewed is-" + current.review.verdict}>
                    <p>
                      Reviewer’s verdict: <b>{REVIEW_WORD[current.review.verdict]}</b>
                    </p>
                    {current.review.your_call && (
                      <>
                        <p className="desk-sub">Your call (only you decide these):</p>
                        <pre>{current.review.your_call}</pre>
                      </>
                    )}
                  </div>
                )}
              </div>

              <div className="desk-step-box">
                <h4>
                  <span className="desk-num">4</span> Decide
                </h4>
                {current.blockers?.length > 0 && current.status !== "approved" && (
                  <ul className="desk-findings">
                    {current.blockers.map((b, i) => (
                      <li key={i} className="is-fail">
                        <AlertTriangle size={13} /> <span>{b}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {!current.reviewed && current.status !== "approved" && (
                  <p className="desk-note">Not reviewed yet. You can still decide, but the reviewer has not seen this version.</p>
                )}
                <div className="desk-actions">
                  <button
                    className="btn primary"
                    disabled={off || current.status === "approved" || current.blockers?.length > 0}
                    onClick={() => decide("approved")}
                  >
                    <Check size={13} /> {current.status === "approved" ? "Approved" : "Approve this gate"}
                  </button>
                  <button className="btn" disabled={off || current.status === "sent_back"} onClick={() => decide("sent_back")}>
                    Send back for corrections
                  </button>
                  {current.blockers?.length > 0 && current.status !== "approved" && (
                    <button
                      className="desk-link"
                      disabled={off}
                      onClick={() => {
                        const why = window.prompt(
                          "This gate has open problems:\n\n- " + current.blockers.join("\n- ") + "\n\nApprove anyway only if you checked them yourself. Say why:",
                        );
                        if (why && why.trim()) call(() => api(`${base}/gate/${g.id}`, "POST", body({ status: "approved", override: why })), "Approved by your decision.");
                      }}
                    >
                      Approve anyway…
                    </button>
                  )}
                </div>
                {current.override && (
                  <p className="desk-note">Approved by your decision over open problems: “{current.override.reason}”.</p>
                )}
              </div>

              <div className="desk-step-box">
                <h4>
                  <span className="desk-num">5</span> Tell the writer{" "}
                  <span className="desk-to writer">paste into your WRITER chat</span>
                </h4>
                <div className="desk-actions">
                  <button className="btn" disabled={busy} onClick={() => copy("reply", "Reply", "WRITER")}>
                    {current.blockers?.length > 0 && current.status !== "approved" ? "Copy the corrections" : "Copy “approved, continue”"}
                  </button>
                  <span className="desk-note">
                    {current.blockers?.length > 0 && current.status !== "approved"
                      ? "The numbered list of what to fix, from the checks and from your reviewer."
                      : "Tells the writer to move to the next phase."}
                  </span>
                </div>
              </div>
            </>
          )}
          {g.id === "G8" && view.gates[7].has_text && (
            <div className="desk-actions">
              <button className="btn" disabled={busy} onClick={() => download("editor_script", "script_for_editor.md")}>
                <LockKeyhole size={13} /> Download the script for the editor
              </button>
              <span className="desk-note">Narration only, under HOOK and CHAPTER headings, ready for Episode setup.</span>
            </div>
          )}
        </section>
      </div>

      <section className="desk-footage" aria-label="Footage search">
        <h3>
          <Search size={15} /> Find real footage on YouTube
        </h3>
        <p className="desk-note">
          This search runs here in the app, not in a chat. A result is only a candidate: open it, check it really is this
          case, then approve it and say what it shows. Nothing is downloaded here. Approved uploads get a Source ID and
          are included automatically in the gate 2 and gate 4 prompts for your WRITER chat.
        </p>
        <div className="desk-search">
          <textarea
            aria-label="Search phrases, one per line"
            value={queries}
            disabled={off || !!jobId}
            onChange={(e) => setQueries(e.target.value)}
            placeholder="One search per line, for example: Jane Doe police press conference"
          />
          <div>
            <button
              className="btn primary"
              disabled={off || !!jobId || !queries.trim() || !view.search_ready}
              onClick={() =>
                call(() =>
                  api(`${base}/search`, "POST", { queries: queries.split("\n").map((q) => q.trim()).filter(Boolean) }),
                ).then((r) => r?.job_id && setJobId(r.job_id))
              }
            >
              <Search size={13} /> {jobId ? "Searching…" : "Search YouTube"}
            </button>
            <button className="btn" disabled={!!jobId} onClick={() => setQueries(view.suggested_searches.join("\n"))}>
              <RefreshCw size={13} /> Suggest searches
            </button>
            <button className="btn" disabled={busy || !view.approved_sources} onClick={() => copy("sources", "Approved sources", "WRITER")}>
              Copy approved sources ({view.approved_sources}) for your WRITER chat
            </button>
            {!view.search_ready && <p className="desk-note">yt-dlp is missing. Rebuild the Docker image.</p>}
          </div>
        </div>
        <div className="desk-tabs">
          {[
            ["candidate", "To check"],
            ["approved", "Approved"],
            ["rejected", "Rejected"],
            ["all", "All"],
          ].map(([k, label]) => (
            <button key={k} className={show === k ? "selected" : ""} onClick={() => setShow(k)}>
              {label} ({k === "all" ? view.candidates.length : count(k)})
            </button>
          ))}
        </div>
        <div className="desk-cands">
          {shown.length === 0 && <p className="desk-note">Nothing here yet.</p>}
          {shown.slice(0, 120).map((c) => (
            <div key={c.id} className={"desk-cand is-" + c.status}>
              <a href={`https://www.youtube.com/watch?v=${c.id}`} target="_blank" rel="noreferrer" aria-label={"Open " + c.title}>
                <img src={`https://i.ytimg.com/vi/${c.id}/mqdefault.jpg`} alt="" loading="lazy" />
              </a>
              <div>
                <b>
                  {c.source_id ? <code>{c.source_id}</code> : null} {c.title}
                </b>
                <small>
                  {c.channel || "channel not read"} · {clock(c.duration || 0)} · {(c.views || 0).toLocaleString()} views
                  {c.upload_date ? ` · uploaded ${c.upload_date.slice(0, 4)}-${c.upload_date.slice(4, 6)}-${c.upload_date.slice(6)}` : ""}
                  {c.score ? "" : " · title does not name the case"}
                </small>
                <div className="desk-actions">
                  <select
                    aria-label={"What " + c.title + " shows"}
                    value={c.kind || ""}
                    disabled={off}
                    onChange={(e) => call(() => api(`${base}/candidate/${c.id}`, "PATCH", { kind: e.target.value }))}
                  >
                    {view.kinds.map((k) => (
                      <option key={k} value={k}>
                        {k || "what does it show?"}
                      </option>
                    ))}
                  </select>
                  <button
                    className="btn"
                    disabled={off || c.status === "approved"}
                    onClick={() => call(() => api(`${base}/candidate/${c.id}`, "PATCH", { status: "approved", inspect: true }))}
                  >
                    <Check size={12} /> Approve
                  </button>
                  <button
                    className="btn"
                    disabled={off || c.status === "rejected"}
                    onClick={() => call(() => api(`${base}/candidate/${c.id}`, "PATCH", { status: "rejected" }))}
                  >
                    Reject
                  </button>
                  <a className="desk-open" href={`https://www.youtube.com/watch?v=${c.id}`} target="_blank" rel="noreferrer">
                    Open <ExternalLink size={11} />
                  </a>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

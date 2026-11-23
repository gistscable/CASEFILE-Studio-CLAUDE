import React, { useEffect, useRef, useState } from "react";
import {
  Download,
  RefreshCw,
  Info,
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
} from "lucide-react";
import DownloadRows, { useFetchJob } from "./DownloadRows.jsx";

// v0.4.19 "Fetch from guide": downloads the guide's YouTube sources and base
// clips/frames, saves them under the guide's exact names and adds them to
// Footage & photos. Rights, reuse basis and audio clearance stay manual.

const KIND = {
  source: "footage",
  "base-clip": "base clip",
  "base-frame": "base frame",
};
const STATUS = {
  todo: "to fetch",
  have: "already here",
  manual: "get by hand",
  unused: "not used by a card",
};

export default function FetchPanel({
  project,
  api,
  disabled,
  onProject,
  onError,
  onNotify,
}) {
  const e = project.episode || {};
  const [plan, setPlan] = useState(null);
  const [backend, setBackend] = useState("yt-dlp");
  const [token, setToken] = useState("");
  const [actor, setActor] = useState("");
  const [height, setHeight] = useState("1080");
  const [agree, setAgree] = useState(false);
  const [result, setResult] = useState(null);
  const [starting, setStarting] = useState(false);
  const live = useRef(true);
  const key = [project.id, project.assets.length, e.guide?.hash || ""].join("|");

  const load = () =>
    api(`/api/projects/${project.id}/fetch`)
      .then((r) => {
        if (!live.current) return;
        setPlan(r);
        if (!actor && r.apify_actor) setActor(r.apify_actor);
      })
      .catch(() => live.current && setPlan(null));

  useEffect(() => {
    live.current = true;
    if (e.guide) load();
    return () => {
      live.current = false;
    };
  }, [key]);

  // Follow the fetch job file by file; when it ends, refresh the project.
  const fetchJob = useFetchJob(api, project.id, async (job) => {
    setResult(job.status === "done" ? job.result : { summary: job.message, results: [], failed: 1 });
    try {
      onProject(await api(`/api/projects/${project.id}`));
    } catch (err) {
      /* the next refresh shows it */
    }
    load();
    onNotify(
      job.status === "done" ? job.result?.summary || "Fetch finished." : job.message || "The download stopped.",
      job.status === "done" && !job.result?.failed ? "success" : "info",
    );
  });
  const jobId = fetchJob.running ? fetchJob.job?.id || "starting" : null;

  if (!e.guide) return null;
  const items = plan?.items || [];
  const counts = plan?.counts || {};
  const todo = counts.todo || 0;
  const status = plan?.backends?.[backend];
  const acknowledged = plan?.acknowledged || agree;
  const needsToken =
    backend === "apify" && !plan?.apify_token_saved && !token.trim();
  const canFetch =
    !disabled &&
    !project.is_demo &&
    !jobId &&
    !starting &&
    todo > 0 &&
    acknowledged &&
    (backend === "apify" ? !needsToken : status?.ready);

  async function start(only) {
    setStarting(true);
    setResult(null);
    try {
      const r = await api(`/api/projects/${project.id}/fetch`, "POST", {
        ...(only ? { only } : {}),
        backend,
        confirm_responsibility: acknowledged,
        max_height: Number(height),
        ...(backend === "apify"
          ? { apify_token: token.trim() || undefined, apify_actor: actor.trim() }
          : {}),
      });
      setToken("");
      fetchJob.follow(r.job_id);
      onNotify(
        only
          ? `Retrying ${only.length === 1 ? only[0] : only.length + " files"}.`
          : `Fetching ${todo} file${todo === 1 ? "" : "s"}. Each file shows its own progress below.`,
        "info",
      );
    } catch (err) {
      onError(err);
    } finally {
      setStarting(false);
    }
  }

  const failed = (result?.results || []).filter((r) => !r.ok);
  return (
    <section className="ep-base ep-fetch" aria-label="Fetch from guide">
      <div className="ep-base-head">
        <Download size={18} />
        <h3>Fetch from guide</h3>
        <span>
          Downloads the guide's YouTube sources and base clips, names them, and
          adds them here
        </span>
      </div>
      <div className="ep-base-counts ep-fetch-counts">
        {["todo", "have", "manual", "unused"].map((s) => (
          <div key={s}>
            <b>{counts[s] || 0}</b>
            <span>{STATUS[s]}</span>
          </div>
        ))}
      </div>
      <div className="ep-base-controls">
        <label className="ep-base-hold">
          <span>Downloader</span>
          <select
            aria-label="Downloader"
            value={backend}
            disabled={disabled || !!jobId}
            onChange={(ev) => setBackend(ev.target.value)}
          >
            <option value="yt-dlp">yt-dlp (built in, free)</option>
            <option value="apify">Apify actor (needs a token)</option>
          </select>
        </label>
        {backend === "yt-dlp" && (
          <label className="ep-base-hold">
            <span>Highest quality</span>
            <select
              aria-label="Highest download quality"
              value={height}
              disabled={disabled || !!jobId}
              onChange={(ev) => setHeight(ev.target.value)}
            >
              {["720", "1080", "1440"].map((h) => (
                <option key={h} value={h}>
                  {h}p
                </option>
              ))}
            </select>
          </label>
        )}
        {backend === "apify" && (
          <>
            <label className="ep-base-hold">
              <span>
                Apify API token
                {plan?.apify_token_saved ? " (saved for this session)" : ""}
              </span>
              <input
                type="password"
                aria-label="Apify API token"
                autoComplete="off"
                placeholder={plan?.apify_token_saved ? "••••••••" : "apify_api_…"}
                value={token}
                disabled={disabled || !!jobId}
                onChange={(ev) => setToken(ev.target.value)}
              />
            </label>
            <label className="ep-base-hold">
              <span>Actor</span>
              <input
                aria-label="Apify actor"
                value={actor}
                disabled={disabled || !!jobId}
                onChange={(ev) => setActor(ev.target.value)}
              />
            </label>
          </>
        )}
        <button
          className="btn primary"
          aria-label="Fetch from guide"
          disabled={!canFetch}
          onClick={() => start()}
        >
          <Download size={14} />{" "}
          {jobId
            ? "Fetching…"
            : todo
              ? `Fetch ${todo} file${todo === 1 ? "" : "s"}`
              : "Nothing to fetch"}
        </button>
        <button
          className="btn"
          aria-label="Refresh fetch list"
          disabled={!!jobId}
          onClick={load}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
      {status && (
        <p className="ep-small">
          {status.ready ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}{" "}
          {status.detail}
        </p>
      )}
      {!plan?.acknowledged && (
        <label className="ep-checkbox ep-fetch-notice">
          <input
            type="checkbox"
            aria-label="I accept the download notice"
            checked={agree}
            disabled={disabled}
            onChange={(ev) => setAgree(ev.target.checked)}
          />{" "}
          <span>
            <b>I understand and take responsibility</b>
            <small>{plan?.notice}</small>
          </span>
        </label>
      )}
      <p className="ep-small">
        <Info size={12} /> Footage is downloaded from 0:00 to just past the last
        window the guide uses, so the guide's times still match the file. Base
        clips are cut to their window; base frames are captured at their
        timestamp. Reuse basis and rights stay yours to record.
      </p>
      {result && (
        <div className="ep-fetch-result">
          <p className="ep-small">
            {failed.length ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}{" "}
            {result.summary}
          </p>
        </div>
      )}
      <DownloadRows
        job={fetchJob.job}
        running={fetchJob.running}
        disabled={disabled || starting || !acknowledged || (backend === "apify" ? needsToken : !status?.ready)}
        onRetry={(ids) => start(ids)}
        onStop={() => fetchJob.job && api(`/api/jobs/${fetchJob.job.id}/cancel`, "POST").catch(onError)}
      />
      {items.length > 0 && (
        <details className="ep-fetch-list">
          <summary>Every file the guide names ({items.length})</summary>
          <table>
            <thead>
              <tr>
                <th>Save as</th>
                <th>Type</th>
                <th>Status</th>
                <th>What happens</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.kind + i.id} className={"is-" + i.status}>
                  <td>
                    <code>{i.save_as}</code>
                    {i.url && (
                      <a
                        href={i.url}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={"Open link for " + i.save_as}
                      >
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </td>
                  <td>{KIND[i.kind]}</td>
                  <td>{STATUS[i.status]}</td>
                  <td>{i.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}

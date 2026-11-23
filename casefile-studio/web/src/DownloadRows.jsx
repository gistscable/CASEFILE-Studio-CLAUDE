import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, AlertTriangle, RefreshCw, X, LoaderCircle } from "lucide-react";

// v0.4.27 One row per file while fetching: its own bar, percentage, speed and
// size, a "stalled" warning when nothing moves, and Retry for that file only.

export const STALL_SECONDS = 30;

const mb = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : `${(n / 1e6).toFixed(n >= 1e8 ? 0 : 1)} MB`);

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function describe(f) {
  // Bytes when yt-dlp gives a total; otherwise (cut sections through ffmpeg)
  // how far into the needed part of the video it is (v0.4.34).
  const pct = f.total
    ? Math.min(100, Math.round((100 * (f.done || 0)) / f.total))
    : f.secs_total
      ? Math.min(100, Math.round((100 * (f.secs || 0)) / f.secs_total))
      : null;
  const stalled = f.status === "downloading" && (f.idle || 0) >= STALL_SECONDS;
  let text = "";
  if (f.status === "waiting") text = "Waiting";
  else if (f.status === "downloading") {
    const bits = [];
    if (f.phase && !f.done) bits.push(f.phase.charAt(0).toUpperCase() + f.phase.slice(1));
    else if (f.phase) bits.push(f.phase);
    if (pct !== null) bits.push(`${pct}%`);
    if (f.speed) bits.push(`${mb(f.speed)}/s`);
    if (!f.total && f.secs_total) bits.push(`${clock(f.secs || 0)} of ${clock(f.secs_total)} of video`);
    if (f.done) bits.push(f.total ? `${mb(f.done)} of ${mb(f.total)}` : `${mb(f.done)} so far`);
    if (f.part) bits.push(f.part);
    if (f.attempt > 1) bits.push(`try ${f.attempt} of ${f.attempts}`);
    text = bits.join(" · ") || "Starting";
  } else if (f.status === "saving") text = "Saving into the project";
  else if (f.status === "done") text = "Done";
  else if (f.status === "failed") text = f.error || "Failed";
  else if (f.status === "stopped") text = "Stopped before it finished";
  return { pct, stalled, text };
}

// Follows the project's latest fetch job: on opening the page it shows the
// last one (or follows it if it is still running).
export function useFetchJob(api, projectId, onFinished, kind = "fetch") {
  const [job, setJob] = useState(null);
  const [follow, setFollow] = useState(null);
  const done = useRef(onFinished);
  done.current = onFinished;
  useEffect(() => {
    let stop = false;
    api(`/api/projects/${projectId}/jobs`)
      .then((jobs) => {
        if (stop) return;
        const last = jobs.find((j) => j.kind === kind);
        if (!last) return;
        setJob(last);
        if (["running", "queued"].includes(last.status)) setFollow(last.id);
      })
      .catch(() => {});
    return () => {
      stop = true;
    };
  }, [projectId]);
  useEffect(() => {
    if (!follow) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = (await api(`/api/projects/${projectId}/jobs`)).find((x) => x.id === follow);
        if (stop) return;
        if (j) {
          setJob(j);
          if (!["running", "queued"].includes(j.status)) {
            setFollow(null);
            done.current && done.current(j);
            return;
          }
        }
      } catch (e) {
        /* keep polling */
      }
      if (!stop) setTimeout(tick, 1000);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [follow]);
  return { job, running: !!follow, follow: setFollow };
}

export default function DownloadRows({ job, running, onRetry, onStop, disabled }) {
  const files = job?.files ? Object.entries(job.files) : [];
  if (!files.length) return null;
  const failed = files.filter(([, f]) => ["failed", "stopped"].includes(f.status));
  const doneCount = files.filter(([, f]) => f.status === "done").length;
  const anyStalled = files.some(([, f]) => describe(f).stalled);
  return (
    <div className="dl" aria-label="Downloads">
      <div className="dl-head">
        <b>
          {running ? "Downloading" : "Last download"} · {doneCount} of {files.length} done
          {failed.length ? ` · ${failed.length} need${failed.length === 1 ? "s" : ""} a retry` : ""}
        </b>
        {running && onStop && (
          <button className="btn" aria-label="Stop the downloads" onClick={onStop}>
            <X size={12} /> Stop
          </button>
        )}
        {!running && failed.length > 1 && onRetry && (
          <button className="btn" aria-label="Retry all that failed" disabled={disabled} onClick={() => onRetry(failed.map(([id]) => id))}>
            <RefreshCw size={12} /> Retry all {failed.length}
          </button>
        )}
      </div>
      {anyStalled && (
        <p className="dl-stall-note">
          <AlertTriangle size={12} /> A download has not moved for {STALL_SECONDS}+ seconds. Give it a minute (YouTube sometimes pauses), or press Stop and retry that file.
        </p>
      )}
      {files.map(([id, f]) => {
        const d = describe(f);
        const cls = d.stalled ? "stalled" : f.status;
        return (
          <div key={id} className={`dl-row is-${cls}`} aria-label={`Download ${f.save_as}`}>
            <span className="dl-icon">
              {f.status === "done" ? (
                <CheckCircle2 size={14} />
              ) : f.status === "failed" || f.status === "stopped" || d.stalled ? (
                <AlertTriangle size={14} />
              ) : f.status === "waiting" ? (
                <span className="dl-dot" />
              ) : (
                <LoaderCircle size={14} className="spin" />
              )}
            </span>
            <code className="dl-name">{f.save_as}</code>
            <div className="dl-bar-wrap">
              <div
                className={`dl-bar ${f.status === "downloading" && d.pct === null ? "indeterminate" : ""}`}
                role="progressbar"
                aria-label={`${f.save_as} progress`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={f.status === "done" ? 100 : d.pct ?? undefined}
              >
                <i style={{ width: `${f.status === "done" || f.status === "saving" ? 100 : d.pct ?? (f.status === "downloading" ? 35 : 0)}%` }} />
              </div>
              <small className="dl-text">{d.stalled ? `No progress for ${Math.round(f.idle)} s · ${d.text}` : d.text}</small>
            </div>
            {!running && ["failed", "stopped"].includes(f.status) && onRetry && (
              <button className="btn dl-retry" aria-label={`Retry ${f.save_as}`} disabled={disabled} onClick={() => onRetry([id])}>
                <RefreshCw size={12} /> Retry
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

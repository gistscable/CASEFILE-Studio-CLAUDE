import React, { useEffect, useMemo, useState } from "react";
import { Plus, Search, Trash2, Scissors, Mic, BookOpen, Film, ArrowUpRight, Clapperboard } from "lucide-react";

// v0.4.33 The start page: create a project, carry on where you left off,
// jump to a tool, or pick any project from the grid.

export function HomeIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V20h5v-6h4v6h5V9.5" />
    </svg>
  );
}

const mb = (b) => {
  const m = b / 1048576;
  return m >= 1024 ? `${(m / 1024).toFixed(1)} GB` : m >= 10 ? `${Math.round(m)} MB` : `${m.toFixed(1)} MB`;
};
const clock = (s) => {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h ? h + ":" + String(m).padStart(2, "0") : m}:${String(s % 60).padStart(2, "0")}`;
};
const ago = (iso) => {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(d)) return "";
  if (d < 90) return "just now";
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  if (d < 86400 * 14) return `${Math.round(d / 86400)} days ago`;
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
};

export default function Home({ api, current, onCreate, onOpen, onDelete, onTool, version }) {
  const [list, setList] = useState(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("recent");
  const load = () => api("/api/home").then((r) => setList(r.projects)).catch(() => setList([]));
  useEffect(() => {
    load();
  }, []);
  const shown = useMemo(() => {
    const items = (list || []).filter((p) => !q || `${p.title} ${p.topic || ""}`.toLowerCase().includes(q.toLowerCase()));
    if (sort === "name") items.sort((a, b) => a.title.localeCompare(b.title));
    else if (sort === "size") items.sort((a, b) => b.size - a.size);
    return items;
  }, [list, q, sort]);
  const last = (list || []).find((p) => p.id === current?.id) || (list || []).find((p) => !p.is_demo);
  const total = (list || []).reduce((a, p) => a + p.size, 0);
  return (
    <div className="home" role="main" aria-label="Home">
      <div className="home-inner">
        <button className="home-create" aria-label="Create project" onClick={onCreate}>
          <span className="home-create-icon">
            <Plus size={26} />
          </span>
          <span>
            <b>Create project</b>
            <small>A new documentary from your script and editing guide</small>
          </span>
        </button>

        <div className="home-tools">
          {last && (
            <button className="home-tool home-continue" onClick={() => onOpen(last.id)}>
              <span className="home-continue-thumb" style={{ backgroundImage: last.thumbnail ? `url("${last.thumbnail}")` : undefined }} />
              <span>
                <em>Carry on where you left off</em>
                <b>{last.title}</b>
                <small>
                  {clock(last.duration)} · {last.scenes} scenes · {ago(last.updated_at)}
                </small>
              </span>
              <ArrowUpRight size={16} />
            </button>
          )}
          <button className="home-tool" onClick={() => onTool("desk")} disabled={!last}>
            <BookOpen size={20} />
            <b>Case desk</b>
            <small>Write and check the script, gate by gate</small>
          </button>
          <button className="home-tool" onClick={() => onTool("setup")} disabled={!last}>
            <Mic size={20} />
            <b>Voice and timing</b>
            <small>Your cloned voice on free Colab, then Whisper timing</small>
          </button>
          <button className="home-tool" onClick={() => onTool("recut")} disabled={!last}>
            <Scissors size={20} />
            <b>Re-cut</b>
            <small>Put the real voices into a finished video</small>
          </button>
        </div>

        <div className="home-head">
          <h2>Projects</h2>
          {list && (
            <span className="home-count">
              {list.length} project{list.length === 1 ? "" : "s"} · {mb(total)} on this computer
            </span>
          )}
          <label className="home-search">
            <Search size={14} />
            <input aria-label="Search projects" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <select aria-label="Sort projects" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="recent">Recent</option>
            <option value="name">Name</option>
            <option value="size">Size</option>
          </select>
        </div>
        {list === null ? (
          <p className="home-empty">Loading your projects…</p>
        ) : shown.length === 0 ? (
          <p className="home-empty">{q ? "No project matches." : "No projects yet. Create one above."}</p>
        ) : (
          <div className="home-grid">
            {shown.map((p) => (
              <div key={p.id} className={`home-card ${p.id === current?.id ? "current" : ""}`}>
                <button className="home-card-open" aria-label={`Open ${p.title}`} onClick={() => onOpen(p.id)}>
                  <span className={`home-thumb ${p.aspect === "9:16" ? "tall" : ""}`} style={{ backgroundImage: p.thumbnail ? `url("${p.thumbnail}")` : undefined }}>
                    {!p.thumbnail && <Clapperboard size={24} />}
                    {p.aspect === "9:16" && <i className="home-badge">9:16</i>}
                    {p.is_demo && <i className="home-badge demo">Demo</i>}
                  </span>
                  <b title={p.title}>{p.title}</b>
                  <small>
                    {mb(p.size)} | {clock(p.duration)}
                    {p.exports ? ` · ${p.exports} export${p.exports === 1 ? "" : "s"}` : ""}
                    {p.recuts ? ` · ${p.recuts} re-cut${p.recuts === 1 ? "" : "s"}` : ""}
                  </small>
                  <small className="home-when">{ago(p.updated_at)}</small>
                </button>
                {!p.is_demo && (
                  <button
                    className="home-card-delete"
                    aria-label={`Delete ${p.title}`}
                    title="Delete this project and all its files"
                    onClick={async () => {
                      if (await onDelete(p)) load();
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="home-foot">
          <Film size={12} /> Casefile Studio v{version} · everything stays on this computer, in Docker’s casefile-data volume.
        </p>
      </div>
    </div>
  );
}

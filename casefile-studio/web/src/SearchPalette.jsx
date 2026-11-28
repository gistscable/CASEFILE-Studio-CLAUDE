// v0.4.68 Search: type what you are looking for (a tool, a setting, a scene, a word in the
// narration, a file) and go straight to it. Opens from the top bar or Ctrl/⌘+K.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Search, CornerDownLeft, Sparkles, X } from "lucide-react";
import { search, POPULAR, GROUP_ORDER } from "./searchIndex.js";

export default function SearchPalette({ items, onPick, onClose, onAskDirector }) {
  const [q, setQ] = useState("");
  const [at, setAt] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const results = useMemo(() => {
    if (q.trim()) return search(items, q);
    return POPULAR.map((label) => items.find((i) => i.label === label)).filter(Boolean).map((i) => ({ ...i, group: "Popular" }));
  }, [items, q]);
  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => setAt(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${at}"]`)?.scrollIntoView({ block: "nearest" });
  }, [at]);
  const pick = (r) => r && onPick(r);
  const onKey = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setAt((i) => Math.min(results.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setAt((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (results[at]) pick(results[at]);
      else if (q.trim()) onAskDirector(q.trim());
    }
  };
  const groups = q.trim() ? GROUP_ORDER : ["Popular"];
  let n = -1;
  return (
    <div className="search-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="search-box" role="dialog" aria-label="Search" onKeyDown={onKey}>
        <label className="search-input">
          <Search size={17} />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search tools, settings, scenes, words, files…"
            aria-label="Search everything"
            role="combobox"
            aria-expanded="true"
            aria-controls="search-results"
            aria-activedescendant={results[at] ? `search-r-${at}` : undefined}
          />
          <button type="button" className="search-close" aria-label="Close search" onClick={onClose}>
            <X size={15} />
          </button>
        </label>
        <div className="search-results" id="search-results" role="listbox" ref={listRef}>
          {groups.map((g) => {
            const rows = results.filter((r) => r.group === g);
            if (!rows.length) return null;
            return (
              <div key={g} className="search-group">
                <div className="search-group-name">{g === "Popular" ? "People often look for" : g}</div>
                {rows.map((r) => {
                  n += 1;
                  const i = n;
                  return (
                    <button
                      type="button"
                      key={g + i + r.label}
                      id={`search-r-${i}`}
                      data-i={i}
                      role="option"
                      aria-selected={i === at}
                      className={`search-row ${i === at ? "on" : ""}`}
                      onMouseMove={() => at !== i && setAt(i)}
                      onClick={() => pick(r)}
                    >
                      <span className="search-label">
                        {r.label}
                        {r.snippet && <small>“{r.snippet}”</small>}
                      </span>
                      <span className="search-where">{r.where}</span>
                      {i === at && <CornerDownLeft size={13} className="search-enter" />}
                    </button>
                  );
                })}
              </div>
            );
          })}
          {q.trim() && !results.length && (
            <div className="search-none">
              <b>Nothing called “{q.trim()}” here.</b>
              <span>The Director understands plain English. Ask it to do this for you.</span>
              <button type="button" className="btn" onClick={() => onAskDirector(q.trim())}>
                <Sparkles size={13} /> Ask the Director
              </button>
            </div>
          )}
        </div>
        <div className="search-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
          <span><kbd>Enter</kbd> open</span>
          <span><kbd>Esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}

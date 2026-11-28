// v0.4.76 The documentary niche: what kind of documentary a project is (true crime, football, boxing & MMA ...).
// The niche picks the defaults that follow from it: the cinematic graphics offered first, the sound design's
// flavour, the music direction, the research and voice direction for the AI drafts and the starting look.
// The list comes from the server (niches.py); the tiles here only add the icons.
import React, { useEffect, useState } from "react";
import {
  Fingerprint,
  Trophy,
  Swords,
  Medal,
  Clapperboard,
  Landmark,
  ChartLine,
  Brain,
  BookOpen,
  Globe,
  CheckCircle2,
} from "lucide-react";

export const NICHE_ICONS = { Fingerprint, Trophy, Swords, Medal, Clapperboard, Landmark, ChartLine, Brain, BookOpen, Globe };
export const DEFAULT_NICHE = "truecrime";

// what the picker shows before the server answers (and if it cannot): true crime only, as before v0.4.76
const FALLBACK = {
  default: DEFAULT_NICHE,
  niches: [{ key: "truecrime", label: "True Crime", icon: "Fingerprint", about: "Cases, investigations, courts and their outcomes.",
    title_hint: "Case name or working title", collection: "truecrime", graphics: "", music: "", sound: { about: "", preset: "cinematic", flavour: {} } }],
};

let cache = null;
let pending = null;

export function loadNiches() {
  if (cache) return Promise.resolve(cache);
  if (!pending)
    pending = fetch("/api/niches", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => {
        cache = d && Array.isArray(d.niches) && d.niches.length ? d : FALLBACK;
        return cache;
      })
      .catch(() => {
        pending = null;
        return FALLBACK;
      });
  return pending;
}

export function useNiches() {
  const [data, setData] = useState(cache || FALLBACK);
  useEffect(() => {
    let live = true;
    loadNiches().then((d) => live && setData(d));
    return () => {
      live = false;
    };
  }, []);
  return data;
}

// the niche of a project (projects made before v0.4.76 are true crime)
// (the server only ever stores a known niche, so the key is trusted before the list has loaded)
export function nicheKey(project) {
  const k = project?.niche;
  return typeof k === "string" && k ? k : DEFAULT_NICHE;
}

export function nicheOf(project, data) {
  const list = (data || cache || FALLBACK).niches;
  const k = nicheKey(project);
  return list.find((n) => n.key === k) || list.find((n) => n.key === DEFAULT_NICHE) || list[0];
}

export default function NichePicker({ value, onChange, compact = false, disabled = false }) {
  const data = useNiches();
  const current = data.niches.find((n) => n.key === value) || data.niches[0];
  return (
    <div className="niche-picker">
      <div className={`niche-grid ${compact ? "compact" : ""}`} role="radiogroup" aria-label="Kind of documentary">
        {data.niches.map((n) => {
          const Icon = NICHE_ICONS[n.icon] || Globe;
          const on = n.key === value;
          return (
            <button
              type="button"
              key={n.key}
              role="radio"
              aria-checked={on}
              disabled={disabled}
              className={on ? "selected" : ""}
              title={n.about}
              onClick={() => onChange(n.key)}
            >
              <Icon size={compact ? 17 : 20} />
              <strong>{n.label}</strong>
              {on && <CheckCircle2 size={13} className="niche-check" />}
            </button>
          );
        })}
      </div>
      {current && (
        <p className="niche-about">
          <b>{current.label}:</b> {current.about}
          {current.graphics ? <> Graphics: {current.graphics}</> : null}
        </p>
      )}
    </div>
  );
}

// v0.4.76 The niche's direction for the music (a brief: you bring the track) or the sound design
export function NicheBrief({ project, kind = "music" }) {
  const data = useNiches();
  const n = nicheOf(project, data);
  const text = kind === "music" ? n?.music : n?.sound?.about;
  if (!n || !text) return null;
  const Icon = NICHE_ICONS[n.icon] || Globe;
  return (
    <div className="feature-note niche-brief">
      <Icon size={15} />
      <div>
        <b>{n.label}: {kind === "music" ? "music direction" : "sound design"}</b>
        <p>{text}</p>
      </div>
    </div>
  );
}

// v0.4.76 Whether the niche swaps any of the generic sound families (so the "niche sounds" switch means something)
export function nicheHasFlavour(project, data) {
  const n = nicheOf(project, data);
  return !!(n && n.sound && n.sound.flavour && Object.keys(n.sound.flavour).length);
}

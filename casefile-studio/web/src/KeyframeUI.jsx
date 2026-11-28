import React from "react";
import { EASES, EASE_LABELS, EASE_HINTS, ease, setSegment, setSpan, retimeKeys } from "./picture.js";

// v0.4.75 Keyframe speed, the way CapCut shows it:
//  * between two keyframes: HOW it moves (a curve, drawn) and HOW LONG it takes (seconds: shorter = faster);
//  * the whole move: how long it takes, or a speed (½× … 2×).
// One list for the picture's keyframes (Effects.jsx) and for stickers (StickerPanel.jsx).

const fmt = (t) => `${t.toFixed(2)} s`;

// the curve, drawn from the same maths the export uses (room for overshoot above and below)
export function CurveIcon({ kind, w = 34, h = 24 }) {
  const pad = 3;
  const lo = -0.25;
  const hi = 1.25;
  const pts = [];
  for (let i = 0; i <= 40; i++) {
    const u = i / 40;
    const v = kind === "hold" ? (i === 40 ? 1 : 0) : ease(u, kind);
    pts.push(`${(pad + u * (w - 2 * pad)).toFixed(1)},${(pad + (1 - (v - lo) / (hi - lo)) * (h - 2 * pad)).toFixed(1)}`);
  }
  if (kind === "hold") pts.splice(pts.length - 1, 0, `${(w - pad).toFixed(1)},${(pad + (1 - (0 - lo) / (hi - lo)) * (h - 2 * pad)).toFixed(1)}`);
  const y0 = pad + (1 - (0 - lo) / (hi - lo)) * (h - 2 * pad);
  const y1 = pad + (1 - (1 - lo) / (hi - lo)) * (h - 2 * pad);
  return (
    <svg className="curve-icon" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <line x1={pad} x2={w - pad} y1={y0} y2={y0} className="curve-axis" />
      <line x1={pad} x2={w - pad} y1={y1} y2={y1} className="curve-axis" />
      <polyline points={pts.join(" ")} className="curve-line" />
    </svg>
  );
}

// a dot that moves with the curve while you point at a choice (so you can see what it does)
function Demo({ kind }) {
  const [p, setP] = React.useState(0);
  React.useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const tick = (now) => {
      const c = ((now - t0) / 1400) % 1.35; // 1 s moving, a short rest
      setP(Math.min(1, c));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [kind]);
  const v = kind === "hold" ? (p >= 1 ? 1 : 0) : ease(p, kind);
  return (
    <div className="curve-demo" aria-hidden="true">
      <i style={{ left: `calc(${(6 + v * 88).toFixed(2)}% - 5px)` }} />
    </div>
  );
}

export function CurvePicker({ value, kinds = EASES, disabled, onChange }) {
  const [open, setOpen] = React.useState(false);
  const [hover, setHover] = React.useState(null);
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    const away = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <span className="curve-pick" ref={ref}>
      <button className="curve-chip" aria-label={`How it moves: ${EASE_LABELS[value]}`} aria-expanded={open} title={EASE_HINTS[value]} disabled={disabled} onClick={() => setOpen(!open)}>
        <CurveIcon kind={value} w={26} h={18} />
        {EASE_LABELS[value]}
      </button>
      {open && (
        <div className="curve-pop" role="listbox" aria-label="How it moves to the next keyframe">
          <div className="curve-pop-head">How it moves to the next keyframe</div>
          <div className="curve-grid">
            {kinds.map((k) => (
              <button
                key={k}
                role="option"
                aria-selected={k === value}
                className={`curve-tile ${k === value ? "on" : ""}`}
                onPointerEnter={() => setHover(k)}
                onPointerLeave={() => setHover((h) => (h === k ? null : h))}
                onFocus={() => setHover(k)}
                onClick={() => {
                  onChange(k);
                  setOpen(false);
                }}
              >
                <CurveIcon kind={k} w={44} h={30} />
                <b>{EASE_LABELS[k]}</b>
              </button>
            ))}
          </div>
          <Demo kind={hover || value} />
          <p className="curve-hint">
            <b>{EASE_LABELS[hover || value]}</b> — {EASE_HINTS[hover || value]}
          </p>
        </div>
      )}
    </span>
  );
}

// seconds with − / + and a typed value
function Secs({ label, value, min = 0.05, max, disabled, onChange }) {
  const [txt, setTxt] = React.useState(value.toFixed(2));
  React.useEffect(() => setTxt(value.toFixed(2)), [value]);
  const commit = (v) => {
    if (!Number.isFinite(v)) return setTxt(value.toFixed(2));
    onChange(Math.min(max, Math.max(min, Math.round(v * 100) / 100)));
  };
  const step = value >= 2 ? 0.25 : 0.05;
  return (
    <span className="kf-secs">
      <button aria-label={`${label}: less time (faster)`} disabled={disabled || value <= min + 1e-6} onClick={() => commit(value - step)}>−</button>
      <input
        aria-label={label}
        value={txt}
        disabled={disabled}
        inputMode="decimal"
        onChange={(e) => setTxt(e.target.value)}
        onBlur={() => commit(Number(txt.replace(/s$/i, "").trim()))}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
      <small>s</small>
      <button aria-label={`${label}: more time (slower)`} disabled={disabled || value >= max - 1e-6} onClick={() => commit(value + step)}>+</button>
    </span>
  );
}

const SPEEDS = [
  [0.5, "½×"],
  [0.75, "¾×"],
  [1.5, "1.5×"],
  [2, "2×"],
];

export function KeyframeList({ keys, kinds = EASES, length, at, describe, onSeek, onChange, disabled }) {
  if (!keys?.length) return null;
  const span = keys[keys.length - 1].t - keys[0].t;
  const room = length - keys[0].t;
  return (
    <div className="kf-list">
      {keys.map((k, i) => (
        <React.Fragment key={k.t}>
          <div className={`kf-item ${at === k ? "on" : ""}`}>
            <button className="kf-time" onClick={() => onSeek(k)}>◆ {fmt(k.t)}</button>
            <span>{describe(k)}</span>
            <button className="danger-link" aria-label={`Remove keyframe at ${fmt(k.t)}`} disabled={disabled} onClick={() => onChange(keys.filter((x) => x !== k))}>×</button>
          </div>
          {i < keys.length - 1 && (
            <div className="kf-seg">
              <CurvePicker value={k.ease} kinds={kinds} disabled={disabled} onChange={(e) => onChange(keys.map((x) => (x === k ? { ...x, ease: e } : x)))} />
              <span className="kf-seg-takes">takes</span>
              <Secs
                label={`Time from keyframe ${i + 1} to ${i + 2}`}
                value={keys[i + 1].t - k.t}
                max={Math.max(0.05, length - k.t - (keys[keys.length - 1].t - keys[i + 1].t))}
                disabled={disabled}
                onChange={(v) => {
                  const next = setSegment(keys, i, v, length);
                  if (next) onChange(next);
                }}
              />
            </div>
          )}
        </React.Fragment>
      ))}
      {keys.length > 1 && (
        <div className="kf-speed">
          <span>
            Whole move
            <small>shorter = faster</small>
          </span>
          <Secs label="Whole move time" value={span} max={Math.max(0.05, room)} disabled={disabled} onChange={(v) => { const next = setSpan(keys, v, length); if (next) onChange(next); }} />
          <span className="kf-speeds" role="group" aria-label="Speed">
            {SPEEDS.map(([x, label]) => {
              const next = retimeKeys(keys, 1 / x, length);
              return (
                <button key={x} className="btn subtle" disabled={disabled || !next} title={next ? `${x > 1 ? "Faster" : "Slower"}: the move takes ${(span / x).toFixed(2)} s` : x < 1 ? "It would run past the end" : "The keyframes would be too close"} onClick={() => onChange(next)}>
                  {label}
                </button>
              );
            })}
          </span>
        </div>
      )}
    </div>
  );
}

import React from "react";

// v0.4.58 A level slider that is heard as it moves and saved once when you let go.
//
// While it moves only this component re-renders and `onLive(v)` is called (the caller sets a
// WebAudio gain — no request, no project change, no new plan, no re-render of the editor).
// `onCommit(v)` is called once: when the pointer is released (never during a drag, however slow),
// or 400 ms after the last change made with the keyboard / wheel. The saved value then flows back through `value`.
export default function LiveRange({ label, value, min, max, step, format = (v) => String(v), onLive, onCommit, disabled, ariaLabel, className = "", title }) {
  const [v, setV] = React.useState(value);
  const pending = React.useRef(false);
  const latest = React.useRef(value);
  const start = React.useRef(value); // the saved value when this change began
  const timer = React.useRef(null);
  const down = React.useRef(false); // a drag in progress is saved when it ends, however slowly it moves
  React.useEffect(() => {
    if (!pending.current) { setV(value); latest.current = value; }
  }, [value]);
  React.useEffect(() => () => clearTimeout(timer.current), []);
  const commit = () => {
    clearTimeout(timer.current);
    if (!pending.current) return;
    pending.current = false;
    if (latest.current !== start.current) onCommit?.(latest.current); // the caller may show the live value as `value`
  };
  const change = (e) => {
    const x = Math.min(max, Math.max(min, Number(e.target.value)));
    if (!Number.isFinite(x)) return;
    latest.current = x;
    if (!pending.current) start.current = value;
    pending.current = true;
    setV(x);
    onLive?.(x);
    clearTimeout(timer.current);
    if (!down.current) timer.current = setTimeout(commit, 400);
  };
  const release = () => { down.current = false; commit(); };
  return (
    <label className={`field live-range ${className}`} title={title}>
      <span className="live-range-head">
        {label} <span className="field-note">{format(v)}</span>
      </span>
      <input
        aria-label={ariaLabel || label}
        className="range"
        type="range"
        min={min}
        max={max}
        step={step}
        value={v}
        disabled={disabled}
        onChange={change}
        onPointerDown={() => { down.current = true; }}
        onPointerUp={release}
        onPointerCancel={release}
        onLostPointerCapture={release}
        onKeyUp={(e) => { if (!e.key.startsWith("Arrow") && !["PageUp", "PageDown", "Home", "End"].includes(e.key)) commit(); }}
        onBlur={release}
      />
    </label>
  );
}

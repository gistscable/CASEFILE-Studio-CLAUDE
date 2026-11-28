import React from "react";
import { FONTS, PRESETS, LIMITS, normaliseStyle, applyPreset, captionCss } from "./captionStyle.js";

// v0.4.25 Captions tab in the Edit inspector: a gallery of looks, then size,
// font, colours, outline, box, shadow, position, words per caption, case and
// animation. The export uses the same style, so the preview is the result.

const SAMPLE = ["The", "truth", "came", "out"];

function Swatch({ label, value, onChange, disabled }) {
  return (
    <label className="cs-swatch">
      <span>{label}</span>
      <input type="color" aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value.toUpperCase())} />
    </label>
  );
}

function Slider({ label, k, value, onChange, disabled, scale = 1000, unit = "", show }) {
  const [lo, hi] = LIMITS[k];
  return (
    <label className="cs-slider">
      <span>
        {label} <b>{show ? show(value) : `${Math.round(value * scale)}${unit}`}</b>
      </span>
      <input
        type="range"
        aria-label={label}
        min={lo * scale}
        max={hi * scale}
        step="1"
        value={Math.round(value * scale)}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value) / scale)}
      />
    </label>
  );
}

export function PresetCard({ preset, selected, onPick, disabled }) {
  const style = applyPreset({}, preset.id);
  const css = captionCss(style, 160, 270);
  const words = style.uppercase ? SAMPLE.map((w) => w.toUpperCase()) : SAMPLE;
  const shown = style.words ? words.slice(0, Math.min(words.length, style.words)) : words;
  return (
    <button
      className={`cs-preset ${selected ? "selected" : ""}`}
      aria-label={`Caption style ${preset.label}`}
      aria-pressed={selected}
      disabled={disabled}
      onClick={() => onPick(preset.id)}
    >
      <div className="cs-preset-frame">
        <div style={{ ...css.wrap, cursor: "pointer", left: "4%", right: "4%", bottom: "50%", transform: "translateY(50%)" }}>
          <span style={css.text}>
            {shown.map((w, i) => (
              <React.Fragment key={i}>
                {i > 0 && " "}
                <span style={style.animation === "highlight" && i === 1 ? { color: style.highlight } : undefined}>{w}</span>
              </React.Fragment>
            ))}
          </span>
        </div>
      </div>
      <span className="cs-preset-name">{preset.label}</span>
    </button>
  );
}

export default function CaptionStyles({ value, enabled, onChange, onToggle, disabled, section }) {
  const s = normaliseStyle(value);
  const set = (patch) => onChange(normaliseStyle({ ...s, ...patch }));
  // v0.4.69 the left Captions tab shows one part at a time: styles, text, box & position
  const show = (k) => !section || section === k;
  return (
    <div className="inspector-content cs">
      {show("styles") && (<>
      <label className="cs-toggle">
        <input type="checkbox" aria-label="Burn captions into the video" checked={!!enabled} disabled={disabled} onChange={(e) => onToggle(e.target.checked)} />
        <span>Captions in the video</span>
      </label>
      <p className="micro-note block">Drag the captions up or down on the preview to move them. The export looks the same.</p>

      <div className="section-label">
        <span>STYLES</span>
      </div>
      <div className="cs-presets">
        {PRESETS.map((p) => (
          <PresetCard key={p.id} preset={p} selected={s.preset === p.id} disabled={disabled} onPick={(id) => onChange(applyPreset(s, id))} />
        ))}
      </div>
      </>)}
      {show("text") && (<>

      <div className="section-label">
        <span>TEXT</span>
      </div>
      <label className="field">
        Font
        <select aria-label="Caption font" value={s.font} disabled={disabled} onChange={(e) => set({ font: e.target.value })}>
          {Object.entries(FONTS).map(([k, f]) => (
            <option key={k} value={k}>
              {f.label}
            </option>
          ))}
        </select>
      </label>
      <Slider label="Caption size" k="size" value={s.size} disabled={disabled} onChange={(v) => set({ size: v })} show={(v) => `${Math.round((v / 0.0335) * 100)}%`} />
      <div className="cs-row">
        <Swatch label="Text colour" value={s.color} disabled={disabled} onChange={(v) => set({ color: v })} />
        {s.animation === "highlight" && <Swatch label="Highlight colour" value={s.highlight} disabled={disabled} onChange={(v) => set({ highlight: v })} />}
        <label className="cs-check">
          <input type="checkbox" aria-label="Uppercase captions" checked={s.uppercase} disabled={disabled} onChange={(e) => set({ uppercase: e.target.checked })} />
          ABC
        </label>
      </div>
      <label className="field">
        Words on screen at once
        <select aria-label="Words on screen at once" value={String(s.words)} disabled={disabled} onChange={(e) => set({ words: Number(e.target.value) })}>
          <option value="0">Whole line (as timed)</option>
          {[1, 2, 3, 4, 5, 6, 8, 10, 12].map((n) => (
            <option key={n} value={n}>
              {n} word{n === 1 ? "" : "s"}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        Animation
        <select aria-label="Caption animation" value={s.animation} disabled={disabled} onChange={(e) => set({ animation: e.target.value })}>
          <option value="none">None</option>
          <option value="fade">Fade in</option>
          <option value="pop">Pop in</option>
          <option value="highlight">Highlight each word as it is said</option>
        </select>
      </label>

      </>)}
      {show("box") && (<>
      <div className="section-label">
        <span>OUTLINE, BOX AND SHADOW</span>
      </div>
      <div className="cs-row">
        <label className="cs-check">
          <input type="checkbox" aria-label="Box behind the captions" checked={s.box} disabled={disabled} onChange={(e) => set({ box: e.target.checked })} />
          Box behind
        </label>
        {s.box ? (
          <Swatch label="Box colour" value={s.box_color} disabled={disabled} onChange={(v) => set({ box_color: v })} />
        ) : (
          <Swatch label="Outline colour" value={s.outline_color} disabled={disabled} onChange={(v) => set({ outline_color: v })} />
        )}
      </div>
      {s.box && <Slider label="Box opacity" k="box_opacity" value={s.box_opacity} scale={100} unit="%" disabled={disabled} onChange={(v) => set({ box_opacity: v })} />}
      <Slider label={s.box ? "Box padding" : "Outline"} k="outline" value={s.outline} scale={1000} disabled={disabled} onChange={(v) => set({ outline: v })} />
      <Slider label="Shadow" k="shadow" value={s.shadow} scale={1000} disabled={disabled} onChange={(v) => set({ shadow: v })} />
      <Slider label="Height from the bottom" k="position" value={s.position} scale={100} unit="%" disabled={disabled} onChange={(v) => set({ position: v })} />
      <button className="btn cs-reset" disabled={disabled} onClick={() => onChange(applyPreset({}, s.preset))}>
        Reset to “{PRESETS.find((p) => p.id === s.preset)?.label}”
      </button>
      </>)}
      {section && section !== "styles" && !enabled && <p className="micro-note block">Captions are off. Switch them on under Styles to see these changes in the video.</p>}
    </div>
  );
}

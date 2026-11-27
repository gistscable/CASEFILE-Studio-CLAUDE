import React from "react";
import { Plus, Trash2, Check, RotateCcw, Play, Sparkles, X, Shuffle, Film } from "lucide-react";
import { MG, TEMPLATES, STATUS, normaliseMotion, optionLabel, cleanLook } from "./motion.js";
import { Step, clock, parseClock } from "./Effects.jsx";
import { planFor } from "./MotionLayer.jsx";

const pct = (v) => `${Math.round(v * 100)}%`;
const round3 = (t) => Math.round(t * 1000) / 1000;

function Choice({ label, value, options, onChange, disabled }) {
  return (
    <label className="field mg-field">
      {label}
      <select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => {
          const [id, text] = Array.isArray(o) ? o : [o, o];
          return <option key={id} value={id}>{text}</option>;
        })}
      </select>
    </label>
  );
}

// v0.4.53: the presets, and any colour (the picker commits once you stop moving it).
function Swatches({ label, value, options, onChange, disabled }) {
  const [live, setLive] = React.useState(value);
  const timer = React.useRef(null);
  React.useEffect(() => setLive(value), [value]);
  React.useEffect(() => () => clearTimeout(timer.current), []);
  const custom = !options.some(([c]) => c === value);
  return (
    <div className="mg-swatches">
      <span>{label}</span>
      {options.map(([c, name]) => (
        <button key={c} title={name} aria-label={`${label}: ${name}`} className={value === c ? "on" : ""} disabled={disabled}
          style={{ background: c }} onClick={() => onChange(c)} />
      ))}
      <label className={`mg-picker ${custom ? "on" : ""}`} title="Any colour">
        <input type="color" aria-label={`${label} colour`} value={live} disabled={disabled}
          onChange={(e) => {
            const c = e.target.value.toLowerCase();
            setLive(c);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => c !== value && onChange(c), 350);
          }} />
      </label>
    </div>
  );
}

// v0.4.62 The story-aware graphics' collections (niches) and categories, from the server (loaded once).
let CATALOG = null;
function useCatalog() {
  const [cat, setCat] = React.useState(CATALOG);
  React.useEffect(() => {
    if (CATALOG) return;
    let live = true;
    fetch("/api/motion/catalog", { credentials: "same-origin" })
      .then((r) => r.json())
      .then((d) => { CATALOG = d; if (live) setCat(d); })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  return cat;
}
const categoryOf = (catalog, it) => {
  const c = (catalog?.collections || []).find((x) => x.key === it.collection);
  return c?.categories.find((k) => k.key === it.category) || null;
};
const itemName = (catalog, x) => (x.template === "cinematic" ? x.label || categoryOf(catalog, x)?.label || "Cinematic graphic" : x.title || TEMPLATES[x.template].label);
const kindName = (catalog, x) => (x.template === "cinematic" ? `Cinematic · ${categoryOf(catalog, x)?.label || x.category}` : TEMPLATES[x.template].label);

// v0.4.63 The look of the cinematic graphics: each category's tested colour sets, your own colours (checked
// for readability by the server, which draws them) and what the graphics are drawn over.
const BACKDROPS = {
  own: "Its own background",
  footage: "Your footage, darkened",
  still: "A still from your footage",
  photo: "A photo from the project",
};
const isHex = (v) => /^#[0-9a-f]{6}$/i.test(v || "");

function Sets({ label, value, palettes, onChange, disabled, follow }) {
  return (
    <div className="mg-sets" role="group" aria-label={label}>
      <span>{label}</span>
      <div className="mg-sets-row">
        {follow && (
          <button className={`mg-set follow ${!value ? "on" : ""}`} disabled={disabled} onClick={() => onChange("")} aria-pressed={!value}>
            <small>{follow}</small>
          </button>
        )}
        {palettes.map((p) => (
          <button key={p.key} className={`mg-set ${value === p.key ? "on" : ""}`} disabled={disabled} title={p.label} aria-label={`${label}: ${p.label}`}
            aria-pressed={value === p.key} onClick={() => onChange(p.key)}>
            <i style={{ background: p.colors.bg }}>
              <em style={{ color: p.colors.ink }}>Aa</em>
              <b style={{ background: p.colors.accent }} />
              {p.colors.accent2 !== p.colors.accent && <b style={{ background: p.colors.accent2 }} />}
            </i>
            <small>{p.label}</small>
          </button>
        ))}
      </div>
    </div>
  );
}

// "" follows (the project, or the designs), "own" is the design's own colour (a graphic, over the project's), or any colour
function ColourPick({ label, value, onChange, disabled, follow, own }) {
  const [live, setLive] = React.useState(isHex(value) ? value : "#ffffff");
  const timer = React.useRef(null);
  React.useEffect(() => { if (isHex(value)) setLive(value.toLowerCase()); }, [value]);
  React.useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <div className="mg-swatches mg-colour">
      <span>{label}</span>
      <button className={`mg-chip ${!value ? "on" : ""}`} disabled={disabled} aria-pressed={!value} onClick={() => onChange("")}>{follow}</button>
      {own && <button className={`mg-chip ${value === "own" ? "on" : ""}`} disabled={disabled} aria-pressed={value === "own"} onClick={() => onChange("own")}>Design's own</button>}
      <label className={`mg-picker ${isHex(value) ? "on" : ""}`} title="Your own colour (checked for readability)">
        <input type="color" aria-label={`${label}: your own colour`} value={live} disabled={disabled}
          onChange={(e) => {
            const c = e.target.value.toLowerCase();
            setLive(c);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => c !== value && onChange(c), 350);
          }} />
      </label>
      {isHex(value) && <code className="mg-hex">{value.toUpperCase()}</code>}
    </div>
  );
}

// v0.4.64 Type and layout: a font style, the text size, the layout mirrored (photo and text swap sides) and the
// layout's size and place in the frame. The server checks every choice against what the category's layout holds.
const PLACES = [[-1, -1], [0, -1], [1, -1], [-1, 0], [0, 0], [1, 0], [-1, 1], [0, 1], [1, 1]];
const PLACE_NAMES = { "-1,-1": "Top left", "0,-1": "Top", "1,-1": "Top right", "-1,0": "Left", "0,0": "Centre", "1,0": "Right",
  "-1,1": "Bottom left", "0,1": "Bottom", "1,1": "Bottom right" };
const FULL = { scale: 1, x: 0, y: 0 };
const r2 = (v) => Math.round(v * 100) / 100;

function Placement({ value, onChange, disabled, range }) {
  const p = { ...FULL, ...(value || {}) };
  const [lo, hi] = range || [0.8, 1];
  const set = (patch) => onChange({ ...p, ...patch });
  return (
    <div className="mg-place-box">
      <Step label="Layout size" value={p.scale} display={pct(p.scale)} step={0.05} min={lo} max={hi} disabled={disabled} onChange={(x) => set({ scale: r2(x) })} />
      <div className="mg-place-row">
        <span>Position</span>
        <div className="mg-place" role="group" aria-label="Position in the frame">
          {PLACES.map(([x, y]) => {
            const on = Math.round(p.x) === x && Math.round(p.y) === y && Math.abs(p.x - x) < 0.01 && Math.abs(p.y - y) < 0.01;
            return <button key={`${x},${y}`} className={on ? "on" : ""} disabled={disabled} aria-pressed={on} title={PLACE_NAMES[`${x},${y}`]}
              aria-label={PLACE_NAMES[`${x},${y}`]} onClick={() => set({ x, y })}><i /></button>;
          })}
        </div>
      </div>
      <Step label="Nudge across" value={p.x} display={p.x === 0 ? "centre" : `${p.x < 0 ? "←" : "→"} ${Math.round(Math.abs(p.x) * 100)}`} step={0.1} min={-1} max={1}
        disabled={disabled} onChange={(x) => set({ x: r2(x) })} />
      <Step label="Nudge up/down" value={p.y} display={p.y === 0 ? "centre" : `${p.y < 0 ? "↑" : "↓"} ${Math.round(Math.abs(p.y) * 100)}`} step={0.1} min={-1} max={1}
        disabled={disabled} onChange={(y) => set({ y: r2(y) })} />
    </div>
  );
}

function ProjectType({ look, set, catalog, cats, disabled }) {
  const ty = catalog?.type || { styles: [], size: [0.85, 1.15], place: [0.8, 1] };
  const mirrorable = cats.filter((k) => k.looks?.mirror);
  const placeable = cats.filter((k) => k.looks?.place);
  const fixed = cats.filter((k) => !k.looks?.place);
  return (
    <>
      <div className="mg-sets-head">Type and layout</div>
      <Choice label="Font" value={look.font || ""} disabled={disabled} options={[["", "Each design's own"], ...ty.styles.map((s) => [s.key, s.label])]}
        onChange={(v) => set({ font: v || undefined })} />
      {look.font && <p className="micro-note block">Fonts bundled with the app. A layout a font does not fit keeps its own (that graphic says so).</p>}
      <Step label="Text size" value={look.size ?? 1} display={pct(look.size ?? 1)} step={0.05} min={ty.size[0]} max={ty.size[1]} disabled={disabled}
        onChange={(x) => set({ size: Math.abs(x - 1) < 0.001 ? undefined : r2(x) })} />
      <p className="micro-note block">Headings, labels and body text. The big dates and headlines are composed for each design and fitted to their space.</p>
      {mirrorable.length > 0 && (
        <label className="cs-check">
          <input type="checkbox" checked={!!look.mirror} disabled={disabled} onChange={(e) => set({ mirror: e.target.checked || undefined })} />
          Mirror the layouts that can be ({mirrorable.map((k) => k.label.toLowerCase()).join(", ")}): photo and text swap sides
        </label>
      )}
      {placeable.length > 0 && (
        <>
          <Placement value={look.place} range={ty.place} disabled={disabled}
            onChange={(pl) => set({ place: pl.scale === 1 && pl.x === 0 && pl.y === 0 ? undefined : pl })} />
          <p className="micro-note block">
            Smaller, the layout sits where you put it and its background still fills the frame.
            {fixed.length ? ` ${fixed.map((k) => k.label).join(", ")} fill${fixed.length === 1 ? "s" : ""} the screen and keep${fixed.length === 1 ? "s" : ""} size and position.` : ""}
          </p>
        </>
      )}
    </>
  );
}

function GraphicType({ own, setLook, cat, style, catalog, disabled }) {
  const lk = cat?.looks || {};
  const ty = style?.type || {};
  const from = style?.from || {};
  const fonts = lk.fonts || [{ key: "design", label: "As designed" }];
  const fontName = (k) => fonts.find((f) => f.key === k)?.label || "as designed";
  const [lo, hi] = lk.size || [1, 1];
  const proj = (k, text) => `Project${style && from[k] !== "graphic" ? ` (${text})` : ""}`;
  const placeRange = catalog?.type?.place || [0.8, 1];
  return (
    <>
      <div className="mg-sets-head">Type and layout</div>
      {fonts.length > 1 && (
        <Choice label="Font" value={own.font || ""} disabled={disabled}
          options={[["", proj("font", fontName(ty.font).toLowerCase())], ...fonts.map((f) => [f.key, f.label])]}
          onChange={(v) => setLook({ font: v || undefined })} />
      )}
      {hi > lo && (
        <div className="mg-row-inline">
          <Step label="Text size" value={own.size ?? ty.size ?? 1} display={pct(own.size ?? ty.size ?? 1)} step={0.05} min={lo} max={hi} disabled={disabled}
            onChange={(x) => setLook({ size: r2(x) })} />
          {own.size !== undefined && <button className="text-link" disabled={disabled} onClick={() => setLook({ size: undefined })}>project</button>}
        </div>
      )}
      {lk.mirror && (
        <Choice label="Layout" value={own.mirror === true ? "mirror" : own.mirror === false ? "design" : ""} disabled={disabled}
          options={[["", proj("mirror", ty.mirror ? "mirrored" : "as designed")], ["design", "As designed"], ["mirror", `Mirrored: ${lk.mirror.toLowerCase()}`]]}
          onChange={(v) => setLook({ mirror: v === "" ? undefined : v === "mirror" })} />
      )}
      {lk.place ? (
        <>
          <Placement value={own.place || ty.place || FULL} range={placeRange} disabled={disabled} onChange={(pl) => setLook({ place: pl })} />
          {own.place && <button className="text-link" disabled={disabled} onClick={() => setLook({ place: undefined })}>Use the project's size and position</button>}
        </>
      ) : (
        <p className="micro-note block">{cat?.label || "This graphic"} fills the screen: it keeps its size and position.</p>
      )}
    </>
  );
}

// The project look: every cinematic graphic follows it unless you change that graphic (select it, then LOOK).
function ProjectLook({ project, look, coll, catalog, images, disabled, onChange }) {
  const set = (patch) => onChange(cleanLook({ ...look, ...patch }));
  const dimD = catalog?.dim || { min: 0.4, max: 0.85, default: 0.62 };
  const pictures = look.background && look.background !== "own";
  const cats = coll?.categories || [];
  const noPicture = cats.filter((k) => !(k.looks?.backdrops || []).includes("footage"));
  const changed = Object.keys(look).length > 0;
  return (
    <details className="mg-look">
      <summary>Look of all cinematic graphics{changed ? " · changed" : ""}</summary>
      <p className="micro-note block">
        For every cinematic graphic in this project. One graphic can still have its own look: select it, then change it under LOOK.
      </p>
      <label className="cs-check">
        <input type="checkbox" checked={!!look.vary} disabled={disabled}
          onChange={(e) => set({ vary: e.target.checked, seed: e.target.checked ? look.seed || project.id : undefined })} />
        Vary the look automatically for this project
      </label>
      <p className="micro-note block">
        Each category gets one of its tested colour sets, picked from this project's own id: this project always looks the same, other projects look different.
        A set you choose below, or on one graphic, always wins.
      </p>
      <Choice label="Background" value={look.background || "own"} disabled={disabled}
        options={[["own", "Each design's own background"], ["footage", BACKDROPS.footage], ["still", "A still from your footage (at each graphic)"], ...(images.length ? [["photo", BACKDROPS.photo]] : [])]}
        onChange={(v) => set({ background: v === "own" ? undefined : v, photo_id: v === "photo" ? look.photo_id || images[0]?.id : undefined })} />
      {look.background === "photo" && (
        <Choice label="Photo (from your project)" value={look.photo_id || ""} options={images.map((a) => [a.id, a.name])} disabled={disabled} onChange={(v) => set({ photo_id: v })} />
      )}
      {pictures && (
        <>
          <Step label="Darken" value={look.dim ?? dimD.default} display={pct(look.dim ?? dimD.default)} step={0.05} min={dimD.min} max={dimD.max} disabled={disabled}
            onChange={(x) => set({ dim: Math.round(x * 100) / 100 })} />
          <p className="micro-note block">
            {noPicture.map((k) => k.looks.backdrop_note).join(" ")}
            {cats.some((k) => k.looks?.palettes?.[0]?.light) ? " A design on paper uses its dark version over a picture, so the text stays light." : ""}
            {look.background === "footage" ? " See-through: back to back, the earlier graphic fades out under the next one." : ""}
            {look.dim === undefined ? cats.filter((k) => k.looks?.dim && Math.abs(k.looks.dim - dimD.default) > 0.001).map((k) => ` ${k.label} is darkened ${pct(k.looks.dim)} unless you set it: its small labels need it.`).join("") : ""}
          </p>
        </>
      )}
      <ColourPick label="Accent" value={look.accent || ""} follow="Each design's own" disabled={disabled} onChange={(v) => set({ accent: v || undefined })} />
      <ColourPick label="Text" value={look.text || ""} follow="Each design's own" disabled={disabled} onChange={(v) => set({ text: v || undefined })} />
      {(look.accent || look.text) && (
        <p className="micro-note block">Checked against each design's background: a colour too faint to read there is drawn in its nearest readable shade (the graphic tells you).</p>
      )}
      <div className="mg-sets-head">Colour sets (tested for readability)</div>
      {cats.map((k) => (
        <Sets key={k.key} label={k.label} value={look.palettes?.[k.key] || (look.vary ? "" : k.looks?.palettes?.[0]?.key)} palettes={k.looks?.palettes || []}
          follow={look.vary ? "Automatic" : null} disabled={disabled}
          onChange={(v) => set({ palettes: { ...(look.palettes || {}), [k.key]: v === k.looks?.palettes?.[0]?.key && !look.vary ? undefined : v || undefined } })} />
      ))}
      <ProjectType look={look} set={set} catalog={catalog} cats={cats} disabled={disabled} />
      {changed && (
        <button className="text-link" disabled={disabled} onClick={() => onChange({})}>Back to each design's approved look</button>
      )}
    </details>
  );
}

// v0.4.62 A story-aware graphic: its words, design and timing come from the narration (it is drawn in
// sync with the words, so it is moved by choosing another passage, not by dragging). You choose its
// category, the photos of its slots (only your own, with the credit you type) and the captions.
function CinematicEditor({ sel, info, images, catalog, disabled, busy, update, onPlayFrom, onRemove, onRemake, previewStatus, time }) {
  const cat = categoryOf(catalog, sel);
  const own = sel.look || {};
  const setLook = (patch) => update(sel.id, { look: cleanLook({ ...own, ...patch }) });
  const style = info && info.id === sel.id ? info.style || null : null;
  const pals = cat?.looks?.palettes || [];
  const palName = (k) => pals.find((p) => p.key === k)?.label || k;
  const bds = (cat?.looks?.backdrops || ["own"]).filter((b) => b !== "photo" || images.length);
  const dimD = catalog?.dim || { min: 0.4, max: 0.85, default: 0.62 };
  const picture = style && style.background !== "own";
  const projectSet = style && style.from?.palette !== "graphic" ? ` (${palName(style.palette)})` : "";
  const coll = (catalog?.collections || []).find((x) => x.key === sel.collection);
  const slots = info && info.id === sel.id ? info.slots || [] : null;
  const setPhoto = (key, patch) => {
    const cur = sel.photos[key] || { asset_id: "", credit: "", month: "", auto: false };
    update(sel.id, { photos: { ...sel.photos, [key]: { ...cur, ...patch, auto: false } } });
  };
  return (
    <div className="st-edit">
      <div className="section-label sub">
        <span>{(cat?.label || "Cinematic graphic").toUpperCase()}</span>
        <small className={`mg-badge ${sel.status}`}>{STATUS[sel.status]}</small>
      </div>
      {cat?.about && <p className="micro-note block">{cat.about}</p>}
      {sel.reason && <p className="micro-note block">Why here: {sel.reason}</p>}
      <div className="st-actions">
        <button className="btn" disabled={disabled} onClick={() => onPlayFrom(Math.max(0, sel.start - 0.5))}>
          <Play size={12} /> Play it
        </button>
        {sel.status !== "approved" ? (
          <button className="btn primary" disabled={disabled} onClick={() => update(sel.id, { status: "approved" })}>
            <Check size={12} /> Approve
          </button>
        ) : (
          <button className="btn" disabled={disabled} onClick={() => update(sel.id, { status: "draft" })}>Unapprove</button>
        )}
        <button className="btn danger" disabled={disabled} onClick={onRemove}>
          {sel.status === "suggested" ? <><X size={12} /> Reject</> : <><Trash2 size={12} /> Remove</>}
        </button>
      </div>
      {previewStatus === "preparing" && <p className="micro-note">Preparing the preview…</p>}
      {coll && (
        <Choice label="Category" value={sel.category} options={coll.categories.map((k) => [k.key, k.label])} disabled={disabled || !!busy}
          onChange={(v) => v !== sel.category && onRemake(sel, v)} />
      )}
      <p className="micro-note block">
        It covers {clock(sel.start)}–{clock(sel.end)} and follows the narration word by word; every word on it is from your script.
        To place it elsewhere, make one from another passage.
      </p>
      <label className="cs-check">
        <input type="checkbox" checked={sel.hide_captions} disabled={disabled} onChange={(e) => update(sel.id, { hide_captions: e.target.checked })} />
        Hide captions while it is on screen
      </label>

      <div className="section-label sub"><span>PHOTOS</span></div>
      {slots === null && <p className="micro-note">Reading the graphic…</p>}
      {slots && !slots.length && <p className="micro-note block">This graphic uses no photos.</p>}
      {slots && slots.length > 0 && (
        <p className="micro-note block">Only photos from your project, with the credit you give them. An empty slot is simply not drawn; nothing is searched for or made up.</p>
      )}
      {(slots || []).map((sl) => {
        const v = sel.photos[sl.key] || { asset_id: "", credit: "", month: "" };
        return (
          <div key={sl.key} className="mg-line">
            <div className="mg-line-head"><b>{sl.label}</b>{v.auto && v.asset_id ? <small> · matched by file name</small> : null}</div>
            <select aria-label={sl.label} value={v.asset_id} disabled={disabled} onChange={(e) => setPhoto(sl.key, { asset_id: e.target.value })}>
              <option value="">No photo</option>
              {images.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            {v.asset_id && (
              <div className="mg-row">
                <input aria-label={`Credit for ${sl.label}`} placeholder="Credit (e.g. Courtesy of the family)" key={sel.id + sl.key + "c" + v.credit} defaultValue={v.credit}
                  maxLength={120} disabled={disabled} onBlur={(e) => e.target.value !== v.credit && setPhoto(sl.key, { credit: e.target.value })} />
                <input aria-label={`Month for ${sl.label}`} placeholder="Month (optional)" key={sel.id + sl.key + "m" + v.month} defaultValue={v.month}
                  maxLength={30} disabled={disabled} onBlur={(e) => e.target.value !== v.month && setPhoto(sl.key, { month: e.target.value })} />
              </div>
            )}
            {v.asset_id && info?.id === sel.id && !sl.filled && <p className="micro-note mg-warn">That photo's file is missing: the slot is left empty.</p>}
          </div>
        );
      })}

      <div className="section-label sub"><span>LOOK</span></div>
      <p className="micro-note block">
        {Object.keys(own).length ? "This graphic has its own look (changed here); the rest follows the project look." : "Follows the project look (Motion › Look of all cinematic graphics)."}
        {Object.keys(own).length > 0 && (
          <> <button className="text-link" disabled={disabled} onClick={() => update(sel.id, { look: {} })}>Use the project look</button></>
        )}
      </p>
      {pals.length > 0 && (
        <Sets label="Colours" value={own.palette || ""} palettes={pals} follow={`Project${projectSet}`} disabled={disabled} onChange={(v) => setLook({ palette: v || undefined })} />
      )}
      <ColourPick label="Accent" value={own.accent || ""} follow="Project" own disabled={disabled} onChange={(v) => setLook({ accent: v || undefined })} />
      <ColourPick label="Text" value={own.text || ""} follow="Project" own disabled={disabled} onChange={(v) => setLook({ text: v || undefined })} />
      <Choice label="Background" value={own.background || ""} disabled={disabled}
        options={[["", `Project${style && style.from?.background !== "graphic" ? ` (${BACKDROPS[style.background].toLowerCase()})` : ""}`], ...bds.map((b) => [b, BACKDROPS[b]])]}
        onChange={(v) => setLook({ background: v || undefined, photo_id: v === "photo" ? own.photo_id || images[0]?.id : undefined, still_at: v === "still" ? own.still_at ?? sel.start : undefined })} />
      {bds.length === 1 && cat?.looks?.backdrop_note && <p className="micro-note block">{cat.looks.backdrop_note}</p>}
      {own.background === "photo" && (
        <Choice label="Photo (from your project)" value={own.photo_id || ""} options={images.map((a) => [a.id, a.name])} disabled={disabled} onChange={(v) => setLook({ photo_id: v })} />
      )}
      {own.background === "still" && (
        <div className="mg-still">
          <Step label="Still from" value={own.still_at ?? sel.start} display={clock(own.still_at ?? sel.start)} typed={parseClock} step={0.5} min={0} max={86400} disabled={disabled}
            onChange={(x) => setLook({ still_at: round3(x) })} />
          <button className="text-link" disabled={disabled} title="The footage on the timeline at the playhead" onClick={() => setLook({ still_at: round3(time) })}>set to playhead</button>
          <p className="micro-note">The frame of your own footage that plays on the timeline at that moment, darkened (not blurred).</p>
        </div>
      )}
      {picture && (
        <Step label="Darken" value={style.dim ?? dimD.default} display={pct(style.dim ?? dimD.default)} step={0.05} min={dimD.min} max={dimD.max} disabled={disabled}
          onChange={(x) => setLook({ dim: Math.round(x * 100) / 100 })} />
      )}
      {style && (style.background === "still" || style.background === "photo") && info.backdrop === "own" && (
        <p className="micro-note block mg-warn">
          {style.background === "still" ? "No footage plays at that moment (a gap, a card or a missing file)" : "That photo's file is missing (or none is chosen)"}: its own background is used. Nothing is made up.
        </p>
      )}
      {style && style.background === "footage" && <p className="micro-note block">See-through: your footage plays under it, darkened. Back to back, the graphic before it fades out under it.</p>}
      <GraphicType own={own} setLook={setLook} cat={cat} style={style} catalog={catalog} disabled={disabled} />
      {(style?.notes || []).map((n, i) => <p key={i} className="micro-note block mg-warn">{n}</p>)}
    </div>
  );
}

// v0.4.52 Motion tab of the inspector: suggestions from the narration, graphics you make from a
// passage you choose, and everything about the selected graphic. Only approved graphics go into
// the export, and only while "Add to the export" is on (off by default).
// v0.4.65 Automatic presentation (optional, off by default): proposes full screen, over the footage or partial for
// each cinematic graphic, from its design, the shots under it and the production script's chapter and shot notes.
// Nothing changes until you apply a proposal; it becomes that graphic's own look, so you can change it back.
const MODE = { own: "Full screen", footage: "Over the footage", partial: "Partial, beside the footage", still: "Over a still", photo: "Over a photo" };

function AutoPresent({ m, save, onPresent, onSeek, onSelect, disabled }) {
  const [props, setProps] = React.useState(null);
  const [picked, setPicked] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const cine = m.items.filter((x) => x.template === "cinematic");
  const key = JSON.stringify(cine.map((x) => [x.id, x.start, x.end, x.look || {}]));
  const ask = async (apply) => {
    setBusy(true);
    setErr("");
    try {
      const r = await onPresent(apply ? { apply } : {});
      setProps(r.proposals);
      setPicked(Object.fromEntries(r.proposals.filter((p) => !p.same).map((p) => [p.id, true])));
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };
  React.useEffect(() => { if (m.present && cine.length) ask(); else setProps(null); }, [m.present, key]);
  const changes = (props || []).filter((p) => !p.same);
  const chosen = changes.filter((p) => picked[p.id]).map((p) => p.id);
  return (
    <div className="mg-present">
      <label className="cs-check">
        <input type="checkbox" aria-label="Propose how each cinematic graphic is presented" checked={!!m.present} disabled={disabled}
          onChange={(e) => save({ present: e.target.checked || undefined })} />
        Propose how each graphic is presented
      </label>
      {m.present && (
        <>
          <p className="micro-note block">
            Full screen, over the footage, or partial beside it, read from each design, the shots under it and your production script's chapters and shot notes.
            Nothing changes until you apply; you can change any graphic afterwards in its Look.
          </p>
          {!cine.length && <p className="micro-note block">Add cinematic graphics first.</p>}
          {busy && !props && <p className="micro-note block">Reading the shots…</p>}
          {err && <p className="micro-note block mg-error">{err}</p>}
          {props && !changes.length && cine.length > 0 && <p className="micro-note block">Every graphic is already presented as proposed.</p>}
          {props && props.map((p) => (
            <div key={p.id} className={"mg-prop" + (p.same ? " same" : "")}>
              <div className="mg-prop-head">
                {!p.same && (
                  <input type="checkbox" aria-label={`Apply the proposal for ${p.label}`} checked={!!picked[p.id]} disabled={disabled || busy}
                    onChange={(e) => setPicked({ ...picked, [p.id]: e.target.checked })} />
                )}
                <button type="button" className="mg-prop-name" onClick={() => { onSelect(p.id); onSeek(p.start); }}>
                  {clock(p.start)} · {p.category}
                </button>
                <span className="mg-prop-mode">{p.same ? MODE[p.mode] : `${MODE[p.current] || p.current} → ${MODE[p.mode]}`}</span>
              </div>
              <ul className="mg-prop-why">{p.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </div>
          ))}
          {changes.length > 0 && (
            <div className="st-actions">
              <button className="btn" disabled={disabled || busy || !chosen.length} onClick={() => ask(chosen)}>
                <Check size={12} /> {busy ? "Applying…" : `Apply ${chosen.length} of ${changes.length}`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function MotionPanel({ project, time, playing, selectedId, onSelect, onChange, onSuggest, onDraft, onPresent, onSeek, onPlayFrom, disabled, previewStatus }) {
  const m = normaliseMotion(project.motion);
  const sel = m.items.find((x) => x.id === selectedId);
  const catalog = useCatalog();
  const [collection, setCollection] = React.useState("");
  const coll = (catalog?.collections || []).find((c) => c.key === (collection || catalog?.default)) || catalog?.collections?.[0];
  const images = (project.assets || []).filter((a) => a.kind === "image");
  const [busy, setBusy] = React.useState("");
  const [narration, setNarration] = React.useState(null);
  const [pick, setPick] = React.useState(null); // {template, from, to} while choosing a passage
  const [error, setError] = React.useState("");
  const save = (patch) => onChange({ ...m, ...patch });
  const setItems = (items) => save({ items });
  const update = (id, patch) => setItems(m.items.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const scenesKey = (project.scenes || []).map((s) => `${s.id}:${s.duration}:${(s.narration || "").length}`).join("|");
  // v0.4.53: what the selected graphic is drawn with (its layout once "Automatic" is resolved, the
  // layouts that look different for it, and whether its photo or footage still was found)
  const [info, setInfo] = React.useState(null);
  const selJson = sel ? JSON.stringify(sel) : "";
  const look = m.look || {};
  const lookJson = JSON.stringify(look);
  React.useEffect(() => {
    if (!sel) return setInfo(null);
    let live = true;
    planFor(project.id, sel, look).then((p) => live && setInfo({ id: sel.id, ...p })).catch(() => live && setInfo(null));
    return () => {
      live = false;
    };
  }, [project.id, selJson, sel?.template === "cinematic" ? lookJson : ""]);
  const layouts = sel && info && info.id === sel.id ? info.layouts || [] : [];
  const nextLayout = (it) => {
    const opts = info && info.id === it.id ? info.layouts || [] : [];
    if (opts.length < 2) return null;
    return opts[(opts.indexOf(info.layout) + 1) % opts.length];
  };

  React.useEffect(() => {
    if (!pick) return;
    let live = true;
    fetch(`/api/projects/${project.id}/motion/narration`, { credentials: "same-origin" })
      .then((r) => r.json())
      .then((d) => live && setNarration(d))
      .catch(() => live && setNarration({ sentences: [] }));
    return () => {
      live = false;
    };
  }, [!!pick, scenesKey]);

  const run = async (what, fn) => {
    setBusy(what);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy("");
    }
  };

  const sentences = narration?.sentences || [];
  const nowIndex = Math.max(0, sentences.findIndex((s) => s.end > time));
  const shown = sentences.slice(Math.max(0, nowIndex - 3), nowIndex + 12);

  const create = () =>
    run("draft", async () => {
      const a = sentences[Math.min(pick.from, pick.to)], b = sentences[Math.max(pick.from, pick.to)];
      const item = pick.template === "cinematic"
        ? await onDraft({ template: "cinematic", collection: coll?.key, category: pick.category || "auto", start: a.start, end: b.end })
        : await onDraft({ template: pick.template, start: a.start, end: b.end });
      setItems([...m.items, item]);
      onSelect(item.id);
      setPick(null);
      onSeek(item.start);
    });

  // v0.4.62 the same passage made again as another category (it says what the passage lacks if it cannot be)
  const remake = (it, category) =>
    run("regen", async () => {
      const fresh = await onDraft({ template: "cinematic", collection: it.collection, category, start: it.start, end: it.end, window: it.window, id: it.id });
      update(it.id, { ...fresh, id: it.id, status: "draft", source: it.source, reason: it.reason, hide_captions: it.hide_captions, look: it.look });
    });

  const regenerate = (it, template = it.template) =>
    run("regen", async () => {
      const fresh = await onDraft({ template, start: it.lines[0]?.at ?? it.start, end: Math.max(it.start + 1, it.end - MG.timing.hold), id: it.id });
      const keep = Object.fromEntries(["background", "photo_id", "still_at", "dim", "font", "size", "accent", "text_color", "align", "x", "y", "speed", "enter", "exit", "hide_captions"].map((k) => [k, it[k]]));
      const same = template === it.template && fresh.title === it.title && JSON.stringify(fresh.lines) === JSON.stringify(it.lines);
      // v0.4.53: the same words again: a different layout instead of the same graphic
      const layout = template !== it.template ? "auto" : same ? nextLayout(it) || it.layout : it.layout;
      update(it.id, { ...fresh, ...keep, layout, id: it.id, status: "draft", source: it.source, reason: it.reason, template });
    });

  return (
    <div className="inspector-content cs mg">
      <div className="section-label">
        <span>MOTION GRAPHICS</span>
      </div>
      <label className="cs-check">
        <input type="checkbox" aria-label="Add approved motion graphics to the export" checked={m.enabled} disabled={disabled} onChange={(e) => save({ enabled: e.target.checked })} />
        Add approved graphics to the export
      </label>
      <p className="micro-note block">
        Animated findings, timelines, conflicting accounts and legal outcomes, made from your narration's own words. Each line appears when the narrator says it.
        Nothing changes your scenes, narration or soundbites; remove a graphic and the picture is back.
      </p>
      <div className="st-actions">
        <button className="btn" disabled={disabled || !!busy} onClick={() => run("suggest", onSuggest)}>
          <Sparkles size={12} /> {busy === "suggest" ? "Reading the narration…" : "Suggest from the narration"}
        </button>
        <button className="btn" disabled={disabled || !!busy} onClick={() => setPick(pick ? null : { template: "findings", from: null, to: null })}>
          <Plus size={12} /> New from a passage
        </button>
      </div>
      <div className="section-label sub"><span>CINEMATIC (STORY-AWARE)</span></div>
      <p className="micro-note block">
        Premium graphics that read the whole story: {coll ? coll.categories.map((k) => k.label.toLowerCase()).join(", ") : "…"}. Placed only where the script supports one,
        each drawn in its own design from your script's own words, in sync with the narration.
      </p>
      {catalog && catalog.collections.length > 1 && (
        <Choice label="Kind of story" value={coll?.key || ""} options={catalog.collections.map((c) => [c.key, c.label])} disabled={disabled} onChange={setCollection} />
      )}
      <div className="st-actions">
        <button className="btn" disabled={disabled || !!busy || !coll} onClick={() => run("cine", () => onSuggest({ engine: "cinematic", collection: coll.key }))}>
          <Film size={12} /> {busy === "cine" ? "Reading the story…" : "Suggest cinematic graphics"}
        </button>
        <button className="btn" disabled={disabled || !!busy || !coll} onClick={() => setPick(pick ? null : { template: "cinematic", category: "auto", from: null, to: null })}>
          <Plus size={12} /> Cinematic from a passage
        </button>
      </div>
      {coll && (
        <ProjectLook project={project} look={look} coll={coll} catalog={catalog} images={images} disabled={disabled}
          onChange={(l) => save({ look: Object.keys(l).length ? l : undefined })} />
      )}
      {coll && onPresent && <AutoPresent m={m} save={save} onPresent={onPresent} onSeek={onSeek} onSelect={onSelect} disabled={disabled} />}
      {error && <p className="micro-note block mg-error">{error}</p>}

      {pick && (
        <div className="mg-pick">
          <Choice label="Template" value={pick.template} options={[...MG.templates.map((t) => [t.id, t.label]), ...(coll ? [["cinematic", "Cinematic (story-aware)"]] : [])]} disabled={disabled}
            onChange={(v) => setPick({ ...pick, template: v, category: "auto" })} />
          {pick.template === "cinematic" && coll && (
            <Choice label="Category" value={pick.category || "auto"} options={[["auto", "Automatic (what the passage supports)"], ...coll.categories.map((k) => [k.key, k.label])]} disabled={disabled}
              onChange={(v) => setPick({ ...pick, category: v })} />
          )}
          <p className="micro-note">Click the first and the last sentence of the passage{narration && !narration.exact ? " (times from the captions)" : ""}.</p>
          <div className="mg-sentences">
            {!narration && <p className="micro-note">Reading the narration…</p>}
            {narration && !sentences.length && <p className="micro-note">This project has no narration yet.</p>}
            {shown.map((s) => {
              const i = sentences.indexOf(s);
              const lo = Math.min(pick.from ?? -1, pick.to ?? pick.from ?? -1), hi = Math.max(pick.from ?? -1, pick.to ?? pick.from ?? -1);
              const on = pick.from !== null && i >= lo && i <= hi;
              return (
                <button key={i} className={`mg-sentence ${on ? "on" : ""} ${time >= s.start && time < s.end ? "now" : ""}`}
                  onClick={() => setPick(pick.from === null || pick.to !== null ? { ...pick, from: i, to: null } : { ...pick, to: i })}>
                  <small>{clock(s.start)}</small> {s.text}
                </button>
              );
            })}
          </div>
          <div className="st-actions">
            <button className="btn primary" disabled={disabled || pick.from === null || !!busy} onClick={create}>
              {busy === "draft" ? "Making…" : pick.template === "cinematic" ? "Make cinematic graphic" : `Make ${TEMPLATES[pick.template].label.toLowerCase()}`}
            </button>
            <button className="text-link" onClick={() => setPick(null)}>Cancel</button>
          </div>
        </div>
      )}

      {!m.items.length && !pick && (
        <p className="micro-note block">No graphics yet. “Suggest from the narration” reads the whole script and proposes a few where they help (none if nothing calls for one); or make one from a passage you choose.</p>
      )}
      <div className="st-list">
        {m.items.map((x) => (
          <button key={x.id} className={`st-item mg-item ${x.id === selectedId ? "on" : ""} ${time >= x.start && time < x.end ? "now" : ""}`}
            onClick={() => { onSelect(x.id); if (!(time >= x.start && time < x.end)) onSeek(x.start); }}>
            <i className={`mg-badge ${x.status}`}>{STATUS[x.status]}</i>
            <span>{itemName(catalog, x)}</span>
            <small>{kindName(catalog, x)} · {clock(x.start)} · {(x.end - x.start).toFixed(1)} s</small>
          </button>
        ))}
      </div>
      {m.items.some((x) => x.status === "approved") && !m.enabled && (
        <p className="micro-note block mg-warn">Approved graphics are not exported until “Add approved graphics to the export” is on.</p>
      )}

      {sel && sel.template === "cinematic" && (
        <CinematicEditor sel={sel} info={info} images={images} catalog={catalog} disabled={disabled} busy={busy} update={update} onPlayFrom={onPlayFrom}
          onRemove={() => { setItems(m.items.filter((x) => x.id !== sel.id)); onSelect(null); }} onRemake={remake} previewStatus={previewStatus} time={time} />
      )}
      {sel && sel.template !== "cinematic" && (
        <div className="st-edit">
          <div className="section-label sub">
            <span>{TEMPLATES[sel.template].label.toUpperCase()}</span>
            <small className={`mg-badge ${sel.status}`}>{STATUS[sel.status]}</small>
          </div>
          {sel.reason && <p className="micro-note block">Why here: {sel.reason}</p>}
          <div className="st-actions">
            <button className="btn" disabled={disabled} onClick={() => onPlayFrom(Math.max(0, sel.start - 0.5))}>
              <Play size={12} /> Play it
            </button>
            {sel.status !== "approved" ? (
              <button className="btn primary" disabled={disabled} onClick={() => update(sel.id, { status: "approved" })}>
                <Check size={12} /> Approve
              </button>
            ) : (
              <button className="btn" disabled={disabled} onClick={() => update(sel.id, { status: "draft" })}>
                Unapprove
              </button>
            )}
            <button className="btn" disabled={disabled || !!busy} title="Make it again from the narration (keeps the style; if the words are the same, it takes another layout)" onClick={() => regenerate(sel)}>
              <RotateCcw size={12} /> {busy === "regen" ? "…" : "Regenerate"}
            </button>
            <button className="btn" disabled={disabled || layouts.length < 2} title={layouts.length ? `Layouts for this graphic: ${layouts.map((l) => optionLabel(MG.layouts[sel.template], l)).join(", ")}` : "Preparing…"}
              onClick={() => update(sel.id, { layout: nextLayout(sel) })}>
              <Shuffle size={12} /> Another layout
            </button>
            <button className="btn danger" disabled={disabled} onClick={() => { setItems(m.items.filter((x) => x.id !== sel.id)); onSelect(null); }}>
              {sel.status === "suggested" ? <><X size={12} /> Reject</> : <><Trash2 size={12} /> Remove</>}
            </button>
          </div>
          {previewStatus === "preparing" && <p className="micro-note">Preparing the preview…</p>}

          <Choice label="Template" value={sel.template} options={MG.templates.map((t) => [t.id, t.label])} disabled={disabled || !!busy}
            onChange={(v) => regenerate(sel, v)} />
          <Choice label="Layout" value={sel.layout} options={MG.layouts[sel.template].map(([id, t]) => (id === "auto" && info?.id === sel.id && info.layout ? [id, `${t} (${optionLabel(MG.layouts[sel.template], info.layout).toLowerCase()})`] : [id, t]))}
            disabled={disabled} onChange={(v) => update(sel.id, { layout: v })} />

          <div className="section-label sub"><span>TEXT</span></div>
          <label className="field mg-field">
            Heading
            <input aria-label="Heading" key={sel.id + "h" + sel.heading} defaultValue={sel.heading} maxLength={MG.limits.heading} disabled={disabled}
              onBlur={(e) => e.target.value !== sel.heading && update(sel.id, { heading: e.target.value })} />
          </label>
          <label className="field mg-field">
            Title
            <input aria-label="Title" key={sel.id + "t" + sel.title} defaultValue={sel.title} maxLength={MG.limits.title} disabled={disabled}
              onBlur={(e) => e.target.value !== sel.title && update(sel.id, { title: e.target.value })} />
          </label>
          {sel.lines.map((l, i) => {
            const setLine = (patch) => update(sel.id, { lines: sel.lines.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
            return (
              <div key={i} className="mg-line">
                <div className="mg-line-head">
                  <b>{TEMPLATES[sel.template].line_label} {i + 1}</b>
                  <button className="text-link" disabled={disabled} title="Show this line from the playhead" onClick={() => setLine({ at: round3(Math.max(sel.start, Math.min(sel.end, time))) })}>
                    at {clock(l.at)} · set to playhead
                  </button>
                  <button className="icon-btn" aria-label={`Remove line ${i + 1}`} disabled={disabled} onClick={() => update(sel.id, { lines: sel.lines.filter((_, j) => j !== i) })}>
                    <Trash2 size={11} />
                  </button>
                </div>
                {(sel.template === "timeline" || sel.template === "legal" || sel.template === "contrast") && (
                  sel.template === "legal" ? (
                    <select aria-label={`Label ${i + 1}`} value={l.label} disabled={disabled} onChange={(e) => setLine({ label: e.target.value })}>
                      <option value="">No label</option>
                      {MG.legal_labels.map((x) => <option key={x} value={x}>{x}</option>)}
                    </select>
                  ) : (
                    <input aria-label={`Label ${i + 1}`} placeholder={sel.template === "timeline" ? "Date or time" : "Who said it (optional)"} key={sel.id + i + "l" + l.label}
                      defaultValue={l.label} maxLength={MG.limits.label} disabled={disabled} onBlur={(e) => e.target.value !== l.label && setLine({ label: e.target.value })} />
                  )
                )}
                {sel.template === "contrast" && (
                  <div className="mg-row">
                    <select aria-label={`Kind ${i + 1}`} value={l.kind || "statement"} disabled={disabled} onChange={(e) => setLine({ kind: e.target.value })}>
                      {MG.contrast_kinds.map(([id, t]) => <option key={id} value={id}>{t === "Statement" ? "What was said" : "What was found"}</option>)}
                    </select>
                    <label className="cs-check"><input type="checkbox" checked={l.emphasis} disabled={disabled} onChange={(e) => setLine({ emphasis: e.target.checked })} /> Emphasise</label>
                  </div>
                )}
                <textarea aria-label={`Line ${i + 1}`} rows={2} key={sel.id + i + "x" + l.text} defaultValue={l.text} maxLength={MG.limits.text} disabled={disabled}
                  onBlur={(e) => e.target.value.trim() && e.target.value !== l.text && setLine({ text: e.target.value })} />
              </div>
            );
          })}
          {sel.lines.length < TEMPLATES[sel.template].max_lines && (
            <button className="text-link" disabled={disabled}
              onClick={() => update(sel.id, { lines: [...sel.lines, { text: "New line", label: "", kind: "finding", emphasis: false, at: round3(Math.max(sel.start, Math.min(sel.end - 1, time))) }] })}>
              + Add a line at the playhead
            </button>
          )}

          <div className="section-label sub"><span>TIMING</span></div>
          <Step label="Starts at" value={sel.start} display={clock(sel.start)} typed={parseClock} step={0.1} min={0} max={86400} disabled={disabled}
            onChange={(x) => { const d = x - sel.start; update(sel.id, { start: x, end: sel.end + d, lines: sel.lines.map((l) => ({ ...l, at: round3(l.at + d) })) }); }} />
          <Step label="Ends at" value={sel.end} display={clock(sel.end)} typed={parseClock} step={0.5} min={sel.start + MG.limits.length[0]} max={sel.start + MG.limits.length[1]} disabled={disabled}
            onChange={(x) => update(sel.id, { end: x })} />
          <Step label="Animation speed" value={sel.speed} display={`${sel.speed.toFixed(2)}×`} step={0.25} min={MG.limits.speed[0]} max={MG.limits.speed[1]} disabled={disabled} onChange={(x) => update(sel.id, { speed: x })} />
          <Choice label="Entrance" value={sel.enter} options={MG.enters} disabled={disabled} onChange={(v) => update(sel.id, { enter: v })} />
          <Choice label="Exit" value={sel.exit} options={MG.exits} disabled={disabled} onChange={(v) => update(sel.id, { exit: v })} />
          <label className="cs-check">
            <input type="checkbox" checked={sel.hide_captions} disabled={disabled} onChange={(e) => update(sel.id, { hide_captions: e.target.checked })} />
            Hide captions while it is on screen
          </label>

          <div className="section-label sub"><span>LOOK</span></div>
          <Choice label="Background" value={sel.background} options={MG.backgrounds.filter(([id]) => id !== "photo" || images.length)} disabled={disabled}
            onChange={(v) => update(sel.id, { background: v, photo_id: v === "photo" ? sel.photo_id || images[0]?.id || "" : "", still_at: v === "still" ? sel.start : sel.still_at })} />
          {sel.background === "photo" && (
            <Choice label="Photo (from your project)" value={sel.photo_id} options={images.map((a) => [a.id, a.name])} disabled={disabled} onChange={(v) => update(sel.id, { photo_id: v })} />
          )}
          {sel.background === "still" && (
            <div className="mg-still">
              <Step label="Still from" value={sel.still_at} display={clock(sel.still_at)} typed={parseClock} step={0.5} min={0} max={86400} disabled={disabled}
                onChange={(x) => update(sel.id, { still_at: round3(x) })} />
              <button className="text-link" disabled={disabled} title="The footage on the timeline at the playhead" onClick={() => update(sel.id, { still_at: round3(time) })}>set to playhead</button>
              <p className="micro-note">The frame of your own footage that plays on the timeline at that moment, blurred and darkened.</p>
            </div>
          )}
          {(sel.background === "still" || sel.background === "photo") && info?.id === sel.id && info.background === "charcoal" && (
            <p className="micro-note block mg-warn">{sel.background === "still" ? "No footage plays at that moment (a gap, a card or a missing file)" : "That photo's file is missing"}: the charcoal is used. Nothing is made up.</p>
          )}
          {sel.background !== "charcoal" && (
            <Step label="Darken" value={sel.dim} display={pct(sel.dim)} step={0.05} min={MG.limits.dim[0]} max={MG.limits.dim[1]} disabled={disabled} onChange={(x) => update(sel.id, { dim: x })} />
          )}
          <Choice label="Font" value={sel.font} options={MG.fonts} disabled={disabled} onChange={(v) => update(sel.id, { font: v })} />
          <Step label="Text size" value={sel.size} display={pct(sel.size)} step={0.05} min={MG.limits.size[0]} max={MG.limits.size[1]} disabled={disabled} onChange={(x) => update(sel.id, { size: x })} />
          <Swatches label="Accent" value={sel.accent} options={MG.accents} disabled={disabled} onChange={(c) => update(sel.id, { accent: c })} />
          <Swatches label="Text" value={sel.text_color} options={MG.text_colors} disabled={disabled} onChange={(c) => update(sel.id, { text_color: c })} />
          <Choice label="Align" value={sel.align} options={[["left", "Left"], ["center", "Centre"]]} disabled={disabled} onChange={(v) => update(sel.id, { align: v })} />
          <Step label="Left ↔ right" value={sel.x} display={pct(sel.x)} step={0.01} min={MG.limits.xy[0]} max={MG.limits.xy[1]} disabled={disabled} onChange={(x) => update(sel.id, { x })} />
          <Step label="Up ↕ down" value={sel.y} display={pct(sel.y)} step={0.01} min={MG.limits.xy[0]} max={MG.limits.xy[1]} disabled={disabled} onChange={(y) => update(sel.id, { y })} />
        </div>
      )}
    </div>
  );
}

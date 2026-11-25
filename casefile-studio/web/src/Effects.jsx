import React from "react";
import { TRANSITIONS, MOTIONS, LOOKS, normaliseEffects, transitionId, transitionLength, normaliseNameCards } from "./effects.js";
import { normaliseCta } from "./cta.js";
import { PIC, fitOf, normaliseKeyframes, cameraAt, upsertKey, cropOf } from "./picture.js";
import { normaliseWatermark, watermarkBox, WM_POSITIONS, WM_DEFAULTS } from "./watermark.js";

// v0.4.26 Effects tab in the Edit inspector: the look of the whole video
// (colour grade, grain, vignette, letterbox) and, for the selected scene, the
// transition into it, photo movement and a lower-third name card.

function Pct({ label, value, onChange, disabled }) {
  return (
    <label className="cs-slider">
      <span>
        {label} <b>{Math.round(value * 100)}%</b>
      </span>
      <input type="range" aria-label={label} min="0" max="100" value={Math.round(value * 100)} disabled={disabled} onChange={(e) => onChange(Number(e.target.value) / 100)} />
    </label>
  );
}

// v0.4.49 A value with − / + buttons (and a typed value), like the Shot Inspector.
export function Step({ label, value, display, step, min, max, onChange, disabled, typed }) {
  const clamp = (v) => Math.min(max, Math.max(min, Math.round(v * 1000) / 1000));
  return (
    <div className="cs-step">
      <span>{label}</span>
      <button aria-label={`${label} less`} disabled={disabled || value <= min} onClick={() => onChange(clamp(value - step))}>−</button>
      {typed ? (
        <input aria-label={label} key={value} defaultValue={display} disabled={disabled}
          onBlur={(e) => { const v = typed(e.target.value); if (v !== null && Number.isFinite(v)) onChange(clamp(v)); }}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()} />
      ) : (
        <b>{display}</b>
      )}
      <button aria-label={`${label} more`} disabled={disabled || value >= max} onClick={() => onChange(clamp(value + step))}>+</button>
    </div>
  );
}

export const clock = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}`;
const pct = (v) => `${Math.round(v * 100)}%`;
// "1:02.5", "62.5" or "0:57.220" → seconds
export function parseClock(s) {
  const m = String(s).trim().match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  return m ? Number(m[1] || 0) * 60 + Number(m[2]) : null;
}

// v0.4.49 Every place the subscribe animation shows: tick it on or off, nudge
// its start, cut it shorter (it fades out), or stop it at the end of its scene.
function CtaPlaces({ cta, spots, natural, playhead, disabled, setCta, onPlay }) {
  const [open, setOpen] = React.useState(null);
  const setSpot = (r, patch) => {
    if (r.auto) setCta({ spots: { ...cta.spots, [r.key]: { ...r.spot, ...patch } } });
    else setCta({ extra: cta.extra.map((e) => (e.id === r.key ? { ...e, ...patch } : e)) });
  };
  const shown = spots.filter((r) => r.shown);
  const add = () => {
    let n = cta.extra.length + 1;
    while (cta.extra.some((e) => e.id === `x${n}`)) n++;
    setCta({ extra: [...cta.extra, { id: `x${n}`, start: Math.round(playhead * 1000) / 1000, on: true, nudge: 0, length: null, scene_end: false }] });
    setOpen(`x${n}`);
  };
  return (
    <>
      <div className="section-label sub">
        <span>WHERE IT SHOWS</span>
      </div>
      <p className="cta-shows">
        {shown.length ? `Shows at ${clock(shown[0].start)}${shown.length > 1 ? ` +${shown.length - 1}` : ""}` : "Not showing anywhere yet"}
      </p>
      <div className="cta-places">
        {spots.map((r) => {
          const len = r.end - r.start;
          const expanded = open === r.key;
          return (
            <div key={r.key} className={`cta-place ${r.shown ? "on" : ""}`}>
              <div className="cta-place-row">
                <input type="checkbox" aria-label={`Show at ${clock(r.start)}`} checked={r.on} disabled={disabled} onChange={(e) => setSpot(r, { on: e.target.checked })} />
                <button className="cta-place-time" onClick={() => onPlay(r.start)} title="Play it in the preview">
                  {clock(r.start)}
                </button>
                <span className="cta-place-what">
                  {r.auto ? r.label : "Added by you"} · {len.toFixed(1)} s{r.fade_out ? " · fades out" : ""}
                  {r.on && !r.shown ? " · overlaps the one before" : ""}
                </span>
                <button className="text-link" onClick={() => setOpen(expanded ? null : r.key)}>{expanded ? "Less" : "More"}</button>
              </div>
              {expanded && (
                <div className="cta-place-more">
                  {r.auto ? (
                    <Step label="Start" value={r.spot.nudge} display={`${r.spot.nudge >= 0 ? "+" : ""}${r.spot.nudge.toFixed(1)} s`} step={0.1} min={-30} max={30} disabled={disabled}
                      onChange={(v) => setSpot(r, { nudge: v })} />
                  ) : (
                    <Step label="Start" value={r.start} display={clock(r.start)} step={0.1} min={0} max={86400} disabled={disabled}
                      typed={parseClock} onChange={(v) => setSpot(r, { start: v })} />
                  )}
                  <Step label="Length" value={r.spot.length || natural} display={r.spot.length && r.spot.length < natural ? `${r.spot.length.toFixed(1)} s` : `full ${natural.toFixed(1)} s`}
                    step={0.5} min={0.5} max={natural} disabled={disabled}
                    onChange={(v) => setSpot(r, { length: v >= natural - 1e-3 ? null : v })} />
                  <label className="cs-check">
                    <input type="checkbox" aria-label="Stop at the end of this scene" checked={r.spot.scene_end} disabled={disabled} onChange={(e) => setSpot(r, { scene_end: e.target.checked })} />
                    Stop at the end of this scene
                  </label>
                  <div className="cta-place-actions">
                    <button className="btn" onClick={() => onPlay(Math.max(0, r.start - 1))}>Play from here</button>
                    {r.auto ? (
                      <button className="text-link" disabled={disabled} onClick={() => { const { [r.key]: _, ...rest } = cta.spots; setCta({ spots: rest }); }}>Reset</button>
                    ) : (
                      <button className="danger-link" disabled={disabled} onClick={() => setCta({ extra: cta.extra.filter((e) => e.id !== r.key) })}>Remove</button>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <button className="btn" disabled={disabled} onClick={add}>+ Add one at the playhead ({clock(playhead)})</button>
      <p className="micro-note block">
        CASEFILE lists every scene that says “subscribe”. When one is cut short (by its length, the end of its scene or the next one) it fades out instead of stopping.
        Captions stay on top. Download MP4 includes it.
      </p>
    </>
  );
}

// v0.4.49 Your own push-in / pan: keyframes of zoom and position for this scene.
function PictureKeys({ scene, local, disabled, onScene, onSeek, sceneStart }) {
  const keys = normaliseKeyframes(scene.keyframes, scene.duration);
  const cam = cameraAt(keys, local);
  const at = keys.find((k) => Math.abs(k.t - local) < 0.05);
  const set = (patch) => onScene({ keyframes: upsertKey(keys, local, { ...cam, ...(at ? { ease: at.ease } : {}), ...patch }, (k) => normaliseKeyframes(k, scene.duration)) });
  return (
    <>
      <div className="section-label sub">
        <span>KEYFRAMES · YOUR OWN MOVEMENT</span>
      </div>
      {!keys.length ? (
        <p className="micro-note block">Put the playhead where a move starts, click “Add keyframe”, then move the playhead and change zoom or position. The picture moves between your keyframes instead of the movement above.</p>
      ) : (
        <p className="micro-note block">At {local.toFixed(2)} s into this scene{at ? " (on a keyframe)" : ""}. Changing a value here {at ? "changes this keyframe" : "adds a keyframe here"}.</p>
      )}
      {keys.length > 0 && (
        <>
          <Step label="Zoom" value={cam.zoom} display={`${Math.round(cam.zoom * 100)}%`} step={0.05} min={1} max={4} disabled={disabled} onChange={(v) => set({ zoom: v })} />
          <Step label="Left ↔ right" value={cam.x} display={pct(cam.x)} step={0.02} min={0} max={1} disabled={disabled} onChange={(v) => set({ x: v })} />
          <Step label="Up ↕ down" value={cam.y} display={pct(cam.y)} step={0.02} min={0} max={1} disabled={disabled} onChange={(v) => set({ y: v })} />
        </>
      )}
      <div className="kf-list">
        {keys.map((k, i) => (
          <div key={k.t} className={`kf-item ${at === k ? "on" : ""}`}>
            <button className="kf-time" onClick={() => onSeek(sceneStart + k.t + 0.001)}>◆ {k.t.toFixed(2)} s</button>
            <span>{Math.round(k.zoom * 100)}% · {pct(k.x)}, {pct(k.y)}</span>
            {i < keys.length - 1 && (
              <button className="text-link" disabled={disabled} title="How it moves to the next keyframe"
                onClick={() => onScene({ keyframes: keys.map((x) => (x === k ? { ...x, ease: x.ease === "linear" ? "smooth" : "linear" } : x)) })}>
                {k.ease === "linear" ? "Steady" : "Smooth"}
              </button>
            )}
            <button className="danger-link" aria-label={`Remove keyframe at ${k.t.toFixed(2)} s`} disabled={disabled} onClick={() => onScene({ keyframes: keys.filter((x) => x !== k) })}>×</button>
          </div>
        ))}
      </div>
      <div className="kf-actions">
        <button className="btn" disabled={disabled || !!at} onClick={() => set({})}>◆ Add keyframe ({local.toFixed(2)} s)</button>
        {keys.length > 0 && <button className="text-link" disabled={disabled} onClick={() => onScene({ keyframes: [] })}>Clear keyframes</button>}
      </div>
    </>
  );
}

function NameCards({ project, api, disabled, onProject }) {
  const nc = normaliseNameCards(project.name_cards);
  const [info, setInfo] = React.useState(null);
  const [newId, setNewId] = React.useState("");
  const load = () => api(`/api/projects/${project.id}/name-cards`).then(setInfo).catch(() => {});
  React.useEffect(() => {
    if (nc.auto) load();
  }, [project.id, nc.auto]);
  const save = (next) => onProject({ name_cards: next });
  const turnOn = async (on) => {
    if (!on) return save({ ...nc, auto: false });
    save({ ...nc, auto: true }); // ticks at once; the names follow
    let i = info;
    try {
      i = await api(`/api/projects/${project.id}/name-cards`);
      setInfo(i);
    } catch (e) {
      /* fill in by hand */
    }
    const people = { ...nc.people };
    for (const [sid, p] of Object.entries(i?.suggested || {})) if (!people[sid]) people[sid] = { name: p.name, role: p.role, on: true };
    save({ auto: true, people });
  };
  const setPerson = (sid, patch) => save({ ...nc, people: { ...nc.people, [sid]: { ...(nc.people[sid] || { name: "", role: "", on: true }), ...patch } } });
  const used = new Set((info?.used || []).map((u) => u.id));
  const titles = Object.fromEntries((info?.used || []).map((u) => [u.id, u.title]));
  const extra = (info?.used || []).filter((u) => !nc.people[u.id]);
  return (
    <>
      <div className="section-label">
        <span>NAME CARDS FROM THE GUIDE</span>
      </div>
      <label className="cs-check">
        <input type="checkbox" aria-label="Fill in name cards automatically" checked={nc.auto} disabled={disabled} onChange={(e) => turnOn(e.target.checked)} />
        Fill in name cards automatically
      </label>
      <p className="micro-note block">
        Optional. The first scene that shows each person’s clip gets their name card. Names come from the re-cut list’s “Who” column; check and edit them here. A name card you type on a scene always wins.
      </p>
      {nc.auto && (
        <div className="nc-people">
          {Object.entries(nc.people).map(([sid, p]) => (
            <div key={sid} className={`nc-row ${p.on ? "" : "off"}`}>
              <label className="nc-on" title={titles[sid] || ""}>
                <input type="checkbox" aria-label={`Name card for ${sid}`} checked={p.on} disabled={disabled} onChange={(e) => setPerson(sid, { on: e.target.checked })} />
                <code>{sid}</code>
                {!used.has(sid) && info && <small>not in this edit</small>}
              </label>
              <input aria-label={`${sid} name`} value={p.name} placeholder="Name" disabled={disabled} onChange={(e) => setPerson(sid, { name: e.target.value })} />
              <input aria-label={`${sid} role`} value={p.role} placeholder="Who they are" disabled={disabled} onChange={(e) => setPerson(sid, { role: e.target.value })} />
            </div>
          ))}
          {Object.keys(nc.people).length === 0 && <p className="micro-note block">No names in the re-cut list yet. Add a person below.</p>}
          {extra.length > 0 && (
            <div className="nc-add">
              <select aria-label="Add a person for clip" value={newId} disabled={disabled} onChange={(e) => setNewId(e.target.value)}>
                <option value="">Add a person for a clip…</option>
                {extra.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.id}
                    {u.title ? ` · ${u.title.slice(0, 50)}` : ""}
                  </option>
                ))}
              </select>
              <button className="btn" disabled={disabled || !newId} onClick={() => { setPerson(newId, { name: "Name", role: "" }); setNewId(""); }}>
                Add
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

const WM_LABELS = {
  "top-left": "Top left",
  "top-center": "Top middle",
  "top-right": "Top right",
  "middle-left": "Middle left",
  center: "Centre",
  "middle-right": "Middle right",
  "bottom-left": "Bottom left",
  "bottom-center": "Bottom middle",
  "bottom-right": "Bottom right",
};

// v0.4.36 Your logo in a corner, the middle of an edge, or the centre.
function Watermark({ project, thumb, disabled, onProject, onUploadLogo }) {
  const wm = normaliseWatermark(project.watermark);
  const set = (patch) => onProject({ watermark: { ...wm, ...patch } });
  const images = (project.assets || []).filter((a) => a.kind === "image");
  const logo = images.find((a) => a.id === wm.asset_id);
  const ref = React.useRef(null);
  const tall = project.aspect === "9:16";
  const fw = tall ? 90 : 160;
  const fh = tall ? 160 : 90;
  const box = logo ? watermarkBox(fw, fh, logo.width || 1, logo.height || 1, wm.position, wm.size) : null;
  const isDefault = wm.position === WM_DEFAULTS.position && wm.size === WM_DEFAULTS.size && wm.opacity === WM_DEFAULTS.opacity;
  return (
    <>
      <div className="section-label">
        <span>LOGO WATERMARK</span>
      </div>
      <label className="cs-check">
        <input type="checkbox" aria-label="Show my logo watermark" checked={wm.enabled} disabled={disabled} onChange={(e) => set({ enabled: e.target.checked })} />
        Show my logo on the whole video
      </label>
      {wm.enabled && (
        <>
          <div className="fx-cta-banner">
            <div className="fx-wm-logo" style={{ backgroundImage: logo ? `url("${logo.url}")` : undefined }} />
            <div>
              <p className={logo ? "fx-cta-ok" : ""}>
                {logo ? `Using ${logo.name}. A PNG with a transparent background looks best.` : "Upload your logo (PNG with a transparent background is best)."}
              </p>
              <button className="btn" disabled={disabled} onClick={() => ref.current?.click()}>
                Upload logo
              </button>
              <input ref={ref} type="file" accept="image/png,image/webp,image/jpeg" hidden
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onUploadLogo(f); }} />
            </div>
          </div>
          {images.length > 1 && (
            <label className="field">
              Logo
              <select aria-label="Logo image" value={wm.asset_id || ""} disabled={disabled} onChange={(e) => set({ asset_id: e.target.value || null })}>
                <option value="">Choose an image</option>
                {images.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="fx-wm-row">
            <div className="fx-wm-grid" role="group" aria-label="Where the logo goes" style={{ width: fw, height: fh, backgroundImage: thumb ? `url("${thumb}")` : undefined }}>
              {WM_POSITIONS.map((pos) => (
                <button key={pos} aria-label={WM_LABELS[pos]} title={WM_LABELS[pos]} aria-pressed={wm.position === pos} disabled={disabled} onClick={() => set({ position: pos })} />
              ))}
              {box && <img alt="" src={logo.url} style={{ left: box.x, top: box.y, width: box.w, height: box.h, opacity: wm.opacity }} />}
            </div>
            <div className="fx-wm-where">
              <b>{WM_LABELS[wm.position]}</b>
              <small>Tap a spot on the frame.</small>
              <button className="btn" disabled={disabled || isDefault} onClick={() => set({ position: WM_DEFAULTS.position, size: WM_DEFAULTS.size, opacity: WM_DEFAULTS.opacity })}>
                YouTube default
              </button>
            </div>
          </div>
          <label className="cs-slider">
            <span>
              Logo size <b>{Math.round(wm.size * 1080)} px at 1080p</b>
            </span>
            <input type="range" aria-label="Logo size" min="5" max="40" value={Math.round(wm.size * 100)} disabled={disabled} onChange={(e) => set({ size: Number(e.target.value) / 100 })} />
          </label>
          <Pct label="Logo opacity" value={wm.opacity} disabled={disabled} onChange={(v) => set({ opacity: Math.max(0.2, v) })} />
          <p className="micro-note block">
            YouTube default: bottom right, 150 px wide at 1080p. Captions and name cards stay on top of the logo. Re-cut clips get it too.
          </p>
        </>
      )}
    </>
  );
}

export default function Effects({ project, scene, sceneIndex, thumb, disabled, onProject, onScene, onUploadBanner, onUploadLogo, ctaEvents = [], ctaSpots = [], ctaNatural = 5, playhead = 0, sceneStart = 0, onSeek, onCrop, onPlayCta, api, autoCard }) {
  const fx = normaliseEffects(project.effects);
  const cta = normaliseCta(project.cta);
  const sceneAsset = (project.assets || []).find((a) => a.id === scene?.asset_id && (a.kind === "image" || a.kind === "video"));
  const setCta = (patch) => onProject({ cta: { ...cta, ...patch } });
  const images = (project.assets || []).filter((a) => a.kind === "image");
  const banner = images.find((a) => a.id === cta.asset_id);
  const bannerRef = React.useRef(null);
  const animRef = React.useRef(null);
  const videos = (project.assets || []).filter((a) => a.kind === "video");
  const animFile = videos.find((a) => a.id === cta.file_id);
  const ownFile = cta.source === "file";
  const setFx = (patch) => onProject({ effects: { ...fx, ...patch } });
  const trans = transitionId(scene?.transition);
  const length = scene ? transitionLength(scene, scene.duration) : 0;
  const lower = scene?.lower_third || { name: "", role: "" };
  const setLower = (patch) => {
    const next = { ...lower, ...patch };
    onScene({ lower_third: next.name || next.role ? next : null });
  };
  return (
    <div className="inspector-content cs fx">
      <div className="section-label">
        <span>LOOK OF THE WHOLE VIDEO</span>
      </div>
      <div className="fx-looks">
        {LOOKS.map((l) => (
          <button
            key={l.id}
            className={`fx-look ${project.look === l.id ? "selected" : ""}`}
            aria-label={`Look ${l.label}`}
            aria-pressed={project.look === l.id}
            disabled={disabled}
            onClick={() => onProject({ look: l.id })}
          >
            <div className="fx-look-img" style={{ backgroundImage: thumb ? `url("${thumb}")` : undefined, filter: l.css }}>
              {l.tint && <i style={{ background: l.tint }} />}
            </div>
            <span>{l.label}</span>
          </button>
        ))}
      </div>
      <Pct label="Film grain" value={fx.grain} disabled={disabled} onChange={(v) => setFx({ grain: v })} />
      <Pct label="Vignette" value={fx.vignette} disabled={disabled} onChange={(v) => setFx({ vignette: v })} />
      <label className="cs-check">
        <input type="checkbox" aria-label="Cinema bars" checked={fx.letterbox} disabled={disabled} onChange={(e) => setFx({ letterbox: e.target.checked })} />
        Cinema bars (2.35:1 letterbox)
      </label>

      <Watermark project={project} thumb={thumb} disabled={disabled} onProject={onProject} onUploadLogo={onUploadLogo || ((f) => onUploadBanner(f, "logo"))} />

      {api && <NameCards project={project} api={api} disabled={disabled} onProject={onProject} />}

      <div className="section-label">
        <span>SUBSCRIBE ANIMATION</span>
      </div>
      <label className="cs-check">
        <input type="checkbox" aria-label="Show the subscribe animation" checked={cta.enabled} disabled={disabled} onChange={(e) => setCta({ enabled: e.target.checked })} />
        Show the subscribe animation
      </label>
      {cta.enabled && (
        <>
          <div className="fx-seg" role="group" aria-label="What to show">
            <button aria-pressed={!ownFile} disabled={disabled} onClick={() => setCta({ source: "casefile" })}>
              Casefile animates my banner
            </button>
            <button aria-pressed={ownFile} disabled={disabled} onClick={() => setCta({ source: "file" })}>
              My own animation file
            </button>
          </div>
          {ownFile && (
            <div className="fx-cta-banner">
              <div className="fx-cta-thumb" style={{ backgroundImage: animFile?.thumbnail ? `url("${animFile.thumbnail}")` : undefined }} />
              <div>
                <p className={animFile ? "fx-cta-ok" : ""}>
                  {animFile
                    ? `Using ${animFile.name} (${Math.min(15, Math.max(1, Number(animFile.duration) || 5)).toFixed(1)} s). Transparent parts show the video behind.`
                    : "Upload a .MOV (ProRes 4444) or .WebM with a transparent background, or a GIF."}
                </p>
                <button className="btn" disabled={disabled} onClick={() => animRef.current?.click()}>
                  Upload animation
                </button>
                <input ref={animRef} type="file" accept=".mov,.webm,.gif,video/quicktime,video/webm,image/gif" hidden
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onUploadBanner(f, true); }} />
              </div>
            </div>
          )}
          {ownFile && videos.length > 0 && (
            <label className="field">
              Animation
              <select aria-label="Subscribe animation file" value={cta.file_id || ""} disabled={disabled} onChange={(e) => setCta({ file_id: e.target.value || null })}>
                <option value="">Choose a file</option>
                {videos.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!ownFile && (<>
          <div className="fx-cta-banner">
            <div className="fx-cta-thumb" style={{ backgroundImage: banner ? `url("${banner.thumbnail || banner.url}")` : undefined }}>
              {banner && cta.button && (
                <i style={{ left: `${cta.button[0] * 100}%`, top: `${cta.button[1] * 100}%`, width: `${(cta.button[2] - cta.button[0]) * 100}%`, height: `${(cta.button[3] - cta.button[1]) * 100}%` }} />
              )}
            </div>
            <div>
              <p className={banner && cta.button ? "fx-cta-ok" : ""}>
                {!banner
                  ? "Choose your channel banner (an image with a SUBSCRIBE button on it)."
                  : cta.button
                    ? "Found the SUBSCRIBE button on your banner (green box). The cursor clicks it."
                    : "No red SUBSCRIBE button found on this banner, so Casefile draws one."}
              </p>
              <button className="btn" disabled={disabled} onClick={() => bannerRef.current?.click()}>
                Upload banner
              </button>
              <input ref={bannerRef} type="file" accept="image/png,image/jpeg,image/webp" hidden
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onUploadBanner(f); }} />
            </div>
          </div>
          {images.length > 0 && (
            <label className="field">
              Banner
              <select aria-label="Subscribe banner" value={cta.asset_id || ""} disabled={disabled} onChange={(e) => setCta({ asset_id: e.target.value || null })}>
                <option value="">Choose an image</option>
                {images.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          </>)}
          <div className="section-label sub">
            <span>BEHIND IT</span>
          </div>
          <div className="fx-seg" role="group" aria-label="Background behind the subscribe animation">
            <button aria-pressed={cta.style === "overlay"} disabled={disabled} onClick={() => setCta({ style: "overlay" })}>
              {ownFile ? "Video as it is" : "See-through banner"}
            </button>
            <button aria-pressed={cta.style === "blur"} disabled={disabled} onClick={() => setCta({ style: "blur" })}>
              Blur the video behind
            </button>
          </div>
          {!ownFile && cta.style === "overlay" && (
            <Pct label="Banner opacity" value={cta.opacity} disabled={disabled} onChange={(v) => setCta({ opacity: Math.max(0.15, v) })} />
          )}
          {(ownFile || cta.style === "blur") && (
            <>
              <Step label="Size" value={cta.size} display={pct(cta.size)} step={0.05} min={0.25} max={1} disabled={disabled} onChange={(v) => setCta({ size: v })} />
              <Step label="Left ↔ right" value={cta.x} display={pct(cta.x)} step={0.05} min={0.1} max={0.9} disabled={disabled} onChange={(v) => setCta({ x: v })} />
              <Step label="Up ↕ down" value={cta.y} display={pct(cta.y)} step={0.05} min={0.15} max={0.85} disabled={disabled} onChange={(v) => setCta({ y: v })} />
            </>
          )}
          {!ownFile && (
            <label className="cs-slider">
              <span>
                Length <b>{cta.seconds.toFixed(1)} s</b>
              </span>
              <input type="range" aria-label="Subscribe animation length" min="30" max="80" value={Math.round(cta.seconds * 10)} disabled={disabled} onChange={(e) => setCta({ seconds: Number(e.target.value) / 10 })} />
            </label>
          )}
          {(ownFile ? animFile : banner) ? (
            <CtaPlaces cta={cta} spots={ctaSpots} natural={ctaNatural} playhead={playhead} disabled={disabled} setCta={setCta} onPlay={onPlayCta} />
          ) : (
            <p className="micro-note block">{ownFile ? "Upload or choose your animation file first." : "Choose your banner first."}</p>
          )}
        </>
      )}

      {scene ? (
        <>
          <div className="section-label">
            <span>SCENE {String(sceneIndex + 1).padStart(2, "0")} · TRANSITION IN</span>
          </div>
          {sceneIndex === 0 && <p className="micro-note block">The first scene has nothing before it; “Fade in and out” still works here.</p>}
          <div className="fx-trans">
            {TRANSITIONS.map((t) => (
              <button
                key={t.id}
                className={`fx-tr ${trans === t.id ? "selected" : ""}`}
                aria-label={`Transition ${t.label}`}
                aria-pressed={trans === t.id}
                disabled={disabled}
                onClick={() => onScene({ transition: t.id, transition_duration: t.id === "none" ? 0 : scene.transition_duration || 0.5 })}
              >
                <i className={`fx-tr-icon tr-${t.id}`} />
                {t.label}
              </button>
            ))}
          </div>
          {trans !== "none" && (
            <label className="cs-slider">
              <span>
                Transition length <b>{length.toFixed(1)} s</b>
              </span>
              <input
                type="range"
                aria-label="Transition length"
                min="2"
                max="20"
                value={Math.round((scene.transition_duration || 0.5) * 10)}
                disabled={disabled}
                onChange={(e) => onScene({ transition_duration: Number(e.target.value) / 10 })}
              />
            </label>
          )}
          <p className="micro-note block">Transitions blend into the scene and never move it, so the narration stays in sync.</p>

          <div className="section-label">
            <span>PICTURE · CROP, FILL AND MOVEMENT</span>
          </div>
          {sceneAsset ? (
            <>
              <div className="fx-crop-row">
                <span>{cropOf(sceneAsset) ? "Cropped" : "Whole picture"} · {sceneAsset.name}</span>
                <button className="btn" disabled={disabled} onClick={() => onCrop?.(sceneAsset.id)}>Adjust crop…</button>
              </div>
              <label className="field">
                Fill the frame
                <select aria-label="How the picture fills the frame" value={scene.fit || ""} disabled={disabled} onChange={(e) => onScene({ fit: e.target.value || null })}>
                  <option value="">{{ "legacy-blur": "Default (blurred background, 9:16)", blur: "Default (cropped: photo over a blur)" }[fitOf(project, { ...scene, fit: null }, sceneAsset)] || "Default (fill the frame)"}</option>
                  {PIC.fits.map((f) => (
                    <option key={f.id} value={f.id}>{f.label}</option>
                  ))}
                </select>
              </label>
            </>
          ) : (
            <p className="micro-note block">Add a picture or clip to this scene to crop it.</p>
          )}
          <label className="field">
            Movement
            <select aria-label="Photo movement" value={scene.motion || "slow-zoom"} disabled={disabled || !!scene.keyframes?.length} onChange={(e) => onScene({ motion: e.target.value })}>
              {MOTIONS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <p className="micro-note block">{scene.keyframes?.length ? "Your keyframes below move the picture instead." : "Movement applies to photos; video plays as filmed (keyframes below move clips too)."}</p>
          {sceneAsset && <PictureKeys scene={scene} local={Math.max(0, Math.min(scene.duration, playhead - sceneStart))} sceneStart={sceneStart} disabled={disabled} onScene={onScene} onSeek={onSeek} />}

          <div className="section-label">
            <span>NAME CARD (LOWER THIRD)</span>
          </div>
          <label className="field">
            Name
            <input aria-label="Name card name" placeholder="e.g. Dedrick Hilton" value={lower.name || ""} maxLength={80} disabled={disabled} onChange={(e) => setLower({ name: e.target.value })} />
          </label>
          <label className="field">
            Who they are
            <input aria-label="Name card role" placeholder="e.g. Jaela’s father" value={lower.role || ""} maxLength={100} disabled={disabled} onChange={(e) => setLower({ role: e.target.value })} />
          </label>
          <p className="micro-note block">
            {autoCard?.auto && !(lower.name || lower.role)
              ? `Automatic name card on this scene: ${[autoCard.name, autoCard.role].filter(Boolean).join(", ")}. Type here to replace it.`
              : "Shows for the first 5 seconds of this scene, above any footage label."}
          </p>
        </>
      ) : (
        <p className="micro-note block">Select a scene for its transition, movement and name card.</p>
      )}
    </div>
  );
}

import React from "react";
import { TRANSITIONS, MOTIONS, LOOKS, normaliseEffects, transitionId, transitionLength, normaliseNameCards } from "./effects.js";
import { normaliseCta } from "./cta.js";
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

export default function Effects({ project, scene, sceneIndex, thumb, disabled, onProject, onScene, onUploadBanner, onUploadLogo, ctaEvents = [], onPlayCta, api, autoCard }) {
  const fx = normaliseEffects(project.effects);
  const cta = normaliseCta(project.cta);
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
              <Pct label="Size" value={cta.size} disabled={disabled} onChange={(v) => setCta({ size: Math.min(1, Math.max(0.25, v)) })} />
              <label className="cs-slider">
                <span>
                  Height on screen <b>{cta.y < 0.4 ? "upper" : cta.y > 0.6 ? "lower" : "middle"}</b>
                </span>
                <input type="range" aria-label="Subscribe animation height" min="15" max="85" value={Math.round(cta.y * 100)} disabled={disabled} onChange={(e) => setCta({ y: Number(e.target.value) / 100 })} />
              </label>
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
          <label className="field">
            When
            <select aria-label="When the subscribe animation shows" value={cta.mode} disabled={disabled} onChange={(e) => setCta({ mode: e.target.value })}>
              <option value="auto">Automatically, when the narration first says “subscribe”</option>
              <option value="scenes">On the scenes I tick</option>
            </select>
          </label>
          <p className="micro-note block">
            {ctaEvents.length
              ? `Shows at ${ctaEvents.map(([a]) => `${Math.floor(a / 60)}:${String(Math.floor(a % 60)).padStart(2, "0")}`).join(", ")}. ${ownFile ? "Your animation plays once, at its own length" : "The button and cursor stay fully visible"}; captions stay on top. Download MP4 includes it.`
              : cta.mode === "auto"
                ? "No scene says “subscribe” yet. Tick a scene below instead, or check the script."
                : "Tick “Subscribe animation here” on a scene below."}
          </p>
          {ctaEvents.length > 0 && (ownFile ? animFile : banner) && (
            <button className="btn" onClick={() => onPlayCta(ctaEvents[0][0])}>
              Play it in the preview
            </button>
          )}
        </>
      )}

      {scene ? (
        <>
          {cta.enabled && cta.mode === "scenes" && (
            <label className="cs-check" style={{ marginTop: 12 }}>
              <input type="checkbox" aria-label="Subscribe animation on this scene" checked={!!scene.cta} disabled={disabled} onChange={(e) => onScene({ cta: e.target.checked })} />
              Subscribe animation here (scene {String(sceneIndex + 1).padStart(2, "0")})
            </label>
          )}
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
            <span>PHOTO MOVEMENT</span>
          </div>
          <label className="field">
            Movement
            <select aria-label="Photo movement" value={scene.motion || "slow-zoom"} disabled={disabled} onChange={(e) => onScene({ motion: e.target.value })}>
              {MOTIONS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <p className="micro-note block">Movement applies to photos; video plays as filmed.</p>

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

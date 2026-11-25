import React from "react";

// v0.4.52 A motion graphic over the preview: the frames the export makes (drawn by the server,
// smaller, as WebP), at 24 fps. Each graphic's frames are loaded ahead while it plays; a frame that
// has not arrived yet keeps the last one on screen (no flicker), and identical frames load once.
const PLANS = new Map(); // item JSON -> Promise<plan>
const IMAGES = new Map(); // hash/k -> HTMLImageElement (loaded or loading)
const MAX_IMAGES = 1500;

function planFor(projectId, item) {
  const key = projectId + JSON.stringify(item);
  if (!PLANS.has(key)) {
    const p = fetch(`/api/projects/${projectId}/motion/plan`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item }),
    }).then((r) => (r.ok ? r.json() : Promise.reject(new Error("plan"))));
    p.catch(() => PLANS.delete(key));
    PLANS.set(key, p);
    if (PLANS.size > 40) PLANS.delete(PLANS.keys().next().value);
  }
  return PLANS.get(key);
}

function image(hash, k) {
  const key = `${hash}/${k}`;
  let im = IMAGES.get(key);
  if (!im) {
    im = new Image();
    im.decoding = "async";
    im.src = `/api/motion/${hash}/${k}.webp`;
    im.onerror = () => {
      // not drawn yet (the server draws on demand): try again shortly
      setTimeout(() => IMAGES.get(key) === im && IMAGES.delete(key), 400);
    };
    IMAGES.set(key, im);
    if (IMAGES.size > MAX_IMAGES) IMAGES.delete(IMAGES.keys().next().value);
  }
  return im;
}

export default function MotionLayer({ projectId, item, time, width, height, playing, onStatus }) {
  const canvas = React.useRef(null);
  const [plan, setPlan] = React.useState(null);
  const lastDrawn = React.useRef(null);
  const wanted = React.useRef(null);
  const json = JSON.stringify(item);
  React.useEffect(() => {
    let live = true;
    setPlan(null);
    lastDrawn.current = null;
    onStatus?.("preparing");
    planFor(projectId, item)
      .then((p) => live && (setPlan(p), onStatus?.("ready")))
      .catch(() => live && onStatus?.("error"));
    return () => {
      live = false;
    };
  }, [projectId, json]);
  const n = plan ? Math.max(0, Math.min(plan.frames.length - 1, Math.floor((time - item.start) * plan.fps + 1e-6))) : 0;
  React.useEffect(() => {
    if (!plan || !canvas.current) return;
    const ctx = canvas.current.getContext("2d");
    const want = plan.frames[n];
    wanted.current = `${plan.hash}/${want}`;
    const draw = (im) => {
      ctx.clearRect(0, 0, plan.width, plan.height);
      ctx.drawImage(im, 0, 0, plan.width, plan.height);
      lastDrawn.current = im;
    };
    const im = image(plan.hash, want);
    if (im.complete && im.naturalWidth) draw(im);
    else {
      const key = wanted.current;
      im.addEventListener("load", () => {
        if (canvas.current && wanted.current === key) draw(im); // still the frame we want?
      }, { once: true });
      if (!lastDrawn.current) ctx.clearRect(0, 0, plan.width, plan.height);
    }
    // load ahead: the next 2 s while playing, 0.5 s when paused (the server draws them in order)
    const ahead = Math.round(plan.fps * (playing ? 2 : 0.5));
    const seen = new Set();
    for (let j = n + 1; j < Math.min(plan.frames.length, n + ahead); j++) {
      const k = plan.frames[j];
      if (!seen.has(k)) {
        seen.add(k);
        image(plan.hash, k);
      }
    }
  }, [plan, n, playing]);
  return (
    <canvas
      ref={canvas}
      className="motion-layer"
      width={plan?.width || 2}
      height={plan?.height || 2}
      style={{ width, height }}
      aria-label="Motion graphic"
    />
  );
}

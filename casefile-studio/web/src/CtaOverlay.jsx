import React from "react";
import { ctaState, ctaPlacement, ctaCard, ctaBlurFade, ctaFileSeconds, normaliseCta, CTA_FALLBACK, CTA_BLUR } from "./cta.js";

// v0.4.35 The blurred video behind the CTA (the export blurs the same way).
function Blur({ t, seconds, width, height, fade = 1 }) {
  const px = Math.max(2, Math.min(width, height) * CTA_BLUR.radius) * 0.6;
  return (
    <div
      className="cta-blur"
      style={{
        opacity: ctaBlurFade(t, seconds) * fade,
        backdropFilter: `blur(${px}px) brightness(${1 + CTA_BLUR.brightness})`,
        WebkitBackdropFilter: `blur(${px}px) brightness(${1 + CTA_BLUR.brightness})`,
      }}
    />
  );
}

// v0.4.47 Uploads the page has asked the server about (once per page load).
const ASKED = new Set();

// v0.4.47 A transparent .MOV (ProRes, QuickTime Animation…) plays in no browser's <video> with its
// transparency, so the server turns its first seconds into WebP stills (which every browser shows,
// see-through parts included) and the preview shows the still for the clock time: in step when
// paused or scrubbed. The export still uses your original file.
function FramesCta({ frames, t, style }) {
  const urls = React.useMemo(
    () => Array.from({ length: frames.count }, (_, i) => `${frames.base}${String(i).padStart(4, "0")}.webp`),
    [frames.base, frames.count],
  );
  const keep = React.useRef([]);
  React.useEffect(() => {
    keep.current = urls.map((u) => {
      const im = new Image();
      im.src = u;
      return im;
    });
  }, [urls]);
  const i = Math.min(frames.count - 1, Math.max(0, Math.floor(t * frames.fps)));
  return <img className="cta-file" src={urls[i]} alt="" style={style} />;
}

// v0.4.35 Your own animation file (.mov/.webm with transparency, or .gif), kept in step with the preview clock.
function FileCta({ file, c, t, width, height, playing, onNeedPreview, fade = 1 }) {
  const ref = React.useRef(null);
  const [failed, setFailed] = React.useState(false);
  const seconds = ctaFileSeconds(file);
  const frames = file.preview_frames;
  const gif = /\.gif$/i.test(file.url || "");
  const ask = () => {
    if (frames || ASKED.has(file.id) || !onNeedPreview) return;
    ASKED.add(file.id);
    onNeedPreview(file.id);
  };
  // Uploaded before v0.4.47: the server has not looked at the codec yet, so ask it once.
  React.useEffect(() => {
    if (!gif && !file.codec) ask();
  }, [file.id, file.codec, gif]);
  React.useEffect(() => {
    const v = ref.current;
    if (!v || v.tagName !== "VIDEO" || v.readyState < 1) return;
    if (Math.abs(v.currentTime - t) > 0.25) v.currentTime = Math.max(0, t);
    if (playing && v.paused) v.play().catch(() => {});
    if (!playing && !v.paused) v.pause();
  }, [t, playing]);
  const w = Math.round(width * c.size);
  const ratio = (file.height || 1080) / (file.width || 1920);
  const h = w * ratio;
  const top = Math.min(Math.max(0, c.y * height - h / 2), height - h);
  const left = Math.min(Math.max(0, c.x * width - w / 2), width - w);
  const style = { position: "absolute", left, top, width: w, height: h };
  return (
    <div className="cta-layer" aria-hidden="true" style={{ opacity: fade }}>
      {c.style === "blur" && <Blur t={t} seconds={seconds} width={width} height={height} />}
      {frames ? (
        <FramesCta frames={frames} t={t} style={style} />
      ) : gif ? (
        <img key={file.id} className="cta-file" src={file.url} alt="" style={style} />
      ) : (
        <video
          ref={ref}
          className="cta-file"
          src={file.url}
          muted
          playsInline
          preload="auto"
          style={style}
          onLoadedMetadata={(e) => {
            setFailed(false);
            e.currentTarget.currentTime = Math.max(0, t);
            if (playing) e.currentTarget.play().catch(() => {});
          }}
          onError={() => {
            setFailed(true);
            ask();
          }}
        />
      )}
      {!frames && (failed || file.preview_error) && (
        <span className="cta-note" style={{ left: style.left, top: style.top, width: w }}>
          {file.preview_error
            ? "This animation can’t be shown in the preview. The export still uses it."
            : file.codec
              ? "Your browser can’t play this animation. The export still uses it."
              : "Preparing your animation for the preview…"}
        </span>
      )}
    </div>
  );
}

// v0.4.29 The subscribe animation drawn over the preview, `t` seconds in.
// `fade`: 1, or less while a place cut short fades out (v0.4.49).
export default function CtaOverlay({ project, banner, file, t, width, height, playing, onNeedPreview, fade = 1 }) {
  const c = normaliseCta(project.cta);
  if (c.source === "file") {
    if (!file || t < 0 || t >= ctaFileSeconds(file)) return null;
    return <FileCta file={file} c={c} t={t} width={width} height={height} playing={playing} onNeedPreview={onNeedPreview} fade={fade} />;
  }
  if (!banner || t < 0 || t >= c.seconds) return null;
  const st = ctaState(t, c.seconds);
  const iw = banner.width || 1600;
  const ih = banner.height || 900;
  const blur = c.style === "blur";
  const box = blur ? ctaCard(width, height, iw, ih, c.size, c.y, c.x) : ctaPlacement(width, height, iw, ih);
  const [b0, b1, b2, b3] = c.button || CTA_FALLBACK;
  const bx0 = box.x + b0 * box.w;
  const by0 = box.y + b1 * box.h;
  const bw = (b2 - b0) * box.w;
  const bh = (b3 - b1) * box.h;
  const cx = bx0 + bw / 2;
  const cy = by0 + bh / 2;
  const fx = box.x + 0.86 * box.w;
  const fy = box.y + 1.02 * box.h;
  const px = fx + (cx - fx) * st.move;
  const py = fy + (cy - fy) * st.move;
  const unit = Math.min(width, height) * (height > width ? 1.4 : 1);
  const cur = unit * 0.003 * (st.pressed ? 0.85 : 1);
  const crop = { left: -(b0 * box.w), top: -(b1 * box.h), width: box.w, height: box.h };
  return (
    <>
    {blur && <div className="cta-layer" aria-hidden="true"><Blur t={t} seconds={c.seconds} width={width} height={height} fade={fade} /></div>}
    <div className="cta-layer" style={{ opacity: st.fade * fade }} aria-hidden="true">
      <img
        className={`cta-banner ${blur ? "cta-card" : ""}`}
        src={banner.url}
        alt=""
        style={{ left: box.x, top: box.y, width: box.w, height: box.h, opacity: blur ? 1 : c.opacity, borderRadius: blur ? box.w * 0.025 : 0 }}
      />
      <div className="cta-btn" style={{ left: bx0, top: by0, width: bw, height: bh, borderRadius: bh * 0.2 }}>
        {st.subscribed ? (
          <span className="cta-subscribed" style={{ fontSize: bh * 0.46 }}>SUBSCRIBED</span>
        ) : c.button ? (
          <img src={banner.url} alt="" style={{ position: "absolute", ...crop }} />
        ) : (
          <span className="cta-subscribe" style={{ fontSize: bh * 0.46 }}>SUBSCRIBE</span>
        )}
      </div>
      {st.bell && (
        <svg className="cta-bell" viewBox="0 0 24 24" style={{ left: bx0 + bw + bh * 0.35, top: cy - bh * 0.45, width: bh * 0.9, height: bh * 0.9, transform: `rotate(${-st.bellAngle}deg)` }}>
          <circle cx="12" cy="3.5" r="1.5" fill="#f5f5f5" />
          <path d="M5 10.5 A7 7 0 0 1 19 10.5 L21 17.5 L3 17.5 Z" fill="#f5f5f5" />
          <circle cx="12" cy="19.2" r="2.3" fill="#f5f5f5" />
        </svg>
      )}
      {st.ripple !== null && (
        <span
          className="cta-ripple"
          style={{
            left: cx - bh * (0.2 + 1.1 * st.ripple),
            top: cy - bh * (0.2 + 1.1 * st.ripple),
            width: 2 * bh * (0.2 + 1.1 * st.ripple),
            height: 2 * bh * (0.2 + 1.1 * st.ripple),
            opacity: 0.86 * (1 - st.ripple),
            borderWidth: Math.max(2, bh * 0.06),
          }}
        />
      )}
      <svg className="cta-cursor" viewBox="0 0 13 20" style={{ left: px, top: py, width: 13 * cur, height: 20 * cur }}>
        <path d="M0 0 L0 17 L4.2 13.2 L7 19.5 L9.6 18.4 L6.9 12.2 L12.2 12.2 Z" fill="#fff" stroke="#000" strokeWidth="1.1" />
      </svg>
    </div>
    </>
  );
}

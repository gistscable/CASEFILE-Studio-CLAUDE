import React from "react";
import { coverBox, containBox, PIC } from "./picture.js";

// v0.4.49 A scene's picture as the export builds it: the media file's crop,
// then cover / photo over a blur of itself, then the movement (`transform`).
// For a video, `videoRef` gets the <video>.
export default function PictureLayer({ asset, crop, fit, width: W, height: H, lookCss = "none", transform, origin, videoRef, onLoadedMetadata, alt = "" }) {
  const [natural, setNatural] = React.useState(null);
  const sw = Number(asset?.width) || natural?.[0] || W;
  const sh = Number(asset?.height) || natural?.[1] || H;
  const video = asset?.kind === "video";
  const look = lookCss && lookCss !== "none" ? lookCss : "";
  const known = (e) => {
    const el = e.currentTarget;
    const w = el.naturalWidth || el.videoWidth;
    const h = el.naturalHeight || el.videoHeight;
    if (w && h && (!natural || natural[0] !== w || natural[1] !== h)) setNatural([w, h]);
  };
  const media = (style) =>
    video ? (
      <video
        key={asset.id}
        ref={videoRef}
        src={asset.url}
        muted
        playsInline
        loop={false}
        className="pic-media"
        style={{ ...style, filter: lookCss }}
        onLoadedMetadata={(e) => {
          known(e);
          onLoadedMetadata?.(e);
        }}
      />
    ) : (
      <img className="pic-media" src={asset.url} alt={alt} style={{ ...style, filter: lookCss }} onLoad={known} draggable={false} />
    );
  const blur = fit === "blur" || fit === "legacy-blur";
  const bgSrc = video ? asset.thumbnail : asset.url;
  const cover = coverBox(W, H, sw, sh, crop);
  const legacy = fit === "legacy-blur";
  const inset = legacy ? 1 : PIC.over_blur.inset;
  const radius = legacy ? W * 0.03 : Math.min(W, H) * PIC.over_blur.radius * 0.8;
  const bgFilter = legacy
    ? `${look} blur(${radius.toFixed(1)}px) brightness(0.85) saturate(0.85)`
    : `${look} blur(${radius.toFixed(1)}px) brightness(${PIC.over_blur.css_brightness}) saturate(${PIC.over_blur.saturation})`;
  const fg = containBox(W, H, sw, sh, crop, inset);
  return (
    <div className="pic-layer" style={{ transform, transformOrigin: origin }}>
      {blur ? (
        <>
          {bgSrc && (
            <div className="pic-bg">
              <img className="pic-media" src={bgSrc} alt="" draggable={false} style={{ ...cover, filter: bgFilter }} />
            </div>
          )}
          <div className="pic-window" style={fg.box}>
            {media(fg.img)}
          </div>
        </>
      ) : (
        media(cover)
      )}
    </div>
  );
}

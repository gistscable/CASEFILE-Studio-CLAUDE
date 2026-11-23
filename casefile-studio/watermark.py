"""Logo watermark (v0.4.36): your logo in a corner, the middle of an edge, or
the centre, burned into the export.

The default is YouTube's own: bottom right, 150 px wide at 1080p (the size of
YouTube's 150x150 branding watermark). `size` is the logo's width as a share
of the frame's short side, so it looks the same in 16:9 and 9:16; a tall logo
is capped at that height. Same numbers as web/src/watermark.js."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

import effects

SPEC = effects.SPEC["watermark"]
D = SPEC["defaults"]
POSITIONS = SPEC["positions"]


def normalise(value, images=None):
    v = value if isinstance(value, dict) else {}
    out = dict(D)
    out["enabled"] = v.get("enabled") is True
    if v.get("asset_id") and (images is None or v["asset_id"] in images):
        out["asset_id"] = str(v["asset_id"])
    out["position"] = v.get("position") if v.get("position") in POSITIONS else D["position"]
    for k in ("size", "opacity"):
        try:
            lo, hi = SPEC["limits"][k]
            n = float(v.get(k, out[k]))
            if math.isfinite(n):
                out[k] = round(min(hi, max(lo, n)), 3)
        except (TypeError, ValueError):
            pass
    return out


def box(frame_w, frame_h, img_w, img_h, position, size):
    """(x, y, w, h) of the logo in the frame."""
    short = min(frame_w, frame_h)
    w = short * size
    h = w * img_h / max(1, img_w)
    if h > short * size:
        h = short * size
        w = h * img_w / max(1, img_h)
    m = short * SPEC["margin"]
    row, _, col = position.partition("-") if "-" in position else ("middle", "", "center")
    if position == "center":
        row, col = "middle", "center"
    x = {"left": m, "center": (frame_w - w) / 2, "right": frame_w - m - w}[col]
    y = {"top": m, "middle": (frame_h - h) / 2, "bottom": frame_h - m - h}[row]
    return round(x), round(y), max(1, round(w)), max(1, round(h))


def active(project):
    w = normalise(project.get("watermark"))
    if not w["enabled"] or not w["asset_id"]:
        return None
    return next((a for a in project.get("assets", []) if a.get("id") == w["asset_id"] and a.get("kind") == "image"), None) and w


def layer(project, logo_path, width, height, out_path):
    """A full-frame transparent PNG with the logo placed; overlaid by ffmpeg."""
    w = normalise(project.get("watermark"))
    with Image.open(logo_path) as im:
        logo = im.convert("RGBA")
    x, y, lw, lh = box(width, height, logo.width, logo.height, w["position"], w["size"])
    logo = logo.resize((lw, lh), Image.LANCZOS)
    logo.putalpha(logo.getchannel("A").point(lambda v: round(v * w["opacity"])))
    frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    frame.alpha_composite(logo, (x, y))
    out_path = Path(out_path)
    frame.save(out_path)
    return out_path

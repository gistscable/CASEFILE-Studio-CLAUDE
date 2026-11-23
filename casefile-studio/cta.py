"""Subscribe call-to-action overlay (v0.4.29).

Your own banner fades in over the picture (50% by default) with its
SUBSCRIBE button at full strength; a cursor moves to the button and clicks,
the button turns to SUBSCRIBED with a bell, then everything fades out.

The timeline (`state`) is the same numbers as web/src/cta.js, from
effectsSpec.json, so the preview moves like the export. Frames are drawn
with Pillow at the export size and overlaid by ffmpeg; a CTA that runs past
the end of a scene carries on in the next one.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import captionstyle
import effects

SPEC = effects.SPEC["cta"]
D = SPEC["defaults"]
FPS = 24


def normalise(value, assets=None, files=None):
    v = value if isinstance(value, dict) else {}
    out = dict(D)
    out["enabled"] = v.get("enabled") is True
    if v.get("asset_id") and (assets is None or v["asset_id"] in assets):
        out["asset_id"] = str(v["asset_id"])
    b = v.get("button")
    if isinstance(b, (list, tuple)) and len(b) == 4:
        try:
            x0, y0, x1, y1 = (min(1.0, max(0.0, float(n))) for n in b)
            if x1 - x0 > 0.01 and y1 - y0 > 0.01:
                out["button"] = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
        except (TypeError, ValueError):
            pass
    for k in ("opacity", "seconds"):
        try:
            lo, hi = SPEC["limits"][k]
            n = float(v.get(k, out[k]))
            if math.isfinite(n):
                out[k] = round(min(hi, max(lo, n)), 2)
        except (TypeError, ValueError):
            pass
    out["mode"] = v.get("mode") if v.get("mode") in ("auto", "scenes") else "auto"
    # v0.4.35: your own animated file, and a blurred video behind the CTA.
    out["style"] = v.get("style") if v.get("style") in ("overlay", "blur") else "overlay"
    out["source"] = v.get("source") if v.get("source") in ("casefile", "file") else "casefile"
    if v.get("file_id") and (files is None or v["file_id"] in files):
        out["file_id"] = str(v["file_id"])
    for k in ("size", "y"):
        try:
            lo, hi = SPEC["limits"][k]
            n = float(v.get(k, out[k]))
            if math.isfinite(n):
                out[k] = round(min(hi, max(lo, n)), 3)
        except (TypeError, ValueError):
            pass
    return out


def file_seconds(asset):
    """How long your own animation plays (its own length, 1 to 15 s)."""
    d = float((asset or {}).get("video_duration") or (asset or {}).get("duration") or 0)
    return round(min(SPEC["file_max_seconds"], max(1.0, d or 5.0)), 3)


def ready(c, assets_by_id):
    """Is there something to show?"""
    if not c["enabled"]:
        return False
    if c["source"] == "file":
        return bool(c["file_id"] and c["file_id"] in assets_by_id)
    return bool(c["asset_id"])


def length(c, assets_by_id):
    return file_seconds(assets_by_id.get(c["file_id"])) if c["source"] == "file" else c["seconds"]


def card(frame_w, frame_h, img_w, img_h, size, y):
    """The banner as a card: `size` of the width, centred at height `y`."""
    w = frame_w * size
    h = w * img_h / img_w
    if h > frame_h * 0.9:
        h = frame_h * 0.9
        w = h * img_w / img_h
    top = min(max(0, y * frame_h - h / 2), frame_h - h)
    return round((frame_w - w) / 2), round(top), round(w), round(h)


def alpha_decoder(path):
    """WebM keeps its transparency only through the libvpx decoder."""
    if str(path).lower().endswith(".webm"):
        import subprocess
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name:stream_tags=alpha_mode",
                            "-of", "default=nw=1", str(path)], capture_output=True, text=True)
        if "alpha_mode=1" in r.stdout:
            return ["-c:v", "libvpx-vp9" if "vp9" in r.stdout else "libvpx"]
    return []


# --------------------------------------------------------------------------
# Finding the SUBSCRIBE button on the banner
# --------------------------------------------------------------------------


def detect_button(path):
    """The biggest solid red rectangle on the banner (a button, not a thin
    frame line or a pin), as fractions [x0, y0, x1, y1]; None if none."""
    with Image.open(path) as im:
        small = im.convert("RGB").resize((256, max(16, round(256 * im.height / im.width))))
    a = np.asarray(small).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mask = (r > 110) & (r > g * 2.2) & (r > b * 2.2)
    h, w = mask.shape
    seen = np.zeros_like(mask)
    best = None
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            stack, pts = [(y, x)], []
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                pts.append((cy, cx))
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            ys = [p[0] for p in pts]
            xs = [p[1] for p in pts]
            x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
            bw, bh = x1 - x0, y1 - y0
            fill = len(pts) / (bw * bh)
            if len(pts) >= 40 and fill > 0.6 and 1.6 <= bw / bh <= 10:
                if best is None or len(pts) > best[0]:
                    best = (len(pts), [x0 / w, y0 / h, x1 / w, y1 / h])
    return [round(n, 4) for n in best[1]] if best else None


# --------------------------------------------------------------------------
# Timing (shared with web/src/cta.js)
# --------------------------------------------------------------------------


def _ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def state(t, seconds):
    """Everything about the animation at `t` seconds into it."""
    fade = min(1.0, t / SPEC["fade_in"]) if t < SPEC["fade_in"] else 1.0
    out_start = seconds - SPEC["fade_out"]
    if t > out_start:
        fade = max(0.0, (seconds - t) / SPEC["fade_out"])
    m0, m1 = SPEC["move"]
    k = _ease((t - m0) / (m1 - m0))
    click = SPEC["click"]
    pressed = click <= t < click + SPEC["press"]
    r0, r1 = SPEC["ripple"]
    ripple = (t - r0) / (r1 - r0) if r0 <= t < r1 else None
    w0, w1 = SPEC["wiggle"]
    bell = 0.0
    if w0 <= t < w1:
        q = (t - w0) / (w1 - w0)
        bell = 18 * math.sin(2 * math.pi * 4 * q) * (1 - q)
    return {
        "fade": fade,
        "move": k,
        "pressed": pressed,
        "subscribed": t >= click + 0.1,
        "ripple": ripple,
        "bell": t >= SPEC["bell_in"],
        "bell_angle": bell,
    }


def placement(frame_w, frame_h, img_w, img_h):
    """Where the banner goes: the whole frame when the shapes match, else
    92% of the width, centred."""
    if abs((img_w / img_h) / (frame_w / frame_h) - 1) < 0.06:
        return 0, 0, frame_w, frame_h
    w = frame_w * 0.92
    h = w * img_h / img_w
    if h > frame_h * 0.92:
        h = frame_h * 0.92
        w = h * img_w / img_h
    return round((frame_w - w) / 2), round((frame_h - h) / 2), round(w), round(h)


def cue_start(scene, clean=lambda s: s):
    """Seconds into the scene to start: just before the first caption that
    says "subscribe", else at the start."""
    import renderer
    for c in renderer.scene_captions(scene):
        if re.search(r"subscri", c["text"], re.I):
            return max(0.0, c["start"] - SPEC["lead"])
    return 0.0


def is_cta_scene(scene):
    head = f"{scene.get('chapter', '')} {scene.get('title', '')}"
    return bool(re.search(r"subscri|\bCTA\b|call to action", head, re.I))


def events(project):
    """[(start, end)] on the whole timeline, in seconds."""
    c = normalise(project.get("cta"))
    assets_by_id = {a["id"]: a for a in project.get("assets", [])}
    if not ready(c, assets_by_id):
        return []
    seconds = length(c, assets_by_id)
    scenes = project.get("scenes", [])
    offsets, t = [], 0.0
    for s in scenes:
        offsets.append(t)
        t += round(float(s["duration"]) * FPS) / FPS
    total = t
    picks = []
    if c["mode"] == "scenes":
        picks = [i for i, s in enumerate(scenes) if s.get("cta")]
    else:
        heads = [i for i, s in enumerate(scenes) if is_cta_scene(s)]
        said = [i for i, s in enumerate(scenes) if re.search(r"subscri", s.get("narration", ""), re.I)]
        pool = [i for i in heads if i in said] or heads or said
        picks = pool[:1]
    out = []
    for i in picks:
        start = offsets[i] + cue_start(scenes[i])
        end = min(total, start + seconds)
        if not out or start >= out[-1][1]:
            out.append((round(start, 3), round(end, 3)))
    return out


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def _font(size):
    try:
        return ImageFont.truetype(str(captionstyle.FONT_DIR / "Inter-Bold.otf"), max(8, int(size)))
    except OSError:
        return ImageFont.load_default()


def _cursor(d, x, y, s):
    pts = [(0, 0), (0, 17), (4.2, 13.2), (7, 19.5), (9.6, 18.4), (6.9, 12.2), (12.2, 12.2)]
    poly = [(x + px * s, y + py * s) for px, py in pts]
    d.polygon(poly, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=max(1, round(s * 1.1)))


def _bell(size, angle):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 24
    d.ellipse((10.5 * s, 2 * s, 13.5 * s, 5 * s), fill=(245, 245, 245, 255))
    d.pieslice((5 * s, 3.5 * s, 19 * s, 17.5 * s), 180, 360, fill=(245, 245, 245, 255))
    d.polygon([(5 * s, 10.5 * s), (19 * s, 10.5 * s), (21 * s, 17.5 * s), (3 * s, 17.5 * s)], fill=(245, 245, 245, 255))
    d.ellipse((9.5 * s, 17 * s, 14.5 * s, 21.5 * s), fill=(245, 245, 245, 255))
    return im.rotate(angle, resample=Image.BICUBIC, center=(size / 2, 3 * s))


def frames(project, banner_path, width, height, folder):
    """Write f0000.png… for one run of the animation; returns how many."""
    c = normalise(project.get("cta"))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with Image.open(banner_path) as im:
        banner = im.convert("RGBA")
    blur = c["style"] == "blur"
    if blur:
        # v0.4.35: a solid card with rounded corners and a shadow, over the blurred video.
        bx, by, bw, bh = card(width, height, banner.width, banner.height, c["size"], c["y"])
        banner = banner.resize((bw, bh), Image.LANCZOS)
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), radius=max(4, round(bw * 0.025)), fill=255)
        banner.putalpha(Image.composite(banner.getchannel("A"), mask, mask))
        from PIL import ImageFilter
        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        off = max(2, round(bh * 0.03))
        ImageDraw.Draw(shadow).rounded_rectangle((bx, by + off, bx + bw, by + bh + off), radius=max(4, round(bw * 0.025)), fill=(0, 0, 0, 150))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(3, round(bh * 0.05))))
        opacity = 1.0
    else:
        bx, by, bw, bh = placement(width, height, banner.width, banner.height)
        banner = banner.resize((bw, bh), Image.LANCZOS)
        shadow = None
        opacity = c["opacity"]
    button = c["button"] or SPEC["fallback_button"]
    x0, y0, x1, y1 = (round(bx + button[0] * bw), round(by + button[1] * bh), round(bx + button[2] * bw), round(by + button[3] * bh))
    bt_h = max(8, y1 - y0)
    btn_img = banner.crop((x0 - bx, y0 - by, x1 - bx, y1 - by)) if c["button"] else None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    fx, fy = bx + SPEC["cursor_from"][0] * bw, by + SPEC["cursor_from"][1] * bh
    unit = effects.text_unit(width, height)
    cursor_scale = unit * 0.003
    font = _font(bt_h * 0.46)
    count = max(1, round(c["seconds"] * FPS))
    for n in range(count):
        st = state(n / FPS, c["seconds"])
        a = st["fade"]
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if shadow is not None:
            sh = shadow.copy()
            sh.putalpha(sh.getchannel("A").point(lambda v: round(v * a)))
            img.alpha_composite(sh)
        layer = banner.copy()
        layer.putalpha(layer.getchannel("A").point(lambda v: round(v * opacity * a)))
        img.alpha_composite(layer, (bx, by))
        d = ImageDraw.Draw(img)
        top = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        td = ImageDraw.Draw(top)
        if st["subscribed"]:
            td.rounded_rectangle((x0, y0, x1, y1), radius=bt_h * 0.2, fill=(48, 48, 48, 255))
            label = "SUBSCRIBED"
            tb = td.textbbox((0, 0), label, font=font)
            td.text((cx - (tb[2] - tb[0]) / 2 - tb[0], cy - (tb[3] - tb[1]) / 2 - tb[1]), label, font=font, fill=(235, 235, 235, 255))
        elif btn_img is not None:
            top.alpha_composite(btn_img, (x0, y0))
        else:  # no button found on the banner: draw one
            td.rounded_rectangle((x0, y0, x1, y1), radius=bt_h * 0.2, fill=(196, 18, 30, 255))
            label = "SUBSCRIBE"
            tb = td.textbbox((0, 0), label, font=font)
            td.text((cx - (tb[2] - tb[0]) / 2 - tb[0], cy - (tb[3] - tb[1]) / 2 - tb[1]), label, font=font, fill=(255, 255, 255, 255))
        if st["bell"]:
            size = round(bt_h * 0.9)
            bell = _bell(size, st["bell_angle"])
            top.alpha_composite(bell, (round(x1 + bt_h * 0.35), round(cy - size / 2)))
        if st["ripple"] is not None:
            q = st["ripple"]
            r = bt_h * (0.2 + 1.1 * q)
            td.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, round(220 * (1 - q))), width=max(2, round(bt_h * 0.06)))
        px = fx + (cx - fx) * st["move"]
        py = fy + (cy - fy) * st["move"]
        _cursor(td, px, py, cursor_scale * (0.85 if st["pressed"] else 1.0))
        top.putalpha(top.getchannel("A").point(lambda v: round(v * a)))
        img.alpha_composite(top)
        del d
        img.save(folder / f"f{n:04d}.png", compress_level=1)
    return count

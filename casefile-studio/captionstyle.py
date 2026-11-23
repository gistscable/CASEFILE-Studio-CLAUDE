"""Caption styles (v0.4.25): one style per project, the same definitions as
the preview (web/src/captionPresets.json), burned in with libass using the
bundled fonts in web/assets/fonts, so the export looks like the preview.

All sizes are fractions of the video height, so a style looks the same at
480p, 720p and 1080p. `size` is the CSS font size; libass sizes fonts by
winAscent + winDescent, so the ASS size is size / ratio for each font.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = json.loads((ROOT / "web/src/captionPresets.json").read_text(encoding="utf-8"))
FONTS = SPEC["fonts"]
DEFAULTS = SPEC["defaults"]
PRESETS = {p["id"]: p for p in SPEC["presets"]}
LIMITS = SPEC["limits"]
FONT_DIR = ROOT / "web/assets/fonts"
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalise(style):
    """A complete, safe style from whatever was saved (or None)."""
    style = style if isinstance(style, dict) else {}
    preset = style.get("preset") if style.get("preset") in PRESETS else DEFAULTS["preset"]
    out = {**DEFAULTS, **PRESETS[preset]["style"], "preset": preset}
    for k, v in style.items():
        if k not in DEFAULTS or k == "preset":
            continue
        if k in LIMITS:
            try:
                lo, hi = LIMITS[k]
                n = float(v)
                if n != n:
                    continue
                out[k] = int(min(hi, max(lo, round(n)))) if k == "words" else round(min(hi, max(lo, n)), 5)
            except (TypeError, ValueError):
                pass
        elif k in ("color", "highlight", "outline_color", "box_color"):
            if isinstance(v, str) and _HEX.match(v):
                out[k] = v.upper()
        elif k in ("box", "uppercase"):
            out[k] = v is True
        elif k == "font" and v in FONTS:
            out[k] = v
        elif k == "animation" and v in SPEC["animations"]:
            out[k] = v
    return out


def ass_colour(hex_colour, opacity=1.0):
    r, g, b = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    alpha = round((1 - max(0.0, min(1.0, opacity))) * 255)
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(sec):
    cs = round(max(0.0, sec) * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "").replace("\\", "").replace("{", "").replace("}", "")).strip()


def word_times(start, end, words):
    """Even timing by length (CapCut does the same without word timings)."""
    weights = [max(1, len(w)) + 1 for w in words]
    total = sum(weights) or 1
    out, t = [], start
    for w, k in zip(words, weights):
        d = (end - start) * k / total
        out.append((t, t + d))
        t += d
    return out


def chunks(cues, words_per):
    """Split cues into at most `words_per` words each (0 keeps them whole)."""
    out = []
    for c in cues:
        words = _clean(c["text"]).split()
        if not words or c["end"] <= c["start"]:
            continue
        if not words_per or len(words) <= words_per:
            out.append({"start": c["start"], "end": c["end"], "words": words})
            continue
        times = word_times(c["start"], c["end"], words)
        for i in range(0, len(words), words_per):
            part = words[i:i + words_per]
            out.append({"start": times[i][0], "end": times[i + len(part) - 1][1], "words": part})
    return out


def style_line(style, width, height):
    import effects  # here, not at the top: effects imports this module
    f = FONTS[style["font"]]
    unit = effects.text_unit(width, height)
    size = style["size"] * unit / f["ratio"]
    outline = style["outline"] * unit
    border = 3 if style["box"] else 1
    outline_colour = ass_colour(style["box_color"], style["box_opacity"]) if style["box"] else ass_colour(style["outline_color"])
    back = ass_colour("#000000", 0.6)
    margin_lr = round(width * 0.0625)
    return (
        f"Style: Default,{f['ass']},{size:.1f},{ass_colour(style['color'])},&H000000FF,{outline_colour},{back},"
        f"{-1 if f['bold'] else 0},0,0,0,100,100,0,0,{border},{outline:.1f},{style['shadow'] * unit:.1f},2,"
        f"{margin_lr},{margin_lr},{round(effects.caption_bottom(style['position'], width, height) * height)},1"
    )


def ass(cues, width, height, style=None, extra_styles=(), extra_events=()):
    """The whole ASS file for these cues (seconds relative to the clip).
    `extra_styles` / `extra_events` add other text, such as a lower third."""
    style = normalise(style)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line(style, width, height)}\n"
        + "".join(s + "\n" for s in extra_styles if s)
        + "\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    anim = style["animation"]
    hi = ass_colour(style["highlight"])
    for c in chunks(cues, style["words"]):
        words = [w.upper() for w in c["words"]] if style["uppercase"] else c["words"]
        if anim == "highlight":
            for i, (a, b) in enumerate(word_times(c["start"], c["end"], words)):
                text = " ".join(
                    f"{{\\c{hi}}}{w}{{\\r}}" if j == i else w for j, w in enumerate(words)
                )
                lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b if i < len(words) - 1 else c['end'])},Default,,0,0,0,,{text}")
            continue
        tag = {"fade": "{\\fad(150,100)}", "pop": "{\\fad(60,0)\\fscx70\\fscy70\\t(0,140,\\fscx100\\fscy100)}"}.get(anim, "")
        lines.append(f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Default,,0,0,0,,{tag}{' '.join(words)}")
    lines += list(extra_events)
    return head + "\n".join(lines) + ("\n" if lines else "")


def filter_arg(ass_path):
    """The ffmpeg subtitles filter that uses the bundled fonts."""
    esc = lambda p: str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles='{esc(ass_path)}':fontsdir='{esc(FONT_DIR)}'"

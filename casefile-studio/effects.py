"""Effects and transitions (v0.4.26), shared with the preview through
web/src/effectsSpec.json.

* Transitions go INTO a scene and never move a boundary: the previous
  scene's last frame is blended into the first moments of this scene with
  ffmpeg's xfade, so every scene keeps its exact length and the narration
  stays in sync.
* A look (colour grade), film grain, vignette and letterbox apply to the
  picture under the titles and captions.
* A lower-third name card is drawn by libass in the same subtitles file as
  the captions, with the bundled font.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import captionstyle

ROOT = Path(__file__).resolve().parent
SPEC = json.loads((ROOT / "web/src/effectsSpec.json").read_text(encoding="utf-8"))
TRANSITIONS = {t["id"]: t for t in SPEC["transitions"]}
LEGACY = SPEC["legacy_transitions"]
MOTIONS = [m["id"] for m in SPEC["motions"]]
LOOKS = {l["id"]: l for l in SPEC["looks"]}
LT = SPEC["lower_third"]
FORMATS = SPEC["formats"]
FITS = [f["id"] for f in SPEC["fits"]]


def aspect_of(project):
    a = (project or {}).get("aspect")
    return a if a in FORMATS else "16:9"


def fit_of(project):
    f = (project or {}).get("vertical_fit")
    return f if f in FITS else "blur"


def frame_size(resolution, aspect="16:9"):
    return tuple(FORMATS.get(aspect, FORMATS["16:9"])["sizes"][resolution])


def text_unit(width, height):
    """Pixels that text sizes are fractions of. 16:9: the height, exactly as
    before. 9:16: the width x 1.6, so captions are big enough on a phone."""
    vertical = height > width
    return min(width, height) * (FORMATS["9:16"]["text_scale"] if vertical else 1.0)


def caption_bottom(position, width, height):
    """Captions sit above the app buttons at the bottom of Shorts/TikTok/Reels."""
    floor = FORMATS["9:16"]["safe_bottom"] if height > width else 0.0
    return max(position, floor)


def transition_id(value):
    value = LEGACY.get(value, value)
    return value if value in TRANSITIONS else "none"


def transition_length(scene, duration):
    """Seconds, at most half the scene and 2 s; 0.5 s when the producer chose
    a transition but no length."""
    t = transition_id(scene.get("transition"))
    if t == "none":
        return 0.0
    try:
        d = float(scene.get("transition_duration") or 0)
    except (TypeError, ValueError):
        d = 0.0
    if d <= 0:
        d = 0.5
    return round(max(0.0, min(d, duration / 2, 2.0)), 3)


def normalise_effects(value):
    v = value if isinstance(value, dict) else {}
    out = dict(SPEC["effects_defaults"])
    for k in ("grain", "vignette"):
        try:
            n = float(v.get(k, out[k]))
            out[k] = round(min(1.0, max(0.0, n)), 3) if math.isfinite(n) else out[k]
        except (TypeError, ValueError):
            pass
    out["letterbox"] = v.get("letterbox") is True
    return out


def normalise_lower_third(value):
    if not isinstance(value, dict):
        return None
    name = " ".join(str(value.get("name") or "").split())[:80]
    role = " ".join(str(value.get("role") or "").split())[:100]
    return {"name": name, "role": role} if name or role else None


def picture_filters(look, fx, width, height):
    """Filters for the picture, after scale/crop/motion and before titles."""
    fx = normalise_effects(fx)
    parts = []
    grade = LOOKS.get(look) or LOOKS["noir"]
    if grade["ffmpeg"]:
        parts.append(grade["ffmpeg"])
    if fx["vignette"] > 0:
        parts.append(f"vignette=angle={0.15 + 0.55 * fx['vignette']:.3f}")
    if fx["grain"] > 0:
        parts.append(f"noise=alls={round(4 + 22 * fx['grain'])}:allf=t+u")
    if fx["letterbox"] and width > height:  # cinema bars only make sense in a wide frame
        bar = max(0, round((height - width / 2.35) / 2))
        if bar:
            parts.append(f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill")
    return parts


def xfade_name(scene):
    return TRANSITIONS[transition_id(scene.get("transition"))]["xfade"]


LABEL_GAP = 0.03  # between a footage label and a name card above it


def lower_third_bottom(width, height, lift=False):
    """Fraction of the height from the bottom. `lift`: the scene shows a
    footage label, so the card goes above it with a clear gap."""
    f = FORMATS["9:16" if height > width else "16:9"]
    bottom = f["lower_third_bottom"]
    return max(bottom, 1 - f["label_top"] + LABEL_GAP) if lift else bottom


def split_who(who):
    """'Dedrick Hilton (father)' -> {'name': 'Dedrick Hilton', 'role': 'Father'}."""
    who = " ".join(str(who or "").split())
    m = re.match(r"^(.*?)\s*[\(\[](.+?)[\)\]]\s*$", who)
    name, role = (m.group(1), m.group(2)) if m else (who, "")
    role = role[:1].upper() + role[1:] if role else ""
    return {"name": name[:80], "role": role[:100]}


def normalise_name_cards(value):
    v = value if isinstance(value, dict) else {}
    people = {}
    for sid, p in (v.get("people") or {}).items():
        if not re.fullmatch(r"[A-Z]{1,3}\d{1,3}", str(sid)) or not isinstance(p, dict):
            continue
        card = normalise_lower_third(p)
        if card:
            people[str(sid)] = {**card, "on": p.get("on") is not False}
    return {"auto": v.get("auto") is True, "people": dict(sorted(people.items()))}


def scene_source(scene):
    return scene.get("guide_source_id") or scene.get("guide_primary_source_id") or ""


def effective_lower_thirds(project):
    """{scene index: card}. A card typed on a scene always wins. With automatic
    name cards on, the first scene that uses each person's clip gets theirs."""
    cards = {}
    nc = normalise_name_cards(project.get("name_cards"))
    seen = set()
    for i, s in enumerate(project.get("scenes", [])):
        own = normalise_lower_third(s.get("lower_third"))
        sid = scene_source(s)
        if own:
            cards[i] = own
            if sid:
                seen.add(sid)
        elif nc["auto"] and sid and sid not in seen:
            p = nc["people"].get(sid)
            if p and p["on"]:
                cards[i] = {"name": p["name"], "role": p["role"]}
                seen.add(sid)
    return cards


def lower_third_ass(lower, scene_duration, width, height, lift=False):
    """(style line, [dialogue lines]) for a lower-third name card."""
    lt = normalise_lower_third(lower)
    if not lt:
        return None, []
    f = captionstyle.FONTS[LT["font"]]
    unit = text_unit(width, height)
    name_fs = LT["name_size"] * unit / f["ratio"]
    role_fs = LT["role_size"] * unit / f["ratio"]
    pad = LT["pad"] * unit
    box = captionstyle.ass_colour("#000000", LT["box_opacity"])
    style = (
        f"Style: LowerThird,{f['ass']},{name_fs:.1f},&H00FFFFFF,&H000000FF,{box},&H00000000,"
        f"{-1 if f['bold'] else 0},0,0,0,100,100,0,0,3,{pad:.1f},0,1,0,0,0,1"
    )
    x1 = round(LT["x"] * width)
    x0 = round(x1 - 0.03 * width)
    y = round(height - lower_third_bottom(width, height, lift) * height)
    end = min(scene_duration, LT["seconds"])
    start = min(0.3, end / 4)
    text = captionstyle._clean(lt["name"])
    if lt["role"]:
        role = captionstyle._clean(lt["role"])
        text = (text + "\\N" if text else "") + f"{{\\fs{role_fs:.1f}\\c&H00D9E3E6&}}{role}"
    event = (
        f"Dialogue: 1,{captionstyle.ass_time(start)},{captionstyle.ass_time(end)},LowerThird,,0,0,0,,"
        f"{{\\an1\\move({x0},{y},{x1},{y},0,300)\\fad(250,300)}}{text}"
    )
    return style, [event]

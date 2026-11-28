"""v0.4.74 keyframe speed (curves + retiming) and the phone & app sounds."""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

import picture
import sfxlib
import sound
import stickers

ROOT = Path(__file__).resolve().parents[1]


def eval_expr(expr, **vars):
    py = re.sub(r"\bif\(", "IF(", expr)
    py = re.sub(r"\blt\(", "LT(", py)
    return eval(py, {"IF": lambda c, a, b: a if c else b, "LT": lambda a, b: a < b, **vars})


def node(js):
    out = subprocess.run(["node", "--input-type=module", "-e", js], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


TIMES = [0, 0.3, 0.99, 1.0, 1.4, 1.75, 2.0, 2.6, 3.2, 3.99, 4.0, 4.5, 5.6, 7]


def sticker_keys():
    kinds = list(picture.STICKER_EASES)
    return [{"t": float(i), "x": 0.1 + 0.13 * i, "y": 0.5 - 0.05 * i, "size": 0.3, "opacity": 1, "ease": e} for i, e in enumerate(kinds)]


def test_every_speed_curve_shape():
    for kind in picture.STICKER_EASES:
        assert picture.ease(0, kind) == pytest.approx(0, abs=1e-12) and picture.ease(1, kind) == pytest.approx(1)
    assert picture.ease(0.5, "linear") == 0.5 and picture.ease(0.5, "smooth") == 0.5
    assert picture.ease(0.3, "in") < 0.3 < picture.ease(0.3, "out")  # starts slow / starts fast
    assert picture.ease(0.99, "hold") == 0  # stays, then jumps
    assert max(picture.ease(u / 100, "bounce") for u in range(101)) > 1.05  # goes past, then settles
    assert picture.ease_kind("nope") == "smooth" and picture.ease_kind("bounce") == "smooth"  # no bounce on the picture
    assert picture.ease_kind("bounce", picture.STICKER_EASES) == "bounce"


def test_speed_curves_preview_and_export_agree():
    keys = stickers.normalise_keyframes(sticker_keys(), 10, {"x": 0.5, "y": 0.5, "size": 0.3, "opacity": 1})
    assert [k["ease"] for k in keys] == list(picture.STICKER_EASES)
    for t in TIMES:
        v = picture.interpolate(keys, t, ("x", "y"))
        for f in ("x", "y"):
            assert eval_expr(picture.expr(keys, f, "T"), T=t) == pytest.approx(v[f], abs=1e-4), (t, f)
    js = node(f"""
    import {{ normaliseStickerKeys }} from "./web/src/stickers.js";
    import {{ interpolate }} from "./web/src/picture.js";
    const keys = normaliseStickerKeys({json.dumps(sticker_keys())}, 10, {{ x: 0.5, y: 0.5, size: 0.3, opacity: 1 }});
    console.log(JSON.stringify({{ keys, v: {json.dumps(TIMES)}.map((t) => interpolate(keys, t, ["x", "y"])) }}));
    """)
    assert js["keys"] == keys
    for t, v in zip(TIMES, js["v"]):
        p = picture.interpolate(keys, t, ("x", "y"))
        assert v["x"] == pytest.approx(p["x"], abs=1e-9) and v["y"] == pytest.approx(p["y"], abs=1e-9)


def test_picture_keyframes_take_the_new_speeds():
    keys = picture.normalise_keyframes([{"t": 0, "zoom": 1, "ease": "in"}, {"t": 2, "zoom": 2, "ease": "hold"}, {"t": 3, "zoom": 1.5, "ease": "bounce"}, {"t": 4, "zoom": 1}])
    assert [k["ease"] for k in keys] == ["in", "hold", "smooth", "smooth"]
    for t in (0.5, 1, 2.5, 3.5):
        assert eval_expr(picture.expr(keys, "zoom", "T"), T=t) == pytest.approx(picture.camera_at(keys, t)["zoom"], abs=1e-4)
    assert picture.camera_at(keys, 2.9)["zoom"] == 2  # held until the next keyframe


def test_a_bounce_never_overshoots_opacity_or_size():
    st = stickers.normalise([{"kind": "like", "start": 0, "length": 4, "keyframes": [
        {"t": 0, "opacity": 0.2, "size": 0.5, "ease": "bounce"}, {"t": 1, "opacity": 1, "size": 0.02}]}])[0]
    for i in range(0, 101):
        v = stickers.sample(st, i / 100)
        assert 0 <= v["opacity"] <= 1 and v["size"] >= stickers.SPEC["limits"]["size"][0]


def test_retime_keys():
    out = node("""
    import { retimeKeys } from "./web/src/picture.js";
    const k = [{ t: 1, x: 0 }, { t: 2, x: 1 }, { t: 3, x: 0 }];
    console.log(JSON.stringify([retimeKeys(k, 0.8, 4), retimeKeys(k, 1.25, 4), retimeKeys(k, 2, 4), retimeKeys([k[0]], 2, 4), retimeKeys([{ t: 0 }, { t: 0.045 }], 0.8, 4)]));
    """)
    assert [k["t"] for k in out[0]] == [1, 1.8, 2.6]  # faster: closer together, from the first
    assert [k["t"] for k in out[1]] == [1, 2.25, 3.5]
    assert out[2] is None and out[3] is None and out[4] is None  # past the end / nothing to retime / too close


# ------------------------------------------------------------------ phone & app sounds

PHONE = ["phone-trio", "phone-chirp", "phone-glow", "phone-chord", "phone-bounce", "phone-ding", "phone-pin", "phone-pin-seq"]


def test_phone_sounds_are_made_here_and_sound():
    assert [c[0] for c in sfxlib.CATALOG if c[1] == "phone"] == PHONE
    for sid in PHONE:
        x, sync = sfxlib.synth(sid)
        assert x.shape[0] == 2 and np.isfinite(x).all()
        assert 0.05 < x.shape[1] / sfxlib.SR < 5, sid
        assert 20 * np.log10(np.abs(x).max()) == pytest.approx(sfxlib.BY_ID[sid][5], abs=0.1)
        tail = np.abs(x[:, -sfxlib._n(0.005):]).max()
        assert tail < np.abs(x).max() * 0.05, sid  # rings out, not cut off


def test_phone_sounds_are_searchable_and_never_placed_automatically(isolated=None):
    cat = {s["id"]: s for s in sfxlib.catalog()}
    assert "tri-tone" in cat["phone-trio"]["tags"] and "tweet" in cat["phone-chirp"]["tags"] and "aurora" in cat["phone-glow"]["tags"]
    assert "rebound" in cat["phone-bounce"]["tags"] and "ticker" in cat["phone-pin"]["tags"]
    for c in sfxlib.CATEGORIES:
        if c == "phone":
            continue
        for i in (0.2, 0.5, 0.9):
            assert not any(s.startswith("phone-") for s in sound._candidates(c, i))
    assert "phone" in sfxlib.CATEGORIES



def test_ffmpeg_moves_a_layer_on_every_curve(tmp_path):
    """The export expression runs in FFmpeg: a red square moved with every speed curve lands where
    the preview puts it."""
    import shutil
    from PIL import Image
    ff = shutil.which("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg")
    keys = stickers.normalise_keyframes(sticker_keys(), 10, {"x": 0.5, "y": 0.5, "size": 0.3, "opacity": 1})
    X = f"({picture.expr(keys, 'x', 't')})*400-5"
    times = [0.5, 1.5, 2.25, 3.5, 4.75, 5.5]
    sel = "+".join(f"eq(n\\,{round(t * 24)})" for t in times)
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "color=black:s=400x40:r=24:d=6", "-f", "lavfi", "-i", "color=red:s=10x10:r=24:d=6",
                    "-filter_complex", f"[0:v][1:v]overlay=x='{X}':y=15,select='{sel}'", "-vsync", "0", str(tmp_path / "f%03d.png")],
                   check=True, timeout=60)
    for i, t in enumerate(times):
        a = np.asarray(Image.open(tmp_path / f"f{i + 1:03d}.png").convert("RGB")).astype(int)
        cols = np.nonzero(a[20, :, 0] > 150)[0]
        want = picture.interpolate(keys, round(t * 24) / 24, ("x",))["x"] * 400
        assert abs(cols.mean() - want) < 2.5, (t, cols.mean(), want)

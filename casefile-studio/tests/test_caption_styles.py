"""Caption styles (v0.4.25): presets shared with the preview, ASS output,
bundled fonts, and a real libass render that matches the style."""
import json
import shutil
import subprocess

import numpy as np
import pytest

import captionstyle as cs
import renderer

CUES = [{"start": 0.0, "end": 2.0, "text": "Her name was Jaela Hilton and she was seventeen"}]


def test_default_style_is_the_old_look():
    line = cs.style_line(cs.normalise(None), 1280, 720)
    # Same font, size, box, padding and height as before styles existed.
    assert line == "Style: Default,DejaVu Sans,28.1,&H00FFFFFF,&H000000FF,&H70000000,&H66000000,0,0,0,0,100,100,0,0,3,2.0,0.0,2,80,80,54,1"


def test_normalise_clamps_and_ignores_junk():
    s = cs.normalise({"preset": "pop", "size": 9, "words": 99, "color": "red", "font": "comic", "animation": "spin", "box": "yes", "evil": 1})
    assert s["preset"] == "pop" and s["size"] == 0.1 and s["words"] == 12
    assert s["color"] == "#FFFFFF" and s["font"] == "inter-black" and s["animation"] == "pop" and s["box"] is False
    assert "evil" not in s
    assert cs.normalise({"preset": "nope"})["preset"] == "documentary"


def test_every_font_file_is_bundled_and_its_ratio_is_right():
    fontTools = pytest.importorskip("fontTools.ttLib")
    for key, f in cs.FONTS.items():
        path = cs.FONT_DIR / f["file"]
        assert path.is_file(), key
        t = fontTools.TTFont(str(path))
        os2 = t["OS/2"]
        assert abs(t["head"].unitsPerEm / (os2.usWinAscent + os2.usWinDescent) - f["ratio"]) < 0.001, key
        names = {t["name"].getDebugName(1), t["name"].getDebugName(16)}
        assert f["ass"] in names, (key, names)


def test_words_per_caption_and_highlight_events():
    s = {"preset": "highlight"}  # 4 words, uppercase, highlight
    text = cs.ass(CUES, 1280, 720, s)
    events = [l for l in text.splitlines() if l.startswith("Dialogue:")]
    assert len(events) == 9  # one per word: each word lights up in turn
    assert "{\\c&H004DD8FF}HER{\\r} NAME WAS JAELA" in events[0]
    assert events[3].endswith("HER NAME WAS {\\c&H004DD8FF}JAELA{\\r}")
    assert __import__("re").sub(r"\{[^}]*\}", "", events[4]).endswith("HILTON AND SHE WAS") and events[-1].split(",")[2] == "0:00:02.00"
    starts = [e.split(",")[1] for e in events]
    assert starts == sorted(starts)
    pop = cs.ass(CUES, 1280, 720, {"preset": "pop"})
    assert pop.count("Dialogue:") == 3 and "\\t(0,140,\\fscx100\\fscy100)" in pop
    whole = cs.ass(CUES, 1280, 720, {"preset": "documentary"})
    assert whole.count("Dialogue:") == 1 and "Her name was Jaela Hilton and she was seventeen" in whole


def test_chunks_keep_time_and_order():
    out = cs.chunks([{"start": 1, "end": 3, "text": "a bb ccc dddd eeeee"}], 2)
    assert [c["words"] for c in out] == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert out[0]["start"] == 1 and abs(out[-1]["end"] - 3) < 1e-9
    assert all(a["end"] <= b["start"] + 1e-9 for a, b in zip(out, out[1:]))


def test_preview_and_export_split_captions_the_same_way():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    scene = {"duration": 7.5, "narration": "One two three four five six seven eight nine ten eleven twelve thirteen"}
    js = f"""
    const m = await import("./web/src/captionStyle.js");
    const scene = {json.dumps(scene)};
    console.log(JSON.stringify([0, 3, 4].map((n) => m.chunks(m.sceneCaptions(scene), n))));
    """
    got = json.loads(subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, check=True, cwd=cs.ROOT).stdout)
    want = [cs.chunks(renderer.scene_captions(scene), n) for n in (0, 3, 4)]
    for g, w in zip(got, want):
        assert [c["words"] for c in g] == [c["words"] for c in w]
        assert all(abs(a["start"] - b["start"]) < 1e-9 and abs(a["end"] - b["end"]) < 1e-9 for a, b in zip(g, w))


def frame(ass_text, tmp_path, t=0.5):
    path = tmp_path / "c.ass"
    path.write_text(ass_text)
    out = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x404040:s=1280x720:d=2", "-vf",
                    cs.filter_arg(path.as_posix()), "-ss", str(t), "-frames:v", "1", str(out)], check=True)
    from PIL import Image
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def test_libass_draws_the_style_where_the_preview_puts_it(tmp_path):
    img = frame(cs.ass(CUES, 1280, 720, {"preset": "highlight"}), tmp_path, 0.1)
    yellow = (img[:, :, 0] > 200) & (img[:, :, 1] > 180) & (img[:, :, 2] < 120)
    white = (img.min(axis=2) > 235)
    assert yellow.sum() > 300 and white.sum() > 300  # the active word is yellow, the rest white
    rows = np.where(white | yellow)[0]
    bottom = 720 - rows.max()
    # The line box starts at position x height (0.14 x 720 = 101 px); capitals sit above the descent.
    assert 100 <= bottom <= 135, bottom  # + the font's descent below capitals
    big = frame(cs.ass(CUES, 1280, 720, {"preset": "highlight", "size": 0.08}), tmp_path, 0.1)
    tall = lambda im: np.ptp(np.where(im.min(axis=2) > 235)[0])
    assert tall(big) > tall(img) * 1.3  # size changes the size
    news = frame(cs.ass(CUES, 1280, 720, {"preset": "news"}), tmp_path, 0.1)
    red = (news[:, :, 0] > 150) & (news[:, :, 1] < 60) & (news[:, :, 2] < 60)
    assert red.sum() > 5000  # the red box


def test_project_style_is_saved_and_fonts_are_served(isolated):
    c, _ = isolated
    p = c.post("/api/projects", json={"title": "Caption QA", "mode": "narration"}).json()
    url = "/api/projects/" + p["id"]
    r = c.patch(url, json={"caption_style": {"preset": "news", "size": 0.05, "junk": 1}})
    assert r.status_code == 200, r.text
    saved = c.get(url).json()["caption_style"]
    assert saved["preset"] == "news" and saved["size"] == 0.05 and "junk" not in saved
    assert c.get("/assets/fonts/Inter-Black.otf").status_code == 200  # the preview loads the same font files

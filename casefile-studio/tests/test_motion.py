"""v0.4.52 Motion graphics: the data, reading the narration, word sync, drawing, the cache,
the export layer and the API."""
import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

import motion
import renderer
from storage import ROOT


def item(**kw):
    base = {"template": "findings", "start": 1.0, "end": 9.0, "heading": "KEY FINDINGS", "title": "What the records showed",
            "lines": [{"text": "Phone records placed him near the scene", "at": 2.0},
                      {"text": "Video showed the car on Nebraska Avenue", "at": 4.0}]}
    base.update(kw)
    return motion.normalise_item(base)


# ------------------------------------------------------------------ the data

def test_off_by_default_and_only_approved_items_export():
    assert motion.normalise(None) == {"enabled": False, "items": []}
    a, b = item(id="a", status="approved"), item(id="b", start=20, end=28)
    assert b["status"] == "draft"
    assert motion.exported({"motion": {"enabled": False, "items": [a, b]}}) == []
    assert [x["id"] for x in motion.exported({"motion": {"enabled": True, "items": [a, b]}})] == ["a"]
    assert motion.caption_gaps({"motion": {"enabled": True, "items": [a]}}) == [(1.0, 9.0)]
    a2 = dict(a, hide_captions=False)
    assert motion.caption_gaps({"motion": {"enabled": True, "items": [a2]}}) == []


def test_normalise_keeps_everything_in_range():
    x = item(end=500, size=9, speed=0, x=3, accent="red", font="comic", enter="spin", layout="nope",
             lines=[{"text": "  a   b ", "at": -5}, {"text": ""}, "junk"])
    assert x["end"] == 1.0 + motion.LIM["length"][1]
    assert x["size"] == motion.LIM["size"][1] and x["speed"] == motion.LIM["speed"][0] and x["x"] == motion.LIM["xy"][1]
    assert (x["accent"], x["font"], x["enter"], x["layout"]) == (motion.DEF["accent"], "oswald", "mask", "auto")
    assert x["lines"] == [{"text": "a b", "label": "", "kind": "", "emphasis": False, "at": 1.0}]
    assert motion.normalise_item({"template": "nope"}) is None
    # a photo background needs one of your own images; else charcoal (nothing is made up)
    assert item(background="photo")["background"] == "charcoal"  # no image chosen
    assert motion.normalise({"items": [item(background="photo", photo_id="p1")]}, {"p1"})["items"][0]["background"] == "photo"
    assert motion.normalise({"items": [item(background="photo", photo_id="p1")]}, set())["items"][0]["background"] == "charcoal"
    many = motion.normalise({"items": [item(id=f"i{n}") for n in range(60)]})
    assert len(many["items"]) == motion.LIM["items"]


# ------------------------------------------------------------------ the narration on the timeline

def guide_project():
    """Two narration scenes around a soundbite, with an exact word clock (as a guide project)."""
    n1 = "Detectives traced the phone. On December 9, he escaped. At 3:33 p.m. he was filmed on Rome Avenue."
    n2 = "He was charged with murder. A jury found him guilty. He was sentenced to forty years in prison."
    words, t = [], 10.0
    for w in n1.split():
        words.append({"word": w, "normalized": motion._norm(w), "start": t, "end": t + 0.3})
        t += 0.4
    t2 = 30.0
    for w in n2.split():
        words.append({"word": w, "normalized": motion._norm(w), "start": t2, "end": t2 + 0.3})
        t2 += 0.4
    scenes = [
        {"id": "a", "chapter": "CHAPTER 2 — THE SEARCH", "narration": n1, "duration": 8.0, "audio_start": 10.0, "audio_duration": 8.0},
        {"id": "b", "chapter": "CHAPTER 2 — THE SEARCH", "narration": "", "insert_audio": True, "duration": 4.0},
        {"id": "c", "chapter": "CHAPTER 3 — TRIAL", "narration": n2, "duration": 8.0, "audio_start": 30.0, "audio_duration": 8.0},
    ]
    return {"scenes": scenes, "episode": {"timings": {"words": words}}}


def test_words_follow_the_episode_word_clock_on_the_timeline():
    p = guide_project()
    w = motion.timeline_words(p)
    assert w[0] == {"w": "Detectives", "t": 0.0, "e": 0.3, "scene": 0}
    assert w[4]["w"] == "On" and w[4]["t"] == pytest.approx(1.6)
    # scene c starts at 8 + 4 = 12 s on the timeline; its narration at 30 s in the narration audio
    c0 = next(x for x in w if x["scene"] == 2)
    assert c0["w"] == "He" and c0["t"] == pytest.approx(12.0)
    assert not any(x["scene"] == 1 for x in w)  # the soundbite has no narration words
    s = motion.sentences(w)
    assert [x["text"] for x in s][:3] == ["Detectives traced the phone.", "On December 9, he escaped.", "At 3:33 p.m. he was filmed on Rome Avenue."]


def test_words_without_a_word_clock_use_captions_then_the_scene():
    p = {"scenes": [{"narration": "One two three four.", "duration": 4.0, "captions": [{"start": 2.0, "end": 4.0, "text": "One two three four."}]},
                    {"narration": "Five six.", "duration": 2.0}]}
    w = motion.timeline_words(p)
    assert [round(x["t"], 2) for x in w] == [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]


def test_sentences_split_after_pm_only_before_a_new_sentence():
    words = [{"w": x, "t": i, "e": i + 0.5, "scene": 0} for i, x in enumerate(
        "Between 2:41 and 3:27 p.m. Trial reporting said so. At 3 p.m. on Friday he left.".split())]
    assert [s["text"] for s in motion.sentences(words)] == [
        "Between 2:41 and 3:27 p.m.", "Trial reporting said so.", "At 3 p.m. on Friday he left."]


# ------------------------------------------------------------------ drafts: only the narration's own words, on time

def test_draft_uses_the_narration_verbatim_and_syncs_each_line():
    p = guide_project()
    d = motion.draft(p, "findings", 0.0, 8.0)
    narr = p["scenes"][0]["narration"]
    assert [l["text"] for l in d["lines"]] == ["Detectives traced the phone", "On December 9, he escaped", "At 3:33 p.m. he was filmed on Rome Avenue"]
    assert all(l["text"] in narr for l in d["lines"])
    assert [l["at"] for l in d["lines"]] == [0.0, 1.6, 3.6]  # when the narrator starts each sentence
    assert d["start"] == 0.0 and d["end"] >= 3.2 + motion.TIM["hold"]
    assert d["heading"] == "CHAPTER 2 · KEY FINDINGS" and d["title"] == "THE SEARCH"
    assert d["status"] == "draft" and d["source"] == "manual"


def test_timeline_and_legal_drafts():
    p = guide_project()
    t = motion.draft(p, "timeline", 0.0, 8.0)
    labels = [l["label"] for l in t["lines"]]
    assert labels == ["DECEMBER 9", "3:33 P.M."]
    assert t["lines"][0]["text"] == "He escaped"  # the date opened the sentence: lifted out
    lg = motion.draft(p, "legal", 12.0, 20.0)
    assert [l["label"] for l in lg["lines"]] == ["CHARGED", "CONVICTED", "SENTENCED"]
    assert motion.draft(p, "legal", 8.5, 11.5) is None  # the soundbite: no narration


# ------------------------------------------------------------------ suggestions

def documentary(*chapters):
    """Scenes of narration (5 s per sentence); a chapter is (name, [sentences], extra scene keys)."""
    scenes = []
    for name, sents, extra in chapters:
        for s in sents:
            scenes.append({"id": f"s{len(scenes)}", "chapter": name, "narration": s, "duration": 5.0, **extra})
    return {"scenes": scenes}


FILLER = ["The town was quiet that year.", "Most people knew each other.", "The streets were familiar.",
          "Life went on as usual.", "The seasons came and went.", "Nothing seemed out of place."]
CHRONO = ["On March 3, detectives received the first tip.", "On March 9, investigators searched the house.",
          "On March 14, the lab returned the results.", "On March 20, records showed a second phone.", "On March 28, police made an arrest."]


def test_suggestions_find_the_chronology_and_skip_the_cold_open_and_the_end():
    p = documentary(("OPENING HOOK", CHRONO, {}), ("CHAPTER 1 — THE TOWN", FILLER * 3, {}),
                    ("CHAPTER 2 — THE INVESTIGATION", CHRONO, {}), ("CHAPTER 3 — AFTER", FILLER * 3, {}))
    got = motion.suggest(p)
    assert len(got) == 1
    g = got[0]
    assert g["template"] == "timeline" and g["status"] == "suggested" and g["source"] == "auto"
    assert g["start"] >= 5 * (5 + 18)  - motion.TIM["lead"] - 0.01  # in chapter 2, not the cold open
    assert [l["label"] for l in g["lines"]][:3] == ["MARCH 3", "MARCH 9", "MARCH 14"]
    assert "dated events" in g["reason"]


def test_no_suggestions_when_nothing_justifies_one():
    assert motion.suggest(documentary(("CHAPTER 1 — THE TOWN", FILLER * 8, {}))) == []
    assert motion.suggest({"scenes": []}) == []


def test_suggestions_avoid_soundbites_family_passages_and_the_cta():
    family = ["On March 3, his mother remembered his smile.", "On March 9, the family held a vigil.",
              "On March 14, his father spoke of his dreams.", "On March 20, they planted a tree.", "On March 28, they gathered again."]
    p = documentary(("CHAPTER 1 — A", FILLER * 3, {}), ("CHAPTER 2 — FAMILY", family, {}), ("CHAPTER 3 — B", FILLER * 3, {}))
    assert motion.suggest(p) == []
    p = documentary(("CHAPTER 1 — A", FILLER * 3, {}), ("CHAPTER 2 — SOUNDBITES", CHRONO, {"insert_audio": True}), ("CHAPTER 3 — B", FILLER * 3, {}))
    assert motion.suggest(p) == []


def test_courtroom_arguments_are_never_offered_as_findings():
    trial = ["The prosecutor said he planned it.", "But the defense argued the video showed self-defense.",
             "The prosecutor told jurors the records were clear.", "However, the defense said the phone was shared.",
             "Jurors were shown the footage again."]
    p = documentary(("CHAPTER 1 — A", FILLER * 3, {}), ("CHAPTER 2 — TRIAL", trial, {}), ("CHAPTER 3 — B", FILLER * 3, {}))
    assert not any(x["template"] == "contrast" for x in motion.suggest(p))
    alibi = ["He told detectives he was home all night.", "But phone records showed his phone near the scene at midnight.",
             "He claimed he never left the house.", "However, video from a neighbour showed his car leaving at 11 p.m.",
             "Investigators also found his receipts."]
    p = documentary(("CHAPTER 1 — A", FILLER * 3, {}), ("CHAPTER 2 — THE ALIBI", alibi, {}), ("CHAPTER 3 — B", FILLER * 3, {}))
    got = motion.suggest(p)
    assert [x["template"] for x in got] == ["contrast"]
    kinds = [l["kind"] for l in got[0]["lines"]]
    assert kinds[:4] == ["statement", "finding", "statement", "finding"]
    assert got[0]["lines"][1]["emphasis"] is True


def test_suggestions_keep_their_distance_and_respect_the_maximum():
    chapters = []
    for n in range(10):
        chapters += [(f"CHAPTER {n + 1} — X", FILLER * 3, {}), (f"CHAPTER {n + 1} — X", CHRONO, {})]
    got = motion.suggest(documentary(*chapters))
    assert 2 <= len(got) <= motion.SPEC["suggest"]["max"]
    starts = [x["start"] for x in got]
    assert all(b - a >= motion.SPEC["suggest"]["min_gap"] for a, b in zip(starts, starts[1:]))
    assert sum(1 for x in got if x["template"] == "timeline") <= 2  # varied, not the same card again and again


def test_suggestions_on_the_real_projects_if_present():
    path = ROOT / "data" / "projects" / "1a5bbba59d244274.json"
    if not path.exists():
        pytest.skip("no local project")
    got = motion.suggest(json.loads(path.read_text()))
    assert 1 <= len(got) <= 5
    narration = " ".join(s["narration"] for s in json.loads(path.read_text())["scenes"])
    for g in got:
        for l in g["lines"]:
            assert l["text"].rstrip("…") in narration or l["text"].lower() in narration.lower()


# ------------------------------------------------------------------ drawing

def ink(im, box):
    a = np.asarray(im.convert("RGB").crop(box), dtype=int)
    return int((a.max(axis=2) > 200).sum())  # bright (text) pixels


@pytest.mark.parametrize("tpl", ["findings", "timeline", "contrast", "legal"])
@pytest.mark.parametrize("size", [(1280, 720), (720, 1280)])
def test_every_template_draws_and_long_text_fits_inside(tpl, size):
    long = "A long sentence from the narration that goes on and on about the records and the video evidence placed in order " * 2
    lines = [{"text": long[:200], "at": 2 + k, "label": lab, "kind": kind} for k, (lab, kind) in
             enumerate(zip(["MARCH 3", "CHARGED", "MARCH 9", "CONVICTED", "MAY 1", "SENTENCED"], ["statement", "finding"] * 3))]
    it = item(template=tpl, end=20, lines=lines, title="A very long title that will need two lines to fit in the frame")
    W, H = size
    lay = motion.build(it, W, H)
    for el in lay.els:
        assert el.x >= -2 and el.y >= -2 and el.x + el.img.width <= W + 2 and el.y + el.img.height <= H * 0.95, (tpl, el)
    im = motion.frame(lay, 15 * 24)
    assert im.size == (W, H) and ink(im, (0, 0, W, H)) > 2000


def test_each_line_appears_when_it_is_said_and_everything_leaves():
    it = item(start=0, end=10, lines=[{"text": "FIRST LINE OF TEXT", "at": 2.0}, {"text": "SECOND LINE OF TEXT", "at": 5.0}])
    lay = motion.build(it, 1280, 720)
    second = max((el for el in lay.els if el.t_in >= 4.9), key=lambda el: el.img.width)  # its text
    box = (second.x, second.y, second.x + second.img.width, second.y + second.img.height)
    assert ink(motion.frame(lay, int(4.9 * 24)), box) == 0  # not yet said
    assert ink(motion.frame(lay, int(5.8 * 24)), box) > 50  # said: shown and held
    assert ink(motion.frame(lay, int(8.5 * 24)), box) > 50
    last = motion.frame(lay, lay.frames - 1)
    assert np.asarray(last)[..., 3].max() < 40  # back to the footage at the end
    first = motion.frame(lay, 0)
    assert np.asarray(first)[..., 3].max() < 40
    assert np.asarray(motion.frame(lay, 3 * 24))[..., 3].min() == 255  # charcoal: covers the picture


def test_identical_frames_are_drawn_once_and_match():
    it = item(start=0, end=14)
    lay = motion.build(it, 640, 360)
    frames, unique = motion.plan(lay)
    assert len(frames) == 14 * 24 and unique < len(frames) * 0.8
    k = max(set(frames), key=frames.count)
    a, b = [n for n, x in enumerate(frames) if x == k][:2]
    assert np.array_equal(np.asarray(motion.frame(lay, a)), np.asarray(motion.frame(lay, b)))


def test_hide_cues_removes_only_what_the_graphic_covers():
    cues = [{"start": 0, "end": 2, "text": "a"}, {"start": 2, "end": 4, "text": "b"}, {"start": 4, "end": 6, "text": "c"}]
    out = renderer.hide_cues(cues, [(1.0, 4.1)])
    assert out == [{"start": 0, "end": 1.0, "text": "a"}, {"start": 4.1, "end": 6, "text": "c"}]
    assert renderer.hide_cues(cues, []) == cues


# ------------------------------------------------------------------ the export

def grab(out, t, w=854, h=480):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(int)


@pytest.fixture
def media(tmp_path, monkeypatch):
    folder = ROOT / "qa" / ("v052-" + tmp_path.name)
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer, "DATA", tmp_path / "data")
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def test_render_shows_the_approved_graphic_only_in_its_window_and_caches_it(tmp_path, media):
    Image.new("RGB", (640, 360), (40, 140, 60)).save(media / "green.png")
    a = {"id": "g", "kind": "image", "path": str(media / "green.png"), "name": "green.png", "width": 640, "height": 360}
    sc = [{"id": "s1", "title": "", "narration": "Phone records placed him near the scene.", "duration": 3.0, "asset_id": "g", "motion": "none", "show_title": False},
          {"id": "s2", "title": "", "narration": "Video showed the car.", "duration": 4.0, "asset_id": "g", "motion": "none", "show_title": False}]
    g = item(id="m1", status="approved", start=1.0, end=6.0,
             lines=[{"text": "Phone records placed him near the scene", "at": 1.6}, {"text": "Video showed the car", "at": 3.5}])
    p = {"id": "mg", "title": "mg", "look": "natural", "captions": False, "music_volume": 0, "assets": [a], "scenes": sc,
         "motion": {"enabled": True, "items": [g]}}
    out = tmp_path / "mg.mp4"
    r1 = renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out, lambda *a: None, lambda: False)
    green = lambda px: px[1] > 110 and px[0] < 90
    assert green(grab(out, 0.5)[240, 427])  # before: the footage
    mid = grab(out, 3.2)  # across the scene cut at 3 s: the graphic
    assert mid[240, 800].max() < 60  # charcoal right side
    assert (mid.max(axis=2) > 200).sum() > 1500  # its text
    assert green(grab(out, 6.6)[240, 427])  # after: the footage again, unchanged
    assert renderer.probe(out)["duration"] == pytest.approx(7.0, abs=0.06)  # timeline untouched
    mg = r1["telemetry"]["motion_graphics"] if "telemetry" in r1 else None
    # a second export draws nothing again (cache by content)
    out2 = tmp_path / "mg2.mp4"
    r2 = renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out2, lambda *a: None, lambda: False)
    cache = tmp_path / "data" / "cache" / "motion"
    assert len(list(cache.iterdir())) == 1
    report = json.dumps(r2)
    assert '"drawn": 0' in report, report[:500]
    # switched off: the picture is exactly as without motion graphics
    p["motion"]["enabled"] = False
    out3 = tmp_path / "mg3.mp4"
    renderer.render(p, {"resolution": "480p", "draft": False, "captions": False}, out3, lambda *a: None, lambda: False)
    assert green(grab(out3, 3.2)[240, 800])


# ------------------------------------------------------------------ the API

def test_api_motion_flow(isolated):
    client, root = isolated
    p = client.post("/api/projects", json={"title": "Motion", "topic": "t"}).json()
    pid = p["id"]
    assert p.get("motion") in (None, {"enabled": False, "items": []})
    scenes = [{"id": f"s{k}", "title": "", "chapter": "CHAPTER 2 — THE INVESTIGATION", "narration": s, "duration": 5.0} for k, s in enumerate(CHRONO)]
    p = client.patch(f"/api/projects/{pid}", json={"scenes": scenes}).json()
    n = client.get(f"/api/projects/{pid}/motion/narration").json()
    assert len(n["sentences"]) == 5 and n["sentences"][1]["start"] == pytest.approx(5.0)
    d = client.post(f"/api/projects/{pid}/motion/draft", json={"template": "timeline", "start": 0, "end": 15}).json()["item"]
    assert [l["label"] for l in d["lines"]] == ["MARCH 3", "MARCH 9", "MARCH 14"]
    assert client.post(f"/api/projects/{pid}/motion/draft", json={"template": "x", "start": 0, "end": 5}).status_code == 422
    p = client.patch(f"/api/projects/{pid}", json={"motion": {"enabled": True, "items": [d]}}).json()
    assert p["motion"]["enabled"] and p["motion"]["items"][0]["id"] == d["id"]
    d2 = dict(p["motion"]["items"][0], status="approved")
    p = client.patch(f"/api/projects/{pid}", json={"motion": {"enabled": True, "items": [d2]}}).json()
    assert p["history"]["undo"][-1] == "Approve motion graphic"
    plan = client.post(f"/api/projects/{pid}/motion/plan", json={"item": d2}).json()
    assert plan["fps"] == 24 and len(plan["frames"]) == round((d2["end"] - d2["start"]) * 24) and plan["width"] == 1280
    r = client.get(f"/api/motion/{plan['hash']}/{plan['frames'][60]}.webp")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    assert client.get("/api/motion/zzzz/0.webp").status_code == 404
    p = client.post(f"/api/projects/{pid}/undo").json()
    assert p["motion"]["items"][0]["status"] == "draft"
    p = client.patch(f"/api/projects/{pid}", json={"motion": {"enabled": True, "items": []}}).json()
    assert p["history"]["undo"][-1] == "Remove motion graphic"
    assert p["scenes"][0]["narration"] == CHRONO[0]  # the layer never touches the scenes


def test_text_is_made_smaller_never_cut():
    it = item(template="findings", layout="split", end=20, title="What surveillance showed that afternoon",
              lines=[{"text": "A long line of narration about the recordings from nearby homes and what each camera captured", "at": 2 + k} for k in range(5)])
    for W, H in ((1280, 720), (854, 480)):
        motion._CUT.n = 0
        lay = motion.build(it, W, H)
        assert motion._CUT.n == 0, (W, H)  # nothing ended in "…"

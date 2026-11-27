"""v0.4.65 Automatic presentation (optional; off by default), the contradiction fit, the digital readability
and the smoother standard reveal."""
import numpy as np
import pytest

import cinematic
import motion
import presentation
from cinegfx import anim as A
from test_cinematic import javits_project, _project


def _cat(key):
    return cinematic.registry()["truecrime"].categories[key]


def _shots_project(spec, chapters=None):
    """scenes from [(seconds, kind, cue show text or "")]; kind "video" / "image" / "" (no picture)."""
    assets, scenes, cues = [], [], []
    for i, (sec, kind, show) in enumerate(spec):
        aid = f"a{i}" if kind else ""
        if kind:
            assets.append({"id": aid, "kind": kind, "name": f"S{i:02d}.mp4"})
        cue = f"C{i + 1:02d}"
        cues.append({"id": cue, "number": i + 1, "show": show, "care": ""})
        scenes.append({"id": f"s{i}", "duration": sec, "asset_id": aid, "guide_cue_id": cue,
                       "chapter": (chapters or {}).get(i, "CHAPTER 1 — START")})
    return {"scenes": scenes, "assets": assets, "episode": {"guide": {"cues": cues}}}


def test_a_design_that_needs_its_screen_stays_full_screen():
    p = _shots_project([(5, "video", "a"), (20, "video", "Show the briefing"), (5, "video", "b")])
    for key in ("contradiction", "digital"):
        r = presentation.propose_one(p, {"start": 6.0, "end": 22.0}, _cat(key))
        assert r["mode"] == "own" and r["look"] == {"background": "own"}
        assert any("own screen" in x for x in r["reasons"])


def test_legal_goes_over_footage_and_findings_sits_beside_it():
    p = _shots_project([(40, "video", "Courthouse exterior")])
    r = presentation.propose_one(p, {"start": 10.0, "end": 22.0}, _cat("legal"))
    assert r["mode"] == "footage" and r["look"] == {"background": "footage"}
    r = presentation.propose_one(p, {"start": 10.0, "end": 22.0}, _cat("findings"))
    assert r["mode"] == "partial" and r["look"]["background"] == "footage"
    assert 0.8 <= r["look"]["place"]["scale"] < 1 and r["look"]["place"]["x"] == -1.0
    # over a still picture: over it whole, not a small layout beside a photo
    p2 = _shots_project([(40, "image", "Portrait")])
    assert presentation.propose_one(p2, {"start": 10.0, "end": 22.0}, _cat("findings"))["mode"] == "footage"


def test_no_picture_under_it_or_busy_footage_means_full_screen():
    blank = _shots_project([(40, "", "")])
    assert presentation.propose_one(blank, {"start": 10.0, "end": 22.0}, _cat("legal"))["mode"] == "own"
    busy = _shots_project([(3, "video", "a"), (3, "video", "b"), (3, "video", "c"), (3, "video", "d"), (30, "video", "e")])
    r = presentation.propose_one(busy, {"start": 1.0, "end": 13.0}, _cat("legal"))
    assert r["mode"] == "own" and any("shots under it" in x for x in r["reasons"])


def test_a_hidden_scripted_shot_goes_over_footage_unless_the_graphic_opens_a_chapter():
    p = _shots_project([(5, "video", "a"), (8, "video", "Show the police announcement"), (20, "video", "c")])
    r = presentation.propose_one(p, {"start": 3.0, "end": 16.0}, _cat("timeline"))
    assert r["mode"] == "footage" and any("C02" in x and "police announcement" in x for x in r["reasons"])
    # the same graphic opening a chapter: full screen marks it, and it says which shot that hides
    chapters = presentation._chapter_starts(_shots_project([(5, "video", "a"), (8, "video", "x")], {1: "CHAPTER 2 — NEXT"}))
    r = presentation.propose_one(p, {"start": 4.0, "end": 17.0}, _cat("turning"), chapters)
    assert r["mode"] == "own" and any("opens Chapter 2" in x and "C02" in x for x in r["reasons"])
    # a scene split on the same footage and script line is one shot, not two cuts
    split = _shots_project([(4, "video", "a"), (4, "video", "a")])
    split["scenes"][1]["asset_id"] = "a0"
    split["scenes"][1]["guide_cue_id"] = "C01"
    assert len(presentation._shots(split, 0.0, 8.0)) == 1


def test_off_by_default_and_nothing_changes_until_applied(isolated):
    client, root = isolated
    pid, p = _project(client, javits_project())
    r = client.post(f"/api/projects/{pid}/motion/suggest", json={"engine": "cinematic"}).json()
    assert "present" not in r["project"]["motion"]  # off by default
    before = r["project"]["motion"]
    props = client.post(f"/api/projects/{pid}/motion/present", json={}).json()["proposals"]
    assert {x["id"] for x in props} == {x["id"] for x in before["items"] if x["template"] == "cinematic"}
    assert all(x["reasons"] and x["mode"] in ("own", "footage", "partial") for x in props)
    assert client.get(f"/api/projects/{pid}").json()["motion"] == before  # proposing saves nothing
    # the tick box round-trips; unticked it is dropped
    m = dict(before, present=True)
    assert client.patch(f"/api/projects/{pid}", json={"motion": m}).json()["motion"]["present"] is True
    assert "present" not in client.patch(f"/api/projects/{pid}", json={"motion": before}).json()["motion"]
    # the Javits test project has no footage: every graphic stays full screen, so applying changes nothing
    r = client.post(f"/api/projects/{pid}/motion/present", json={"apply": [x["id"] for x in props]}).json()
    assert r["applied"] == 0 and all(x["same"] for x in r["proposals"])


def test_apply_keeps_the_rest_of_the_look():
    prop = {"mode": "partial", "look": {"background": "footage", "place": {"scale": 0.86, "x": -1.0, "y": 0.0}}}
    out = presentation.apply({"palette": "B", "background": "photo", "photo_id": "x", "size": 1.1}, prop)
    assert out == {"palette": "B", "background": "footage", "place": prop["look"]["place"], "size": 1.1}
    # back to full screen undoes the partial this tool made, but keeps a size you chose yourself
    full = {"mode": "own", "look": {"background": "own"}}
    assert "place" not in presentation.apply(out, full)
    mine = {"scale": 0.9, "x": 0.5, "y": 0.0}
    assert presentation.apply({"place": mine}, full)["place"] == mine


# ------------------------------------------------------------------ visual refinements

def test_standard_reveal_is_smoother_but_not_slower():
    fps = 24
    steps = [A.out_smooth(k / fps / A.FAST) for k in range(1, 8)]
    old = [A.out_expo(k / fps / A.FAST) for k in range(1, 8)]
    assert steps[0] < old[0] and steps[0] > 0.4       # less of the move lands in the first frame (it reads as motion)
    assert A.out_smooth(1.0) == 1.0 and A.ease(0.28, 0.0) == 1.0  # same duration: done at the same frame
    assert all(b >= a for a, b in zip(steps, steps[1:]))
    assert A.out_smooth(0.6) > 0.9  # settled well before the end


def test_contradiction_fills_its_columns():
    """The statements take the largest size that fits and the block is centred in the space left."""
    p = javits_project()
    it = next(x for x in cinematic.suggest(p, []) if x["category"] == "contradiction")
    it = motion.normalise({"items": [it]})["items"][0]
    g = cinematic.build(it)
    assert 44 <= g.fs <= 56 and g._bottom(g.fs) <= g.BOTTOM
    assert g.fs > 44  # the Javits statements are short: bigger than the old fixed 44 px
    assert g.fs == max(f for f in g.FS if g._bottom(f) <= g.BOTTOM)
    # a very long statement falls back to the old size and the old top
    g2 = cinematic.build(dict(it, payload=dict(it["payload"])))
    g2.cards = [dict(k, text=(k["text"] + " ") * 4) for k in g2.cards]
    g2._fit()
    assert g2.fs == 44 and g2.dy == 0


def test_digital_detail_text_is_brighter():
    from cinegfx.look import contrast
    th = _cat("digital").theme
    assert contrast(th.muted, th.bg) >= 7.5  # was 5.3:1 with #5E8C88 (detail lines read dim)
    for _, _, c in [x for x in _cat("digital").looks["palettes"] if x[2]]:
        assert contrast(c["muted"], c["bg"]) >= 7.5

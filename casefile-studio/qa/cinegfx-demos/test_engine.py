"""Engine tests for cinegfx (kept beside the demos until the engine is approved for integration; they move
to tests/ with it). Run: PATH=$PWD/.venv/bin:$PATH .venv/bin/python -m pytest qa/cinegfx-demos/test_engine.py -q"""
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cinegfx import core, render, story as S, timing as TM  # noqa: E402
import make_demos as M  # noqa: E402

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def story():
    return S.parse_script((HERE / "javits-script.md").read_text())


@pytest.fixture(scope="module")
def coll():
    return core.load_collections()["truecrime"]


@pytest.fixture(scope="module")
def texts():
    return json.loads((HERE / "narration" / "texts.json").read_text())


def test_story_people_roles_and_shared_surname(story):
    assert story.subject == "Javits Frimpong"
    assert story.people["Joseph Kenny"].role == "Chief of Detectives"
    assert story.people["Thomas Frimpong"].role == "father"
    assert story.people["Scott Krompinger"].role == "Judge"
    # "Frimpong" is shared by father and son, so it is an alias of neither
    assert "Frimpong" not in story.people["Javits Frimpong"].aliases


def test_relative_dates_resolve_against_the_story(story):
    by_text = {s.text[:30]: s for s in story.sentences}
    that_day = next(s for s in story.sentences if s.text.startswith("That day, the 17-year-old was arraigned"))
    assert that_day.dates[0].date == dt.date(2026, 11, 11) and that_day.dates[0].relative
    walk = next(s for s in story.sentences if "following day" in s.text)
    assert dt.date(2026, 11, 7) in [d.date for d in walk.dates]
    assert story.incident_date() == dt.date(2026, 10, 29)
    assert by_text


def test_relayed_and_negated_claims(story):
    s = next(s for s in story.sentences if s.text.startswith("Ben Crump said prosecutors"))
    c = s.claims[0]
    assert c.source == "prosecutors" and c.via == "Ben Crump" and c.negated
    father = next(s for s in story.sentences if s.text.startswith("Javits’s father had said"))
    assert father.claims[0].source == "Thomas Frimpong" and not father.claims[0].negated
    no5 = next(s for s in story.sentences if "No. 5 train" in s.text)
    assert not no5.claims[0].negated  # "No. 5" is a route number, not a negation


@pytest.mark.parametrize("key", list(M.EXPECT))
def test_each_demo_window_is_classified_as_its_category_and_only_that(key, story, coll, texts):
    a, b = M.window_for(story, texts[key])
    scored = M.classify(story, coll, a, b)
    assert scored[0][1] == M.EXPECT[key]
    assert len(scored) == 1, f"{key} also matched {[s[1] for s in scored[1:]]}"


def test_selection_is_sparse_spaced_and_varied(story, coll):
    beats = core.select(story, coll)
    assert 3 <= len(beats) <= 8
    for x, y in zip(beats, beats[1:]):
        assert y.a >= x.b + 2  # never back-to-back
    assert len({b.category for b in beats}) == len(beats)  # no repeated composition in one episode this short


def test_new_niche_registers_without_touching_core(story):
    class Toy(core.Graphic):
        def build(self):
            self.cue(0.1, "pop-soft-1")

        def draw(self, canvas, t):
            pass

    def detect_scoreline(st, a, b):
        m = re.search(r"\b(\d+)[–-](\d+)\b", st.window_text(a, b))
        return (0.9, {"score": m.group(0)}, ["scoreline"]) if m else None

    sport = core.Collection()
    sport.key, sport.label = "football", "Football"
    from cinegfx.collections.truecrime import THEMES
    sport.add(core.Category("scoreline", "Scoreline", THEMES["turning"], detect_scoreline, Toy))
    core.register(sport)
    try:
        st = S.parse_script("# Final\n## Chapter 1 — The night\nThey won the final 3-1 on May 4. The city celebrated.\n")
        beats = core.select(st, core.REGISTRY["football"])
        assert [b.category for b in beats] == ["scoreline"] and beats[0].payload["score"] == "3-1"
    finally:
        core.REGISTRY.pop("football")


def test_timeline_alignment_snaps_sentence_ends_to_detected_pauses(texts):
    narr = texts["6-turning"]
    tl = TM.timeline_for(str(HERE / "narration" / "6-turning.mp3"), narr)
    q = next(w for w in tl.words if w.text == "arrest")
    on = next(w for w in tl.words if w.text == "On")
    pause = tl.pauses[0]
    assert abs(q.end - pause[0]) < 0.02 and abs(on.start - pause[1]) < 0.02
    back = TM.from_srt(TM.to_srt(tl))
    assert [w.text for w in back.words] == [w.text for w in tl.words]  # SRT round-trip keeps every word
    assert all(abs(x.start - y.start) < 0.6 for x, y in zip(back.words, tl.words))
    assert all(w.end <= x.start + 1e-6 for w, x in zip(tl.words, tl.words[1:]))


@pytest.mark.parametrize("key", list(M.EXPECT))
def test_frames_render_deterministically(key, story, coll, texts):
    a, b = M.window_for(story, texts[key])
    score, cat, payload, why = M.classify(story, coll, a, b)[0]
    tl = TM.timeline_for(str(HERE / "narration" / f"{key}.mp3"), texts[key])
    spec = ("truecrime", cat, core.Beat("truecrime", cat, a, b, score, payload, why), tl, str(HERE / "photos"))
    g1, g2 = render.build(spec), render.build(spec)
    for t in (0.0, g1.duration / 2, g1.duration - 0.6):
        f1, f2 = g1.frame(t), g2.frame(t)
        assert f1.size == (1920, 1080)
        assert hashlib.md5(f1.tobytes()).digest() == hashlib.md5(f2.tobytes()).digest()
    assert g1.cues and all(0 <= c.t <= g1.duration for c in g1.cues)
    from cinegfx import sfx
    for c in g1.cues:
        sfx._sound(c.sfx)  # every cue id exists in sfxlib


def test_no_blur_anywhere_in_the_engine():
    src = "".join(p.read_text() for p in (ROOT / "cinegfx").rglob("*.py"))
    assert not re.search(r"GaussianBlur|BoxBlur|ImageFilter|boxblur|gblur", src)


def test_engine_does_not_touch_the_production_motion_engine():
    src = "".join(p.read_text() for p in (ROOT / "cinegfx").rglob("*.py"))
    assert "import motion" not in src and "from motion" not in src

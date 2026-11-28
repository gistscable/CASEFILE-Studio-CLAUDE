"""v0.4.77 sports editorial engine: semantics, typesetting, families, fx, score, edit planning.

Everything here is synthetic (no broadcast footage, no RVM model needed) so it runs in CI.
"""
import numpy as np
import pytest
from PIL import Image

from cinegfx.sports import families as F
from cinegfx.sports import fx as FX
from cinegfx.sports import matte as M
from cinegfx.sports import score as SC
from cinegfx.sports import semantics as S
from cinegfx.sports import typeset as T
from cinegfx.sports.edit import Edit, Transition, encoder_args
from cinegfx.sports.footage import GRADES, Shot, grade


def _seg(text, at, heard):
    t = 0.0
    out = []
    for w in heard:
        out.append({"word": w, "start": t, "end": t + 0.3})
        t += 0.32
    return {"text": text, "at": at, "heard": out}


def _story():
    return S.timeline([
        _seg("Lionel Messi. The greatest of his time.", 0.0, ["Lionel", "Messi.", "The", "greatest", "of", "his", "time."]),
        _seg("On the sixth of April, twenty ten, at the Camp Nou, Arsenal came to town.", 4.0,
             ["On", "the", "6th", "of", "April,", "2010,", "at", "the", "Camp", "Nou,", "Arsenal", "came", "to", "town."]),
        _seg("One. In the twenty-first minute, from the edge of the box. Two. In the thirty-seventh minute, calmly past "
             "Almunia. Three. In the forty-second minute, a chip over the keeper.",
             10.0, ["1.", "In", "the", "21st", "minute,", "from", "the", "edge", "of", "the", "box.", "2.", "In", "the", "37th",
                    "minute,", "calmly", "past", "Almunia.", "3.", "In", "the", "42nd", "minute,", "a", "chip", "over", "the",
                    "keeper."]),
        _seg("Four goals. One night.", 21.0, ["4", "goals.", "One", "night."]),
    ])


def test_alignment_keeps_script_text_and_matches_spoken_numbers():
    ws = _story()
    texts = [w.text for w in ws]
    assert "sixth" in texts and "twenty-first" in [t.lower().strip(".,") for t in texts]
    # every word timed and monotonic: numbers heard as digits still align
    assert all(b.s >= a.s for a, b in zip(ws, ws[1:]))
    one = next(w for w in ws if w.text.startswith("One.") and w.s >= 10)
    assert abs(one.s - 10.0) < 1e-6


def test_analyse_finds_name_date_numbered_and_impact_without_overlap():
    els = S.analyse(_story())
    fams = [e.family for e in els]
    assert "name" in fams and "label" in fams and "numbered" in fams and "impact" in fams
    for a, b in zip(els, els[1:]):
        assert a.t_out <= b.t_in + 1e-6
    lab = next(e for e in els if e.family == "label")
    assert lab.data["lines"][0]["text"] == "6 APRIL 2010"
    num = next(e for e in els if e.family == "numbered")
    assert [p["n"] for p in num.data["items"]] == [1, 2, 3]
    assert num.data["items"][0]["label"].startswith("21'")
    # word-level sync: each point appears on its spoken number, not on a fixed grid
    assert [round(p["t"] - 10.0, 2) for p in num.data["items"]] == [0.0, round(11 * 0.32, 2), round(19 * 0.32, 2)]
    imp = next(e for e in els if e.family == "impact")
    assert imp.data["value"] == "4"


def test_no_fabrication_every_graphic_word_is_spoken():
    ws = _story()
    spoken = " ".join(w.text.upper() for w in ws)
    for e in S.analyse(ws):
        frags = [e.data.get("text", ""), e.data.get("value", ""), e.data.get("label", ""), e.data.get("sub", "")]
        for it in e.data.get("items", []) + e.data.get("lines", []):
            frags.append(it["label"] if isinstance(it, dict) and "label" in it else
                         it.get("text", "") if isinstance(it, dict) else it[0])
        for frag in frags:
            if not isinstance(frag, str):
                continue
            for tok in frag.replace("'", " ").split():
                if not tok.isdigit() and tok not in ("APRIL",):
                    assert S.clean(tok).upper() in spoken.replace(",", "").replace(".", ""), tok


def test_scramble_locks_left_to_right_and_keeps_spaces():
    target = "CAMP NOU"
    assert T.scramble_text(target, 0.9, 1.0, 0.48, seed=3) == ("", 0)       # nothing before its word
    late, n = T.scramble_text(target, 1.6, 1.0, 0.48, seed=3)
    assert late == target and n == len(target)
    mid, n = T.scramble_text(target, 1.24, 1.0, 0.48, seed=3)
    assert mid[:n] == target[:n] and 0 < n < len(target)                   # locks left to right
    assert mid[n:] != target[n:len(mid)]                                   # flickering tail ahead of the lock


def test_dynamic_sizing_hits_cap_height():
    for cap in (60, 200, 420):
        sz = T.size_for_cap(F.DISPLAY, cap)
        assert abs(T.cap_height(F.DISPLAY, sz) - cap) <= max(3, cap * 0.04)


@pytest.mark.parametrize("fam", list(F.FAMILIES))
def test_every_family_draws_and_persists_until_its_out_time(fam):
    W, H = 640, 360
    data = {
        "name": {"lines": [("LIONEL", 0.0), ("MESSI", 0.5)]},
        "headline": {"text": "ONE-MAN SHOW", "t": 0.0, "sub": [("MESSI", 0.4), ("3", 0.7)]},
        "numbered": {"items": [{"n": 1, "t": 0.0, "label": "21' FROM THE EDGE", "tokens": [("21'", 0.2), ("FROM", 0.4)],
                                "end": 0.8},
                               {"n": 2, "t": 1.0, "label": "37' PAST ALMUNIA", "tokens": [("37'", 1.1)], "end": 1.5}]},
        "minimal": {"lines": [{"text": "BUT FIRST.", "t0": 0.0, "t1": 0.6}, {"text": "WE HAVE TO GO BACK", "t0": 0.8, "t1": 1.4}]},
        "label": {"lines": [{"text": "6 APRIL 2010", "t": 0.0}, {"text": "CAMP NOU", "t": 0.6}]},
        "cumulative": {"items": [{"value": "47", "label": "GOALS", "t": 0.0}, {"value": "53", "label": "GAMES", "t": 0.8}]},
        "impact": {"value": "4", "t": 0.0, "label": "GOALS", "label_t": 0.4, "sub": "ONE NIGHT", "sub_t": 0.8},
    }[fam]
    g = F.make(S.Element(fam, 0.0, 3.0, data, "test"), W, H)
    blank = lambda: Image.new("RGBA", (W, H), (0, 0, 0, 0))  # noqa: E731
    ctx = type("C", (), {"subject": lambda self, t: {"head_x": 0.4, "head_x0": 0.35, "head_x1": 0.45, "head_y": 0.2,
                                                       "cover": 0.2}})()
    drawn = 0
    for t in (1.6, 2.2):
        b, f = blank(), blank()
        g.draw(t, b, f, ctx)
        drawn += int(np.asarray(b)[..., 3].max() > 0 or np.asarray(f)[..., 3].max() > 0)
    assert drawn == 2  # visible mid-way: persistence is by narration time, not by shot
    b, f = blank(), blank()
    g.draw(3.6, b, f, ctx)
    assert np.asarray(b)[..., 3].max() == 0 and np.asarray(f)[..., 3].max() == 0
    assert all(c.t >= 0 for c in g.cues())


def test_behind_subject_families_use_behind_layer():
    assert F.FAMILIES["name"].behind_subject and F.FAMILIES["cumulative"].behind_subject
    assert not F.FAMILIES["numbered"].behind_subject


def test_grades_are_bounded_and_mono_is_grey():
    img = (np.random.default_rng(1).random((36, 64, 3)) * 255).astype(np.uint8)
    for g in GRADES:
        out = grade(img, g)
        assert out.shape == img.shape and out.dtype == np.uint8
    m = grade(img, "mono_cool").astype(int)
    assert np.abs(m[..., 0] - m[..., 2]).mean() < 25


def test_fx_shapes():
    a = np.zeros((36, 64, 3), np.uint8)
    b = np.full((36, 64, 3), 200, np.uint8)
    assert FX.rgb_split(b, 3).shape == b.shape
    d = FX.luma_dissolve(a, b, 0.5, seed=1)
    assert d.shape == a.shape and 0 < d.mean() < 200
    assert FX.luma_dissolve(a, b, 1.0, seed=1).mean() == pytest.approx(200, abs=1)
    p = FX.push(a, b, 0.5, -1)
    assert p.shape == a.shape


def test_score_sounds_and_bed():
    for sid in ("sp-glitch", "sp-scramble", "whoosh-short-1"):
        x = SC.sound(sid)[0] if isinstance(SC.sound(sid), tuple) else SC.sound(sid)
        assert x.ndim == 2 and x.shape[0] == 2 and np.isfinite(x).all() and np.abs(x).max() <= 1.0001
    b = SC.bed(6.0, [(0, 2, "nostalgic"), (2, 3, "minimal"), (3, 6, "peak")])
    assert b.shape[0] == 2 and abs(b.shape[1] - 6 * 48000) < 48000 * 0.05
    rms = lambda s: float(np.sqrt((b[:, int(s[0] * 48000):int(s[1] * 48000)] ** 2).mean()))  # noqa: E731
    assert rms((2.1, 2.9)) < rms((4, 6))  # the minimal section really is quieter than the peak


def test_auto_transitions_follow_context():
    e = Edit(640, 360, 25)
    for i in range(4):
        e.add(Shot("x.mp4", i * 3.0, 2.0, grade="low_key" if i == 2 else "natural"))
    e.set_elements([S.Element("minimal", 3.9, 6.0, {"lines": [{"text": "BUT FIRST.", "t": 3.9}]}, "t"),
                    S.Element("headline", 0.0, 2.0, {"text": "X"}, "t")])
    e.auto_transitions()
    assert e.trans[1].kind in ("glitch", "cut")
    assert e.trans[2].kind == "dissolve"
    assert isinstance(e.trans[3], Transition)


def test_matte_optional_and_encoder_fallback(monkeypatch):
    monkeypatch.setenv("CASEFILE_RVM_MODEL", "/nonexistent.onnx")
    assert isinstance(M.available(), bool)
    if not M.available():
        assert M.unavailable_reason()
    monkeypatch.setenv("CASEFILE_HWENC", "0")
    args = encoder_args()
    assert "libx264" in args


def test_impact_numeral_never_hidden_by_the_player():
    """Behind-subject only when the player leaves the number readable; decided per shot (no flicker)."""
    W, H = 640, 360
    el = S.Element("impact", 0.0, 2.0, {"value": "4", "t": 0.0, "label": "GOALS", "label_t": 0.3}, "t")

    class Ctx:
        def __init__(self, occ):
            self.occ = occ
            self.shots = [Shot("x.mp4", 0, 2.0)]
            self.shots[0].start = 0.0

        def shot_at(self, t):
            return 0

        def occlusion(self, t, box):
            return self.occ

        def subject(self, t):
            return None

    for occ, where in ((0.1, "behind"), (0.8, "front")):
        g = F.make(el, W, H)
        b, f = Image.new("RGBA", (W, H)), Image.new("RGBA", (W, H))
        g.draw(1.0, b, f, Ctx(occ))
        nb, nf = (np.asarray(b)[..., 3] > 0).sum(), (np.asarray(f)[..., 3] > 0).sum()
        assert (nb > nf) if where == "behind" else (nf > nb and nb == 0)

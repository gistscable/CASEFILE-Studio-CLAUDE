"""v0.4.64 Type and layout of the cinematic graphics: a font style, the text size, the layout mirrored, the layout's
size and place in the frame (project + per graphic, checked against what each layout holds); the crowded timeline
no longer runs labels together; legal is darkened more over a picture by default; the default look is unchanged."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import cinematic
import motion
from cinegfx import core, draw as D, look as L
from cinegfx_layout import check, check_frame, settled_times
from test_cinematic import javits_project

TC = core.load_collections()["truecrime"]
PHOTOS = Path(__file__).resolve().parents[1] / "qa" / "cinegfx-demos" / "photos"
FILES = {"Joseph Kenny": "kenny.jpg", "Ben Crump": "crump.jpg", "Javits Frimpong": "javits.jpg", "vigil": "memorial-candles.jpg"}


@pytest.fixture(scope="module")
def items():
    return {x["category"]: x for x in cinematic.suggest(javits_project(), [])}


def styled(it, look=None, **item_look):
    x = dict(it, look=item_look) if item_look else dict(it)
    return motion.normalise({"enabled": True, "items": [x], "look": look or {}})["items"][0]


def files_for(it):
    """The approved Javits photos in the graphic's slots (the producer's own, as in the app)."""
    out = {}
    for sl in cinematic.slots(it):
        v = sl["value"]
        f = FILES.get(v) or ("courthouse.jpg" if "ourt" in v else "freeman-tracks.jpg" if "Freeman" in v else None)
        if f:
            out[sl["key"]] = {"file": str(PHOTOS / f), "credit": "Photo: test", "month": ""}
    return out


def test_default_type_draws_the_approved_design(items):
    for cat, it in items.items():
        s = styled(it)
        assert s["style"]["type"] == {"font": "design", "fonts": None, "size": 1.0, "mirror": False, "place": None}
        g = cinematic.build(s)
        assert g.th is TC.categories[cat].theme and g.place is None  # same Theme object, the approved drawing path


def test_look_is_stored_as_the_choices_made():
    n = cinematic.normalise_look
    assert n({"font": "serif", "size": 1.4, "mirror": True, "place": {"scale": 0.5, "x": 3, "y": -0.5}}, project=True) == {
        "font": "serif", "size": 1.15, "mirror": True, "place": {"scale": 0.8, "x": 1.0, "y": -0.5}}
    # the project drops "as designed" values; a graphic keeps them (they win over the project's choice)
    assert n({"font": "design", "size": 1, "mirror": False, "place": {"scale": 1, "x": 0, "y": 0}}, project=True) == {}
    assert n({"font": "design", "size": 1, "mirror": False, "place": {"scale": 1, "x": 0, "y": 0}}) == {
        "font": "design", "size": 1.0, "mirror": False, "place": {"scale": 1.0, "x": 0.0, "y": 0.0}}
    assert n({"font": "comic-sans", "mirror": "yes", "place": "left"}) == {}


def test_graphic_wins_over_project_and_limits_are_said(items):
    tl, con, fin = items["timeline"], items["contradiction"], items["findings"]
    look = {"font": "serif", "size": 1.1, "mirror": True, "place": {"scale": 0.9, "x": 0, "y": 1}}
    s = styled(tl, look)["style"]
    assert s["type"]["font"] == "serif" and s["type"]["size"] == 1.1 and s["type"]["place"] == {"scale": 0.9, "x": 0.0, "y": 1.0}
    assert s["type"]["mirror"] is False and not s["notes"]  # the project's "mirror where it can": no note on a timeline
    assert s["from"]["font"] == "project"
    s = styled(tl, look, font="design", size=1.0, place={"scale": 1, "x": 0, "y": 0})["style"]
    assert s["type"] == {"font": "design", "fonts": None, "size": 1.0, "mirror": False, "place": None}
    assert s["from"]["font"] == "graphic"
    # contradiction fills the screen and its layout does not take the serif style: kept, and said
    s = styled(con, None, font="geometric", place={"scale": 0.8, "x": 0, "y": 0}, mirror=True)["style"]
    assert s["type"]["place"] is None and s["type"]["mirror"] is False
    assert any("fills the screen" in x for x in s["notes"]) and any("cannot be mirrored" in x for x in s["notes"])
    assert s["type"]["font"] == "design"  # geometric IS contradiction's own design: offered as "As designed"
    s = styled(fin, None, mirror=True, font="mono")["style"]
    assert s["type"]["mirror"] is True and s["type"]["font"] == "design" and any("keeps its own font" in x for x in s["notes"])


def test_every_offered_font_and_size_fits_its_layout(items):
    """The guarantee behind the options: on the app's own graphics (with photos), no text runs into other text, is cut
    by its box or leaves the frame, for every font a category offers at both ends of its text size range, mirrored too."""
    bad = []
    for cat, it in items.items():
        c = TC.categories[cat]
        lo, hi = L.size_range(c)
        f = files_for(it)
        for font, _ in L.fonts_of(c):
            for size in sorted({lo, hi}):
                for mirror in ([False, True] if (c.looks or {}).get("mirror") else [False]):
                    s = styled(it, None, font=font, size=size, mirror=mirror)
                    problems = check(cinematic.build(s, f))
                    if problems:
                        bad.append((cat, font, size, mirror, problems[:2]))
    assert not bad, bad


def test_crowded_timeline_keeps_labels_apart(items):
    it = items["timeline"]
    assert len(it["payload"]["events"]) == 5
    g = cinematic.build(it, files_for(it))
    assert g.crowded and g.card_w < 330
    assert not [p for p in check(g) if p[0] == "overlap"]
    # up to four events: the approved layout
    few = dict(it, payload=dict(it["payload"], events=it["payload"]["events"][1:]))
    g4 = cinematic.build(few, files_for(few))
    assert not g4.crowded and g4.card_w == 330


def test_legal_is_darkened_more_over_a_picture(items):
    leg, tl = items["legal"], items["timeline"]
    assert styled(leg, {"background": "footage"})["style"]["dim"] == 0.75
    assert styled(tl, {"background": "footage"})["style"]["dim"] == L.DIM[2]
    assert styled(leg, {"background": "footage", "dim": 0.5})["style"]["dim"] == 0.5  # your own setting wins
    assert styled(leg, None, background="footage", dim=0.45)["style"]["dim"] == 0.45
    # readability of its small red labels over a mid-grey picture: below 3:1 at 62%, above at 75%
    accent = L.palettes(TC.categories["legal"])[-1][2]["accent"]
    assert L.contrast(accent, L.picture_ref(0.62)) < 3.0 <= L.contrast(accent, L.picture_ref(0.75))


def _texts(g, t):
    D.RECORD = []
    try:
        g.frame(t)
        return {e[0]: e for e in D.RECORD}
    finally:
        D.RECORD = None


def test_mirrored_layouts_swap_photo_and_text(items):
    fin = items["findings"]
    f = files_for(fin)
    a, b = cinematic.build(styled(fin), f), cinematic.build(styled(fin, None, mirror=True), f)
    t = settled_times(a)[-1]
    ta, tb = _texts(a, t), _texts(b, t)
    title = next(k for k in ta if k.startswith("WHAT "))
    assert ta[title][3] == 856 and tb[title][3] == 96  # the findings move left
    name = next(k for k in ta if k == fin["payload"]["source"].upper())
    assert ta[name][3] < 300 and tb[name][3] > 1100  # the photo (and the name on it) moves right
    leg = items["legal"]
    a, b = cinematic.build(styled(leg), files_for(leg)), cinematic.build(styled(leg, None, mirror=True), files_for(leg))
    t = settled_times(a)[-1]
    assert _texts(a, t)["DEFENDANT"][3] == 790 and _texts(b, t)["DEFENDANT"][3] == 120


def test_layout_size_and_position(items):
    it = items["timeline"]
    W, H = 1920, 1080
    s = styled(it, None, place={"scale": 0.8, "x": 1, "y": 1})
    g = cinematic.build(s)
    assert g.place == L.placement({"scale": 0.8, "x": 1.0, "y": 1.0})
    sc, dx, dy = g.place
    assert sc == 0.8 and dx == round(0.1 * W + 0.1 * W + L.NUDGE * W) and dy == round(0.1 * H + 0.1 * H + L.NUDGE * H)
    k = cinematic.frames_of(s) - 30
    im = np.asarray(cinematic.frame(g, s, k, W, H))
    bg = np.array(TC.categories["timeline"].theme.c("bg"))
    # its own background still fills the frame; the top-left corner (outside the placed layout) is only background
    assert (im[: dy, : dx] == bg).all()
    # over the footage the darkening still covers the whole frame (see-through), the layout sits bottom right
    s2 = styled(it, {"background": "footage"}, place={"scale": 0.8, "x": 1, "y": 1})
    im2 = np.asarray(cinematic.frame(cinematic.build(s2), s2, k, W, H))
    assert (im2[:dy, :dx, 3] == round(255 * L.DIM[2])).all()
    # text is inside the placed area and still sharp-edged (Lanczos downscale, no blur filter): full-alpha pixels exist
    assert im2[dy:, dx:, 3].max() == 255


def test_placed_preview_equals_export(items, tmp_path):
    """The placed layout goes through the same frame() the preview and the export use."""
    it = items["digital"]
    s = styled(it, None, place={"scale": 0.85, "x": -0.5, "y": 0}, size=1.1, font="sans")
    g = cinematic.build(s)
    k = cinematic.frames_of(s) // 2
    a = cinematic.frame(g, s, k, 1280, 720)
    b = cinematic.frame(cinematic.build(dict(s)), s, k, 1280, 720)
    assert np.array_equal(np.asarray(a), np.asarray(b))
    assert cinematic.item_hash(s, 1280, 720) != cinematic.item_hash(styled(it), 1280, 720)


def test_catalog_offers_what_each_layout_holds():
    cat = cinematic.catalog()
    tc = next(c for c in cat["collections"] if c["key"] == "truecrime")
    by = {k["key"]: k["looks"] for k in tc["categories"]}
    assert by["contradiction"]["place"] is False and by["contradiction"]["mirror"] == ""
    assert by["legal"]["dim"] == 0.75 and by["legal"]["mirror"]
    for k, lk in by.items():
        assert lk["fonts"][0]["key"] == "design" and len(lk["fonts"]) >= 3, k
        assert lk["size"] == [0.85, 1.15], k
    assert {s["key"] for s in cat["type"]["styles"]} == set(L.STYLES)

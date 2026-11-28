"""v0.4.76 Multi-niche: the documentary niches (niches.py), the project's `niche` (create, edit, history), what it
sets (graphics collection, sound flavour, research and voice direction, starting look), the niche sound library,
and the new cinematic collections (football, combat sports, entertainment, documentary): their detectors on
narrator-style scripts, their layouts at every offered font and size, readable colour sets, determinism, and that
every word they draw comes from the narration (or is one of the graphic's own fixed labels)."""
import re
from pathlib import Path

import numpy as np
import pytest

import ai
import cinematic
import effects
import motion
import niches
import sfxlib
import sound
import storage
from cinegfx import core, draw as D, look as L
from cinegfx import story as S
from cinegfx.collections import _kit as K
from cinegfx_layout import check
import niche_scripts as N

R = core.load_collections()
PHOTO = str(Path(__file__).resolve().parents[1] / "qa" / "cinegfx-demos" / "photos" / "kenny.jpg")
SETS = {"football": N.FOOTBALL, "combat": N.COMBAT, "entertainment": N.ENTERTAINMENT, "documentary": N.DOCUMENTARY}
EXPECT = {"football": ["stats", "bracket", "tactics", "risefall"], "combat": ["tape", "journey", "legacy"],
          "entertainment": ["career", "impact"], "documentary": ["figures", "arc"]}


def styled(it, look=None, **item_look):
    x = dict(it, look=item_look) if item_look else dict(it)
    return motion.normalise({"enabled": True, "items": [x], "look": look or {}})["items"][0]


@pytest.fixture(scope="module")
def placed():
    return {coll: cinematic.suggest(N.project(script, coll), [], collection=coll) for coll, script in SETS.items()}


def photos_for(it):
    return {sl["key"]: {"file": PHOTO, "credit": "Photo: test", "month": ""} for sl in cinematic.slots(it)}


# ------------------------------------------------------------------ the niches

def test_ten_niches_in_the_picker_order_each_complete():
    keys = [n["key"] for n in niches.NICHES]
    assert keys == ["truecrime", "football", "boxing", "wrestling", "entertainment", "history", "business", "psychology", "faith", "general"]
    assert niches.DEFAULT == "truecrime"
    cats = {c[1] for c in sfxlib.CATALOG}
    for n in niches.NICHES:
        for f in ("label", "icon", "about", "title_hint", "collection", "look", "graphics", "music", "research", "voice"):
            assert isinstance(n[f], str) and n[f].strip(), (n["key"], f)
        assert n["look"] in effects.LOOKS, n["key"]
        assert n["collection"] in R, n["key"]  # every niche's graphics exist (documentary covers the rest)
        assert n["sound"]["preset"] in sound.PRESETS
        for generic, family in n["sound"]["flavour"].items():
            assert generic in cats and family in cats, (n["key"], generic, family)  # real library families only
    assert niches.get("truecrime")["sound"]["flavour"] == {}  # true crime sounds exactly as before


def test_projects_without_a_niche_are_true_crime():
    assert niches.key_of({}) == niches.key_of({"niche": "nonsense"}) == niches.key_of(None) == "truecrime"
    assert niches.collection({}) == "truecrime" and niches.flavour({}) == {}
    with pytest.raises(ValueError):
        niches.normalise("cooking")
    assert {"boxing": "combat", "wrestling": "combat", "history": "documentary", "general": "documentary",
            "football": "football", "entertainment": "entertainment"} == {k: niches.collection({"niche": k}) for k in
                                                                         ("boxing", "wrestling", "history", "general", "football", "entertainment")}


def test_catalog_for_the_editor():
    c = niches.catalog()
    assert c["default"] == "truecrime" and len(c["niches"]) == 10
    assert set(c["niches"][1]) >= {"key", "label", "icon", "about", "title_hint", "collection", "graphics", "music", "sound"}
    assert "research" not in c["niches"][1]  # the AI's directions stay on the server


def test_new_project_takes_the_niche_and_its_look(isolated):
    p = storage.new_project("Messi", "topic", 25, niche="football")
    assert p["niche"] == "football" and p["look"] == "punchy"
    q = storage.new_project("Case", "topic", 25)
    assert "niche" not in q and q["look"] == "noir"  # no niche given: exactly the project made before v0.4.76
    with pytest.raises(ValueError):
        storage.new_project("X", niche="cooking")


def test_api_create_edit_and_list_niches(isolated):
    client, _ = isolated
    r = client.get("/api/niches")
    assert r.status_code == 200 and [n["key"] for n in r.json()["niches"]][:2] == ["truecrime", "football"]
    p = client.post("/api/projects", json={"title": "Iron Mike", "mode": "topic", "target_minutes": 25, "niche": "boxing"}).json()
    assert p["niche"] == "boxing" and p["look"] == "punchy"
    assert client.post("/api/projects", json={"title": "X", "mode": "topic", "niche": "cooking"}).status_code == 422
    old = client.post("/api/projects", json={"title": "A case", "mode": "topic"}).json()
    assert "niche" not in old
    r = client.patch(f"/api/projects/{p['id']}", json={"niche": "wrestling"})
    assert r.status_code == 200 and r.json()["niche"] == "wrestling"
    assert r.json()["look"] == "punchy"  # changing the niche never changes the look already chosen
    assert client.patch(f"/api/projects/{p['id']}", json={"niche": "cooking"}).status_code == 422
    # the cinematic editor offers the default collection first, then the niches' own
    keys = [c["key"] for c in client.get("/api/motion/catalog").json()["collections"]]
    assert keys[0] == "truecrime" and {"football", "combat", "entertainment", "documentary"} <= set(keys)


def test_research_and_voice_direction_follow_the_niche():
    tc = {"topic": "x"}
    assert ai.voice_direction(tc) == ("Read in a calm, clear, respectful documentary voice. Measured pacing, natural pauses. "
                                      "Do not add any words.")  # true crime: word for word as before
    assert ai._research_focus(tc).startswith("Use current web search, prioritizing court documents")
    fb = {"topic": "x", "niche": "football"}
    assert "sports" in ai.voice_direction(fb) and ai.voice_direction(fb).endswith("Do not add any words.")
    assert "football documentary" in ai._research_focus(fb) and "match reports" in ai._research_focus(fb)
    assert "court documents" not in ai._research_focus(fb)


# ------------------------------------------------------------------ sound

NEW_SFX = ["crowd-swell-1", "crowd-swell-2", "crowd-cheer-1", "whistle-1", "whistle-3", "ring-bell-1", "ring-bell-3", "punch-1", "punch-2",
           "punch-3", "arena-hit-1", "arena-boom-1", "flash-1", "flash-2", "sparkle-1", "sparkle-2", "warm-swell-1", "warm-swell-2",
           "heartbeat-1", "heartbeat-2", "projector-1", "ticker-1", "ticker-2"]


def test_niche_sounds_are_original_synthesis_and_deterministic():
    ids = {c[0] for c in sfxlib.CATALOG}
    for sid in NEW_SFX:
        assert sid in ids
        (a, _), (b, _) = sfxlib.synth(sid), sfxlib.synth(sid)
        assert np.array_equal(a, b), sid
        peak = float(np.abs(a).max())
        assert 0.01 < peak <= 1.0, (sid, peak)
        assert 0.3 < a.shape[1] / sfxlib.SR < 7.0, sid


def test_flavour_swaps_generic_families_for_the_niche():
    assert sound._flavoured("swell", {"swell": "crowd"}) == "crowd"
    assert sound._flavoured(("swell", "2"), {"swell": "crowd"}) == "crowd"
    assert sound._flavoured(("whoosh", "mid"), {"swell": "crowd"}) == ("whoosh", "mid")
    assert sound._flavoured("swell", {}) == "swell"
    assert sound.flavour_of({"niche": "football"}) == {"swell": "crowd"}
    assert sound.flavour_of({"niche": "football", "sound": {"flavour": False}}) == {}
    assert sound.flavour_of({}) == {}
    assert sound.normalise({})["flavour"] is True and sound.normalise({"flavour": 0})["flavour"] is False


def test_the_plan_uses_the_niches_sounds_and_true_crime_is_unchanged():
    from test_cinematic import javits_project
    fam = {c[0]: c[1] for c in sfxlib.CATALOG}

    def families(niche, **snd):
        p = javits_project()
        if niche:
            p["niche"] = niche
        if snd:
            p["sound"] = snd
        items, _ = sound.plan(p)
        return [(i["anchor"], fam[i["sound"]]) for i in items]

    base = families(None)
    assert families("truecrime") == base
    swells = [a for a, f in base if f == "swell"]
    assert swells, "the sample plan has a chapter swell"
    fb = dict(families("football"))
    assert all(fb[a] == "crowd" for a in swells)
    assert all(dict(families("faith"))[a] == "warm-swell" for a in swells)
    assert families("football", flavour=False) == base  # switched off: the generic sounds


def test_cinematic_cues_of_the_new_families_have_a_kind():
    for fam in ("crowd", "whistle", "ring-bell", "punch", "arena", "flash", "sparkle", "warm-swell", "heartbeat", "projector", "ticker"):
        assert any(fam.startswith(k) for k in sound._CINE_KIND), fam


# ------------------------------------------------------------------ the collections

def test_new_collections_register_alongside_true_crime():
    assert {"truecrime", "football", "combat", "entertainment", "documentary"} <= set(R)
    assert "_kit" not in R
    for coll, cats in EXPECT.items():
        assert set(cats) <= set(R[coll].categories), coll
    keys = [c["key"] for c in cinematic.catalog()["collections"]]
    assert keys[0] == "truecrime"  # the default first, then the rest by name


def test_every_category_is_placed_on_its_sample_script(placed):
    for coll, cats in EXPECT.items():
        got = [x["category"] for x in placed[coll]]
        assert got == cats, (coll, got)
        for it in placed[coll]:
            assert it["collection"] == coll and it["label"] and it["start"] < it["end"]


def test_detectors_read_the_narration(placed):
    by = {(c, x["category"]): x["payload"] for c, items in placed.items() for x in items}
    st = by[("football", "stats")]
    assert st["subject"] == "Lionel Messi" and st["team"] == "Barcelona" and st["period"] == "2004–2021"
    assert [(s["value"], s["label"]) for s in st["stats"]] == [("672", "GOALS"), ("778", "GAMES"), ("303", "ASSISTS"), ("35", "TROPHIES")]
    br = by[("football", "bracket")]
    assert br["competition"] == "Champions League"
    assert [(r["stage"], r["opponent"], r["result"]) for r in br["rounds"]] == [
        ("ROUND OF 16", "Inter Milan", "W"), ("QUARTER-FINAL", "Benfica", "W"), ("SEMI-FINAL", "Villarreal", "W"), ("FINAL", "Real Madrid", "L")]
    tc = by[("football", "tactics")]
    assert tc["formations"][0]["shape"] == [4, 3, 3] and [n["kind"] for n in tc["notes"]] == ["press", "counter", "wide"]
    rf = by[("football", "risefall")]
    assert rf["subject"] == "Cristiano Ronaldo" and rf["arc"] == "redemption" and [p["dir"] for p in rf["points"]] == ["up", "down", "up"]
    tape = by[("combat", "tape")]
    assert (tape["left"], tape["right"]) == ("Mike Tyson", "Jake Paul")
    rows = {r["key"]: (r["left"], r["right"], r["edge"]) for r in tape["rows"]}
    assert rows["record"] == ("50-6", "10-1", 0) and rows["reach"] == ("71″", "76″", 1) and rows["height"] == ("5′10″", "6′1″", 1)
    jr = by[("combat", "journey")]
    assert jr["subject"] == "Mike Tyson" and [m["kind"] for m in jr["moments"]] == ["won", "won", "won", "lost"]
    assert jr["moments"][0]["belt"] == "WBC HEAVYWEIGHT TITLE" and jr["moments"][0]["label"] == "Defeated Trevor Berbick"
    lg = by[("combat", "legacy")]
    assert lg["rival"] == "Shawn Michaels" and [m["year"] for m in lg["moments"]] == [2009, 2014, 2020]
    ca = by[("entertainment", "career")]
    assert ca["title"] == "FROM KING TO CHAOS" and ca["subject"] == "Michael Jackson"  # the chapter's own words
    im = by[("entertainment", "impact")]
    assert im["work"] == "Thriller" and [s["value"] for s in im["stats"]] == ["70M", "37", "8", "500M"]
    fg = by[("documentary", "figures")]
    assert [s["value"] for s in fg["stats"]][:3] == ["100,000", "120", "437M"]
    arc = by[("documentary", "arc")]
    assert [p["label"] for p in arc["points"]] == ["Became the world's largest phone maker", "Struggled to respond",
                                                    "Sold its phone business to Microsoft", "Returned under a new licence"]


def test_another_actors_moment_is_not_the_subjects():
    st = S.parse_script("# Nokia\n## Chapter 1 — Fall\nIn 1998, Nokia became the biggest. In 2007, Apple launched the iPhone and Nokia struggled. "
                        "In 2013, Nokia sold its phone business to Microsoft.\n")
    labels = [p["label"] for p in K.career_points(st, 0, len(st.sentences))]
    assert not any("iPhone" in x for x in labels) and "Struggled" in labels


def test_detectors_find_nothing_in_true_crime_and_never_raise():
    from test_cinematic import javits_project
    p = javits_project()
    for coll in ("football", "combat", "entertainment"):
        assert cinematic.suggest(p, [], collection=coll) == [], coll  # a murder case is not a football story
    st = S.parse_script("# X\n## Chapter 1 — Odd\n4-4-2. 1-0. 50 wins. $ million. — . In 2001,. 7 feet 99 inches.\n")
    for c in R.values():
        for cat in c.categories.values():
            for a in range(len(st.sentences)):
                for b in range(a + 1, min(len(st.sentences), a + 3) + 1):
                    cat.detect(st, a, b)  # never raises


def test_headlines_are_the_narrations_own_words():
    assert K.headline("he suffered a serious knee injury that kept him out for months") == "Suffered a serious knee injury"
    assert K.headline("beat Michaels at WrestleMania in a match many still call the greatest ever", 46) == "Beat Michaels at WrestleMania"
    assert K.headline("Joined Real Madrid for a world-record fee and a new contract", 30) == "Joined Real Madrid"
    assert K.short_name("Mike Tyson") == "Tyson" and K.number("twenty") == 20 and K.number("1,234") == 1234


def _narration_words(script):
    text = script.lower()
    words = set(re.findall(r"[a-z0-9']+", text)) | set(re.findall(r"[a-z0-9]+", text))
    words |= {str(v) for k, v in K.NUM_WORDS.items() if k in words}
    words |= {w.rstrip("s") for w in words}
    return words


FIXED = {"tale", "of", "the", "tape", "vs", "road", "to", "final", "tactical", "breakdown", "championship", "journey", "superstar",
         "legacy", "rise", "fall", "and", "redemption", "comeback", "rise,", "key", "figures", "achievements", "w", "l", "d", "agg",
         "pens", "round", "record", "height", "reach", "weight", "knockouts", "age", "m", "b", "k", "t", "cm", "kg", "lbs", "1", "2", "3",
         "4", "5", "6"}


def test_every_word_on_screen_comes_from_the_narration(placed):
    bad = []
    for coll, items in placed.items():
        words = _narration_words(SETS[coll]) | FIXED
        for it in items:
            g = cinematic.build(it)
            D.RECORD = []
            try:
                g.frame(g.out - 0.05)
                drawn = [e[0] for e in D.RECORD]
            finally:
                D.RECORD = None
            for s in drawn:
                for tok in re.findall(r"[a-z0-9']+", s.lower().replace("’", "'")):
                    t2 = re.sub(r"^(\d+)[mbkt]$", r"\1", tok)
                    if tok not in words and t2 not in words and tok.rstrip("s") not in words:
                        bad.append((coll, it["category"], s, tok))
    assert not bad, bad


def test_layouts_fit_at_every_font_size_and_mirror_with_and_without_photos(placed):
    bad = []
    for coll, items in placed.items():
        for it in items:
            c = R[coll].categories[it["category"]]
            lo, hi = L.size_range(c)
            for files in ({}, photos_for(it)):
                for font, _ in L.fonts_of(c):
                    for size in sorted({lo, hi}):
                        for mirror in ([False, True] if (c.looks or {}).get("mirror") else [False]):
                            problems = check(cinematic.build(styled(it, None, font=font, size=size, mirror=mirror), files))
                            if problems:
                                bad.append((coll, it["category"], bool(files), font, size, mirror, problems[:2]))
    assert not bad, bad


def test_every_tested_colour_set_is_readable():
    for coll in EXPECT:
        for cat in R[coll].categories.values():
            pals = L.palettes(cat)
            assert len(pals) >= 3, (coll, cat.key)
            assert pals[0][2] == {r: getattr(cat.theme, r).upper() for r in L.ROLES}
            for key, label, c in pals:
                assert L.contrast(c["ink"], c["bg"]) >= L.TEXT_MIN, (coll, cat.key, key)
                assert L.contrast(c["accent"], c["bg"]) >= L.ACCENT_MIN, (coll, cat.key, key)
                assert L.contrast(c["accent2"], c["bg"]) >= L.ACCENT_MIN, (coll, cat.key, key)
                assert L.contrast(c["muted"], c["bg"]) >= 3.0, (coll, cat.key, key)


def test_frames_are_deterministic_and_every_cue_is_a_library_sound(placed):
    ids = {c[0] for c in sfxlib.CATALOG}
    for coll, items in placed.items():
        for it in items:
            g1, g2 = cinematic.build(it, photos_for(it)), cinematic.build(it, photos_for(it))
            assert [(c.t, c.sfx) for c in g1.cues] == [(c.t, c.sfx) for c in g2.cues]
            assert all(c.sfx in ids for c in g1.cues), (coll, it["category"])
            n = cinematic.frames_of(it)
            for k in (n // 3, n - 3):
                a = np.asarray(cinematic.frame(g1, it, k, 320, 180))
                b = np.asarray(cinematic.frame(g2, it, k, 320, 180))
                assert np.array_equal(a, b), (coll, it["category"], k)
                assert a.std() > 2  # something is drawn


def test_photos_only_from_the_project(placed):
    for coll, items in placed.items():
        for it in items:
            g = cinematic.build(it)  # no photos given: none drawn, nothing fetched or made up
            assert not any(getattr(g, k, None) for k in ("photo_key",)), (coll, it["category"])
            assert not any(getattr(g, "keys", None) or []), (coll, it["category"])

"""Inside the CASEFILE-Studio repository: the kit's engine is Casefile's (byte for byte but the two layout lines),
and the kit draws exactly Casefile's frames for the same graphic, whatever its look. Skipped in the standalone zip."""
import json
import re

import pytest

import javits_demo as J
from conftest import KIT, casefile_or_skip

from storyroom_kit import graphics as G
from storyroom_kit import plan as PL


def test_engine_copy_matches_casefile():
    casefile_or_skip()
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_engine", KIT / "tools" / "sync_engine.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.main([]) == 0


def test_approved_demos_identical_to_casefile_with_photos():
    casefile_or_skip()
    import cinegfx as CC
    from cinegfx import core, story, text, timing  # noqa: F401
    from storyroom_kit import cinegfx as KC
    photos = str(KIT.parent / "casefile-studio" / "qa" / "cinegfx-demos" / "photos")
    for (k, _, a), (_, _, b) in zip(J.graphics(KC, photos), J.graphics(CC, photos)):
        for t in J.marks(a):
            assert a.frame(t).tobytes() == b.frame(t).tobytes(), (k, t)


LOOKS = [
    None,
    {"background": "footage"},
    {"palettes": {"findings": "B", "timeline": "C", "legal": "B", "digital": "B", "turning": "B"}, "accent": "#3FA7FF"},
    {"font": "serif", "size": 1.1, "mirror": True},
    {"place": {"scale": 0.86, "x": 0.6, "y": 0.0}, "background": "footage", "dim": 0.7},
]


@pytest.mark.parametrize("look", LOOKS, ids=["design", "footage", "palettes", "type", "placed"])
def test_kit_frames_are_casefiles_frames(look):
    casefile_or_skip()
    import cinematic
    plan = PL.make((KIT / "examples" / "sheriff" / "script.md").read_text(), look=look)
    assert len(plan["graphics"]) == 6
    for it in plan["graphics"]:
        g_kit, g_cf = G.build(it), cinematic.build(json.loads(json.dumps(it)))
        n = G.frames_of(it)
        for k in (3, n // 3, n // 2, n - 4):
            for size in ((1920, 1080),) if k != n // 2 else ((1920, 1080), (1080, 1920)):
                a = G.frame(g_kit, it, k, *size)
                b = cinematic.frame(g_cf, it, k, *size)
                assert a.tobytes() == b.tobytes(), (it["category"], k, size, look)
        assert G.cues(it, g_kit) == cinematic.cues(it)


def test_same_choices_as_casefile_on_the_same_script():
    """Casefile's own suggestion for the sheriff script (as a project) picks the same graphics over the same sentences."""
    casefile_or_skip()
    import cinematic
    raw = (KIT / "examples" / "sheriff" / "script.md").read_text()
    scenes, chapter = [], None
    for line in raw.splitlines():
        m = re.match(r"## Chapter \d+ — (.+)", line)
        if m:
            chapter = m.group(1).strip().upper()
            continue
        if line.startswith("#"):
            chapter = None
            continue
        if chapter and line.strip() and not line.startswith("**"):
            scenes.append({"id": f"s{len(scenes)}", "title": "", "chapter": chapter, "narration": line.strip(),
                           "duration": round(len(line.split()) * 0.38 + 0.4, 2)})
    project = {"id": "sh", "title": "The Last Timeline — Dana Whitfield", "topic": "Dana Whitfield", "created_at": "2026-11-24T09:00:00",
               "scenes": scenes, "assets": [], "motion": {"enabled": True, "items": []}}
    cf = [(it["category"], it["text"]) for it in cinematic.suggest(project, [])]
    kit = [(it["category"], it["text"]) for it in PL.make(raw)["graphics"]]
    assert kit == cf

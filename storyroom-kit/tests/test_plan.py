"""Plans: the same graphics Casefile places, photos only from what you give, looks resolved with their notes."""
import json

from storyroom_kit import graphics as G
from storyroom_kit import plan as PL

from conftest import KIT

SHERIFF = (KIT / "examples" / "sheriff" / "script.md").read_text()
JAVITS = (KIT / "examples" / "javits" / "script.md").read_text()


def test_javits_full_script_selection_is_casefiles():
    """Casefile's demo report (qa/cinegfx-demos/out/report.json, selection_full_script)."""
    plan = PL.make(JAVITS)
    assert [(g["category"], g["window"]) for g in plan["graphics"]] == [
        ("digital", [23, 26]), ("findings", [26, 30]), ("timeline", [44, 47]), ("turning", [47, 49]), ("legal", [49, 51]),
        ("contradiction", [54, 57])]


def test_sheriff_script_gets_all_six_in_story_order():
    plan = PL.make(SHERIFF)
    cats = [g["category"] for g in plan["graphics"]]
    assert sorted(cats) == sorted(["findings", "timeline", "contradiction", "legal", "digital", "turning"])
    starts = [g["start"] for g in plan["graphics"]]
    assert starts == sorted(starts)
    assert plan["script"]["subject"] == "Dana Whitfield"


def test_back_to_back_graphics_cover_each_other():
    plan = PL.make(JAVITS)
    gs = plan["graphics"]
    covered = [g for g in gs if g.get("cut")]
    assert covered, "the Javits sequence (timeline -> turning -> legal) runs back to back"
    for a, b in zip(gs, gs[1:]):
        if a.get("cut"):
            assert a["end"] > b["start"] and a["end"] - b["start"] <= G.FADE_IN + 1.5 / G.FPS


def test_only_some_categories():
    plan = PL.make(SHERIFF, categories=["timeline", "legal"])
    assert {g["category"] for g in plan["graphics"]} == {"timeline", "legal"}


def test_photos_by_file_name_without_inventing_credits(tmp_path):
    from PIL import Image
    (tmp_path / "pics").mkdir()
    Image.new("RGB", (800, 600), (90, 90, 90)).save(tmp_path / "pics" / "okafor.jpg")
    Image.new("RGB", (800, 600), (90, 90, 90)).save(tmp_path / "pics" / "unrelated.jpg")
    plan = PL.make(SHERIFF, photos=str(tmp_path / "pics"))
    filled = {k: v for g in plan["graphics"] for k, v in g["photos"].items()}
    assert filled and all(v["file"].endswith("okafor.jpg") and v["credit"] == "" for v in filled.values())
    assert all(s["kind"] in ("person", "place", "tag") for g in plan["graphics"] for s in g["slots"])


def test_look_notes_say_what_could_not_be_used():
    plan = PL.make(SHERIFF, look={"background": "footage", "accent": "#202020"})
    by = {g["category"]: g["style"] for g in plan["graphics"]}
    assert by["contradiction"]["background"] == "own" and by["contradiction"]["notes"]   # keeps its own background
    assert by["timeline"]["background"] == "footage"
    assert any("too faint" in n for n in by["timeline"]["notes"])


def test_plan_round_trip_and_skip(tmp_path):
    plan = PL.make(SHERIFF)
    plan["graphics"][0]["status"] = "skipped"
    p = PL.save(plan, tmp_path / "plan.json")
    back = PL.load(p)
    assert back["graphics"][0]["status"] == "skipped" and len(back["graphics"]) == 6
    assert json.loads(p.read_text())["kit"] == "storyroom-kit"


def test_relocate_keeps_photos_findable(tmp_path):
    from PIL import Image
    (tmp_path / "proj" / "pics").mkdir(parents=True)
    Image.new("RGB", (400, 300)).save(tmp_path / "proj" / "pics" / "okafor.jpg")
    plan = PL.make(SHERIFF, photos=str(tmp_path / "proj" / "pics"))
    PL.relocate(plan, tmp_path / "proj" / "out")
    assert plan["photos"]["folder"] == "../pics"
    f = next(v["file"] for g in plan["graphics"] for v in g["photos"].values())
    assert f == "../pics/okafor.jpg"

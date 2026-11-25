"""v0.4.51 Undo and redo for every edit (history.py)."""

import copy
import json

import pytest

import history
import storage
from test_studio import make


@pytest.fixture
def proj(isolated, monkeypatch):
    c, root = isolated
    monkeypatch.setattr(history, "MERGE_SECONDS", 0)  # every edit its own step unless a test says so
    p = make(c)
    return c, root, p, "/api/projects/" + p["id"]


def patch(c, url, **fields):
    r = c.patch(url, json=fields)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_editor_setting_can_be_undone_and_redone(proj):
    c, _, p, url = proj
    edits = {
        "stickers": [{"id": "st1", "kind": "subscribe-click", "x": 0.5, "y": 0.5, "size": 0.2, "start": 1, "length": 3}],
        "cta": {**(p.get("cta") or {}), "x": 0.2},
        "effects": {**(p.get("effects") or {}), "grain": 0.4},
        "caption_style": {**(p.get("caption_style") or {}), "size": 1.3},
        "watermark": {**(p.get("watermark") or {}), "enabled": True},
        "name_cards": {**(p.get("name_cards") or {}), "style": "bold"},
        "aspect": "9:16",
        "vertical_fit": "blur",
        "look": "archive",
        "music_volume": 0.31,
    }
    tested = []
    for field, value in edits.items():
        before = c.get(url).json().get(field)
        after = patch(c, url, **{field: value})
        if after.get(field) == before:
            continue  # the server normalised it to the same thing: nothing to undo
        tested.append(field)
        undone = c.post(url + "/undo").json()
        assert undone.get(field) == before, field
        redone = c.post(url + "/redo").json()
        assert redone.get(field) == after.get(field), field
    print("tested", tested)
    assert {"stickers", "cta", "aspect", "vertical_fit", "look", "music_volume"} <= set(tested)


def test_scene_keyframes_and_fill_undo_redo_with_names(proj):
    c, _, p, url = proj
    scenes = copy.deepcopy(p["scenes"])
    scenes[1]["keyframes"] = [{"t": 0, "zoom": 1.2, "x": 0.5, "y": 0.5, "ease": "linear"}]
    after = patch(c, url, scenes=scenes)
    assert after["history"]["undo"][-1] == "Scene 2 · keyframes"
    scenes[0]["fit"] = "blur"
    after = patch(c, url, scenes=scenes)
    assert after["history"]["undo"][-1] == "Scene 1 · fill"
    undone = c.post(url + "/undo").json()
    assert undone["scenes"][0].get("fit") == p["scenes"][0].get("fit")
    assert undone["scenes"][1]["keyframes"]
    assert undone["history"]["redo"] == ["Scene 1 · fill"]
    undone = c.post(url + "/undo").json()
    assert undone["scenes"] == p["scenes"]
    redone = c.post(url + "/redo").json()
    assert redone["scenes"][1]["keyframes"][0]["zoom"] == 1.2


def test_sticker_step_names(proj):
    c, _, p, url = proj
    st = {"id": "st1", "kind": "subscribe-click", "x": 0.5, "y": 0.5, "size": 0.2, "start": 1, "length": 3}
    names = []
    names.append(patch(c, url, stickers=[st])["history"]["undo"][-1])
    names.append(patch(c, url, stickers=[{**st, "x": 0.3, "y": 0.6}])["history"]["undo"][-1])
    names.append(patch(c, url, stickers=[{**st, "x": 0.3, "y": 0.6, "size": 0.3}])["history"]["undo"][-1])
    names.append(patch(c, url, stickers=[])["history"]["undo"][-1])
    assert names[0].startswith("Add sticker")
    assert names[1:] == ["Move sticker", "Resize sticker", "Remove sticker"]


def test_drag_saved_in_parts_is_one_step(proj, monkeypatch):
    c, _, p, url = proj
    monkeypatch.setattr(history, "MERGE_SECONDS", 60)
    st = {"id": "st1", "kind": "subscribe-click", "x": 0.5, "y": 0.5, "size": 0.2, "start": 1, "length": 3}
    patch(c, url, stickers=[st])
    steps = len(c.get(url).json()["history"]["undo"])
    for x in (0.45, 0.4, 0.35, 0.3):
        last = patch(c, url, stickers=[{**st, "x": x}])
    assert len(last["history"]["undo"]) == steps + 1
    assert last["history"]["undo"][-1] == "Move sticker"
    undone = c.post(url + "/undo").json()
    assert undone["stickers"][0]["x"] == 0.5  # back to before the whole drag
    redone = c.post(url + "/redo").json()
    assert redone["stickers"][0]["x"] == 0.3
    # a different control is a new step, even straight away
    other = patch(c, url, look="archive")
    assert len(other["history"]["undo"]) == steps + 2


def test_new_edit_clears_redo_and_noop_makes_no_step(proj):
    c, _, p, url = proj
    patch(c, url, look="archive")
    c.post(url + "/undo")
    assert c.get(url).json()["history"]["redo"] == ["Look"]
    steps = len(c.get(url).json()["history"]["undo"])
    same = patch(c, url, look=c.get(url).json()["look"])  # nothing changes
    assert len(same["history"]["undo"]) == steps and same["history"]["redo"] == ["Look"]
    patch(c, url, music_volume=0.22)
    h = c.get(url).json()["history"]
    assert h["redo"] == [] and h["undo"][-1] == "Music volume"
    assert c.post(url + "/redo").status_code == 400


def test_fifty_steps_and_nothing_to_undo(proj):
    c, _, p, url = proj
    for n in range(55):
        patch(c, url, music_volume=round(0.01 + n * 0.005, 3))
    h = c.get(url).json()["history"]
    assert len(h["undo"]) == history.LIMIT == 50
    for _ in range(50):
        assert c.post(url + "/undo").status_code == 200
    r = c.post(url + "/undo")
    assert r.status_code == 400 and "Nothing to undo" in r.json()["detail"]
    assert len(c.get(url).json()["history"]["redo"]) == 50


def test_crop_is_undoable_and_generated_previews_are_kept(proj):
    c, root, p, url = proj
    full = storage.get_project(p["id"])
    full["assets"].append({"id": "a1", "kind": "image", "name": "photo.jpg", "path": "x.jpg", "url": "/media/x.jpg"})
    storage.save_project(full)
    r = c.patch(url + "/assets/a1", json={"crop": [0.1, 0.1, 0.9, 0.9]})
    assert r.status_code == 200, r.text
    h = c.get(url).json()["history"]
    assert h["undo"][-1] == "Crop · photo.jpg"
    # Casefile makes new preview stills afterwards; undo must not bring old ones back
    full = storage.get_project(p["id"])
    full["assets"][-1]["preview_frames"] = {"count": 3, "version": 2}
    storage.save_project(full)
    undone = c.post(url + "/undo").json()
    a = next(x for x in undone["assets"] if x["id"] == "a1")
    assert not a.get("crop") and a["preview_frames"] == {"count": 3, "version": 2}
    redone = c.post(url + "/redo").json()
    assert next(x for x in redone["assets"] if x["id"] == "a1")["crop"] == [0.1, 0.1, 0.9, 0.9]


def test_history_lives_outside_the_project_file(proj):
    c, root, p, url = proj
    patch(c, url, look="archive")
    saved = json.loads((root / "data" / "projects" / f"{p['id']}.json").read_text())
    assert "undo" not in saved
    assert saved["history"]["undo"][-1] == "Look"
    assert (root / "data" / "history" / f"{p['id']}.json").exists()


def test_old_project_copies_become_history_once(isolated):
    c, root = isolated
    p = make(c)
    url = "/api/projects/" + p["id"]
    raw_path = root / "data" / "projects" / f"{p['id']}.json"
    (root / "data" / "history" / f"{p['id']}.json").unlink(missing_ok=True)
    raw = json.loads(raw_path.read_text())
    raw.pop("history", None)
    old = {k: copy.deepcopy(raw.get(k)) for k in ("script", "scenes", "look", "captions")}
    raw["undo"] = [{**old, "look": "archive"}]  # v0.4.50 kept whole copies
    raw_path.write_text(json.dumps(raw))
    got = c.get(url).json()
    assert "undo" not in got and got["history"]["undo"] == ["Earlier edit"]
    assert c.post(url + "/undo").json()["look"] == "archive"
    assert "undo" not in json.loads(raw_path.read_text())


def test_delete_removes_history(proj):
    c, root, p, url = proj
    patch(c, url, look="archive")
    hist = root / "data" / "history" / f"{p['id']}.json"
    assert hist.exists()
    r = c.request("DELETE", url, json={"confirm_title": p["title"]})
    assert r.status_code == 200, r.text
    assert not hist.exists()


def test_undo_failed_edit_leaves_no_step(proj):
    c, _, p, url = proj
    steps = len(c.get(url).json()["history"]["undo"])
    assert c.patch(url, json={"nonsense": 1}).status_code == 422
    assert len(c.get(url).json()["history"]["undo"]) == steps


def test_guide_rebuild_keeps_scene_ids_title_switch_and_makes_no_empty_step(isolated):
    import episode
    from test_episode import prepared

    c, _ = isolated
    p = prepared()
    episode.build(p, True)
    p.update(created_at=storage.now(), updated_at=storage.now(), messages=[], exports=[])
    storage.save_project(p)
    url = "/api/projects/" + p["id"]
    first = patch(c, url, scenes=c.get(url).json()["scenes"])  # the first save may settle review flags
    ids = [s["id"] for s in first["scenes"]]
    steps = len(first["history"]["undo"])
    again = patch(c, url, scenes=first["scenes"])  # nothing changed
    assert [s["id"] for s in again["scenes"]] == ids  # v0.4.51: ids survive the rebuild
    assert len(again["history"]["undo"]) == steps  # and no empty step
    scenes = again["scenes"]
    scenes[0]["show_title"] = True
    on = patch(c, url, scenes=scenes)
    assert on["scenes"][0]["show_title"] is True  # was lost by the rebuild before v0.4.51
    assert on["history"]["undo"][-1] == "Scene 1 · title card"
    off = c.post(url + "/undo").json()
    assert not off["scenes"][0].get("show_title")
    assert c.post(url + "/redo").json()["scenes"][0]["show_title"] is True

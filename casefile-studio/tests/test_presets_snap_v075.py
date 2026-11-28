"""v0.4.75 saved presets, the new keyframe curves and manual speed, snapping guides."""
import json
import subprocess
from pathlib import Path

import pytest

import picture
import presets

ROOT = Path(__file__).resolve().parents[1]


def node(js):
    out = subprocess.run(["node", "--input-type=module", "-e", js], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ------------------------------------------------------------------ curves

def test_curves_python_and_js_agree():
    us = [i / 50 for i in range(51)]
    js = node(f"""
    import {{ ease, STICKER_EASES, EASES }} from "./web/src/picture.js";
    console.log(JSON.stringify({{ kinds: STICKER_EASES, picture: EASES, v: Object.fromEntries(STICKER_EASES.map((k) => [k, {json.dumps(us)}.map((u) => ease(u, k))])) }}));
    """)
    assert js["kinds"] == list(picture.STICKER_EASES) and js["picture"] == list(picture.EASES)
    for k in picture.STICKER_EASES:
        for u, v in zip(us, js["v"][k]):
            assert v == pytest.approx(picture.ease(u, k), abs=1e-9), (k, u)


def test_picture_curves_never_leave_the_two_keyframes():
    for k in picture.EASES:
        vals = [picture.ease(i / 400, k) for i in range(401)]
        assert min(vals) >= -1e-9 and max(vals) <= 1 + 1e-9, k
    assert min(picture.ease(i / 100, "anticipate") for i in range(101)) < -0.05  # pulls back first
    assert max(picture.ease(i / 100, "elastic") for i in range(101)) > 1.05  # a spring wobbles past


def test_manual_speed():
    out = node("""
    import { setSegment, setSpan } from "./web/src/picture.js";
    const k = [{ t: 0, x: 0 }, { t: 1, x: 1 }, { t: 3, x: 0 }];
    console.log(JSON.stringify([setSegment(k, 0, 0.5, 6), setSegment(k, 1, 4, 6), setSegment(k, 1, 9, 6), setSpan(k, 1.5, 6), setSpan(k, 9, 6), setSegment(k, 0, 0, 6)]));
    """)
    assert [x["t"] for x in out[0]] == [0, 0.5, 2.5]  # the first move faster: the rest follows
    assert [x["t"] for x in out[1]] == [0, 1, 5]
    assert out[2] is None and out[4] is None  # past the end
    assert [x["t"] for x in out[3]] == [0, 0.5, 1.5]  # the whole move twice as fast, in proportion
    assert [x["t"] for x in out[5]] == [0, 0.05, 2.05]  # never shorter than 0.05 s


# ------------------------------------------------------------------ snapping

def test_snap_to_centre_edges_and_other_stickers():
    out = node("""
    import { snapMove, snapSize } from "./web/src/snap.js";
    const box = { x: 0.505, y: 0.497, w: 0.1, h: 0.1 };
    console.log(JSON.stringify({
      centre: snapMove(box, [], 0.01, 0.01),
      free: snapMove({ x: 0.43, y: 0.41, w: 0.02, h: 0.02 }, [], 0.005, 0.005),
      item: snapMove({ x: 0.704, y: 0.2, w: 0.1, h: 0.1 }, [{ x: 0.7, y: 0.8, w: 0.2, h: 0.1 }], 0.01, 0.01),
      safe: snapMove({ x: 0.1, y: 0.4, w: 0.1, h: 0.1 }, [], 0.01, 0.01),
      size: snapSize({ x: 0.5, y: 0.5, w: 0.33, h: 0.2 }, [], 0.01, 0.01, { edge: "right" }),
      keep: snapSize({ x: 0.5, y: 0.5, w: 0.33, h: 0.2 }, [], 0.01, 0.01, { edge: "corner", keep: true }),
    }));
    """)
    c = out["centre"]
    assert c["x"] == pytest.approx(0.5) and c["y"] == pytest.approx(0.5)
    assert {(g["axis"], g["kind"]) for g in c["guides"]} == {("v", "centre"), ("h", "centre")}
    assert out["free"]["x"] == 0.43 and out["free"]["guides"] == []  # nothing near: it stays where you put it
    assert out["item"]["x"] == pytest.approx(0.7) and any(g["kind"] == "item" for g in out["item"]["guides"])
    assert out["safe"]["x"] - 0.05 == pytest.approx(0.05)  # its left edge on the 5% safe margin
    assert out["size"]["w"] == pytest.approx(2 * (2 / 3 - 0.5))  # the right edge lands on the two-thirds line
    assert out["keep"]["h"] / out["keep"]["w"] == pytest.approx(0.2 / 0.33)  # the corner keeps the shape


# ------------------------------------------------------------------ presets

def test_presets_are_cleaned_like_the_real_thing(isolated):
    client, root = isolated
    import storage
    assert storage.DATA == root / "data"
    r = client.post("/api/presets", json={"kind": "sticker", "name": "  My   lower third  ", "data": {
        "kind": "tt-lower", "id": "x", "start": 99, "size": 9, "lines": ["SAM", "Witness"], "length": 3,
        "keyframes": [{"t": 0, "x": 0.2, "ease": "elastic"}, {"t": 1, "x": 0.4, "ease": "nope"}]}})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["name"] == "My lower third" and "id" not in p["data"] and "start" not in p["data"]
    assert p["data"]["size"] <= 1 and p["data"]["lines"] == ["SAM", "Witness"]
    assert [k["ease"] for k in p["data"]["keyframes"]] == ["elastic", "smooth"]
    # a picture move is kept from its first keyframe; a caption style is a full style
    m = client.post("/api/presets", json={"kind": "move", "name": "push in", "data": {"keyframes": [{"t": 1, "zoom": 1}, {"t": 3, "zoom": 1.6, "ease": "bounce"}]}}).json()
    assert [k["t"] for k in m["data"]["keyframes"]] == [0, 2]
    c = client.post("/api/presets", json={"kind": "caption", "name": "", "data": {"preset": "bold", "font": "nope"}}).json()
    assert c["name"] == "My preset" and c["data"]["font"] != "nope"
    # nothing usable / your own picture / unknown kind
    assert client.post("/api/presets", json={"kind": "move", "data": {"keyframes": [{"t": 0}]}}).status_code == 400
    bad = client.post("/api/presets", json={"kind": "sticker", "data": {"kind": "image", "asset_id": "abc"}})
    assert bad.status_code == 400 and "project" in bad.json()["detail"]
    assert client.post("/api/presets", json={"kind": "voice", "data": {}}).status_code == 422
    # one list for the whole app, in the data folder
    got = client.get("/api/presets").json()["presets"]
    assert [x["kind"] for x in got] == ["sticker", "move", "caption"]
    assert (root / "data" / "presets.json").exists()
    assert client.patch(f"/api/presets/{p['id']}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.delete(f"/api/presets/{m['id']}").status_code == 200
    assert client.delete(f"/api/presets/{m['id']}").status_code == 404
    assert [x["name"] for x in client.get("/api/presets").json()["presets"]] == ["Renamed", "My preset"]


def test_a_broken_presets_file_is_ignored(isolated):
    client, root = isolated
    (root / "data" / "presets.json").write_text("{nope")
    assert client.get("/api/presets").json() == {"presets": []}
    (root / "data" / "presets.json").write_text(json.dumps({"presets": [{"id": "a", "kind": "sticker", "name": "x", "data": {"kind": "gone"}}, {"id": "b", "kind": "move", "name": "m", "data": {"keyframes": [{"t": 0}, {"t": 1, "zoom": 2}]}}]}))
    assert [p["id"] for p in presets.load()] == ["b"]


def test_a_saved_move_onto_another_sticker():
    out = node("""
    import { moveOnto } from "./web/src/presets.js";
    const keys = [{ t: 0.5, x: 0.2, y: 0.5, size: 0.2, ease: "bounce" }, { t: 2.5, x: 0.6, y: 0.4, size: 0.4, ease: "smooth" }];
    console.log(JSON.stringify([moveOnto(keys, { x: 0.5, y: 0.5, size: 0.1 }, 6), moveOnto(keys, { x: 0.5, y: 0.5, size: 0.1 }, 1), moveOnto(keys, {}, 6, { shift: [], scale: [] })]));
    """)
    a, short, cam = out
    assert [k["t"] for k in a] == [0, 2] and a[0]["ease"] == "bounce"
    assert a[1]["x"] == pytest.approx(0.9) and a[1]["y"] == pytest.approx(0.4) and a[1]["size"] == pytest.approx(0.2)  # from where it is
    assert [k["t"] for k in short] == [0, 1]  # squeezed to fit a shorter sticker
    assert cam[1]["x"] == 0.6  # a picture move keeps its framing

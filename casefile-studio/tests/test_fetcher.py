"""Fetch from guide (v0.4.19): yt-dlp first, Apify optional.

No network: a stand-in yt-dlp script generates real video files with ffmpeg and
logs every call; Apify is a mock HTTP transport.
"""
import json
import os
import stat
import sys
import textwrap
import time

import httpx
import pytest

import app as server
import fetcher
import renderer
from test_episode import SCRIPT

GUIDE = textwrap.dedent(
    """\
    # Synthetic fetch guide

    **Standing boundaries:** No real evidence. Keep narration unchanged; mute source audio.

    ## Script-by-script placement

    ### HOOK

    1. **At:** “First synthetic sentence” **Show:** Synthetic test pattern. **Preview:** `S03` [Preview](https://www.youtube.com/watch?v=SYNTHvid003&t=20s), around 0:20–0:24. **Label:** SYNTHETIC | 2026 **Care:** Technical fixture.

    ### CHAPTER 1

    2. **At:** “Second synthetic sentence” **Show:** Synthetic still. **Preview:** `S01` [Preview](https://youtu.be/SYNTHvid001). **Label:** SYNTHETIC | 2026 **Care:** Technical fixture.

    ## Source library

    - **S03 — [Synthetic video](https://www.youtube.com/watch?v=SYNTHvid003)** Test video. **Rights:** Test-created.

    - **S01 — [Synthetic clip](https://youtu.be/SYNTHvid001)** Test video. **Rights:** Test-created.

    - **S09 — [Not used anywhere](https://www.youtube.com/watch?v=SYNTHvid009)** Library only.

    - **S10 — [News site upload](https://example.org/news-video)** Not on YouTube.

    ## Base clips

    | Save as | What it shows | YouTube link + time | Type | Tag |
    |---|---|---|---|---|
    | `BASE-V--portrait--01.jpg` | victim portrait in the report | https://www.youtube.com/watch?v=SYNTHvid003&t=12s at 0:12 | frame | portrait |
    | `BASE-C--location--01.mp4` | street, 6 s | https://youtu.be/SYNTHbase01 0:40–0:46 | clip | location |
    | `BASE-S--court--01.jpg` | hearing still | from S03, 0:05 | frame | court |
    | `BASE-V--memorial--01.jpg` | vigil | police release (no link) | frame | memorial |
    """
)

FAKE = textwrap.dedent(
    """\
    #!{python}
    # Stand-in for yt-dlp: writes a real MP4 with ffmpeg; logs its arguments.
    import json, os, re, subprocess, sys
    args = sys.argv[1:]
    log = os.environ["FAKE_YTDLP_LOG"]
    if args == ["--version"]:
        print("2099.01.01"); sys.exit(0)
    with open(log, "a") as f:
        f.write(json.dumps(args) + "\\n")
    url = args[-1]
    vid = re.search(r"v=([A-Za-z0-9_-]{{11}})", url).group(1)
    if vid in os.environ.get("FAKE_YTDLP_FAIL", ""):
        print("ERROR: [youtube] " + vid + ": Video unavailable", file=sys.stderr); sys.exit(1)
    out = args[args.index("-o") + 1]
    length = 90.0
    if "--download-sections" in args:
        length = float(args[args.index("--download-sections") + 1].split("-")[-1])
    path = out.replace("%(ext)s", "mp4")
    if "--download-sections" in args:  # cut sections: ffmpeg's own progress, no byte totals
        import time
        for t in (1.0, length / 2, length):
            s = int(t)
            sys.stderr.write(f"frame=  {{s * 24}} fps= 24 q=-1.0 size=   {{s * 100}}kB time=00:00:{{s:02d}}.00 bitrate= 800kbits/s speed=1x\\r")
            sys.stderr.flush()
            time.sleep(float(os.environ.get("FAKE_YTDLP_PAUSE", "0")))
    elif "--progress-template" in args:  # what real yt-dlp prints with Casefile's template
        import time
        for done in (0, 2500000, 5000000):
            print(f"CFPROG {{done}}|5000000|NA|1250000.0|avc1", flush=True)
            time.sleep(float(os.environ.get("FAKE_YTDLP_PAUSE", "0")))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        f"testsrc2=s=320x180:r=24:d={{length}}", "-f", "lavfi", "-i",
        f"sine=f=440:d={{length}}", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest", path], check=True)
    json.dump({{"title": "Synthetic " + vid, "uploader": "Synthetic Uploader",
        "upload_date": "20260101", "duration": length}},
        open(out.replace("%(ext)s", "info.json"), "w"))
    """
)


@pytest.fixture
def fake_ytdlp(tmp_path, monkeypatch):
    script = tmp_path / "yt-dlp"
    script.write_text(FAKE.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("CASEFILE_YTDLP", str(script))
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(log))
    return log


def calls(log):
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def project_with_guide(c, guide=GUIDE):
    p = c.post("/api/projects", json={"title": "Fetch QA", "mode": "narration"}).json()
    url = "/api/projects/" + p["id"]
    for role, text in [("script", SCRIPT), ("guide", guide)]:
        r = c.post(url + "/episode/import", json={"role": role, "text": text, "filename": role + ".md"})
        assert r.status_code == 200, r.text
    return url


def wait(job_id, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        j = server.JOBS[job_id]
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.2)
    raise AssertionError("fetch job did not finish")


# ---------------------------------------------------------------- unit level


def test_youtube_links_and_times():
    assert fetcher.youtube_id("https://www.youtube.com/watch?v=z0GGKSasvIg&t=26s") == "z0GGKSasvIg"
    assert fetcher.youtube_id("https://youtu.be/z0GGKSasvIg?t=3") == "z0GGKSasvIg"
    assert fetcher.youtube_id("https://www.youtube.com/shorts/z0GGKSasvIg") == "z0GGKSasvIg"
    assert fetcher.youtube_id("https://example.org/watch?v=z0GGKSasvIg") is None
    assert fetcher.youtube_id("https://www.youtube.com/watch?v=short") is None
    assert fetcher.url_time("https://youtu.be/x?t=1m5s") == 65
    assert fetcher.url_time("https://www.youtube.com/watch?v=x&start=90") == 90
    assert fetcher.ranges("around 0:40–0:46 and 1:02:03-1:02:09") == [(40, 46), (3723, 3729)]


def test_plan_reads_sources_base_rows_and_windows(isolated):
    c, _ = isolated
    url = project_with_guide(c)
    plan = c.get(url + "/fetch").json()
    items = {i["save_as"]: i for i in plan["items"]}
    # Footage keeps YouTube timing: 0:00 to the last guide window + margin.
    assert items["S03.mp4"]["need"] == 24 + fetcher.PAD_END and items["S03.mp4"]["status"] == "todo"
    # No window anywhere: the whole video.
    assert items["S01.mp4"]["need"] == "full"
    assert items["S09.mp4"]["status"] == "unused"
    assert items["S10.mp4"]["status"] == "manual"
    frame = items["BASE-V--portrait--01.jpg"]
    assert frame["kind"] == "base-frame" and frame["at"] == 12 and frame["video_id"] == "SYNTHvid003"
    clip = items["BASE-C--location--01.mp4"]
    assert clip["kind"] == "base-clip" and clip["window"] == [40, 46]
    via = items["BASE-S--court--01.jpg"]
    assert via["via_source"] == "S03" and via["at"] == 5
    assert items["BASE-V--memorial--01.jpg"]["status"] == "manual"
    assert "Terms of Service" in plan["notice"] and plan["acknowledged"] is False
    assert set(plan["backends"]) == {"yt-dlp", "apify"}


def test_real_last_timeline_guide_plan():
    g = server.episode.parse_guide(
        (server.ROOT / "examples/the-last-timeline/editing-guide-44.md").read_text()
    )
    plan = fetcher.plan({"episode": {"guide": g}, "assets": []})
    todo = [i for i in plan["items"] if i["status"] == "todo"]
    assert todo and all(i["video_id"] and i["save_as"].startswith(i["id"]) for i in todo)


# ------------------------------------------------------------- end to end


def test_fetch_requires_notice_then_downloads_names_imports_and_links(isolated, fake_ytdlp):
    c, _ = isolated
    url = project_with_guide(c)
    r = c.post(url + "/fetch", json={"backend": "yt-dlp"})
    assert r.status_code == 422 and "notice" in r.text
    r = c.post(url + "/fetch", json={"backend": "yt-dlp", "confirm_responsibility": True})
    assert r.status_code == 200, r.text
    job = wait(r.json()["job_id"])
    assert job["status"] == "done", job
    result = job["result"]
    assert result["fetched"] == 5 and result["failed"] == 0, result

    log = calls(fake_ytdlp)
    vids = [a[-1] for a in log]
    # One download per YouTube video, even though S03 also feeds two base frames.
    assert sorted(vids) == sorted(fetcher.watch_url(v) for v in ("SYNTHvid003", "SYNTHvid001", "SYNTHbase01"))
    s03 = next(a for a in log if a[-1].endswith("SYNTHvid003"))
    assert s03[s03.index("--download-sections") + 1] == f"*0-{int(24 + fetcher.PAD_END) + 1}"
    s01 = next(a for a in log if a[-1].endswith("SYNTHvid001"))
    assert "--download-sections" not in s01  # whole video when no window is known

    p = c.get(url).json()
    assets = {a["name"]: a for a in p["assets"]}
    assert set(assets) >= {"S03.mp4", "S01.mp4", "BASE-V--portrait--01.jpg", "BASE-C--location--01.mp4", "BASE-S--court--01.jpg"}
    assert assets["BASE-V--portrait--01.jpg"]["kind"] == "image"
    assert abs(assets["BASE-C--location--01.mp4"]["duration"] - 6) < 0.3  # cut to its window
    assert assets["S03.mp4"]["duration"] >= 34  # from 0:00, so 0:20–0:24 still lines up
    rec = assets["S03.mp4"]["fetched"]
    assert rec["video_id"] == "SYNTHvid003" and rec["uploader"] == "Synthetic Uploader" and rec["backend"] == "yt-dlp"
    # Fetching never records a reuse basis or rights approval.
    assert all(a["license"] == "" for a in assets.values())
    bindings = p["episode"]["bindings"]
    assert bindings["S03"]["asset_id"] == assets["S03.mp4"]["id"]
    assert bindings["S01"]["asset_id"] == assets["S01.mp4"]["id"]
    assert not bindings["S03"].get("rights_confirmed")
    assert p["episode"]["fetch_ack"]["notice"] == server.FETCH_NOTICE

    # Everything is here now: the plan says so and a second fetch does nothing.
    plan = c.get(url + "/fetch").json()
    assert plan["counts"].get("todo", 0) == 0 and plan["acknowledged"]
    assert c.post(url + "/fetch", json={"backend": "yt-dlp"}).status_code == 422


def test_one_failing_video_does_not_stop_the_rest(isolated, fake_ytdlp, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_FAIL", "SYNTHvid001")
    c, _ = isolated
    url = project_with_guide(c)
    r = c.post(url + "/fetch", json={"backend": "yt-dlp", "confirm_responsibility": True})
    job = wait(r.json()["job_id"])
    res = {x["save_as"]: x for x in job["result"]["results"]}
    assert not res["S01.mp4"]["ok"] and "Video unavailable" in res["S01.mp4"]["error"]
    assert res["S03.mp4"]["ok"] and res["BASE-C--location--01.mp4"]["ok"]
    # It was retried before giving up.
    assert sum(1 for a in calls(fake_ytdlp) if a[-1].endswith("SYNTHvid001")) == 2
    # Retry later fetches only what is still missing.
    plan = c.get(url + "/fetch").json()
    assert [i["save_as"] for i in plan["items"] if i["status"] == "todo"] == ["S01.mp4"]


def test_only_selected_items(isolated, fake_ytdlp):
    c, _ = isolated
    url = project_with_guide(c)
    r = c.post(url + "/fetch", json={"confirm_responsibility": True, "only": ["BASE-C--location--01.mp4"]})
    job = wait(r.json()["job_id"])
    assert job["result"]["fetched"] == 1
    assert [a[-1] for a in calls(fake_ytdlp)] == [fetcher.watch_url("SYNTHbase01")]


def test_missing_ytdlp_is_reported_not_crashed(isolated, monkeypatch):
    monkeypatch.setenv("CASEFILE_YTDLP", "")
    monkeypatch.setattr(fetcher.shutil, "which", lambda name: None)
    c, _ = isolated
    url = project_with_guide(c)
    assert c.get(url + "/fetch").json()["backends"]["yt-dlp"]["ready"] is False
    r = c.post(url + "/fetch", json={"confirm_responsibility": True})
    assert r.status_code == 422 and "yt-dlp is not installed" in r.text


# ------------------------------------------------------------------- Apify


def mp4_bytes(tmp_path, seconds=50):
    path = tmp_path / "apify-src.mp4"
    import subprocess

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=24:d={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", str(path)],
        check=True,
    )
    return path.read_bytes()


def apify_client(tmp_path, row=None, seen=None):
    video = mp4_bytes(tmp_path)
    seen = seen if seen is not None else []

    def handler(request):
        seen.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(200, json=[row or {
                "success": True, "sourceUrl": body["url"],
                "downloadUrl": "https://api.apify.com/v2/key-value-stores/k/records/video.mp4",
                "filename": "video.mp4",
            }])
        return httpx.Response(200, content=video)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_apify_backend_downloads_through_the_actor(tmp_path):
    client, seen = apify_client(tmp_path)
    a = fetcher.Apify("tok123", client=client)
    assert a.status()["ready"]
    path, info = a.download("SYNTHvid003", 34, tmp_path, lambda: False)
    assert path.stat().st_size > 1000 and info["actor"] == fetcher.DEFAULT_ACTOR
    post = seen[0]
    assert post.url.path == "/v2/acts/danng~youtube-to-mp4-youtube-downloader-with-yt-dlp/run-sync-get-dataset-items"
    assert post.url.params["token"] == "tok123"
    assert json.loads(post.content) == {"url": fetcher.watch_url("SYNTHvid003")}
    # The same cutting rules apply after an Apify download.
    out = fetcher.materialize(
        {"kind": "base-clip", "save_as": "BASE-C--x--01.mp4", "window": [10, 16]}, path, tmp_path
    )
    assert abs(renderer.probe(out)["duration"] - 6) < 0.3


def test_apify_errors_are_plain(tmp_path):
    client, _ = apify_client(tmp_path, row={"success": False, "error": "Video unavailable"})
    with pytest.raises(fetcher.FetchError, match="Video unavailable"):
        fetcher.Apify("t", client=client).download("SYNTHvid003", "full", tmp_path, lambda: False)
    client, _ = apify_client(tmp_path, row={"success": True, "title": "no link"})
    with pytest.raises(fetcher.FetchError, match="no download link"):
        fetcher.Apify("t", client=client).download("SYNTHvid003", "full", tmp_path, lambda: False)
    assert fetcher.Apify("").status()["ready"] is False


def test_apify_token_stays_in_memory(isolated, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    c, _ = isolated
    url = project_with_guide(c)
    r = c.post(url + "/fetch", json={"backend": "apify", "apify_token": "secret-token-xyz"})
    assert r.status_code == 422  # notice not accepted yet
    assert c.get(url + "/fetch").json()["apify_token_saved"] is True
    project_file = (server.DATA / "projects" / (url.rsplit("/", 1)[1] + ".json")).read_text()
    assert "secret-token-xyz" not in project_file


def test_each_file_reports_its_own_progress(isolated, fake_ytdlp, monkeypatch):
    monkeypatch.setenv("FAKE_YTDLP_FAIL", "SYNTHvid001")
    monkeypatch.setenv("FAKE_YTDLP_PAUSE", "0.6")
    c, _ = isolated
    url = project_with_guide(c)
    pid = url.rsplit("/", 1)[1]
    r = c.post(url + "/fetch", json={"backend": "yt-dlp", "confirm_responsibility": True})
    job_id = r.json()["job_id"]
    seen = {}
    end = time.time() + 120
    while time.time() < end:
        j = next(x for x in c.get(url + "/jobs").json() if x["id"] == job_id)
        for fid, f in (j.get("files") or {}).items():
            seen.setdefault(fid, set()).add(f["status"])
            if f["status"] == "downloading" and f.get("total"):
                assert f["done"] <= f["total"] == 5000000 and f["speed"] == 1250000.0
                assert "idle" in f
            if f["status"] == "downloading" and f.get("secs_total"):
                assert 0 <= f["secs"] <= f["secs_total"]  # cut sections: how far into the video
                seen.setdefault("_secs", set()).add(f["secs"])
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.15)
    files = j["files"]
    assert files["S01"]["status"] == "failed" and "Video unavailable" in files["S01"]["error"]
    assert files["S03"]["status"] == "done" and files["S03"]["save_as"] == "S03.mp4"
    assert any("downloading" in s for s in seen.values())  # live, file by file
    assert len(seen.get("_secs", ())) >= 2  # a real percentage for cut sections, moving
    # Retry just the failed one.
    monkeypatch.setenv("FAKE_YTDLP_FAIL", "")
    monkeypatch.setenv("FAKE_YTDLP_PAUSE", "0")
    r = c.post(url + "/fetch", json={"confirm_responsibility": True, "only": ["S01"]})
    job = wait(r.json()["job_id"])
    assert list(job["files"]) == ["S01"] and job["files"]["S01"]["status"] == "done"


def test_ffmpeg_time_lines_are_parsed():
    assert fetcher.ffmpeg_seconds("frame= 120 fps=24 size= 1024kB time=00:01:12.40 bitrate=") == 72.4
    assert fetcher.ffmpeg_seconds("time=N/A") is None and fetcher.ffmpeg_seconds("time=-00:00:00.02") is None


def test_progress_lines_are_parsed():
    assert fetcher.parse_progress("CFPROG 100|NA|400|25.5|none") == {"done": 100.0, "total": 400.0, "speed": 25.5, "part": "audio"}
    assert fetcher.parse_progress("CFPROG NA|NA|NA|NA|NA")["done"] is None
    assert fetcher.parse_progress("[download] 12%") is None

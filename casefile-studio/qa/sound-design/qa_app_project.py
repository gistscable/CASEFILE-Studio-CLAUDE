"""v0.4.59 A small project for browser_sound_qa.mjs, in a QA data folder (never data/).

    CASEFILE_DATA_DIR=/tmp/qa/app python -m uvicorn app:app --port 8000   # the app, on the QA data
    python qa/sound-design/qa_app_project.py http://127.0.0.1:8000 /tmp/qa/app   # prints the project id

40 s of narration-like tone (4 scenes of 10 s, chapters 1 and 2), a 9 s music track placed on
scene 2 and chapter 2 (so it loops with crossfades), sound design on with no sound of its own.
Every run makes a fresh project (the QA moves sliders and adds a sound, which are saved)."""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from PIL import Image

base, data = sys.argv[1].rstrip("/"), Path(sys.argv[2])
req = urllib.request.Request(f"{base}/api/projects", data=json.dumps({"title": "QA sound", "topic": "qa"}).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
pid = json.loads(urllib.request.urlopen(req).read())["id"]
media = data / "media" / pid
media.mkdir(parents=True, exist_ok=True)
gate = "0.3*sin(2*PI*220*t)*max(0\\,sin(2*PI*0.35*t))"  # speech-like: on and off
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc={gate}:s=48000:d=40", "-ac", "1", str(media / "voice.wav")], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc='0.2*sin(2*PI*110*t)+0.1*sin(2*PI*165*t)':s=48000:d=9",
                "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", str(media / "music.mp3")], check=True)
Image.new("RGB", (1280, 720), (40, 40, 48)).save(media / "plate.png")


def asset(id_, kind, name, **kw):
    return {"id": id_, "kind": kind, "name": name, "path": str(media / name), "url": f"/media/{pid}/{name}", **kw}


assets = [asset("img", "image", "plate.png", width=1280, height=720),
          asset("nar", "audio", "voice.wav", duration=40.0, has_audio=True),
          asset("mus", "audio", "music.mp3", duration=9.0, has_audio=True)]
scenes = [{"id": f"{k + 1:016x}", "title": f"Scene {k + 1}", "narration": "", "duration": 10.0, "asset_id": "img", "motion": "none",
           "show_title": False, "audio_start": k * 10.0, "audio_duration": 10.0, "chapter": f"CHAPTER {k // 2 + 1}"} for k in range(4)]
f = data / "projects" / f"{pid}.json"
p = json.loads(f.read_text())
p.update({"assets": assets, "scenes": scenes, "narration_id": "nar", "music_id": "mus", "music_volume": 0.25, "narration_volume": 1.0,
          "look": "natural", "captions": False, "sound": {"enabled": True, "items": [], "master": 0.8},
          "music": {"mode": "scenes", "scenes": [scenes[1]["id"]], "chapters": ["CHAPTER 2"], "crossfade": 1.0}})
f.write_text(json.dumps(p, indent=1))
print(pid)

# v0.4.59 QA scratch script kept for reproducibility (run from casefile-studio/ with PATH=$PWD/.venv/bin:$PATH, PYTHONPATH=$PWD).
"""Does the export keep the last seconds of the narration? A sliced (non-guide) project, with and without effects / music."""
import json, subprocess, sys, os
from pathlib import Path
sys.path.insert(0, '.')
import numpy as np
from PIL import Image
import renderer
D = renderer.DATA / "media" / "tail"; D.mkdir(parents=True, exist_ok=True)
Image.new("RGB", (640, 360), (40, 40, 48)).save(D / "plate.png")
voice = D / "voice.wav"
# speech-like all the way to the very end (a tone until 40.0 s)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*3*t))':s=48000:d=40", "-ac", "1", str(voice)], check=True)
music = D / "music.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "aevalsrc='0.2*sin(2*PI*110*t)':s=48000:d=30", "-ac", "2", str(music)], check=True)
assets = [{"id": "img", "kind": "image", "path": str(D / "plate.png"), "name": "plate.png", "width": 640, "height": 360},
          {"id": "nar", "kind": "audio", "path": str(voice), "name": "voice.wav", "duration": 40.0, "has_audio": True},
          {"id": "mus", "kind": "audio", "path": str(music), "name": "music.wav", "duration": 30.0, "has_audio": True}]
sc = [{"id": f"{k:016x}", "title": "", "narration": "", "duration": 10.0, "asset_id": "img", "motion": "none", "show_title": False,
       "audio_start": k * 10.0, "audio_duration": 10.0} for k in range(4)]
base = {"id": "5d000000000000aa", "title": "tail", "look": "natural", "captions": False, "music_volume": 0, "assets": assets, "scenes": sc,
        "narration_id": "nar", "exports": []}
items = [{"anchor": "t:5.0", "sound": "swell-2", "source": "manual", "gain": 0.0}]
cases = {
    "narration only": {},
    "narration + effects (ducked)": {"sound": {"enabled": True, "items": items}},
    "narration + music (ducked)": {"music_id": "mus", "music_volume": 0.2},
    "narration + music + effects": {"music_id": "mus", "music_volume": 0.2, "sound": {"enabled": True, "items": items}},
    "guide: narration + music + effects": {"music_id": "mus", "music_volume": 0.2, "sound": {"enabled": True, "items": items},
                                           "episode": {"guide": True, "plan": {"mode": "final"}}},
}
import episode
episode.issues = lambda project: []
out = {}
for name, extra in cases.items():
    p = {**base, **extra}
    f = Path(f"/tmp/tail-{len(out)}.mp4")
    renderer.render(json.loads(json.dumps(p)), {"resolution": "480p", "draft": False, "captions": False}, f, lambda *a: None, lambda: False)
    a = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"], capture_output=True).stdout, np.float32)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout or 0)
    last = a[-48000:] if len(a) >= 48000 else a
    out[name] = {"audio_s": round(len(a) / 48000, 3), "stream_duration": dur, "rms_last_second_db": float(round(20 * np.log10(np.sqrt(np.mean(last ** 2)) + 1e-9), 1)),
                 "rms_37_38_db": float(round(20 * np.log10(np.sqrt(np.mean(a[37 * 48000:38 * 48000] ** 2)) + 1e-9), 1)) if len(a) > 38 * 48000 else None}
    print(name, out[name], flush=True)
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tail.json", "w"), indent=1)

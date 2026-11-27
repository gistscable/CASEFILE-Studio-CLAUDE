"""Re-mix a demo's sound design and remux it onto the already-rendered video (video stream copied,
not re-encoded) — sound tweaks never cost a re-render."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cinegfx import sfx, core  # noqa
from cinegfx.timing import ffbin  # noqa
import make_demos as M  # noqa

HERE = Path(__file__).resolve().parent
story = M.S.parse_script((HERE / "javits-script.md").read_text())
coll = core.load_collections()["truecrime"]
texts = json.loads((HERE / "narration" / "texts.json").read_text())
for key in (sys.argv[1:] or texts):
    a, b = M.window_for(story, texts[key])
    score, cat, payload, why = M.classify(story, coll, a, b)[0]
    audio = str(HERE / "narration" / f"{key}.mp3")
    tl = M.TM.timeline_for(audio, texts[key])
    g = M.render.build(("truecrime", cat, core.Beat("truecrime", cat, a, b, score, payload, why), tl, str(HERE / "photos")))
    wav = str(HERE / "out" / f"{key}.wav")
    sfx.mix(g.cues, audio, g.duration, wav)
    src, tmp = HERE / f"{key}.mp4", HERE / f"{key}.tmp.mp4"
    subprocess.run([ffbin(), "-v", "error", "-y", "-nostdin", "-i", str(src), "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(src)
    Path(wav).unlink()
    print("remixed", key, flush=True)

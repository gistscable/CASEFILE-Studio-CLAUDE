"""v0.4.58 Music bed cost at documentary length: the music branch of the final mix alone, rendered
to the null muxer, v0.4.57 (`-stream_loop -1` + fades + volume) against v0.4.58 (music.filters).

    cd casefile-studio && PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/sound-design/music_bench.py track.mp3 [timeline_s]
"""
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import music  # noqa: E402


def run(cmd):
    r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t = time.monotonic()
    subprocess.run(cmd, check=True, capture_output=True)
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"wall_s": round(time.monotonic() - t, 2), "cpu_s": round(r1.ru_utime + r1.ru_stime - r0.ru_utime - r0.ru_stime, 2),
            "max_rss_mb": round(r1.ru_maxrss / 1024)}


def probe(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, check=True).stdout)


def main(track, total=1500.0):
    d = probe(track)
    out = {"track_s": round(d, 3), "timeline_s": total}
    # v0.4.57 (renderer at c6ec51e): hard restart, fixed fades
    old = ["ffmpeg", "-v", "error", "-nostdin", "-stream_loop", "-1", "-i", str(track), "-filter_complex",
           f"[0:a]atrim=duration={total},afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, total - 2)}:d=2,volume=0.2[o]", "-map", "[o]", "-f", "null", "-"]
    out["v0.4.57 stream_loop"] = run(old)
    for name, s in [("v0.4.58 loop, 2 s crossfade", {}), ("v0.4.58 loop, 0.5 s crossfade", {"crossfade": 0.5}),
                    ("v0.4.58 part 0:30-1:00 looped (aloop)", {"start": 30, "end": 60}), ("v0.4.58 once", {"mode": "once"})]:
        lay = music.layout(music.normalise(s), d, total)
        args, f = music.filters(lay, str(track), 0, total)
        r = run(["ffmpeg", "-v", "error", "-nostdin", *args, "-filter_complex", ";".join(f) + ";[mus]volume=0.2[o]", "-map", "[o]", "-f", "null", "-"])
        r["passes"] = sum(len(x["iters"]) for x in lay["runs"])
        r["inputs_opened"] = args.count("-i")
        r["path"] = "aloop" if r["passes"] > music.CHAIN_MAX else "crossfade chain"
        out[name] = r
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1500.0)

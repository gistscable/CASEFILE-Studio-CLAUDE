"""v0.4.56 Sound design benchmark on a real project file (no media needed: the plan and the stem
only read the timeline). Reports wall time, CPU time and peak memory of each step.

    cd casefile-studio && PATH=$PWD/.venv/bin:$PATH .venv/bin/python qa/sound-design/benchmark.py project.json
"""
import json
import os
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import sfxlib  # noqa: E402
import sound  # noqa: E402


def step(name, fn, out):
    c0, t0 = time.process_time(), time.perf_counter()
    r = fn()
    out[name] = {"wall_s": round(time.perf_counter() - t0, 3), "cpu_s": round(time.process_time() - c0, 3),
                 "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024}
    return r


def main(path):
    p = json.loads(Path(path).read_text())
    p["sound"] = {"enabled": True}
    data = Path(tempfile.mkdtemp(prefix="sfxbench-"))
    total = sum(round(float(s["duration"]) * 24) / 24 for s in p["scenes"])
    out = {"project": {"scenes": len(p["scenes"]), "minutes": round(total / 60, 2),
                       "graphics": len([i for i in (p.get("motion") or {}).get("items", []) if i.get("status") == "approved"])},
           "cpu_count": os.cpu_count()}
    step("library_all_78_sounds_first_time", lambda: sfxlib.ensure(data, [c[0] for c in sfxlib.CATALOG]), out)
    sound._EVENTS.clear()
    evs = step("events_first_time", lambda: sound.events(p), out)
    step("events_cached", lambda: sound.events(p), out)
    items, info = step("plan", lambda: sound.plan(p), out)
    placed, gone = step("resolve", lambda: sound.resolve(p, data), out)
    step("stem_write_full_timeline", lambda: sound.stem(p, data, total, data), out)
    step("stem_cache_hit", lambda: sound.stem(p, data, total, data), out)
    # one sound edited: the plan of the others is unchanged and only the stem is written again
    edited = dict(items[len(items) // 2], gain=-12.0, edited=True)
    p["sound"] = {"enabled": True, "items": [edited]}
    items2, _ = step("plan_after_one_edit", lambda: sound.effective(p), out)
    same = sum(1 for a in items2 if a["id"] != edited["id"] and a in items)
    step("stem_after_one_edit", lambda: sound.stem(p, data, total, data), out)
    # every planned sound moved by 5 frames and made quieter: the planner still adds or drops nothing
    p["sound"] = {"enabled": True, "items": [dict(it, gain=it["gain"] - 3.0, offset=5 / 24, edited=True) for it in items]}
    items3, _ = step("plan_with_every_sound_edited", lambda: sound.effective(p), out)
    p["sound"] = {"enabled": True, "items": []}
    out["result"] = {"events": len(evs), "planned": len(items), "silenced": len(info["silenced"]), "placed": len(placed), "gone": len(gone),
                     "unchanged_after_one_edit": f"{same}/{len(items) - 1}",
                     "same_moments_with_every_sound_edited": sorted(i["anchor"] for i in items3) == sorted(i["anchor"] for i in items),
                     "stem_mb": round(sum(f.stat().st_size for f in (data / "cache" / "sfx" / "stems").glob("*.flac")) / 2 / 1e6, 2)}
    print(json.dumps(out, indent=1))
    shutil.rmtree(data, ignore_errors=True)
    return out


if __name__ == "__main__":
    main(sys.argv[1])

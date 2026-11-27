"""v0.4.65 One command: the cinematic engine run automatically on a real project, timed (for the MacBook Air M1).

It reads one of your projects (never changes it: it works on a copy in memory) and does what the app does:

  1. reads the narration, captions, production script and footage guide and places the cinematic graphics
     (where, which category, the words, each element's timing)          -> "suggest"
  2. proposes how each is presented (full screen / over the footage / partial), from the design, the shots
     under it and the script's chapter and shot notes                    -> "present" (applied here only with --apply)
  3. draws each graphic's export layer at 1920x1080 through the export code (the same frames the preview shows)
  4. makes a review MP4 of each: the graphic over its footage when that file is on this machine (else on black),
     with its narration and its own sound cues mixed as the export does (ducked under the voice)

and writes report.md / report.json with what it decided and how long every step took.

Usage (from casefile-studio/, the app's own Python):
  .venv/bin/python qa/motion_check.py                       # the most recently edited project with narration
  .venv/bin/python qa/motion_check.py --project 1a5bbba59d244274 --apply
  .venv/bin/python qa/motion_check.py --list                # your projects
Options: --data DIR (default: CASEFILE_DATA_DIR or ./data), --out DIR (default: qa/motion-check/<project>),
         --no-mp4 (time the engine only), --workers N.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _data_dir(arg):
    return Path(arg or os.environ.get("CASEFILE_DATA_DIR") or ROOT / "data").resolve()


def _projects(data):
    out = []
    for f in sorted((data / "projects").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            p = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        out.append((f, p))
    return out


def _machine():
    info = {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "python": platform.python_version(), "cpus": os.cpu_count()}
    if platform.system() == "Darwin":
        try:
            info["chip"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
            info["memory_gb"] = round(int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30, 1)
        except (OSError, ValueError):
            pass
    return info


def _asset_file(data, project, asset):
    import renderer
    try:
        f = Path(renderer.asset_path(asset))
        return f if f.is_file() else None
    except Exception:  # noqa: BLE001 - a missing or odd asset is reported, never fatal
        return None


def _footage_under(data, project, item):
    """(file, seconds into it) of the shot under the middle of the graphic, when that video is on this machine."""
    import motion
    scenes = project.get("scenes") or []
    offsets, _ = motion.scene_offsets(scenes)
    mid = (float(item["start"]) + float(item["end"])) / 2
    assets = {a["id"]: a for a in project.get("assets") or []}
    for i, s in enumerate(scenes):
        b = offsets[i] + max(1, round(float(s.get("duration") or 0) * motion.FPS)) / motion.FPS
        if offsets[i] <= mid < b:
            a = assets.get(s.get("asset_id"))
            if a and a.get("kind") == "video":
                f = _asset_file(data, project, a)
                if f:
                    return f, max(0.0, float(s.get("trim_start") or 0) + float(item["start"]) - offsets[i])
            return None
    return None


def _narration(data, project):
    """The narration audio file, when it is on this machine (the episode's voice track)."""
    for a in project.get("assets") or []:
        if a.get("kind") == "audio":
            f = _asset_file(data, project, a)
            if f:
                return f
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--apply", action="store_true", help="apply the presentation proposals before drawing")
    ap.add_argument("--no-mp4", action="store_true")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    data = _data_dir(a.data)
    os.environ["CASEFILE_DATA_DIR"] = str(data)
    import storage
    import renderer
    storage.DATA = renderer.DATA = data
    import cinematic
    import motion
    import presentation
    from cinegfx import sfx

    projects = _projects(data)
    if a.list or not projects:
        for f, p in projects:
            print(f"{p.get('id')}  {p.get('title')!r}  scenes={len(p.get('scenes') or [])}")
        if not projects:
            print(f"No projects in {data}/projects")
        return 0 if projects else 1
    if a.project:
        found = [p for f, p in projects if p.get("id") == a.project]
        if not found:
            print(f"No project {a.project} in {data}")
            return 1
        project = found[0]
    else:
        project = next((p for f, p in projects if any((s.get("narration") or "").strip() for s in p.get("scenes") or [])), projects[0][1])
    project = copy.deepcopy(project)  # never written back
    out = Path(a.out or ROOT / "qa" / "motion-check" / project["id"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"Project {project['id']} {project.get('title')!r}: {len(project.get('scenes') or [])} scenes -> {out}")
    rep = {"project": {"id": project["id"], "title": project.get("title")}, "machine": _machine(), "steps": {}, "graphics": []}

    # 1. placement from the story
    cur = motion.normalise(project.get("motion"))
    keep = [x for x in cur["items"] if x["template"] != "cinematic" or x["status"] != "suggested"]
    t0 = time.perf_counter()
    cinematic._STORY.clear()
    new = cinematic.suggest(project, keep)
    rep["steps"]["suggest_s"] = round(time.perf_counter() - t0, 3)
    t0 = time.perf_counter()
    cinematic.suggest(project, keep)
    rep["steps"]["suggest_again_s"] = round(time.perf_counter() - t0, 3)  # the story is cached: what an edit costs
    project["motion"] = motion.normalise({"enabled": True, "items": keep + new, "look": cur.get("look")})
    print(f"  suggest: {len(new)} graphics in {rep['steps']['suggest_s']} s (again {rep['steps']['suggest_again_s']} s)")

    # 2. presentation
    t0 = time.perf_counter()
    props = presentation.propose(project)
    rep["steps"]["present_s"] = round(time.perf_counter() - t0, 3)
    if a.apply:
        by = {p["id"]: p for p in props if not p["same"]}
        m = project["motion"]
        for it in m["items"]:
            if it["id"] in by:
                it["look"] = presentation.apply(it.get("look"), by[it["id"]])
        project["motion"] = motion.normalise(m)
    print(f"  present: {sum(not p['same'] for p in props)} changes proposed in {rep['steps']['present_s']} s"
          + (" (applied)" if a.apply else " (not applied; --apply to use them)"))

    narration = _narration(data, project)
    rep["narration_file"] = bool(narration)
    pmap = {p["id"]: p for p in props}
    cine = [x for x in project["motion"]["items"] if x["template"] == "cinematic"]
    tmp = Path(tempfile.mkdtemp(prefix="motion-check-"))
    try:
        for n, it in enumerate(cine, 1):
            files = cinematic.photo_files(project, it, renderer.asset_path, data)
            g_rep = {"id": it["id"], "category": it["category"], "label": it.get("label"), "start": it["start"], "end": it["end"],
                     "seconds": round(it["end"] - it["start"], 2), "words": it.get("text", "")[:300], "reason": it.get("reason"),
                     "presentation": {k: pmap.get(it["id"], {}).get(k) for k in ("current", "mode", "reasons")},
                     "background": cinematic.backdrop_used(it, files), "photos": sorted(k for k in files if k != cinematic.BACKDROP)}
            t0 = time.perf_counter()
            cinematic._GRAPHICS.clear()
            g = cinematic.build(it, files)
            g_rep["build_s"] = round(time.perf_counter() - t0, 3)
            t0 = time.perf_counter()
            cinematic.frame(g, it, 0, 960, 540)
            g_rep["first_frame_s"] = round(time.perf_counter() - t0, 3)
            g_rep["cues"] = cinematic.cues(it, files)
            mov = tmp / f"{n}.mov"
            t0 = time.perf_counter()
            frames = cinematic.encode(it, files, 1920, 1080, mov, workers=a.workers)
            dt = time.perf_counter() - t0
            g_rep.update({"frames": frames, "encode_s": round(dt, 2), "encode_fps": round(frames / dt, 1),
                          "workers": a.workers or cinematic.workers_for(frames), "realtime_x": round((frames / cinematic.FPS) / dt, 2)})
            if not a.no_mp4:
                t0 = time.perf_counter()
                dur = frames / cinematic.FPS
                wav = tmp / f"{n}.wav"
                voice = tmp / f"{n}-voice.wav"
                ff = shutil.which("ffmpeg") or "ffmpeg"
                if narration:
                    subprocess.run([ff, "-v", "error", "-y", "-nostdin", "-ss", f"{it['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(narration),
                                    "-ac", "2", "-ar", str(sfx.SR), str(voice)], check=True)
                else:
                    subprocess.run([ff, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-t", f"{dur:.3f}", "-i",
                                    f"anullsrc=r={sfx.SR}:cl=stereo", str(voice)], check=True)
                cue_objs = [type("Cue", (), c) for c in g_rep["cues"]]
                sfx.mix(cue_objs, str(voice), dur, str(wav))
                foot = _footage_under(data, project, it) if g_rep["background"] == "footage" else None
                g_rep["review_over"] = "footage" if foot else ("its own background" if g_rep["background"] != "footage" else
                                                              "black (the footage file is not on this machine)")
                bg = (["-ss", f"{foot[1]:.3f}", "-t", f"{dur:.3f}", "-i", str(foot[0])] if foot else
                      ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"color=c=black:s=1920x1080:r={cinematic.FPS}"])
                mp4 = out / f"{n:02d}-{it['category']}.mp4"
                subprocess.run([ff, "-v", "error", "-y", "-nostdin", *bg, "-i", str(mov), "-i", str(wav), "-filter_complex",
                                f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps={cinematic.FPS},setsar=1[b];"
                                "[b][1:v]overlay=0:0:format=auto[v]", "-map", "[v]", "-map", "2:a", "-t", f"{dur:.3f}",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                                str(mp4)], check=True)
                g_rep["review_mp4"] = mp4.name
                g_rep["review_s"] = round(time.perf_counter() - t0, 2)
            rep["graphics"].append(g_rep)
            print(f"  {n}. {it['category']:<13} {g_rep['seconds']:>5.1f} s  {g_rep['presentation']['mode'] or '':<8} "
                  f"build {g_rep['build_s']} s · encode {g_rep['encode_s']} s ({g_rep['encode_fps']} fps, {g_rep['realtime_x']}x real time)"
                  + (f" · review {g_rep['review_s']} s" if "review_s" in g_rep else ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    total = sum(x["encode_s"] for x in rep["graphics"])
    secs = sum(x["frames"] for x in rep["graphics"]) / cinematic.FPS
    rep["steps"]["encode_total_s"] = round(total, 2)
    rep["steps"]["graphics_seconds"] = round(secs, 2)
    (out / "report.json").write_text(json.dumps(rep, indent=2, default=str))
    (out / "report.md").write_text(_markdown(rep, a.apply))
    print(f"  total: {len(rep['graphics'])} graphics, {secs:.1f} s of graphics drawn in {total:.1f} s -> {out / 'report.md'}")
    return 0


def _markdown(rep, applied):
    m = rep["machine"]
    L = [f"# Motion check: {rep['project']['title']}", "",
         f"Machine: {m.get('chip') or m['machine']} · {m['system']} {m['release']} · {m['cpus']} cores"
         + (f" · {m['memory_gb']} GB" if m.get("memory_gb") else "") + f" · Python {m['python']}", "",
         "| Step | Seconds |", "|---|---|"]
    for k, v in rep["steps"].items():
        L.append(f"| {k} | {v} |")
    L += ["", f"Narration audio on this machine: {'yes' if rep['narration_file'] else 'no (the review clips have the sound cues only)'}.",
          f"Presentation proposals: {'applied' if applied else 'shown, not applied'}.", ""]
    for n, g in enumerate(rep["graphics"], 1):
        L += [f"## {n}. {g['label']} ({g['category']}, {g['start']:.2f}-{g['end']:.2f} s)", "",
              f"Why here: {g['reason']}", "", f"Words: “{g['words']}”", "",
              f"Presentation: {g['presentation'].get('current')} -> {g['presentation'].get('mode')}"]
        L += [f"- {r}" for r in g["presentation"].get("reasons") or []]
        L += ["", f"Sound cues: " + ", ".join(f"{c['t']:.2f} s {c['sfx']} ({c['why']})" for c in g["cues"]), "",
              f"Build {g['build_s']} s · first frame {g['first_frame_s']} s · {g['frames']} frames encoded in {g['encode_s']} s "
              f"({g['encode_fps']} fps, {g['workers']} workers, {g['realtime_x']}x real time)"
              + (f" · review clip `{g['review_mp4']}` over {g['review_over']} in {g['review_s']} s" if g.get("review_mp4") else ""), ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())

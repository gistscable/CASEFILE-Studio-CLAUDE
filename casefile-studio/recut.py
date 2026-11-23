"""Re-cut (v0.4.22): put the real voices into a finished video.

Takes a rendered video and a list of inserts. At each insert the video stops at
"at", the original clip plays with its own picture and sound, and the video
carries on from "until". The stretch between "at" and "until" is the narrator
reading the same words, so it is skipped: the speaker says the line once and
the narrator does not repeat it. When "until" equals "at" nothing is skipped.

The insert list can be typed in the app or read from a re-cut list document
(the Markdown the guide writer produces: a table of cut points and a table of
the clips that will play). Playing a clip's own sound is the producer's
decision, clip by clip; this module never assumes it.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import captionstyle
import cutaways as cutaway_rules
import effects

FPS = 24
STALL_SECONDS = 180  # a step with no progress for this long is stopped
_T = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"


class RecutError(RuntimeError):
    pass


def seconds(stamp):
    parts = str(stamp).replace(",", ".").split(":")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def clock(sec, decimals=2):
    m, s = divmod(max(0.0, float(sec)), 60)
    return f"{int(m)}:{s:0{3 + decimals if decimals else 2}.{decimals}f}"


def _tables(text):
    out, cur = [], None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cur is None:
                cur = {"header": [c.lower() for c in cells], "rows": []}
            elif not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in cells):
                cur["rows"].append(cells)
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def _col(header, *names):
    for i, h in enumerate(header):
        if any(n in h for n in names):
            return i
    return None


def _exact(header, *names):
    """A column whose whole name is one of `names` (so "rc" does not match "source")."""
    for i, h in enumerate(header):
        if re.sub(r"[^a-z]", "", h) in names:
            return i
    return None


_ID_COLS = ("rc", "rcid", "id", "insert", "insertid", "clipid")


def _key(cell):
    m = re.search(r"\d+", cell or "")
    return m.group(0) if m else re.sub(r"\W+", "", (cell or "").lower())


def parse(text):
    """Inserts from a re-cut list: [{at, source_id, video_id, start, end, who,
    words, optional, note}] in playing order."""
    # v0.4.37: several inserts can share a chapter. They are matched by an
    # RC / ID column when both tables have one, otherwise the n-th cut of a
    # chapter goes with the n-th clip of that chapter.
    cuts, clips, direct, cuts_away = {}, {}, [], {}
    for t in _tables(text):
        h = t["header"]
        i_at = _col(h, "cut from", "insert at", "at")
        i_clip, i_win = _col(h, "clip", "source"), _col(h, "window", "from")
        i_ch = _col(h, "chapter", "order", "#")
        if i_at is not None and i_clip is not None and i_win is not None and _col(h, "cut from") is None:
            for r in t["rows"]:  # one simple table: At | Source | Window
                if len(r) <= max(i_at, i_clip, i_win):
                    continue
                at = re.search(_T, r[i_at])
                span = re.findall(_T, " ".join(r[i_win:i_win + 2]))
                sid = re.search(r"[A-Z]{1,3}\d{1,3}", r[i_clip])
                if at and len(span) >= 2 and sid:
                    i_res = _col(h, "resume", "cut to", "continue", "until")
                    res = re.search(_T, r[i_res]) if i_res is not None and i_res < len(r) else None
                    a_t = seconds(at.group(0))
                    direct.append({"at": a_t, "until": max(a_t, seconds(res.group(0))) if res else a_t,
                                   "source_id": sid.group(0), "start": seconds(span[0]), "end": seconds(span[1])})
            continue
        # v0.4.38: picture cutaways inside a clip: | RC | From | To | Show |
        i_rc, i_show = _exact(h, *_ID_COLS), _col(h, "show", "picture", "cutaway")
        i_from, i_to2 = _exact(h, "from", "start", "cutawayfrom"), _exact(h, "to", "end", "cutawayto")
        if i_rc is not None and i_show is not None and i_from is not None and i_to2 is not None and _col(h, "cut from") is None:
            for r in t["rows"]:
                if len(r) <= max(i_rc, i_show, i_from, i_to2) or not r[i_rc]:
                    continue
                row = cutaway_rules.parse_row(r[i_from], r[i_to2], r[i_show])
                if row:
                    cuts_away.setdefault(("id", _key(r[i_rc])), []).append(row)
            continue
        if _col(h, "cut from") is not None and i_ch is not None:
            i_c = _col(h, "chapter") if _col(h, "chapter") is not None else i_ch
            i_id = _exact(h, *_ID_COLS)
            for r in t["rows"]:
                if len(r) <= max(i_c, i_at):
                    continue
                at = re.search(_T, r[i_at])
                i_to = _col(h, "cut to", "resume", "continue")
                to = re.search(_T, r[i_to]) if i_to is not None and i_to < len(r) else None
                if at:
                    a_t = seconds(at.group(0))
                    key = ("id", _key(r[i_id])) if i_id is not None and i_id < len(r) and r[i_id] else ("ch", _key(r[i_c]))
                    cuts.setdefault(key, []).append({"rc": r[i_id].strip("`* ") if key[0] == "id" else "",
                                          "at": a_t, "until": max(a_t, seconds(to.group(0))) if to else a_t,
                                          "optional": "optional" in " ".join(r).lower()})
        elif i_clip is not None and i_win is not None and _col(h, "chapter") is not None:
            i_c, i_who, i_words = _col(h, "chapter"), _col(h, "who"), _col(h, "words")
            i_id = _exact(h, *_ID_COLS)
            for r in t["rows"]:
                if len(r) <= max(i_c, i_clip, i_win):
                    continue
                span = re.findall(_T, r[i_win])
                sid = re.search(r"`([A-Z]{1,3}\d{1,3})`", r[i_clip]) or re.search(r"\b([A-Z]{1,3}\d{1,3})\b", r[i_clip])
                vid = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", r[i_clip])
                if len(span) >= 2:
                    key = ("id", _key(r[i_id])) if i_id is not None and i_id < len(r) and r[i_id] else ("ch", _key(r[i_c]))
                    clips.setdefault(key, []).append({
                        "source_id": sid.group(1) if sid else "", "video_id": vid.group(1) if vid else "",
                        "start": seconds(span[0]), "end": seconds(span[1]),
                        "who": re.sub(r"[*_`]", "", r[i_who]) if i_who is not None and i_who < len(r) else "",
                        "words": re.sub(r"[*_`]", "", r[i_words]).strip('" “”') if i_words is not None and i_words < len(r) else "",
                        "approximate": bool(re.search(r"about|somewhere|approx|~", r[i_win], re.I)),
                    })
    out = [{"who": "", "words": "", "video_id": "", "optional": False, "approximate": False, "rc": "", "cutaways": [], **d} for d in direct]
    for key, group in cuts.items():
        for n, cut in enumerate(group):
            options = clips.get(key) or []
            clip = options[n] if n < len(options) else None
            if clip and clip["end"] > clip["start"]:
                out.append({**clip, **cut, "cutaways": cuts_away.get(key, []) if key[0] == "id" else []})
    out.sort(key=lambda x: x["at"])
    return out


def _probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    import json

    try:
        j = json.loads(r.stdout)
    except ValueError:
        raise RecutError("That file could not be read as a video.")
    streams = j.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    return {
        "duration": float(j.get("format", {}).get("duration") or 0),
        "has_video": bool(video), "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": int(video["width"]) if video else 0, "height": int(video["height"]) if video else 0,
    }


def check(base_path, inserts):
    """Problems that would stop the re-cut, as plain sentences."""
    base = _probe(base_path)
    problems = []
    if not base["has_video"] or not base["has_audio"]:
        problems.append("The video to re-cut needs both picture and sound.")
    last, prev_at = -1.0, -1.0
    for n, ins in enumerate(sorted(inserts, key=lambda x: x["at"]), 1):
        until = ins.get("until", ins["at"])
        if not ins.get("path"):
            problems.append(f"Insert {n}: no file for this clip in the project yet.")
            continue
        clip = _probe(ins["path"])
        if not clip["has_audio"]:
            problems.append(f"Insert {n}: the clip has no sound.")
        if not clip["has_video"]:
            problems.append(f"Insert {n}: the clip has no picture.")
        if ins["end"] <= ins["start"]:
            problems.append(f"Insert {n}: the clip's end must be after its start.")
        elif ins["end"] - ins["start"] > 90:
            problems.append(f"Insert {n}: the clip is longer than 90 seconds.")
        if clip["duration"] and ins["end"] > clip["duration"] + 0.2:
            problems.append(f"Insert {n}: the clip file is only {clock(clip['duration'])} long, but the insert ends at {clock(ins['end'])}.")
        if not 0 <= ins["at"] <= base["duration"]:
            problems.append(f"Insert {n}: {clock(ins['at'])} is outside the video ({clock(base['duration'])} long).")
        if until < ins["at"]:
            problems.append(f"Insert {n}: the video must continue at or after the moment it stops.")
        elif until > base["duration"] + 0.05:
            problems.append(f"Insert {n}: the video cannot continue from {clock(until)}; it is only {clock(base['duration'])} long.")
        elif until - ins["at"] > 120:
            problems.append(f"Insert {n}: more than two minutes of the video would be skipped. Check the two times.")
        if n > 1 and ins["at"] < last - 1e-6:
            problems.append(f"Insert {n}: it starts inside the part the insert before it skips.")
        elif n > 1 and abs(ins["at"] - prev_at) < 1e-6:
            problems.append(f"Insert {n}: two inserts sit at the same moment.")
        last, prev_at = max(until, ins["at"]), ins["at"]
    return problems, base


# --------------------------------------------------------------------------
# Picture check (v0.4.39): after every re-cut, look at the finished file at
# each insert and compare it with the clip it must show. A wrong picture is
# never handed over silently.
# --------------------------------------------------------------------------

_PW, _PH = 64, 36


def _thumbs(path, t, w, h, count=1):
    """Grey 64x36 thumbnails of the centre of the picture, `count` frames from t."""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"crop=iw*0.6:ih*0.6:iw*0.2:ih*0.15,scale={_PW}:{_PH},format=gray")
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", str(count), "-vf", vf,
                        "-f", "rawvideo", "-"], capture_output=True)
    n = _PW * _PH
    return [r.stdout[i:i + n] for i in range(0, len(r.stdout) - n + 1, n)]


def _diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def picture_check(out_path, base_path, placed, w, h, proof_dir=None):
    """placed: [(insert, start in the finished video, length)]. Returns
    [{n, ok, diff, base_diff, at, proof}] and never raises."""
    results = []
    for n, (ins, pos, length) in enumerate(placed, 1):
        busy = [(c["from"] - 0.2, c["to"] + 0.2) for c in ins.get("cutaways") or []]
        card_end = 5.5 if ins.get("lower_third") else 0.0
        spots = [x for x in (length * 0.5, length * 0.25, length * 0.75, length - 0.6, 0.6)
                 if 0.3 < x < length - 0.3 and not any(a <= x <= b for a, b in busy)]
        spots = sorted(spots, key=lambda x: (x < card_end, abs(x - length / 2)))[:2]
        if not spots:
            results.append({"n": n, "ok": True, "diff": None, "base_diff": None, "at": pos, "skipped": "cutaways cover the clip"})
            continue
        worst, worst_base, proof_at, looked = 0.0, None, spots[0], 0
        for x in spots:
            got = _thumbs(out_path, pos + x, w, h)
            want = _thumbs(ins["path"], ins["start"] + x - 1.0 / FPS, w, h, count=3)
            if not got or not want:
                continue
            looked += 1
            d = min(_diff(got[0], f) for f in want)
            if d > worst:
                worst, proof_at = d, x
            # How far the picture is from the narration video at the same spot (the wrong picture).
            nar = _thumbs(base_path, ins["at"], w, h)
            if nar:
                bd = _diff(got[0], nar[0])
                worst_base = bd if worst_base is None else min(worst_base, bd)
        proof = None
        if proof_dir is not None:
            proof = Path(proof_dir) / f"insert{n:02d}.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{pos + proof_at:.3f}", "-i", str(out_path), "-frames:v", "1",
                            "-vf", "scale=320:-2", str(proof)], capture_output=True)
            proof = proof.name if proof.exists() else None
        results.append({"n": n, "ok": looked > 0 and worst <= 22.0, "diff": round(worst, 1) if looked else None, "base_diff": None if worst_base is None else round(worst_base, 1),
                        "at": round(pos, 2), "proof": proof})
    return results


def _src_fps(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip().split(",")
    for v in r:
        try:
            a, b = (v.split("/") + ["1"])[:2]
            f = float(a) / float(b)
            if 5 <= f <= 121:
                return round(f, 4)
        except (ValueError, ZeroDivisionError):
            pass
    return 30.0


def _clip_command(ins, exact, frames, w, h, vfmt, afmt, venc, aenc, work, k, logo, attempt, pic, snd):
    """One inserted clip: its own picture (plus cutaways, logo and name card) and its own sound.

    attempt "timestamps" (used) trusts the file's frame times; "frame-count"
    lays the frames out at the file's frame rate instead."""
    fade = min(0.08, exact / 4)
    card = ""
    cuts = [c for c in ins.get("cutaways") or [] if c["from"] < exact - 0.05]
    if ins.get("lower_third"):
        # v0.4.30: a name card on the clip; v0.4.38: cut short by the first cutaway.
        style, events = effects.lower_third_ass(ins["lower_third"], min(exact, cuts[0]["from"]) if cuts else exact, w, h)
        if style:
            ass = work / f"card{k}.ass"
            ass.write_text(captionstyle.ass([], w, h, None, [style], events), encoding="utf-8")
            card = "," + captionstyle.filter_arg(ass.as_posix())
    timing = "setpts=PTS-STARTPTS" if attempt == "timestamps" else f"setpts=N/({_src_fps(ins['path'])}*TB)"
    inputs, graph, last = [], [f"[0:v]{timing},{vfmt}[v0]"], "v0"
    for j, c in enumerate(cuts, 1):
        a, b = c["from"], min(c["to"], exact)
        d = b - a
        if c["kind"] == "image":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d + 0.2:.3f}", "-i", str(c["path"])]
            zw, zh = round(w * 1.08 / 2) * 2, round(h * 1.08 / 2) * 2
            pic_f = (f"scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={zw}:{zh},"
                     f"crop={w}:{h}:x='({zw}-{w})/2*min(1,t/{d:.3f})':y='({zh}-{h})/2*min(1,t/{d:.3f})',fps={FPS}")
        else:
            inputs += ["-ss", f"{c['start']:.3f}", "-t", f"{d + 0.2:.3f}", "-i", str(c["path"])]
            pic_f = f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        graph.append(f"[{j}:v]{pic_f},setsar=1,format=yuv420p,setpts=PTS-STARTPTS+{a:.3f}/TB[c{j}]")
        graph.append(f"[{last}][c{j}]overlay=0:0:enable='between(t,{a:.3f},{b - 0.001:.3f})':eof_action=pass[v{j}]")
        last = f"v{j}"
    if logo:
        lp = work / "logo.png"
        if not lp.exists():
            logo(w, h, lp)
        inputs += ["-i", str(lp)]
        graph.append(f"[{last}][{len(cuts) + 1}:v]overlay=0:0:format=auto[vl]")
        last = "vl"
    graph.append(f"[{last}]null{card}[vout]")
    graph.append(f"[0:a]asetpts=PTS-STARTPTS,{afmt},loudnorm=I=-16:TP=-1.5:LRA=11,{afmt},afade=t=in:d={fade:.3f},"
                 f"afade=t=out:st={max(0, exact - fade):.3f}:d={fade:.3f},apad,atrim=duration={exact:.6f}[aout]")
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{ins['start']:.3f}", "-i", str(ins["path"]), *inputs,
            "-filter_complex", ";".join(graph), "-map", "[vout]", "-frames:v", str(frames), *venc, str(pic),
            "-map", "[aout]", *aenc, str(snd)]


def render(base_path, inserts, out_path, progress=lambda *a: None, cancelled=lambda: False, logo=None, proof_dir=None, check_picture=True, checks=None):
    """Write the re-cut to out_path. Returns the new duration.

    v0.4.31: each piece (a stretch of the video, or an inserted clip) is made
    on its own and the pieces are joined at the end. One filter graph that
    split the whole video held decoded frames for every later piece in
    memory, which ran a 16-minute 1080p video with 13 inserts out of memory.
    Pieces keep memory small and constant, whatever the length."""
    inserts = sorted(inserts, key=lambda x: x["at"])
    if not inserts:
        raise RecutError("Add at least one insert.")
    problems, base = check(base_path, inserts)
    if problems:
        raise RecutError(" ".join(problems[:3]))
    w, h = base["width"] - base["width"] % 2, base["height"] - base["height"] % 2
    afmt = "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo"
    vfmt = f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,format=yuv420p"
    snap = lambda t: round(t * FPS) / FPS  # cut on a frame, picture and sound together
    # Pieces of the original video that are kept: (start, end or None for "to the end").
    kept, cursor = [], 0.0
    for ins in inserts:
        kept.append((cursor, snap(ins["at"])))
        cursor = snap(max(ins.get("until", ins["at"]), ins["at"]))
    kept.append((cursor, None))
    # The plan, in playing order: ("base", k, start, length) and ("clip", k, ins, length).
    plan = []
    for k, (a, b) in enumerate(kept):
        length = (base["duration"] - a) if b is None else (b - a)
        if length > 1.0 / FPS:
            plan.append(("base", k, a, length, b is not None))
        if k < len(inserts):
            ins = inserts[k]
            plan.append(("clip", k, ins, snap(ins["end"] - ins["start"]), True))
    total = sum(p[3] for p in plan) or 1.0
    out_path = Path(out_path)
    work = out_path.with_name(out_path.stem + ".pieces")
    work.mkdir(parents=True, exist_ok=True)
    # v0.4.40: built the way the main export is built, which plays everywhere:
    # picture pieces are video-only MP4s with an exact frame count (one encoder
    # setting for all of them), the sound is one continuous track made from WAV
    # pieces of exactly the same lengths, and the two are joined at the end.
    # v0.4.41: every piece is encoded identically, so the joined video is one uniform
    # H.264 stream: 4:2:0 High profile (Apple's players cannot decode 4:4:4, which a
    # logo overlay produced before and froze every clip in Safari/DuckDuckGo), the same
    # colour tags and the same keyframe spacing whatever the source file was.
    venc = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-x264-params", f"keyint={FPS * 2}:min-keyint={FPS}:scenecut=0", "-r", str(FPS),
            "-video_track_timescale", "12288", "-movflags", "+faststart"]
    aenc = ["-vn", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
    done = 0.0

    def run(cmd, length, label):
        nonlocal done
        import threading
        import time as _time
        proc = subprocess.Popen(cmd + ["-progress", "pipe:1", "-nostats"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # v0.4.41 watchdog: a step that makes no progress for 3 minutes is stopped with a clear message.
        state = {"last": _time.monotonic(), "stalled": False, "over": False}

        def watch():
            while not state["over"]:
                if _time.monotonic() - state["last"] > STALL_SECONDS:
                    state["stalled"] = True
                    proc.kill()
                    return
                _time.sleep(1)
        threading.Thread(target=watch, daemon=True).start()
        try:
            for line in proc.stdout:
                state["last"] = _time.monotonic()
                if cancelled():
                    proc.kill()
                    proc.wait()
                    raise RecutError("Cancelled.")
                m = re.match(r"out_time_ms=(\d+)", line)
                if m:
                    at = min(length, int(m.group(1)) / 1e6)
                    progress(min(96, int(96 * (done + at) / total)), label)
            err = proc.stderr.read()
            code = proc.wait()
        finally:
            state["over"] = True
        if state["stalled"]:
            raise RecutError(f"The re-cut stopped making progress ({label}) and was halted after {STALL_SECONDS // 60} minutes. "
                             "Nothing was saved. Please send this message to support.")
        if code:
            if code < 0 or code in (137, 247):
                raise RecutError("The re-cut was stopped by the system, usually for lack of memory. Close other apps or give Docker more memory, then try again.")
            raise RecutError("The re-cut failed: " + ((err or "").strip()[-300:] or f"ffmpeg stopped with code {code}."))
        done += length

    try:
        pictures, sounds = [], []
        for n, (kind, k, src, length, has_end) in enumerate(plan):
            frames = max(1, round(length * FPS))
            exact = frames / FPS  # picture and sound of every piece end on the same frame
            pic, snd = work / f"{n:03d}.mp4", work / f"{n:03d}.wav"
            if kind == "base":
                a = src
                fades = ",afade=t=in:d=0.03" if a > 0 else ""  # a short fade at each cut avoids a click
                if has_end:
                    fades += f",afade=t=out:st={max(0, exact - 0.03):.3f}:d=0.03"
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-i", str(base_path),
                       "-filter_complex", f"[0:v]setpts=PTS-STARTPTS,{vfmt}[vout];[0:a]asetpts=PTS-STARTPTS,{afmt}{fades},apad,atrim=duration={exact:.6f}[aout]",
                       "-map", "[vout]", "-frames:v", str(frames), *venc, str(pic),
                       "-map", "[aout]", *aenc, str(snd)]
                run(cmd, length, f"Re-cutting the video · part {n + 1} of {len(plan)}")
            else:
                ins = src
                label = f"Adding clip {k + 1} of {len(inserts)} · part {n + 1} of {len(plan)}"
                run(_clip_command(ins, exact, frames, w, h, vfmt, afmt, venc, aenc, work, k, logo, "timestamps", pic, snd), length, label)
            # Every piece must be plain 4:2:0 H.264 High, or Apple's players freeze on it.
            fmt = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,profile,pix_fmt,width,height",
                                  "-of", "csv=p=0", str(pic)], capture_output=True, text=True).stdout.strip()
            if fmt != f"h264,High,{w},{h},yuv420p":
                raise RecutError(f"Part {n + 1} of the re-cut came out as {fmt or 'unreadable'} instead of standard H.264 4:2:0, "
                                 "which Safari and other Apple players cannot play. Nothing was saved. Please send this message to support.")
            pictures.append(pic)
            sounds.append(snd)
        progress(97, "Joining the parts")
        vlist, alist = work / "pictures.txt", work / "sounds.txt"
        vlist.write_text("".join(f"file '{p.name}'\n" for p in pictures), encoding="utf-8")
        alist.write_text("".join(f"file '{p.name}'\n" for p in sounds), encoding="utf-8")
        picture, sound = work / "picture.mp4", work / "sound.wav"
        for cmd in (["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(vlist), "-c", "copy", str(picture)],
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(alist), "-c", "copy", str(sound)],
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(picture), "-i", str(sound), "-map", "0:v:0", "-map", "1:a:0",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path)]):
            join = subprocess.run(cmd, capture_output=True, text=True)
            if join.returncode:
                raise RecutError("The re-cut failed while joining: " + (join.stderr or "").strip()[-300:])
        if not out_path.exists():
            raise RecutError("The re-cut failed while joining.")
        # Sound and picture must end together: a short picture track shifts every later shot.
        streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", str(out_path)],
                                 capture_output=True, text=True).stdout.split()
        lens = {x.split(",")[0]: float(x.split(",")[1]) for x in streams if x.count(",") == 1 and x.split(",")[1] not in ("", "N/A")}
        if "video" in lens and "audio" in lens and abs(lens["video"] - lens["audio"]) > 0.5:
            raise RecutError(f"The re-cut's picture ({clock(lens['video'])}) and sound ({clock(lens['audio'])}) came out different lengths, "
                             "so clips would show the wrong picture. Nothing was saved. Please send this message to support.")
        if check_picture:
            progress(99, "Checking each clip's picture")
            placed, pos = [], 0.0
            for kind, k, src, length, _ in plan:
                if kind == "clip":
                    placed.append((src, pos, length))
                pos += length
            looked = picture_check(out_path, base_path, placed, w, h, proof_dir)
            bad = [c for c in looked if not c["ok"]]
            if bad:
                names = ", ".join(f"clip {c['n']} (at {clock(c['at'])})" for c in bad[:4])
                raise RecutError(f"Picture check failed: {names} did not show the clip's own picture in the finished video (or could not be read). "
                                 "Nothing was saved. Please send this message to support.")
            if checks is not None:
                checks.extend(looked)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return _probe(out_path)["duration"]


# --------------------------------------------------------------------------
# Fetch the clips the list needs (v0.4.23)
# --------------------------------------------------------------------------

PAD_END = 10.0  # seconds kept after the last clip a source needs


def fetch_items(inserts, have, links):
    """What the Re-cut page can download itself.

    inserts: parse() output; have: source IDs that already have a file;
    links: source ID -> YouTube video ID from the guide, used when the list
    row has no link of its own. Returns fetcher-style items, one per source:
    status "have", "todo" (has a YouTube link) or "manual" (no link)."""
    by_sid = {}
    for ins in inserts:
        sid = ins.get("source_id")
        if not sid:
            continue
        item = by_sid.setdefault(sid, {
            "kind": "source", "id": sid, "save_as": f"{sid}.mp4", "title": ins.get("who") or "",
            "video_id": ins.get("video_id") or links.get(sid) or "", "end": 0.0, "used": True,
        })
        item["video_id"] = item["video_id"] or ins.get("video_id") or ""
        item["end"] = max(item["end"], float(ins.get("end") or 0))
    out = []
    for sid, item in sorted(by_sid.items()):
        vid = item.pop("video_id")
        end = item.pop("end")
        item.update(video_id=vid or None, url=f"https://www.youtube.com/watch?v={vid}" if vid else None,
                    need=end + PAD_END)
        if sid in have:
            item.update(status="have", note=f"{sid} is in the project.")
        elif not vid:
            item.update(status="manual", note=f"No YouTube link for {sid} in the list or the guide. Upload it named {sid}.mp4.")
        else:
            item.update(status="todo", note=f"Downloads 0:00 to {clock(end + PAD_END, 0)} of the video, so the clip times line up.")
        out.append(item)
    return out

"""Footage discovery (v0.4.20): find YouTube uploads about a case, for free.

Uses yt-dlp's own YouTube search (no API key, no paid service). A search result
is only a CANDIDATE. Nothing here decides that a video is genuine case footage,
and nothing is downloaded: the producer opens each video, then approves or
rejects it and says what kind it is. Approved uploads get a Source ID and can be
pasted to the script chat for the ledger's "Footage on YouTube?" column.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import os

KINDS = ("", "event footage", "news report", "press conference", "court", "family interview", "vigil or memorial", "commentary")
ANGLES = ("", "police", "press conference", "family", "court", "arrest", "vigil", "news report", "sentencing", "interview")


def binary():
    return os.environ.get("CASEFILE_YTDLP") or shutil.which("yt-dlp")


def suggest(case_name, victims=(), suspects=()):
    """Search phrases built from the case: the people's names with each angle."""
    names = [n for n in list(victims) + list(suspects) if n and len(n) > 3]
    place = ""
    parts = [p.strip() for p in (case_name or "").split(",")]
    if len(parts) > 1:
        place = re.sub(r"\b(19|20)\d\d\b.*", "", parts[1]).strip()
    base = names[:2] or ([parts[0]] if parts and parts[0] else [])
    out = []
    for b in base:
        for angle in ANGLES:
            out.append(" ".join(x for x in (b, angle) if x))
    if base and place:
        out.append(f"{base[0]} {place}")
    return list(dict.fromkeys(out))[:24]


def search(query, limit=15, timeout=120, run=subprocess.run):
    """One YouTube search. Returns [{id, title, channel, duration, views}]."""
    exe = binary()
    if not exe:
        raise RuntimeError("yt-dlp is not installed in this container. Rebuild the Docker image.")
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:120]
    if not query:
        return []
    limit = max(1, min(40, int(limit)))
    r = run([exe, "--flat-playlist", "--dump-single-json", "--no-warnings", "--no-progress", f"ytsearch{limit}:{query}"],
            capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("YouTube search failed: " + ((r.stderr or "").strip().splitlines() or ["unknown error"])[-1][:300])
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        raise RuntimeError("YouTube search returned something unreadable.")
    out = []
    for e in data.get("entries") or []:
        vid = e.get("id")
        if not vid or not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            continue
        out.append({
            "id": vid, "title": (e.get("title") or "")[:200],
            "channel": (e.get("channel") or e.get("uploader") or "")[:120],
            "duration": int(e.get("duration") or 0), "views": int(e.get("view_count") or 0),
        })
    return out


def details(vid, timeout=120, run=subprocess.run):
    """Upload date, description and channel of one video (no download)."""
    exe = binary()
    if not exe:
        raise RuntimeError("yt-dlp is not installed in this container.")
    r = run([exe, "--skip-download", "--dump-single-json", "--no-warnings", "--no-playlist", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("Could not read the video page: " + ((r.stderr or "").strip().splitlines() or ["unknown error"])[-1][:300])
    j = json.loads(r.stdout)
    return {
        "title": (j.get("title") or "")[:200], "channel": (j.get("channel") or j.get("uploader") or "")[:120],
        "upload_date": j.get("upload_date") or "", "duration": int(j.get("duration") or 0),
        "views": int(j.get("view_count") or 0), "description": (j.get("description") or "")[:1500],
        "channel_followers": j.get("channel_follower_count"),
    }


def relevance(title, terms):
    low = (title or "").lower()
    return sum(1 for t in terms if t and t.lower() in low)


def merge(candidates, found, query, terms):
    """Add new search results to the candidate list; never touch decisions."""
    by_id = {c["id"]: c for c in candidates}
    added = 0
    for f in found:
        c = by_id.get(f["id"])
        if c:
            if query not in c.setdefault("queries", []):
                c["queries"].append(query)
            c["views"] = f["views"] or c.get("views", 0)
            continue
        c = {**f, "status": "candidate", "kind": "", "note": "", "source_id": "", "upload_date": "",
             "queries": [query], "score": relevance(f["title"], terms)}
        candidates.append(c)
        by_id[c["id"]] = c
        added += 1
    return added


def decide(candidates, vid, status=None, kind=None, note=None):
    c = next((x for x in candidates if x["id"] == vid), None)
    if not c:
        raise ValueError("That video is not in the candidate list.")
    if kind is not None:
        if kind not in KINDS:
            raise ValueError("Unknown kind.")
        c["kind"] = kind
    if note is not None:
        c["note"] = str(note)[:300]
    if status is not None:
        if status not in ("candidate", "approved", "rejected"):
            raise ValueError("Unknown status.")
        c["status"] = status
        if status == "approved" and not c.get("source_id"):
            used = {int(m.group(1)) for x in candidates for m in [re.fullmatch(r"S(\d+)", x.get("source_id") or "")] if m}
            c["source_id"] = f"S{(max(used) + 1 if used else 1):02d}"
    return c

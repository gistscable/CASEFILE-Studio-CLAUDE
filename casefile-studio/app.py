from __future__ import annotations
import asyncio, base64, copy, hmac, json, os, re, shutil, subprocess, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
import ai, renderer, editorial, production, episode, fetcher, casedesk, discovery, voicegen, autotiming, recut, colabvoice, captionstyle, effects, cta, watermark, cutaways, basefill, picture, stickers, history
import motion as motiongfx
import sfxlib
import sound as sfxplan
import music as musiclib
from storage import (
    ROOT,
    DATA,
    asset_reference,
    resolve_asset,
    LOCK,
    now,
    uid,
    atomic_json,
    get_project,
    save_project,
    projects,
    new_project,
    build_scenes,
    checkpoint,
    add_message,
    seed,
)

seed()
app = FastAPI(title="Casefile Studio", version="0.4.66", docs_url="/api/docs")


@app.middleware("http")
async def optional_basic_auth(request: Request, call_next):
    """Password gate for public hosting.

    Inactive unless both BASIC_AUTH_USER and BASIC_AUTH_PASSWORD are set in
    the environment (e.g. on Render). Protects every route, including the
    static frontend and media files.
    """
    user = os.environ.get("BASIC_AUTH_USER", "")
    password = os.environ.get("BASIC_AUTH_PASSWORD", "")
    if user and password:
        expected = "Basic " + base64.b64encode(
            f"{user}:{password}".encode("utf-8")
        ).decode("ascii")
        provided = request.headers.get("authorization", "")
        if not hmac.compare_digest(
            provided.encode("utf-8"), expected.encode("ascii")
        ):
            return JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Casefile Studio"'},
            )
    return await call_next(request)


POOL = ThreadPoolExecutor(max_workers=4)
RENDER_LOCK = threading.Semaphore(1)
SESSIONS = {}
JOBS = {}
for path in (DATA / "jobs").glob("*.json"):
    try:
        j = json.loads(path.read_text())
        if j["status"] in ("queued", "running"):
            j.update(
                status="interrupted",
                message="Server restarted. Please run this operation again.",
            )
            atomic_json(path, j)
        JOBS[j["id"]] = j
    except (ValueError, KeyError):
        pass


@app.middleware("http")
async def session(request: Request, call_next):
    # An opaque browser-session header also works inside cross-site live-preview
    # iframes where third-party cookies are blocked. It never contains the API key.
    sid = request.headers.get("x-casefile-session") or request.cookies.get(
        "casefile_session"
    )
    fresh = not sid or not re.fullmatch(r"[a-f0-9]{32}", sid)
    if fresh:
        sid = uuid.uuid4().hex
    request.state.session = sid
    if (
        request.method in ("POST", "PATCH", "DELETE")
        and re.match(r"^/api/projects/[a-f0-9]{16}(?:/|$)", request.url.path)
        and not request.url.path.endswith("/production-plan")
    ):
        project_id = request.url.path.split("/")[3]
        if any(
            j["project_id"] == project_id
            and j["status"] in ("queued", "running")
            and j["kind"] != "render"
            for j in list(JOBS.values())
        ):
            return JSONResponse(
                {
                    "detail": "This project is read-only while its current AI/production operation runs. Wait for it to finish or cancel it."
                },
                status_code=409,
            )
    response = await call_next(request)
    if fresh and request.url.path.startswith("/api"):
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(
            "casefile_session",
            sid,
            httponly=True,
            samesite="strict",
            secure=secure,
            max_age=86400,
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def project_or_404(id):
    try:
        return get_project(id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found.")


def config(request):
    cfg = SESSIONS.get(request.state.session)
    if not cfg or not cfg.get("key"):
        raise HTTPException(
            412,
            "Connect an AI API key in Settings first. Local editing and video rendering do not need one.",
        )
    return copy.deepcopy(cfg)


def public_config(request):
    cfg = SESSIONS.get(request.state.session, {})
    return {
        "connected": bool(cfg.get("key")),
        "model": cfg.get("model", "gpt-4.1"),
        "research_model": cfg.get("research_model", "gpt-4.1"),
        "speech_model": cfg.get("speech_model", "gpt-4o-mini-tts"),
        "voice": cfg.get("voice", "onyx"),
    }


def job_update(id, **fields):
    with LOCK:
        JOBS[id].update(fields, updated_at=now())
        atomic_json(DATA / "jobs" / f"{id}.json", JOBS[id])


def spawn(project_id, kind, work):
    with LOCK:
        if any(
            j["project_id"] == project_id and j["status"] in ("running", "queued")
            for j in JOBS.values()
        ):
            raise HTTPException(
                409,
                "An operation is already running for this project. Wait for it to finish or cancel it.",
            )
        id = uid()
        JOBS[id] = {
            "id": id,
            "project_id": project_id,
            "kind": kind,
            "status": "queued",
            "progress": 0,
            "message": "Queued",
            "cancel_requested": False,
            "created_at": now(),
            "updated_at": now(),
        }
        job_update(id)

    def run():
        try:
            job_update(id, status="running", message="Starting")
            def progress(percent, message, **extra):
                job_update(id, progress=percent, message=message, **extra)
            cancelled = lambda: JOBS[id].get("cancel_requested", False)
            result = work(progress, cancelled)
            if cancelled():
                job_update(
                    id,
                    status="cancelled",
                    message="Cancelled. Completed AI requests may still incur charges.",
                )
            else:
                job_update(
                    id,
                    status="done",
                    progress=100,
                    message="Complete",
                    result=result or {},
                )
        except Exception as e:
            message = str(e)
            job_update(
                id,
                status="cancelled" if JOBS[id].get("cancel_requested") else "error",
                message=message[:1600],
            )

    POOL.submit(run)
    return {"job_id": id}


def sanitize_scene(scene, asset_ids):
    out = {
        "id": scene.get("id")
        if re.fullmatch(r"[a-f0-9]{16}", str(scene.get("id", "")))
        else uid()
    }
    out.update(
        {
            k: str(scene.get(k, ""))[: (12000 if k == "narration" else 180)]
            for k in ["title", "chapter", "narration"]
        }
    )
    try:
        minimum = 1 / renderer.FPS if "guide_gap" in scene else 0.5
        out["duration"] = round(
            min(600, max(minimum, float(scene.get("duration", 5)))), 3
        )
        out["trim_start"] = max(0, min(21600, float(scene.get("trim_start", 0))))
        out["audio_start"] = max(0, min(21600, float(scene.get("audio_start", 0))))
        out["audio_duration"] = max(
            0.04, min(600, float(scene.get("audio_duration", out["duration"])))
        )
    except (ValueError, TypeError):
        raise HTTPException(422, "Scene timing must be a number.")
    if not isinstance(scene.get("source_ids", []), list):
        raise HTTPException(
            422, "Scene source references must be a list of S1-style IDs."
        )
    out["source_ids"] = list(
        dict.fromkeys(
            [
                str(ref).upper()
                for ref in scene.get("source_ids", [])
                if re.fullmatch(r"S\d+", str(ref), re.I)
            ]
            + editorial.source_ids(out["narration"])
        )
    )[:40]
    out["narration"] = editorial.strip_references(out["narration"])
    out["asset_id"] = (
        scene.get("asset_id") if scene.get("asset_id") in asset_ids else None
    )
    out["motion"] = (
        scene.get("motion")
        if scene.get("motion")
        in effects.MOTIONS
        else "slow-zoom"
    )
    out["transition"] = (
        scene.get("transition")
        if scene.get("transition") in list(effects.TRANSITIONS) + list(effects.LEGACY)
        else "none"
    )
    out["transition_duration"] = max(
        0.0, min(600.0, float(scene.get("transition_duration", 0) or 0))
    )
    out["show_title"] = bool(scene.get("show_title", True))
    # v0.4.49: how the picture fills the frame, and your own camera keyframes.
    if scene.get("fit") in picture.FITS:
        out["fit"] = scene["fit"]
    keys = picture.normalise_keyframes(scene.get("keyframes"), out["duration"])
    if keys:
        out["keyframes"] = keys
    if scene.get("cta") is True:
        out["cta"] = True
    if scene.get("replaced") is True:
        out["replaced"] = True
    lower = effects.normalise_lower_third(scene.get("lower_third"))
    if lower:
        out["lower_third"] = lower
    out["timing"] = scene.get("timing", "estimated")[:30]
    for field in ("guide_cue_id", "guide_source_id", "source_label"):
        if field in scene:
            out[field] = str(scene[field] or "")[:240]
    if "guide_gap" in scene:
        out["guide_gap"] = bool(scene["guide_gap"])
    for field in ("inspection_only", "guide_unreviewed", "guide_alternative"):
        if field in scene:
            out[field] = scene[field] is True
    if scene.get("insert_audio") is True:
        out["insert_audio"] = True
    if isinstance(scene.get("base_fill"), dict):
        fill = scene["base_fill"]
        out["base_fill"] = {
            "bucket": str(fill.get("bucket", ""))[:1],
            "tags": [str(t)[:40] for t in (fill.get("tags") or [])][:12],
            "asset_name": str(fill.get("asset_name", ""))[:240],
            "tier": str(fill.get("tier", ""))[:40],
            "hint": str(fill.get("hint", ""))[:120],
            "reason": str(fill.get("reason", ""))[:30],
            "notes": [str(n)[:160] for n in (fill.get("notes") or [])][:6],
        }
    if "guide_primary_source_id" in scene:
        out["guide_primary_source_id"] = str(scene["guide_primary_source_id"])[:30]
    if "source_window_basis" in scene:
        out["source_window_basis"] = str(scene["source_window_basis"])[:240]
    if "source_crop_end" in scene:
        try:
            out["source_crop_end"] = max(0.0, float(scene["source_crop_end"]))
        except (ValueError, TypeError):
            out["source_crop_end"] = None
    out["captions_exact"] = scene.get("captions_exact") is True
    out["captions"] = []
    for c in scene.get("captions", [])[:500]:
        try:
            out["captions"].append(
                {
                    "start": max(0, float(c["start"])),
                    "end": max(0, float(c["end"])),
                    "text": str(c["text"])[:2000],
                }
            )
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, "Invalid caption timing.")
    return out


@app.get("/healthz")
def healthz():
    """Cheap liveness probe for hosting platforms; never touches media."""
    return {"ok": True, "version": app.version, "render": bool(shutil.which("ffmpeg"))}


@app.get("/api/bootstrap")
def bootstrap(request: Request):
    return {
        "projects": projects(),
        "config": public_config(request),
        "capabilities": {
            "render": bool(shutil.which("ffmpeg")),
            "ai_requires_key": True,
            "single_workspace": True,
        },
    }


@app.get("/api/config")
def get_config(request: Request):
    return public_config(request)


@app.post("/api/config")
async def set_config(request: Request):
    data = await request.json()
    old = SESSIONS.get(request.state.session, {})
    key = str(data.get("key") or old.get("key", "")).strip()
    if not key:
        raise HTTPException(
            422, "Enter an API key in the private connection field, not in chat."
        )
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            result = await client.get(
                ai.BASE + "/models", headers={"Authorization": "Bearer " + key}
            )
        if result.status_code != 200:
            raise HTTPException(
                400,
                "The key could not be verified. Check the API key, account permissions, and provider billing.",
            )
    except httpx.HTTPError:
        raise HTTPException(
            502, "The AI provider could not be reached. Try again later."
        )
    cfg = {"key": key}
    for field, default in [
        ("model", "gpt-4.1"),
        ("research_model", "gpt-4.1"),
        ("speech_model", "gpt-4o-mini-tts"),
        ("voice", "onyx"),
    ]:
        val = str(data.get(field, old.get(field, default))).strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", val):
            raise HTTPException(422, "Invalid model or voice name.")
        cfg[field] = val
    SESSIONS[request.state.session] = cfg
    return public_config(request)


@app.delete("/api/config")
def disconnect(request: Request):
    SESSIONS.pop(request.state.session, None)
    return public_config(request)


class NewProject(BaseModel):
    title: str = Field(default="Untitled documentary", max_length=180)
    mode: Literal["topic", "script", "narration", "footage"] = "topic"
    target_minutes: int = Field(default=25, ge=20, le=40)


@app.post("/api/projects")
def create_project(data: NewProject):
    return new_project(data.title.strip(), data.mode, data.target_minutes)


@app.get("/api/projects/{id}")
def get_one(id: str):
    return project_or_404(id)


@app.get("/api/projects/{id}/media-status")
def media_status(id: str):
    p = project_or_404(id)
    result = []
    for asset in p.get("assets", []):
        try:
            exists = resolve_asset(asset.get("path")).is_file()
        except (OSError, ValueError):
            exists = False
        result.append(
            {key: asset.get(key) for key in ("id", "name", "size", "kind", "has_audio")}
            | {"exists": exists}
        )
    return {"assets": result}


@app.post("/api/projects/{id}/recover-empty")
async def recover_empty(id: str, request: Request):
    body = await request.json()
    if not re.fullmatch(r"[a-f0-9]{16}", id):
        raise HTTPException(422, "Invalid recovery project ID.")
    with LOCK:
        try:
            return get_project(id)
        except FileNotFoundError:
            pass
        mode = body.get("mode", "narration")
        if mode not in ("topic", "script", "narration", "footage"):
            mode = "narration"
        try:
            minutes = min(40, max(20, int(body.get("target_minutes", 25))))
        except (ValueError, TypeError):
            minutes = 25
        return new_project(
            str(body.get("title") or "Recovered working session")[:180],
            mode,
            minutes,
            project_id=id,
        )


@app.post("/api/projects/{id}/recovery-checkpoint")
def recovery_checkpoint(id: str):
    p = project_or_404(id)
    token = now().replace(":", "-").replace("+", "_")
    atomic_json(DATA / "recovery-backups" / f"{id}-{token}.json", p)
    return {"saved": True}


@app.post("/api/projects/{id}/reuse-timings")
async def reuse_timings(id: str, request: Request):
    body = await request.json()
    fingerprint = str(body.get("hash", ""))
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise HTTPException(422, "Invalid timing fingerprint.")
    with LOCK:
        p = project_or_404(id)
        for path in (DATA / "projects").glob("*.json"):
            try:
                candidate = (
                    json.loads(path.read_text()).get("episode", {}).get("timings", {})
                )
            except (OSError, ValueError, AttributeError):
                continue
            if candidate.get("hash") == fingerprint:
                checkpoint(p, "Reuse timings")
                e = copy.deepcopy(episode.state(p))
                e["timings"] = copy.deepcopy(candidate)
                e.pop("timing_reviewed_digest", None)
                e.pop("transcript_reviewed_digest", None)
                p["episode"] = e
                p["review"]["picture"] = False
                return episode_result(p)
    raise HTTPException(
        404, "The original timing export is needed; no word clock was guessed."
    )


@app.post("/api/browser-session")
async def browser_session(request: Request):
    raw = await request.body()
    if len(raw) > 16000000:
        raise HTTPException(413, "Session diagnostic too large.")
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(422, "Invalid session diagnostic.")
    if not isinstance(body, dict):
        raise HTTPException(422, "Invalid session diagnostic object.")
    source = body.get("snapshot")
    snapshot = None
    if isinstance(source, dict) and re.fullmatch(
        r"[a-f0-9]{16}", str(source.get("id", ""))
    ):
        keys = {
            "id",
            "title",
            "updated_at",
            "mode",
            "target_minutes",
            "script",
            "script_origin",
            "episode",
            "narration_id",
            "music_id",
            "music_volume",
            "music",
            "look",
            "captions",
            "review",
            "scenes",
            "sources",
            "assets",
            "exports",
        }
        snapshot = {key: source[key] for key in keys if key in source}
        snapshot["assets"] = [
            {
                key: item.get(key)
                for key in (
                    "id",
                    "name",
                    "size",
                    "kind",
                    "duration",
                    "video_duration",
                    "has_audio",
                    "license",
                    "url",
                    "available_on_server",
                )
            }
            for item in source.get("assets", [])
            if isinstance(item, dict)
        ]
    parsed = urlparse(str(body.get("origin", "")))
    origin = (
        f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme in ("http", "https") and parsed.netloc and not parsed.username
        else ""
    )
    record = {
        "observed_at": now(),
        "origin": origin,
        "frontend_version": str(body.get("version", ""))[:30],
        "backend_version": app.version,
        "snapshot": snapshot,
    }
    atomic_json(DATA / "browser-sessions" / f"{request.state.session}.json", record)
    if origin and not any(x in origin for x in ("127.0.0.1", "localhost")):
        print("Browser editor connected from " + origin, flush=True)
    return {"received": True, "backend_version": app.version}


@app.patch("/api/projects/{id}")
async def update_project(id: str, request: Request):
    changes = await request.json()
    with LOCK:
        p = project_or_404(id)
        allowed = {
            "title",
            "topic",
            "target_minutes",
            "script",
            "scenes",
            "look",
            "captions",
            "music_volume",
            "narration_volume",
            "narration_id",
            "music_id",
            "review",
            "caption_style",
            "effects",
            "aspect",
            "vertical_fit",
            "cta",
            "name_cards",
            "watermark",
            "stickers",
            "motion",
            "sound",
            "music",
        }
        if set(changes) - allowed:
            raise HTTPException(422, "Unsupported project field.")
        # v0.4.51: every edit can be undone (an edit that changes nothing makes no step).
        checkpoint(p)
        old_script = p["script"]
        old_story = [
            (x["id"], x["narration"], x.get("source_ids", [])) for x in p["scenes"]
        ]
        old_narration = {s["id"]: s["narration"] for s in p["scenes"]}
        for field in ["title", "topic", "script"]:
            if field in changes:
                p[field] = str(changes[field])[: 200000 if field == "script" else 180]
        if p["script"] != old_script:
            p["script_dirty"] = "scenes" not in changes
            p["review"]["facts"] = False
            p["script_approved_hash"] = None
        if "target_minutes" in changes:
            p["target_minutes"] = min(40, max(20, int(changes["target_minutes"])))
        if "scenes" in changes:
            if not isinstance(changes["scenes"], list) or len(changes["scenes"]) > 400:
                raise HTTPException(422, "A project can have up to 400 scenes.")
            before = p["scenes"]
            p["scenes"] = [
                sanitize_scene(s, {a["id"] for a in p["assets"]})
                for s in changes["scenes"]
            ]
            if p.get("episode") and p["episode"].get("guide"):
                # v0.4.33: the rebuild below regenerates guide scenes; keep the
                # producer's choices (transition, replaced picture, name card…).
                episode.record_overrides(p, before, p["scenes"])
            rewritten = any(
                s["id"] in old_narration and s["narration"] != old_narration[s["id"]]
                for s in p["scenes"]
            )
            if rewritten:
                p["review"]["facts"] = False
                if "narration_id" not in changes:
                    p["narration_id"] = None
            if old_story != [
                (x["id"], x["narration"], x.get("source_ids", [])) for x in p["scenes"]
            ]:
                p["script_approved_hash"] = None
                if not p.get("script_dirty") or "script" in changes:
                    p["script"] = editorial.script_from_scenes(p["scenes"])
                    p["script_dirty"] = False
            p["review"]["picture"] = False
        if "look" in changes:
            if changes["look"] not in effects.LOOKS:
                raise HTTPException(422, "Unknown visual look.")
            p["look"] = changes["look"]
        if "captions" in changes:
            p["captions"] = bool(changes["captions"])
        if "name_cards" in changes:
            p["name_cards"] = effects.normalise_name_cards(changes["name_cards"])
        if "cta" in changes:
            old = cta.normalise(p.get("cta"))
            new = cta.normalise(
                changes["cta"],
                {x["id"] for x in p["assets"] if x.get("kind") == "image"},
                {x["id"] for x in p["assets"] if x.get("kind") == "video"},
            )
            if new["asset_id"] and new["asset_id"] != old["asset_id"]:
                # A new banner: find its SUBSCRIBE button.
                banner = next(x for x in p["assets"] if x["id"] == new["asset_id"])
                try:
                    new["button"] = cta.detect_button(renderer.asset_path(banner))
                except (ValueError, OSError):
                    new["button"] = None
            p["cta"] = new
        if "stickers" in changes:
            p["stickers"] = stickers.normalise(changes["stickers"], {x["id"] for x in p["assets"] if x.get("kind") == "image"})
        if "motion" in changes:
            p["motion"] = motiongfx.normalise(changes["motion"], {x["id"] for x in p["assets"] if x.get("kind") == "image"})
        if "music" in changes:  # v0.4.58: where the music plays and how it loops (never the timeline)
            p["music"] = musiclib.normalise(changes["music"])
        if "sound" in changes:  # v0.4.56: one edited sound leaves the rest of the plan as it is
            p["sound"] = sfxplan.normalise(changes["sound"])
        if "watermark" in changes:
            p["watermark"] = watermark.normalise(changes["watermark"], {x["id"] for x in p["assets"] if x.get("kind") == "image"})
        if "aspect" in changes:
            if changes["aspect"] not in effects.FORMATS:
                raise HTTPException(422, "Choose 16:9 or 9:16.")
            p["aspect"] = changes["aspect"]
        if "vertical_fit" in changes:
            if changes["vertical_fit"] not in effects.FITS:
                raise HTTPException(422, "Choose blurred background or crop.")
            p["vertical_fit"] = changes["vertical_fit"]
        if "effects" in changes:
            p["effects"] = effects.normalise_effects(changes["effects"])
        if "caption_style" in changes:
            p["caption_style"] = captionstyle.normalise(changes["caption_style"])
        if "music_volume" in changes:
            p["music_volume"] = min(0.5, max(0, float(changes["music_volume"])))
        if "narration_volume" in changes:  # v0.4.57: 0..2 (100% = as recorded)
            p["narration_volume"] = renderer.narration_volume({"narration_volume": changes["narration_volume"]})
        for field in ["narration_id", "music_id"]:
            if field in changes:
                value = changes[field]
                if value is not None and not any(
                    a["id"] == value and a.get("has_audio", a["kind"] == "audio")
                    for a in p["assets"]
                ):
                    raise HTTPException(422, "Select an asset with an audio track.")
                if value != p.get(field):
                    p[field] = value
                    if field == "narration_id" and value:
                        cursor = 0
                        for s in p["scenes"]:
                            s.update(
                                audio_start=round(cursor, 3),
                                audio_duration=s["duration"],
                                timing="estimated",
                                captions=[],
                            )
                            cursor += s["duration"]
                    p["review"]["picture"] = False
        if "review" in changes:
            p["review"] = {
                k: bool(changes["review"].get(k, False))
                for k in ["facts", "rights", "disclosure", "picture"]
            }
        # Auto-rebuild the inspection timeline when scenes change on a
        # guide-driven project, so manual source assignments via the dropdown
        # are picked up without requiring a separate "Build" click.
        if "scenes" in changes and p.get("episode") and p["episode"].get("guide"):
            try:
                episode.build(p, allow_placeholders=True, inspection=True)
            except (ValueError, TypeError, KeyError):
                pass
        return save_project(p)


@app.post("/api/projects/{id}/undo")
def undo(id: str):
    """v0.4.51 Undo the last step (any edit); it can be redone."""
    with LOCK:
        p = project_or_404(id)
        name = history.undo(p)
        if name is None:
            save_project(p)
            raise HTTPException(400, "Nothing to undo yet. Your edits create history.")
        if not editorial.script_approved(p):
            p["script_approved_hash"] = None
        return save_project(p, follow=False)


@app.post("/api/projects/{id}/redo")
def redo(id: str):
    """v0.4.51 Redo the last undone step (until a new edit is made)."""
    with LOCK:
        p = project_or_404(id)
        name = history.redo(p)
        if name is None:
            save_project(p)
            raise HTTPException(400, "Nothing to redo.")
        if not editorial.script_approved(p):
            p["script_approved_hash"] = None
        return save_project(p, follow=False)


@app.post("/api/projects/{id}/assemble")
def assemble(id: str):
    with LOCK:
        p = project_or_404(id)
        if (p.get("episode") or {}).get("guide"):
            raise HTTPException(
                400,
                "Use Episode setup to rebuild this guide-driven timeline. Generic filename/rotation assignment is disabled.",
            )
        checkpoint(p, "Build timeline")
        try:
            # An amended script must not silently retain an out-of-date voice.
            if p["scenes"] and renderer.plain(p["script"]) != renderer.plain(
                "\n\n".join(s["narration"] for s in p["scenes"])
            ):
                p["narration_id"] = None
            scenes = build_scenes(p)
        except ValueError as e:
            raise HTTPException(400, str(e))
        p["scenes"] = scenes
        p["script_dirty"] = False
        p["review"]["picture"] = False
        add_message(
            p,
            "assistant",
            f"Assembled {len(scenes)} scenes from your script. Visuals use filename matching and rotation; review assignments and estimated caption timing before export.",
        )
        return save_project(p)


@app.post("/api/projects/{id}/upload")
async def upload(
    id: str,
    files: list[UploadFile] = File(...),
    episode_role: Literal["narration", "music", "sources", "sfx"] | None = Form(default=None),
):
    p = project_or_404(id)
    # v0.4.56: "sfx" = your own short sound effect for the sound design: added to the media only
    # (never rebuilds the timeline, never becomes narration or music)
    sfx_upload = episode_role == "sfx"
    if len(files) > 30:
        raise HTTPException(422, "Upload up to 30 files at a time.")
    folder = DATA / "media" / id
    folder.mkdir(parents=True, exist_ok=True)
    added = []
    script = None
    for file in files:
        suffix = Path(file.filename or "").suffix.lower()
        if episode_role and suffix in (".md", ".txt"):
            raise HTTPException(
                422,
                "This card accepts media only. Import script and guide documents in their separate cards.",
            )
        if suffix in (".md", ".txt") and p.get("episode"):
            raise HTTPException(
                422,
                "Use Episode setup's separate Script and Editing guide inputs; documents must not silently replace each other.",
            )
        allowed = {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".mp4",
            ".mov",
            ".webm",
            ".gif",
            ".mkv",
            ".mp3",
            ".wav",
            ".m4a",
            ".aac",
            ".ogg",
            ".flac",
            ".txt",
            ".md",
        }
        if suffix not in allowed:
            raise HTTPException(
                422,
                f"{file.filename}: unsupported format. Use images, video, audio, TXT, or Markdown.",
            )
        name = uid() + suffix
        path = folder / name
        size = 0
        try:
            with path.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise ValueError(
                            "Each file must be smaller than 512 MB in this prototype."
                        )
                    out.write(chunk)
            if suffix in [".txt", ".md"]:
                if size > 1000000:
                    raise ValueError("Text imports must be smaller than 1 MB.")
                script = path.read_text(encoding="utf-8-sig")[:200000]
                path.unlink()
                continue
            asset = {
                "id": uid(),
                "name": (file.filename or name)[:180],
                "path": asset_reference(path),
                "url": f"/media/{id}/{name}",
                "size": size,
                "generated": False,
                "license": "",
                "thumbnail": None,
            }
            if suffix in [".png", ".jpg", ".jpeg", ".webp"]:
                with Image.open(path) as image:
                    image = ImageOps.exif_transpose(image)
                    image.load()
                    if image.width * image.height > 60000000:
                        raise ValueError(
                            "Image is too large. Resize it below 60 megapixels."
                        )
                    asset.update(
                        kind="image",
                        width=image.width,
                        height=image.height,
                        duration=0,
                        has_audio=False,
                    )
                    thumb = folder / (path.stem + "-thumb.jpg")
                    ImageOps.fit(image.convert("RGB"), (480, 270)).save(
                        thumb, quality=82
                    )
                asset["thumbnail"] = f"/media/{id}/{thumb.name}"
            else:
                info = await __import__("asyncio").to_thread(renderer.probe, path)
                asset.update(info, kind="video" if info["has_video"] else "audio")
                if info["duration"] > 21600:
                    raise ValueError("Media longer than six hours is not supported.")
                if asset["kind"] == "video":
                    thumb = folder / (path.stem + "-thumb.jpg")
                    await __import__("asyncio").to_thread(
                        renderer.thumbnail, path, thumb
                    )
                    asset["thumbnail"] = f"/media/{id}/{thumb.name}"
                    # v0.4.47: a transparent .MOV (ProRes, Animation…) does not play in the browser;
                    # short ones (likely a CTA animation) get preview stills right away.
                    if renderer.needs_preview(info) and info["duration"] <= 60:
                        await __import__("asyncio").to_thread(make_preview, id, asset, path)
                if info["has_audio"]:
                    asset["waveform"] = await __import__("asyncio").to_thread(
                        renderer.waveform, path
                    )
            if episode_role in ("narration", "music") and not asset.get("has_audio"):
                raise ValueError(
                    "Narration and music require an actual audio track, not an image or silent video."
                )
            if sfx_upload and (asset.get("kind") != "audio" or float(asset.get("duration") or 0) > 30):
                raise ValueError("A sound effect must be an audio file (WAV, MP3, M4A, OGG, FLAC) of up to 30 seconds.")
            if sfx_upload:
                asset["sfx"] = True
            if episode_role == "sources" and asset["kind"] not in ("image", "video"):
                raise ValueError(
                    "The source-file input accepts uploaded images and videos. Keep music and narration in their own cards."
                )
            added.append(asset)
        except Exception as e:
            path.unlink(missing_ok=True)
            # Keep previously accepted files when a later file fails.
            with LOCK:
                latest = project_or_404(id)
                latest["assets"].extend(added)
                if script is not None:
                    latest["script"] = script
                save_project(latest)
            raise HTTPException(422, str(e)[:400])
        finally:
            await file.close()
    with LOCK:
        p = project_or_404(id)
        p["assets"].extend(added)
        if sfx_upload:
            return save_project(p)
        if episode_role and not p.get("episode"):
            p["episode"] = copy.deepcopy(episode.state(p))
        if script is not None:
            checkpoint(p, "Upload")
            p["script"] = script
            p["script_dirty"] = True
            p["script_origin"] = "user"
            p["script_approved_hash"] = None
            p["review"]["facts"] = False
        # Auto-rebuild the inspection timeline when media lands, so uploaded
        # source files are matched to gap scenes and cue crops are inherited.
        # No manual "First draft" click required.
        if p.get("episode") and p["episode"].get("guide"):
            try:
                episode.build(p, allow_placeholders=True, inspection=True)
            except (ValueError, TypeError, KeyError):
                # A failed rebuild must not block the upload itself. Assets are
                # already saved; the user can run First draft manually.
                pass
        return save_project(p)


def make_preview(project_id, asset, path):
    """v0.4.47 Give a video the browser cannot play (a transparent .MOV) WebP stills for the edit preview."""
    folder = path.with_name(path.stem + "-frames")
    try:
        info = renderer.preview_frames(path, folder)
    except (ValueError, OSError, subprocess.TimeoutExpired) as e:
        asset["preview_error"] = str(e)[:300]
        return asset
    asset.pop("preview_error", None)
    asset["preview_frames"] = {**info, "base": f"/media/{project_id}/{folder.name}/"}
    return asset


@app.post("/api/projects/{id}/assets/{asset_id}/preview")
async def asset_preview(id: str, asset_id: str):
    """v0.4.47 Check a video uploaded before v0.4.47 and make its preview stills if the browser
    cannot play it. Returns the asset (with `codec`, so the page asks only once).
    v0.4.50: stills from before v0.4.50 (640 px, soft) are made again, sharp."""
    with LOCK:
        p = project_or_404(id)
        asset = copy.deepcopy(next((a for a in p["assets"] if a["id"] == asset_id), None))
    if not asset or asset.get("kind") != "video":
        raise HTTPException(404, "Video not found.")
    if (asset.get("preview_frames") or {}).get("version", 1) >= renderer.PREVIEW_VERSION:
        return asset
    try:
        path = renderer.asset_path(asset)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not asset.get("codec"):
        info = await asyncio.to_thread(renderer.probe, path)
        asset.update(codec=info["codec"], alpha=info["alpha"])
    if renderer.needs_preview(asset):
        await asyncio.to_thread(make_preview, id, asset, path)
    with LOCK:
        p = project_or_404(id)
        for a in p["assets"]:
            if a["id"] == asset_id:
                for k in ("codec", "alpha", "preview_frames", "preview_error"):
                    if k in asset:
                        a[k] = asset[k]
                    else:
                        a.pop(k, None)
                save_project(p)
    if asset.get("preview_error"):
        raise HTTPException(422, asset["preview_error"])
    return asset


@app.patch("/api/projects/{id}/assets/{asset_id}")
async def update_asset(id: str, asset_id: str, request: Request):
    body = await request.json()
    with LOCK:
        p = project_or_404(id)
        asset = next((a for a in p["assets"] if a["id"] == asset_id), None)
        if not asset:
            raise HTTPException(404, "Media not found.")
        checkpoint(p)  # v0.4.51: a crop, a rename… can be undone
        for key in ["name", "license"]:
            if key in body:
                asset[key] = str(body[key])[: 1000 if key == "license" else 180]
                p["review"]["rights"] = False
        if "sticker" in body and asset.get("kind") == "image":
            asset["sticker"] = body["sticker"] is True  # v0.4.49: listed under Stickers · Yours
        if "crop" in body:
            # v0.4.49: keep only the real photo; every scene using this file gets it.
            if asset.get("kind") not in ("image", "video"):
                raise HTTPException(422, "Only pictures and clips can be cropped.")
            box = picture.normalise_crop(body["crop"])
            if box:
                asset["crop"] = box
            else:
                asset.pop("crop", None)
            p["review"]["picture"] = False
        return save_project(p)


@app.post("/api/projects/{id}/assets/{asset_id}/autocrop")
def auto_crop(id: str, asset_id: str):
    """v0.4.49 Suggest a crop that cuts away black bars and plain borders (not saved)."""
    with LOCK:
        p = project_or_404(id)
        asset = copy.deepcopy(next((a for a in p["assets"] if a["id"] == asset_id), None))
    if not asset or asset.get("kind") not in ("image", "video"):
        raise HTTPException(404, "Picture not found.")
    try:
        path = renderer.asset_path(asset)
        if asset["kind"] == "image":
            box = picture.detect_crop(path)
        else:
            box = picture.detect_crop_video(path, asset.get("duration") or asset.get("video_duration"), DATA / "cache" / "autocrop" / asset_id)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        raise HTTPException(422, f"Could not look at this picture: {e}")
    return {"crop": box or [0.0, 0.0, 1.0, 1.0], "found": bool(box)}


@app.get("/api/stickers/{kind}/{frame}.png")
def sticker_frame(kind: str, frame: int):
    """v0.4.49 A built-in sticker drawn by the export's own code, for the preview."""
    try:
        path = stickers.preview_frame(kind, frame, DATA / "cache" / "stickers")
    except KeyError:
        raise HTTPException(404, "Unknown sticker.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------------ v0.4.52 motion graphics

def _motion_photo(p, item):
    """The picture behind a graphic: your photo or a still from your footage (v0.4.53)."""
    return motiongfx.background_path(p, item, DATA, renderer.asset_path)


@app.get("/api/projects/{id}/motion/narration")
def motion_narration(id: str):
    """The narration's sentences with their times on the timeline (to choose a passage)."""
    p = project_or_404(id)
    words = motiongfx.timeline_words(p)
    return {"sentences": [{"text": s["text"], "start": round(s["t"], 3), "end": round(s["e"], 3), "scene": s["scene"]}
                          for s in motiongfx.sentences(words)],
            "exact": bool(((p.get("episode") or {}).get("timings") or {}).get("words"))}


@app.get("/api/motion/catalog")
def motion_catalog():
    """v0.4.62 The story-aware (cinematic) graphics: the collections (niches) and their categories."""
    import cinematic
    return cinematic.catalog()


@app.post("/api/projects/{id}/motion/options")
async def motion_options(id: str, request: Request):
    """v0.4.62 Which cinematic categories the passage between `start` and `end` supports, best first."""
    import cinematic
    body = await request.json()
    p = project_or_404(id)
    try:
        start, end = float(body["start"]), float(body["end"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "Choose a passage of the narration.")
    opts, win = cinematic.options(p, start, end, body.get("collection") or cinematic.DEFAULT_COLLECTION)
    return {"options": [{k: v for k, v in o.items() if k != "beat"} for o in opts], "sentences": list(win) if win else None}


@app.post("/api/projects/{id}/motion/draft")
async def motion_draft(id: str, request: Request):
    """A graphic made from the narration between `start` and `end` (not saved: the editor adds it)."""
    body = await request.json()
    p = project_or_404(id)
    if body.get("template") != "cinematic" and body.get("template") not in motiongfx.TEMPLATES:
        raise HTTPException(422, "Choose a template.")
    try:
        start, end = float(body["start"]), float(body["end"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "Choose a passage of the narration.")
    if body["template"] == "cinematic":  # v0.4.62: the story-aware engine reads the passage and picks (or checks) the category
        import cinematic
        prev = next((x for x in motiongfx.normalise(p.get("motion"))["items"] if body.get("id") and x["id"] == body["id"]), None)
        try:
            item, opts = cinematic.draft(p, start, end, body.get("collection") or cinematic.DEFAULT_COLLECTION,
                                         body.get("category") or "auto", item_id=body.get("id") or None, prev=prev,
                                         window=body.get("window") if isinstance(body.get("window"), list) else None)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"item": item, "options": opts}
    item = motiongfx.draft(p, body["template"], start, end, item_id=body.get("id") or None)
    if not item:
        raise HTTPException(422, "There is no narration in this passage.")
    if not body.get("id"):  # v0.4.53: a new graphic of a template you already use gets another layout
        others = motiongfx.normalise(p.get("motion"))["items"]
        item = motiongfx.vary_layout(item, others, motiongfx._is_tall(p))
    return {"item": item}


@app.post("/api/projects/{id}/motion/suggest")
async def motion_suggest(id: str, request: Request):
    """Read the whole narration and propose graphics (replaces the earlier suggestions you have not
    approved or edited; can be undone). v0.4.62: {"engine": "cinematic", "collection": ...} places the
    story-aware graphics instead (replacing only earlier cinematic suggestions)."""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    cine = body.get("engine") == "cinematic"
    with LOCK:
        p = project_or_404(id)
        checkpoint(p)
        cur = motiongfx.normalise(p.get("motion"))
        is_cine = lambda x: x["template"] == "cinematic"
        keep = [x for x in cur["items"] if x["status"] != "suggested" or is_cine(x) != cine]
        if cine:
            import cinematic
            try:
                new = cinematic.suggest(p, keep, body.get("collection") or cinematic.DEFAULT_COLLECTION)
            except ValueError as e:
                raise HTTPException(422, str(e))
        else:
            new = motiongfx.suggest(p, keep)
        p["motion"] = motiongfx.normalise({"enabled": cur["enabled"], "items": keep + new, "look": cur.get("look")})  # v0.4.63 keeps the look
        p = save_project(p)
    return {"project": p, "added": len(new)}


@app.post("/api/projects/{id}/motion/present")
async def motion_present(id: str, request: Request):
    """v0.4.65 How each cinematic graphic could be presented (full screen, over the footage, partial), from its
    design, the shots under it and the production script's chapter and shot notes. Without "apply" it only
    proposes (nothing saved); {"apply": [ids]} applies those proposals as each graphic's own look (can be undone)."""
    import presentation
    try:
        body = await request.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    ids = body.get("apply")
    if not isinstance(ids, list):
        p = project_or_404(id)
        return {"proposals": presentation.propose(p)}
    ids = {str(x) for x in ids}
    with LOCK:
        p = project_or_404(id)
        props = {x["id"]: x for x in presentation.propose(p) if x["id"] in ids and not x["same"]}
        if props:
            checkpoint(p)
            cur = motiongfx.normalise(p.get("motion"))
            for it in cur["items"]:
                if it["id"] in props:
                    it["look"] = presentation.apply(it.get("look"), props[it["id"]])
            p["motion"] = motiongfx.normalise(cur, {x["id"] for x in p["assets"] if x.get("kind") == "image"})
            p = save_project(p)
    return {"project": p, "applied": len(props), "proposals": presentation.propose(p)}


@app.post("/api/projects/{id}/motion/plan")
async def motion_plan(id: str, request: Request):
    """The preview frames of one graphic (the editor plays them; drawn in the background)."""
    body = await request.json()
    p = project_or_404(id)
    item = motiongfx.normalise_item(body.get("item"))
    if not item:
        raise HTTPException(422, "Not a motion graphic.")
    if item["template"] == "cinematic":  # v0.4.63: drawn with its look over the project look the editor has now
        import cinematic
        images = {x["id"] for x in p.get("assets") or [] if x.get("kind") == "image"}
        look = (cinematic.normalise_look(body.get("look"), project=True, image_assets=images) if "look" in body
                else motiongfx.normalise(p.get("motion")).get("look"))
        item["style"] = cinematic.style_of(item, look)
    try:
        out = motiongfx.preview_plan(DATA, p, item, _motion_photo(p, item))
    except (OSError, ValueError) as e:
        raise HTTPException(422, f"Could not prepare the preview: {e}")
    motiongfx.warm(DATA, out["hash"], out["unique"], paused=lambda: RENDER_LOCK._value == 0)
    return out


@app.get("/api/motion/{h}/{k}.webp")
def motion_frame(h: str, k: int):
    try:
        path = motiongfx.preview_frame(DATA, h, k)
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(404, "Not prepared.")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ------------------------------------------------------------------ v0.4.56 sound design

@app.get("/api/sound/catalog")
def sound_catalog():
    """The built-in library (made by sfxlib on this computer; nothing is downloaded)."""
    return {"sounds": sfxlib.catalog(), "categories": sfxlib.CATEGORIES, "version": sfxlib.LIB_VERSION}


@app.get("/api/sound/lib/{sid}.wav")
def sound_file(sid: str):
    if sid not in sfxlib.BY_ID:
        raise HTTPException(404, "Unknown sound.")
    sfxlib.ensure(DATA, [sid])
    return FileResponse(sfxlib.path_of(DATA, sid), media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/projects/{id}/sound/custom/{asset_id}.wav")
def sound_custom_file(id: str, asset_id: str):
    p = project_or_404(id)
    try:
        path = sfxplan.custom_file(p, DATA, f"a:{asset_id}")
    except (OSError, ValueError, subprocess.CalledProcessError):
        path = None
    if not path:
        raise HTTPException(404, "That sound file could not be read.")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/projects/{id}/sound/plan")
def sound_plan(id: str):
    """Where every sound falls on the timeline now, what was left silent and why."""
    p = project_or_404(id)
    return sfxplan.overview(p, DATA)


@app.get("/api/projects/{id}/sound/duck")
def sound_duck(id: str):
    """v0.4.57 The effects' gain over time under the voice, exactly as the export ducks them, for the
    editor preview ({status: none | working | ready}; made in the background, cached)."""
    p = project_or_404(id)
    return sfxplan.duck_curve(p, DATA)


@app.post("/api/projects/{id}/sound/generate")
def sound_generate(id: str):
    """Plan again from the timeline (your own sounds, edits and removals stay; can be undone)."""
    with LOCK:
        p = project_or_404(id)
        checkpoint(p)
        cur = sfxplan.normalise(p.get("sound"))
        mine = [it for it in cur["items"] if it["source"] == "manual" or it["edited"] or it["status"] == "removed"]
        fresh, info = sfxplan.plan(p, cur, keep={it["anchor"] for it in mine}, held=sfxplan._held(p, mine))
        p["sound"] = {**cur, "items": mine + fresh}
        p = save_project(p)
    return {"project": p, "added": len(fresh), "silenced": len(info["silenced"])}


@app.delete("/api/projects/{id}/assets/{asset_id}")
def delete_asset(id: str, asset_id: str):
    with LOCK:
        p = project_or_404(id)
        if any(
            j["project_id"] == id and j["status"] in ("running", "queued")
            for j in JOBS.values()
        ):
            raise HTTPException(
                409, "Wait for the current operation before deleting media."
            )
        checkpoint(p, "Delete media")
        asset = next((a for a in p["assets"] if a["id"] == asset_id), None)
        if not asset:
            raise HTTPException(404, "Media not found.")
        p["assets"] = [a for a in p["assets"] if a["id"] != asset_id]
        for s in p["scenes"]:
            if s.get("asset_id") == asset_id:
                s["asset_id"] = None
        for key in ["narration_id", "music_id"]:
            if p.get(key) == asset_id:
                p[key] = None
        # Keep bytes for undo references and existing exported project manifests.
        p["review"]["picture"] = False
        return save_project(p)


@app.post("/api/projects/{id}/sources")
async def add_source(id: str, request: Request):
    data = await request.json()
    with LOCK:
        p = project_or_404(id)
        url = str(data.get("url", "")).strip()
        if url and (
            urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc
        ):
            raise HTTPException(
                422,
                "Use a complete http or https source URL, or leave it empty for an offline source.",
            )
        title = str(data.get("title", "")).strip()[:250]
        if not title:
            raise HTTPException(422, "Give the source a title.")
        n = (
            max(
                [
                    int(s["id"][1:])
                    for s in p["sources"]
                    if re.fullmatch(r"S\d+", s["id"])
                ]
                + [0]
            )
            + 1
        )
        p["sources"].append(
            {
                "id": f"S{n}",
                "title": title,
                "url": url[:2000],
                "notes": str(data.get("notes", ""))[:20000],
                "type": str(data.get("type", "Producer source"))[:80],
                "reviewed": False,
            }
        )
        p["review"]["facts"] = False
        return save_project(p)


@app.patch("/api/projects/{id}/sources/{source_id}")
async def patch_source(id: str, source_id: str, request: Request):
    data = await request.json()
    with LOCK:
        p = project_or_404(id)
        source = next((s for s in p["sources"] if s["id"] == source_id), None)
        if not source:
            raise HTTPException(404, "Source not found.")
        changed = False
        for field in ["title", "notes"]:
            if field in data:
                value = str(data[field])[:20000]
                changed = changed or value != source.get(field, "")
                source[field] = value
        if changed:
            source["reviewed"] = False
        if "reviewed" in data:
            source["reviewed"] = bool(data["reviewed"])
        if not editorial.script_approved(p):
            p["script_approved_hash"] = None
        p["review"]["facts"] = False
        return save_project(p)


@app.post("/api/projects/{id}/research")
def research(id: str, request: Request):
    p = project_or_404(id)
    cfg = config(request)
    if p.get("is_demo"):
        raise HTTPException(
            400,
            "Start a new project for real case research. The sample is intentionally fictional.",
        )
    if not p["topic"].strip():
        raise HTTPException(
            400, "Enter a case name, place, and any identifying context first."
        )

    def work(progress, cancelled):
        result = ai.research(cfg, p, progress)
        if not cancelled():
            with LOCK:
                latest = project_or_404(id)
                # Remap new source IDs and retain producer-added/previously reviewed sources.
                existing = latest["sources"]
                base = max(
                    [
                        int(s["id"][1:])
                        for s in existing
                        if re.fullmatch(r"S\d+", s["id"])
                    ]
                    + [0]
                )
                for n, source in enumerate(result["sources"]):
                    source["id"] = f"S{base + n + 1}"
                latest["research_report"] = result["research_report"]
                latest["sources"] = existing + result["sources"]
                latest["review"]["facts"] = False
                add_message(
                    latest,
                    "assistant",
                    "Research brief saved with source leads. Open the originals, add verified notes, and mark sources reviewed before drafting.",
                )
                save_project(latest)
        return {"sources": len(result["sources"])}

    return spawn(id, "research", work)


@app.post("/api/projects/{id}/draft")
def draft(id: str, request: Request):
    p = project_or_404(id)
    if (p.get("episode") or {}).get("guide"):
        raise HTTPException(
            400,
            "This guide-driven project preserves your supplied script and voice. Use Episode setup; destructive script/voice/transcript generation is disabled.",
        )
    cfg = config(request)
    if not any(s.get("reviewed") for s in p["sources"]):
        raise HTTPException(
            400,
            "Review at least one source in Research before drafting a factual script.",
        )

    def work(progress, cancelled):
        result = ai.draft_script(cfg, p, progress)
        if not cancelled():
            with LOCK:
                latest = project_or_404(id)
                checkpoint(latest, "Draft script")
                latest["script"] = result["script"]
                latest["script_origin"] = "ai"
                latest["script_approved_hash"] = None
                latest["narration_id"] = None
                latest["scenes"] = build_scenes(latest)
                latest["script_dirty"] = False
                latest["review"]["facts"] = False
                latest["review"]["picture"] = False
                add_message(
                    latest,
                    "assistant",
                    result.get(
                        "note",
                        "Draft ready. Review every claim and scene before publication.",
                    ),
                )
                save_project(latest)
        return {"draft_ready": True}

    return spawn(id, "script", work)


@app.post("/api/projects/{id}/narrate")
def narrate(id: str, request: Request):
    p = project_or_404(id)
    if (p.get("episode") or {}).get("guide"):
        raise HTTPException(
            400,
            "This guide-driven project preserves your supplied script and voice. Use Episode setup; destructive script/voice/transcript generation is disabled.",
        )
    cfg = config(request)
    if not p["scenes"]:
        raise HTTPException(400, "Build a timeline first.")
    if message := editorial.narration_gate(p):
        raise HTTPException(400, message)

    def work(progress, cancelled):
        asset, scenes = ai.generate_narration(cfg, p, progress, cancelled)
        if not cancelled():
            with LOCK:
                latest = project_or_404(id)
                checkpoint(latest, "Narration")
                latest["assets"].append(asset)
                latest.update(narration_id=asset["id"], scenes=scenes)
                latest["review"]["disclosure"] = False
                latest["review"]["picture"] = False
                add_message(
                    latest,
                    "assistant",
                    "AI narration generated and aligned by scene. Caption timing inside each scene is estimated; transcribe the voice track for tighter timing. Disclose synthetic narration to viewers.",
                )
                save_project(latest)
        return {"narration_ready": True}

    return spawn(id, "narration", work)


@app.post("/api/projects/{id}/transcribe/{asset_id}")
def transcribe(id: str, asset_id: str, request: Request):
    p = project_or_404(id)
    if (p.get("episode") or {}).get("guide"):
        raise HTTPException(
            400,
            "This guide-driven project preserves your supplied script and voice. Use Episode setup; destructive script/voice/transcript generation is disabled.",
        )
    cfg = config(request)
    asset = next((a for a in p["assets"] if a["id"] == asset_id), None)
    if not asset:
        raise HTTPException(404, "Media not found.")

    def work(progress, cancelled):
        segments = ai.transcribe(cfg, p, asset, progress, cancelled)
        scenes = production.transcript_scenes(p, asset, segments)
        if not cancelled():
            with LOCK:
                latest = project_or_404(id)
                checkpoint(latest, "Transcription")
                latest.update(
                    scenes=scenes,
                    script="\n\n".join(s["narration"] for s in scenes),
                    script_dirty=False,
                    script_origin="transcript",
                    script_approved_hash=None,
                    narration_id=asset_id,
                )
                latest["review"]["picture"] = False
                latest["review"]["facts"] = False
                add_message(
                    latest,
                    "assistant",
                    "Transcription assembled into a source-aligned timeline. This replaces the previous timeline (Undo is available). Review recognition accuracy and every cut.",
                )
                save_project(latest)
        return {"scenes": len(scenes)}

    return spawn(id, "transcription", work)


def apply_plan(p, plan, ai_generated=False):
    if (p.get("episode") or {}).get("guide"):
        for op in plan.get("operations", []):
            if op.get("op") in ("move_scene", "delete_scene") or (
                op.get("op") == "update_scene"
                and set(op.get("fields", {}))
                - {"title", "show_title", "motion", "source_ids"}
            ):
                raise ValueError(
                    "This edit would change the preserved narration or guide timing. Change cue positions and source ranges in Episode setup, then rebuild. Look, caption, music-level, and source-annotation edits are supported without changing your voice."
                )
    checkpoint(p, "Direct your edit")
    narration_changed = False
    story_changed = False
    for op in plan.get("operations", [])[:500]:
        kind = op.get("op")
        if kind == "set_look" and op.get("value") in effects.LOOKS:
            p["look"] = op["value"]
        elif kind == "set_captions":
            p["captions"] = bool(op.get("value"))
        elif kind == "set_music_volume":
            value = float(op.get("value"))
            if not __import__("math").isfinite(value) or not 0 <= value <= 0.5:
                raise ValueError("Music level must be between 0% and 50%.")
            p["music_volume"] = value
        elif kind in ("update_scene", "move_scene", "delete_scene"):
            scene = next(
                (s for s in p["scenes"] if s["id"] == op.get("scene_id")), None
            )
            if not scene:
                raise ValueError(
                    "The edit plan referenced a scene that does not exist. No edit was saved."
                )
            if kind == "delete_scene":
                story_changed = True
                p["scenes"].remove(scene)
            elif kind == "move_scene":
                story_changed = True
                p["scenes"].remove(scene)
                p["scenes"].insert(
                    min(len(p["scenes"]), max(0, int(op.get("index", 0)))), scene
                )
            else:
                fields = {
                    k: v
                    for k, v in op.get("fields", {}).items()
                    if k
                    in [
                        "title",
                        "chapter",
                        "duration",
                        "narration",
                        "show_title",
                        "motion",
                        "transition",
                        "asset_id",
                        "trim_start",
                        "source_ids",
                    ]
                }
                if "narration" in fields and fields["narration"] != scene["narration"]:
                    narration_changed = True
                    story_changed = True
                    fields["captions"] = []
                    fields["timing"] = "estimated"
                if "source_ids" in fields and fields["source_ids"] != scene.get(
                    "source_ids", []
                ):
                    story_changed = True
                scene.update(fields)
                scene.update(sanitize_scene(scene, {a["id"] for a in p["assets"]}))
        else:
            raise ValueError(
                "The AI requested an unsupported operation. No changes were saved."
            )
    if narration_changed:
        p["narration_id"] = None
        p["review"]["facts"] = False
    if story_changed:
        if p.get("script_dirty"):
            raise ValueError(
                "Apply or undo your unapplied script edits before making story-changing commands."
            )
        p["script"] = editorial.script_from_scenes(p["scenes"])
        p["script_dirty"] = False
        p["script_approved_hash"] = None
        if ai_generated:
            p["script_origin"] = "ai"
    p["review"]["picture"] = False
    return narration_changed


def local_plan(instruction, p):
    text = instruction.strip().lower()
    ops = []
    message = ""
    if re.search(r"(hide|disable|turn off|remove).*(caption|subtitle)", text):
        ops = [{"op": "set_captions", "value": False}]
        message = "Captions are off."
    elif re.search(r"(show|enable|turn on).*(caption|subtitle)", text):
        ops = [{"op": "set_captions", "value": True}]
        message = "Captions are on."
    elif re.search(r"(hide|remove|show|enable).*(all )?titles", text):
        show = bool(re.search(r"^(show|enable)", text))
        ops = [
            {"op": "update_scene", "scene_id": s["id"], "fields": {"show_title": show}}
            for s in p["scenes"]
        ]
        message = ("Showing" if show else "Hiding") + " scene titles."
    elif re.search(r"(archive|noir|natural) (look|style)", text) or re.search(
        r"(look|style).*\b(archive|noir|natural)\b", text
    ):
        look = next(x for x in ("archive", "noir", "natural") if x in text)
        ops = [{"op": "set_look", "value": look}]
        message = f"Applied the {look} look."
    elif match := re.search(r"(?:music|background).*?(\d+(?:\.\d+)?)\s*%", text):
        level = float(match[1])
        if not 0 <= level <= 50:
            raise ValueError("Music level must be between 0% and 50%.")
        ops = [{"op": "set_music_volume", "value": level / 100}]
        message = f"Music level is {level:g}%. It still ducks under narration; listen to the actual MP4."
    elif match := re.search(
        r"scene\s+(\d+).*?(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b", text
    ):
        index, duration = int(match[1]) - 1, float(match[2])
        if not 0 <= index < len(p["scenes"]):
            raise ValueError("That scene number does not exist.")
        ops = [
            {
                "op": "update_scene",
                "scene_id": p["scenes"][index]["id"],
                "fields": {"duration": duration},
            }
        ]
        message = f"Scene {index + 1} is now {duration:g} seconds. Existing voice audio is trimmed or padded to fit; check the cut."
    elif match := re.search(r"move scene (\d+) to (?:position )?(\d+)", text):
        src, dest = int(match[1]) - 1, int(match[2]) - 1
        if not 0 <= src < len(p["scenes"]) or not 0 <= dest < len(p["scenes"]):
            raise ValueError("That scene position does not exist.")
        ops = [{"op": "move_scene", "scene_id": p["scenes"][src]["id"], "index": dest}]
        message = f"Moved scene {src + 1} to position {dest + 1}, including its narration slice."
    if not ops:
        return None
    return {"operations": ops, "message": message}


@app.post("/api/projects/{id}/command")
async def command(id: str, request: Request):
    data = await request.json()
    instruction = str(data.get("instruction", "")).strip()[:3000]
    if not instruction:
        raise HTTPException(422, "Enter an editing instruction.")
    p = project_or_404(id)
    try:
        plan = local_plan(instruction, p)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if plan:
        with LOCK:
            p = project_or_404(id)
            try:
                apply_plan(p, plan)
            except (ValueError, TypeError) as e:
                raise HTTPException(400, str(e))
            add_message(p, "user", instruction)
            add_message(p, "assistant", plan["message"])
            return {"project": save_project(p)}
    cfg = config(request)

    def work(progress, cancelled):
        plan = ai.edit_plan(cfg, p, instruction, progress)
        if not cancelled():
            with LOCK:
                latest = project_or_404(id)
                changed = apply_plan(latest, plan, ai_generated=True)
                add_message(latest, "user", instruction)
                note = plan.get("message", "Edit plan applied.")
                if changed:
                    note += " Narration text changed: the previous voice track was detached. Re-record or regenerate it before export."
                add_message(latest, "assistant", note)
                save_project(latest)
        return {"edit_applied": True}

    return spawn(id, "direction", work)


class ExportOptions(BaseModel):
    resolution: Literal["480p", "720p", "1080p"] = "720p"
    draft: bool = True
    captions: bool = True
    allow_guided_gaps: bool = False
    allow_inspection: bool = False


@app.post("/api/projects/{id}/render")
def export(id: str, options: ExportOptions):
    p = project_or_404(id)
    if ((p.get("episode") or {}).get("plan") or {}).get("mode") == "inspection":
        if not options.draft or not options.allow_inspection:
            raise HTTPException(
                400,
                "This is an unreviewed inspection plan. Explicitly choose an inspection draft; final export requires actual reviews and a reviewed-plan rebuild.",
            )
    report = editorial.inspect(p)
    issues = [
        i
        for i in report["issues"]
        if i["blocks_draft"] or (not options.draft and i["blocks_final"])
    ]
    if issues:
        raise HTTPException(
            400, " ".join(i["title"] + ": " + i["detail"] for i in issues[:2])
        )
    if (
        options.draft
        and (p.get("episode") or {}).get("guide")
        and any(not s.get("asset_id") for s in p["scenes"])
        and not options.allow_guided_gaps
    ):
        raise HTTPException(
            400,
            "This guide plan has missing visual coverage. Explicitly allow marked gap cards for an internal review-only video; CASEFILE will not substitute or loop unrelated footage.",
        )
    return spawn(
        id,
        "render",
        lambda progress, cancelled: write_export(
            p, options.model_dump(), progress, cancelled
        ),
    )


def with_machine_note(progress):
    """v0.4.48: progress messages say so when the render runs as translated Intel
    code (an amd64 image on an Apple-silicon Mac) or with only 1-2 CPUs."""
    note = renderer.machine_note()
    if not note:
        return progress
    return lambda percent, message, **extra: progress(percent, message + note, **extra)


def write_export(project, options, progress, cancelled):
    progress = with_machine_note(progress)
    export_id = uid()
    folder = DATA / "exports" / export_id
    folder.mkdir(parents=True, exist_ok=True)
    with RENDER_LOCK:
        try:
            if cancelled():
                raise RuntimeError("Render cancelled before it started.")
            out = folder / "documentary.mp4"
            info = renderer.render(project, options, out, progress, cancelled)
            if cancelled():
                raise RuntimeError("Render cancelled. No output was published.")
            # v0.4.48: where the time went, for "why is my render slow?"
            timing = info.pop("timing", None)
            if timing:
                (folder / "render-report.txt").write_text(renderer.timing_report(timing))
                info["render_seconds"] = timing["total"]
                info["render_report_url"] = f"/exports/{export_id}/render-report.txt"
            report = editorial.inspect(project)
            (folder / "captions.srt").write_text(renderer.project_srt(project))
            (folder / "sources.md").write_text(source_notes(project))
            (folder / "preflight.md").write_text(
                editorial.report_markdown(project, report)
            )
            (folder / "chapters.txt").write_text(editorial.chapter_text(project))
            (folder / "publication-notes.md").write_text(
                editorial.publication_notes(project)
            )
            if project.get("episode"):
                (folder / "episode-plan.md").write_text(episode.markdown(project))
            atomic_json(folder / "preflight.json", report)
            atomic_json(
                folder / "project.json",
                {k: v for k, v in project.items() if k not in ("undo", "history")},
            )
            record = {
                "id": export_id,
                "title": project["title"],
                "created_at": now(),
                "draft": options["draft"],
                "url": f"/exports/{export_id}/documentary.mp4",
                "captions_url": f"/exports/{export_id}/captions.srt",
                "sources_url": f"/exports/{export_id}/sources.md",
                "preflight_url": f"/exports/{export_id}/preflight.md",
                "chapters_url": f"/exports/{export_id}/chapters.txt",
                "publication_url": f"/exports/{export_id}/publication-notes.md",
                **info,
            }
            if project.get("episode"):
                record["episode_plan_url"] = f"/exports/{export_id}/episode-plan.md"
                record["marked_gaps_allowed"] = options.get("allow_guided_gaps", False)
                record["inspection_only"] = (
                    (project.get("episode") or {}).get("plan") or {}
                ).get("mode") == "inspection"
            with LOCK:
                latest = project_or_404(project["id"])
                latest["exports"].insert(0, record)
                save_project(latest)
            return record
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise


class ProductionOptions(BaseModel):
    allow_paid: bool = False
    generate_voice: bool = False
    auto_assign_visuals: bool = True
    allow_placeholders: bool = False
    allow_silent: bool = False
    render: bool = True
    resolution: Literal["480p", "720p", "1080p"] = "720p"
    source_asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    max_voice_characters: int = Field(default=45000, ge=1000, le=90000)


@app.post("/api/projects/{id}/production-plan")
def production_plan(id: str, options: ProductionOptions, request: Request):
    p = project_or_404(id)
    if (p.get("episode") or {}).get("guide"):
        raise HTTPException(
            400,
            "Use Episode setup for this guide-driven project; generic footage rotation is disabled.",
        )
    return production.plan(
        p,
        production.Options(**options.model_dump()),
        public_config(request)["connected"],
    )


@app.post("/api/projects/{id}/produce")
def auto_produce(id: str, options: ProductionOptions, request: Request):
    p = project_or_404(id)
    if (p.get("episode") or {}).get("guide"):
        raise HTTPException(
            400,
            "This project follows an editing guide. Use Episode setup to build and render; generic footage rotation is disabled.",
        )
    cfg = copy.deepcopy(SESSIONS.get(request.state.session))
    opts = production.Options(**options.model_dump())
    return spawn(
        id,
        "production",
        lambda progress, cancelled: production.run(
            id, opts, cfg, progress, cancelled, write_export
        ),
    )


@app.post("/api/projects/{id}/approve-script")
async def approve_script(id: str, request: Request):
    body = await request.json()
    if body.get("acknowledge") is not True:
        raise HTTPException(
            400, "Explicitly confirm that you reviewed the script against its sources."
        )
    with LOCK:
        p = project_or_404(id)
        problems = editorial.script_problems(p)
        if not p.get("script", "").strip():
            raise HTTPException(400, "There is no script to approve.")
        if problems["unresolved"] or problems["unknown_sources"]:
            raise HTTPException(
                400,
                "Resolve unverified markers and broken source references before approving the AI script.",
            )
        if p.get("script_origin") == "ai" and not any(
            s.get("reviewed") for s in p.get("sources", [])
        ):
            raise HTTPException(
                400,
                "Review the original sources before approving an AI-generated factual script.",
            )
        used = {s["id"]: s for s in p.get("sources", [])}
        if any(
            not used[ref].get("reviewed")
            for ref in problems["references"]
            if ref in used
        ):
            raise HTTPException(
                400, "Review all cited sources before approving the script."
            )
        checkpoint(p, "Approve script")
        p["script_approved_hash"] = editorial.approval_fingerprint(p)
        add_message(
            p,
            "assistant",
            "Producer approved the script text for narration. This approval does not independently verify case facts or clear media rights.",
        )
        return save_project(p)


@app.get("/api/projects/{id}/preflight")
def preflight(id: str):
    return editorial.inspect(project_or_404(id))


@app.get("/api/projects/{id}/preflight.md")
def preflight_download(id: str):
    return PlainTextResponse(
        editorial.report_markdown(project_or_404(id)),
        headers={"Content-Disposition": 'attachment; filename="preflight.md"'},
    )


@app.get("/api/projects/{id}/chapters.txt")
def chapters_download(id: str):
    return PlainTextResponse(
        editorial.chapter_text(project_or_404(id)),
        headers={"Content-Disposition": 'attachment; filename="chapters.txt"'},
    )


def source_notes(p):
    text = f"# {p['title']}\n\nExported {now()}\n\n"
    if p.get("is_demo"):
        text += "**FICTIONAL DEMONSTRATION. All sample imagery is AI-generated illustration, not real evidence.**\n\n"
    text += "## Sources\n\n"
    for s in p["sources"]:
        text += f"### [{s['id']}] {s['title']}\n{s.get('url', 'Offline source')}\n\nReviewed: {s.get('reviewed', False)}\n\n{s.get('notes', '')}\n\n"
    text += "## Scene references\n\n"
    for n, scene in enumerate(p.get("scenes", [])):
        refs = ", ".join(scene.get("source_ids", [])) or "Not linked"
        text += f"- Scene {n + 1}: {scene.get('title', '')} — {refs}\n"
    text += "\n## Media rights notes\n\n"
    for a in p["assets"]:
        text += f"- {a['name']}: {a.get('license') or 'RIGHTS NOT DOCUMENTED'}\n"
    text += "\n## Editorial checklist\n\n" + "\n".join(
        f"- {k}: {v}" for k, v in p["review"].items()
    )
    text += "\n\nThis file records producer review, not independent legal clearance or fact verification.\n"
    return text


@app.get("/api/projects/{id}/captions.srt")
def captions_download(id: str):
    p = project_or_404(id)
    return PlainTextResponse(
        renderer.project_srt(p),
        headers={"Content-Disposition": 'attachment; filename="captions.srt"'},
    )


@app.get("/api/projects/{id}/sources.md")
def sources_download(id: str):
    return PlainTextResponse(
        source_notes(project_or_404(id)),
        headers={"Content-Disposition": 'attachment; filename="source-notes.md"'},
    )


@app.get("/api/projects/{id}/project.json")
def project_download(id: str):
    p = project_or_404(id)
    p.pop("undo", None)
    p.pop("history", None)
    return JSONResponse(
        p,
        headers={"Content-Disposition": 'attachment; filename="casefile-project.json"'},
    )


class ClearSessionOptions(BaseModel):
    confirm_download_saved: bool = False


@app.delete("/api/projects/{id}/session")
def clear_session(id: str, options: ClearSessionOptions):
    """Explicit post-save cleanup. Never follows client paths or touches originals."""
    if not options.confirm_download_saved:
        raise HTTPException(
            422,
            "Confirm that you saved and checked the output/backups you need before clearing this temporary session.",
        )
    with LOCK:
        p = project_or_404(id)
        if p.get("is_demo"):
            raise HTTPException(
                400, "The shared fictional sample is not a user session to clear."
            )
        if any(
            j.get("project_id") == id and j.get("status") in ("running", "queued")
            for j in JOBS.values()
        ):
            raise HTTPException(
                409, "Finish or cancel the current job before clearing this session."
            )
        removals = []
        media = DATA / "media" / id
        if media.exists():
            if media.is_symlink() or not media.resolve().is_relative_to(
                (DATA / "media").resolve()
            ):
                raise HTTPException(
                    409, "Unsafe session media path; no files were cleared."
                )
            removals.append(media)
        for record in p.get("exports", []):
            eid = str(record.get("id", ""))
            if not re.fullmatch(r"[a-f0-9]{16}", eid):
                continue
            folder = DATA / "exports" / eid
            if not folder.exists():
                continue
            if folder.is_symlink() or not folder.resolve().is_relative_to(
                (DATA / "exports").resolve()
            ):
                raise HTTPException(409, "Unsafe export path; no files were cleared.")
            manifest = folder / "project.json"
            try:
                owner = json.loads(manifest.read_text()).get("id")
            except (OSError, ValueError):
                owner = None
            if owner == id:
                removals.append(folder)
        owned_jobs = [key for key, job in JOBS.items() if job.get("project_id") == id]
        for folder in removals:
            shutil.rmtree(folder)
        for key in owned_jobs:
            if re.fullmatch(r"[a-f0-9]{16}", key):
                (DATA / "jobs" / f"{key}.json").unlink(missing_ok=True)
            JOBS.pop(key, None)
        for file in (DATA / "recovery-backups").glob(f"{id}-*.json"):
            file.unlink(missing_ok=True)
        for file in (DATA / "browser-sessions").glob("*.json"):
            try:
                record = json.loads(file.read_text())
                if (record.get("snapshot") or {}).get("id") == id:
                    file.unlink(missing_ok=True)
            except (OSError, ValueError, AttributeError):
                pass
        (DATA / "projects" / f"{id}.json").unlink()
        return {
            "deleted": True,
            "project_id": id,
            "folders_removed": len(removals),
            "jobs_removed": len(owned_jobs),
            "original_computer_files": "untouched; only this server's working copies were cleared",
        }


@app.api_route(
    "/api/projects/{id}/exports/{export_id}/download", methods=["GET", "HEAD"]
)
def download_export(id: str, export_id: str):
    """Save a completed export; never render again, approve it or delete it."""
    p = project_or_404(id)
    if not re.fullmatch(r"[a-f0-9]{16}", export_id):
        raise HTTPException(404, "Rendered video not found.")
    record = next(
        (item for item in p.get("exports", []) if item.get("id") == export_id), None
    )
    if record is None:
        raise HTTPException(
            404, "This completed export does not belong to the selected project."
        )
    folder = (DATA / "exports" / export_id).resolve()
    if not folder.is_relative_to((DATA / "exports").resolve()):
        raise HTTPException(404, "Rendered video is unavailable.")
    file = (folder / "documentary.mp4").resolve()
    if not file.is_relative_to(folder) or not file.is_file():
        raise HTTPException(
            404,
            "The render record exists, but its MP4 is not available on this server. A project JSON backup does not contain the video bytes. Nothing was deleted by this download request.",
        )
    title = (
        re.sub(r"[^A-Za-z0-9 _-]", "", str(p.get("title", "Casefile-video"))).strip()[
            :110
        ]
        or "Casefile-video"
    )
    suffix = (
        "-unreviewed-inspection"
        if record.get("inspection_only")
        else "-review-draft"
        if record.get("draft")
        else ""
    )
    return FileResponse(
        file,
        media_type="video/mp4",
        filename=title + suffix + ".mp4",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


class SignOffOptions(BaseModel):
    confirmed: bool = False


@app.post("/api/projects/{id}/signoff")
def producer_signoff(id: str, options: SignOffOptions):
    """One explicit producer action replacing the itemized review checklist.

    Marks every research source reviewed, records a reuse-responsibility note
    on each linked file, approves each placement using the windows currently
    in the plan, and ticks the four attestations. The producer attests in one
    click; the app verifies nothing and the record says exactly that.
    """
    if not options.confirmed:
        raise HTTPException(422, "Confirm the sign-off to apply it.")
    with LOCK:
        p = project_or_404(id)
        if p.get("is_demo"):
            raise HTTPException(400, "The fictional sample cannot be signed off.")
        e = episode.state(p)
        if not (e.get("guide") or {}).get("cues"):
            raise HTTPException(422, "This project has no editing guide to sign off.")
        assets = {a["id"]: a for a in p.get("assets", [])}
        day = now()[:10]
        note = f"Producer sign-off {day}: responsibility taken in bulk; not independently verified."
        for s in p.get("sources", []):
            s["reviewed"] = True
            if not str(s.get("notes", "")).strip():
                s["notes"] = f"Producer sign-off {day}: bulk confirmation."
        in_use = {b.get("asset_id") for b in (e.get("bindings") or {}).values()}
        in_use |= {p.get("narration_id"), p.get("music_id")}
        # Base images the producer supplied for this episode get the same
        # bulk-responsibility record as other linked files (same explicit click).
        in_use |= {item["id"] for item in episode.basefill.pool(p)}
        for a in p.get("assets", []):
            if a.get("id") in in_use and not str(a.get("license", "")).strip():
                a["license"] = note
        confirmed = 0
        for src in (e.get("guide") or {}).get("sources", []):
            binding = (e.get("bindings") or {}).get(src["id"], {})
            asset = assets.get(binding.get("asset_id"))
            if not asset or asset.get("kind") not in ("image", "video"):
                continue
            if not str(asset.get("license", "")).strip():
                episode.bind_source(p, src["id"], {"license": note})
            episode.bind_source(p, src["id"], {"rights_confirmed": True})
            confirmed += 1
        windows = {}
        for s in p.get("scenes", []):
            if (
                s.get("asset_id")
                and s.get("guide_cue_id")
                and not s.get("base_fill")
                and not s.get("insert_audio")
            ):
                windows.setdefault(
                    s["guide_cue_id"],
                    (float(s.get("trim_start", 0) or 0), s.get("source_crop_end")),
                )
        reviewed, skipped = 0, []
        reviewed_ids = set()
        for cue in e["guide"]["cues"]:
            if cue.get("fill_only"):
                continue
            resolved = episode.resolve_cue(p, cue)
            binding = (
                (episode.state(p).get("bindings") or {}).get(resolved["source_id"], {})
            )
            asset = assets.get(binding.get("asset_id"))
            fields = {"reviewed": True}
            if asset and asset.get("kind") == "video":
                window = windows.get(cue["id"])
                if not window or window[1] is None:
                    skipped.append(cue["id"])
                    continue
                fields["in"] = window[0]
                fields["out"] = window[1]
            try:
                episode.review_cue(p, cue["id"], fields)
                reviewed += 1
                reviewed_ids.add(cue["id"])
            except ValueError:
                skipped.append(cue["id"])
        # A sub-quarter-second lead-in before the first placement is a caption
        # quantization artifact, not missing coverage: start the first approved
        # placement at 0:00 so the final export is not blocked by four frames.
        lead = 0.0
        for s in p.get("scenes", []):
            if s.get("guide_cue_id") or s.get("asset_id"):
                break
            lead += float(s.get("duration", 0))
        lead_in_covered = False
        if 0 < lead <= 0.25:
            first_cue = next(
                (
                    s.get("guide_cue_id")
                    for s in p.get("scenes", [])
                    if s.get("guide_cue_id") in reviewed_ids
                ),
                None,
            )
            if first_cue:
                try:
                    episode.review_cue(p, first_cue, {"narration_start": 0})
                    lead_in_covered = True
                except ValueError:
                    pass
        # One action, complete: rebuild as a reviewed plan (this resets the
        # picture attestation), confirm the timing/transcript review digests,
        # then set the attestations last.
        try:
            episode.build(p, allow_placeholders=True)
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(422, f"Signed-off reviews saved, but the reviewed rebuild failed: {error}")
        e = episode.state(p)
        report = episode.analyze(p)
        if report["has_voice"] and not report["errors"]:
            if report["has_script"] and report["has_guide"]:
                e["timing_reviewed_digest"] = episode.input_digest(p)
            e["transcript_reviewed_digest"] = episode.input_digest(p)
            p["episode"] = e
        p["review"] = {key: True for key in ("facts", "rights", "disclosure", "picture")}
        save_project(p)
        report = editorial.inspect(p)
        blockers = [i["title"] for i in report["issues"] if i.get("blocks_final")]
        return {
            "signed_off": True,
            "sources_confirmed": confirmed,
            "placements_reviewed": reviewed,
            "placements_skipped": skipped,
            "lead_in_covered": lead_in_covered,
            "plan_mode": (p.get("episode") or {}).get("plan", {}).get("mode"),
            "ready_for_final": not blockers,
            "remaining_blockers": blockers,
            "note": note,
        }


@app.get("/api/projects/{id}/jobs")
def get_jobs(id: str):
    project_or_404(id)
    jobs = sorted(
        [copy.deepcopy(j) for j in JOBS.values() if j["project_id"] == id],
        key=lambda j: j["created_at"],
        reverse=True,
    )[:25]
    moment = time.time()
    for j in jobs:  # seconds since each file last moved (for "stalled")
        for f in (j.get("files") or {}).values():
            f["idle"] = round(max(0.0, moment - float(f.get("at") or moment)), 1)
    return jobs


@app.post("/api/jobs/{id}/cancel")
def cancel(id: str):
    if id not in JOBS:
        raise HTTPException(404, "Job not found.")
    if JOBS[id]["status"] not in ("running", "queued"):
        raise HTTPException(400, "This operation has already finished.")
    job_update(
        id,
        cancel_requested=True,
        message="Cancellation requested; waiting for the current step to stop.",
    )
    return JOBS[id]


async def episode_json(request):
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(422, "Send a JSON object.")
    if not isinstance(data, dict):
        raise HTTPException(422, "Send a JSON object.")
    return data


class EpisodeDocument(BaseModel):
    role: Literal["script", "guide", "timings"]
    text: str = Field(max_length=32000000)
    filename: str = Field(default="document.md", max_length=200)


def episode_result(p):
    return {"project": save_project(p), "analysis": episode.analyze(p)}


@app.post("/api/projects/{id}/episode/restore-scene")
async def episode_restore_scene(id: str, request: Request):
    """Undo "Replace picture" on a guide scene: the guide's own choice comes back."""
    body = await episode_json(request)
    with LOCK:
        p = project_or_404(id)
        scene = next((s for s in p["scenes"] if s["id"] == body.get("scene_id")), None)
        if not scene or not (p.get("episode") or {}).get("guide"):
            raise HTTPException(404, "That scene is not part of a guide edit.")
        checkpoint(p, "Restore guide picture")
        ov = p["episode"].setdefault("overrides", {})
        key = episode.scene_key(scene)
        for field in ("asset_id", "trim_start", "replaced", "source_label"):
            (ov.get(key) or {}).pop(field, None)
        if key in ov and not ov[key]:
            del ov[key]
        try:
            episode.build(p, allow_placeholders=True, inspection=True)
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        return save_project(p)


@app.get("/api/projects/{id}/episode")
def episode_analysis(id: str):
    return episode.analyze(project_or_404(id))


@app.post("/api/projects/{id}/episode/import")
def episode_import(id: str, body: EpisodeDocument):
    with LOCK:
        p = project_or_404(id)
        checkpoint(p, "Import guide document")
        try:
            episode.import_document(p, body.role, body.text, body.filename)
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        return episode_result(p)


@app.patch("/api/projects/{id}/episode/source/{source_id}")
async def episode_source(id: str, source_id: str, request: Request):
    body = await episode_json(request)
    with LOCK:
        p = project_or_404(id)
        checkpoint(p, "Link source")
        try:
            episode.bind_source(p, source_id, body)
            episode.resolve_automatic_source_links(p)
            # Auto-rebuild the inspection timeline after a source binding
            # changes, so assigned media is reflected in the plan and the
            # source_label stays aligned with the cue.
            if p.get("episode") and p["episode"].get("guide"):
                try:
                    episode.build(p, allow_placeholders=True, inspection=True)
                except (ValueError, TypeError, KeyError):
                    pass
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        return episode_result(p)


@app.patch("/api/projects/{id}/episode/cue/{cue_id}")
async def episode_cue(id: str, cue_id: str, request: Request):
    body = await episode_json(request)
    with LOCK:
        p = project_or_404(id)
        checkpoint(p, "Review cue")
        try:
            episode.review_cue(p, cue_id, body)
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        return episode_result(p)


@app.patch("/api/projects/{id}/episode/choice/{cue_id}")
async def episode_choice(id: str, cue_id: str, request: Request):
    body = await episode_json(request)
    with LOCK:
        p = project_or_404(id)
        checkpoint(p, "Choose source")
        try:
            episode.choose_source(p, cue_id, body)
            # Auto-rebuild the inspection timeline after a source choice
            # changes, so the selected media is reflected in the plan and the
            # source_label stays aligned with the cue.
            if p.get("episode") and p["episode"].get("guide"):
                try:
                    episode.build(p, allow_placeholders=True, inspection=True)
                except (ValueError, TypeError, KeyError):
                    pass
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        return episode_result(p)


@app.patch("/api/projects/{id}/episode/options")
async def episode_options(id: str, request: Request):
    body = await episode_json(request)
    if not isinstance(body, dict) or set(body) - {
        "brief",
        "narration_id",
        "music_id",
        "music_volume",
        "music",
        "narration_volume",
        "captions",
        "confirm_timing",
        "confirm_transcript",
        "clear_timings",
        "base_fill",
        "base_seed",
        "reshuffle",
        "base_hold",
        "base_label",
    }:
        raise HTTPException(422, "Unsupported episode option.")
    with LOCK:
        p = project_or_404(id)
        checkpoint(p, "Episode options")
        e = copy.deepcopy(episode.state(p))
        if body.get("clear_timings") is True:
            e.pop("timings", None)
            e.pop("timing_reviewed_digest", None)
        if "brief" in body:
            e["brief"] = str(body["brief"])[:5000]
        for role in ("narration_id", "music_id"):
            if role in body:
                asset = next(
                    (
                        a
                        for a in p["assets"]
                        if a["id"] == body[role]
                        and a.get("has_audio", a["kind"] == "audio")
                    ),
                    None,
                )
                if body[role] is not None and not asset:
                    raise HTTPException(
                        422, "Choose an uploaded file with an audio track."
                    )
                if body[role] is not None and body[role] in {
                    b.get("asset_id") for b in e.get("bindings", {}).values()
                }:
                    raise HTTPException(
                        422,
                        "Keep source footage audio muted. Choose a separate finished narration/music file.",
                    )
                if p.get(role) != body[role]:
                    e.pop("timing_reviewed_digest", None)
                    if role == "narration_id":
                        for review in e.get("reviews", {}).values():
                            review.pop("narration_start", None)
                            if "narration_end" in review:
                                review.pop("narration_end", None)
                                review["reviewed"] = False
                p[role] = body[role]
        if p.get("narration_id") and p.get("narration_id") == p.get("music_id"):
            raise HTTPException(422, "Narration and music must be different files.")
        if "music_volume" in body:
            try:
                value = float(body["music_volume"])
                if not __import__("math").isfinite(value) or not 0 <= value <= 0.5:
                    raise ValueError()
                p["music_volume"] = value
            except (TypeError, ValueError):
                raise HTTPException(422, "Music level must be between 0 and 0.5.")
        if "music" in body:  # v0.4.58 placement / loop / fades / ducking (never the timeline)
            if not isinstance(body["music"], dict):
                raise HTTPException(422, "Music settings must be an object.")
            p["music"] = musiclib.normalise(body["music"])
        if "narration_volume" in body:
            try:
                value = float(body["narration_volume"])
                if not 0 <= value <= 2:  # NaN fails the comparison too
                    raise ValueError()
                p["narration_volume"] = round(value, 3)
            except (TypeError, ValueError):
                raise HTTPException(422, "Narration level must be between 0 and 2.")
        if "captions" in body:
            p["captions"] = body["captions"] is True
        base_changed = False
        if "base_fill" in body:
            e["base_fill"] = body["base_fill"] is not False
            base_changed = True
        if "base_label" in body:
            e["base_label"] = body["base_label"] is not False
            base_changed = True
        if "base_hold" in body:
            try:
                hold = float(body["base_hold"])
                if not __import__("math").isfinite(hold) or not 3 <= hold <= 12:
                    raise ValueError()
                e["base_hold"] = hold
            except (TypeError, ValueError):
                raise HTTPException(422, "Longest base-image shot must be 3 to 12 seconds.")
            base_changed = True
        if "base_seed" in body:
            try:
                e["base_seed"] = max(1, min(10**6, int(body["base_seed"])))
            except (TypeError, ValueError):
                raise HTTPException(422, "The base-image shuffle number must be a whole number.")
            base_changed = True
        if body.get("reshuffle") is True:
            e["base_seed"] = int(e.get("base_seed") or 1) + 1
            base_changed = True
        p["episode"] = e
        if base_changed and e.get("guide") and e.get("script"):
            # Rebuild the same kind of plan so the new shuffle/settings show at once.
            mode = (e.get("plan") or {}).get("mode")
            try:
                episode.build(p, allow_placeholders=True, inspection=mode == "inspection")
            except (ValueError, TypeError, KeyError):
                pass
        if body.get("confirm_timing") is True:
            report = episode.analyze(p)
            if (
                not report["has_voice"]
                or report["errors"]
                or not report["has_script"]
                or not report["has_guide"]
            ):
                raise HTTPException(
                    422,
                    "Upload the matching narration and resolve cue matching/timing errors before confirming.",
                )
            e["timing_reviewed_digest"] = episode.input_digest(p)
        elif "confirm_timing" in body:
            e.pop("timing_reviewed_digest", None)
        if body.get("confirm_transcript") is True:
            report = episode.analyze(p)
            if not report["has_voice"] or report["errors"]:
                raise HTTPException(
                    422,
                    "Upload the exact matching narration and resolve timing errors before confirming transcript review.",
                )
            e["transcript_reviewed_digest"] = episode.input_digest(p)
        elif "confirm_transcript" in body:
            e.pop("transcript_reviewed_digest", None)
        p["review"]["picture"] = False
        return episode_result(p)


def link_filenames(p):
    """Bind every unbound guide source whose file name matches (Match filenames)."""
    for source_id, asset_id in episode.suggestions(p).items():
        if not episode.state(p).get("bindings", {}).get(source_id, {}).get("asset_id"):
            episode.bind_source(p, source_id, {"asset_id": asset_id})
    episode.resolve_automatic_source_links(p)


@app.post("/api/projects/{id}/episode/autolink")
def episode_autolink(id: str):
    with LOCK:
        p = project_or_404(id)
        checkpoint(p, "Auto-link sources")
        link_filenames(p)
        return episode_result(p)


# ---------------------------------------------------------------------------
# Fetch from guide (v0.4.19): download the guide's YouTube sources and base
# clips/frames with yt-dlp (or an optional Apify actor), save them under the
# exact names the guide gives, and add them to Footage & photos. Fetching only
# gets files: reuse basis, rights notes and audio clearance stay manual.
# ---------------------------------------------------------------------------

FETCH_NOTICE = (
    "Downloading from YouTube may break YouTube's Terms of Service, and copyright "
    "is a separate question. You are responsible for having the right to download "
    "and use every video. Fetching records where each file came from; it does not "
    "clear rights, record a reuse basis or tick any approval."
)


class FileProgress:
    """Each file's own progress in a fetch job (v0.4.27), saved on the job as
    `files`: {id: {save_as, status, done, total, speed, attempt, error, at}}.
    `at` changes only when something moves, so the page can say "stalled"."""

    def __init__(self, job_progress, items):
        self.job_progress = job_progress
        self.files = {i["id"]: {"save_as": i["save_as"], "status": "waiting", "at": time.time()} for i in items}
        self.lock = threading.Lock()
        self.last = 0.0
        self.message = "Starting"
        self.pct = 0

    def __call__(self, item_id, **state):
        with self.lock:
            f = self.files.get(item_id)
            if f is None:
                return
            before = (f.get("status"), f.get("done"), f.get("phase"), f.get("secs"))
            if state.get("status") != "downloading" or "attempt" in state:
                for k in ("done", "total", "speed", "phase", "part", "secs", "secs_total"):
                    f.pop(k, None)
            if (state.get("done") is not None or state.get("secs") is not None) and "phase" not in state and f.get("phase") == "starting":
                f.pop("phase", None)  # bytes are moving: "starting" is over
            f.update({k: v for k, v in state.items() if v is not None})
            if state.get("status") == "failed":
                f.pop("speed", None)
            if (f.get("status"), f.get("done"), f.get("phase"), f.get("secs")) != before:
                f["at"] = time.time()
            changed = f["status"] != before[0]
            now_ = time.time()
            if changed or now_ - self.last > 0.4:
                self.last = now_
                self.job_progress(self.pct, self.message, files=copy.deepcopy(self.files))

    def overall(self, pct, message):
        with self.lock:
            self.pct, self.message = pct, message
            self.job_progress(pct, message, files=copy.deepcopy(self.files))

    def finish(self):
        with self.lock:
            for f in self.files.values():
                if f["status"] in ("waiting", "downloading", "saving"):
                    f.update(status="stopped", at=time.time())
            return copy.deepcopy(self.files)


def fetch_downloaders(request, body=None):
    body = body or {}
    cfg = SESSIONS.setdefault(request.state.session, {})
    if str(body.get("apify_token") or "").strip():
        cfg["apify_token"] = str(body["apify_token"]).strip()[:200]
    if str(body.get("apify_actor") or "").strip():
        cfg["apify_actor"] = str(body["apify_actor"]).strip()[:120]
    try:
        height = min(2160, max(360, int(body.get("max_height") or fetcher.DEFAULT_HEIGHT)))
    except (TypeError, ValueError):
        height = fetcher.DEFAULT_HEIGHT
    return {
        "yt-dlp": fetcher.YtDlp(max_height=height),
        "apify": fetcher.Apify(cfg.get("apify_token"), cfg.get("apify_actor")),
    }


@app.get("/api/projects/{id}/fetch")
def fetch_plan(id: str, request: Request):
    p = project_or_404(id)
    plan = fetcher.plan(p, include_unused=request.query_params.get("include_unused") == "1")
    downloaders = fetch_downloaders(request)
    cfg = SESSIONS.get(request.state.session, {})
    return {
        **plan,
        "backends": {name: d.status() for name, d in downloaders.items()},
        "apify_actor": downloaders["apify"].actor,
        "apify_token_saved": bool(cfg.get("apify_token") or os.environ.get("APIFY_TOKEN")),
        "notice": FETCH_NOTICE,
        "acknowledged": bool((p.get("episode") or {}).get("fetch_ack")),
    }


def import_fetched(id, path, item, record):
    """Add one fetched file to the project exactly as an upload would."""
    folder = DATA / "media" / id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    stored = folder / (uid() + suffix)
    shutil.move(str(path), stored)
    asset = {
        "id": uid(),
        "name": item["save_as"][:180],
        "path": asset_reference(stored),
        "url": f"/media/{id}/{stored.name}",
        "size": stored.stat().st_size,
        "generated": False,
        "license": "",
        "thumbnail": None,
        "fetched": record,
    }
    try:
        if suffix in (".png", ".jpg", ".jpeg", ".webp"):
            with Image.open(stored) as image:
                image = ImageOps.exif_transpose(image)
                image.load()
                asset.update(kind="image", width=image.width, height=image.height, duration=0, has_audio=False)
                thumb = folder / (stored.stem + "-thumb.jpg")
                ImageOps.fit(image.convert("RGB"), (480, 270)).save(thumb, quality=82)
            asset["thumbnail"] = f"/media/{id}/{thumb.name}"
        else:
            info = renderer.probe(stored)
            if not info["has_video"]:
                raise ValueError("The download has no picture.")
            asset.update(info, kind="video")
            thumb = folder / (stored.stem + "-thumb.jpg")
            renderer.thumbnail(stored, thumb)
            asset["thumbnail"] = f"/media/{id}/{thumb.name}"
            if info["has_audio"]:
                asset["waveform"] = renderer.waveform(stored)
    except Exception:
        stored.unlink(missing_ok=True)
        raise
    with LOCK:
        p = project_or_404(id)
        if any(a.get("name", "").lower() == asset["name"].lower() for a in p["assets"]):
            stored.unlink(missing_ok=True)
            raise ValueError(f"{asset['name']} is already in the project; kept the existing file.")
        p["assets"].append(asset)
        if not p.get("episode"):
            p["episode"] = copy.deepcopy(episode.state(p))
        save_project(p)
    return asset


# ---------------------------------------------------------------------------
# Case Desk (v0.4.20): the script workflow's gates, checked in code, plus free
# YouTube footage discovery. No AI model and no paid service is used here.
# ---------------------------------------------------------------------------

DESK_LOCK = threading.Lock()


def desk_view(id):
    project_or_404(id)
    view = casedesk.analyze(casedesk.load(DATA, id))
    setup = view["setup"]
    view["suggested_searches"] = discovery.suggest(view["case"]["name"], setup["victims"], setup["suspects"])
    view["search_ready"] = bool(discovery.binary())
    view["kinds"] = list(discovery.KINDS)
    return view


@app.get("/api/projects/{id}/casedesk")
def desk_get(id: str):
    return desk_view(id)


@app.patch("/api/projects/{id}/casedesk/case")
async def desk_case(id: str, request: Request):
    body = await episode_json(request)
    project_or_404(id)
    with DESK_LOCK:
        state = casedesk.load(DATA, id)
        for key in ("name", "channel"):
            if key in body:
                state["case"][key] = str(body[key])[:200]
        for key, low, high in (("target_words", 100, 20000), ("wpm", 90, 220)):
            if key in body:
                try:
                    state["case"][key] = min(high, max(low, int(body[key])))
                except (TypeError, ValueError):
                    raise HTTPException(422, f"{key} must be a number.")
        casedesk.save(DATA, id, state)
    return desk_view(id)


@app.post("/api/projects/{id}/casedesk/gate/{gate}")
async def desk_submit(id: str, gate: str, request: Request):
    body = await episode_json(request)
    project_or_404(id)
    try:
        with DESK_LOCK:
            state = casedesk.load(DATA, id)
            if "text" in body:
                state = casedesk.submit(state, gate, str(body.get("text") or ""), str(body.get("filename") or ""), body.get("chapter"))
            if "review" in body:
                state = casedesk.submit_review(state, gate, str(body.get("review") or ""), body.get("chapter"))
            if body.get("status"):
                state = casedesk.set_status(state, gate, str(body["status"]), body.get("chapter"), str(body.get("override") or ""))
            casedesk.save(DATA, id, state)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    return desk_view(id)


@app.post("/api/projects/{id}/casedesk/packet")
async def desk_packet(id: str, request: Request):
    body = await episode_json(request)
    project_or_404(id)
    try:
        if body.get("kind") == "reviewer_prompt":
            return {"text": casedesk.prompt("gate_reviewer.md")}
        if body.get("kind") == "sources":
            return {"text": casedesk.sources_block(casedesk.load(DATA, id)) or "No approved uploads yet."}
        if body.get("kind") == "editor_script":
            state = casedesk.load(DATA, id)
            text = state["gates"]["G8"]["text"] or state["gates"]["G7"]["text"]
            if not text:
                raise ValueError("Paste the locked script at gate 8 first.")
            return {"text": casedesk.editor_script(text)}
        return {"text": casedesk.packet(casedesk.load(DATA, id), str(body.get("gate")), str(body.get("kind")), body.get("chapter"))}
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(422, str(e) or "Unknown packet.")


@app.post("/api/projects/{id}/casedesk/search")
async def desk_search(id: str, request: Request):
    body = await episode_json(request)
    project_or_404(id)
    queries = [re.sub(r"\s+", " ", str(q)).strip()[:120] for q in (body.get("queries") or []) if str(q).strip()][:24]
    if not queries:
        raise HTTPException(422, "Type at least one search phrase.")
    if not discovery.binary():
        raise HTTPException(422, "yt-dlp is not installed in this container. Rebuild the Docker image.")
    try:
        per = min(40, max(5, int(body.get("per_query") or 15)))
    except (TypeError, ValueError):
        per = 15

    def work(progress, cancelled):
        added, errors = 0, []
        for i, q in enumerate(queries):
            if cancelled():
                break
            progress(int(95 * i / len(queries)), f"Searching YouTube: {q}")
            try:
                found = discovery.search(q, per)
            except Exception as e:
                errors.append(f"{q}: {str(e)[:200]}")
                continue
            with DESK_LOCK:
                state = casedesk.load(DATA, id)
                setup = casedesk.context(state)["setup"]
                terms = [w for n in setup["victims"] + setup["suspects"] for w in n.split() if len(w) > 2]
                added += discovery.merge(state["candidates"], found, q, terms)
                state["searches"].append({"query": q, "found": len(found), "at": casedesk.now()})
                casedesk.save(DATA, id, state)
        return {"added": added, "errors": errors,
                "summary": f"{added} new videos from {len(queries)} searches" + (f"; {len(errors)} searches failed." if errors else ".")}

    return spawn(id, "discovery", work)


@app.patch("/api/projects/{id}/casedesk/candidate/{vid}")
async def desk_candidate(id: str, vid: str, request: Request):
    body = await episode_json(request)
    project_or_404(id)
    try:
        with DESK_LOCK:
            state = casedesk.load(DATA, id)
            c = discovery.decide(state["candidates"], vid, body.get("status"), body.get("kind"), body.get("note"))
            if body.get("inspect") and not c.get("upload_date"):
                try:
                    c.update(discovery.details(vid))
                except Exception as e:
                    c["inspect_error"] = str(e)[:200]
            casedesk.save(DATA, id, state)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return desk_view(id)


# ---------------------------------------------------------------------------
# Voice and timing (v0.4.21). Two choices each, in every mode:
#   voice  = upload your own recording, OR generate it in your cloned voice
#            with a local speech server (VoiceStudio);
#   timing = upload CapCut's SRT/JSON, OR let local Whisper hear the audio and
#            take the spelling from the script.
# Everything generated can be downloaded. Nothing here uses a paid service.
# ---------------------------------------------------------------------------


def narration_sources(p, id):
    desk = casedesk.load(DATA, id)
    locked = desk["gates"]["G8"]["text"] or desk["gates"]["G7"]["text"]
    out = {}
    if locked:
        out["locked"] = voicegen.spoken_text(casedesk.editor_script(locked))
    script = ((p.get("episode") or {}).get("script") or {}).get("text") or ""
    if script.strip():
        out["script"] = voicegen.spoken_text(script)
    return {k: v for k, v in out.items() if v.strip()}


def voice_server(id):
    cfg = casedesk.load(DATA, id)["voice"]
    return voicegen.SpeechServer(cfg["base"] or None, cfg["key"] or None, cfg["model"] or None, cfg["voice"] or None), cfg


def voice_view(id):
    p = project_or_404(id)
    server, cfg = voice_server(id)
    status = server.status()
    sources = narration_sources(p, id)
    narration = next((a for a in p["assets"] if a["id"] == p.get("narration_id")), None)
    desk = casedesk.load(DATA, id)
    timing = (p.get("episode") or {}).get("timings")
    return {
        "server": status,
        "voices": server.voices() if status["ready"] else [],
        "settings": {"base": cfg["base"] or voicegen.DEFAULT_BASE, "model": cfg["model"], "voice": cfg["voice"], "key_saved": bool(cfg["key"] or os.environ.get("OMNIVOICE_API_KEY"))},
        "sources": {k: {"words": len(v.split()), "preview": v[:160]} for k, v in sources.items()},
        "narration": {"name": narration["name"], "url": f"/api/projects/{id}/voice/file/narration", "duration": narration.get("duration"), "generated": bool(narration.get("voiced"))} if narration else None,
        "whisper": {"ready": autotiming.available(), "models": list(autotiming.MODELS), "error": autotiming.unavailable_reason()},
        "has_timing": bool(timing),
        "made_timing": desk["timing"] or None,
        "colab": colab_view(id, desk),
    }


def colab_view(id, desk):
    c = desk["colab"]
    sample = DATA / "media" / id / "voice" / "sample.wav"
    pack = DATA / "media" / id / "voice" / "pack.zip"
    return {
        "settings": colabvoice.settings(c.get("emotion"), c.get("pace"), c.get("seed")),
        "sample": {"name": c.get("sample") or "your clip", "seconds": c.get("sample_seconds") or 0,
                   "url": f"/api/projects/{id}/voice/colab/sample.wav"} if sample.is_file() else None,
        "pack": {"url": f"/api/projects/{id}/voice/colab/pack.zip", **(c.get("pack") or {})} if pack.is_file() else None,
        "notebook_url": "/api/voice/colab-notebook",
    }


@app.get("/api/projects/{id}/voice")
def voice_get(id: str):
    return voice_view(id)


@app.patch("/api/projects/{id}/voice")
async def voice_settings(id: str, request: Request):
    body = await episode_json(request)
    project_or_404(id)
    with DESK_LOCK:
        state = casedesk.load(DATA, id)
        if any(k in body for k in ("emotion", "pace", "seed")):
            c = state["colab"]
            c.update(colabvoice.settings(body.get("emotion", c.get("emotion")), body.get("pace", c.get("pace")), body.get("seed", c.get("seed"))))
        for key in ("base", "model", "voice", "key"):
            if key in body:
                value = str(body[key] or "").strip()[:300]
                if key == "base" and value and urlparse(value).scheme not in ("http", "https"):
                    raise HTTPException(422, "The voice server address must start with http:// or https://.")
                state["voice"][key] = value
        casedesk.save(DATA, id, state)
    return voice_view(id)


def import_audio(id, path, name, extra):
    folder = DATA / "media" / id
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / (uid() + path.suffix.lower())
    shutil.move(str(path), stored)
    info = renderer.probe(stored)
    if not info["has_audio"]:
        stored.unlink(missing_ok=True)
        raise ValueError("The generated file has no sound.")
    with LOCK:
        p = project_or_404(id)
        names = {a["name"] for a in p["assets"]}
        base, n, final = Path(name).stem, 1, name
        while final in names:
            n += 1
            final = f"{base}-{n}{Path(name).suffix}"
        asset = {"id": uid(), "name": final, "path": asset_reference(stored), "url": f"/media/{id}/{stored.name}",
                 "size": stored.stat().st_size, "generated": False, "license": "", "thumbnail": None,
                 "kind": "audio", **info, "waveform": renderer.waveform(stored), **extra}
        p["assets"].append(asset)
        e = p.setdefault("episode", copy.deepcopy(episode.state(p)))
        if p.get("narration_id") != asset["id"]:
            e.pop("timing_reviewed_digest", None)
            for review in e.get("reviews", {}).values():
                review.pop("narration_start", None)
                if "narration_end" in review:
                    review.pop("narration_end", None)
                    review["reviewed"] = False
        p["narration_id"] = asset["id"]
        save_project(p)
    return asset


@app.get("/api/projects/{id}/voice/file/{name}")
def voice_file(id: str, name: str):
    """Download the narration audio or a timing file under a plain name."""
    p = project_or_404(id)
    if name == "narration":
        a = next((a for a in p["assets"] if a["id"] == p.get("narration_id")), None)
        if not a:
            raise HTTPException(404, "This project has no narration audio yet.")
        return FileResponse(renderer.asset_path(a), filename=a["name"])
    if name not in ("captions.srt", "word_timings.json", "differences.txt"):
        raise HTTPException(404, "Unknown file.")
    path = DATA / "media" / id / "timing" / name
    if not path.is_file():
        raise HTTPException(404, "Make the timing first.")
    return FileResponse(path, filename=name)


@app.post("/api/projects/{id}/voice/generate")
async def voice_generate(id: str, request: Request):
    body = await episode_json(request)
    p = project_or_404(id)
    source = str(body.get("source") or "")
    if source == "text":
        text = voicegen.spoken_text(str(body.get("text") or "")[:200000])
    else:
        text = narration_sources(p, id).get(source, "")
    if not text.strip():
        raise HTTPException(422, "There is no narration text to read. Lock the script in the Case desk, add the script in Episode setup, or paste the narration.")
    server, cfg = voice_server(id)
    if not server.voice:
        raise HTTPException(422, "Choose which voice to use first.")
    ready = server.status()
    if not ready["ready"]:
        raise HTTPException(422, ready["detail"])

    def work(progress, cancelled):
        work_dir = DATA / "fetch-work" / f"voice-{id}"
        try:
            out = work_dir / "narration.mp3"
            made = voicegen.narrate(text, server, work_dir, out, progress, cancelled)
            progress(97, "Adding the narration to the project")
            asset = import_audio(id, out, "narration-cloned-voice.mp3",
                                 {"voiced": {"voice": server.voice, "model": server.model, "at": now(), "words": made["words"], "source": source}})
        except voicegen.VoiceError as e:
            raise RuntimeError(str(e))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        secs = round(made["seconds"])
        return {"asset_id": asset["id"], "name": asset["name"], "url": asset["url"], "seconds": made["seconds"],
                "summary": f"Narration made: {secs // 60}:{secs % 60:02d}, {made['words']} words. It is set as this project's narration."}

    return spawn(id, "voice", work)


@app.post("/api/projects/{id}/voice/timing")
async def voice_timing(id: str, request: Request):
    body = await episode_json(request)
    p = project_or_404(id)
    narration = next((a for a in p["assets"] if a["id"] == p.get("narration_id")), None)
    if not narration:
        raise HTTPException(422, "Add the narration audio first: upload your recording or generate it.")
    sources = narration_sources(p, id)
    script = sources.get("script") or sources.get("locked") or ""
    if not script.strip():
        raise HTTPException(422, "Add the script first, so the timing can use its spelling.")
    if not autotiming.available():
        raise HTTPException(422, "Whisper cannot load in this container (" + (autotiming.unavailable_reason() or "not installed")
                            + "). Rebuild the Docker image, or upload the SRT and JSON from CapCut.")
    return start_timing(id, narration, script, str(body.get("model") or "base.en"), body.get("apply") is not False)


def start_timing(id, narration, script, model="base.en", apply=True):
    def work(progress, cancelled):
        heard = autotiming.transcribe(renderer.asset_path(narration), model, str(DATA / "models"), progress, cancelled)
        words, report = autotiming.align(script, heard)
        if report["match"] < 0.6:
            raise RuntimeError(f"Only {report['match'] * 100:.0f}% of the script was heard in this audio. Is it the right recording for this script?")
        folder = DATA / "media" / id / "timing"
        folder.mkdir(parents=True, exist_ok=True)
        srt, js = autotiming.to_srt(words), autotiming.to_json(words)
        (folder / "captions.srt").write_text(srt, encoding="utf-8")
        (folder / "word_timings.json").write_text(js, encoding="utf-8")
        (folder / "differences.txt").write_text(autotiming.differences_text(report), encoding="utf-8")
        applied = False
        if apply:
            progress(96, "Loading the timing into the project")
            with LOCK:
                latest = project_or_404(id)
                episode.import_document(latest, "timings", js, "whisper_word_timings.json")
                episode.import_document(latest, "timings", srt, "whisper_captions.srt")
                save_project(latest)
            applied = True
        made = {"at": now(), "model": model, "match": report["match"], "differences": report["difference_count"],
                "duration": report["duration"], "applied": applied, "narration": narration["name"],
                "files": {k: f"/api/projects/{id}/voice/file/{k}" for k in ("captions.srt", "word_timings.json", "differences.txt")},
                "examples": report["differences"][:8]}
        with DESK_LOCK:
            state = casedesk.load(DATA, id)
            state["timing"] = made
            casedesk.save(DATA, id, state)
        return {**made, "summary": f"Timing made: {report['match'] * 100:.0f}% of the script matched, {report['difference_count']} places to check."
                + (" Loaded into the project." if applied else "")}

    return spawn(id, "timing", work)


# ---------------------------------------------------------------------------
# Free Google Colab (v0.4.23): Casefile makes a voice pack, the Colab notebook
# makes the MP3 on Google's free GPU, and the MP3 comes back here. Casefile
# never connects to Colab itself (the free tier forbids that).
# ---------------------------------------------------------------------------


@app.get("/api/voice/colab-notebook")
def colab_notebook():
    return PlainTextResponse(json.dumps(colabvoice.notebook(), indent=1, ensure_ascii=False), media_type="application/x-ipynb+json",
                    headers={"Content-Disposition": f'attachment; filename="{colabvoice.NOTEBOOK_NAME}"'})


@app.post("/api/projects/{id}/voice/colab/sample")
async def colab_sample(id: str, files: list[UploadFile] = File(...)):
    project_or_404(id)
    file = files[0]
    folder = DATA / "media" / id / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / ("upload" + (Path(file.filename or "").suffix.lower()[:6] or ".bin"))
    with raw.open("wb") as out:
        size = 0
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > 60 << 20:
                raw.unlink(missing_ok=True)
                raise HTTPException(422, "The voice clip is too big. 10 to 20 seconds of audio is all it needs.")
            out.write(chunk)
    try:
        seconds = colabvoice.prepare_sample(raw, folder / "sample.wav")
    except colabvoice.ColabError as e:
        raise HTTPException(422, str(e))
    finally:
        raw.unlink(missing_ok=True)
    with DESK_LOCK:
        state = casedesk.load(DATA, id)
        state["colab"].update(sample=Path(file.filename or "voice clip").name[:120], sample_seconds=round(seconds, 1))
        casedesk.save(DATA, id, state)
    return voice_view(id)


@app.post("/api/projects/{id}/voice/colab/pack")
async def colab_pack(id: str, request: Request):
    body = await episode_json(request)
    p = project_or_404(id)
    source = body.get("source") or "script"
    if source == "text":
        text = str(body.get("text") or "")[:300000]
    else:
        text = narration_sources(p, id).get(source, "")
    desk = casedesk.load(DATA, id)
    folder = DATA / "media" / id / "voice"
    try:
        data, meta = colabvoice.make_pack(text, folder / "sample.wav", desk["colab"], p.get("title") or "")
    except colabvoice.ColabError as e:
        raise HTTPException(422, str(e))
    tmp = folder / "pack.zip.part"
    tmp.write_bytes(data)
    tmp.replace(folder / "pack.zip")
    with DESK_LOCK:
        state = casedesk.load(DATA, id)
        state["colab"]["pack"] = {"at": now(), "source": source, "words": meta["words"], "parts": meta["parts"], "minutes": meta["minutes"]}
        casedesk.save(DATA, id, state)
    return voice_view(id)


@app.get("/api/projects/{id}/voice/colab/{name}")
def colab_file(id: str, name: str):
    p = project_or_404(id)
    if name not in ("sample.wav", "pack.zip"):
        raise HTTPException(404, "Unknown file.")
    path = DATA / "media" / id / "voice" / name
    if not path.is_file():
        raise HTTPException(404, "Not made yet.")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", p.get("title") or "casefile").strip("-")[:60] or "casefile"
    return FileResponse(path, filename=f"{stem}-voice-pack.zip" if name == "pack.zip" else f"{stem}-voice-sample.wav")


@app.post("/api/projects/{id}/voice/colab/result")
async def colab_result(id: str, files: list[UploadFile] = File(...), model: str = Form(default="base.en")):
    """The MP3 from Colab becomes the narration; then the timing is made."""
    project_or_404(id)
    file = files[0]
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".mp3", ".wav", ".m4a"):
        raise HTTPException(422, "Choose the MP3 that Colab downloaded.")
    work_dir = DATA / "fetch-work" / f"voice-{id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    tmp = work_dir / ("colab" + suffix)
    with tmp.open("wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    desk = casedesk.load(DATA, id)
    try:
        asset = import_audio(id, tmp, "narration-cloned-voice" + suffix,
                             {"voiced": {"voice": "your clip on Colab (Chatterbox)", "model": "chatterbox", "at": now(),
                                         "words": (desk["colab"].get("pack") or {}).get("words"), "source": "colab"}})
    except ValueError as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(422, str(e))
    p = project_or_404(id)
    sources = narration_sources(p, id)
    script = sources.get("script") or sources.get("locked") or ""
    if script.strip() and autotiming.available():
        started = start_timing(id, asset, script, model if model in autotiming.MODELS else "base.en", True)
        return {**voice_view(id), "job_id": started["job_id"], "timing_started": True}
    return {**voice_view(id), "timing_started": False,
            "timing_note": "Add the script first, then use Make the timing." if not script.strip() else "Whisper is not installed in this container; upload the CapCut SRT/JSON instead."}


# ---------------------------------------------------------------------------
# Re-cut (v0.4.22): replace narrated quotes in a finished video with the
# original clips and their own sound. The narrated stretch is skipped.
# ---------------------------------------------------------------------------


def recut_sources(p):
    """Guide source IDs mapped to their linked video files."""
    e = p.get("episode") or {}
    assets = {a["id"]: a for a in p.get("assets", [])}
    out = {}
    for sid, b in (e.get("bindings") or {}).items():
        a = assets.get(b.get("asset_id"))
        if a and a.get("kind") == "video":
            out[sid] = a
    for a in p.get("assets", []):
        m = re.match(r"^([A-Z]{1,3}\d{1,3})(?![A-Za-z0-9])", a.get("name", ""))
        if m and a.get("kind") == "video" and m.group(1) not in out:
            out[m.group(1)] = a
    return out


def recut_view(id):
    p = project_or_404(id)
    desk = casedesk.load(DATA, id)
    sources = recut_sources(p)
    bound = {b.get("asset_id") for b in ((p.get("episode") or {}).get("bindings") or {}).values()}
    videos = [{"kind": "export", "id": x["id"], "label": f"Rendered {x['created_at'][:16].replace('T', ' ')}" + (" (draft)" if x.get("draft") else ""), "duration": x.get("duration")}
              for x in p.get("exports", []) if (DATA / "exports" / x["id"] / "documentary.mp4").exists()]
    videos += [{"kind": "recut", "id": r["id"], "label": f"Re-cut {r['at'][:16].replace('T', ' ')}", "duration": r.get("duration")} for r in desk["recuts"]
               if (DATA / "media" / id / "recut" / f"{r['id']}.mp4").exists()]
    videos += [{"kind": "asset", "id": a["id"], "label": "Uploaded: " + a["name"], "duration": a.get("duration")}
               for a in p.get("assets", []) if a.get("kind") == "video" and a.get("has_audio") and a["id"] not in bound and not a["name"].upper().startswith("BASE-")
               and not re.match(r"^[A-Z]{1,3}\d{1,3}(?![A-Za-z0-9])", a["name"])]
    return {
        "videos": videos,
        "sources": [{"id": sid, "name": a["name"], "duration": a.get("duration"), "has_audio": bool(a.get("has_audio")), "url": a.get("url"),
                     "thumbnail": a.get("thumbnail")} for sid, a in sorted(sources.items())],
        "list": desk["recut_list"],
        "inserts": recut_inserts(desk["recut_list"], sources),
        "fetch": recut_fetch_items(p, desk["recut_list"], sources),
        "fetch_notice": FETCH_NOTICE,
        "fetch_acknowledged": bool((p.get("episode") or {}).get("fetch_ack") or desk.get("fetch_ack")),
        "recuts": [{**r, "url": f"/api/projects/{id}/recut/file/{r['id']}"} for r in desk["recuts"]],
    }


def recut_inserts(text, sources):
    out = []
    for ins in recut.parse(text) if text.strip() else []:
        a = sources.get(ins["source_id"])
        out.append({**ins, "file": a["name"] if a else None, "file_has_audio": bool(a and a.get("has_audio")),
                    "file_duration": a.get("duration") if a else None})
    return out


def recut_cutaways(p, raw_inserts, auto=True):
    """v0.4.38 The picture cutaways each insert will get: planned rows from the
    re-cut list first, else automatic ones on clips of 12 s or more. Pictures
    rotate across the whole re-cut. raw_inserts: dicts with start, end, who,
    words, cutaways (planned), card (bool), off (indexes), pick {index: asset id}."""
    setup = ((p.get("episode") or {}).get("guide") or {}).get("setup") or {}
    avoid = set(setup.get("avoid_tags") or [])
    pool = [i for i in basefill.pool(p) if not avoid.intersection(i["tags"])]
    sources = recut_sources(p)
    assets = {x["id"]: x for x in p.get("assets", [])}
    victim, suspect = " ".join(setup.get("victims") or []), " ".join(setup.get("suspects") or [])
    used, out = {}, []
    for raw in raw_inserts:
        try:
            length = float(raw["end"]) - float(raw["start"])
        except (KeyError, TypeError, ValueError):
            out.append({"cutaways": [], "warnings": [], "auto": False})
            continue
        planned = [c for c in raw.get("cutaways") or [] if isinstance(c, dict) and isinstance(c.get("show"), dict)]
        is_auto = not planned and bool(auto)
        plan = planned if planned else cutaways.auto_plan(length, raw.get("who", ""), raw.get("words", ""), victim, suspect, bool(raw.get("card"))) if auto else []
        plan, warnings = cutaways.clean([{"from": float(c["from"]), "to": float(c["to"]), "show": c["show"], "label": c.get("label") or cutaways.show_label(c["show"]),
                                          **({k: c[k] for k in ("auto", "alts", "why") if c.get(k)})} for c in plan], length, raw.get("who", ""))
        picks = raw.get("pick") or {}
        off = {int(x) for x in raw.get("off") or [] if str(x).lstrip("-").isdigit()}
        for n, c in enumerate(plan):
            c["n"] = n
            chosen = picks.get(str(n)) or picks.get(n)
            if chosen and chosen in assets:
                c["show"] = {"kind": "asset", "asset_id": chosen, "name": assets[chosen]["name"]}
        plan = [c for c in plan if c["n"] not in off]
        done, more = cutaways.resolve(plan, pool, sources, used, lambda a: renderer.asset_path(assets[a["id"]]))
        out.append({"cutaways": done, "warnings": warnings + more, "auto": is_auto, "speaker": cutaways.speaker(raw.get("who", ""), suspect),
                    "why": next((c["why"] for c in plan if c.get("why")), ""),
                    "off": sorted(off), "length": round(length, 3)})
    return out


@app.post("/api/projects/{id}/recut/cutaways")
async def recut_cutaways_preview(id: str, request: Request):
    body = await episode_json(request)
    p = project_or_404(id)
    plans = recut_cutaways(p, body.get("inserts") or [], body.get("auto", True) is not False)
    pool = [{"id": i["id"], "name": i["name"], "bucket": i["bucket"], "kind": i["kind"]} for i in basefill.pool(p)]
    for i in pool:
        x = next((x for x in p.get("assets", []) if x["id"] == i["id"]), {})
        i["thumb"] = x.get("thumbnail") or (x.get("url") if x.get("kind") == "image" else None)
    for plan in plans:
        for c in plan["cutaways"]:
            c.pop("path", None)
            x = next((x for x in p.get("assets", []) if x["id"] == c.get("asset_id")), None) or {}
            c["thumb"] = x.get("thumbnail") or (x.get("url") if x.get("kind") == "image" else None)
    return {"plans": plans, "pictures": pool}


@app.get("/api/projects/{id}/recut")
def recut_get(id: str):
    return recut_view(id)


def recut_fetch_items(p, text, sources):
    guide = (p.get("episode") or {}).get("guide") or {}
    links = {s["id"]: fetcher.youtube_id(s.get("url")) for s in guide.get("sources", []) if fetcher.youtube_id(s.get("url"))}
    return recut.fetch_items(recut.parse(text) if text.strip() else [], set(sources), links)


@app.get("/api/projects/{id}/name-cards")
def name_card_suggestions(id: str):
    """People for automatic name cards (v0.4.30): the re-cut list's Who column,
    one per clip ID, and which clips the edit uses. Nothing is applied here."""
    p = project_or_404(id)
    desk = casedesk.load(DATA, id)
    found = {}
    for ins in recut.parse(desk["recut_list"]) if desk["recut_list"].strip() else []:
        if ins.get("source_id") and ins.get("who") and ins["source_id"] not in found:
            found[ins["source_id"]] = {**effects.split_who(ins["who"]), "from": "re-cut list"}
    used = sorted({effects.scene_source(s) for s in p.get("scenes", []) if effects.scene_source(s)})
    guide = {s["id"]: s.get("title", "") for s in ((p.get("episode") or {}).get("guide") or {}).get("sources", [])}
    return {
        "suggested": found,
        "used": [{"id": sid, "title": guide.get(sid, "")} for sid in used],
        "current": effects.normalise_name_cards(p.get("name_cards")),
    }


@app.post("/api/projects/{id}/recut/fetch")
async def recut_fetch(id: str, request: Request):
    """Download the clips the re-cut list needs, named S01.mp4 and so on."""
    body = await episode_json(request)
    p = project_or_404(id)
    downloaders = fetch_downloaders(request, body)
    desk = casedesk.load(DATA, id)
    if not body.get("confirm_responsibility") and not ((p.get("episode") or {}).get("fetch_ack") or desk.get("fetch_ack")):
        raise HTTPException(422, "Read and accept the download notice first. " + FETCH_NOTICE)
    name = body.get("backend") or "yt-dlp"
    if name not in ("yt-dlp", "apify"):
        raise HTTPException(422, "Choose yt-dlp or apify.")
    downloader = downloaders[name]
    ready = downloader.status()
    if not ready["ready"]:
        raise HTTPException(422, ready["detail"])
    plan = recut_fetch_items(p, desk["recut_list"], recut_sources(p))
    only = {str(x) for x in (body.get("only") or [])}
    items = [i for i in plan if i["status"] == "todo" and (not only or i["id"] in only)]
    if not items:
        manual = [i["id"] for i in plan if i["status"] == "manual"]
        raise HTTPException(422, "Nothing to fetch: " + (
            f"{', '.join(manual)} {'has' if len(manual) == 1 else 'have'} no YouTube link; upload {'it' if len(manual) == 1 else 'them'} by hand." if manual
            else "every clip in the list is already in the project." if plan else "load the re-cut list first."))
    with DESK_LOCK:
        state = casedesk.load(DATA, id)
        state["fetch_ack"] = state.get("fetch_ack") or {"at": now(), "notice": FETCH_NOTICE}
        casedesk.save(DATA, id, state)

    def work(progress, cancelled):
        work_dir = DATA / "fetch-work" / f"recut-{id}"
        files = FileProgress(progress, items)
        try:
            results = fetcher.run(
                items, downloader, work_dir,
                lambda path, item, record: import_fetched(id, path, item, record),
                lambda pct, msg: files.overall(min(95, pct), msg), cancelled,
                on_status=files,
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            progress(96, "Finishing", files=files.finish())
        ok = [r for r in results if r["ok"]]
        if ok and (project_or_404(id).get("episode") or {}).get("guide"):
            with LOCK:
                latest = project_or_404(id)
                try:
                    link_filenames(latest)
                    save_project(latest)
                except (ValueError, TypeError, KeyError):
                    pass
        failed = [r for r in results if not r["ok"]]
        return {"results": results, "fetched": len(ok), "failed": len(failed),
                "summary": f"Fetched {len(ok)} of {len(results)} clips" + (f"; {len(failed)} failed (see the list)." if failed else ".")}

    return spawn(id, "clip-fetch", work)


@app.post("/api/projects/{id}/recut/list")
async def recut_list(id: str, request: Request):
    body = await episode_json(request)
    project_or_404(id)
    with DESK_LOCK:
        state = casedesk.load(DATA, id)
        state["recut_list"] = str(body.get("text") or "")[:100000]
        casedesk.save(DATA, id, state)
    view = recut_view(id)
    if state["recut_list"].strip() and not view["inserts"]:
        raise HTTPException(422, "No inserts could be read from that list. It needs a table of cut points and a table of clips with their windows, or add the inserts by hand.")
    return view


def recut_base(p, id, video):
    kind, vid = str((video or {}).get("kind")), str((video or {}).get("id"))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", vid):
        raise HTTPException(422, "Choose the video to re-cut.")
    if kind == "export" and any(x["id"] == vid for x in p.get("exports", [])):
        path = DATA / "exports" / vid / "documentary.mp4"
    elif kind == "recut":
        path = DATA / "media" / id / "recut" / f"{vid}.mp4"
    elif kind == "asset" and any(a["id"] == vid for a in p["assets"]):
        path = renderer.asset_path(next(a for a in p["assets"] if a["id"] == vid))
    else:
        raise HTTPException(422, "Choose the video to re-cut.")
    if not Path(path).is_file():
        raise HTTPException(422, "That video file is no longer on disk. Render it again or upload it.")
    return Path(path)


@app.post("/api/projects/{id}/recut/render")
async def recut_render(id: str, request: Request):
    body = await episode_json(request)
    p = project_or_404(id)
    base = recut_base(p, id, body.get("video"))
    sources = recut_sources(p)
    inserts, raws = [], []
    for n, raw in enumerate(body.get("inserts") or [], 1):
        try:
            at, start, end = float(raw["at"]), float(raw["start"]), float(raw["end"])
            until = float(raw["until"]) if raw.get("until") is not None else at
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, f"Insert {n}: the times are not numbers.")
        a = sources.get(str(raw.get("source_id") or ""))
        if not a:
            raise HTTPException(422, f"Insert {n}: there is no file for {raw.get('source_id') or 'this clip'} in the project. Fetch or upload it first.")
        if raw.get("audio_ok") is not True:
            raise HTTPException(422, f"Insert {n}: tick that you may play this clip's original audio, or leave the insert out.")
        card = effects.normalise_lower_third(raw.get("lower_third"))
        inserts.append({"at": at, "until": until, "start": start, "end": end, "path": renderer.asset_path(a), "source_id": raw["source_id"], "file": a["name"],
                        **({"lower_third": card} if card else {})})
        raws.append({**raw, "card": bool(card)})
    if not inserts:
        raise HTTPException(422, "Tick at least one insert to include.")
    for ins, plan in zip(inserts, recut_cutaways(p, raws, body.get("auto_cutaways", True) is not False)):
        ins["cutaways"] = plan["cutaways"]
    problems, base_info = recut.check(base, inserts)
    if problems:
        raise HTTPException(422, " ".join(problems[:3]))
    length_note = recut.mismatch_note(base_info)

    def work(progress, cancelled):
        progress = with_machine_note(progress)
        folder = DATA / "media" / id / "recut"
        folder.mkdir(parents=True, exist_ok=True)
        rid = uid()
        out = folder / f"{rid}.mp4"
        try:
            with RENDER_LOCK:
                wm = watermark.active(p)
                logo = None
                if wm:
                    logo_asset = next(x for x in p["assets"] if x["id"] == wm["asset_id"])
                    logo = lambda w, h, path: watermark.layer(p, renderer.asset_path(logo_asset), w, h, path)
                proofs = folder / f"{rid}-check"
                proofs.mkdir(exist_ok=True)
                checks = []
                duration = recut.render(base, inserts, out, progress, cancelled, logo=logo, proof_dir=proofs, checks=checks)
        except recut.RecutError as e:
            out.unlink(missing_ok=True)
            shutil.rmtree(folder / f"{rid}-check", ignore_errors=True)
            raise RuntimeError(str(e))
        record = {"id": rid, "at": now(), "duration": duration, "size": out.stat().st_size,
                  "inserts": [{**{k: i[k] for k in ("at", "until", "start", "end", "source_id", "file")}, "cutaways": len(i.get("cutaways") or [])} for i in inserts],
                  # v0.4.39 picture check: where each clip sits in the finished video, and a frame from it
                  "checks": [{"n": c["n"], "ok": c["ok"], "at": c["at"], "proof": c.get("proof")} for c in checks],
                  "audio_confirmed": now()}
        with DESK_LOCK:
            state = casedesk.load(DATA, id)
            state["recuts"].insert(0, record)
            casedesk.save(DATA, id, state)
        secs = round(duration)
        summary = f"Re-cut ready: {secs // 60}:{secs % 60:02d} with {len(inserts)} original clip{'s' if len(inserts) != 1 else ''} in place of the narrated lines."
        return {**record, "summary": summary + (" " + length_note if length_note else "")}

    return spawn(id, "recut", work)


@app.get("/api/projects/{id}/recut/check/{rid}/{name}")
def recut_check_image(id: str, rid: str, name: str):
    project_or_404(id)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", rid) or not re.fullmatch(r"insert\d{2}\.jpg", name):
        raise HTTPException(404, "Not found.")
    path = DATA / "media" / id / "recut" / f"{rid}-check" / name
    if not path.is_file():
        raise HTTPException(404, "Not found.")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/projects/{id}/recut/file/{rid}")
def recut_file(id: str, rid: str):
    p = project_or_404(id)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid):
        raise HTTPException(404, "Unknown re-cut.")
    path = DATA / "media" / id / "recut" / f"{rid}.mp4"
    if not path.is_file():
        raise HTTPException(404, "That re-cut is no longer on disk.")
    name = re.sub(r"[^A-Za-z0-9 _-]+", "", p.get("title") or "video").strip() or "video"
    return FileResponse(path, filename=f"{name} - recut.mp4", media_type="video/mp4")


# ---------------------------------------------------------------------------
# Delete a project and everything it stored on disk (v0.4.22).
# ---------------------------------------------------------------------------


def project_files(id, p):
    """Every folder and file that belongs only to this project."""
    paths = [DATA / "projects" / f"{id}.json", DATA / "casedesk" / f"{id}.json", DATA / "history" / f"{id}.json",
             DATA / "fetch-work" / id, DATA / "fetch-work" / f"voice-{id}",
             DATA / "fetch-work" / f"recut-{id}"]
    paths += [DATA / "exports" / x["id"] for x in p.get("exports", []) if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(x.get("id", "")))]
    return paths


def folder_size(path):
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0


@app.get("/api/home")
def home_view():
    """The start page (v0.4.33): every project with a picture, length, size and
    what has been made from it. Read-only."""
    out = []
    for summary in projects():
        p = get_project(summary["id"]) or {}
        assets = {a["id"]: a for a in p.get("assets", [])}
        thumb = None
        for s in p.get("scenes", []):
            a = assets.get(s.get("asset_id"))
            if a and (a.get("thumbnail") or a.get("kind") == "image"):
                thumb = a.get("thumbnail") or a.get("url")
                break
        if not thumb:
            a = next((x for x in p.get("assets", []) if x.get("thumbnail")), None)
            thumb = a and a["thumbnail"]
        recuts = (casedesk.load(DATA, summary["id"]).get("recuts") or []) if (DATA / "casedesk" / f"{summary['id']}.json").exists() else []
        out.append({
            **summary,
            "thumbnail": thumb,
            "duration": round(sum(float(s.get("duration") or 0) for s in p.get("scenes", [])), 2),
            "scenes": len(p.get("scenes", [])),
            "aspect": effects.aspect_of(p),
            "size": folder_size(DATA / "media" / summary["id"]) + sum(folder_size(DATA / "exports" / x["id"]) for x in p.get("exports", []) if x.get("id")),
            "exports": len(p.get("exports", [])),
            "recuts": len(recuts),
        })
    return {"projects": out}


@app.get("/api/projects/{id}/storage")
def project_storage(id: str):
    p = project_or_404(id)
    media = folder_size(DATA / "media" / id)
    exports = sum(folder_size(DATA / "exports" / x["id"]) for x in p.get("exports", []))
    return {"media": media, "exports": exports, "total": media + exports + sum(folder_size(x) for x in project_files(id, p)[:2])}


@app.delete("/api/projects/{id}")
async def delete_project(id: str, request: Request):
    body = await episode_json(request)
    p = project_or_404(id)
    if any(j["project_id"] == id and j["status"] in ("running", "queued") for j in JOBS.values()):
        raise HTTPException(409, "Wait for the current operation to finish before deleting this project.")
    if str(body.get("confirm_title") or "").strip() != str(p.get("title") or "").strip():
        raise HTTPException(422, "Type the project's exact title to delete it.")
    with LOCK:
        # Files another project still points at (a restored backup or a copy) are kept.
        prefix = f"media/{id}/"
        keep = set()
        for other in projects():
            if other["id"] == id:
                continue
            full = get_project(other["id"]) or {}
            for a in full.get("assets", []):
                ref = str(a.get("path", "")).replace("\\", "/")
                if prefix in ref:
                    keep.add(Path(ref).name)
                    keep.add(Path(ref).stem + "-thumb.jpg")
        freed = 0
        media = DATA / "media" / id
        if media.is_dir():
            if keep:
                for f in media.rglob("*"):
                    if f.is_file() and f.name not in keep:
                        freed += f.stat().st_size
                        f.unlink()
            else:
                freed += folder_size(media)
                shutil.rmtree(media, ignore_errors=True)
        for path in project_files(id, p):
            freed += folder_size(path)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        for jid in [k for k, j in JOBS.items() if j["project_id"] == id]:
            JOBS.pop(jid, None)
        # v0.4.33: nothing of it is left behind: saved job records and recovery backups too.
        for f in (DATA / "jobs").glob("*.json"):
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("project_id") == id:
                    freed += f.stat().st_size
                    f.unlink()
            except (OSError, ValueError):
                pass
        for f in (DATA / "recovery-backups").glob(f"{id}-*.json"):
            freed += f.stat().st_size
            f.unlink(missing_ok=True)
        for f in (DATA / "browser-sessions").glob("*.json"):
            try:
                if (json.loads(f.read_text(encoding="utf-8")).get("snapshot") or {}).get("id") == id:
                    freed += f.stat().st_size
                    f.unlink()
            except (OSError, ValueError):
                pass
    return {"deleted": id, "freed": freed, "kept_shared_files": len(keep) // 2, "projects": projects()}


@app.post("/api/projects/{id}/fetch")
async def fetch_start(id: str, request: Request):
    body = await episode_json(request)
    p = project_or_404(id)
    downloaders = fetch_downloaders(request, body)  # keeps a pasted token for this session
    if not (p.get("episode") or {}).get("guide"):
        raise HTTPException(422, "Import the editing guide first; the guide lists what to fetch.")
    if not body.get("confirm_responsibility") and not (p.get("episode") or {}).get("fetch_ack"):
        raise HTTPException(422, "Read and accept the download notice first. " + FETCH_NOTICE)
    name = body.get("backend") or "yt-dlp"
    if name not in ("yt-dlp", "apify"):
        raise HTTPException(422, "Choose yt-dlp or apify.")
    downloader = downloaders[name]
    ready = downloader.status()
    if not ready["ready"]:
        raise HTTPException(422, ready["detail"])
    plan = fetcher.plan(p, include_unused=bool(body.get("include_unused")))
    only = {str(x) for x in (body.get("only") or [])}
    items = [i for i in plan["items"] if i["status"] == "todo" and (not only or i["id"] in only)]
    if not items:
        raise HTTPException(422, "Nothing to fetch: every file the guide names is already here, or needs getting by hand.")
    with LOCK:
        p = project_or_404(id)
        e = p.setdefault("episode", copy.deepcopy(episode.state(p)))
        e.setdefault("fetch_ack", {"at": now(), "notice": FETCH_NOTICE})
        save_project(p)

    def work(progress, cancelled):
        work_dir = DATA / "fetch-work" / id
        files = FileProgress(progress, items)
        try:
            results = fetcher.run(
                items, downloader, work_dir,
                lambda path, item, record: import_fetched(id, path, item, record),
                lambda pct, msg: files.overall(min(95, pct), msg), cancelled,
                on_status=files,
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            progress(96, "Finishing", files=files.finish())
        ok = [r for r in results if r["ok"]]
        if ok:
            progress(97, "Linking files to the guide's sources")
            with LOCK:
                p = project_or_404(id)
                link_filenames(p)
                try:
                    episode.build(p, allow_placeholders=True, inspection=True)
                except (ValueError, TypeError, KeyError):
                    pass
                save_project(p)
        failed = [r for r in results if not r["ok"]]
        return {
            "results": results,
            "fetched": len(ok),
            "failed": len(failed),
            "summary": f"Fetched {len(ok)} of {len(results)} files"
            + (f"; {len(failed)} failed (see the list)." if failed else "."),
        }

    return spawn(id, "fetch", work)



@app.post("/api/projects/{id}/episode/first-draft")
def first_draft(id: str):
    """One explicit inspection action: available files -> match -> build -> preview.

    Never records rights/context approval, invents missing footage, or requires
    final-publication sign-offs merely to see the selected source.
    """
    with LOCK:
        p = project_or_404(id)
        if p.get("is_demo"):
            raise HTTPException(
                422,
                "Start your own project rather than replacing the fictional sample.",
            )
        e = episode.state(p)
        if not e.get("script") or not e.get("guide"):
            raise HTTPException(
                422,
                "Add your narration script and editing guide first. They are separate inputs.",
            )
        available = set()
        for asset in p.get("assets", []):
            try:
                exists = resolve_asset(asset.get("path")).is_file()
            except (ValueError, OSError):
                exists = False
            asset["available_on_server"] = exists
            if exists:
                available.add(asset["id"])
        options_project = {
            **p,
            "assets": [a for a in p["assets"] if a["id"] in available],
        }
        for sid, aid in episode.suggestions(options_project).items():
            bound = episode.state(p).get("bindings", {}).get(sid, {}).get("asset_id")
            if bound not in available:
                episode.bind_source(p, sid, {"asset_id": aid})
        corrections = episode.resolve_automatic_source_links(p)
        report = episode.analyze(p)
        if report["errors"]:
            raise HTTPException(422, " ".join(report["errors"]))
        if not report["inspection_cues"]:
            visuals = [a for a in p["assets"] if a["kind"] in ("image", "video")]
            if visuals and not any(a["id"] in available for a in visuals):
                raise HTTPException(
                    422,
                    "The source names are saved, but their uploaded copies are not available on this server. Your computer originals were not deleted. Add one original source photo/video to verify the preview; checking approvals cannot restore missing bytes.",
                )
            if not visuals:
                raise HTTPException(
                    422,
                    "Add at least one source photo or video first. We will not call an all-placeholder timeline a visual draft.",
                )
            raise HTTPException(
                422,
                "Files are present, but no guide placement can use them yet. Match a filename to its source ID or check the source-choice/range explanation in More settings. No approval checkboxes are needed for inspection.",
            )
        plan = e.get("plan") or {}
        used_missing = any(
            s.get("asset_id") and s["asset_id"] not in available
            for s in p.get("scenes", [])
        )
        reused = (
            report["plan_current"]
            and plan.get("mode") == "inspection"
            and not used_missing
            and any(s.get("asset_id") for s in p.get("scenes", []))
        )
        if not reused:
            checkpoint(p, "First draft")
            try:
                episode.build(p, allow_placeholders=True, inspection=True)
            except (ValueError, TypeError, KeyError) as error:
                raise HTTPException(422, str(error))
        start = 0.0
        first = None
        for scene in p["scenes"]:
            if scene.get("asset_id"):
                first = {
                    "scene_id": scene["id"],
                    "time": start + min(1 / renderer.FPS, scene["duration"] / 2),
                }
                break
            start += scene["duration"]
        if first is None:
            raise HTTPException(
                422,
                "No real visual was produced. Check a linked file and its permitted range; the empty plan was not saved as a successful draft.",
            )
        result = episode_result(p)
        result["preview"] = first
        result["reused_current_plan"] = bool(reused)
        result["automatic_source_corrections"] = corrections
        return result


@app.post("/api/projects/{id}/episode/build")
async def episode_build(id: str, request: Request):
    body = await episode_json(request)
    with LOCK:
        p = project_or_404(id)
        checkpoint(p, "Build episode")
        try:
            episode.build(
                p,
                allow_placeholders=body.get("allow_placeholders") is True,
                inspection=body.get("inspection") is True,
            )
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, str(e))
        return episode_result(p)


@app.get("/api/projects/{id}/episode/base-report")
def episode_base_report(id: str):
    """Pool readiness and every base-image fill in the current plan."""
    p = project_or_404(id)
    e = episode.state(p)
    items = episode.basefill.pool(p)
    counts, tags = episode.basefill.pool_counts(items)
    summary = (e.get("plan") or {}).get("base_fill")
    guide = e.get("guide") or {}
    return {
        "enabled": episode.basefill.enabled(p, items),
        "pool": counts,
        "pool_tags": tags,
        "files": [
            {
                "name": i["name"],
                "bucket": i["bucket"],
                "tags": i["tags"],
                "kind": i["kind"],
                "window": i.get("window"),
            }
            for i in items
        ],
        "setup": guide.get("setup"),
        "guide_base_files": guide.get("base_files", []),
        "seed": int(e.get("base_seed") or 1),
        "plan": summary,
        "findings": episode.basefill.pool_warnings(items)
        + episode.basefill.readiness(
            summary or {"fills": 0},
            guide.get("setup"),
            guide.get("base_files"),
            [a.get("name", "") for a in p.get("assets", [])],
        ),
    }


@app.get("/api/projects/{id}/episode/plan.md")
def episode_report(id: str):
    return PlainTextResponse(
        episode.markdown(project_or_404(id)),
        headers={"Content-Disposition": 'attachment; filename="episode-plan.md"'},
    )


app.mount("/assets", StaticFiles(directory=ROOT / "web/assets"), name="assets")
app.mount("/media", StaticFiles(directory=DATA / "media"), name="media")
app.mount("/exports", StaticFiles(directory=DATA / "exports"), name="exports")


@app.get("/{path:path}")
def index(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found.")
    return FileResponse(ROOT / "web/index.html")

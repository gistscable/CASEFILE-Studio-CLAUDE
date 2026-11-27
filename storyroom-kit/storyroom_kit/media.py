"""FFmpeg: found on the PATH, or from the optional `ffmpeg-binaries` package (pip install "storyroom-kit[ffmpeg]")."""
from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path


def ensure_ffmpeg() -> str:
    """The ffmpeg to use; puts the bundled one on the PATH (for the engine and worker processes) when needed."""
    env = os.environ.get("STORYROOM_FFMPEG")
    if env and Path(env).is_file():
        os.environ["PATH"] = str(Path(env).parent) + os.pathsep + os.environ.get("PATH", "")
        return env
    found = shutil.which("ffmpeg")
    if found and shutil.which("ffprobe"):
        return found
    spec = importlib.util.find_spec("ffmpeg")
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            b = Path(loc) / "binaries"
            if (b / "ffmpeg").is_file() or (b / "ffmpeg.exe").is_file():
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
                return shutil.which("ffmpeg") or str(b / "ffmpeg")
    if found:
        return found
    raise RuntimeError("FFmpeg was not found. Install it (macOS: brew install ffmpeg) or: pip install \"storyroom-kit[ffmpeg]\". "
                       "You can also point STORYROOM_FFMPEG at an ffmpeg file.")

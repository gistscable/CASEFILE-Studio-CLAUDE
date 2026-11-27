"""Copy the graphics engine from Casefile Studio into the kit, or check that the kit's copy still matches.

The kit carries its own copy of `cinegfx` (the engine), `sfxlib.py` (its sounds) and the fonts, so it runs
without Casefile and nothing in Casefile changes. Two lines differ from Casefile's files, and only because the
kit is laid out differently (see PATCHES). Everything else is byte for byte the same.

    python tools/sync_engine.py            # check: exit 1 and list the files that differ
    python tools/sync_engine.py --write    # copy again from ../casefile-studio (after the engine changes there)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
PKG = KIT / "storyroom_kit"
CASEFILE = KIT.parent / "casefile-studio"

# (file inside the engine, Casefile's line, the kit's line)
PATCHES = {
    "cinegfx/theme.py": [
        ('FONT_DIR = Path(__file__).resolve().parent.parent / "web" / "assets" / "fonts"',
         'FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"  # storyroom-kit: the kit\'s own copy of the fonts'),
        ('        return str(FONT_DIR.parent / "dm-sans.ttf")',
         '        return str(FONT_DIR / "dm-sans.ttf")  # storyroom-kit: kept with the other fonts'),
    ],
    "cinegfx/sfx.py": [
        ("sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\nimport sfxlib  # noqa: E402",
         "from .. import sfxlib  # noqa: E402  (storyroom-kit: the kit's own copy)"),
    ],
}


def _sources():
    """(path in Casefile, path in the kit) for every file the kit copies."""
    out = []
    for f in sorted((CASEFILE / "cinegfx").rglob("*.py")):
        rel = f.relative_to(CASEFILE)
        out.append((f, PKG / rel))
    out.append((CASEFILE / "sfxlib.py", PKG / "sfxlib.py"))
    fonts = CASEFILE / "web" / "assets" / "fonts"
    for f in sorted(fonts.iterdir()):
        if f.is_file():
            out.append((f, PKG / "fonts" / f.name))
    out.append((CASEFILE / "web" / "assets" / "dm-sans.ttf", PKG / "fonts" / "dm-sans.ttf"))
    out.append((CASEFILE / "web" / "assets" / "FONT-LICENSE.txt", PKG / "fonts" / "DM-Sans-LICENSE.txt"))
    return out


def expected(src: Path) -> bytes:
    data = src.read_bytes()
    rel = src.relative_to(CASEFILE).as_posix()
    for old, new in PATCHES.get(rel, []):
        text = data.decode()
        if text.count(old) != 1:
            raise SystemExit(f"{rel}: the line the kit changes is no longer in Casefile's file; update PATCHES:\n  {old}")
        data = text.replace(old, new).encode()
    return data


def _commit():
    try:
        return subprocess.run(["git", "-C", str(KIT.parent), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def main(argv):
    if not (CASEFILE / "cinegfx").is_dir():
        print("Casefile Studio is not next to the kit (../casefile-studio): nothing to compare with.")
        return 0
    write = "--write" in argv
    differ, files = [], {}
    for src, dst in _sources():
        want = expected(src)
        files[dst.relative_to(PKG).as_posix()] = hashlib.sha256(want).hexdigest()[:16]
        if not dst.exists() or dst.read_bytes() != want:
            differ.append(dst.relative_to(KIT).as_posix())
            if write:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(want)
    kit_engine = {p.relative_to(PKG).as_posix() for p in (PKG / "cinegfx").rglob("*.py")}
    extra = sorted(kit_engine - set(files))
    for x in extra:
        differ.append(f"storyroom_kit/{x} (not in Casefile)")
        if write:
            (PKG / x).unlink()
    if write:
        shutil.rmtree(PKG / "cinegfx" / "__pycache__", ignore_errors=True)
        (PKG / "ENGINE_SOURCE.json").write_text(json.dumps({"copied_from": "casefile-studio", "commit": _commit(), "patches": {
            k: len(v) for k, v in PATCHES.items()}, "files": files}, indent=1) + "\n")
        print(f"Copied {len(files)} files from Casefile Studio ({len(differ)} changed).")
        return 0
    if differ:
        print("The kit's engine differs from Casefile's:\n  " + "\n  ".join(differ))
        print("Run: python tools/sync_engine.py --write")
        return 1
    print(f"The kit's engine matches Casefile's ({len(files)} files; {sum(len(v) for v in PATCHES.values())} layout lines differ by design).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

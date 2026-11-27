import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))
CASEFILE = KIT.parent / "casefile-studio"


@pytest.fixture(scope="session")
def ffmpeg():
    from storyroom_kit.media import ensure_ffmpeg
    try:
        return ensure_ffmpeg()
    except RuntimeError as e:
        pytest.skip(str(e))


def casefile_or_skip():
    if not (CASEFILE / "cinematic.py").is_file():
        pytest.skip("Casefile Studio is not next to the kit (only inside the CASEFILE-Studio repository)")
    if str(CASEFILE) not in sys.path:
        sys.path.insert(0, str(CASEFILE))

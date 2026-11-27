"""The kit draws the approved Javits graphics as Casefile Studio does. The reference stills in tests/data/reference
were drawn by Casefile's engine (v0.4.66) without photos (the press photos are not shipped with the kit); they are
stored at 640x360, so a tiny tolerance absorbs differences in how another Pillow build resizes."""
from pathlib import Path

import numpy as np
from PIL import Image

import javits_demo as J
from storyroom_kit import cinegfx as KC
from storyroom_kit.cinegfx import core, story, text, timing  # noqa: F401  (submodules on the package)

REF = Path(__file__).resolve().parent / "data" / "reference"


def test_the_six_demos_choose_their_approved_category():
    got = {k: cat for k, cat, _ in J.graphics(KC)}
    assert got == J.EXPECT


def test_the_six_demos_match_casefiles_stills():
    n = 0
    for key, _, g in J.graphics(KC):
        for t in J.marks(g):
            ref = REF / f"{key}-{t:06.2f}.png"
            assert ref.exists(), ref
            a = np.asarray(g.frame(t).convert("RGB").resize((640, 360), Image.LANCZOS), dtype=np.int16)
            b = np.asarray(Image.open(ref).convert("RGB"), dtype=np.int16)
            assert np.abs(a - b).mean() < 0.35, (key, t, float(np.abs(a - b).mean()))
            n += 1
    assert n == 18

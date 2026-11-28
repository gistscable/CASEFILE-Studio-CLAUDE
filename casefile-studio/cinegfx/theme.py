"""Visual identities. A Theme is pure data (palette + type roles + layout traits), so a niche collection
defines its own looks without touching drawing code, and the same category can be restyled per project."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "web" / "assets" / "fonts"
FONTS = {
    "oswald": "Oswald-Bold.ttf", "oswald-md": "Oswald-Medium.ttf", "oswald-rg": "Oswald-Regular.ttf",
    "inter-black": "Inter-Black.otf", "inter-bold": "Inter-Bold.otf",
    "poppins": "Poppins-Bold.ttf", "caladea": "Caladea-Bold.ttf", "serif": "LiberationSerif-Bold.ttf",
    "mono": "LiberationMono-Bold.ttf", "sans": "DejaVuSans.ttf", "sans-bold": "DejaVuSans-Bold.ttf",
    "carlito": "Carlito-Bold.ttf", "lib-sans": "LiberationSans-Bold.ttf",
    # v0.4.77 sports editorial (cinegfx/sports): heavy condensed display + condensed labels
    "anton": "Anton-Regular.ttf", "bebas": "BebasNeue-Regular.ttf",
    "barlow-sb": "BarlowCondensed-SemiBold.ttf", "barlow-b": "BarlowCondensed-Bold.ttf",
}


def font_path(key: str) -> str:
    key = key.split("@", 1)[0]  # v0.4.64: "@1.1" is a text-size scale (draw.font), not a different file
    if key == "dm-sans":
        return str(FONT_DIR.parent / "dm-sans.ttf")
    return str(FONT_DIR / FONTS[key])


def hexrgb(h: str, a: int = 255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    bg2: str            # secondary surface
    ink: str            # primary text
    muted: str          # secondary text
    accent: str
    accent2: str
    display: str        # font keys
    heading: str
    body: str
    label: str
    traits: dict = field(default_factory=dict)  # free-form layout traits a graphic may read (grid, rule weight ...)

    def c(self, role: str, a: int = 255):
        return hexrgb(getattr(self, role), a)

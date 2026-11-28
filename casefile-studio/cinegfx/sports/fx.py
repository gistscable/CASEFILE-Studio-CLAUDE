"""Frame effects: selective RGB split, horizontal slice displacement, luma-matte dissolve, directional push,
and the film finish (warm vignette, lifted blacks, grain, dust, faint light streaks). All deterministic per
frame index, so any frame renders identically in any worker."""
from __future__ import annotations

from functools import lru_cache

import numpy as np


def rng(seed: int):
    return np.random.default_rng(seed & 0xFFFFFFFF)


def rgb_split(img: np.ndarray, dx: int, dy: int = 0) -> np.ndarray:
    """Red channel shifted one way, blue the other (green stays): the 'digital doubling' of a glitch."""
    if dx == 0 and dy == 0:
        return img
    out = img.copy()
    out[..., 0] = np.roll(img[..., 0], (dy, dx), axis=(0, 1))
    out[..., 2] = np.roll(img[..., 2], (-dy, -dx), axis=(0, 1))
    return out


def slices(img: np.ndarray, seed: int, amount: float, bands: int = 14) -> np.ndarray:
    """Horizontal slice displacement: random bands slide sideways by up to `amount` * width."""
    if amount <= 0:
        return img
    H, W = img.shape[:2]
    r = rng(seed)
    out = img.copy()
    cuts = np.sort(r.integers(0, H, bands * 2))
    for a, b in zip(cuts[::2], cuts[1::2]):
        if b - a < 2:
            continue
        sh = int(r.uniform(-1, 1) * amount * W)
        out[a:b] = np.roll(img[a:b], sh, axis=1)
    return out


def glitch(img: np.ndarray, seed: int, p: float) -> np.ndarray:
    """A short digital hit (p 0..1 strength): slices + RGB split + a few bright scan bands."""
    if p <= 0:
        return img
    W = img.shape[1]
    out = slices(img, seed, 0.06 * p)
    out = rgb_split(out, int(W * 0.012 * p) + 2, 0)
    r = rng(seed + 7)
    for _ in range(int(3 * p)):
        y = int(r.integers(0, img.shape[0] - 6))
        h = int(r.integers(2, 6))
        out[y:y + h] = np.clip(out[y:y + h].astype(np.int16) + 70, 0, 255).astype(np.uint8)
    return out


@lru_cache(maxsize=4)
def _blotch(W: int, H: int, seed: int):
    """A soft blotchy noise field (0..1) for the luma-matte dissolve, made from a few octaves of upscaled noise."""
    from PIL import Image
    acc = np.zeros((H, W), np.float32)
    r = rng(seed)
    for k, (gw, wt) in enumerate(((6, 0.55), (14, 0.3), (40, 0.15))):
        g = (r.random((max(2, gw * H // W), gw)) * 255).astype(np.uint8)
        acc += np.asarray(Image.fromarray(g).resize((W, H), Image.BICUBIC), np.float32) / 255 * wt
    acc -= acc.min()
    return acc / max(1e-6, acc.max())


def luma_dissolve(a: np.ndarray, b: np.ndarray, p: float, seed: int = 3, soft: float = 0.12) -> np.ndarray:
    """Blotchy luma-matte transition from a to b (p 0..1): bright parts of the incoming shot and the noise
    field burn through first."""
    if p <= 0:
        return a
    if p >= 1:
        return b
    H, W = a.shape[:2]
    lb = (b[..., 0] * 0.3 + b[..., 1] * 0.59 + b[..., 2] * 0.11).astype(np.float32) / 255
    field = 0.6 * _blotch(W, H, seed) + 0.4 * lb
    thr = p * (1 + soft) - soft
    m = np.clip((field - (1 - thr - soft)) / soft, 0, 1)[..., None]
    m = np.clip(m + (p > 0.92) * (p - 0.92) / 0.08, 0, 1)
    return (a * (1 - m) + b * m).astype(np.uint8)


def dissolve(a, b, p):
    if p <= 0:
        return a
    if p >= 1:
        return b
    return (a.astype(np.float32) * (1 - p) + b.astype(np.float32) * p).astype(np.uint8)


def push(a, b, p, direction=1):
    """Directional push with a short smear: the outgoing shot leaves as the incoming one arrives."""
    if p <= 0:
        return a
    if p >= 1:
        return b
    from .. import anim
    W = a.shape[1]
    e = anim.in_out_cubic(p)
    off = int(e * W) * direction
    out = np.empty_like(a)
    if direction > 0:
        out[:, : W - off] = a[:, off:]
        out[:, W - off:] = b[:, : off]
    else:
        off = -off
        out[:, off:] = a[:, : W - off]
        out[:, : off] = b[:, W - off:]
    smear = int(40 * np.sin(np.pi * p))
    if smear > 2:
        out = ((out.astype(np.uint16) + np.roll(out, smear * direction, axis=1)) // 2).astype(np.uint8)
    return out


def dip(a, b, p, color=0):
    if p < 0.5:
        return (a.astype(np.float32) * (1 - p * 2) + color * p * 2).astype(np.uint8)
    q = (p - 0.5) * 2
    return (b.astype(np.float32) * q + color * (1 - q)).astype(np.uint8)


# ------------------------------------------------------------------ film finish
@lru_cache(maxsize=2)
def _vignette(W: int, H: int, strength: float):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2) / np.sqrt(2)
    v = np.clip((d - 0.35) / 0.65, 0, 1) ** 1.6 * strength
    # warm brown edge (the reference's dark warm-brown/red vignette)
    tint = np.array([0.62, 0.48, 0.42], np.float32)
    mul = 1 - v[..., None] * (1 - tint * 0.35)
    mul = mul * (1 - v[..., None] * 0.55)
    return (mul * 256).astype(np.uint16)


@lru_cache(maxsize=1)
def _grain_bank(W: int, H: int, n: int = 6):
    r = rng(99)
    return [r.normal(0, 1, (H // 2, W // 2)).astype(np.float32) for _ in range(n)]


def _grain(W, H, i, amount):
    g = _grain_bank(W, H)[i % 6]
    g = np.repeat(np.repeat(g, 2, axis=0), 2, axis=1)[:H, :W]
    return g * amount


def finish(img: np.ndarray, i: int, grain: float = 5.5, vignette: float = 0.85, lift=(10, 7, 5), dust: bool = True,
           streaks: bool = True) -> np.ndarray:
    H, W = img.shape[:2]
    out = (img.astype(np.uint16) * _vignette(W, H, vignette) >> 8).astype(np.float32)
    # lifted, warm blacks
    l = np.array(lift, np.float32)
    out = out + l * (1 - out / 255)
    if grain:
        out += _grain(W, H, i, grain)[..., None]
    if streaks:
        r = rng(1000 + i // 9)
        for _ in range(2):
            x = int(r.integers(0, W))
            w = int(r.integers(1, 3))
            out[:, x:x + w] += float(r.uniform(4, 10))
    if dust:
        r = rng(5000 + i)
        for _ in range(int(r.integers(0, 4))):
            x, y = int(r.integers(0, W - 6)), int(r.integers(0, H - 6))
            s = int(r.integers(1, 4))
            v = float(r.choice([-60, 70]))
            out[y:y + s, x:x + s] += v
    return np.clip(out, 0, 255).astype(np.uint8)

"""The 7 sports editorial graphics families, timed from semantics.Element word times.

Each family is a pure function of time:
  draw(t, behind, front, ctx)  type into the BEHIND layer (composited under the subject's matte, so a player
                               occludes it) and/or the FRONT layer (always on top)
  cues()                       sound events, each on the exact frame of its visual event
  fx(t)                        frame-level requests: {"glitch": p, "rgb": px, "grade": (name, mix)}
Graphics live on the timeline, not on a shot, so they persist across cuts.

Proportions and timing follow the study of the reference (qa/sports-demos/REFERENCE-NOTES.md).
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image

from .. import anim
from ..core import Cue
from . import fx as FX
from . import typeset as T

DISPLAY = "anton"        # heavy condensed display (names, headlines, numerals)
LABEL = "barlow-b"       # condensed labels
SMALLCAPS = "barlow-sb"  # minimal storytelling lines


def frames(dt, fps):
    return int(math.floor(dt * fps + 1e-6))


class Family:
    behind_subject = False

    def __init__(self, el, W=1920, H=1080, fps=25):
        self.el, self.W, self.H, self.fps = el, W, H, fps
        self.d = el.data
        self.t_in, self.t_out = el.t_in, el.t_out
        self.layout = None

    def active(self, t):
        return self.t_in - 0.05 <= t <= self.t_out + 0.4

    def cues(self):
        return []

    def fx(self, t):
        return {}

    def draw(self, t, behind, front, ctx):
        raise NotImplementedError

    def exit_p(self, t, dur=0.22):
        return anim.clamp((t - self.t_out) / dur)


# ------------------------------------------------------------------ 1. name behind subject
class NameBehind(Family):
    """Two huge tight-leading lines (each ~36% of frame height), placed so the subject's head overlaps the
    first letters; each line is revealed by a fast masked left->right wipe on its own word."""
    behind_subject = True

    def _layout(self, ctx):
        H, W = self.H, self.W
        lines = [ln for ln, _ in self.d["lines"]]
        cap = H * 0.34
        size = T.size_for_cap(DISPLAY, cap)
        widest = max(T.advance(s, DISPLAY, size) for s in lines)
        if widest > W * 0.9:
            size = int(size * W * 0.9 / widest)
            cap = T.cap_height(DISPLAY, size)
            widest = max(T.advance(s, DISPLAY, size) for s in lines)
        gap = cap * 0.09
        block_h = cap * len(lines) + gap * (len(lines) - 1)
        y0 = (H - block_h) / 2 + H * 0.02
        sub = ctx.subject(self.t_in + 0.3) if ctx else None
        if sub:  # head overlaps the first letters: text starts just left of the head centre
            cx = sub["head_x"] * W
            if cx < W * 0.55:
                x0 = min(max(W * 0.05, cx - W * 0.07), W * 0.95 - widest)
            else:
                x0 = max(W * 0.05, min(cx + W * 0.07, W * 0.95) - widest)
        else:
            x0 = (W - widest) / 2 + W * 0.04
        self.layout = dict(size=size, cap=cap, gap=gap, x0=x0, y0=y0, widest=widest)

    def cues(self):
        out = []
        for k, (_, t) in enumerate(self.d["lines"]):
            out.append(Cue(t, "whoosh-short-1" if k == 0 else "whoosh-short-2", -2, "name line wipes in"))
        out.append(Cue(self.d["lines"][0][1], "bass-hit-2", -3, "name lands"))
        return out

    def draw(self, t, behind, front, ctx):
        if self.layout is None:
            self._layout(ctx)
        L = self.layout
        ex = self.exit_p(t, 0.25)
        for k, (text, t0) in enumerate(self.d["lines"]):
            p = anim.out_quint(anim.prog(t, t0, 0.30))
            if p <= 0:
                continue
            y = L["y0"] + k * (L["cap"] + L["gap"])
            x = L["x0"] + (L["widest"] - T.advance(text, DISPLAY, L["size"])) * 0  # left aligned
            spr = T.sprite(text, DISPLAY, L["size"], "cool", 0.0, 0.5)
            T.place(behind, spr, x - ex * 30, y, alpha=1 - ex, crop=(0.0, p))


# ------------------------------------------------------------------ 2. oversized headline + supporting statements
class Headline(Family):
    """Slam in: frame 1 an oversized RGB-doubled ghost, frame 2 near size, settled by frame 3. The supporting
    statement is animated independently (word by word on the narration). Exit: slice displacement + fade,
    then the edit adds a short RGB-split glitch on the next shot."""

    def _layout(self):
        W, H = self.W, self.H
        text = self.d["text"]
        quote = self.d.get("quote")
        target_w = W * (0.80 if not quote else 0.84)
        size = T.size_for_cap(DISPLAY, H * 0.30)
        w = T.advance(text, DISPLAY, size)
        if w > target_w:
            size = int(size * target_w / w)
        else:
            size = int(size * min(1.15, target_w / w))
        cap = T.cap_height(DISPLAY, size)
        w = T.advance(text, DISPLAY, size)
        y = H * 0.42 - cap / 2 if self.d.get("sub") else (H - cap) / 2
        ssize = T.size_for_cap(SMALLCAPS, H * (0.052 if not quote else 0.046))
        sy = y + cap + H * 0.055
        if self.d.get("behind"):  # behind a close-up: above the head so only raised hands cross it
            y = H * 0.08
            sy = H * 0.78
        self.layout = dict(size=size, cap=cap, x=(W - w) / 2, y=y, w=w, ssize=ssize, sy=sy)

    def cues(self):
        t = self.d["t"]
        out = [Cue(t, "impact-tr-3", -3, "headline slams in"), Cue(t, "rwhoosh-3", -6, "suck into the slam")]
        for k, (_, ts) in enumerate(self.d.get("sub", [])):
            out.append(Cue(ts, "tick-1", -10, "supporting word"))
        if not self.d.get("quote"):
            out.append(Cue(self.t_out, "sp-glitch", -5, "headline glitches out"))
        return out

    def fx(self, t):
        dt = t - self.d["t"]
        if 0 <= dt < 1 / self.fps:
            return {"rgb": 14}
        if 1 / self.fps <= dt < 2 / self.fps:
            return {"rgb": 5}
        if not self.d.get("quote") and 0 <= t - self.t_out < 0.16:
            return {"glitch": 0.8}
        return {}

    def draw(self, t, behind, front, ctx):
        if self.layout is None:
            self._layout()
        L = self.layout
        t0 = self.d["t"]
        dt = t - t0
        if dt < 0:
            return
        f = frames(dt, self.fps)
        quote = self.d.get("quote")
        ex = anim.clamp((t - self.t_out) / (0.16 if not quote else 0.5))
        if ex >= 1:
            return
        spr = T.sprite(self.d["text"], DISPLAY, L["size"], "cool", 0.0, 0.55)
        layer = behind if (self.behind_subject or self.d.get("behind")) else front
        if f == 0:  # oversized ghost, RGB doubled
            s = 1.22
            cx, cy = L["x"] + L["w"] / 2, L["y"] + L["cap"] / 2
            ghost = Image.new("RGBA", layer.size, (0, 0, 0, 0))
            T.place(ghost, spr, cx - L["w"] * s / 2, cy - L["cap"] * s / 2, alpha=0.75, scale=s)
            g = np.asarray(ghost).copy()
            g = FX.rgb_split(g, 18, 0)
            layer.alpha_composite(Image.fromarray(g, "RGBA"))
        else:
            s = 1.0 + (0.05 if f == 1 else 0.012 * math.exp(-(dt - 2 / self.fps) * 10))
            cx, cy = L["x"] + L["w"] / 2, L["y"] + L["cap"] / 2
            if ex > 0 and not quote:  # slice displacement on the way out
                tmp = Image.new("RGBA", layer.size, (0, 0, 0, 0))
                T.place(tmp, spr, cx - L["w"] * s / 2, cy - L["cap"] * s / 2, alpha=1 - ex * 0.6, scale=s)
                a = FX.slices(np.asarray(tmp), int(t * self.fps), 0.08 * (0.3 + ex))
                layer.alpha_composite(Image.fromarray(a, "RGBA"))
            else:
                T.place(layer, spr, cx - L["w"] * s / 2, cy - L["cap"] * s / 2, alpha=1 - ex, scale=s)
        # supporting statement, word by word
        sub = self.d.get("sub")
        if sub:
            words = [w for w, _ in sub]
            text = "  ".join(words) if not quote else " ".join(words)
            tracking = 4 if not quote else 3
            size = L["ssize"]
            xs, total = T.slots(text, SMALLCAPS, size, tracking)
            x0 = (self.W - total) / 2
            pos, i = [], 0
            for w, ts in sub:
                pos.append((i, w, ts))
                i += len(w) + (2 if not quote else 1)
            for i0, w, ts in pos:
                p = anim.out_cubic(anim.prog(t, ts, 0.18))
                if p <= 0:
                    continue
                style = "yellow" if (w.isdigit() or "–" in w) else "cool"
                spr2 = T.sprite(w, SMALLCAPS, size, style, tracking, 0.5)
                T.place(front, spr2, x0 + xs[i0], L["sy"] + 10 * (1 - p), alpha=p * (1 - ex))
        if self.d.get("attrib"):
            p = anim.out_cubic(anim.prog(t, self.d["attrib_t"], 0.3))
            if p > 0:
                spr3 = T.sprite(self.d["attrib"], LABEL, int(L["ssize"] * 0.8), "yellow", 6, 0.5)
                tw = T.advance(self.d["attrib"], LABEL, int(L["ssize"] * 0.8), 6)
                T.place(front, spr3, (self.W - tw) / 2, L["sy"] + L["ssize"] * 1.6, alpha=p * (1 - ex))


# ------------------------------------------------------------------ 3. sequential numbered points
@lru_cache(maxsize=4)
def _left_shade(W, H, a):
    x = np.linspace(0, 1, W, dtype=np.float32)
    ramp = np.clip(1 - x / 0.62, 0, 1) ** 1.6 * a
    arr = np.zeros((H, W, 4), np.uint8)
    arr[..., 3] = ramp[None, :].astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


class Numbered(Family):
    """Big numerals stacked down the left; each lands on its spoken number with a quick rise; its label sits
    upper-right of the numeral and is revealed word by word as it is said. Earlier rows dim to keep the
    eye on the current point. Persists across cuts."""

    def _layout(self):
        H = self.H
        n = len(self.d["items"])
        step = H * min(0.2, 0.78 / n)
        cap = step * 0.74
        size = T.size_for_cap(DISPLAY, cap)
        lsize = T.size_for_cap(LABEL, cap * 0.36)
        y0 = (H - (step * (n - 1) + cap)) / 2
        self.layout = dict(step=step, cap=cap, size=size, lsize=lsize, y0=y0, x=self.W * 0.075)

    def cues(self):
        out = []
        for it in self.d["items"]:
            out += [Cue(it["t"], "thump-deep-2", -6, f"point {it['n']} lands"), Cue(it["t"], "whoosh-short-2", -8, "rise")]
        return out

    def draw(self, t, behind, front, ctx):
        if self.layout is None:
            self._layout()
        L = self.layout
        ex = self.exit_p(t, 0.3)
        items = self.d["items"]
        current = max([k for k, it in enumerate(items) if t >= it["t"]] or [0])
        # soft shade down the left so the points read over busy footage (a falloff, never a panel)
        sh = anim.out_cubic(anim.prog(t, self.t_in, 0.4)) * (1 - ex)
        if sh > 0:
            front.alpha_composite(_left_shade(self.W, self.H, int(round(15 * sh)) * 10))
        for k, it in enumerate(items):
            p = anim.out_quint(anim.prog(t, it["t"], 0.26))
            if p <= 0:
                continue
            dim = 1.0 if k == current else 0.55
            y = L["y0"] + k * L["step"]
            a = p * dim * (1 - ex)
            num = str(it["n"])
            spr = T.sprite(num, DISPLAY, L["size"], "cool", 0.0, 0.5)
            T.place(front, spr, L["x"], y + 26 * (1 - p), alpha=a)
            nw = T.advance(num, DISPLAY, L["size"])
            lx = L["x"] + nw + L["cap"] * 0.16
            # label words appear as they are spoken
            text = it["label"]
            toks = it["tokens"]
            xs, _ = T.slots(text, LABEL, L["lsize"], 3)
            i = 0
            for w, ts in toks:
                q = anim.out_cubic(anim.prog(t, ts, 0.16))
                if q > 0:
                    style = "yellow" if w.endswith("'") else "cool"
                    T.place(front, T.sprite(w, LABEL, L["lsize"], style, 3, 0.5), lx + xs[i], y + L["cap"] * 0.04 + 8 * (1 - q),
                            alpha=q * dim * (1 - ex))
                i += len(w) + 1


# ------------------------------------------------------------------ 4. minimal storytelling / historical transition
class Minimal(Family):
    """Small centred tracked caps with a soft letter-by-letter reveal paced to the words; nothing else."""

    def cues(self):
        return [Cue(self.t_in, "swell-2", -12, "the room goes quiet")]

    def draw(self, t, behind, front, ctx):
        H = self.H
        size = T.size_for_cap(SMALLCAPS, H * 0.032)
        lines = self.d["lines"]
        ex = self.exit_p(t, 0.5)
        n = len(lines)
        for k, ln in enumerate(lines):
            text = ln["text"]
            y = H * 0.5 - (n * H * 0.05) / 2 + k * H * 0.06
            m = len(text)
            times = [ln["t0"] + (ln["t1"] - ln["t0"]) * 0.85 * i / max(1, m - 1) for i in range(m)]
            T.letters(front, text, SMALLCAPS, size, self.W / 2, y, "white", 9, times, t, 0.22, rise=0, anchor="c",
                      alpha=1 - ex)


# ------------------------------------------------------------------ 5. dates / seasons / venues: scramble labels
class ScrambleLabel(Family):
    """Bottom-left label; characters lock left->right over ~12 frames with a flickering random tail;
    a second line (venue / event) scrambles in on its own word, in the accent colour."""

    def cues(self):
        out = []
        for k, ln in enumerate(self.d["lines"]):
            out.append(Cue(ln["t"], "sp-scramble", -9, f"scramble: {ln['text']}"))
            out.append(Cue(ln["t"] + self.dur(ln["text"]), "click-mech-2", -14, "label locks"))
        return out

    def dur(self, text):
        return max(0.36, min(0.56, 0.035 * len(text)))

    def draw(self, t, behind, front, ctx):
        H, W = self.H, self.W
        ex = self.exit_p(t, 0.25)
        size1 = T.size_for_cap(LABEL, H * 0.05)
        size2 = T.size_for_cap(LABEL, H * 0.034)
        x = W * 0.06
        base = H * 0.80
        for k, ln in enumerate(self.d["lines"]):
            size = size1 if k == 0 else size2
            y = base if k == 0 else base + H * 0.05 + H * 0.022
            style = "cool" if k == 0 else "yellow"
            T.scramble(front, ln["text"], LABEL, size, x, y, t, ln["t"], self.dur(ln["text"]), seed=hash(ln["text"]) & 0xFFFF,
                       style=style, tracking=4 if k == 0 else 6, fps=self.fps, alpha=1 - ex)


# ------------------------------------------------------------------ 6. layered cumulative statistics (masked)
class Cumulative(Family):
    """Figures stack up one by one (numeral + label to the right), drawn BEHIND the subject so a player
    passing in front occludes them; they persist as the footage changes."""
    behind_subject = True

    def cues(self):
        out = []
        for it in self.d["items"]:
            out += [Cue(it["t"], "bass-hit-1", -5, f"{it['value']} lands"), Cue(it["t"], "whoosh-mid-1", -9, "rise")]
        return out

    def draw(self, t, behind, front, ctx):
        H, W = self.H, self.W
        items = self.d["items"]
        n = len(items)
        step = H * 0.27
        cap = H * 0.22
        size = T.size_for_cap(DISPLAY, cap)
        lsize = T.size_for_cap(LABEL, cap * 0.24)
        y0 = (H - (step * (n - 1) + cap)) / 2
        numw = max(T.advance(it["value"], DISPLAY, size) for it in items)
        if self.layout is None:
            sub = ctx.subject(self.t_in + 0.2) if ctx else None
            lw = max(T.advance(it["label"], LABEL, lsize, 4) for it in items)
            block = numw + cap * 0.18 + lw
            if sub and sub["head_x"] >= 0.5:   # player right: figures to his left, his head over the last digit
                x = max(W * 0.05, sub["head_x0"] * W + numw * 0.3 - block)
            elif sub:                          # player left: his head's edge over the first digit, figures run right
                x = min(W * 0.95 - block, sub["head_x1"] * W - numw * 0.3)
            else:
                x = W * 0.1
            self.layout = dict(x=x)
        x = self.layout["x"]
        ex = self.exit_p(t, 0.3)
        for k, it in enumerate(items):
            p = anim.out_quint(anim.prog(t, it["t"], 0.3))
            if p <= 0:
                continue
            y = y0 + k * step
            spr = T.sprite(it["value"], DISPLAY, size, "cool", 0.0, 0.5)
            vw = T.advance(it["value"], DISPLAY, size)
            T.place(behind, spr, x + (numw - vw), y + 40 * (1 - p), alpha=p * (1 - ex))
            q = anim.out_cubic(anim.prog(t, it["t"] + 0.12, 0.25))
            if q > 0:
                T.place(behind, T.sprite(it["label"], LABEL, lsize, "cream", 4, 0.5), x + numw + cap * 0.18,
                        y + cap - T.cap_height(LABEL, lsize) - 2 + 10 * (1 - q), alpha=q * (1 - ex))


# ------------------------------------------------------------------ 7. oversized single statistic
class Impact(Family):
    """One very heavy numeral (~60% of frame height): frame 1 a scaled RGB-split ghost, frame 2 settling,
    full on frame 3; its label in the accent colour letter-reveals on its word. Exit: desaturate to cyan,
    then the edit dissolves through a blotchy luma matte."""
    behind_subject = True

    def cues(self):
        d = self.d
        out = [Cue(d["t"], "impact-tr-3", -2, "the number hits"), Cue(d["t"], "thump-deep-1", -4, "low end"),
               Cue(d["t"], "sp-glitch", -12, "ghost frame"), Cue(d["label_t"], "tick-2", -10, "label")]
        if d.get("sub_t"):
            out.append(Cue(d["sub_t"], "whoosh-short-2", -11, "sub line"))
        return out

    def fx(self, t):
        dt = t - self.d["t"]
        if 0 <= dt < 1 / self.fps:
            return {"rgb": 16}
        if 1 / self.fps <= dt < 2 / self.fps:
            return {"rgb": 6}
        if t > self.t_out - 0.35:
            return {"grade": ("cyan_fade", anim.clamp((t - (self.t_out - 0.35)) / 0.35))}
        return {}

    def _behind_ok(self, t, ctx, box):
        """The numeral goes behind the player only if he never hides much of it in this shot (decided once per
        shot, so it can't flicker between layers mid-shot). A number nobody can read isn't an impact."""
        if not hasattr(ctx, "occlusion"):
            return True
        k = ctx.shot_at(t)
        memo = self.__dict__.setdefault("_layer", {})
        if k not in memo:
            sh = ctx.shots[k]
            a, b = max(sh.start, self.d["t"]), min(sh.end, self.t_out)
            samples = [a + (b - a) * q for q in (0.05, 0.35, 0.65, 0.95)] if b > a else [t]
            memo[k] = max(ctx.occlusion(u, box) for u in samples) < 0.35
        return memo[k]

    def draw(self, t, behind, front, ctx):
        H, W = self.H, self.W
        d = self.d
        dt = t - d["t"]
        if dt < 0:
            return
        cap = H * 0.60
        size = T.size_for_cap(DISPLAY, cap)
        vw = T.advance(d["value"], DISPLAY, size)
        lsize = T.size_for_cap(LABEL, H * 0.055)
        lw = T.advance(d["label"], LABEL, lsize, 6)
        block = vw + H * 0.04 + lw
        x = (W - block) / 2
        y = (H - cap) / 2
        ex = self.exit_p(t, 0.3)
        f = frames(dt, self.fps)
        spr = T.sprite(d["value"], DISPLAY, size, "cool", 0.0, 0.55)
        behind = behind if self._behind_ok(t, ctx, (x / W, y / H, (x + vw) / W, (y + cap) / H)) else front
        if f == 0:
            s = 1.25
            ghost = Image.new("RGBA", behind.size, (0, 0, 0, 0))
            T.place(ghost, spr, x + vw / 2 - vw * s / 2, y + cap / 2 - cap * s / 2, alpha=0.7, scale=s)
            behind.alpha_composite(Image.fromarray(FX.rgb_split(np.asarray(ghost).copy(), 20, 0), "RGBA"))
        else:
            s = 1.0 + (0.06 if f == 1 else 0.012 * math.exp(-(dt - 2 / self.fps) * 9))
            T.place(behind, spr, x + vw / 2 - vw * s / 2, y + cap / 2 - cap * s / 2, alpha=1 - ex, scale=s)
        # label: letter reveal on its word, bottom-aligned to the numeral
        lt = d["label_t"]
        times = [lt + 0.03 * i for i in range(len(d["label"]))]
        ly = y + cap - T.cap_height(LABEL, lsize)
        if d.get("sub"):
            ly -= H * 0.075
        T.letters(front, d["label"], LABEL, lsize, x + vw + H * 0.04, ly, "yellow", 6, times, t, 0.1, alpha=1 - ex)
        if d.get("sub"):
            ssize = T.size_for_cap(SMALLCAPS, H * 0.04)
            p = anim.out_cubic(anim.prog(t, d["sub_t"], 0.25))
            if p > 0:
                T.place(front, T.sprite(d["sub"], SMALLCAPS, ssize, "cool", 5, 0.5), x + vw + H * 0.04,
                        y + cap - T.cap_height(SMALLCAPS, ssize) + 8 * (1 - p), alpha=p * (1 - ex))


FAMILIES = {"name": NameBehind, "headline": Headline, "numbered": Numbered, "minimal": Minimal,
            "label": ScrambleLabel, "cumulative": Cumulative, "impact": Impact}
LABELS = {"name": "1 · Behind-subject kinetic typography", "headline": "2 · Oversized cinematic headline",
          "numbered": "3 · Sequential numbered points", "minimal": "4 · Minimal storytelling transition",
          "label": "5 · Scramble date / venue labels", "cumulative": "6 · Layered cumulative statistics",
          "impact": "7 · Single-statistic impact"}


def make(el, W=1920, H=1080, fps=25):
    return FAMILIES[el.family](el, W, H, fps)

"""Temporally stable person mattes for behind-subject type (families 1 and 6).

Model: Robust Video Matting (Lin et al., 2021), MobileNetV3, run with onnxruntime on the CPU (on an Apple M1
the CPU provider is the reliable choice; CoreML can be slower and re-specialises on dynamic shapes).
RVM is recurrent: each frame's hidden state carries the previous frames, so the matte does not flicker
from frame to frame, which is what lets type sit *behind* a moving player for seconds at a time.

Optional by design: without onnxruntime or a model file, `available()` is False and the families draw their
type in front of the subject instead (the edit still renders).

Model files (either works; put one in casefile-studio/models/ or set CASEFILE_RVM_MODEL):
  rvm_mobilenetv3_fp32.onnx  the official export (github.com/PeterL1n/RobustVideoMatting releases v1.0.0):
                              NCHW input + downsample_ratio
  rvm_mobilenetv3_r1.onnx    an NHWC export of the same network without the internal resize (made from the
                              TF.js weights, see qa/sports-demos/REFERENCE-NOTES.md)
Mattes are computed once per (source, in, out, fps, size, model) and cached as uint8 .npy, so re-renders and
re-edits never run the network again.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]
MODEL_DIRS = [HERE / "models"]
NAMES = ("rvm_mobilenetv3_fp32.onnx", "rvm_mobilenetv3_r1.onnx")
MATTE_W = 640          # network width (360p for 16:9): RVM's recommended scale for HD sources
_SESSION = None


def model_path():
    env = os.environ.get("CASEFILE_RVM_MODEL")
    if env and Path(env).exists():
        return Path(env)
    for d in MODEL_DIRS:
        for n in NAMES:
            if (d / n).exists():
                return d / n
    return None


def _has_ort() -> bool:
    import importlib.util
    return importlib.util.find_spec("onnxruntime") is not None


def available() -> bool:
    return _has_ort() and model_path() is not None


def unavailable_reason() -> str:
    if not _has_ort():
        return "onnxruntime is not installed (pip install onnxruntime)"
    if model_path() is None:
        return "no RVM model in casefile-studio/models/ (rvm_mobilenetv3_fp32.onnx)"
    return ""


class _Net:
    def __init__(self, path: Path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 4))
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.s = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        ins = {i.name: i for i in self.s.get_inputs()}
        self.names = [o.name for o in self.s.get_outputs()]
        self.nchw = "downsample_ratio" in ins
        self.id = hashlib.sha1(path.read_bytes()[:1 << 20]).hexdigest()[:10]
        if self.nchw:
            self.rec = ["r1i", "r2i", "r3i", "r4i"]
        else:
            self.rec = [n for n in ("r1i:0", "r2i:0", "r3i:0", "r4i:0") if n in ins]
            self.ch = [16, 20, 40, 64]

    def reset(self):
        if self.nchw:
            return [np.zeros((1, 1, 1, 1), np.float32) for _ in range(4)]
        return [np.zeros((1, 1, 1, c), np.float32) for c in self.ch]

    def step(self, rgb: np.ndarray, rec):
        """rgb uint8 HxWx3 at network size -> (alpha float32 HxW, new state)."""
        x = rgb.astype(np.float32) / 255.0
        if self.nchw:
            feed = {"src": x.transpose(2, 0, 1)[None], "downsample_ratio": np.array([1.0], np.float32)}
            feed.update(dict(zip(self.rec, rec)))
            out = dict(zip(self.names, self.s.run(None, feed)))
            return out["pha"][0, 0], [out["r1o"], out["r2o"], out["r3o"], out["r4o"]]
        feed = {"src": x[None]}
        feed.update(dict(zip(self.rec, rec)))
        out = dict(zip(self.names, self.s.run(None, feed)))
        return out["pha"][0, ..., 0], [out["r1o"], out["r2o"], out["r3o"], out["r4o"]]


def net():
    global _SESSION
    if _SESSION is None:
        _SESSION = _Net(model_path())
    return _SESSION


def matte_frames(frames, warmup: int = 12):
    """Mattes for consecutive frames (uint8 HxWx3 at network size). The first `warmup` frames are run once
    beforehand so the recurrent state has settled when the shot starts (RVM needs ~15 frames to converge)."""
    n = net()
    rec = n.reset()
    frames = list(frames)
    for f in frames[:warmup]:
        _, rec = n.step(f, rec)
    out = []
    for f in frames:
        a, rec = n.step(f, rec)
        out.append((np.clip(a, 0, 1) * 255).astype(np.uint8))
    return out


def still(rgb: np.ndarray, passes: int = 10):
    """Matte for a photograph: the same image fed repeatedly lets the recurrent state converge."""
    return matte_frames([rgb] * passes, warmup=0)[-1]


def cache_key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def shot_mattes(reader, cache_dir: Path, key_parts, compute: bool = True) -> str | None:
    """Path of the cached uint8 [n, h, w] mattes for a shot (reader() gives network-size frames).
    compute=False: only a matte already in the cache (a quick preview never waits for segmentation)."""
    if not available():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / f"matte-{cache_key(*key_parts, net().id, MATTE_W)}.npy"
    if f.exists():
        return str(f)
    if not compute:
        return None
    arr = np.stack(matte_frames(reader()))
    tmp = f.with_name(f.stem + ".tmp.npy")
    np.save(tmp, arr)
    os.replace(tmp, f)
    return str(f)


def refine(a_small: np.ndarray, W: int, H: int, choke: float = 0.08) -> np.ndarray:
    """Network-size uint8 matte -> float32 HxW at output size: bilinear upscale, then a slight choke so
    type never shows a halo of the old background around the subject's edge."""
    from PIL import Image
    im = Image.fromarray(np.ascontiguousarray(a_small)).resize((W, H), Image.BILINEAR)
    a = np.asarray(im, np.float32) / 255.0
    return np.clip((a - choke) / (1 - 2 * choke), 0, 1)

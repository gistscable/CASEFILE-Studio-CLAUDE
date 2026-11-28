"""Sports editorial engine (v0.4.77): cinematic sports-documentary graphics composited INTO the footage.

Separate from the true-crime six (collections/truecrime.py) and from the overlay-card collections
(collections/football.py etc.). It shares the engine's timing, sound library, anim helpers and fonts.

Layers (see README.md in this folder):
  semantics.py  narration words -> editorial elements (intro names, dates, questions, stats...)
  matte.py      temporally stable person mattes (Robust Video Matting via onnxruntime, optional), cached
  footage.py    shot decoding, grading, photo animation
  typeset.py    cool-white condensed type sprites, masked wipes, scrambles, letter reveals
  families.py   the 7 graphics families (pure functions of time; behind/front layers + sfx cues)
  fx.py         RGB split, slice glitch, luma-matte dissolve, film look
  score.py      procedural music bed (emotional progression) and sports sfx
  edit.py       the edit: shots + transitions + persistent elements -> chunked, cached render + mix
"""

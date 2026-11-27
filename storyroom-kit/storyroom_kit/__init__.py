"""storyroom-kit: Casefile Studio's story-aware cinematic graphics, on their own, for Storyroom (or any editor).

    from storyroom_kit import make_plan, render_plan
    plan = make_plan(open("script.md").read(), srt=open("narration.srt").read(), photos="photos")
    render_plan(plan, "out")
"""
__version__ = "0.1.0"
ENGINE_FROM = "Casefile Studio v0.4.66"


def make_plan(*a, **k):
    from .plan import make
    return make(*a, **k)


def render_plan(*a, **k):
    from .export import render_plan as r
    return r(*a, **k)


def load_plan(path):
    from .plan import load
    return load(path)


def save_plan(plan, path):
    from .plan import save
    return save(plan, path)

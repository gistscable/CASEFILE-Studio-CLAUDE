"""Timings only say when the script's words are spoken; the words on screen are always the script's."""
import json

from storyroom_kit import plan as PL
from storyroom_kit import script as SC
from storyroom_kit import timings as TM

from conftest import KIT

RAW = (KIT / "examples" / "sheriff" / "script.md").read_text()


def _srt(narr, mangle=lambda w: w, shift=0.0):
    """An SRT of the narration, one caption per sentence, from the given word times (what a caption tool exports)."""
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    out = []
    for i, (t0, t1, idx) in enumerate(narr.times):
        words = " ".join(mangle(narr.words[k]["w"]) for k in idx)
        out.append(f"{i + 1}\n{ts(t0 + shift)} --> {ts(t1 + shift)}\n{words}\n")
    return "\n".join(out)


def test_estimated_timings_are_in_order_and_marked():
    narr = SC.narration(RAW)
    ts = [w["t"] for w in narr.words]
    assert ts == sorted(ts) and narr.timing["source"] == "estimated" and narr.timing["notes"]


def test_srt_times_the_script_words_even_when_the_transcript_misspells_them():
    base = SC.narration(RAW)
    swaps = {"Reed": "Read", "Whitfield": "Whitfeld", "Okafor": "Oka", "deputies": "deputys"}
    srt = _srt(base, mangle=lambda w: swaps.get(w.strip(".,’'s"), w), shift=12.0)
    narr = SC.narration(RAW, srt=srt)
    assert narr.timing["source"] == "srt" and narr.timing["matched"] > 0.9
    assert [w["w"] for w in narr.words] == [w["w"] for w in base.words]          # the script's words, not the transcript's
    assert abs(narr.words[0]["t"] - (base.words[0]["t"] + 12.0)) < 0.5
    plan = PL.make(RAW, srt=srt)
    assert len(plan["graphics"]) == 6
    for it in plan["graphics"]:
        assert "Read " not in it["text"] and "Whitfeld" not in it["text"]
        assert it["text"] in " ".join(s.text for s in narr.story.sentences)


def test_word_timings_in_common_shapes():
    base = SC.narration(RAW)
    words = [{"word": w["w"], "start": w["t"] + 3, "end": w["e"] + 3} for w in base.words]
    for data in (words, {"words": words}, {"segments": [{"words": words}]},
                 [{"text": w["word"], "start_ms": w["start"] * 1000, "end_ms": w["end"] * 1000} for w in words]):
        narr = SC.narration(RAW, words_json=json.loads(json.dumps(data)))
        assert narr.timing["matched"] > 0.99
        assert abs(narr.words[10]["t"] - (base.words[10]["t"] + 3)) < 0.01


def test_unmatched_words_are_timed_between_their_neighbours():
    script = ["She", "was", "15-year-old", "and", "gone."]
    heard = [("She", 0.0, 0.2), ("was", 0.2, 0.4), ("fifteen", 0.4, 0.7), ("year", 0.7, 0.9), ("old", 0.9, 1.1), ("and", 1.1, 1.3),
             ("gone", 1.3, 1.6)]
    times, m = TM.align(script, heard)
    assert times[2][0] >= 0.4 - 1e-6 and times[2][1] <= 1.1 + 1e-6
    assert times[3] == (1.1, 1.3) and m == 0.8


def test_a_wrong_srt_is_flagged():
    srt = "1\n00:00:01,000 --> 00:00:04,000\nSomething else entirely was said here.\n"
    narr = SC.narration(RAW, srt=srt)
    assert narr.timing["matched"] < 0.1 and any("check that they are for this script" in n for n in narr.timing["notes"])


def test_offset_moves_everything():
    a = PL.make(RAW)
    b = PL.make(RAW, offset=30.0)
    assert [round(y["start"] - x["start"], 2) for x, y in zip(a["graphics"], b["graphics"])] == [30.0] * 6

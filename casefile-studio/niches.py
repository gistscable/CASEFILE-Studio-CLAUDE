"""v0.4.76 Documentary niches: what kind of documentary a project is, and everything that follows from it.

A project carries `niche` (a key below). The niche decides, as defaults the producer can still change:

* the cinematic graphics collection the editor offers first (Motion -> Cinematic, `collection`),
* the sound design's flavour: which library families stand in for the generic ones (`sound.flavour`,
  e.g. football: a stadium crowd swell where a true-crime edit has a dark atmospheric swell),
* the music direction shown in the Music panel (a brief: the producer brings the track),
* the research focus and the writing / voice direction handed to the AI drafts,
* the picture look a new project starts with.

Projects made before v0.4.76 have no `niche`: they are true crime (what Casefile was made for), so nothing
about them changes. A niche never changes the narration, the timeline or anything already placed.
"""
from __future__ import annotations

DEFAULT = "truecrime"     # projects without a niche (everything made before v0.4.76)

# key, label, icon (lucide name, the editor's), one line, graphics collection, picture look
NICHES = [
    {
        "key": "truecrime", "label": "True Crime", "icon": "Fingerprint", "collection": "truecrime", "look": "noir",
        "about": "Cases, investigations, courts and their outcomes.",
        "title_hint": "Case name or working title",
        "graphics": "Investigative findings, timelines, conflicting accounts, legal outcomes, evidence logs, turning points.",
        "sound": {"about": "Dark tension: restrained investigative clicks, low pulses and controlled impacts.",
                  "preset": "cinematic", "flavour": {}},
        "music": "Dark, tense and restrained: low drones, sparse piano, slow pulses. Keep it well under the voice and let it "
                 "drop out for family and victim passages.",
        "research": "Prioritise court documents, official case records, reliable contemporaneous reporting and clearly "
                    "attributed interviews.",
        "voice": "Read in a calm, clear, respectful documentary voice. Measured pacing, natural pauses.",
    },
    {
        "key": "football", "label": "Football", "icon": "Trophy", "collection": "football", "look": "punchy",
        "about": "Players, clubs, tournaments, tactics and careers.",
        "title_hint": "Player, club or story",
        "graphics": "Player and team stats, the road to the final, tactical boards, rise-fall-and-redemption curves.",
        "sound": {"about": "Emotional, triumphant, tension, stadium atmosphere: crowd swells instead of dark drones.",
                  "preset": "cinematic", "flavour": {"swell": "crowd"}},
        "music": "Emotional and triumphant with real tension: building strings and drums for the big matches, a "
                 "lighter piano for the early years, a stadium-sized lift for the trophy.",
        "research": "Prioritise official match reports, league and federation statistics, club announcements, "
                    "reliable sports journalism and attributed interviews. Check every score, date and number.",
        "voice": "Read in a warm, engaged sports-documentary voice. Lift for the big moments, never shouting.",
    },
    {
        "key": "boxing", "label": "Boxing & MMA", "icon": "Swords", "collection": "combat", "look": "punchy",
        "about": "Fighters, fights, title reigns and rivalries.",
        "title_hint": "Fighter, fight or story",
        "graphics": "Tale of the tape, championship journeys, superstar legacies.",
        "sound": {"about": "Hard-hitting and tense: punch impacts, the ring bell, heavy hits for the knockouts.",
                  "preset": "intense", "flavour": {"transition-impact": "punch", "thump": "punch"}},
        "music": "Heavy, driving and tense: low percussion and brass for fight night, sparse and lonely for the "
                 "training camp and the losses.",
        "research": "Prioritise official records (BoxRec, the sanctioning bodies, the promotion), fight results with the "
                    "method and round, reliable combat-sports reporting and attributed interviews.",
        "voice": "Read in a strong, focused fight-documentary voice. Punchy, steady pace.",
    },
    {
        "key": "wrestling", "label": "Wrestling", "icon": "Medal", "collection": "combat", "look": "punchy",
        "about": "Superstars, championships, rivalries, returns and betrayals.",
        "title_hint": "Superstar or storyline",
        "graphics": "Superstar legacy walls, championship journeys, tale of the tape.",
        "sound": {"about": "Big-arena energy: crowd swells, booming arena hits for the returns and the betrayals.",
                  "preset": "intense", "flavour": {"transition-impact": "arena", "bass-impact": "arena", "swell": "crowd"}},
        "music": "Big, theatrical and anthemic: rock and orchestral hits for the entrances and title wins, a dark "
                 "turn for the betrayals.",
        "research": "Prioritise the promotion's official title histories and event results, reliable wrestling "
                    "journalism and attributed interviews. Say when a storyline was scripted.",
        "voice": "Read in a big, confident storyteller's voice. Dramatic, but every fact clear.",
    },
    {
        "key": "entertainment", "label": "Entertainment", "icon": "Clapperboard", "collection": "entertainment", "look": "warm",
        "about": "Stars, careers, fame, controversy and comebacks.",
        "title_hint": "Star, show or story",
        "graphics": "Career progression (the rise and the fall), achievements and cultural impact.",
        "sound": {"about": "Glossy and dramatic: camera flashes, sparkles for the awards, warm swells for the highs.",
                  "preset": "cinematic", "flavour": {"notification": "sparkle", "swell": "warm-swell"}},
        "music": "Glossy and cinematic: bright pop-orchestral for the rise, darker synths for the controversy, "
                 "a warm swell for the comeback.",
        "research": "Prioritise official charts and box-office figures, award bodies' records, reliable entertainment "
                    "journalism and attributed interviews. Separate rumour from what was confirmed.",
        "voice": "Read in a smooth, engaging entertainment-documentary voice. Light where the story is light.",
    },
    {
        "key": "history", "label": "History", "icon": "Landmark", "collection": "documentary", "look": "archive",
        "about": "Events, eras, empires and the people who shaped them.",
        "title_hint": "Event, era or person",
        "graphics": "Timelines of dated events, key figures, rise and fall.",
        "sound": {"about": "Epic and solemn: deep swells, archive-film projector texture, paper and documents.",
                  "preset": "subtle", "flavour": {"scan": "projector"}},
        "music": "Epic and solemn: orchestral strings, low choirs and period colour, never modern beats over the archive.",
        "research": "Prioritise primary sources, academic histories and reputable archives. Give dates precisely and "
                    "say where historians disagree.",
        "voice": "Read in an authoritative, unhurried history-documentary voice.",
    },
    {
        "key": "business", "label": "Business", "icon": "ChartLine", "collection": "documentary", "look": "natural",
        "about": "Companies, founders, deals, booms and collapses.",
        "title_hint": "Company, founder or deal",
        "graphics": "Rise and fall, key figures (revenue, staff, market share), timelines of dated events.",
        "sound": {"about": "Clean and modern: digital tickers, crisp clicks, rising tension for the deals and the crash.",
                  "preset": "cinematic", "flavour": {"notification": "ticker", "scan": "ticker"}},
        "music": "Clean, modern and driving: pulsing electronics and light percussion, tension for the deals and the fall.",
        "research": "Prioritise company filings, earnings reports, regulators' records, reliable business journalism "
                    "and attributed interviews. Give every figure with its date and currency.",
        "voice": "Read in a clear, confident business-documentary voice. Say the numbers slowly.",
    },
    {
        "key": "psychology", "label": "Psychology", "icon": "Brain", "collection": "documentary", "look": "cold",
        "about": "The mind, behaviour, experiments and inner lives.",
        "title_hint": "Topic or question",
        "graphics": "Key figures from the studies, timelines of dated events, rise and fall.",
        "sound": {"about": "Intimate and uneasy: heartbeats, soft pulses, quiet tension. Few effects.",
                  "preset": "subtle", "flavour": {"pulse": "heartbeat", "bass-impact": "heartbeat"}},
        "music": "Intimate and uneasy: soft pads, slow piano, sparse textures that leave room for thought.",
        "research": "Prioritise peer-reviewed studies, recognised experts and professional bodies. Say how strong the "
                    "evidence is and never diagnose real people.",
        "voice": "Read in a calm, thoughtful, intimate voice. Unhurried.",
    },
    {
        "key": "faith", "label": "Faith & Religion", "icon": "BookOpen", "collection": "documentary", "look": "warm",
        "about": "Belief, traditions, places and the people of faith.",
        "title_hint": "Tradition, figure or story",
        "graphics": "Timelines of dated events, key figures, rise and fall.",
        "sound": {"about": "Reverent and warm: soft warm swells, gentle bells, no hard hits.",
                  "preset": "subtle", "flavour": {"swell": "warm-swell", "pulse": "warm-swell",
                                                  "transition-impact": "warm-swell", "bass-impact": "warm-swell"}},
        "music": "Reverent and warm: choir, organ or strings, gentle and spacious. Respect each tradition's own music.",
        "research": "Prioritise the tradition's own texts and recognised scholars, reliable reporting and attributed "
                    "interviews. Present beliefs respectfully and attribute them.",
        "voice": "Read in a warm, respectful, reflective voice.",
    },
    {
        "key": "general", "label": "General Documentary", "icon": "Globe", "collection": "documentary", "look": "noir",
        "about": "Any other story: places, science, travel, society.",
        "title_hint": "Story or working title",
        "graphics": "Timelines of dated events, key figures, rise and fall.",
        "sound": {"about": "Balanced documentary sound: soft whooshes, clean clicks, gentle swells.",
                  "preset": "cinematic", "flavour": {}},
        "music": "Balanced documentary score: piano and strings with light pulses, following the story's mood.",
        "research": "Prioritise primary sources, official records, reputable reporting and attributed interviews.",
        "voice": "Read in a calm, clear documentary voice. Measured pacing, natural pauses.",
    },
]
BY_KEY = {n["key"]: n for n in NICHES}


def key_of(project) -> str:
    """The project's niche (true crime for projects made before niches existed)."""
    k = (project or {}).get("niche")
    return k if k in BY_KEY else DEFAULT


def get(project_or_key):
    if isinstance(project_or_key, str):
        return BY_KEY.get(project_or_key) or BY_KEY[DEFAULT]
    return BY_KEY[key_of(project_or_key)]


def normalise(value) -> str:
    """A niche key from the editor; anything unknown is refused (ValueError)."""
    if value not in BY_KEY:
        raise ValueError("Unknown documentary niche.")
    return value


def collection(project) -> str:
    """The cinematic collection the niche's graphics come from (true crime's when that collection is not installed)."""
    key = get(project)["collection"]
    try:
        from cinegfx import core
        return key if key in core.load_collections() else get(DEFAULT)["collection"]
    except ImportError:
        return key


def flavour(project) -> dict:
    """Library families that stand in for generic ones in this niche's automatic sound plan."""
    return dict(get(project)["sound"]["flavour"])


def catalog():
    """For the editor: every niche, in the order of the picker."""
    return {"default": DEFAULT, "niches": [
        {k: n[k] for k in ("key", "label", "icon", "about", "title_hint", "collection", "look", "graphics", "music")}
        | {"sound": {"about": n["sound"]["about"], "preset": n["sound"]["preset"], "flavour": dict(n["sound"]["flavour"])}}
        for n in NICHES]}

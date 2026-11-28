"""v0.4.76 Sample narration for the niche collections (tests and qa only): one script per niche, written the way a
documentary narrator writes, each with passages every category of its collection should find, and the project
builder the cinematic tests use (one scene per paragraph, at a narrator's pace)."""
from __future__ import annotations

import re

FOOTBALL = """# The Last Dance — Lionel Messi
## Chapter 1 — The numbers
Lionel Messi scored 672 goals in 778 games for Barcelona between 2004 and 2021. He added 303 assists and won 35 trophies with the club.
The fans could not believe what they were seeing. Every weekend felt like a new record. Opponents spoke about him with a kind of fear.
Nobody in the dressing room doubted who the team belonged to. The city had built its identity around one small man.

## Chapter 2 — The road to Paris
Liverpool's 2022 campaign in the Champions League was relentless. In the round of 16, Liverpool beat Inter Milan 2-1 on aggregate. In the quarter-final they knocked out Benfica 6-4 on aggregate. Liverpool beat Villarreal 5-2 on aggregate in the semi-final, but lost to Real Madrid 1-0 in the final.
The players walked off in silence. The supporters stayed long after the whistle. It was a season that deserved more.
Some of them would never get that close again. The dressing room was quiet for a long time.

## Chapter 3 — The system
Jurgen Klopp set up his side in a 4-3-3 formation built on a relentless high press. When they won the ball, they hit teams on the counter-attack, and the full-backs pushed forward down the right flank.
It changed English football. Other managers copied it within a season. Pundits called it heavy metal football.
Few teams could live with the intensity. The league had never seen anything quite like it.

## Chapter 4 — The arc
In 2009, Cristiano Ronaldo joined Real Madrid for a world-record fee. In 2014, Ronaldo suffered a serious knee injury that kept him out for months. In 2016, Ronaldo returned and won the European Championship with Portugal.
Nobody had written a story like it. His critics went quiet. The boy from Madeira had done it again.
"""

COMBAT = """# Iron — Mike Tyson
## Chapter 1 — The tape
Mike Tyson stood five feet ten inches tall, with a 71-inch reach and a record of 50 wins, 6 losses and 44 knockouts. Jake Paul stood six feet one inch, with a 76-inch reach and a record of 10 wins, 1 loss and 7 knockouts.
On paper it made no sense. The promoters sold it anyway. Millions of people bought the fight.
The arena was full hours before the first bell. Nobody knew what to expect.

## Chapter 2 — The belts
In 1986, Tyson defeated Trevor Berbick to win the WBC heavyweight title. In 1987, he beat James Smith for the WBA title and then defeated Tony Tucker to take the IBF belt. In 1990, he lost to Buster Douglas in Tokyo and the titles were gone.
The shock went around the world. Bookmakers had made Douglas a forty-two to one outsider. Nobody had seen it coming.
Tyson never quite recovered his aura. The years that followed were turbulent.

## Chapter 3 — The legacy
The Undertaker's rivalry with Shawn Michaels defined an era of wrestling. In 2009, he beat Michaels at WrestleMania in a match many still call the greatest ever. In 2014, his streak ended when Brock Lesnar pinned him. In 2020, he returned one final time before announcing his retirement.
The crowd fell silent when the streak ended. Fans still argue about that night.
His farewell was emotional. The lights went out for the last time.
"""

ENTERTAINMENT = """# Thriller — Michael Jackson
## Chapter 1 — From king to chaos
In 1982, Michael Jackson released Thriller and broke through to a global audience. In 1984, he won eight Grammy Awards in a single night. In 1993, he was accused of abuse and the scandal followed him for years. In 2001, he returned with Invincible and filled stadiums again.
Few careers have climbed so high or fallen so hard. Fans never stopped arguing about him.
The music outlived the headlines. The world kept dancing.

## Chapter 2 — The numbers
Thriller sold more than 70 million copies worldwide and spent 37 weeks at number one. It won 8 Grammy Awards, and its videos drew 500 million views on YouTube.
Critics called it the album that changed pop. Radio stations played it around the clock.
Other artists spent decades chasing it. Nothing quite caught up.
"""

DOCUMENTARY = """# The Empire That Sold Everything — Nokia
## Chapter 1 — The giant
By 2007, Nokia employed more than 100,000 people in 120 countries. It sold 437 million phones that year and held 40 per cent of the global market.
Executives believed the lead could never be lost. Analysts agreed. Few imagined what was coming.
The company had reinvented itself before. It expected to do so again.

## Chapter 2 — The fall
In 1998, Nokia became the world's largest phone maker. In 2007, Apple launched the iPhone and Nokia struggled to respond. In 2013, Nokia sold its phone business to Microsoft. In 2016, the brand returned under a new licence.
It was one of the fastest collapses in corporate history. Thousands of jobs went with it.
Finland felt the loss for years. A generation of engineers moved on.
"""


def project(script, niche="truecrime", title=None, subject=""):
    scenes, chapter = [], None
    for line in script.splitlines():
        m = re.match(r"## Chapter \d+ — (.+)", line)
        if m:
            chapter = m.group(1).strip().upper()
            continue
        if line.startswith("#"):
            continue
        if chapter and line.strip():
            words = line.split()
            scenes.append({"id": f"s{len(scenes)}", "title": "", "chapter": chapter, "narration": line.strip(),
                           "duration": round(len(words) * 0.38 + 0.4, 2)})
    head = next((ln[2:] for ln in script.splitlines() if ln.startswith("# ")), "")
    return {"id": "n-" + niche, "title": title or head, "topic": subject, "niche": niche, "created_at": "2026-11-24T09:00:00",
            "scenes": scenes, "assets": [], "motion": {"enabled": True, "items": []}}

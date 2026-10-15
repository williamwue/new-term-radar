"""What kind of thing a lead is, and whether it is a one-click tool waiting to be built.

Two habits of people who build tool sites for a living:
- the format sets the ceiling of what a visitor will pay for: video > voice > image > text;
- a manual workflow that people pass around (a tutorial, a prompt recipe, a trend everyone
  copies) is a tool nobody has built yet: "anything done by hand across a broken chain can
  be one button".
Both are read from the lead's own words (its name, the posts, the examples, the maker's own
description) by keyword rules. Cheap, and right often enough to sort a list; read the posts
before acting on a tag.
"""
from __future__ import annotations

import re

FORMATS = [
    ("video", re.compile(r"\b(?:videos?|clips?|animat\w*|film|movie|veo|sora|kling|hailuo|runway|seedance|"
                         r"lip ?sync|text[- ]to[- ]video|image[- ]to[- ]video|i2v|t2v)\b", re.I)),
    ("voice", re.compile(r"\b(?:voices?|tts|text[- ]to[- ]speech|speech|audio|music|songs?|singing|podcasts?|"
                         r"dubbing|transcri\w+|asr|sound)\b", re.I)),
    ("image", re.compile(r"\b(?:images?|photos?|pictures?|pics?|art|drawings?|illustrations?|portraits?|headshots?|"
                         r"logos?|stickers?|figurines?|anime|upscal\w*|backgrounds?|text[- ]to[- ]image|t2i|edit\w* photos?)\b",
                         re.I)),
]
RANK = {"video": 0, "voice": 1, "image": 2, "text": 3}
TUTORIAL = re.compile(r"\b(?:how to|step[- ]by[- ]step|step 1\b|tutorial|walkthrough|here'?s how|full prompt|"
                      r"prompts? (?:below|inside|included)|copy (?:this|my) prompt|prompt:)|🧵", re.I)
TREND = re.compile(r"\b(?:trend(?:ing)?|viral|everyone(?:'s| is) (?:making|doing|using|posting)|going viral|memes?)\b", re.I)
VIRAL = 1000                # likes: a tutorial nobody shared is not a demand signal
SHARE = 0.25                # a format named in at least this share of the posts (and two of them) counts


def own_words(lead: dict) -> str:
    """The thing's own words: its name, the examples, its maker's description."""
    about = lead.get("about") or ("", "")
    return " ".join([lead.get("term", ""), *lead.get("examples", []), about[1] if isinstance(about, (list, tuple)) else ""])


def fmt(lead: dict) -> str:
    """video, voice, image or text. Its own words decide first ("veo 3.1", "ai headshot"); otherwise the
    format the posts name most, if at least a quarter of them (and two) do; ties go to the costlier format."""
    mine = own_words(lead)
    for name, rx in FORMATS:
        if rx.search(mine):
            return name
    posts = lead.get("posts", [])
    counts = [(sum(1 for p in posts if rx.search(p.get("text", ""))), -RANK[name], name) for name, rx in FORMATS]
    n, _, name = max(counts)
    return name if n >= max(2, SHARE * len(posts)) else "text"


def one_click(posts: list[dict]) -> str | None:
    """"tutorial" when a post that walks through a manual workflow drew VIRAL likes, "trend" when a post
    riding a trend did; else None."""
    shared = [p.get("text", "") for p in posts if (p.get("likes") or 0) >= VIRAL]
    return "tutorial" if any(TUTORIAL.search(x) for x in shared) else "trend" if any(TREND.search(x) for x in shared) else None


def tag(lead: dict) -> dict:
    lead["format"], lead["one_click"] = fmt(lead), one_click(lead.get("posts", []))
    return lead

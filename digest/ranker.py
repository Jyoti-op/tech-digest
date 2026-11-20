"""Processing: canonicalize, dedupe, tag topics, score."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .sources import Story

TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid"}


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING])
    host = p.netloc.lower().removeprefix("www.")
    return urlunsplit(("https", host, p.path.rstrip("/"), query, ""))


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower())


def dedupe(stories: list[Story], threshold: float = 0.85) -> list[Story]:
    """Drop stories with the same canonical URL or a near-identical title.
    When duplicates collide, keep the one with more engagement/weight."""
    stories = sorted(stories, key=lambda s: (s.points + s.comments, s.weight), reverse=True)
    kept: list[Story] = []
    seen_urls: set[str] = set()
    for s in stories:
        s.url = canonical_url(s.url) if s.url.startswith("http") else s.url
        if s.url in seen_urls:
            continue
        nt = _norm_title(s.title)
        if any(SequenceMatcher(None, nt, _norm_title(k.title)).ratio() >= threshold for k in kept):
            continue
        seen_urls.add(s.url)
        kept.append(s)
    return kept


def tag_topic(title: str, topics: dict[str, list[str]]) -> str:
    t = f" {title.lower()} "
    best, best_hits = "General", 0
    for topic, words in topics.items():
        hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", t))
        if hits > best_hits:
            best, best_hits = topic, hits
    return best


def score(s: Story, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    age_h = max((now - s.published_at).total_seconds() / 3600, 0)
    freshness = 0.5 ** (age_h / 24)
    engagement = 1 + math.log10(1 + s.points + s.comments / 2)
    return round(s.weight * engagement * freshness, 4)


def process(stories: list[Story], topics: dict[str, list[str]], max_age_days: float | None = None) -> list[Story]:
    if max_age_days:
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
        stories = [s for s in stories if s.published_at.timestamp() >= cutoff]
    out = dedupe(stories)
    for s in out:
        s.topic = s.topic or tag_topic(f"{s.title} {s.summary}", topics)
        s.score = score(s)
    return sorted(out, key=lambda s: s.score, reverse=True)

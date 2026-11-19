"""Ingestion: fetch stories from Hacker News and RSS/Atom feeds."""
from __future__ import annotations

import html
import json
import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

log = logging.getLogger(__name__)
UA = {"User-Agent": "tech-digest/1.0"}
TIMEOUT = 10


@dataclass
class Story:
    title: str
    url: str
    source: str
    published_at: datetime
    points: int = 0
    comments: int = 0
    weight: float = 1.0
    topic: str = ""          # empty = auto-tag from keywords; set = forced by the source
    score: float = 0.0
    summary: str = ""
    extra: dict = field(default_factory=dict)


def _get(url: str) -> bytes:
    headers = dict(UA)
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"  # optional: higher rate limit
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


# ---------- Hacker News ----------
HN = "https://hacker-news.firebaseio.com/v0"


def _hn_item(item_id: int, weight: float) -> Story | None:
    try:
        d = json.loads(_get(f"{HN}/item/{item_id}.json"))
    except Exception as e:  # noqa: BLE001
        log.debug("HN item %s failed: %s", item_id, e)
        return None
    if not d or d.get("type") != "story" or not d.get("title"):
        return None
    url = d.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
    return Story(
        title=d["title"],
        url=url,
        source="Hacker News",
        published_at=datetime.fromtimestamp(d.get("time", 0), tz=timezone.utc),
        points=d.get("score", 0),
        comments=d.get("descendants", 0),
        weight=weight,
        extra={"discussion": f"https://news.ycombinator.com/item?id={item_id}"},
        summary=clean_text(d.get("text")),  # Ask/Show HN posts carry their own text
    )


def fetch_hackernews(limit: int = 40, weight: float = 1.2) -> list[Story]:
    ids = json.loads(_get(f"{HN}/topstories.json"))[:limit]
    with ThreadPoolExecutor(max_workers=10) as pool:
        return [s for s in pool.map(lambda i: _hn_item(i, weight), ids) if s]


# ---------- RSS / Atom ----------
ATOM = "{http://www.w3.org/2005/Atom}"


def _parse_date(text: str | None) -> datetime:
    if not text:
        return datetime.now(timezone.utc)
    text = text.strip()
    try:
        dt = parsedate_to_datetime(text)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def clean_text(raw: str | None, limit: int = 260) -> str:
    """Strip HTML tags/entities, collapse whitespace, cut at a word boundary."""
    if not raw:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(raw)))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def fetch_rss(name: str, url: str, weight: float = 1.0) -> list[Story]:
    root = ET.fromstring(_get(url))
    stories: list[Story] = []
    for it in root.iter("item"):  # RSS 2.0
        title, link = it.findtext("title"), it.findtext("link")
        if title and link:
            stories.append(Story(title.strip(), link.strip(), name,
                                 _parse_date(it.findtext("pubDate")), weight=weight,
                                 summary=clean_text(it.findtext("description"))))
    for e in root.iter(f"{ATOM}entry"):  # Atom
        title = e.findtext(f"{ATOM}title")
        link_el = e.find(f"{ATOM}link[@rel='alternate']")
        if link_el is None:
            link_el = e.find(f"{ATOM}link")
        link = link_el.get("href") if link_el is not None else None
        date = e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")
        body = e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content")
        if title and link:
            stories.append(Story(title.strip(), link.strip(), name, _parse_date(date), weight=weight,
                                 summary=clean_text(body)))
    return stories


# ---------- Summaries for stories whose source gives none (e.g. Hacker News) ----------
_META_RE = [
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:description|description|twitter:description)["\'][^>]*'
               r'content=["\']([^"\']{20,})["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']{20,})["\'][^>]*(?:property|name)=["\']'
               r'(?:og:description|description|twitter:description)["\']', re.I),
]


def _page_description(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={**UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=6) as r:
            if "html" not in (r.headers.get("Content-Type") or ""):
                return ""
            head = r.read(200_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    for rx in _META_RE:
        m = rx.search(head)
        if m and not GENERIC.search(m.group(1)):
            return clean_text(m.group(1))
    body = re.sub(r"<(script|style|nav|header|footer|svg)\b.*?</\1>", " ", head, flags=re.I | re.S)
    for p in re.findall(r"<p(?:\s[^>]*)?>(.*?)</p>", body, re.I | re.S):  # first real paragraph
        text = clean_text(p)
        if len(text) >= 80 and not GENERIC.search(text) and "Ctrl K" not in text:
            return text
    return ""


# Site-wide taglines that say nothing about the specific article
GENERIC = re.compile(
    r"we.re on a journey to advance|^a blog post by|try out artifacts|cookies|subscribe to our|"
    r"join the discussion on this|sign in|javascript is disabled|enable javascript|all rights reserved", re.I)


def enrich_summaries(stories: list[Story], limit: int = 120) -> None:
    """Fill missing summaries for the top `limit` stories by reading each page's description."""
    for s in stories:  # drop feed descriptions that are just boilerplate
        if s.summary and GENERIC.search(s.summary):
            s.summary = ""
    todo = [s for s in stories[:limit] if not s.summary and s.url.startswith("http")]
    with ThreadPoolExecutor(max_workers=16) as pool:
        for s, desc in zip(todo, pool.map(lambda s: _page_description(s.url), todo)):
            s.summary = desc
    log.info("Summaries: filled %d of %d missing", sum(1 for s in todo if s.summary), len(todo))


# ---------- Keyword searches & specialist sources ----------
def _iso(text: str | None) -> datetime:
    return _parse_date(text)


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _matches(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return not keywords or any(k.lower() in t for k in keywords)


def fetch_hn_search(src: dict) -> list[Story]:
    """Hacker News stories matching keyword queries (via Algolia), last N days."""
    since = int(_since(src.get("days", 3)).timestamp())
    out: list[Story] = []
    for q in src["queries"]:
        url = ("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=20"
               f"&numericFilters=created_at_i>{since}&query={quote(q)}")
        for h in json.loads(_get(url))["hits"]:
            if not h.get("title"):
                continue
            disc = f"https://news.ycombinator.com/item?id={h['objectID']}"
            out.append(Story(h["title"], h.get("url") or disc, src["name"],
                             datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
                             points=h.get("points") or 0, comments=h.get("num_comments") or 0,
                             weight=src.get("weight", 1.0), topic=src.get("topic", ""),
                             extra={"discussion": disc}, summary=clean_text(h.get("story_text"))))
    return out


def fetch_github_search(src: dict) -> list[Story]:
    """New GitHub repos matching each query, created in the last N days, by stars."""
    since = _since(src.get("days", 7)).date().isoformat()
    out: list[Story] = []
    for q in src["queries"]:
        url = ("https://api.github.com/search/repositories?sort=stars&order=desc&per_page="
               f"{src.get('per_query', 8)}&q={quote(q)}+created:>{since}")
        for r in json.loads(_get(url)).get("items", []):
            if r.get("stargazers_count", 0) < src.get("min_stars", 5):
                continue
            out.append(Story(f"{r['full_name']} ★{r['stargazers_count']}", r["html_url"], src["name"],
                             _iso(r.get("created_at")), points=r["stargazers_count"],
                             weight=src.get("weight", 1.0), topic=src.get("topic", ""),
                             summary=(r.get("description") or "")[:200]))
    return out


def fetch_mcp_registry(src: dict) -> list[Story]:
    """Servers newly published to the official MCP registry, filtered by keywords."""
    since = _since(src.get("days", 3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, cursor, seen = [], None, set()
    for _ in range(src.get("max_pages", 5)):
        url = f"https://registry.modelcontextprotocol.io/v0/servers?limit=100&updated_since={since}"
        if cursor:
            url += f"&cursor={quote(cursor)}"
        data = json.loads(_get(url))
        for entry in data.get("servers", []):
            s, meta = entry["server"], entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
            text = f"{s.get('name', '')} {s.get('title', '')} {s.get('description', '')}"
            if s["name"] in seen or not _matches(text, src.get("keywords", [])):
                continue
            seen.add(s["name"])
            link = s.get("websiteUrl") or (s.get("repository") or {}).get("url") \
                or f"https://registry.modelcontextprotocol.io/v0/servers?search={quote(s['name'])}"
            out.append(Story(f"New MCP server: {s.get('title') or s['name']}", link, src["name"],
                             _iso(meta.get("publishedAt")), weight=src.get("weight", 1.0),
                             topic=src.get("topic", "MCP"), summary=(s.get("description") or "")[:200]))
        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break
    return out


def fetch_hf_papers(src: dict) -> list[Story]:
    out = []
    for p in json.loads(_get(f"https://huggingface.co/api/daily_papers?limit={src.get('limit', 20)}")):
        paper = p["paper"]
        out.append(Story(f"📄 {paper['title']}", f"https://huggingface.co/papers/{paper['id']}", src["name"],
                         _iso(p.get("publishedAt")), points=paper.get("upvotes", 0),
                         comments=p.get("numComments", 0), weight=src.get("weight", 1.0),
                         topic=src.get("topic", "HuggingFace"), summary=(paper.get("summary") or "")[:200]))
    return out


def fetch_hf_trending(src: dict) -> list[Story]:
    """Trending Hugging Face models or spaces (kind = models | spaces)."""
    kind = src.get("kind", "models")
    url = f"https://huggingface.co/api/{kind}?sort=trendingScore&limit={src.get('limit', 10)}"
    if src.get("search"):
        url += f"&search={quote(src['search'])}"
    out = []
    for m in json.loads(_get(url)):
        label = m.get("pipeline_tag") or m.get("sdk") or kind[:-1]
        prefix = "" if kind == "models" else "spaces/"
        out.append(Story(f"🤗 Trending {kind[:-1]}: {m['id']} ({label})",
                         f"https://huggingface.co/{prefix}{m['id']}", src["name"],
                         _iso(m.get("createdAt")), points=m.get("trendingScore", 0) * 5,
                         weight=src.get("weight", 1.0), topic=src.get("topic", "HuggingFace"),
                         summary=f"{m.get('likes', 0)} likes · {m.get('downloads', 0)} downloads"
                         if kind == "models" else f"{m.get('likes', 0)} likes"))
    return out


EXTRA = {
    "hn_search": fetch_hn_search,
    "github_search": fetch_github_search,
    "mcp_registry": fetch_mcp_registry,
    "hf_papers": fetch_hf_papers,
    "hf_trending": fetch_hf_trending,
}


# ---------- Orchestration ----------
def fetch_all(cfg: dict) -> list[Story]:
    """Fetch every enabled source in parallel; a failing source is logged and skipped."""
    jobs = []
    hn = cfg.get("hackernews", {})
    if hn.get("enabled", True):
        jobs.append(("Hacker News", lambda: fetch_hackernews(hn.get("limit", 40), hn.get("weight", 1.2))))
    for f in cfg.get("rss_feeds", []):
        def rss_job(f=f):
            items = fetch_rss(f["name"], f["url"], f.get("weight", 1.0))
            for s in items:
                s.topic = f.get("topic", "")
            return items[: f.get("limit", 50)]
        jobs.append((f["name"], rss_job))
    for src in cfg.get("extra_sources", []):
        if src.get("enabled", True):
            jobs.append((src["name"], lambda src=src: EXTRA[src["type"]](src)))

    results: list[Story] = []
    with ThreadPoolExecutor(max_workers=len(jobs) or 1) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs}
        for fut, name in futures.items():
            try:
                items = fut.result()
                log.info("%-22s %3d stories", name, len(items))
                results.extend(items)
            except Exception as e:  # noqa: BLE001
                log.warning("%-22s FAILED: %s", name, e)
    return results

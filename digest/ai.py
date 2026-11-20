"""AI intelligence layer: turns a story into summary / explanation / why-it-matters / takeaways.

Providers (pick with config ai.provider or the AI_PROVIDER env var):
  ollama  - a free open-source model run by Ollama (used inside the GitHub Actions job; also works on your PC)
  openai  - OpenAI API (needs OPENAI_API_KEY)
  claude  - Anthropic Claude (needs ANTHROPIC_API_KEY and `pip install anthropic`)
  none    - no LLM: a free extractive write-up built from the article text
  auto    - ollama if a local Ollama server answers, else claude/openai if a key exists, else none
If an LLM call fails for any reason, that story falls back to the extractive write-up.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request

log = logging.getLogger(__name__)

SYSTEM = (
    "You write a weekly technology newsletter for developers, data engineers and AI practitioners. "
    "Explain at an intermediate level: assume programming knowledge, define niche terms briefly. "
    "Use ONLY facts from the article text provided; if the text is thin, say less rather than guess. "
    "Reply with a single JSON object and nothing else."
)

STORY_PROMPT = """Article
Title: {title}
Source: {source}
Topic: {topic}
URL: {url}
Text:
{text}

Candidate learning links (you may only pick resources from this list):
{links}

Return JSON with exactly these keys:
"short_summary": 1-2 sentences on what happened,
"technical_explanation": 2-4 sentences on how it works / what is technically interesting,
"why_it_matters": 1-2 sentences on relevance for developers, data engineers or AI practitioners,
"key_takeaways": list of 2-3 short bullet strings,
"resources": list of up to 3 objects {{"title": ..., "url": ...}} chosen from the candidate links"""

WEEKLY_PROMPT = """These are this week's selected technology stories:
{stories}

Return JSON with keys:
"takeaway": 2-3 sentences summarising the week's most important direction,
"explore": list of 3 short names of technologies worth exploring further this week"""


# ---------------------------------------------------------------- providers
def _openai_compatible(base_url: str, api_key: str | None, model: str, prompt: str, extra_headers=None,
                       timeout: int = 90) -> str:
    body = {"model": model, "temperature": 0.2, "max_tokens": 900,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        data = json.loads(raw)
    except ValueError:
        raise RuntimeError(f"provider returned non-JSON: {raw[:120]!r}") from None
    return data["choices"][0]["message"]["content"]


def _ollama_up(cfg: dict) -> bool:
    try:
        urllib.request.urlopen(cfg.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/tags", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def resolve_provider(cfg: dict) -> str:
    p = (os.environ.get("AI_PROVIDER") or cfg.get("provider") or "auto").lower()
    if p != "auto":
        return p
    if _ollama_up(cfg):
        return "ollama"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "none"


def complete(provider: str, cfg: dict, prompt: str) -> str:
    if provider == "openai":
        return _openai_compatible("https://api.openai.com/v1/chat/completions",
                                  os.environ["OPENAI_API_KEY"], cfg["openai_model"], prompt)
    if provider == "ollama":
        return _openai_compatible(cfg.get("ollama_url", "http://localhost:11434").rstrip("/") + "/v1/chat/completions",
                                  None, cfg["ollama_model"], prompt, timeout=600)
    if provider == "claude":
        from .ai_claude import complete_claude  # imported only when chosen
        return complete_claude(cfg["claude_model"], SYSTEM, prompt)
    raise ValueError(f"unknown AI provider {provider!r}")


# ---------------------------------------------------------------- helpers
def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ```json fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model reply")
    return json.loads(m.group(0))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 30]


def extractive(story: dict, text: str, links: list[dict]) -> dict:
    """Free, no-LLM write-up: summary from the feed, explanation from the article's own sentences."""
    summary = story.get("summary") or (_sentences(text)[:1] or [""])[0]
    rest = [s for s in _sentences(text) if s[:60] not in summary][:3]
    return {
        "short_summary": summary,
        "technical_explanation": " ".join(rest),
        "why_it_matters": "",
        "key_takeaways": [],
        "resources": links[:3],
        "generated_by": "extractive",
    }


def _clean(result: dict, story: dict, links: list[dict], provider: str) -> dict:
    allowed = {l["url"] for l in links} | {story["url"]}
    res = [r for r in result.get("resources") or []
           if isinstance(r, dict) and r.get("url") in allowed and r.get("url") != story["url"]][:3]
    takeaways = [str(t).strip() for t in result.get("key_takeaways") or [] if str(t).strip()][:3]
    return {
        "short_summary": str(result.get("short_summary") or story.get("summary") or "").strip(),
        "technical_explanation": str(result.get("technical_explanation") or "").strip(),
        "why_it_matters": str(result.get("why_it_matters") or "").strip(),
        "key_takeaways": takeaways,
        "resources": res,
        "generated_by": provider,
    }


# ---------------------------------------------------------------- public API
class Writer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.provider = resolve_provider(cfg)
        self._last_call = 0.0
        self.disabled_reason = ""
        self.failures = 0
        if self.provider == "ollama":
            self.cfg = {**cfg, "delay_seconds": 0}  # local model: no rate limit to respect
        log.info("AI provider: %s", self.provider)

    def _call(self, prompt: str) -> dict:
        wait = self.cfg.get("delay_seconds", 4) - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)  # stay inside free-tier rate limits
        try:
            return parse_json(complete(self.provider, self.cfg, prompt))
        finally:
            self._last_call = time.time()

    def write_story(self, story: dict, text: str, links: list[dict]) -> dict:
        if self.provider == "none" or self.disabled_reason or not (text or story.get("summary")):
            return extractive(story, text, links)
        prompt = STORY_PROMPT.format(
            title=story["title"], source=story["source"], topic=story["topic"], url=story["url"],
            text=(text or story.get("summary") or "")[: self.cfg.get("article_chars", 4000)],
            links="\n".join(f"- {l['title']}: {l['url']}" for l in links) or "(none)")
        try:
            return _clean(self._call(prompt), story, links, self.provider)
        except Exception as e:  # noqa: BLE001
            log.warning("AI write-up failed for %r (%s) — using extractive fallback", story["title"][:60], e)
            self.failures += 1
            if self.failures >= 3 or any(c in str(e) for c in ("401", "403", "404", "429", "non-JSON")):
                self.disabled_reason = str(e)  # stop calling a provider that keeps failing
            return extractive(story, text, links)

    def weekly_takeaway(self, stories: list[dict]) -> dict:
        topics: dict[str, int] = {}
        for s in stories:
            topics[s["topic"]] = topics.get(s["topic"], 0) + 1
        fallback = {"takeaway": "This week's biggest themes: " + ", ".join(
            f"{t} ({n})" for t, n in sorted(topics.items(), key=lambda x: -x[1])) + ".",
            "explore": [s["title"][:60] for s in stories[:3]]}
        if self.provider == "none" or self.disabled_reason:
            return fallback
        listing = "\n".join(f"- [{s['topic']}] {s['title']}: {s.get('ai', {}).get('short_summary', '')}" for s in stories)
        try:
            out = self._call(WEEKLY_PROMPT.format(stories=listing))
            return {"takeaway": str(out.get("takeaway", "")).strip() or fallback["takeaway"],
                    "explore": [str(x) for x in out.get("explore") or []][:3] or fallback["explore"]}
        except Exception as e:  # noqa: BLE001
            log.warning("Weekly takeaway failed (%s) — using fallback", e)
            return fallback

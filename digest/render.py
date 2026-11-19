"""Composer: render a subscriber's digest as HTML and plain text."""
from __future__ import annotations

import html
from collections import OrderedDict
from datetime import datetime

TOPIC_COLORS = {
    "MCP": "#0f766e", "Automation": "#b45309", "HuggingFace": "#ca8a04",
    "AI": "#7c3aed", "Security": "#dc2626", "Dev": "#2563eb", "Cloud": "#0891b2",
    "Hardware": "#ea580c", "Startups": "#16a34a", "General": "#6b7280",
}


def _group(items, order: list[str] | None = None) -> "OrderedDict[str, list]":
    """Group by topic; the subscriber's own topics come first, in the order they chose."""
    groups: OrderedDict[str, list] = OrderedDict((t, []) for t in (order or []))
    for it in items:
        groups.setdefault(it["topic"], []).append(it)
    return OrderedDict((k, v) for k, v in groups.items() if v)


def _summary(r) -> str:
    try:
        return r["summary"] or ""
    except (IndexError, KeyError):
        return ""


def render_html(items, sub, unsubscribe_base: str = "https://example.com/unsubscribe") -> str:
    date = datetime.now().strftime("%A, %d %B %Y")
    sections = []
    order = [t for t in sub["topics"].split(",") if t]
    for topic, rows in _group(items, order).items():
        color = TOPIC_COLORS.get(topic, "#6b7280")
        lis = "".join(
            f'<li style="margin:0 0 14px"><a href="{html.escape(r["url"])}" '
            f'style="color:#111827;font-weight:600;text-decoration:none">{html.escape(r["title"])}</a>'
            + (f'<div style="color:#374151;font-size:13px;margin-top:2px">{html.escape(_summary(r))}</div>'
               if _summary(r) else "")
            + f'<div style="color:#6b7280;font-size:12px">{html.escape(r["source"])}</div></li>'
            for r in rows
        )
        sections.append(
            f'<h2 style="font-size:14px;letter-spacing:.05em;text-transform:uppercase;color:{color};'
            f'border-bottom:2px solid {color};padding-bottom:4px;margin:24px 0 12px">{topic}</h2>'
            f'<ul style="list-style:none;padding:0;margin:0">{lis}</ul>'
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Tech Digest</title></head>
<body style="margin:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,sans-serif">
  <div style="max-width:600px;margin:0 auto;background:#fff;padding:24px 28px">
    <h1 style="margin:0;font-size:24px">⚡ Tech Digest</h1>
    <div style="color:#6b7280;font-size:13px">{date} · {len(items)} stories</div>
    {''.join(sections) or '<p>No new stories today.</p>'}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:28px 0 12px">
    <div style="color:#9ca3af;font-size:11px">
      Sent to {html.escape(sub['email'])} · {sub['frequency']} ·
      <a href="{unsubscribe_base}?token={sub['token']}" style="color:#9ca3af">Unsubscribe</a>
    </div>
  </div>
</body></html>"""


def render_text(items, sub) -> str:
    lines = [f"TECH DIGEST — {datetime.now():%d %b %Y}", ""]
    for topic, rows in _group(items, [t for t in sub["topics"].split(",") if t]).items():
        lines.append(f"== {topic} ==")
        lines += [f"- {r['title']} ({r['source']})\n" + (f"  {_summary(r)}\n" if _summary(r) else "")
                  + f"  {r['url']}" for r in rows]
        lines.append("")
    lines.append(f"Unsubscribe token: {sub['token']}")
    return "\n".join(lines)

"""Newsletter generation: weekly HTML + plain-text email.

Layout: highlights → per-topic stories (summary, how it works, why it matters,
key takeaways, learning resources) → weekly technology takeaway.
"""
from __future__ import annotations

import html
from collections import OrderedDict
from datetime import datetime

TOPIC_COLORS = {
    "MCP": "#0f766e", "AI": "#7c3aed", "Automation": "#b45309", "Dev": "#2563eb",
    "Data Engineering": "#0891b2", "Cloud/DevOps": "#4f46e5", "Dev Tools": "#16a34a",
    "Emerging": "#db2777", "General": "#6b7280",
}
E = html.escape


def _group(items, order: list[str]) -> "OrderedDict[str, list]":
    groups: OrderedDict[str, list] = OrderedDict((t, []) for t in order)
    for it in items:
        groups.setdefault(it["topic"], []).append(it)
    return OrderedDict((k, v) for k, v in groups.items() if v)


def _label(text: str, color: str) -> str:
    return (f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
            f'color:{color};margin:10px 0 2px">{text}</div>')


def _story_html(r: dict, color: str) -> str:
    a = r.get("ai") or {}
    parts = [f'<a href="{E(r["url"])}" style="color:#111827;font-size:16px;font-weight:700;'
             f'text-decoration:none">{E(r["title"])}</a>',
             f'<div style="color:#6b7280;font-size:12px;margin-top:2px">{E(r["source"])}</div>']
    if a.get("short_summary"):
        parts.append(f'<p style="margin:8px 0 0;color:#111827;font-size:14px;line-height:1.5">{E(a["short_summary"])}</p>')
    if a.get("technical_explanation"):
        parts.append(_label("How it works", color)
                     + f'<p style="margin:0;color:#374151;font-size:14px;line-height:1.5">{E(a["technical_explanation"])}</p>')
    if a.get("why_it_matters"):
        parts.append(_label("Why it matters", color)
                     + f'<p style="margin:0;color:#374151;font-size:14px;line-height:1.5">{E(a["why_it_matters"])}</p>')
    if a.get("key_takeaways"):
        lis = "".join(f'<li style="margin:2px 0">{E(t)}</li>' for t in a["key_takeaways"])
        parts.append(_label("Key takeaways", color)
                     + f'<ul style="margin:0;padding-left:18px;color:#374151;font-size:14px;line-height:1.5">{lis}</ul>')
    links = [{"title": "Original announcement", "url": r["url"]}] + list(a.get("resources") or [])
    parts.append(_label("Learn more", color) + '<div style="font-size:13px;line-height:1.6">' + " · ".join(
        f'<a href="{E(l["url"])}" style="color:{color}">{E(l["title"])}</a>' for l in links) + "</div>")
    return ('<div style="border:1px solid #e5e7eb;border-left:4px solid ' + color
            + ';border-radius:8px;padding:14px 16px;margin:0 0 14px">' + "".join(parts) + "</div>")


def render_html(items, sub, order: list[str], weekly: dict, name: str = "TechPulse",
                unsubscribe_base: str = "https://example.com/unsubscribe") -> str:
    date = datetime.now().strftime("%A, %d %B %Y")
    highlights = "".join(
        f'<li style="margin:4px 0"><a href="#s{r["id"]}" style="color:#111827;text-decoration:none">'
        f'<b style="color:{TOPIC_COLORS.get(r["topic"], "#6b7280")}">{E(r["topic"])}</b> · {E(r["title"])}</a></li>'
        for r in items[:3])
    sections = []
    for topic, rows in _group(items, order).items():
        color = TOPIC_COLORS.get(topic, "#6b7280")
        cards = "".join(f'<a name="s{r["id"]}"></a>' + _story_html(r, color) for r in rows)
        sections.append(
            f'<h2 style="font-size:14px;letter-spacing:.05em;text-transform:uppercase;color:{color};'
            f'border-bottom:2px solid {color};padding-bottom:4px;margin:26px 0 12px">{E(topic)}</h2>{cards}')
    explore = "".join(f'<li style="margin:2px 0">{E(x)}</li>' for x in weekly.get("explore", []))
    minutes = max(3, round(len(items) * 1.1))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{E(name)}</title></head>
<body style="margin:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,sans-serif">
  <div style="max-width:640px;margin:0 auto;background:#fff;padding:24px 28px">
    <h1 style="margin:0;font-size:24px">⚡ {E(name)}</h1>
    <div style="color:#6b7280;font-size:13px">{date} · {len(items)} updates · ~{minutes} min read</div>
    <div style="background:#f9fafb;border-radius:8px;padding:12px 16px;margin:18px 0 0">
      <div style="font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#111827">This week's highlights</div>
      <ol style="margin:6px 0 0;padding-left:20px;font-size:14px">{highlights}</ol>
    </div>
    {''.join(sections) or '<p>No new stories this week.</p>'}
    <div style="background:#111827;color:#f9fafb;border-radius:8px;padding:16px 18px;margin:26px 0 0">
      <div style="font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#a5b4fc">Weekly technology takeaway</div>
      <p style="margin:6px 0 0;font-size:14px;line-height:1.5">{E(weekly.get("takeaway", ""))}</p>
      {f'<div style="font-size:13px;margin-top:8px;color:#c7d2fe">Worth exploring:</div><ul style="margin:4px 0 0;padding-left:18px;font-size:14px">{explore}</ul>' if explore else ''}
    </div>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:28px 0 12px">
    <div style="color:#9ca3af;font-size:11px">
      Sent to {E(sub['email'])} · weekly ·
      <a href="{unsubscribe_base}?token={sub['token']}" style="color:#9ca3af">Unsubscribe</a>
    </div>
  </div>
</body></html>"""


def render_text(items, sub, order: list[str], weekly: dict, name: str = "TechPulse") -> str:
    lines = [f"{name.upper()} — week of {datetime.now():%d %b %Y}", ""]
    for topic, rows in _group(items, order).items():
        lines.append(f"== {topic} ==")
        for r in rows:
            a = r.get("ai") or {}
            lines.append(f"* {r['title']} ({r['source']})")
            for label, key in (("", "short_summary"), ("How it works: ", "technical_explanation"),
                               ("Why it matters: ", "why_it_matters")):
                if a.get(key):
                    lines.append(f"  {label}{a[key]}")
            lines += [f"  - {t}" for t in a.get("key_takeaways") or []]
            lines.append(f"  {r['url']}")
            lines += [f"  {l['title']}: {l['url']}" for l in a.get("resources") or []]
            lines.append("")
    lines += ["== Weekly takeaway ==", weekly.get("takeaway", "")]
    lines += [f"- {x}" for x in weekly.get("explore", [])]
    lines += ["", f"Unsubscribe token: {sub['token']}"]
    return "\n".join(lines)

"""Command-line entry point: subscribe, unsubscribe, list, run."""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from . import ai, mailer, ranker, render, sources
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from .env into the environment (real env vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    smtp = cfg.setdefault("smtp", {})
    # Environment overrides, so secrets never live in config.json (used by GitHub Actions too)
    for key, env in (("host", "DIGEST_SMTP_HOST"), ("port", "DIGEST_SMTP_PORT"),
                     ("username", "DIGEST_SMTP_USER"), ("from", "DIGEST_FROM")):
        if os.environ.get(env):
            smtp[key] = int(os.environ[env]) if key == "port" else os.environ[env]
    if smtp.get("username") and "example.com" in smtp.get("from", ""):
        smtp["from"] = f"Tech Digest <{smtp['username']}>"
    return cfg


def sync_subscribers_from_env(store: Store) -> None:
    """DIGEST_SUBSCRIBERS="a@x.com|MCP,AI|daily; b@y.com||weekly" — keeps the list out of git."""
    raw = os.environ.get("DIGEST_SUBSCRIBERS", "").strip()
    for entry in filter(None, (e.strip() for e in raw.split(";"))):
        parts = [p.strip() for p in entry.split("|")] + ["", ""]
        email, topics, freq = parts[0], parts[1], parts[2] or "daily"
        store.subscribe(email, [t for t in topics.split(",") if t], freq)
    if raw:
        logging.info("Synced %d subscriber(s) from DIGEST_SUBSCRIBERS", len([e for e in raw.split(";") if e.strip()]))


def pick_balanced(rows, total: int, per_topic: int) -> list:
    """Highest-scored first, but no single topic may take more than `per_topic` slots."""
    picked, counts = [], {}
    for r in rows:  # rows arrive sorted by score
        if counts.get(r["topic"], 0) < per_topic:
            picked.append(r)
            counts[r["topic"]] = counts.get(r["topic"], 0) + 1
            if len(picked) >= total:
                break
    return picked


def is_scheduled_time(sched: dict, now_utc: datetime | None = None) -> bool:
    """True when local time (e.g. Europe/Berlin) is the configured weekday + hour.
    GitHub cron is UTC-only, so the workflow fires at both possible UTC hours and this picks the right one."""
    from zoneinfo import ZoneInfo
    local = (now_utc or datetime.now(timezone.utc)).astimezone(ZoneInfo(sched["timezone"]))
    return local.strftime("%A") == sched["weekday"] and local.hour == sched["hour"]


def subscriber_topics(sub, cfg: dict) -> list[str]:
    """The subscriber's topics that exist in config; none chosen means all configured topics
    (never 'General', so off-topic front-page stories stay out)."""
    return [t for t in sub["topics"].split(",") if t in cfg["topics"]] or list(cfg["topics"])


def ensure_ai(rows, store: Store, writer: ai.Writer, cfg: dict) -> list[dict]:
    """Attach an AI write-up to each story, generating (and caching) it only when missing."""
    out = []
    for r in rows:
        story = dict(r)
        cached = json.loads(story["ai"]) if story.get("ai") else None
        if not cached or (cached.get("generated_by") == "extractive" and writer.provider != "none"
                          and not writer.disabled_reason):
            text, links = sources.fetch_article(story["url"], cfg["ai"].get("article_chars", 4000))
            cached = writer.write_story(story, text, links)
            store.save_ai(story["id"], cached)
            logging.info("  write-up [%s] %s", cached["generated_by"], story["title"][:70])
        story["ai"] = cached
        out.append(story)
    return out


def cmd_run(cfg: dict, store: Store, send: bool, force: bool) -> None:
    logging.info("Fetching sources…")
    raw = sources.fetch_all(cfg)
    ranked = ranker.process(raw, cfg["topics"], cfg.get("max_age_days"))
    logging.info("Fetched %d raw → %d unique recent stories", len(raw), len(ranked))
    sources.enrich_summaries(ranked, cfg.get("summarize_top", 150))
    store.upsert_items(ranked)

    failures = 0
    subs = store.due_subscribers(force=force)
    if not subs:
        logging.info("No subscribers due. Add one: python main.py subscribe you@example.com")
        return
    writer = ai.Writer(cfg["ai"])
    name = cfg.get("newsletter_name", "TechPulse")
    for sub in subs:
        topics = subscriber_topics(sub, cfg)
        rows = pick_balanced(store.unsent_items(sub["id"], topics, cfg.get("lookback_hours", 192), 500),
                             cfg.get("max_items_per_digest", 10), cfg.get("max_items_per_topic", 3))
        if not rows:
            logging.info("%s: nothing new", sub["email"])
            continue
        items = ensure_ai(rows, store, writer, cfg)
        weekly = writer.weekly_takeaway(items)
        order = topics
        html_body = render.render_html(items, sub, order, weekly, name)
        text_body = render.render_text(items, sub, order, weekly, name)
        subject = f"{name} · week of {datetime.now():%d %b} · {items[0]['title'][:55]}"
        if send:
            try:
                mailer.send_smtp(cfg["smtp"], sub["email"], subject, html_body, text_body)
            except Exception as e:  # noqa: BLE001 — one bad address must not stop the others
                logging.error("%s: SEND FAILED (%s) — will retry next run", sub["email"], e)
                failures += 1
                continue
            logging.info("%s: SENT %d stories", sub["email"], len(items))
        else:
            path = mailer.write_preview(str(ROOT / cfg["output_dir"]), sub["email"], html_body)
            logging.info("%s: %d stories → %s", sub["email"], len(items), path)
        store.record_delivery(sub["id"], [i["id"] for i in items])
    if failures:
        raise SystemExit(f"{failures} digest(s) failed to send")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tech-digest", description="Tech digest newsletter")
    p.add_argument("--config", default=str(ROOT / "config.json"))
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("subscribe", help="add or update a subscriber")
    s.add_argument("email")
    s.add_argument("--topics", default="", help='comma list, e.g. "MCP,AI,Data Engineering" (empty = all)')
    s.add_argument("--frequency", choices=["daily", "weekly"], default="weekly")

    u = sp.add_parser("unsubscribe", help="deactivate by email or token")
    u.add_argument("email_or_token")

    sp.add_parser("list", help="list subscribers")

    r = sp.add_parser("run", help="fetch, rank and deliver digests")
    r.add_argument("--send", action="store_true", help="really send via SMTP (default: write HTML previews)")
    r.add_argument("--force", action="store_true", help="ignore frequency schedule")
    r.add_argument("--scheduled", action="store_true",
                   help="only run if it is now the configured local weekday+hour (used by the cron job)")

    t = sp.add_parser("test-email", help="send one short test email to check SMTP settings")
    t.add_argument("to")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    load_dotenv(ROOT / ".env")
    cfg = load_config(args.config)
    store = Store(str(ROOT / cfg["db_path"]))
    sync_subscribers_from_env(store)

    if args.cmd == "test-email":
        mailer.send_smtp(cfg["smtp"], args.to, "Tech Digest: test email",
                         "<p>✅ Your Tech Digest email setup works.</p>", "Your Tech Digest email setup works.")
        print(f"Test email sent to {args.to} — check your inbox (and spam folder).")
        return

    if args.cmd == "subscribe":
        topics = [t.strip() for t in args.topics.split(",") if t.strip()]
        bad = [t for t in topics if t not in cfg["topics"] and t != "General"]
        if bad:
            p.error(f"unknown topics {bad}; choose from {list(cfg['topics']) + ['General']}")
        store.subscribe(args.email, topics, args.frequency)
        print(f"Subscribed {args.email} ({args.frequency}, topics: {', '.join(topics) or 'all'})")
    elif args.cmd == "unsubscribe":
        print("Unsubscribed." if store.unsubscribe(args.email_or_token) else "Not found.")
    elif args.cmd == "list":
        for s in store.subscribers(only_active=False):
            print(f"{'✓' if s['active'] else '✗'} {s['email']:<30} {s['frequency']:<7} {s['topics'] or 'all'}")
    elif args.cmd == "run":
        if args.scheduled and not is_scheduled_time(cfg["schedule"]):
            s = cfg["schedule"]
            print(f"Not {s['weekday']} {s['hour']}:00 in {s['timezone']} right now — skipping this trigger.")
            return
        cmd_run(cfg, store, send=args.send, force=args.force)

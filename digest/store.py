"""Storage: SQLite tables for items, subscribers and deliveries."""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from .sources import Story

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    source TEXT, topic TEXT, score REAL,
    published_at TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    topics TEXT NOT NULL DEFAULT '',          -- comma separated; empty = all
    frequency TEXT NOT NULL DEFAULT 'daily',  -- daily | weekly
    token TEXT NOT NULL,                      -- unsubscribe token
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_sent_at TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
    subscriber_id INTEGER NOT NULL REFERENCES subscribers(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    sent_at TEXT NOT NULL,
    PRIMARY KEY (subscriber_id, item_id)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(items)")}
        if "summary" not in cols:  # migrate databases created before summaries existed
            self.db.execute("ALTER TABLE items ADD COLUMN summary TEXT DEFAULT ''")
        if "ai" not in cols:  # cached AI write-up (JSON), so a story is only processed once
            self.db.execute("ALTER TABLE items ADD COLUMN ai TEXT")

    def save_ai(self, item_id: int, ai: dict) -> None:
        self.db.execute("UPDATE items SET ai=? WHERE id=?", (json.dumps(ai), item_id))
        self.db.commit()

    # ----- items -----
    def upsert_items(self, stories: list[Story]) -> None:
        self.db.executemany(
            """INSERT INTO items(url,title,source,topic,score,published_at,fetched_at,summary)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(url) DO UPDATE SET score=excluded.score, topic=excluded.topic,
                   title=excluded.title, summary=excluded.summary, fetched_at=excluded.fetched_at""",
            [(s.url, s.title, s.source, s.topic, s.score, s.published_at.isoformat(), now(), s.summary)
             for s in stories],
        )
        self.db.commit()

    def unsent_items(self, sub_id: int, topics: list[str], since_hours: int, limit: int) -> list[sqlite3.Row]:
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        sql = """SELECT * FROM items i
                 WHERE i.fetched_at >= ?
                   AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.subscriber_id=? AND d.item_id=i.id)"""
        args: list = [since, sub_id]
        if topics:
            sql += f" AND i.topic IN ({','.join('?' * len(topics))})"
            args += topics
        sql += " ORDER BY i.score DESC LIMIT ?"
        args.append(limit)
        return self.db.execute(sql, args).fetchall()

    # ----- subscribers -----
    def subscribe(self, email: str, topics: list[str], frequency: str) -> None:
        self.db.execute(
            """INSERT INTO subscribers(email,topics,frequency,token,created_at) VALUES(?,?,?,?,?)
               ON CONFLICT(email) DO UPDATE SET topics=excluded.topics, frequency=excluded.frequency, active=1""",
            (email.lower(), ",".join(topics), frequency, secrets.token_urlsafe(16), now()),
        )
        self.db.commit()

    def unsubscribe(self, email_or_token: str) -> bool:
        cur = self.db.execute("UPDATE subscribers SET active=0 WHERE email=? OR token=?",
                              (email_or_token.lower(), email_or_token))
        self.db.commit()
        return cur.rowcount > 0

    def subscribers(self, only_active: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM subscribers" + (" WHERE active=1" if only_active else "")
        return self.db.execute(q).fetchall()

    def due_subscribers(self, force: bool = False) -> list[sqlite3.Row]:
        out = []
        for s in self.subscribers():
            if force or not s["last_sent_at"]:
                out.append(s)
                continue
            gap = timedelta(days=7 if s["frequency"] == "weekly" else 1) - timedelta(hours=1)
            if datetime.now(timezone.utc) - datetime.fromisoformat(s["last_sent_at"]) >= gap:
                out.append(s)
        return out

    def record_delivery(self, sub_id: int, item_ids: list[int]) -> None:
        ts = now()
        self.db.executemany("INSERT OR IGNORE INTO deliveries VALUES(?,?,?)", [(sub_id, i, ts) for i in item_ids])
        self.db.execute("UPDATE subscribers SET last_sent_at=? WHERE id=?", (ts, sub_id))
        self.db.commit()

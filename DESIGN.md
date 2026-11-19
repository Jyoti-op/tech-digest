# Tech Digest Newsletter — System Design

## 1. Goal
Collect the day's most important tech stories from several sources, remove duplicates,
rank and group them by topic, and send each subscriber one clean digest email
(daily or weekly) with only the topics they care about.

## 2. Requirements

**Functional**
- Pull stories from multiple sources (Hacker News API, RSS/Atom feeds).
- Deduplicate (same URL, or near-identical titles across sources).
- Score and rank stories; tag each with a topic (AI, Security, Dev, Cloud, Hardware, Startups…).
- Subscribers sign up with email, topics, and frequency (daily / weekly).
- Render an HTML + plain-text email per subscriber; never send the same story twice.
- One-click unsubscribe.

**Non-functional**
- Idempotent runs (re-running a day doesn't double-send).
- A failing source must not break the whole digest.
- Runs on a schedule (cron / Task Scheduler / cloud job).

## 3. Architecture

```
          ┌────────────── Scheduler (cron / Task Scheduler) ──────────────┐
          ▼                                                               │
 ┌─────────────────┐   raw items   ┌──────────────┐  ranked items  ┌──────────────┐
 │  Ingestion      │ ────────────▶ │  Processing  │ ─────────────▶ │  Composer    │
 │  - HN API       │               │  - normalize │                │  - per-user  │
 │  - RSS feeds    │               │  - dedupe    │                │    filtering │
 │  (parallel,     │               │  - topic tag │                │  - HTML/text │
 │   timeouts)     │               │  - score     │                │    templates │
 └─────────────────┘               └──────┬───────┘                └──────┬───────┘
                                          │                               │
                                          ▼                               ▼
                                   ┌──────────────┐               ┌──────────────┐
                                   │  Storage     │◀──────────────│  Delivery    │
                                   │  SQLite/PG   │  sent log     │  SMTP / SES  │
                                   │  items,      │               │  (or files   │
                                   │  subscribers,│               │   in dry-run)│
                                   │  deliveries  │               └──────────────┘
                                   └──────────────┘
```

## 4. Components

| Component  | Responsibility | This repo |
|------------|----------------|-----------|
| Ingestion  | Fetch sources concurrently with timeouts; isolate failures | `digest/sources.py` |
| Processing | URL canonicalization, title-similarity dedupe, keyword topic tagging, scoring | `digest/ranker.py` |
| Storage    | `items`, `subscribers`, `deliveries` tables | `digest/store.py` |
| Composer   | Filter by subscriber topics, exclude already-sent, render templates | `digest/render.py` |
| Delivery   | SMTP send, or write `.html` files in dry-run | `digest/mailer.py` |
| CLI / Jobs | `subscribe`, `unsubscribe`, `list`, `run` | `digest/cli.py` |

## 5. Data model

```
items(id PK, url UNIQUE, title, source, topic, score, published_at, fetched_at)
subscribers(id PK, email UNIQUE, topics CSV, frequency, token, active, created_at)
deliveries(subscriber_id, item_id, sent_at, PK(subscriber_id, item_id))
```

`deliveries` is what makes runs idempotent: a story is only included if no
row exists for (subscriber, item).

## 6. Ranking

```
score = source_weight × (1 + log10(1 + points + comments/2)) × freshness
freshness = 0.5 ^ (age_hours / 24)        # half-life of one day
```
RSS items have no points, so they rely on source weight and freshness.
Topic = the topic whose keyword list has the most hits in the title.

## 7. Scaling path (when this outgrows one machine)
1. SQLite → Postgres; run ingestion as its own job writing to the DB.
2. Put per-subscriber composition on a queue (SQS / Redis) and fan out workers.
3. SMTP → transactional provider (SES, SendGrid, Postmark) with bounce/complaint webhooks
   that deactivate subscribers.
4. Add an embeddings-based dedupe/clustering step and optional LLM one-line summaries.
5. Web signup page + double opt-in, signed unsubscribe links, open/click tracking.

## 8. Failure handling
- Each source fetch has a timeout and is wrapped; failures are logged and skipped.
- Delivery records are written only after a successful send.
- Dry-run mode (default) writes emails to `output/` so nothing leaves your machine.

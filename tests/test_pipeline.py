"""Unit tests — run with:  python -m unittest   (or pytest)"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digest import ai, cli, ranker  # noqa: E402
from digest.sources import Story, clean_text  # noqa: E402

NOW = datetime.now(timezone.utc)
TOPICS = cli.load_config(str(Path(__file__).resolve().parent.parent / "config.json"))["topics"]


def story(title, url, hours_old=1, **kw):
    return Story(title, url, "Test", NOW - timedelta(hours=hours_old), **kw)


class Ranking(unittest.TestCase):
    def test_canonical_url_strips_tracking(self):
        self.assertEqual(ranker.canonical_url("http://www.Example.com/a/?utm_source=x&id=2"),
                         "https://example.com/a?id=2")

    def test_dedupe_by_url_and_title(self):
        out = ranker.dedupe([
            story("OpenAI releases new model", "https://a.com/x", points=5),
            story("OpenAI releases new model!", "https://b.com/y"),
            story("Something else", "https://a.com/x?utm_source=hn"),
        ])
        self.assertEqual(len(out), 1)

    def test_topic_tagging(self):
        self.assertEqual(ranker.tag_topic("New MCP server for browsers", TOPICS), "MCP")
        self.assertEqual(ranker.tag_topic("Apache Spark 4 speeds up ETL pipelines", TOPICS), "Data Engineering")
        self.assertEqual(ranker.tag_topic("Kubernetes 1.40 released", TOPICS), "Cloud/DevOps")

    def test_old_stories_dropped(self):
        out = ranker.process([story("Fresh", "https://a.com/1"), story("Stale", "https://a.com/2", hours_old=24 * 30)],
                             TOPICS, max_age_days=8)
        self.assertEqual([s.title for s in out], ["Fresh"])

    def test_pick_balanced_caps_topics(self):
        rows = [{"topic": "AI"}] * 5 + [{"topic": "Dev"}] * 5
        picked = cli.pick_balanced(rows, total=10, per_topic=3)
        self.assertEqual(len(picked), 6)


class Schedule(unittest.TestCase):
    sched = {"weekday": "Saturday", "hour": 10, "timezone": "Europe/Berlin"}

    def test_winter_and_summer(self):
        self.assertTrue(cli.is_scheduled_time(self.sched, datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)))
        self.assertFalse(cli.is_scheduled_time(self.sched, datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)))
        self.assertTrue(cli.is_scheduled_time(self.sched, datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc)))


class AIWriter(unittest.TestCase):
    def test_parse_json_with_fences(self):
        self.assertEqual(ai.parse_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_resources_must_come_from_article(self):
        s = {"title": "t", "url": "https://x.com/post", "summary": "s"}
        links = [{"title": "Docs", "url": "https://docs.x.com"}]
        out = ai._clean({"resources": [{"title": "Docs", "url": "https://docs.x.com"},
                                       {"title": "Made up", "url": "https://hallucinated.example"}]},
                        s, links, "github")
        self.assertEqual([r["url"] for r in out["resources"]], ["https://docs.x.com"])

    def test_extractive_fallback(self):
        s = {"title": "t", "url": "https://x.com", "summary": "Short summary here."}
        text = ("Short summary here. The system uses a columnar engine to speed up queries. "
                "It also adds vectorized execution for joins and aggregations across large tables.")
        out = ai.extractive(s, text, [])
        self.assertEqual(out["generated_by"], "extractive")
        self.assertIn("columnar", out["technical_explanation"])

    def test_clean_text(self):
        self.assertEqual(clean_text("<p>Hello&nbsp;<b>world</b></p>"), "Hello world")


class Privacy(unittest.TestCase):
    def test_mask_email_hides_local_part(self):
        self.assertEqual(cli.mask_email("jane.doe@gmail.com"), "ja***@gmail.com")
        self.assertEqual(cli.mask_email("a@x.com"), "a***@x.com")

    def test_mask_email_handles_bad_input(self):
        self.assertEqual(cli.mask_email(""), "***")
        self.assertEqual(cli.mask_email("not-an-email"), "***")


if __name__ == "__main__":
    unittest.main()

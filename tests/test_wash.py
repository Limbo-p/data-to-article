import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_to_article.storage.file import JsonFileBackend
from data_to_article.washing.run import run_wash

CONFIG = {
    "sources": {
        "demo": {"label": "演示", "date_field": "pub_time", "min_content": 10},
    }
}


def _recent(minutes_ago=60):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


class TestWash(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JsonFileBackend(root=self.tmp.name)

    def test_wash_cleans_and_upserts(self):
        self.store.save_raw_articles([
            {"title": "示例新闻标题一", "content": "正文内容足够长超过十字符", "source": "demo",
             "url": "u1", "pub_time": _recent(120)},
            {"title": "财经早餐摘要内容", "content": "这是系列内容应被过滤掉", "source": "demo",
             "url": "u2", "pub_time": _recent(60)},
        ])
        stats = run_wash(CONFIG, self.store, hours=72)
        self.assertEqual(stats["cleaned"], 1)
        self.assertEqual(stats["series_skipped"], 1)
        cleaned = self.store.fetch_cleaned()
        self.assertEqual(len(cleaned), 1)
        self.assertIn("content_fp", cleaned[0])

    def test_wash_dry_run_no_write(self):
        self.store.save_raw_articles([
            {"title": "示例新闻标题二", "content": "正文内容足够长超过十字符", "source": "demo",
             "url": "u3", "pub_time": _recent(30)},
        ])
        stats = run_wash(CONFIG, self.store, hours=72, dry_run=True)
        self.assertEqual(stats["cleaned"], 1)
        self.assertEqual(len(self.store.fetch_cleaned()), 0)


if __name__ == "__main__":
    unittest.main()
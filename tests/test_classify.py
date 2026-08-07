import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_to_article.event.classify import ClassifyEngine
from data_to_article.llm.base import LLMResponse
from data_to_article.storage.file import JsonFileBackend

CONFIG = {
    "dedup": {"enabled": True},
    "classification": {"router": {"batch_size": 12, "candidate_days": 30, "candidate_limit": 100}},
}


class _RouteStub:
    """模拟 LLMClassifier 接口的 stub（不真正调用 API）。"""

    def chat(self, messages, system="", temperature=None, max_tokens=None):
        return LLMResponse(
            content='[{"no": 1, "event_id": "", "new_group": "new_1", "confidence": "high", "reason": "r"}]',
            usage={}, model="stub",
        )

    def route_articles(self, articles, candidates):
        return [
            {"no": i, "event_id": "", "new_group": "new_1", "confidence": "high", "reason": "r"}
            for i in range(1, len(articles) + 1)
        ]

    def summarize_event(self, items):
        return {}

    def match_article(self, **kwargs):
        return None, "stub"


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JsonFileBackend(root=self.tmp.name)

    def test_l0_direct_merge_by_title(self):
        eid = self.store.save_event({
            "event_id": "evt_1", "event_title": "央行宣布降准", "status": "active",
            "keywords": [], "article_count": 1,
            "articles": [{"content_fp": "fp0", "etl_collection": "demo", "title": "央行宣布降准"}],
            "content_fps": ["fp0"], "etl_collections": ["demo"],
            "updated_at": "2026-08-01T00:00:00",
        })
        self.store.upsert_cleaned([
            {"title": "央行宣布降准", "content": "央行宣布降准0.5个百分点", "source": "demo",
             "content_fp": "fp1", "pub_time": "2026-08-01T08:00:00"},
        ])
        engine = ClassifyEngine(CONFIG, self.store, None)
        stats = engine.process_batch(hours=168)
        self.assertEqual(stats["assigned"], 1)
        evt = self.store.get_event(eid)
        self.assertEqual(evt["article_count"], 2)

    def test_new_event_via_llm_route(self):
        self.store.upsert_cleaned([
            {"title": "某公司发布财报", "content": "某公司发布季度财报，营收增长。", "source": "demo",
             "content_fp": "fp2", "pub_time": "2026-08-01T08:00:00"},
        ])
        engine = ClassifyEngine(CONFIG, self.store, _RouteStub())
        stats = engine.process_batch(hours=168)
        self.assertEqual(stats["created"], 1)
        events = self.store.query_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(self.store.content_fp_exists("fp2"))
        stats2 = engine.process_batch(hours=168)
        self.assertEqual(stats2["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
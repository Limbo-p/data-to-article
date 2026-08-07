import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_to_article.generate.generator import GenerateEngine
from data_to_article.llm.base import LLMResponse
from data_to_article.storage.file import JsonFileBackend

CONFIG = {
    "generation": {"variants_per_event": 2, "min_sources": 2, "max_content_chars": 2000},
    "llm": {"temperature": 0.7},
}


class _GenStub:
    def chat(self, messages, system="", temperature=None, max_tokens=None):
        content = (
            '{"articles": [{"title": "视角一", "style": "深度综述", "viewpoint": "综合", '
            '"content": "正文一"}, {"title": "视角二", "style": "市场反应", "viewpoint": "市场反应", '
            '"content": "正文二"}]}'
        )
        return LLMResponse(content=content, usage={}, model="stub")


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JsonFileBackend(root=self.tmp.name)

    def _seed(self):
        self.store.upsert_cleaned([
            {"title": "公司发布财报", "content": "某公司发布季度财报，营收增长10%。", "source": "demo",
             "content_fp": "fpA", "pub_time": "2026-08-01T08:00:00"},
        ])
        eid = self.store.save_event({
            "event_id": "evt_gen", "event_title": "公司发布财报", "status": "active",
            "keywords": [], "overview": "概述", "category": "公司要闻",
            "articles": [{"content_fp": "fpA", "etl_collection": "demo", "title": "公司发布财报"}],
            "content_fps": ["fpA"], "etl_collections": ["demo"],
            "updated_at": "2026-08-01T09:00:00",
        })
        return eid

    def test_generate_writes_articles(self):
        eid = self._seed()
        engine = GenerateEngine(CONFIG, self.store, _GenStub())
        stats = engine.process_batch(hours=168)
        self.assertEqual(stats["ok"], 1)
        self.assertTrue(self.store.articles_exist(eid))

    def test_generate_dry_run_no_write(self):
        eid = self._seed()
        engine = GenerateEngine(CONFIG, self.store, _GenStub())
        stats = engine.process_batch(hours=168, dry_run=True)
        self.assertEqual(stats["total"], 1)
        self.assertFalse(self.store.articles_exist(eid))


if __name__ == "__main__":
    unittest.main()

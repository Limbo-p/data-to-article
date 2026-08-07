import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_to_article.storage.file import JsonFileBackend


class TestFileStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JsonFileBackend(root=self.tmp.name)

    def test_save_and_fetch_raw(self):
        docs = [
            {
                "title": "t1",
                "content": "c1",
                "source": "a",
                "url": "u1",
                "pub_time": "2026-08-01T00:00:00",
            }
        ]
        self.assertEqual(self.store.save_raw_articles(docs), 1)
        got = self.store.fetch_raw(source="a")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["title"], "t1")

    def test_upsert_cleaned_dedup(self):
        doc = {"title": "t", "content": "c", "content_fp": "fp1", "source": "a"}
        r1 = self.store.upsert_cleaned([doc])
        r2 = self.store.upsert_cleaned([doc])
        self.assertEqual(r1["inserted"], 1)
        self.assertEqual(r2["inserted"], 0)
        self.assertEqual(r2["updated"], 1)
        self.assertTrue(self.store.content_fp_exists("fp1"))
        self.assertEqual(self.store.get_cleaned_by_fp("fp1")["title"], "t")

    def test_dedup_claim_mark_release(self):
        ok, eid = self.store.claim_content_fp("fp9")
        self.assertTrue(ok)
        ok2, eid2 = self.store.claim_content_fp("fp9")
        self.assertFalse(ok2)
        self.assertEqual(eid2, "")
        self.store.mark_content_fp("fp9", "evt_x")
        ok3, eid3 = self.store.claim_content_fp("fp9")
        self.assertFalse(ok3)
        self.assertEqual(eid3, "evt_x")
        self.store.release_content_fp("fp9")
        ok4, _ = self.store.claim_content_fp("fp9")
        self.assertTrue(ok4)

    def test_events_and_articles(self):
        eid = self.store.save_event({"event_title": "evt", "keywords": ["k"]})
        self.assertTrue(eid)
        self.assertTrue(self.store.update_event(eid, {"event_title": "evt2"}))
        evs = self.store.query_events("evt2")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["event_id"], eid)
        self.assertEqual(self.store.get_event(eid)["event_title"], "evt2")
        self.store.save_event_articles(eid, [{"title": "a1", "content": "x"}])
        self.store.save_event_articles(eid, [{"title": "a2", "content": "y"}])
        self.assertTrue(self.store.articles_exist(eid))

    def test_record_run(self):
        self.store.record_run("wash", "ok", {"hours": 1}, "tail")


if __name__ == "__main__":
    unittest.main()

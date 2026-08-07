import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_to_article.cli import main


def _write_config(tmp: str) -> str:
    cfg = {
        "storage": {"backend": "file", "root": str(Path(tmp) / "data")},
        "llm": {"provider": "mock"},
        "pipeline": {
            "stages": {
                "wash": {"enabled": True},
                "classify": {"enabled": True},
                "generate": {"enabled": True},
            }
        },
    }
    p = Path(tmp) / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return str(p)


class TestCli(unittest.TestCase):
    def test_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_config(tmp)
            sample = Path(tmp) / "in.jsonl"
            sample.write_text(
                json.dumps(
                    {
                        "title": "t1",
                        "content": "c1",
                        "source": "s1",
                        "url": "u1",
                        "pub_time": "2026-08-01",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            rc = main(["ingest", "--config", cfg, "--file", str(sample)])
            self.assertEqual(rc, 0)
            raw_dir = Path(tmp) / "data" / "raw"
            self.assertEqual(len(list(raw_dir.glob("*.json"))), 1)

    def test_run_dry(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_config(tmp)
            rc = main(["run", "--config", cfg, "--dry-run"])
            self.assertEqual(rc, 0)
            runs_dir = Path(tmp) / "data" / "runs"
            self.assertGreaterEqual(len(list(runs_dir.glob("*.json"))), 3)


if __name__ == "__main__":
    unittest.main()

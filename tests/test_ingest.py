# -*- coding: utf-8 -*-
"""ingest 适配器测试：JSONL / JSON 数组 / MySQL 注册分支。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from data_to_article.ingest import registry
from data_to_article.ingest.jsonl import JsonlIngest


class JsonlIngestTest(unittest.TestCase):
    def _write(self, content: str) -> Path:
        f = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        f.write(content)
        f.close()
        return Path(f.name)

    def test_jsonl_lines(self):
        p = self._write('{"title": "a", "content": "x"}\n{"title": "b", "content": "y"}\n')
        try:
            docs = JsonlIngest(str(p)).read()
            self.assertEqual(len(docs), 2)
            self.assertEqual(docs[0]["title"], "a")
        finally:
            p.unlink(missing_ok=True)

    def test_json_array_file(self):
        p = self._write(json.dumps([
            {"title": "\u7532", "content": "\u6b63\u6587\u4e00"},
            {"title": "\u4e59", "content": "\u6b63\u6587\u4e8c"},
        ], ensure_ascii=False))
        try:
            docs = JsonlIngest(str(p)).read()
            self.assertEqual(len(docs), 2)
            self.assertEqual(docs[1]["title"], "\u4e59")
        finally:
            p.unlink(missing_ok=True)

    def test_limit(self):
        p = self._write('{"t": 1}\n{"t": 2}\n{"t": 3}\n')
        try:
            docs = JsonlIngest(str(p)).read(limit=2)
            self.assertEqual(len(docs), 2)
        finally:
            p.unlink(missing_ok=True)


class RegistryMysqlTest(unittest.TestCase):
    def test_mysql_branch(self):
        fake = mock.Mock()
        fake.return_value = "mysql-ingest"
        cfg = {
            "mysql": {
                "host": "db-host", "port": 3307, "user": "u",
                "password": "p", "database": "news", "table": "articles",
            }
        }
        with mock.patch("data_to_article.ingest.mysql.MySqlIngest", fake):
            obj = registry.get_ingest(cfg, "mysql", collection="articles")
        self.assertEqual(obj, "mysql-ingest")
        _, kw = fake.call_args
        self.assertEqual(kw["host"], "db-host")
        self.assertEqual(kw["port"], 3307)
        self.assertEqual(kw["table"], "articles")
        self.assertEqual(kw["database"], "news")

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            registry.get_ingest({}, "oracle")


if __name__ == "__main__":
    unittest.main()
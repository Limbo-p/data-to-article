"""JSONL 文件导入。"""

from __future__ import annotations

import json
from pathlib import Path

from data_to_article.ingest.base import IngestSource


class JsonlIngest(IngestSource):
    def __init__(self, path: str):
        self.path = Path(path)

    def read(self, limit: int = 0) -> list[dict]:
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
                if limit and len(out) >= limit:
                    break
        return out

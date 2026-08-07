"""CSV 文件导入（首行为表头）。"""

from __future__ import annotations

import csv
from pathlib import Path

from data_to_article.ingest.base import IngestSource


class CsvIngest(IngestSource):
    def __init__(self, path: str):
        self.path = Path(path)

    def read(self, limit: int = 0) -> list[dict]:
        out = []
        with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                out.append(dict(row))
                if limit and len(out) >= limit:
                    break
        return out

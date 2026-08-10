"""JSONL / JSON 数组文件导入（兼容两种格式）。"""

from __future__ import annotations

import json
from pathlib import Path

from data_to_article.ingest.base import IngestSource


class JsonlIngest(IngestSource):
    def __init__(self, path: str):
        self.path = Path(path)

    def read(self, limit: int = 0) -> list[dict]:
        out = []
        with open(self.path, "r", encoding="utf-8-sig") as f:
            first = ""
            for line in f:
                line = line.strip()
                if line:
                    first = line
                    break
            if not first:
                return out
            if first.startswith("["):
                # 单个 JSON 数组文件（[{...}, {...}]）
                f.seek(0)
                data = json.load(f)
                for item in data:
                    out.append(item)
                    if limit and len(out) >= limit:
                        break
                return out
            # JSONL：每行一个 JSON 对象
            out.append(json.loads(first))
            if limit and len(out) >= limit:
                return out
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
                if limit and len(out) >= limit:
                    break
        return out
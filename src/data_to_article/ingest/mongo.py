"""从 MongoDB 集合读取已有原始文章（集合名可自定义，兼容旧 results_* 类数据）。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from data_to_article.ingest.base import IngestSource


class MongoCollectionIngest(IngestSource):
    def __init__(self, uri: str = "", database: str = "", collection: str = "", window_hours: int = 0):
        from pymongo import MongoClient

        self.client = MongoClient(uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
        self.col = self.client[database or os.environ.get("MONGO_DB", "data_to_article")][collection]
        self.window_hours = window_hours

    def read(self, limit: int = 0) -> list[dict]:
        q = {}
        if self.window_hours > 0:
            since = datetime.now(timezone.utc) - timedelta(hours=self.window_hours)
            q["pub_time"] = {"$gte": since.isoformat(timespec="seconds")}
        cursor = self.col.find(q)
        if limit > 0:
            cursor = cursor.limit(limit)
        out = []
        for d in cursor:
            d.pop("_id", None)
            out.append(d)
        return out

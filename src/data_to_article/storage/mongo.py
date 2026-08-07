"""MongoBackend：默认存储适配器。连接信息来自 config 或 MONGO_URI / MONGO_DB 环境变量。"""

from __future__ import annotations

import os
import re as _re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from data_to_article.storage.base import StorageBackend


class MongoBackend(StorageBackend):
    def __init__(self, uri: str = "", database: str = "data_to_article", collections: Optional[dict] = None):
        from pymongo import MongoClient

        self.uri = uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        self.database = database or os.environ.get("MONGO_DB", "data_to_article")
        self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[self.database]
        c = collections or {}
        self.c_raw = self.db[c.get("raw", "raw_articles")]
        self.c_cleaned = self.db[c.get("cleaned", "articles")]
        self.c_events = self.db[c.get("events", "events")]
        self.c_articles = self.db[c.get("event_articles", "event_articles")]
        self.c_runs = self.db[c.get("runs", "pipeline_runs")]
        self.c_fps = self.db[c.get("fps", "content_fps")]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ---- raw ----
    def save_raw_articles(self, articles: list[dict]) -> int:
        if not articles:
            return 0
        res = self.c_raw.insert_many([dict(a) for a in articles])
        return len(res.inserted_ids)

    def fetch_raw(self, source: str = "", since: Optional[str] = None, limit: int = 0) -> list[dict]:
        q = {}
        if source:
            q["source"] = source
        if since:
            q["pub_time"] = {"$gte": since}
        cursor = self.c_raw.find(q).sort("pub_time", -1)
        if limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)

    # ---- cleaned ----
    def upsert_cleaned(self, articles: list[dict]) -> dict:
        from pymongo import UpdateOne

        ops = []
        now = self._now()
        for a in articles:
            fp = a.get("content_fp", "")
            if not fp:
                continue
            doc = dict(a)
            doc["cleaned_at"] = now
            ops.append(UpdateOne({"content_fp": fp}, {"$set": doc}, upsert=True))
        if not ops:
            return {"inserted": 0, "updated": 0}
        res = self.c_cleaned.bulk_write(ops)
        return {"inserted": res.upserted_count, "updated": max(0, len(ops) - res.upserted_count)}

    def fetch_cleaned(self, since: Optional[str] = None, sources: Optional[list[str]] = None, limit: int = 0) -> list[dict]:
        q = {}
        if since:
            q["cleaned_at"] = {"$gte": since}
        if sources:
            q["source"] = {"$in": list(sources)}
        cursor = self.c_cleaned.find(q).sort("cleaned_at", -1)
        if limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)

    def get_cleaned_by_fp(self, fp: str) -> Optional[dict]:
        return self.c_cleaned.find_one({"content_fp": fp})

    def content_fp_exists(self, fp: str) -> bool:
        return self.c_cleaned.find_one({"content_fp": fp}) is not None

    # ---- dedup ----
    def claim_content_fp(self, fp: str) -> tuple:
        from pymongo.errors import DuplicateKeyError

        try:
            res = self.c_fps.update_one(
                {"content_fp": fp},
                {"$setOnInsert": {
                    "content_fp": fp, "event_id": "", "status": "pending",
                    "claimed_at": self._now(),
                }},
                upsert=True,
            )
            if res.upserted_id is not None:
                return True, ""
            doc = self.c_fps.find_one({"content_fp": fp}, {"event_id": 1})
            return False, (doc or {}).get("event_id", "")
        except DuplicateKeyError:
            return False, ""
        except Exception:
            return False, ""

    def mark_content_fp(self, fp: str, event_id: str) -> None:
        self.c_fps.update_one(
            {"content_fp": fp},
            {"$set": {"event_id": event_id, "status": "assigned", "assigned_at": self._now()}},
        )

    def release_content_fp(self, fp: str) -> None:
        self.c_fps.delete_one({"content_fp": fp})

    # ---- events ----
    def save_event(self, event: dict) -> str:
        eid = event.get("event_id") or _uuid.uuid4().hex
        doc = dict(event)
        doc["event_id"] = eid
        doc.setdefault("updated_at", self._now())
        self.c_events.replace_one({"event_id": eid}, doc, upsert=True)
        return eid

    def update_event(self, event_id: str, event: dict) -> bool:
        res = self.c_events.update_one(
            {"event_id": event_id},
            {"$set": {**event, "updated_at": self._now()}},
        )
        return res.matched_count > 0

    def get_event(self, event_id: str) -> Optional[dict]:
        return self.c_events.find_one({"event_id": event_id})

    def query_events(self, keyword: str = "", limit: int = 0) -> list[dict]:
        q = {}
        if keyword:
            rx = _re.compile(_re.escape(keyword), _re.I)
            q["$or"] = [{"event_title": rx}, {"keywords": rx}]
        cursor = self.c_events.find(q).sort("updated_at", -1)
        if limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)

    # ---- articles ----
    def save_event_articles(self, event_id: str, articles: list[dict]) -> None:
        now = self._now()
        cur = self.c_articles.find_one({"event_id": event_id})
        version = (len((cur or {}).get("versions", []) or []) + 1) if cur else 1
        self.c_articles.update_one(
            {"event_id": event_id},
            {
                "$set": {"articles": articles, "ai_generated_at": now},
                "$push": {
                    "versions": {"version": version, "articles": articles, "archived_at": now}
                },
            },
            upsert=True,
        )

    def articles_exist(self, event_id: str) -> bool:
        return self.c_articles.find_one({"event_id": event_id}, {"_id": 1}) is not None

    # ---- runs ----
    def record_run(self, stage: str, status: str, params: dict, log_tail: str = "") -> None:
        self.c_runs.insert_one(
            {
                "stage": stage,
                "status": status,
                "params": params or {},
                "log_tail": log_tail,
                "started_at": self._now(),
                "finished_at": self._now(),
            }
        )

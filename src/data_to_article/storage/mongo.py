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
        self.c_raw = self._colls(c.get("raw", "raw_articles"))
        self.c_cleaned = self._colls(c.get("cleaned", "articles"))
        self._cleaned_write = self.c_cleaned[0]
        self.c_events = self.db[c.get("events", "events")]
        self.c_articles = self.db[c.get("event_articles", "event_articles")]
        self.c_runs = self.db[c.get("runs", "pipeline_runs")]
        self.c_fps = self.db[c.get("fps", "content_fps")]
        self.c_publish = self.db[c.get("publish", "publish_logs")]

    def _colls(self, value, default="articles"):
        """Split comma-separated collection names into a list of handles."""
        names = [n.strip() for n in str(value).split(",") if n.strip()]
        if not names:
            names = [default]
        return [self.db[n] for n in names]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ---- raw ----
    def save_raw_articles(self, articles: list[dict]) -> int:
        if not articles:
            return 0
        res = self.c_raw[0].insert_many([dict(a) for a in articles])
        return len(res.inserted_ids)

    def fetch_raw(self, source: str = "", since: Optional[str] = None, limit: int = 0) -> list[dict]:
        q = {}
        if source:
            q["source"] = source
        if since:
            q["pub_time"] = {"$gte": since}
        out = []
        for coll in self.c_raw:
            out.extend(coll.find(q))
        out.sort(key=lambda d: str(d.get("pub_time", "")), reverse=True)
        if limit > 0:
            out = out[:limit]
        return out

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
        res = self._cleaned_write.bulk_write(ops)
        return {"inserted": res.upserted_count, "updated": max(0, len(ops) - res.upserted_count)}

    def fetch_cleaned(self, since: Optional[str] = None, sources: Optional[list[str]] = None, limit: int = 0) -> list[dict]:
        q = {}
        if since:
            q["cleaned_at"] = {"$gte": since}
        if sources:
            q["source"] = {"$in": list(sources)}
        out = []
        for coll in self.c_cleaned:
            out.extend(coll.find(q))
        out.sort(key=lambda d: str(d.get("cleaned_at", "")), reverse=True)
        if limit > 0:
            out = out[:limit]
        return out

    def get_cleaned_by_fp(self, fp: str) -> Optional[dict]:
        for coll in self.c_cleaned:
            a = coll.find_one({"content_fp": fp})
            if a:
                return a
        return None

    def content_fp_exists(self, fp: str) -> bool:
        return self.get_cleaned_by_fp(fp) is not None

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

    # ---- articles: 读回 / 审核 / 回滚 / 搜索 ----
    def get_event_articles(self, event_id: str) -> Optional[dict]:
        return self.c_articles.find_one({"event_id": event_id})

    def set_article_review(self, event_id: str, article_idx: int,
                           status: str, note: str = "") -> bool:
        doc = self.c_articles.find_one({"event_id": event_id})
        if not doc or not doc.get("articles") or article_idx >= len(doc["articles"]):
            return False
        arts = list(doc["articles"])
        art = dict(arts[article_idx])
        art["review_status"] = status
        art["reviewed_at"] = self._now()
        if note:
            art["review_note"] = note
        arts[article_idx] = art
        self.c_articles.update_one({"event_id": event_id}, {"$set": {"articles": arts}})
        return True

    def rollback_articles(self, event_id: str, version: int) -> bool:
        doc = self.c_articles.find_one({"event_id": event_id})
        if not doc:
            return False
        for v in doc.get("versions") or []:
            if int(v.get("version")) == int(version):
                self.c_articles.update_one(
                    {"event_id": event_id},
                    {"$set": {"articles": v.get("articles", []),
                              "ai_generated_at": v.get("archived_at", self._now())}},
                )
                return True
        return False

    def search_articles(self, keyword: str = "", limit: int = 0) -> list[dict]:
        import re as _re
        rx = _re.compile(_re.escape(keyword), _re.I) if keyword else None
        out = []
        for doc in self.c_articles.find():
            for idx, art in enumerate(doc.get("articles") or []):
                hay = " ".join([str(art.get("title", "")), str(art.get("content", ""))])
                if rx is not None and not rx.search(hay):
                    continue
                item = dict(art)
                item["event_id"] = doc.get("event_id")
                item["_idx"] = idx
                out.append(item)
                if limit and len(out) >= limit:
                    return out
        return out

    # ---- publish ----
    def record_publish(self, log: dict) -> None:
        self.c_publish.insert_one(dict(log))

    def list_publish_logs(self, limit: int = 20) -> list[dict]:
        return list(self.c_publish.find({}, {"_id": 0})
                    .sort("published_at", -1).limit(limit))

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

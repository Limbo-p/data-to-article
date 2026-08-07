"""JsonFileBackend：零依赖的文件存储后端（每个集合一个目录，每文档一个 json 文件）。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from data_to_article.storage.base import StorageBackend


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JsonFileBackend(StorageBackend):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._dirs = {
            "raw": self.root / "raw",
            "cleaned": self.root / "cleaned",
            "dedup": self.root / "dedup",
            "events": self.root / "events",
            "articles": self.root / "articles",
            "runs": self.root / "runs",
        }
        for d in self._dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    def _write(self, kind: str, name: str, doc: dict) -> None:
        (self._dirs[kind] / f"{name}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )

    def _read(self, kind: str, name: str) -> Optional[dict]:
        p = self._dirs[kind] / f"{name}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def _list(self, kind: str):
        return [p.stem for p in self._dirs[kind].glob("*.json")]

    # ---- raw ----
    def save_raw_articles(self, articles: list[dict]) -> int:
        n = 0
        for a in articles:
            doc = dict(a)
            doc.setdefault("_id", uuid.uuid4().hex)
            doc.setdefault("_stored_at", _now())
            self._write("raw", doc["_id"], doc)
            n += 1
        return n

    def fetch_raw(self, source: str = "", since: Optional[str] = None, limit: int = 0) -> list[dict]:
        out = []
        for name in self._list("raw"):
            doc = self._read("raw", name)
            if doc is None:
                continue
            if source and doc.get("source") != source:
                continue
            if since and str(doc.get("pub_time", "")) < since:
                continue
            out.append(doc)
            if limit and len(out) >= limit:
                break
        out.sort(key=lambda d: str(d.get("pub_time", "")), reverse=True)
        return out

    # ---- cleaned ----
    def upsert_cleaned(self, articles: list[dict]) -> dict:
        inserted = updated = 0
        now = _now()
        for a in articles:
            fp = a.get("content_fp", "")
            if not fp:
                continue
            doc = dict(a)
            doc["cleaned_at"] = now
            if (self._dirs["cleaned"] / f"{fp}.json").exists():
                updated += 1
            else:
                inserted += 1
            self._write("cleaned", fp, doc)
        return {"inserted": inserted, "updated": updated}

    def fetch_cleaned(self, since: Optional[str] = None, sources: Optional[list[str]] = None, limit: int = 0) -> list[dict]:
        out = []
        for name in self._list("cleaned"):
            doc = self._read("cleaned", name)
            if doc is None:
                continue
            if since and str(doc.get("cleaned_at", "")) < since:
                continue
            if sources and doc.get("source") not in sources:
                continue
            out.append(doc)
            if limit and len(out) >= limit:
                break
        out.sort(key=lambda d: str(d.get("cleaned_at", "")), reverse=True)
        return out

    def get_cleaned_by_fp(self, fp: str) -> Optional[dict]:
        return self._read("cleaned", fp)

    def content_fp_exists(self, fp: str) -> bool:
        return (self._dirs["cleaned"] / f"{fp}.json").exists()

    # ---- dedup ----
    def claim_content_fp(self, fp: str) -> tuple:
        p = self._dirs["dedup"] / f"{fp}.json"
        if p.exists():
            doc = json.loads(p.read_text(encoding="utf-8"))
            return False, doc.get("event_id", "")
        self._write("dedup", fp, {
            "content_fp": fp, "event_id": "", "status": "pending", "claimed_at": _now(),
        })
        return True, ""

    def mark_content_fp(self, fp: str, event_id: str) -> None:
        p = self._dirs["dedup"] / f"{fp}.json"
        if p.exists():
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["event_id"] = event_id
            doc["status"] = "assigned"
            doc["assigned_at"] = _now()
            self._write("dedup", fp, doc)

    def release_content_fp(self, fp: str) -> None:
        p = self._dirs["dedup"] / f"{fp}.json"
        if p.exists():
            p.unlink()

    # ---- events ----
    def save_event(self, event: dict) -> str:
        eid = event.get("event_id") or uuid.uuid4().hex
        doc = dict(event)
        doc["event_id"] = eid
        doc.setdefault("updated_at", _now())
        self._write("events", eid, doc)
        return eid

    def update_event(self, event_id: str, event: dict) -> bool:
        cur = self._read("events", event_id)
        if cur is None:
            return False
        cur.update(event)
        cur["event_id"] = event_id
        cur["updated_at"] = _now()
        self._write("events", event_id, cur)
        return True

    def get_event(self, event_id: str) -> Optional[dict]:
        return self._read("events", event_id)

    def query_events(self, keyword: str = "", limit: int = 0) -> list[dict]:
        rx = re.compile(re.escape(keyword), re.I) if keyword else None
        out = []
        for name in self._list("events"):
            doc = self._read("events", name)
            if doc is None:
                continue
            if rx is not None:
                hay = " ".join(
                    [str(doc.get("event_title", "")), " ".join(doc.get("keywords", []) or [])]
                )
                if not rx.search(hay):
                    continue
            out.append(doc)
            if limit and len(out) >= limit:
                break
        out.sort(key=lambda d: str(d.get("updated_at", "")), reverse=True)
        return out

    # ---- articles ----
    def save_event_articles(self, event_id: str, articles: list[dict]) -> None:
        cur = self._read("articles", event_id) or {"event_id": event_id, "articles": [], "versions": []}
        version = len(cur.get("versions") or []) + 1
        cur["articles"] = articles
        cur["ai_generated_at"] = _now()
        cur["versions"] = (cur.get("versions") or []) + [
            {"version": version, "articles": articles, "archived_at": _now()}
        ]
        self._write("articles", event_id, cur)

    def articles_exist(self, event_id: str) -> bool:
        return (self._dirs["articles"] / f"{event_id}.json").exists()

    # ---- runs ----
    def record_run(self, stage: str, status: str, params: dict, log_tail: str = "") -> None:
        doc = {
            "stage": stage,
            "status": status,
            "params": params or {},
            "log_tail": log_tail,
            "started_at": _now(),
            "finished_at": _now(),
        }
        name = f"{stage}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:6]}"
        self._write("runs", name, doc)

"""MySqlBackend：MySQL 存储后端（清洗库/归类库/二创库 + 查重指纹 + 运行记录）。

文档以 JSON 列存储（MySQL 5.7+ / 8.0），表结构见仓库根目录 schema.sql；
首次连接会自动建库建表（CREATE ... IF NOT EXISTS，幂等）。

连接参数优先级：显式参数 > config["storage"]["mysql"] > 环境变量 MYSQL_*。
依赖（可选）：pip install pymysql 或 pip install "data-to-article[mysql]"
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from data_to_article.storage.base import StorageBackend


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MySqlBackend(StorageBackend):
    def __init__(self, host: str = "", port: int = 0, user: str = "",
                 password: str = "", database: str = "",
                 table_prefix: str = "dta_"):
        try:
            import pymysql
        except ImportError:
            raise RuntimeError(
                "MySQL 存储需要 pymysql：pip install pymysql "
                "（或 pip install 'data-to-article[mysql]'）"
            )
        self._pymysql = pymysql
        self.host = host or os.environ.get("MYSQL_HOST", "localhost")
        self.port = int(port or os.environ.get("MYSQL_PORT", "3306"))
        self.user = user or os.environ.get("MYSQL_USER", "root")
        self.password = password or os.environ.get("MYSQL_PASSWORD", "")
        self.database = database or os.environ.get("MYSQL_DB", "data_to_article")
        self.prefix = table_prefix or "dta_"
        self._t = {k: f"{self.prefix}{k}" for k in
                   ("raw", "cleaned", "dedup", "events", "articles", "runs")}
        self._ensure_schema()

    # ===================== 连接与建表 =====================

    def _connect(self, with_db: bool = True):
        return self._pymysql.connect(
            host=self.host, port=self.port, user=self.user, password=self.password,
            database=self.database if with_db else "",
            charset="utf8mb4", autocommit=True,
            cursorclass=self._pymysql.cursors.DictCursor,
        )

    def _q(self, name: str) -> str:
        return f"`{name}`"

    def _ensure_schema(self) -> None:
        conn = self._connect(with_db=False)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
                cur.execute(f"USE `{self.database}`")
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._q(self._t['raw'])} ("
                    f" id VARCHAR(64) PRIMARY KEY,"
                    f" doc JSON NOT NULL,"
                    f" pub_time VARCHAR(64),"
                    f" source VARCHAR(255),"
                    f" stored_at VARCHAR(64),"
                    f" KEY idx_raw_pub (pub_time)"
                    f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                )
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._q(self._t['cleaned'])} ("
                    f" content_fp VARCHAR(64) PRIMARY KEY,"
                    f" doc JSON NOT NULL,"
                    f" cleaned_at VARCHAR(64),"
                    f" source VARCHAR(255),"
                    f" KEY idx_cleaned_at (cleaned_at)"
                    f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                )
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._q(self._t['dedup'])} ("
                    f" content_fp VARCHAR(64) PRIMARY KEY,"
                    f" event_id VARCHAR(64) NOT NULL DEFAULT '',"
                    f" status VARCHAR(16) NOT NULL DEFAULT 'pending',"
                    f" claimed_at VARCHAR(64),"
                    f" assigned_at VARCHAR(64)"
                    f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                )
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._q(self._t['events'])} ("
                    f" event_id VARCHAR(64) PRIMARY KEY,"
                    f" doc JSON NOT NULL,"
                    f" event_title VARCHAR(512),"
                    f" keywords TEXT,"
                    f" updated_at VARCHAR(64),"
                    f" KEY idx_events_updated (updated_at)"
                    f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                )
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._q(self._t['articles'])} ("
                    f" event_id VARCHAR(64) PRIMARY KEY,"
                    f" doc JSON NOT NULL,"
                    f" ai_generated_at VARCHAR(64)"
                    f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                )
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._q(self._t['runs'])} ("
                    f" id BIGINT AUTO_INCREMENT PRIMARY KEY,"
                    f" stage VARCHAR(32),"
                    f" status VARCHAR(16),"
                    f" params JSON,"
                    f" log_tail TEXT,"
                    f" started_at VARCHAR(64),"
                    f" finished_at VARCHAR(64)"
                    f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                )
        finally:
            conn.close()

    # ===================== 原始数据 =====================

    def save_raw_articles(self, articles: list[dict]) -> int:
        if not articles:
            return 0
        now = _now()
        n = 0
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for a in articles:
                    doc = dict(a)
                    rid = str(doc.get("_id") or uuid.uuid4().hex)
                    doc["_id"] = rid
                    doc.setdefault("_stored_at", now)
                    cur.execute(
                        f"INSERT IGNORE INTO {self._q(self._t['raw'])} "
                        f"(id, doc, pub_time, source, stored_at) VALUES (%s,%s,%s,%s,%s)",
                        (rid, json.dumps(doc, ensure_ascii=False),
                         str(doc.get("pub_time", "")), str(doc.get("source", "")), now),
                    )
                    n += cur.rowcount
        finally:
            conn.close()
        return n

    def fetch_raw(self, source: str = "", since: Optional[str] = None, limit: int = 0) -> list[dict]:
        sql = f"SELECT doc FROM {self._q(self._t['raw'])}"
        conds, args = [], []
        if source:
            conds.append("source=%s")
            args.append(source)
        if since:
            conds.append("pub_time>=%s")
            args.append(since)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY pub_time DESC"
        if limit > 0:
            sql += " LIMIT %s"
            args.append(limit)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
        finally:
            conn.close()
        return [json.loads(r["doc"]) for r in rows if r.get("doc")]

    # ===================== 清洗库 =====================

    def upsert_cleaned(self, articles: list[dict]) -> dict:
        inserted = updated = 0
        now = _now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for a in articles:
                    fp = a.get("content_fp", "")
                    if not fp:
                        continue
                    doc = dict(a)
                    doc["cleaned_at"] = now
                    cur.execute(
                        f"INSERT INTO {self._q(self._t['cleaned'])} "
                        f"(content_fp, doc, cleaned_at, source) VALUES (%s,%s,%s,%s) "
                        f"ON DUPLICATE KEY UPDATE doc=VALUES(doc), "
                        f"cleaned_at=VALUES(cleaned_at), source=VALUES(source)",
                        (fp, json.dumps(doc, ensure_ascii=False),
                         now, str(doc.get("source", ""))),
                    )
                    if cur.rowcount == 1:
                        inserted += 1
                    else:
                        updated += 1
        finally:
            conn.close()
        return {"inserted": inserted, "updated": updated}

    def fetch_cleaned(self, since: Optional[str] = None,
                      sources: Optional[list[str]] = None, limit: int = 0) -> list[dict]:
        sql = f"SELECT doc FROM {self._q(self._t['cleaned'])}"
        conds, args = [], []
        if since:
            conds.append("cleaned_at>=%s")
            args.append(since)
        if sources:
            conds.append("source IN (%s)" % ",".join(["%s"] * len(sources)))
            args.extend(list(sources))
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY cleaned_at DESC"
        if limit > 0:
            sql += " LIMIT %s"
            args.append(limit)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
        finally:
            conn.close()
        return [json.loads(r["doc"]) for r in rows if r.get("doc")]

    def get_cleaned_by_fp(self, fp: str) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT doc FROM {self._q(self._t['cleaned'])} WHERE content_fp=%s",
                    (fp,),
                )
                row = cur.fetchone()
                return json.loads(row["doc"]) if row and row.get("doc") else None
        finally:
            conn.close()

    def content_fp_exists(self, fp: str) -> bool:
        return self.get_cleaned_by_fp(fp) is not None

    # ===================== 查重指纹（归类侧） =====================

    def claim_content_fp(self, fp: str) -> tuple:
        now = _now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT IGNORE INTO {self._q(self._t['dedup'])} "
                    f"(content_fp, event_id, status, claimed_at) VALUES (%s,'',%s,%s)",
                    (fp, "pending", now),
                )
                if cur.rowcount == 1:
                    return True, ""
                cur.execute(
                    f"SELECT event_id FROM {self._q(self._t['dedup'])} WHERE content_fp=%s",
                    (fp,),
                )
                row = cur.fetchone()
                return False, ((row or {}).get("event_id") or "")
        finally:
            conn.close()

    def mark_content_fp(self, fp: str, event_id: str) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self._q(self._t['dedup'])} SET event_id=%s, "
                    f"status='assigned', assigned_at=%s WHERE content_fp=%s",
                    (event_id, _now(), fp),
                )
        finally:
            conn.close()

    def release_content_fp(self, fp: str) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self._q(self._t['dedup'])} WHERE content_fp=%s",
                    (fp,),
                )
        finally:
            conn.close()

    # ===================== 归类库（事件） =====================

    def save_event(self, event: dict) -> str:
        eid = event.get("event_id") or uuid.uuid4().hex
        doc = dict(event)
        doc["event_id"] = eid
        doc.setdefault("updated_at", _now())
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self._q(self._t['events'])} "
                    f"(event_id, doc, event_title, keywords, updated_at) VALUES (%s,%s,%s,%s,%s) "
                    f"ON DUPLICATE KEY UPDATE doc=VALUES(doc), "
                    f"event_title=VALUES(event_title), keywords=VALUES(keywords), "
                    f"updated_at=VALUES(updated_at)",
                    (eid, json.dumps(doc, ensure_ascii=False),
                     str(doc.get("event_title", "")),
                     json.dumps(doc.get("keywords") or [], ensure_ascii=False),
                     doc["updated_at"]),
                )
        finally:
            conn.close()
        return eid

    def update_event(self, event_id: str, event: dict) -> bool:
        cur = self.get_event(event_id)
        if cur is None:
            return False
        merged = {**cur, **event, "event_id": event_id, "updated_at": _now()}
        self.save_event(merged)
        return True

    def get_event(self, event_id: str) -> Optional[dict]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT doc FROM {self._q(self._t['events'])} WHERE event_id=%s",
                    (event_id,),
                )
                row = cur.fetchone()
                if not row or not row.get("doc"):
                    return None
                doc = json.loads(row["doc"])
                doc.setdefault("event_id", event_id)
                return doc
        finally:
            conn.close()

    def query_events(self, keyword: str = "", limit: int = 0) -> list[dict]:
        sql = f"SELECT doc FROM {self._q(self._t['events'])}"
        conds, args = [], []
        if keyword:
            kw = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conds.append("(event_title LIKE %s OR keywords LIKE %s)")
            args += [f"%{kw}%", f"%{kw}%"]
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY updated_at DESC"
        if limit > 0:
            sql += " LIMIT %s"
            args.append(limit)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
        finally:
            conn.close()
        return [json.loads(r["doc"]) for r in rows if r.get("doc")]

    # ===================== 二创库（文章） =====================

    def save_event_articles(self, event_id: str, articles: list[dict]) -> None:
        now = _now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT doc FROM {self._q(self._t['articles'])} WHERE event_id=%s",
                    (event_id,),
                )
                row = cur.fetchone()
                base = (json.loads(row["doc"]) if row and row.get("doc")
                        else {"event_id": event_id, "articles": [], "versions": []})
                version = len(base.get("versions") or []) + 1
                doc = {
                    "event_id": event_id,
                    "articles": articles,
                    "ai_generated_at": now,
                    "versions": (base.get("versions") or []) + [
                        {"version": version, "articles": articles, "archived_at": now}
                    ],
                }
                cur.execute(
                    f"INSERT INTO {self._q(self._t['articles'])} "
                    f"(event_id, doc, ai_generated_at) VALUES (%s,%s,%s) "
                    f"ON DUPLICATE KEY UPDATE doc=VALUES(doc), "
                    f"ai_generated_at=VALUES(ai_generated_at)",
                    (event_id, json.dumps(doc, ensure_ascii=False), now),
                )
        finally:
            conn.close()

    def articles_exist(self, event_id: str) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT 1 AS x FROM {self._q(self._t['articles'])} WHERE event_id=%s LIMIT 1",
                    (event_id,),
                )
                return cur.fetchone() is not None
        finally:
            conn.close()

    # ===================== 运行记录 =====================

    def record_run(self, stage: str, status: str, params: dict, log_tail: str = "") -> None:
        now = _now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self._q(self._t['runs'])} "
                    f"(stage, status, params, log_tail, started_at, finished_at) "
                    f"VALUES (%s,%s,%s,%s,%s,%s)",
                    (stage, status, json.dumps(params or {}, ensure_ascii=False),
                     str(log_tail or ""), now, now),
                )
        finally:
            conn.close()
"""按类型创建导入源。"""

from __future__ import annotations

from data_to_article.ingest.base import IngestSource


def get_ingest(config: dict, kind: str, **kwargs) -> IngestSource:
    if kind == "jsonl":
        from data_to_article.ingest.jsonl import JsonlIngest

        return JsonlIngest(kwargs["path"])

    if kind == "csv":
        from data_to_article.ingest.csv import CsvIngest

        return CsvIngest(kwargs["path"])

    if kind == "mongo":
        from data_to_article.ingest.mongo import MongoCollectionIngest

        icol = config.get("ingest", {}) or {}
        return MongoCollectionIngest(
            uri=kwargs.get("uri", ""),
            database=kwargs.get("database", ""),
            collection=kwargs.get("collection") or icol.get("collection", "raw_articles"),
            window_hours=kwargs.get("window_hours", 0),
        )

    if kind == "mysql":
        from data_to_article.ingest.mysql import MySqlIngest

        mcfg = config.get("mysql", {}) or {}
        return MySqlIngest(
            host=kwargs.get("host", "") or mcfg.get("host", ""),
            port=kwargs.get("port", 0) or mcfg.get("port", 0),
            user=kwargs.get("user", "") or mcfg.get("user", ""),
            password=kwargs.get("password", "") or mcfg.get("password", ""),
            database=kwargs.get("database", "") or mcfg.get("database", ""),
            table=kwargs.get("collection", "") or kwargs.get("table", "") or mcfg.get("table", ""),
            where=mcfg.get("where", ""),
        )

    raise ValueError(f"未知导入类型: {kind}")
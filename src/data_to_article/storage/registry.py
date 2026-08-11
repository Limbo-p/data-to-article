"""按配置创建存储后端：backend=mongo|file|mysql，或自定义 backend + module。"""

from __future__ import annotations

import importlib
import json
import os

from data_to_article.settings import PROJECT_ROOT
from data_to_article.storage.base import StorageBackend


def _read_marker_backend() -> str:
    """读取 ingest 写入的存储后端标记（跟随输入来源，三库一致）。"""
    try:
        marker = PROJECT_ROOT / "data" / ".storage.json"
        if marker.exists():
            data = json.loads(marker.read_text(encoding="utf-8"))
            backend = data.get("backend")
            if backend:
                return str(backend)
    except Exception:
        pass
    return ""


def get_storage(config: dict) -> StorageBackend:
    scfg = config.get("storage", {}) or {}
    kind = os.environ.get("DTA_STORAGE") or _read_marker_backend() or scfg.get("backend") or "mongo"

    if kind == "file":
        from data_to_article.storage.file import JsonFileBackend

        root = scfg.get("root") or os.environ.get("DTA_STORAGE_ROOT", "data")
        return JsonFileBackend(root=root)

    if kind == "mongo":
        from data_to_article.storage.mongo import MongoBackend

        return MongoBackend(
            uri=scfg.get("uri", ""),
            database=scfg.get("database", "data_to_article"),
            collections=scfg.get("collections") or {},
        )

    if kind == "mysql":
        from data_to_article.storage.mysql import MySqlBackend

        mcfg = scfg.get("mysql") or {}
        return MySqlBackend(
            host=mcfg.get("host", ""),
            port=int(mcfg.get("port", 0) or 0),
            user=mcfg.get("user", ""),
            password=mcfg.get("password", ""),
            database=mcfg.get("database", ""),
            table_prefix=mcfg.get("table_prefix", "dta_"),
        )

    # 自定义存储：storage.module 指向用户自己的 StorageBackend 子类
    module_path = scfg.get("module", "")
    if not module_path:
        raise ValueError(f"未知存储后端: {kind}（可配置 storage.module 指定自定义实现）")
    mod_name, _, attr = module_path.rpartition(".")
    cls = getattr(importlib.import_module(mod_name), attr)
    return cls(scfg)

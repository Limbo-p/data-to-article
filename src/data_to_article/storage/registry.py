"""按配置创建存储后端：backend=mongo|file，或自定义 backend + module。"""

from __future__ import annotations

import importlib
import os

from data_to_article.storage.base import StorageBackend


def get_storage(config: dict) -> StorageBackend:
    scfg = config.get("storage", {}) or {}
    kind = scfg.get("backend") or os.environ.get("DTA_STORAGE", "mongo")

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

    # 自定义存储：storage.module 指向用户自己的 StorageBackend 子类
    module_path = scfg.get("module", "")
    if not module_path:
        raise ValueError(f"未知存储后端: {kind}（可配置 storage.module 指定自定义实现）")
    mod_name, _, attr = module_path.rpartition(".")
    cls = getattr(importlib.import_module(mod_name), attr)
    return cls(scfg)

"""存储层：StorageBackend 接口 + 适配器（mongo/file/自定义）。"""

from data_to_article.storage.base import StorageBackend, StorageError
from data_to_article.storage.registry import get_storage

__all__ = ["StorageBackend", "StorageError", "get_storage"]

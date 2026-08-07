"""数据接入层：IngestSource 接口 + 适配器（jsonl/csv/mongo/自定义）。"""

from data_to_article.ingest.base import IngestSource, normalize_article
from data_to_article.ingest.registry import get_ingest

__all__ = ["IngestSource", "normalize_article", "get_ingest"]

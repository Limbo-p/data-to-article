"""IngestSource 接口：把外部原始数据接入流水线（替代爬虫写库）。"""

from __future__ import annotations

import abc


def normalize_article(doc: dict) -> dict:
    """把任意输入文档规范化为标准原始文章。"""
    pub_time = str(doc.get("pub_time", "")).strip()
    # 兼容旧格式 "YYYY-MM-DD HH:MM:SS" -> ISO "YYYY-MM-DDTHH:MM:SS"（保证字符串比较一致）
    if " " in pub_time and pub_time[4] == "-":
        pub_time = pub_time.replace(" ", "T", 1)
    out = {
        "title": str(doc.get("title", "")).strip(),
        "content": str(doc.get("content", "")).strip(),
        "url": str(doc.get("url", "")).strip(),
        "source": str(doc.get("source", "")).strip(),
        "pub_time": pub_time or None,
    }
    for k, v in doc.items():
        if k not in out:
            out[k] = v
    return out


class IngestSource(abc.ABC):
    @abc.abstractmethod
    def read(self, limit: int = 0) -> list[dict]:
        """读取原始文档列表（未规范化）。"""

    def read_normalized(self, limit: int = 0) -> list[dict]:
        return [normalize_article(d) for d in self.read(limit)]

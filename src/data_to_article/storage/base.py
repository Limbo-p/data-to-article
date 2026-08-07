"""Storage 接口：数据到文章流水线与存储实现的解耦点。

业务模块只依赖本文件定义的 StorageBackend，不直接依赖 MongoDB 或任何具体存储。
自定义存储：继承 StorageBackend 实现全部方法，然后在 config 的 storage.backend 用自定义名、
storage.module 指向你的类。
"""

from __future__ import annotations

import abc
from typing import Optional


class StorageError(Exception):
    pass


class StorageBackend(abc.ABC):
    """流水线需要的最小存储操作集合。"""

    # ---- 原始数据（ingest 写入，清洗读取）----
    @abc.abstractmethod
    def save_raw_articles(self, articles: list[dict]) -> int:
        """批量写入原始文章，返回写入条数。"""

    @abc.abstractmethod
    def fetch_raw(self, source: str = "", since: Optional[str] = None, limit: int = 0) -> list[dict]:
        """按时间窗口读取原始文章。since 为 ISO 时间字符串；limit<=0 表示不限制。"""

    # ---- 清洗产物（washing 写入，归类读取）----
    @abc.abstractmethod
    def upsert_cleaned(self, articles: list[dict]) -> dict:
        """按 content_fp 幂等写入清洗后文章，返回 {"inserted": n, "updated": n}。"""

    @abc.abstractmethod
    def fetch_cleaned(self, since: Optional[str] = None, sources: Optional[list[str]] = None, limit: int = 0) -> list[dict]:
        """读取清洗后文章。"""

    # ---- 查重指纹 ----
    @abc.abstractmethod
    def content_fp_exists(self, fp: str) -> bool:
        """指纹是否已存在（用于事件侧查重）。"""

    # ---- 事件（归类写入/查询）----
    @abc.abstractmethod
    def save_event(self, event: dict) -> str:
        """保存事件，返回 event_id。"""

    @abc.abstractmethod
    def update_event(self, event_id: str, event: dict) -> bool:
        """按 event_id 更新事件。"""

    @abc.abstractmethod
    def query_events(self, keyword: str = "", limit: int = 0) -> list[dict]:
        """搜索事件（标题/关键词模糊匹配，时间倒序）。"""

    # ---- 二创产物 ----
    @abc.abstractmethod
    def save_event_articles(self, event_id: str, articles: list[dict], version: int = 1) -> None:
        """保存某事件的多视角二创文章，并写入历史版本。"""

    # ---- 运行记录 ----
    @abc.abstractmethod
    def record_run(self, stage: str, status: str, params: dict, log_tail: str = "") -> None:
        """记录一次阶段运行结果。"""

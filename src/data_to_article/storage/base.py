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

    @abc.abstractmethod
    def get_cleaned_by_fp(self, fp: str) -> Optional[dict]:
        """按内容指纹取单篇清洗后文章。"""

    # ---- 查重指纹（归类侧）----
    @abc.abstractmethod
    def claim_content_fp(self, fp: str) -> tuple:
        """原子认领指纹，返回 (是否新认领, 已映射的 event_id)。"""

    @abc.abstractmethod
    def mark_content_fp(self, fp: str, event_id: str) -> None:
        """标记指纹已归入事件。"""

    @abc.abstractmethod
    def release_content_fp(self, fp: str) -> None:
        """释放指纹认领。"""

    # ---- 事件（归类写入/查询）----
    @abc.abstractmethod
    def save_event(self, event: dict) -> str:
        """保存事件，返回 event_id。"""

    @abc.abstractmethod
    def update_event(self, event_id: str, event: dict) -> bool:
        """按 event_id 更新事件（部分字段合并）。"""

    @abc.abstractmethod
    def get_event(self, event_id: str) -> Optional[dict]:
        """按 event_id 读取事件。"""

    @abc.abstractmethod
    def query_events(self, keyword: str = "", limit: int = 0) -> list[dict]:
        """搜索事件（标题/关键词模糊匹配，时间倒序）。"""

    # ---- 二创产物 ----
    @abc.abstractmethod
    def save_event_articles(self, event_id: str, articles: list[dict]) -> None:
        """保存某事件的多视角二创文章；重新生成时旧版本自动归档（版本号自增）。"""

    @abc.abstractmethod
    def articles_exist(self, event_id: str) -> bool:
        """事件是否已生成过二创文章。"""

    # ---- 二创产物：读回 / 审核 / 回滚 / 搜索 ----
    @abc.abstractmethod
    def get_event_articles(self, event_id: str) -> Optional[dict]:
        """读取某事件当前二创文档（含 articles 与 versions）。"""

    @abc.abstractmethod
    def set_article_review(self, event_id: str, article_idx: int,
                           status: str, note: str = "") -> bool:
        """更新某事件第 article_idx 篇二创文章的审核状态。"""

    @abc.abstractmethod
    def rollback_articles(self, event_id: str, version: int) -> bool:
        """回滚二创文章到指定版本。"""

    @abc.abstractmethod
    def search_articles(self, keyword: str = "", limit: int = 0) -> list[dict]:
        """搜索二创文章（标题/正文模糊匹配），返回带 event_id 与 _idx 的文章列表。"""

    # ---- 发布记录 ----
    @abc.abstractmethod
    def record_publish(self, log: dict) -> None:
        """记录一次发布操作。"""

    @abc.abstractmethod
    def list_publish_logs(self, limit: int = 20) -> list[dict]:
        """读取最近发布记录。"""

    # ---- 运行记录 ----
    @abc.abstractmethod
    def record_run(self, stage: str, status: str, params: dict, log_tail: str = "") -> None:
        """记录一次阶段运行结果。"""

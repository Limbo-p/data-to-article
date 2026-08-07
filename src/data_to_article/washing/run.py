"""wash 阶段：原始数据 -> 清洗/去重/系列过滤 -> 清洗产物。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data_to_article.washing.clean import clean_article, deduplicate
from data_to_article.washing.series_filter import is_series_content


def run_wash(config: dict, storage, hours: int = 24, limit: int = 0, dry_run: bool = False) -> dict:
    """执行清洗阶段。返回统计信息。"""
    sources = config.get("sources", {}) or {}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")

    raw = storage.fetch_raw(since=cutoff, limit=limit)
    print(f"[wash] 原始文章 {len(raw)} 篇（窗口 {hours}h）")

    cleaned = []
    series_skipped = 0
    invalid = 0
    for r in raw:
        src_name = r.get("source", "") or "default"
        scfg = sources.get(src_name, sources.get("default", {})) or {}
        art = clean_article(r, scfg)
        if art is None:
            invalid += 1
            continue
        detected, _ = is_series_content(art.get("title", ""), art.get("content", ""))
        if detected:
            series_skipped += 1
            continue
        cleaned.append(art)

    if dry_run:
        print(f"[wash][dry] 清洗后 {len(cleaned)} 篇（无效 {invalid}，系列过滤 {series_skipped}），未写入")
        return {"cleaned": len(cleaned), "invalid": invalid, "series_skipped": series_skipped}

    deduped = deduplicate(cleaned)
    result = storage.upsert_cleaned(deduped)
    print(f"[wash] 去重 {len(cleaned)} -> {len(deduped)}，写入 {result}")
    return {"cleaned": len(cleaned), "deduped": len(deduped), "upsert": result,
            "invalid": invalid, "series_skipped": series_skipped}

"""清洗 ETL 核心函数：文本清理、日期解析、内容过滤、文章清洗、去重。"""

from __future__ import annotations

import hashlib
import re


def clean_text(text: str) -> str:
    """清理 HTML 实体与多余换行。"""
    if not text:
        return ""
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_date(raw: str) -> str:
    """多种日期格式统一为 YYYY-MM-DD HH:MM:SS。"""
    if not raw:
        return ""
    raw = raw.strip()
    patterns = [
        r"(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?",
        r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?\s*(\d{1,2}):(\d{2})",
        r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?",
        r"(\d{4})/(\d{1,2})/(\d{1,2})",
    ]
    for pat in patterns:
        m = re.search(pat, raw)
        if m:
            parts = [int(g) for g in m.groups() if g is not None]
            y, mo, d = parts[0], parts[1], parts[2]
            h = mi = s = 0
            rest = parts[3:]
            if len(rest) >= 2:
                h, mi = rest[0], rest[1]
                if len(rest) >= 3:
                    s = rest[2]
            return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
    return ""


def apply_content_filter(content: str, config: dict) -> str:
    """根据配置过滤正文中的干扰文字。"""
    rules = config.get("content_filter", {}) or {}
    for text in rules.get("remove_text", []) or []:
        content = content.replace(text, "")
    return content


def is_valid_article(article: dict, config: dict) -> bool:
    """根据配置判断文章是否有效。"""
    content = article.get("content", "")
    title = article.get("title", "")
    rules = config.get("content_filter", {}) or {}
    for kw in rules.get("invalid_keywords", []) or []:
        if kw in content:
            return False
    threshold = rules.get("image_news_threshold", 0)
    if threshold > 0 and article.get("word_count", 0) < threshold:
        for kw in rules.get("image_news_keywords", []) or []:
            if kw in content or kw in title:
                return False
    return True


def clean_article(raw: dict, config: dict) -> dict | None:
    """根据来源配置清洗单篇文章，返回清洗后文章或 None。"""
    title = clean_text(raw.get("title", ""))
    if not title or len(title) < 5:
        return None

    content = clean_text(raw.get("content", ""))
    content = apply_content_filter(content, config)
    if len(content) < int(config.get("min_content", 20)):
        return None

    date_field = config.get("date_field", "pub_time")
    pub_time = parse_date(raw.get(date_field, ""))

    source = clean_text(raw.get("source", ""))
    source = re.sub(r"\s+", "", source)

    section_cn = ""
    section_field = config.get("section_field")
    if section_field:
        section_map = config.get("section_map", {}) or {}
        section_raw = raw.get(section_field, "")
        section_cn = section_map.get(section_raw, section_raw)

    article = {
        "title": title,
        "source": source,
        "author": clean_text(raw.get("author", "")),
        "pub_time": pub_time,
        "content": content,
        "url": raw.get("url", ""),
        "fingerprint": raw.get("fingerprint", ""),
        "content_fp": hashlib.md5(content.encode("utf-8")).hexdigest(),
        "crawled_at": raw.get("crawled_at", ""),
        "word_count": len(content),
        "sentence_count": len(re.findall(r"[。！？.!?\n]", content)),
        "tags": [],
        "_spider": config.get("label", ""),
        "_source_id": raw.get("_id", ""),
    }
    if section_cn:
        article["section_cn"] = section_cn

    if not is_valid_article(article, config):
        return None
    return article


def deduplicate(articles: list[dict]) -> list[dict]:
    """两轮去重：先按 URL/指纹，再按内容指纹（保留字数更多/更新）。"""
    seen = {}
    content_seen = {}
    to_remove = set()

    for a in articles:
        f = a.get("fingerprint", "") or hashlib.md5(a.get("url", "").encode()).hexdigest()
        if f and (f not in seen or a.get("crawled_at", "") > seen[f].get("crawled_at", "")):
            seen[f] = a

    for a in seen.values():
        cfp = a.get("content_fp", "")
        if not cfp:
            continue
        if cfp in content_seen:
            prev = content_seen[cfp]
            if a.get("word_count", 0) > prev.get("word_count", 0) or (
                a.get("word_count", 0) == prev.get("word_count", 0)
                and a.get("crawled_at", "") > prev.get("crawled_at", "")
            ):
                content_seen[cfp] = a
                to_remove.add(id(prev))
            else:
                to_remove.add(id(a))
        else:
            content_seen[cfp] = a

    result = [a for a in seen.values() if id(a) not in to_remove]
    return result

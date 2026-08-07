"""series_filter - 周期性/系列性内容检测与过滤。

识别四类不适合作为独立事件的内容：
  1. FM-Radio 早餐摘要（华尔街见闻）
  2. 财经/金融早餐（其他来源每日早报）
  3. 周报（多主题合集）
  4. 机构日报（分析师署名 + 多主题头）
"""

from __future__ import annotations

import re

# 非主题词：出现在行首"XXX："模式中但不应视为主题头的词
_NON_TOPICS = {
    "免责声明", "免责", "来源", "数据来源", "资料来源",
    "责任编辑", "编辑", "风险提示",
}


def is_series_content(title: str, content: str) -> tuple:
    """判断是否为应过滤的周期性内容。返回 (True, 原因) 应过滤；(False, "") 保留。"""
    if "FM-Radio" in title:
        return True, "FM早餐摘要"

    if re.search(r"(财经早餐|金融早餐)", title):
        return True, "财经早餐摘要"

    if "周报" in title:
        return True, "周报"

    if "日报" in title or "日评" in title:
        has_analyst = "从业资格号" in content
        headers = re.findall(
            r"^([\u4e00-\u9fff\w&（）()／\-]{1,24})[：:]",
            content, re.MULTILINE,
        )
        clean = [h for h in headers if h not in _NON_TOPICS]
        if has_analyst and len(clean) >= 2:
            return True, f"机构日报（{len(clean)}个主题）"

    return False, ""

"""二创生成引擎：读取事件与其原文，LLM 单次生成多视角文章并落库。

平移自旧项目 event.generator.EventGenerator，存储/LLM 全部走接口。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from data_to_article.prompts import load_prompt

_SYSTEM_CROSS = """你是一位资深财经新闻编辑兼事实核查专家。

你收到同一事件下、来自多个财经媒体的文章。请先内部完成以下步骤，再输出最终结果：

【内部推理步骤 - 不在输出中体现】
1. 交叉验证：比对各来源的核心事实（数字、金额、百分比、日期、人名、机构名、政策条款），标注一致或差异，确定各差异的最可信版本
2. 视角分析：识别各来源的报道角度差异（快讯/产业影响/市场反应/政策视角等）
3. 确定叙事框架：基于交叉验证的结果，规划多篇正文的视角分布和事实分配
4. 观点分级：将写入正文的内容分为事实/推断/推测三类，并确定对应的措辞，正文不出现标注

【文章生成要求】
基于上述验证，生成多篇可独立发布的财经文章：
- 每篇从不同视角切入，不得重复或雷同
- 不要出现"据XX报道"、"据来源"等引用痕迹，事实以陈述句直接呈现
- 有差异的事实取推荐版本，不在正文中暴露差异过程
- 每篇有独立的标题和开篇方式
- 表述专业、客观，保持财经新闻的写作风格
- 视角可选：综合综述 / 产业影响 / 市场反应 / 政策视角 / 民生影响

【数据铁律】
1. 内容边界：必须基于参考文章的核心事实展开，不得引入原文未涉及的独立话题或编造精确数据
2. 推断分级：正文中不出现【事实】/【推断】/【推测】等括号标注，必须用措辞明示每条判断的可信度：
   - 事实（原文或来源有明确依据）：直接陈述，必要时用"公司公告显示""财报披露""数据显示"等交代出处
   - 推断（基于事实的分析延伸）：必须用"这表明""这意味着""反映出"等推断性措辞，不得写成确定事实
   - 推测（无依据或面向未来）：必须用"预计""可能""有望""不排除"等不确定性措辞
   - 精确数字、日期、人名只允许出现在有依据的事实里；推断和推测不得伪造精确数据
3. 术语精确：使用行业惯用术语，禁止跨领域概念迁移
4. 因果审慎：禁止将时间先后或相关性表述为因果性
5. 风格纠偏：禁止套路化表达（"释放出明确的政策信号"、"印证了……的刚需配套"等空洞结语）
6. 禁止操作性建议：不得出现具体买卖建议或操作指导

输出格式（仅 JSON，不要其他文字）：
{
  "articles": [
    {
      "title": "文章标题",
      "style": "深度综述/趋势分析/市场反应/政策解读/产业影响",
      "viewpoint": "综合 | 产业影响 | 市场反应 | 政策视角 | 民生影响",
      "content": "正文内容（600-1200字）"
    }
  ]
}"""

_SYSTEM_SINGLE = """你是一位专业的财经新闻编辑。

根据下面这篇参考文章，生成多篇不同视角的财经报道。
- 每篇从不同视角切入（综合/产业影响/市场反应/政策视角/民生影响）
- 每篇有独立标题和开篇方式
- 不要出现引用痕迹，事实以陈述句直接呈现
- 表述专业、客观，保持财经新闻写作风格

约束规则：
1. 内容边界：必须基于参考文章的核心事实展开，不得引入原文未涉及的独立话题或编造精确数据
2. 推断分级：正文中不出现【事实】/【推断】/【推测】等括号标注，必须用措辞明示每条判断的可信度：
   - 事实（原文或来源有明确依据）：直接陈述，必要时用"公司公告显示""财报披露""数据显示"等交代出处
   - 推断（基于事实的分析延伸）：必须用"这表明""这意味着""反映出"等推断性措辞，不得写成确定事实
   - 推测（无依据或面向未来）：必须用"预计""可能""有望""不排除"等不确定性措辞
   - 精确数字、日期、人名只允许出现在有依据的事实里；推断和推测不得伪造精确数据
3. 术语精确：使用行业惯用术语，禁止跨领域概念迁移
4. 因果审慎：禁止将时间先后或相关性表述为因果性
5. 风格纠偏：禁止套路化表达（避免空洞结语）
6. 禁止操作性建议：不得出现具体买卖建议或操作指导

输出格式（仅 JSON，不要其他文字）：
{
  "articles": [
    {
      "title": "文章标题",
      "style": "深度综述/趋势分析/市场反应/政策解读/产业影响",
      "viewpoint": "综合 | 产业影响 | 市场反应 | 政策视角 | 民生影响",
      "content": "正文内容（600-1200字）"
    }
  ]
}"""


class GenerateEngine:
    def __init__(self, config: dict, storage, llm):
        self.config = config
        self.storage = storage
        self.llm = llm
        self.dry_run = False

        gen = config.get("generation", {}) or {}
        self.variants = int(gen.get("variants_per_event", 2))
        self.min_sources = int(gen.get("min_sources", 2))
        self.max_content_chars = int(gen.get("max_content_chars", 2000))
        self.temperature = float((config.get("llm", {}) or {}).get("temperature", 0.7))
        self.system_cross = load_prompt("generate_cross.txt", _SYSTEM_CROSS)
        self.system_single = load_prompt("generate_single.txt", _SYSTEM_SINGLE)

    # ---------- 主流程 ----------

    def process_batch(self, hours: int = 168, limit: int = 0, dry_run: bool = False,
                       event_id: str = "") -> dict:
        self.dry_run = dry_run
        events = self._find_unprocessed(hours, limit)
        if event_id:
            events = [e for e in events if e.get("event_id") == event_id]
        print(f"[generate] 待处理事件 {len(events)} 个（窗口 {hours}h）")
        if not events:
            return {"ok": 0, "skipped": 0, "failed": 0, "total": 0}
        results = []
        for event in events:
            results.append(self.process_one(event))
        ok = sum(1 for r in results if r.get("status") == "ok")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        failed = sum(1 for r in results if r.get("status") == "failed")
        print(f"[generate] 完成: 成功 {ok}, 跳过 {skipped}, 失败 {failed}, 共 {len(results)}")
        return {"ok": ok, "skipped": skipped, "failed": failed, "total": len(results)}

    def process_one(self, event: dict) -> dict:
        eid = event.get("event_id", "")
        title = (event.get("event_title", "") or "")[:60]
        print(f"\n  事件: {title} ({eid})")

        articles = self._load_articles(event)
        if not articles:
            print(f"    x 事件无可用原文，跳过")
            return {"event_id": eid, "status": "skipped", "reason": "no articles"}

        sources = {a.get("_collection", "") for a in articles if a.get("_collection")}
        cross = len(sources) >= self.min_sources
        print(f"    来源: {', '.join(sources) or '无'} ({len(articles)} 篇) 交叉验证={cross}")

        user_prompt = self._build_user_prompt(event, articles)
        system = self.system_cross if cross else self.system_single

        if self.dry_run:
            print(f"    [dry] 不调 LLM：system={system[:20]}... user={len(user_prompt)} 字")
            return {"event_id": eid, "status": "dry_run"}

        resp = self.llm.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system=system,
            temperature=self.temperature,
        )
        data = self._parse_json(resp.content)
        articles_out = data.get("articles", [])
        if not articles_out:
            print(f"    x 解析失败或无有效文章: {resp.content[:200]}")
            return {"event_id": eid, "status": "failed", "reason": "LLM 未返回有效文章"}

        self.storage.save_event_articles(eid, articles_out)
        print(f"    v 写入 {len(articles_out)} 篇文章")
        return {"event_id": eid, "status": "ok", "article_count": len(articles_out)}

    # ---------- 辅助 ----------

    def _find_unprocessed(self, hours: int, limit: int):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        out = []
        # limit ??"???? N ??????"?????? updated_at ?????? N ???
        for evt in self.storage.query_events(limit=0):
            if evt.get("status", "active") != "active":
                continue
            if str(evt.get("updated_at", "")) < cutoff:
                continue
            if self.storage.articles_exist(evt.get("event_id", "")):
                continue
            out.append(evt)
            if limit > 0 and len(out) >= limit:
                break
        return out

    def _load_articles(self, event):
        out = []
        for ref in (event.get("articles") or []):
            fp = ref.get("content_fp", "")
            if not fp:
                continue
            a = self.storage.get_cleaned_by_fp(fp)
            if a:
                a["_collection"] = ref.get("etl_collection", "")
                out.append(a)
        return out

    def _build_user_prompt(self, event: dict, articles: list) -> str:
        lines = []
        lines.append("===== 事件信息 =====")
        lines.append(f"事件ID: {event.get('event_id', '')}")
        lines.append(f"事件标题: {event.get('event_title', '')}")
        lines.append(f"事件分类: {event.get('category', '')}")
        lines.append(f"事件概述: {event.get('overview', '')}")
        lines.append(f"来源文章数: {len(articles)} 篇（来自 {len(set(a.get('_collection', '') for a in articles))} 个来源）")
        lines.append("")
        lines.append(f"===== 参考文章（共 {len(articles)} 篇，按发布时间升序）=====")
        for i, art in enumerate(articles, 1):
            source_label = art.get("_source_label", art.get("_collection", "未知"))
            content = (art.get("content", "") or "")[:self.max_content_chars]
            lines.append(f"\n--- 文章{i} ---")
            lines.append(f"来源: {source_label}")
            lines.append(f"标题: {art.get('title', '')}")
            lines.append(f"时间: {art.get('pub_time', '')}")
            lines.append(f"正文:\n{content}")
        lines.append(f"\n请生成 {self.variants} 篇不同视角的财经文章。")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return {}

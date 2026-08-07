"""DemoLLM：自定义 LLM provider 示例 —— 确定性返回，无需 API Key。

用途：无 Key 的端到端演示 / 冒烟测试；同时演示"自定义 LLM 接口"的接入方式：
  config:
    llm:
      provider: demo
      demo:
        module: demo_llm.DemoLLM     # 本文件放在 examples/ 下，运行时需把 examples 加入 sys.path
"""

from __future__ import annotations

import json
import re

from data_to_article.llm.base import BaseLLMClient, LLMResponse


class DemoLLM(BaseLLMClient):
    @classmethod
    def _provider_name(cls) -> str:
        return "demo"

    def __init__(self, config: dict):
        self.model = "demo-1"

    def _build_payload(self, *args, **kwargs):
        raise NotImplementedError("demo provider 不构造真实请求")

    def _parse_response(self, *args, **kwargs):
        raise NotImplementedError("demo provider 不解析真实响应")

    def chat(self, messages: list, system: str = "", temperature=None, max_tokens=None) -> LLMResponse:
        user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
        )
        # 归类路由：返回路由数组（全部视为新事件）
        if "【待归类文章】" in user:
            n = len(re.findall(r"^\d+ \|", user, re.M)) or 1
            return LLMResponse(
                content=json.dumps([
                    {"no": i, "event_id": "", "new_group": "new_1", "confidence": "high", "reason": "demo"}
                    for i in range(1, n + 1)
                ]),
                usage={}, model=self.model,
            )
        # 二创生成：返回多视角文章
        if "篇不同视角" in user:
            return LLMResponse(
                content=json.dumps({"articles": [
                    {"title": f"演示文章{i}", "style": "深度综述", "viewpoint": "综合",
                     "content": f"这是演示生成的第 {i} 篇正文，仅用于无 Key 演示。"}
                    for i in range(1, 3)
                ]}),
                usage={}, model=self.model,
            )
        # 事件概述
        return LLMResponse(
            content=json.dumps({
                "event_title": "演示事件",
                "overview": "演示概述：用于无 Key 端到端演示。",
                "category": "市场动态",
                "keywords": ["演示"],
            }),
            usage={}, model=self.model,
        )
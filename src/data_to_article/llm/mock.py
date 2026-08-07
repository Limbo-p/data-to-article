"""MockClient：确定性返回，不调用任何 API，用于开发/测试/演示（无需 Key）。"""

from __future__ import annotations

from data_to_article.llm.base import BaseLLMClient, LLMResponse


class MockClient(BaseLLMClient):
    @classmethod
    def _provider_name(cls) -> str:
        return "mock"

    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {}) or {}
        self.model = llm_cfg.get("model", "mock-1")
        self.default_temperature = llm_cfg.get("temperature", 0.7)
        self.default_max_tokens = llm_cfg.get("max_tokens", 8192)
        self.max_retries = 0

    def _build_payload(self, messages: list, system: str, temperature: float, max_tokens: int) -> dict:
        raise NotImplementedError("mock provider 不构造真实请求")

    def _parse_response(self, resp_json: dict) -> tuple[str, dict]:
        raise NotImplementedError("mock provider 不解析真实响应")

    def chat(self, messages: list, system: str = "", temperature: float | None = None, max_tokens: int | None = None) -> LLMResponse:
        last = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        content = f"[mock:{self.model}] {last[:200]}"
        return LLMResponse(content=content, usage={"prompt_tokens": 0, "completion_tokens": 0}, model=self.model)

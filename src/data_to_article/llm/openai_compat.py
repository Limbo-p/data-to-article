"""OpenAI 兼容适配器：OpenAI / DeepSeek / Qwen / Moonshot / GLM / Ollama 本地均走此实现。"""

from __future__ import annotations

from data_to_article.llm.base import BaseLLMClient


class OpenAICompatClient(BaseLLMClient):
    @classmethod
    def _provider_name(cls) -> str:
        return "openai_compat"

    def _get_headers(self) -> dict:
        h = super()._get_headers()
        h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _build_payload(self, messages: list, system: str, temperature: float, max_tokens: int) -> dict:
        msgs = list(messages)
        if system:
            msgs.insert(0, {"role": "system", "content": system})
        return {
            "model": self.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _parse_response(self, resp_json: dict) -> tuple[str, dict]:
        choice = resp_json["choices"][0]["message"]
        return choice["content"].strip(), resp_json.get("usage", {})

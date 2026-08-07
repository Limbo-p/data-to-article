"""Anthropic Claude 适配器（消息格式与认证方式不同于 OpenAI）。"""

from __future__ import annotations

from data_to_article.llm.base import BaseLLMClient


class AnthropicClient(BaseLLMClient):
    @classmethod
    def _provider_name(cls) -> str:
        return "anthropic"

    def _get_headers(self) -> dict:
        h = super()._get_headers()
        h["x-api-key"] = self.api_key
        h["anthropic-version"] = "2023-06-01"
        return h

    def _get_endpoint(self) -> str:
        return f"{self.base_url}/v1/messages"

    def _build_payload(self, messages: list, system: str, temperature: float, max_tokens: int) -> dict:
        filtered = [m for m in messages if m.get("role") != "system"]
        return {
            "model": self.model,
            "messages": filtered,
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _parse_response(self, resp_json: dict) -> tuple[str, dict]:
        content = "".join(b["text"] for b in resp_json["content"] if b.get("type") == "text")
        usage = {
            "prompt_tokens": resp_json.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": resp_json.get("usage", {}).get("output_tokens", 0),
        }
        return content.strip(), usage

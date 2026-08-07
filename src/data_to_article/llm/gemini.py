"""Google Gemini 适配器（generateContent 端点，key 放在 URL query）。"""

from __future__ import annotations

from data_to_article.llm.base import BaseLLMClient


class GeminiClient(BaseLLMClient):
    @classmethod
    def _provider_name(cls) -> str:
        return "gemini"

    def _get_endpoint(self) -> str:
        base = self.base_url.rstrip("/") or "https://generativelanguage.googleapis.com"
        return f"{base}/v1beta/models/{self.model}:generateContent?key={self.api_key}"

    def _build_payload(self, messages: list, system: str, temperature: float, max_tokens: int) -> dict:
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload

    def _parse_response(self, resp_json: dict) -> tuple[str, dict]:
        candidate = resp_json["candidates"][0]
        content = "".join(p["text"] for p in candidate["content"]["parts"])
        usage = resp_json.get("usageMetadata", {})
        return content.strip(), {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
        }

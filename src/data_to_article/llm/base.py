"""LLM 接口：BaseLLMClient + LLMResponse，所有业务只依赖这里。"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional



@dataclass
class LLMResponse:
    content: str
    usage: dict
    model: str


class BaseLLMClient(ABC):
    """自定义 LLM：继承本类并实现 _provider_name/_build_payload/_parse_response，
    然后在 config 的 llm.<名称>.module 指向你的类。"""

    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {}) or {}
        provider = self._provider_name()
        provider_cfg = llm_cfg.get(provider, {}) or {}
        env_key = provider_cfg.get("api_key_env", f"{provider.upper()}_API_KEY")
        self.api_key = os.environ.get(env_key, "")
        if not self.api_key:
            raise ValueError(f"环境变量 {env_key} 未设置")
        self.model = provider_cfg.get("model", "gpt-4o")
        self.base_url = (provider_cfg.get("base_url") or "https://api.openai.com").rstrip("/")
        self.default_temperature = llm_cfg.get("temperature", 0.7)
        self.default_max_tokens = llm_cfg.get("max_tokens", 8192)
        self.max_retries = 3

    @classmethod
    @abstractmethod
    def _provider_name(cls) -> str:
        ...

    @abstractmethod
    def _build_payload(self, messages: list, system: str, temperature: float, max_tokens: int) -> dict:
        ...

    @abstractmethod
    def _parse_response(self, resp_json: dict) -> tuple[str, dict]:
        ...

    def _get_headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def _get_endpoint(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def chat(self, messages: list, system: str = "", temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> LLMResponse:
        try:
            import requests
        except ImportError:
            raise RuntimeError("???? requests???????????? llm.provider=mock")
        payload = self._build_payload(
            messages,
            system,
            temperature if temperature is not None else self.default_temperature,
            max_tokens if max_tokens is not None else self.default_max_tokens,
        )
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(self._get_endpoint(), headers=self._get_headers(), json=payload, timeout=120)
                resp.raise_for_status()
                content, usage = self._parse_response(resp.json())
                return LLMResponse(content=content, usage=usage, model=self.model)
            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM 调用失败（{self.max_retries} 次重试）: {last_error}")

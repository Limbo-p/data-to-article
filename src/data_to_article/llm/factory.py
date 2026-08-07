"""LLM 工厂：内置 provider 注册表 + 自定义 provider 动态加载。

自定义方式（config.example.yaml）：
  llm:
    provider: my_provider
    my_provider:
      module: mypackage.my_llm.MyClient   # 继承 BaseLLMClient 的类
      api_key_env: MY_LLM_KEY
      base_url: https://...
      model: ...
"""

from __future__ import annotations

import importlib

from data_to_article.llm.anthropic import AnthropicClient
from data_to_article.llm.base import BaseLLMClient
from data_to_article.llm.gemini import GeminiClient
from data_to_article.llm.mock import MockClient
from data_to_article.llm.openai_compat import OpenAICompatClient

_BUILTIN = {
    "openai_compat": OpenAICompatClient,
    "openai": OpenAICompatClient,
    "deepseek": OpenAICompatClient,
    "qwen": OpenAICompatClient,
    "moonshot": OpenAICompatClient,
    "anthropic": AnthropicClient,
    "gemini": GeminiClient,
    "mock": MockClient,
}


def create_llm_client(config: dict) -> BaseLLMClient:
    llm_cfg = config.get("llm", {}) or {}
    provider = llm_cfg.get("provider", "mock")
    cls = _BUILTIN.get(provider)
    if cls is None:
        provider_cfg = llm_cfg.get(provider, {}) or {}
        module_path = provider_cfg.get("module", "")
        if not module_path:
            raise ValueError(
                f"未知 LLM provider: {provider}（可配置 llm.{provider}.module 指定自定义实现）"
            )
        mod_name, _, attr = module_path.rpartition(".")
        cls = getattr(importlib.import_module(mod_name), attr)
    return cls(config)

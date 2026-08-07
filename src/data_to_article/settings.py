"""统一配置加载：config/config.yaml（或 config.example.yaml）+ 环境变量覆盖。"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:
    import yaml
except ImportError:  # 零依赖模式：未安装 PyYAML 时按 JSON 解析（JSON 是 YAML 子集）
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "config.example.yaml"

_ENV_OVERRIDES = {
    "DTA_STORAGE": ("storage", "backend"),
    "DTA_STORAGE_ROOT": ("storage", "root"),
    "MONGO_URI": ("storage", "uri"),
    "MONGO_DB": ("storage", "database"),
    "DTA_LLM_PROVIDER": ("llm", "provider"),
}


def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.exists():
        cfg_path = EXAMPLE_CONFIG
    text = cfg_path.read_text(encoding="utf-8")
    if yaml is not None:
        cfg = yaml.safe_load(text) or {}
    else:
        cfg = json.loads(text)
    for env_name, keys in _ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if not value:
            continue
        node = cfg
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
    return cfg

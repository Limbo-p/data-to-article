"""prompt 模板加载：优先 config/prompts/<name>.txt，否则使用内置默认。"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_prompt(name: str, fallback: str) -> str:
    p = PROJECT_ROOT / "config" / "prompts" / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return fallback

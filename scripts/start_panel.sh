#!/bin/sh
# data-to-article 总控面板启动脚本（Linux / macOS）
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
# 首次运行自动装依赖（可跳过：已装过时很快）
"$PY" -m pip install -e ".[mysql]" >/dev/null 2>&1 || true
exec "$PY" -m data_to_article.web.server "$@"
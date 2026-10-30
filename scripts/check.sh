#!/usr/bin/env bash
# 本地质量门：与 CI 的 quality job 完全一致。
#
#   bash scripts/check.sh
#
# Windows 上可用 Git Bash 执行；也可以逐条跑下面的命令。
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== 依赖 =="
uv sync --frozen

echo "== ruff =="
uv run ruff check .

echo "== pyright =="
uv run pyright

echo "== pytest =="
uv run pytest -q

echo "== 评测集校验 =="
uv run python scripts/eval/check_cases.py

echo "== 前端语法 =="
node --check src/prompt_search_agent/web/app.js

echo "== compose 配置 =="
docker compose config >/dev/null

echo
echo "全部通过"

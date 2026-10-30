#!/usr/bin/env bash
# 回滚到上一个版本，并交换 current/previous，所以可以连续回滚来回切换。
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/prompt-atelier}"
SERVICE="${SERVICE:-prompt-atelier}"

releases="$APP_ROOT/releases"
current="$APP_ROOT/current"
previous="$APP_ROOT/previous"

if [ ! -L "$previous" ]; then
  echo "没有 上一版本 记录，无法回滚"
  exit 1
fi

target="$(readlink -f "$previous")"
active="$(readlink -f "$current")"

if [ ! -d "$target" ]; then
  echo "上一版本目录已不存在：$target"
  echo "可用版本："
  ls -1dt "$releases"/* 2>/dev/null || true
  exit 1
fi

ln -sfn "$active" "$previous"
ln -sfn "$target" "$current"

systemctl restart "$SERVICE"
sleep 2

if ! systemctl is-active --quiet "$SERVICE"; then
  echo "回滚后服务仍未启动，请查看 journalctl -u $SERVICE -n 100"
  exit 1
fi

echo "已回滚 -> $target"
curl -fsS "http://127.0.0.1:${PORT:-8000}/api/version" || true
echo

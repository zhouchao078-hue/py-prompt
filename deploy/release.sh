#!/usr/bin/env bash
# 构建并切换到一个新版本。切换后服务起不来会自动退回上一个版本。
#
# 目录约定：
#   /opt/prompt-atelier/repo/          git 仓库（只做拉取，不直接运行）
#   /opt/prompt-atelier/releases/<ts>-<sha>/
#   /opt/prompt-atelier/current   -> 当前版本（符号链接）
#   /opt/prompt-atelier/previous  -> 上一个版本（符号链接，供 rollback 用）
#   /opt/prompt-atelier/shared/app.env   环境变量（不进仓库）
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/prompt-atelier}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
SERVICE="${SERVICE:-prompt-atelier}"

repo="$APP_ROOT/repo"
releases="$APP_ROOT/releases"
current="$APP_ROOT/current"
previous="$APP_ROOT/previous"

stamp="$(date +%Y%m%d-%H%M%S)"
git -C "$repo" fetch --quiet origin
commit="$(git -C "$repo" rev-parse --short origin/main)"
target="$releases/$stamp-$commit"

mkdir -p "$releases"
git -C "$repo" worktree add --detach "$target" "$commit" >/dev/null
printf 'GIT_COMMIT=%s\nBUILD_TIME=%s\n' "$commit" "$(date -Iseconds)" >"$target/release.env"

(cd "$target" && uv sync --frozen --no-dev)

old=""
if [ -L "$current" ]; then
  old="$(readlink -f "$current")"
  ln -sfn "$old" "$previous"
fi

ln -sfn "$target" "$current"

if ! systemctl restart "$SERVICE"; then
  echo "启动失败，回滚"
  if [ -n "$old" ]; then
    ln -sfn "$old" "$current"
    systemctl restart "$SERVICE" || true
  fi
  exit 1
fi

sleep 2
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "服务未处于 active，回滚"
  if [ -n "$old" ]; then
    ln -sfn "$old" "$current"
    systemctl restart "$SERVICE" || true
  fi
  exit 1
fi

# 只保留最近 N 个版本，避免磁盘被吃满。
ls -1dt "$releases"/* | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf

echo "已切换 -> $target"
echo "回滚命令：deploy/rollback.sh"

#!/usr/bin/env bash
# 服务器端部署：切到指定镜像，健康检查不过自动回滚。
#
#   remote-deploy.sh ghcr.io/owner/repo:abc1234def56
#   remote-deploy.sh --rollback
#
# 只靠两个状态文件记录历史，不依赖 git：
#   .current-image   当前在跑的镜像
#   .previous-image  上一个能健康运行的镜像
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/prompt-atelier}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
STATE_CURRENT="$APP_DIR/.current-image"
STATE_PREVIOUS="$APP_DIR/.previous-image"

cd "$APP_DIR"

log() { printf '[deploy] %s\n' "$*"; }

container_id() {
  docker compose ps -q app 2>/dev/null | head -n1
}

health_status() {
  local cid
  cid="$(container_id)"

  if [ -z "$cid" ]; then
    echo "missing"
    return
  fi

  docker inspect \
    --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "$cid" 2>/dev/null || echo unknown
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT))

  while [ "$SECONDS" -lt "$deadline" ]; do
    local status
    status="$(health_status)"

    case "$status" in
      healthy) log "容器健康"; return 0 ;;
      none)    # 镜像没带 HEALTHCHECK 时退回进程存活判断
               if [ -n "$(container_id)" ]; then log "容器在运行（无健康检查）"; return 0; fi ;;
    esac

    sleep 3
  done

  log "等待健康超时（最后状态：$(health_status)）"
  return 1
}

switch_to() {
  local image="$1"
  log "拉取 $image"
  APP_IMAGE="$image" docker compose pull app
  log "启动 $image"
  APP_IMAGE="$image" docker compose up -d app
}

rollback() {
  local target="$1"
  log "回滚到 $target"
  switch_to "$target"

  if wait_healthy; then
    echo "$target" >"$STATE_CURRENT"
    log "回滚成功"
    return 0
  fi

  log "回滚后仍不健康，需要人工介入"
  return 1
}

if [ "${1:-}" = "--rollback" ]; then
  previous="$(cat "$STATE_PREVIOUS" 2>/dev/null || true)"

  if [ -z "$previous" ]; then
    log "没有可回滚的历史镜像"
    exit 1
  fi

  current="$(cat "$STATE_CURRENT" 2>/dev/null || true)"
  rollback "$previous"
  echo "$current" >"$STATE_PREVIOUS"
  exit 0
fi

TARGET="${1:?用法: remote-deploy.sh <image:tag> | --rollback}"
CURRENT="$(cat "$STATE_CURRENT" 2>/dev/null || true)"

if [ "$TARGET" = "$CURRENT" ]; then
  log "目标镜像已经是当前版本，仍执行一次收敛：$TARGET"
fi

switch_to "$TARGET"

if wait_healthy; then
  if [ -n "$CURRENT" ] && [ "$CURRENT" != "$TARGET" ]; then
    echo "$CURRENT" >"$STATE_PREVIOUS"
  fi
  echo "$TARGET" >"$STATE_CURRENT"
  log "部署完成：$TARGET"
  exit 0
fi

log "新版本不健康"
if [ -n "$CURRENT" ] && [ "$CURRENT" != "$TARGET" ]; then
  rollback "$CURRENT" || true
fi

exit 1

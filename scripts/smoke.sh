#!/usr/bin/env bash
# 上线冒烟：跑完 8 项即为可对外。
#   BASE=https://atelier.example.com TOKEN=你的口令 ./scripts/smoke.sh
set -uo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:-}"
FAILED=0

check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf 'PASS  %-28s %s\n' "$name" "$actual"
  else
    printf 'FAIL  %-28s want=%s got=%s\n' "$name" "$expected" "$actual"
    FAILED=$((FAILED + 1))
  fi
}

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

BIG_BODY="$(mktemp)"
python3 -c 'print("{\"message\":\"" + "雪"*300000 + "\"}")' >"$BIG_BODY"

check "健康检查"       "200" "$(code "$BASE/api/health")"
check "版本"           "200" "$(code "$BASE/api/version")"
check "首页"           "200" "$(code "$BASE/")"
check "未带口令被拒"   "401" "$(code -X POST "$BASE/api/prompt" \
  -H 'Content-Type: application/json' -d '{"message":"雪夜白猫"}')"
check "带口令可生成"   "200" "$(code -X POST "$BASE/api/prompt" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"雪夜里穿汉服的少女，电影感"}')"
check "历史越权被拒"   "403" "$(code "$BASE/api/history/not-mine" \
  -H "Authorization: Bearer $TOKEN")"
check "写库被禁用"     "403" "$(code -X POST "$BASE/api/prompts" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"prompt_text":"should fail"}')"
check "超大请求体被拒" "413" "$(code -X POST "$BASE/api/prompt" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  --data-binary "@$BIG_BODY")"

rm -f "$BIG_BODY"

echo
echo "健康详情: $(curl -s "$BASE/api/health")"

if [ "$FAILED" -ne 0 ]; then
  echo "有 $FAILED 项失败"
  exit 1
fi

echo "全部通过"

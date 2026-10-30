# Prompt Atelier 上线 SOP

> 适用对象：本仓库维护者
> 目标：把当前本地可运行的 demo，在 **3~7 天**内改造成**可公开访问、成本可控、故障可查**的在线 demo。
> 原则：**不重构业务链路**，只加"服务化外壳"。每一步都有验证命令和通过标准，不通过不进下一步。

---

## 0. 总览

### 0.1 阶段划分与验收门

| 阶段 | 目标 | 包含步骤 | 验收门（不通过不许往下走） |
|---|---|---|---|
| **A 安全可暴露** | 敢把端口开到公网 | S1~S6 | 无口令 401、刷 30 次被 429、黑 thread_id 403、空库自愈 |
| **B 体验可演示** | 首轮 8 秒内出结果、生图不 504 | S7~S9 | P50 延迟 ≤ 8s、生图 180s 不超时、示例 chip 秒回 |
| **C 可运维** | 一台机器一条命令起来 | S10~S13 | 新机冷启动 10 分钟内跑通验收脚本 |
| **D 上线验收** | 交付 | 验收 SOP | 18 项全绿 |

### 0.2 产出物清单

```
docs/deploy-sop.md                          ← 本文档
src/prompt_search_agent/guard.py            ← 口令/限流/trace/签名
src/prompt_search_agent/storage/seed.py     ← seed 自动导入
src/prompt_search_agent/config.py           ← 配置改造
src/prompt_search_agent/webapp.py           ← 接口改造
src/prompt_search_agent/web/app.js          ← 前端适配
data/seed/prompts.jsonl.gz                  ← 提示词库快照（进 Git）
scripts/export_seed.py
scripts/warm_cache.py
scripts/smoke.sh
Dockerfile / .dockerignore / docker-compose.yml
deploy/Caddyfile
```

### 0.3 如果只有 3 天

砍掉 S7、S8、S9（体验优化），生图入口在页面上标注"未开放"，只做 **S1~S6 + S10~S13**。
代价：首轮 10~20 秒、生图走同步可能 504。可接受，但**A 阶段一步都不能省**。

### 0.4 实施状态（最近一次更新）

| 步骤 | 状态 | 说明 |
|---|---|---|
| S0 基线固化 | ⬜ 待做 | 提交前记得打 `pre-launch` tag |
| S1 配置解耦 | ✅ 已完成 | `config.py` 改为 `DATA_DIR` 派生 + `validate_runtime()` |
| S2 seed | ✅ 已完成 | 798 条；空库导入 798，二次导入 0（幂等已验证） |
| S3 口令限流 | ✅ 已完成 | `guard.py`；401 / 429 / 503 已真机验证 |
| S4 越权修复 | ✅ 已完成 | thread_id HMAC 签名；越权 403 已验证 |
| S5 错误收敛 | ✅ 已完成 | trace_id 响应头 + 友好文案 + 异常日志 |
| S6 健康检查 | ✅ 已完成 | 结构化 health + `DEMO_READONLY_LIBRARY` |
| 前端适配 | ✅ 已完成 | 口令门、thread token、降级状态点 |
| S8 生图异步 | ✅ 已完成 | `/api/images/jobs` + 前端 1.5s 轮询 |
| S9 缓存预热 | ✅ 已完成 | `scripts/warm_cache.py`（脚本就绪，尚未真实预热） |
| S7 延迟优化 | ⬜ 待做 | 实测单轮 6.8s，未触发重构阈值，保持观察 |
| 异步化 | ✅ 已完成 | `to_thread` + `CapacityLimiter`，上限 `MAX_CONCURRENT_GENERATIONS` |
| SSE 流式 | ✅ 已完成 | `POST /api/prompt/stream`，首字节 0.07s，实测 23s 长任务不再干等 |
| 静态指纹 | ✅ 已完成 | 启动时内容哈希改写 `index.html`，命中回 `immutable` |
| 发布回滚 | ✅ 已完成 | `deploy/release.sh` / `rollback.sh` / systemd 单元 + `/api/version` |
| P0 健壮性 | ✅ 已完成 | 熔断 + 45s 预算 + Tavily/会话写降级 + 请求体上限 + SSRF 收口 + XFF 取最右 |
| P1 资源与交付 | ✅ 已完成 | 图片三层配额 + 线程池、排队上限、SSE 取消、磁盘巡检与水位、Dockerfile/compose/Caddy、CI、smoke.sh |
| P2 可观测与规范 | ✅ 已完成 | `/metrics`、前端超时与断流提示、schema 迁移版本化、`auto_vacuum` + 增量回收、provider 侧 webp |
| S10~S13 部署 | ✅ 已完成 | 容器化与 Caddy 已就绪 |

> 下面各步骤的代码块是**设计参考**，实际实现以仓库代码为准（命名略有调整，例如
> `Settings.thread_secret_value`、`Settings.is_public_mode`）。

---

## 1. 前置准备（T-7 天开始，因为备案有周期）

### 1.1 清单

| 项 | 要求 | 备注 |
|---|---|---|
| 服务器 | 2C2G / 40G 盘 / Ubuntu 22.04 | 单机足够，别上 K8s |
| 域名 | 一个二级域名，如 `atelier.example.com` | 国内节点需 **ICP 备案**，5~20 天；赶时间先用海外节点或纯 IP + 端口 |
| DeepSeek Key | 充值，设消费上限 | 主成本项 |
| Tavily Key | 免费额度 1000 次/月 | 可先关闭联网功能 |
| 图片中转 | OpenAI-compatible，确认单价 | **最贵**，demo 建议限流最严 |
| HTTPS | Caddy 自动签发 | 域名必须已解析到服务器 |

### 1.2 成本估算（按 1000 次真实对话）

- LLM：每轮 4~5 次调用、约 2k 输入 / 500 输出 → **分币/轮**，1000 轮在十元以内。
- Tavily：每轮 1 search + 1 extract ≈ 2 credits → 1000 轮约 2000 credits（超出免费额度）。
- 图片：**大头**，按中转单价 × 张数，务必在 S3 卡死日配额。

> 结论：**演示期把生图日配额压到 50 张**，其余靠缓存。

---

## 2. 阶段 A：安全可暴露

### S0 — 基线固化

```powershell
cd D:\PY\PythonProject\prompt-search-agent
git status                # 必须干净
.\.venv\Scripts\python.exe -m pytest -q
git tag pre-launch && git push origin pre-launch
```

**通过标准**：工作区干净、测试全绿、打上回滚锚点 `pre-launch`。

---

### S1 — 配置与数据路径解耦

**问题**：`PROJECT_ROOT = Path(__file__).resolve().parents[2]` 在开发态正确，但 wheel 装进 `site-packages` 后会指向 `.venv/Lib`，DB 和图片写错位置；容器里还可能只读直接崩。另外 `deepseek_api_key` 是必填，缺 key 启动就抛异常且无提示。

**改动文件**：`src/prompt_search_agent/config.py`

```python
"""Application configuration."""

import os
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    raw = os.getenv("DATA_DIR", "").strip()
    return Path(raw) if raw else PROJECT_ROOT / "data"


DATA_DIR = _default_data_dir()


class Settings(BaseSettings):
    # —— 允许缺省：由 validate_runtime() 给出中文诊断，而不是启动即崩
    deepseek_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_api_base: str = "https://api.deepseek.com"

    # —— 数据路径全部从 DATA_DIR 派生
    data_dir: Path = DATA_DIR
    prompt_db_path: Path = DATA_DIR / "indexes" / "prompt_index.sqlite3"
    image_output_dir: Path = DATA_DIR / "generated" / "images"
    seed_file: Path = DATA_DIR / "seed" / "prompts.jsonl.gz"

    # —— demo 运行约束
    demo_access_code: SecretStr | None = None
    thread_secret: SecretStr = SecretStr("dev-only-change-me")
    rate_limit_per_ip_per_hour: int = 20
    daily_request_cap: int = 500
    demo_readonly_library: bool = True

    # —— 原有字段保持不变
    sqlite_busy_timeout_ms: int = 5000
    conversation_recent_messages: int = 8
    conversation_compress_after_messages: int = 12
    conversation_summary_max_chars: int = 800
    tavily_max_results: int = 5
    tavily_fetch_max_urls: int = 3
    tavily_max_chars: int = 2500
    image_api_key: SecretStr | None = None
    image_api_base: str = "https://api.openai.com/v1"
    image_model: str | None = None
    image_response_format: str | None = None
    image_timeout_seconds: float = 120.0
    image_max_download_bytes: int = 25_000_000
    image_retention_days: int = 7
    image_size_square: str = "1024x1024"
    image_size_landscape: str = "1536x1024"
    image_size_portrait: str = "1024x1536"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def validate_runtime(self) -> list[str]:
        """返回非致命的配置问题，启动时打日志，不阻断进程。"""
        problems: list[str] = []

        if not self._filled(self.deepseek_api_key):
            problems.append("DEEPSEEK_API_KEY 未配置 → 提示词生成不可用")
        if not self._filled(self.demo_access_code):
            problems.append("DEMO_ACCESS_CODE 未配置 → 公网部署必须设置，否则接口裸奔")
        if self.thread_secret.get_secret_value() == "dev-only-change-me":
            problems.append("THREAD_SECRET 仍是默认值 → 必须更换为随机串")
        if not self.prompt_db_path.parent.exists():
            problems.append(f"数据库目录不存在 → {self.prompt_db_path.parent}")

        return problems

    @staticmethod
    def _filled(value: SecretStr | None) -> bool:
        return value is not None and bool(value.get_secret_value().strip())
```

**同步改 `.env.example`**，追加：

```env
# —— 上线必填 ——
DEMO_ACCESS_CODE=
THREAD_SECRET=
DATA_DIR=

# —— demo 配额 ——
RATE_LIMIT_PER_IP_PER_HOUR=20
DAILY_REQUEST_CAP=500
DEMO_READONLY_LIBRARY=true
```

**验证**：

```powershell
$env:DATA_DIR='D:\tmp\atelier-data'
.\.venv\Scripts\python.exe -c "from prompt_search_agent.config import Settings; s=Settings(); print(s.prompt_db_path); print(s.validate_runtime())"
```

**通过标准**：
- 输出路径以 `D:\tmp\atelier-data` 开头；
- 缺 key 时 `validate_runtime()` 返回的是**中文问题列表**，而不是抛异常。

> ⚠️ 注意：`DATA_DIR` 必须在**真实环境变量**里设置才生效（pydantic-settings 读 `.env` 不会污染 `os.environ`）。容器里用 `environment:` 注入即可。

---

### S2 — 提示词库随包发布（否则上线即空库）

**问题**：`data/indexes/` 和 `data/raw/` 都在 `.gitignore`，仓库里没有任何源数据。新机器启动后 `prompt_count = 0`，FTS 检索链全空 —— **demo 的核心卖点直接消失**。

**步骤 1**：新建 `scripts/export_seed.py`

```python
"""把本地构建好的提示词库导出为可提交进 Git 的 seed 文件。"""

import argparse
import gzip
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "indexes" / "prompt_index.sqlite3"
DEFAULT_OUT = PROJECT_ROOT / "data" / "seed" / "prompts.jsonl.gz"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出提示词库快照")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"数据库不存在: {args.db}")
        return 1

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT prompt_text, category, source_file, source_sheet, source_row
        FROM prompts
        ORDER BY id
        """
    ).fetchall()
    connection.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")

    print(f"已导出 {len(rows)} 条 -> {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**步骤 2**：新建 `src/prompt_search_agent/storage/seed.py`

```python
"""首次启动时把随包发布的 seed 数据导入空库。"""

import gzip
import json
import logging
from contextlib import closing
from pathlib import Path

from prompt_search_agent.ingest.records import RawPromptRecord
from prompt_search_agent.ingest.transformer import prepare_prompt_records
from prompt_search_agent.storage.database import connect_database
from prompt_search_agent.storage.repository import insert_prompt_records

LOGGER = logging.getLogger(__name__)


def import_seed_if_empty(
    db_path: Path,
    seed_file: Path,
    busy_timeout_ms: int = 5000,
) -> int:
    """仅当 prompts 表为空时导入 seed，返回导入条数。"""
    if not seed_file.is_file():
        LOGGER.warning("seed 文件不存在，跳过导入: %s", seed_file)
        return 0

    with closing(connect_database(db_path, busy_timeout_ms)) as connection:
        existing = int(
            connection.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
        )

    if existing:
        LOGGER.info("提示词库已有 %s 条，跳过 seed 导入", existing)
        return 0

    raw_records: list[RawPromptRecord] = []
    with gzip.open(seed_file, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            raw_records.append(
                RawPromptRecord(
                    prompt_text=str(item["prompt_text"]),
                    category=item.get("category"),
                    source_file=str(item.get("source_file") or "seed"),
                    source_sheet=str(item.get("source_sheet") or "seed"),
                    source_row=int(item.get("source_row") or 0),
                )
            )

    inserted = insert_prompt_records(
        db_path,
        prepare_prompt_records(raw_records),
        busy_timeout_ms,
    )
    LOGGER.info("seed 导入完成: %s 条", inserted)
    return inserted
```

**步骤 3**：在 `storage/__init__.py` 追加导出，并在 `webapp.py` 的 lifespan 里调用：

```python
# webapp.py lifespan 内，build_prompt_service 之后
from prompt_search_agent.storage.seed import import_seed_if_empty

app.state.prompt_service = build_prompt_service(settings)
app.state.image_skill = build_image_generation_skill(settings)
import_seed_if_empty(
    settings.prompt_db_path,
    settings.seed_file,
    settings.sqlite_busy_timeout_ms,
)
```

**步骤 4**：导出并提交

```powershell
.\.venv\Scripts\python.exe scripts\export_seed.py
git add data/seed/prompts.jsonl.gz scripts/export_seed.py
git commit -m "chore: 发布提示词库 seed"
```

**验证**：

```powershell
$env:DATA_DIR='D:\tmp\atelier-empty'
Remove-Item -Recurse -Force D:\tmp\atelier-empty -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -c "from prompt_search_agent.config import Settings; from prompt_search_agent.storage.database import initialize_database; from prompt_search_agent.storage.seed import import_seed_if_empty; s=Settings(); initialize_database(s.prompt_db_path); print('imported', import_seed_if_empty(s.prompt_db_path, s.seed_file))"
```

**通过标准**：
- 空目录下打印 `imported` 为千级数字；
- **再跑一次打印 `imported 0`**（幂等，不重复导入）；
- `git ls-files data/seed` 能看到该文件。

---

### S3 — 访问口令 + 限流 + 日配额（最高优先级）

**问题**：5 个接口全部匿名可调，而一轮对话消耗 4~5 次 LLM + 1~2 次 Tavily + 可能 1 次生图。**公网暴露第一天就会被刷**。

**步骤 1**：新建 `src/prompt_search_agent/guard.py`

> ⚠️ 不要放进 `web/` 目录 —— 那个目录被 `app.mount("/static", ...)` 整个暴露，`.py` 会被当静态文件下载。

```python
"""访问口令、IP 限流、全局日配额与 trace_id。"""

import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

RATE_WINDOW_SECONDS = 3600.0
EXEMPT_PREFIXES = ("/static/",)
EXEMPT_PATHS = {"/", "/api/health", "/favicon.svg"}


class DemoGuard:
    """单进程内存态限流器。多 worker 部署会失效，demo 请保持 1 worker。"""

    def __init__(
        self,
        access_code: str,
        per_ip_limit: int,
        daily_cap: int,
    ) -> None:
        self.access_code = access_code
        self.per_ip_limit = per_ip_limit
        self.daily_cap = daily_cap
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day = ""
        self._day_count = 0

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
        return request.client.host if request.client else "unknown"

    def check(self, request: Request) -> JSONResponse | None:
        path = request.url.path

        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return None

        now = time.monotonic()

        # 全局日配额
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._day_count = today, 0
        if self._day_count >= self.daily_cap:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "quota_exhausted",
                    "message": "今日演示额度已用完，明天再来。",
                },
            )

        # 每 IP 滑动窗口
        ip = self._client_ip(request)
        hits = self._hits[ip]
        while hits and now - hits[0] > RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.per_ip_limit:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limited",
                    "message": "请求太频繁了，歇一会儿再试。",
                },
            )

        # 访问口令
        token = request.headers.get("authorization", "")
        token = token.removeprefix("Bearer ").strip()
        if token != self.access_code:
            return JSONResponse(
                status_code=401,
                content={
                    "code": "unauthorized",
                    "message": "需要访问口令。",
                },
            )

        hits.append(now)
        self._day_count += 1
        return None


def install_guard(app: FastAPI, settings) -> None:
    if settings is None or settings.demo_access_code is None:
        return

    guard = DemoGuard(
        settings.demo_access_code.get_secret_value(),
        settings.rate_limit_per_ip_per_hour,
        settings.daily_request_cap,
    )

    @app.middleware("http")
    async def demo_guard_middleware(request: Request, call_next):
        rejection = guard.check(request)
        if rejection is not None:
            return rejection
        return await call_next(request)
```

**步骤 2**：`webapp.py` 的 `create_app()` 里，`app = FastAPI(...)` 之后立刻安装：

```python
install_guard(app, app_settings)
```

> 集成测试注入 fake service 时 `app_settings` 为 `None`，中间件不装，不影响现有测试。

**步骤 3**：前端适配 `web/app.js`

```js
function accessToken() {
  try {
    return localStorage.getItem("prompt-atelier-token") || "";
  } catch {
    return "";
  }
}

function authHeaders(extra = {}) {
  const token = accessToken();

  if (!token) {
    return extra;
  }

  return { ...extra, Authorization: `Bearer ${token}` };
}

function requestAccessCode() {
  const next = window.prompt("请输入演示访问口令");

  if (next && next.trim()) {
    try {
      localStorage.setItem("prompt-atelier-token", next.trim());
    } catch {
      // 存不了就本次生效
    }
  }
}
```

然后在 `postJson` 和两处 `fetch` 里加 `headers: authHeaders({ "Content-Type": "application/json" })`，并在 `response.status === 401` 时调用 `requestAccessCode()` 后重试一次。

**验证**：

```powershell
# 无口令
curl.exe -s -o NUL -w "%{http_code}`n" -X POST http://127.0.0.1:8000/api/prompt -H "Content-Type: application/json" -d "{\"message\":\"测试\"}"
# 期望 401

# 有口令
curl.exe -s -o NUL -w "%{http_code}`n" -X POST http://127.0.0.1:8000/api/prompt -H "Content-Type: application/json" -H "Authorization: Bearer <CODE>" -d "{\"message\":\"测试\"}"
# 期望 200

# 限流
1..30 | ForEach-Object { curl.exe -s -o NUL -w "%{http_code} " -X POST http://127.0.0.1:8000/api/prompt -H "Content-Type: application/json" -H "Authorization: Bearer <CODE>" -d "{\"message\":\"测试\"}" }
# 期望第 21 次起出现 429
```

**通过标准**：401 / 429 / 503 三种状态码都按预期出现，且 `/api/health` 不受限流影响（监控要能一直探活）。

---

### S4 — 会话越权修复

**问题**：`GET /api/history/{thread_id}` 拿到任意 thread_id 就能读别人完整对话；`POST /api/prompt` 也信任客户端传的 thread_id，可往别人会话写。

**方案**：服务端用 `THREAD_SECRET` 给 thread_id 签名，客户端拿着 token 才能读写。

**步骤 1**：`guard.py` 追加

```python
import hashlib
import hmac


def sign_thread_id(thread_id: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        thread_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def verify_thread_id(thread_id: str, token: str, secret: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(sign_thread_id(thread_id, secret), token)
```

**步骤 2**：`webapp.py`

```python
# PromptResponse / MediaResponse 增加字段
thread_token: str = ""

# 两个接口在 return 前
thread_token=sign_thread_id(result.thread_id, thread_secret),

# generate_prompt 入口处，若带 thread_id 必须验签
if payload.thread_id and not verify_thread_id(
    payload.thread_id,
    request.headers.get("x-thread-token", ""),
    thread_secret,
):
    raise HTTPException(status_code=403, detail="无权访问该会话")

# history 接口入口处
if not verify_thread_id(thread_id, request.headers.get("x-thread-token", ""), thread_secret):
    raise HTTPException(status_code=403, detail="无权访问该会话")
```

`thread_secret` 从 `request.app.state.settings.thread_secret.get_secret_value()` 取。

**步骤 3**：前端把 token 与 thread_id 一起存

```js
function saveThreadId(tool, threadId, threadToken) {
  // …原逻辑
  try {
    localStorage.setItem(`prompt-atelier-thread-token-${tool}`, threadToken || "");
  } catch {}
}
```

`/api/history` 请求带 `x-thread-token`。

**验证**：

```powershell
# 拿到 A 的 thread_id 和 A 的 token 正常
curl.exe -s -o NUL -w "%{http_code}`n" "http://127.0.0.1:8000/api/history/<A_ID>" -H "x-thread-token: <A_TOKEN>"
# 期望 200

# 用 A 的 thread_id、不带 token（或 B 的 token）
curl.exe -s -o NUL -w "%{http_code}`n" "http://127.0.0.1:8000/api/history/<A_ID>"
# 期望 403
```

**通过标准**：200 / 403 符合预期；**前端刷新页面后历史记录仍能恢复**（说明 token 持久化正确）。

---

### S5 — 错误收敛 + trace_id

**问题**：`HTTPException(422, detail=str(exc))` 把内部异常原文（可能含上游地址、HTML 错误页）直接返回浏览器；出问题无法定位。

**步骤 1**：`guard.py` 追加 trace 中间件

```python
from uuid import uuid4


def install_trace(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("x-request-id") or uuid4().hex[:16]
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-request-id"] = trace_id
        return response
```

**步骤 2**：统一异常体

```python
# webapp.py，create_app 内
@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "-")
    LOGGER.exception(
        "unhandled trace_id=%s path=%s", trace_id, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "服务暂时不可用，请稍后再试。",
            "trace_id": trace_id,
        },
    )
```

业务错误改成：

```python
except PromptServiceError as exc:
    LOGGER.warning("prompt failed trace_id=%s err=%s", request.state.trace_id, exc)
    raise HTTPException(
        status_code=422,
        detail="这次没能生成，换个说法再试一次。",
    ) from exc
```

**步骤 3**：前端兼容新错误体（`app.js`）

```js
throw new Error(data.message || data.detail || "请求失败，请稍后再试。");
```

**步骤 4**：日志格式

`webapp.run()` 里：

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
```

**验证**：故意把 `DEEPSEEK_API_BASE` 改错，发一次请求 → 前端看到友好文案，服务端日志有 trace_id 和原始异常。

**通过标准**：浏览器里**看不到任何堆栈、URL、key 片段**。

---

### S6 — 健康检查结构化 + 只读库

**步骤 1**：`/api/health` 返回真实依赖状态

```python
@app.get("/api/health")
def health(request: Request) -> dict:
    settings = request.app.state.settings
    report = {
        "status": "ok",
        "db": "down",
        "prompt_count": 0,
        "llm": "unknown",
        "web": "off",
        "image": "off",
    }
    if settings is None:
        return report

    try:
        index_version = get_prompt_index_version(
            settings.prompt_db_path, settings.sqlite_busy_timeout_ms
        )
        report["db"] = "ok"
        report["prompt_count"] = int(index_version.split(":")[0])
    except Exception:
        LOGGER.warning("health: db unavailable", exc_info=True)

    report["llm"] = "ok" if settings.deepseek_api_key else "missing"
    report["web"] = "ok" if settings.tavily_api_key else "off"
    report["image"] = "ok" if settings.image_model and settings.image_api_key else "off"
    if report["db"] != "ok" or report["llm"] != "ok":
        report["status"] = "degraded"
    return report
```

**步骤 2**：`demo_readonly_library` 生效，公网禁止写公共库

```python
@app.post("/api/prompts")
def add_prompt(payload: AddPromptRequest, request: Request):
    settings = request.app.state.settings
    if settings is not None and settings.demo_readonly_library:
        raise HTTPException(
            status_code=403,
            detail="演示环境已关闭提示词写入。",
        )
    # …原逻辑
```

**步骤 3**：前端状态点接真实数据（`app.js` 的 health 回调）

```js
const degraded = data.status !== "ok" || data.prompt_count === 0;
systemStatus.classList.toggle("is-degraded", degraded);
promptCount.textContent = data.prompt_count
  ? `${data.prompt_count} PROMPTS`
  : "INDEX EMPTY";
```

**验证**：

```powershell
curl.exe -s http://127.0.0.1:8000/api/health
# {"status":"ok","db":"ok","prompt_count":1024,"llm":"ok","web":"ok","image":"ok"}
```

**通过标准**：`prompt_count` 大于 0；断网改错 base 后 `llm` 为 `missing`、`status` 为 `degraded`，但**进程不崩、页面能开**。

---

## 3. 阶段 B：体验可演示

### S7 — 延迟测量 → 再决定优化

**先测，不要拍脑袋优化。**

**步骤 1**：`prompt_service.py` 加计时

```python
import time

started = time.perf_counter()
intent_result = self._classify_intent(user_query, conversation_context)
LOGGER.info("stage=intent elapsed=%.2fs", time.perf_counter() - started)
started = time.perf_counter()
# …每个阶段同样打点：parse / search / rerank / compose / total
```

**步骤 2**：跑 20 条真实 query，统计 P50 / P95。判定：

| P50 | 结论 |
|---|---|
| ≤ 6s | 不动，直接进 S8 |
| 6~10s | 做下面「快速路径」 |
| > 10s | 做「合并意图+解析」重构，预计 -3~5s |

**快速路径**（0.5 天，低风险）：明显是"生成新图"的请求跳过 LLM 意图分类，走正则预判。

```python
CREATE_HINT = re.compile(r"(画|生成|来一张|做个|场景|画面|海报|插画)", re.IGNORECASE)

if CREATE_HINT.search(user_query) and not MODIFY_REQUEST_PATTERN.search(user_query):
    intent_result = IntentResult(intent="create")   # 省掉 1 次 LLM 调用
else:
    intent_result = self._classify_intent(...)
```

**通过标准**：P50 ≤ 8s，且 `intent` 分类准确率没有肉眼可见下降（人工抽 20 条）。

---

### S8 — 生图异步化（防 504）

**问题**：`/api/media` 里同步调生图，30~120s，Nginx 默认 60s、Cloudflare 100s 直接 504。

**步骤 1**：新增任务存储（单进程内存态，重启即丢，demo 可接受）

```python
# webapp.py 内
import threading
from uuid import uuid4

IMAGE_JOBS: dict[str, dict] = {}
IMAGE_JOBS_LOCK = threading.Lock()


def _run_image_job(job_id: str, skill, prompt: str, ratio: str, use_cache: bool) -> None:
    try:
        result = skill.invoke(prompt, ratio, use_cache=use_cache)
        payload = {
            "status": "done",
            "image_url": f"/api/images/{result.file_name}",
            "image_id": result.image_id,
            "image_cached": result.cached,
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("image job %s failed: %s", job_id, exc)
        payload = {"status": "failed", "message": "图片生成失败，请稍后重试。"}

    with IMAGE_JOBS_LOCK:
        IMAGE_JOBS[job_id] = payload
```

**步骤 2**：接口

```python
@app.post("/api/images/jobs")
def create_image_job(payload: DirectImageRequest, request: Request):
    skill = request.app.state.image_skill
    if skill is None:
        raise HTTPException(status_code=503, detail="图片生成服务尚未配置")

    job_id = uuid4().hex
    with IMAGE_JOBS_LOCK:
        IMAGE_JOBS[job_id] = {"status": "pending"}

    threading.Thread(
        target=_run_image_job,
        args=(job_id, skill, payload.prompt, payload.aspect_ratio, True),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/images/jobs/{job_id}")
def read_image_job(job_id: str):
    with IMAGE_JOBS_LOCK:
        job = IMAGE_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job
```

**步骤 3**：前端 `app.js` 把生图从 `await postJson` 改成"提交 → 每 1.5s 轮询 → 最多 120 次"。

**通过标准**：生图耗时 60s 的场景，页面**不报错、不白屏**，进度文案正常；网关日志里**没有 504**。

---

### S9 — 缓存预热（首屏秒回的杀手锏）

**步骤**：新建 `scripts/warm_cache.py`

```python
"""预热高频 query 的 query_cache，让演示首屏秒回。"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from prompt_search_agent.config import Settings  # noqa: E402
from prompt_search_agent.services.prompt_service import build_prompt_service  # noqa: E402
from prompt_search_agent.storage import initialize_database  # noqa: E402

SAMPLE_QUERIES = [
    "雪夜里穿汉服的少女，电影感，低机位，冷色调",
    "一只白色短腿胖小猫在雪山上滑雪，电影感真实摄影，超广角，8k，--ar 2:3",
    "赛博朋克雨夜街头，孤独女杀手，霓虹反光，电影写实，低机位",
    "火星上的紫色机械鲸鱼，赛博朋克，电影感，超广角",
    "秋日午后咖啡馆窗边，胶片质感，浅景深，侧逆光",
    "敦煌壁画风格的飞天，工笔重彩，对称构图",
    "极简产品海报，白色背景，柔光，居中构图",
    "蒸汽朋克飞艇飞越伦敦上空，黄昏，云雾，广角",
    "水下失重感的舞者，蓝绿色调，束状光",
    "老式绿皮火车窗边的旅人，暖黄色调，胶片颗粒",
]


def main() -> int:
    settings = Settings()
    initialize_database(settings.prompt_db_path, settings.sqlite_busy_timeout_ms)
    service = build_prompt_service(settings)

    warmed_threads: list[str] = []
    for query in SAMPLE_QUERIES:
        # 全新会话 → 上下文为空，与真实首轮 cache key 一致
        result = service.generate(query)
        warmed_threads.append(result.thread_id)
        print(f"{'CACHE' if result.cached else 'MISS '} {query[:28]}")

    # 预热产生的临时会话清掉，别留在演示库里
    connection = sqlite3.connect(settings.prompt_db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executemany(
        "DELETE FROM conversations WHERE thread_id = ?",
        [(thread_id,) for thread_id in warmed_threads],
    )
    connection.commit()
    connection.close()

    print(f"完成 {len(SAMPLE_QUERIES)} 条，临时会话已清理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**验证**：连跑两次，第二次全部输出 `CACHE`。

**通过标准**：首页 3 个示例 chip 点下去**1 秒内**出结果。

---

## 4. 阶段 C：容器与部署

### S10 — Dockerfile

`Dockerfile`：

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

COPY --from=build /app /app
COPY data/seed /app/data/seed

RUN mkdir -p /data/indexes /data/generated/images

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"

CMD ["uvicorn", "prompt_search_agent.webapp:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

> ⚠️ `--workers 1` 是**刻意**的：限流器和生图任务都是进程内内存态，多 worker 会失效，SQLite 也更稳。

`.dockerignore`：

```
.venv
.git
.idea
.pytest_cache
.ruff_cache
**/__pycache__
data/indexes
data/generated
data/eval
data/*.log
tests
```

### S11 — compose + Caddy

`docker-compose.yml`：

```yaml
services:
  app:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      DATA_DIR: /data
      SEED_FILE: /app/data/seed/prompts.jsonl.gz
    volumes:
      - atelier-data:/data
    expose:
      - "8000"

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    depends_on:
      - app
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config

volumes:
  atelier-data:
  caddy-data:
  caddy-config:
```

`deploy/Caddyfile`：

```caddyfile
atelier.example.com {
    encode zstd gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

    reverse_proxy app:8000 {
        transport http {
            response_header_timeout 180s
        }
    }
}
```

> 没有域名就写 `:80`，用 `http://<IP>/` 访问 —— 但**口令必须设**。

### S12 — 服务器执行

```bash
sudo apt update && sudo apt -y install git docker.io docker-compose-v2
sudo usermod -aG docker "$USER"   # 重新登录生效

sudo mkdir -p /opt/prompt-atelier && sudo chown "$USER" /opt/prompt-atelier
git clone <repo-url> /opt/prompt-atelier
cd /opt/prompt-atelier

cp .env.example .env
vim .env    # 填 DEEPSEEK_API_KEY / DEMO_ACCESS_CODE / THREAD_SECRET
            # THREAD_SECRET 用: openssl rand -hex 32

docker compose up -d --build
docker compose logs -f app        # 看到 seed 导入日志即成功
```

DNS：`A` 记录指向服务器 IP，放行 80/443。

### S13 — 冒烟脚本

`scripts/smoke.sh`：

```bash
#!/usr/bin/env bash
set -uo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:-}"

check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf 'PASS  %-34s %s\n' "$name" "$actual"
  else
    printf 'FAIL  %-34s want=%s got=%s\n' "$name" "$expected" "$actual"
  fi
}

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

check "健康检查"         "200" "$(code "$BASE/api/health")"
check "首页"             "200" "$(code "$BASE/")"
check "未带口令被拒"     "401" "$(code -X POST "$BASE/api/prompt" \
  -H 'Content-Type: application/json' -d '{"message":"雪夜白猫"}')"
check "带口令可生成"     "200" "$(code -X POST "$BASE/api/prompt" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"雪夜里穿汉服的少女，电影感"}')"
check "历史越权被拒"     "403" "$(code "$BASE/api/history/not-mine")"
check "写库被禁用"       "403" "$(code -X POST "$BASE/api/prompts" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"prompt_text":"should fail"}')"

echo
echo "health: $(curl -s "$BASE/api/health")"
```

```bash
chmod +x scripts/smoke.sh
BASE=https://atelier.example.com TOKEN=<CODE> ./scripts/smoke.sh
```

**通过标准**：6 项全 PASS，`prompt_count` 大于 0。

---

## 5. 阶段 D：上线验收（18 项，30 分钟）

| # | 检查项 | 方法 | 通过标准 |
|---:|---|---|---|
| 1 | 新机冷启动 | 空卷 `docker compose up -d --build` | 3 分钟内 healthy |
| 2 | seed 自动导入 | 看日志 + `/api/health` | `prompt_count` > 0 |
| 3 | 幂等 | 重启容器 | 不重复导入 |
| 4 | 首页 | 浏览器打开 | 无控制台报错 |
| 5 | 无口令 | curl 不带 header | 401 |
| 6 | 限流 | 连打 30 次 | 出现 429 |
| 7 | 日配额 | 临时把 cap 改成 3 | 第 4 次 503 |
| 8 | 越权 | 用他人的 thread_id | 403 |
| 9 | 写库禁用 | POST /api/prompts | 403 |
| 10 | 提示词生成 | 示例 chip | 出结果，`LIVE` 或 `CACHED` |
| 11 | 缓存命中 | 同一句再发一次 | `CACHED`，1s 内 |
| 12 | 会话恢复 | 刷新页面 | 历史仍在 |
| 13 | 生图 | 点"直接生图" | 90s 内出图，无 504 |
| 14 | 错误文案 | 改错 DeepSeek base | 友好中文，无堆栈 |
| 15 | trace | 查日志 | 每请求有 trace_id |
| 16 | HTTPS | `https://域名` | 证书有效，http 自动跳转 |
| 17 | 移动端 | 390px 视口 | 无横向滚动 |
| 18 | 成本 | 跑 100 次真实对话 | 账单可接受，记录基线 |

---

## 6. 运维 SOP

### 6.1 每日巡检（2 分钟）

```bash
curl -s https://<域名>/api/health          # status 必须 ok
docker compose ps                          # 两个容器 Up
docker compose logs --since 24h app | grep -c " ERROR "   # 应为 0
df -h /var/lib/docker                      # 使用率 < 80%
```

配一个外部监控（UptimeRobot / 阿里云拨测）探 `/api/health`，5 分钟一次。

### 6.2 每周备份

```bash
docker compose exec -T app python - <<'PY'
import datetime
import pathlib
import sqlite3

pathlib.Path("/data/backup").mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
target = f"/data/backup/prompt_index-{stamp}.sqlite3"

conn = sqlite3.connect("/data/indexes/prompt_index.sqlite3")
conn.execute(f"VACUUM INTO '{target}'")
conn.close()
print("backup ->", target)
PY

docker cp "$(docker compose ps -q app):/data/backup" ./backups/
```

保留最近 7 份。**恢复**：停容器 → 覆盖 `/data/indexes/prompt_index.sqlite3` → 起容器。

### 6.3 缓存清理（防无限增长）

`query_cache` 没有 TTL，会一直涨。加 crontab：

```bash
0 4 * * * cd /opt/prompt-atelier && docker compose exec -T app python -c "import sqlite3;c=sqlite3.connect('/data/indexes/prompt_index.sqlite3');c.execute(\"DELETE FROM query_cache WHERE created_at < datetime('now','-30 day')\");c.commit();c.execute('VACUUM');c.close()"
```

### 6.4 故障处置表

| 现象 | 最可能原因 | 处置 |
|---|---|---|
| 全员 401 | 口令改了 / 前端没带 token | 清 `localStorage` 里的 `prompt-atelier-token` 重新输入 |
| 全员 429 | 被恶意刷 | 临时下调 `RATE_LIMIT_PER_IP_PER_HOUR`，Caddy 层加 IP 封禁 |
| 503 quota_exhausted | 日额度用完 | 提 `DAILY_REQUEST_CAP` 或等次日；**先看账单** |
| `prompt_count = 0` | seed 没挂载 / 卷被清 | `docker compose exec app ls -l /app/data/seed` |
| 大量 500 | DeepSeek 余额不足 / 上游故障 | 看 trace_id 日志里的原始异常，充值或降级为纯缓存模式 |
| 504 | 生图超时 | 确认已上 S8 异步；Caddy `response_header_timeout 180s` |
| 磁盘满 | 图片堆积 | `find /data/generated/images -mtime +7 -delete` |
| 启动即退出 | 配置错 / 目录不可写 | `docker compose logs app`，检查 `DATA_DIR` 权限 |

### 6.5 回滚

```bash
cd /opt/prompt-atelier
git fetch --tags && git checkout pre-launch
docker compose up -d --build
# 数据卷 atelier-data 不动，历史会话和缓存保留
```

### 6.6 密钥泄露应急

1. 立刻在 DeepSeek / Tavily / 图片中转后台**吊销**该 key；
2. 服务器 `vim .env` 换新 key；
3. `docker compose up -d --force-recreate`；
4. 查账单确认损失区间。

---

## 7. 排期

单人为例（约 6.5 人日）：

| 日期 | 步骤 | 产出 |
|---|---|---|
| D1 上午 | S0、S1、S2 | 配置解耦 + seed 发布 |
| D1 下午 | S3、S4 | 口令限流 + 越权修复 |
| D2 上午 | S5、S6 | 错误收敛 + 健康检查 |
| D2 下午 | S10、S11、S12 | 容器化 + 首次部署 |
| D3 上午 | S13 + 验收 1~9 项 | 安全验收通过，**可对外试运行** |
| D3 下午 | S7、S8 | 延迟优化 + 生图异步 |
| D4 上午 | S9 + 验收 10~18 项 | 体验验收，正式上线 |
| D5 | 巡检、备份、压测记录 | 运维基线 |

两人并行可压到 3 天（A 阶段 / C 阶段两人分头）。

---

## 8. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| 备案周期 | 无法用域名 | 先用海外节点或纯 IP，备案并行办 |
| 限流器是内存态 | 多 worker 失效 | 锁死 `--workers 1`；要扩容就换 Redis |
| 生图任务内存态 | 重启丢任务 | demo 可接受；要持久化就落 sqlite 表 |
| seed 数据版权 | 法律风险 | 只用自有/已授权数据，页面标注"演示数据集" |
| 生成内容合规 | 国内监管要求 | 接入内容安全审核，或限制为"仅提示词不生图" |
| 上游涨价/限流 | 服务不可用 | 缓存命中率就是生命线，`query_cache` 命中率 < 30% 要告警 |
| 单点故障 | 全站不可用 | demo 阶段接受；有 SLA 要求再上多机 + 托管数据库 |

---

## 9. 交付物检查（上线当天）

- [ ] `docs/deploy-sop.md` 已更新为实际操作记录
- [ ] `data/seed/prompts.jsonl.gz` 已提交
- [ ] `.env.example` 含全部新增变量，无真实密钥
- [ ] `scripts/smoke.sh` 6 项全 PASS
- [ ] 验收 18 项全绿并截图存档
- [ ] 口令已通过安全渠道发给演示对象（**不要发群里**）
- [ ] 账单基线已记录
- [ ] `pre-launch` tag 存在，回滚命令已验证

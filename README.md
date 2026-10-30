# Prompt Atelier

一个面向 AIGC 创作的本地提示词检索、改写与生图工作台。

项目将自然语言需求转换为结构化检索条件，通过 SQLite FTS5 检索本地提示词库，
再使用 DeepSeek 完成重排和提示词组装。当本地没有匹配结果时，可使用 Tavily
搜索公开资料；联网仍无结果时返回“未检索到”，并允许用户手动添加提示词。

## 功能

- 自然语言生成 AIGC 提示词
- SQLite FTS5 + jieba 中文提示词检索
- 多查询变体召回与 DeepSeek 语义重排
- Tavily 联网搜索与网页内容抓取
- 提示词改写、合规泛化与直接生图
- OpenAI-compatible 图片生成中转
- 图片元数据持久化、精确缓存和过期清理
- 任务级多轮对话历史
- 较早对话摘要 + 最近消息的滚动上下文压缩
- FastAPI 前后端一体的响应式 Web 工作台
- 手动添加提示词并即时更新 FTS 索引
- 访问口令鉴权、每 IP 限流与全局日配额
- 会话签名，防止他人凭 thread_id 读取历史对话
- 结构化健康检查、trace_id 全链路日志与友好错误文案
- 提示词库 seed 快照，新环境启动自动还原
- 生图异步任务，避免长请求被网关切断
- SSE 流式生成，阶段进度 + token 逐字输出
- 联网按需触发，本地漏召回不再阻塞在 20s 的网页抓取上
- 静态资源内容哈希指纹，可长缓存且发版即失效
- 版本化发布与一键回滚
- 上游熔断、单轮超时预算与请求体上限
- 磁盘巡检（图片/缓存/会话 TTL）与磁盘水位保护
- 图片生成三层配额：小时总量 / 在飞并发 / 缓存退还
- Prometheus 指标端点（`/metrics`）与 schema 版本化迁移
- Docker Compose + Caddy 一键部署

## 技术栈

- Python 3.12
- FastAPI / Uvicorn
- LangChain / LangGraph
- DeepSeek
- Tavily
- OpenAI-compatible Image API
- SQLite / FTS5 / WAL
- jieba 中文分词
- Pydantic / pydantic-settings
- pytest / Ruff / Pyright

## 核心流程

### 提示词生成

```text
用户自然语言
  -> 意图分类
  -> 结构化需求解析
  -> SQLite FTS5 多查询召回
  -> DeepSeek 语义重排
  -> 提示词组装
  -> 最终提示词
```

本地无匹配时：

```text
本地检索为空
  -> Tavily 搜索
  -> 网页抓取
  -> 基于网络资料组装
  -> 仍无结果则提示手动添加
```

### 提示词修改

涉及润色、缩短、翻译、去版权风险或替换元素的请求会直接进入独立改写链，
不会触发本地检索或联网搜索。

### 图片生成

```text
最终提示词
  -> 图片缓存查询
  -> OpenAI-compatible 图片接口
  -> 下载或解码图片
  -> 保存文件与元数据
  -> 前端预览
```

相同提示词、模型和尺寸默认复用缓存；显式“重新生成”会绕过缓存并替换旧文件。

## 对话记忆

- 数据库保存完整对话历史，前端刷新后可以恢复。
- 发送给 LLM 的上下文只包含：
  - 较早对话摘要
  - 当前结构化约束
  - 上一版提示词
  - 最近 8 条消息
- 超过 12 条消息后，早期消息压缩为不超过 800 字的摘要。
- 历史规则已注入意图分类、解析、重排、组装、改写、聊天和摘要提示词。

## 目录结构

```text
src/prompt_search_agent/
  chains/        LangChain 提示词与结构化输出链
  graph/         LangGraph 工作流
  images/        图片 Provider 与结果模型
  ingest/        Excel 数据导入与清洗
  search/        SQLite FTS5 检索与中文分词
  services/      业务编排、缓存与对话记忆
  skills/        聊天、提示词生成、图片生成 Skill
  storage/       SQLite schema、仓库与缓存
  tools/         Tavily 搜索和网页抓取
  web/           前端页面与静态资源
tests/           单元测试与集成测试
```

## 快速开始

```powershell
uv sync
Copy-Item .env.example .env
```

配置 `.env`：

```env
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=
DEEPSEEK_API_BASE=https://api.deepseek.com

TAVILY_API_KEY=

IMAGE_API_KEY=
IMAGE_API_BASE=https://your-relay.example.com/v1
IMAGE_MODEL=
IMAGE_RETENTION_DAYS=7
```

本机开发只需上面这些。要暴露到公网，必须再配置：

```env
# 访问口令：不配置则接口完全无鉴权，仅限本机
DEMO_ACCESS_CODE=换成你的口令
# 会话签名密钥，生成方式：openssl rand -hex 32
THREAD_SECRET=换成随机串
# 每 IP 每小时上限 / 全局每日上限
RATE_LIMIT_PER_IP_PER_HOUR=20
DAILY_REQUEST_CAP=500
# 公网务必开启，否则任何人都能往提示词库里写内容
DEMO_READONLY_LIBRARY=true
```

启动：

```powershell
uv run prompt-search-web
```

访问：

```text
http://127.0.0.1:8000
```

验证图片中转：

```powershell
uv run python scripts/probe_image_api.py
```

## 测试

```powershell
uv run pytest -q
uv run ruff check .
uv run pyright
node --check src/prompt_search_agent/web/app.js
```

当前测试状态：

```text
77 passed
Ruff: passed
Pyright: 0 errors
JavaScript syntax: passed
```

## 公网安全

| 机制 | 行为 |
|---|---|
| 访问口令 | 业务接口需 `Authorization: Bearer <DEMO_ACCESS_CODE>`，缺失或错误返回 401 |
| IP 限流 | 每 IP 每小时 `RATE_LIMIT_PER_IP_PER_HOUR` 次，超出返回 429 |
| 日配额 | 全局每天 `DAILY_REQUEST_CAP` 次，超出返回 503 |
| 会话签名 | thread_id 由 `THREAD_SECRET` 做 HMAC 签名，读写历史必须带 `x-thread-token`，否则 403 |
| 只读库 | `DEMO_READONLY_LIBRARY=true` 时关闭 `/api/prompts` 写入，返回 403 |
| 错误收敛 | 对外只返回 `{code, message, trace_id}`，异常原文只进服务端日志 |
| 降级启动 | 密钥缺失或数据库初始化失败时进程照常启动，接口返回 503 并在 `/api/health` 报 `degraded` |

`/`、`/api/health`、`/static/*` 不受口令与限流影响，便于探活与加载页面。

> ⚠️ 限流与生图任务都是**进程内内存态**，因此部署必须保持单 worker（`--workers 1`）。

## 故障处理

| 故障 | 系统行为 |
|---|---|
| 上游连续失败 | 连续 `UPSTREAM_FAILURE_THRESHOLD` 次后熔断，冷却期内直接 503，不再占用并发槽位 |
| 单轮超时 | `GENERATION_DEADLINE_SECONDS` 预算，到点后不再发起新的上游调用 |
| Tavily 搜索/抓取失败 | 退回本地检索结果继续生成，不整单失败 |
| 会话库写入失败 | 已生成的提示词照常返回，只丢历史记录 |
| 请求体过大 | 超出 `MAX_REQUEST_BODY_BYTES` 返回 413 |
| 图片地址非公网 | 拒绝下载（含 `file://`、内网 IP、重定向到内网） |
| 生图 provider 失败 | 任务标记 `failed`，前端轮询拿到明确提示 |

## 运行时架构

| 能力 | 实现 | 说明 |
|---|---|---|
| 异步执行 | `to_thread` + `CapacityLimiter` | 生成任务在线程里跑，并发上限 `MAX_CONCURRENT_GENERATIONS`（默认 8），超出排队而非打满线程池 |
| SSE 流式 | `POST /api/prompt/stream` | 事件序列 `open → stage(intent/retrieval) → token* → result`，失败推 `error`，心跳 5s |
| 静态指纹 | `webassets.AssetManifest` | 启动时按内容哈希改写 `index.html`；命中指纹回 `immutable`，未命中回 7 天 |
| 发布回滚 | `deploy/release.sh` / `deploy/rollback.sh` | releases 目录 + `current`/`previous` 符号链接，起不来自动退回 |

## 评测

评测集在 `data/eval/cases.jsonl`，每个用例自带期望：必含同义词组、禁用词、画幅、期望路由。
**规则断言是主信号，LLM judge 只是辅助**——模型自评普遍给 85~95 分，区分不出好坏。

```bash
python scripts/eval/check_cases.py                      # L1：格式/覆盖矩阵，秒级，进 CI
python scripts/eval/run_eval.py                         # L2：全量真跑，出报告
python scripts/eval/run_eval.py --update-baseline       # 更新基线
python scripts/eval/run_eval.py --bucket compose --limit 3   # 局部快跑
```

L2 会绕过缓存（命中缓存一律报 `compose`，会把真实路由抹平），并与 `data/eval/baseline.json` 对比。

| 指标 | 门槛 |
|---|---|
| `include_recall` | ≥ 0.95 |
| `exclude_violations` | == 0 |
| `aspect_pass_rate` | == 1.0 |
| `route_accuracy` | ≥ 0.90 |

当前基线（25 条）：`include_recall 1.0` / `route_accuracy 1.0` / `p50 6.0s` / `p95 9.3s`。

### 接口

| 接口 | 用途 |
|---|---|
| `POST /api/prompt` | 一次性生成，给脚本和第三方调用 |
| `POST /api/prompt/stream` | SSE 流式生成，前端使用 |
| `POST /api/images/jobs` → `GET /api/images/jobs/{id}` | 异步生图 |
| `DELETE /api/history/{thread_id}` | 删除会话全部历史（需 `x-thread-token`） |
| `GET /api/version` | 当前版本、commit 与 `schema_version`，发布/回滚后核对 |
| `GET /metrics` | Prometheus 文本格式指标 |

### 数据保留

| 数据 | 保留期 | 配置项 |
|---|---|---|
| 生成图片 | 7 天 | `IMAGE_RETENTION_DAYS` |
| 查询缓存 | 30 天 | `CACHE_RETENTION_DAYS` |
| 会话历史 | 90 天（按最后更新时间） | `CONVERSATION_RETENTION_DAYS` |
| 用户主动删除 | 立即 | `DELETE /api/history/{thread_id}` |

清理由常驻巡检任务每小时执行一次，删除后通过 `PRAGMA incremental_vacuum` 把空间还给文件系统，避免库文件只涨不缩。

### 关键指标

| 指标 | 用途 |
|---|---|
| `prompt_atelier_generation_waiting` | **唯一的雪崩前兆**：持续 > 0 说明上游变慢或并发已满 |
| `prompt_atelier_generation_seconds` | 单轮生成耗时分布 |
| `prompt_atelier_upstream_failures_total` | 上游失败次数，配合熔断判断 |
| `prompt_atelier_requests_total{path,status}` | 按路由模板统计，不会因 uuid 爆炸 |
| `prompt_atelier_disk_free_bytes` | 磁盘余量 |
| `prompt_atelier_image_jobs_total{status}` | 生图任务成败 |

### 发布与回滚

两种方式二选一。

**A. Docker Compose（推荐）**

```bash
cp .env.example .env      # 填 DEEPSEEK_API_KEY / DEMO_ACCESS_CODE / THREAD_SECRET
vim deploy/Caddyfile      # 把 atelier.example.com 换成你的域名
docker compose up -d --build
docker compose logs -f app
```

数据在 `atelier-data` 卷里，`docker compose down` 不会丢。

**B. systemd + 版本目录**

目录约定见 `deploy/release.sh` 头部注释。首次安装：

```bash
sudo cp deploy/prompt-atelier.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now prompt-atelier

deploy/release.sh      # 拉取、装依赖、切换、重启；起不来自动回滚
deploy/rollback.sh     # 退回上一版本，可来回切换
curl -s localhost:8000/api/version   # 核对当前 commit
```

上线冒烟：

```bash
BASE=https://你的域名 TOKEN=你的口令 ./scripts/smoke.sh
```

### 流水线

`git push` → 质量门（ruff / pyright / pytest / 评测集校验 / 前端语法 / compose 配置）
→ 构建并推送镜像 → 部署到服务器 → 线上冒烟 → **失败自动回滚**。

```bash
bash scripts/check.sh      # 本地跑一遍与 CI 相同的质量门
```

评测有独立工作流（手动触发或每周一），因为它要打真实模型、几分钟且花钱。
Secrets 配置与回滚细节见 [docs/pipeline.md](docs/pipeline.md)。

## 数据与密钥

- `.env` 已被 `.gitignore` 忽略。
- 提示词索引、生成图片和运行日志不进入 Git。
- 网络资料在提示词中被标记为不可信数据，不允许执行网页中的指令。

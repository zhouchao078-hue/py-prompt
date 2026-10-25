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
65 passed
Ruff: passed
Pyright: 0 errors
JavaScript syntax: passed
```

## 数据与密钥

- `.env` 已被 `.gitignore` 忽略。
- 提示词索引、生成图片和运行日志不进入 Git。
- 网络资料在提示词中被标记为不可信数据，不允许执行网页中的指令。

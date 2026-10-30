# 流水线

从一次 `git push` 到线上可用，全流程自动化；部署后冒烟失败会**自动回滚**。

```
push / PR
   │
   ▼
┌─────────────┐   ┌─────────────┐   ┌──────────────────────┐
│ 质量门       │──▶│ 构建镜像     │──▶│ 部署 → 冒烟 → 回滚    │
│ ruff        │   │ buildx      │   │ ssh + compose         │
│ pyright     │   │ 推 ghcr     │   │ /api/health 轮询       │
│ pytest      │   │ (仅 main)   │   │ smoke.sh 8 项         │
│ 评测集校验   │   └─────────────┘   └──────────────────────┘
│ 前端语法     │
│ compose     │
└─────────────┘
```

## 工作流

| 文件 | 触发 | 做什么 |
|---|---|---|
| `.github/workflows/ci.yml` | PR / push main / 手动 | 质量门 → 构建镜像 →（main）部署并冒烟 |
| `.github/workflows/eval.yml` | 手动 / 每周一 03:00 | 全量评测，结果作为 artifact 上传 |

**为什么评测单独一个工作流**：一轮 25 条要打 100+ 次真实模型，几分钟且花钱。
放在每个 PR 上既慢又贵，所以改成定时 + 手动。

## 需要的 Secrets

在 `Settings → Secrets and variables → Actions` 里配置。**一个都不配也能跑**——
部署 job 会自动跳过，只做质量门和镜像构建。

| Secret | 用途 | 示例 |
|---|---|---|
| `SSH_HOST` | 服务器地址 | `1.2.3.4` |
| `SSH_USER` | 部署账号 | `deploy` |
| `SSH_KEY` | 私钥全文（含 BEGIN/END 行） | `-----BEGIN OPENSSH...` |
| `APP_DIR` | 服务器上的 compose 目录 | `/opt/prompt-atelier` |
| `PUBLIC_URL` | 冒烟用的线上地址 | `https://atelier.example.com` |
| `DEMO_ACCESS_CODE` | 冒烟用的访问口令 | 与服务器 `.env` 一致 |
| `DEEPSEEK_API_KEY` | 仅 eval 工作流 | — |
| `TAVILY_API_KEY` | 仅 eval 工作流（可选） | — |

`GITHUB_TOKEN` 由 Actions 自动提供，用于推镜像到 `ghcr.io`。

## 首次接入

1. **服务器准备**

   ```bash
   sudo mkdir -p /opt/prompt-atelier && sudo chown "$USER" /opt/prompt-atelier
   cd /opt/prompt-atelier
   # 只需要这三个文件：compose、Caddyfile、.env
   # 仓库可以 clone 到这里，也可以用 scp 传
   cp .env.example .env && vim .env     # 填 key / 口令 / THREAD_SECRET
   ```

2. **镜像仓库可见性**：`ghcr.io` 的包默认私有，服务器需要 `docker login ghcr.io`
   （用有 `read:packages` 权限的 PAT）。公开仓库可把包设为 public 免登录。

3. **推一次 main**，Actions 跑完即完成首次部署。

4. **确认版本**：`curl https://你的域名/api/version` 应返回本次 commit 的 sha。

## 回滚

部署失败时流水线会自动回滚，但也可以手动：

```bash
ssh deploy@服务器 "APP_DIR=/opt/prompt-atelier bash /tmp/remote-deploy.sh --rollback"
```

服务器上只靠两个状态文件记录历史，不依赖 git：

```
/opt/prompt-atelier/.current-image    当前在跑的镜像
/opt/prompt-atelier/.previous-image   上一个健康过的镜像
```

`remote-deploy.sh` 的判断顺序：拉镜像 → 起容器 → 轮询 `docker inspect` 的
health 状态（最长 120s）→ 不健康就用上一版重新起 → 仍不健康则退出码 1，
流水线标红并保留现场。

## 本地复现

提交前跑一遍，和 CI 的 quality job 完全一致：

```bash
bash scripts/check.sh
```

单跑某一项：

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
uv run python scripts/eval/check_cases.py
node --check src/prompt_search_agent/web/app.js
docker compose config >/dev/null
```

## 设计取舍

- **部署用镜像，不用 `git pull` + `uv sync`**：同一个镜像在测试和线上跑，可复现；
  服务器不需要网络装依赖。`deploy/release.sh`（systemd + 版本目录）保留作为
  非容器环境的备选，两条路径不要同时用。
- **`docker compose` 同时支持 `build` 和 `image`**：本地 `up --build` 用源码构建，
  线上只 consume `APP_IMAGE` 指向的成品镜像。
- **冒烟在 CI 侧执行**，不在服务器上：断言的是"公网可达 + 口令生效"，
  这是用户真正会遇到的路径。
- **部署 job 有 `guard` 步骤**：没配 SSH 密钥时明确输出"跳过部署"，
  而不是让 workflow 莫名其妙失败。

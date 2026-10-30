# 基础镜像只用 Docker Hub：国内服务器拉不到 ghcr.io 时会直接卡在第一步。
# 需要镜像源时构建加 --build-arg UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
FROM python:3.12-slim AS build

ARG PIP_INDEX_URL
ARG UV_INDEX_URL

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # 空值会让 uv 报错，所以给个默认官方源
    UV_INDEX_URL=${UV_INDEX_URL:-https://pypi.org/simple} \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url ${PIP_INDEX_URL}} uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    DATA_DIR=/data \
    # 默认指向镜像里自带的 seed，裸 docker run 也能还原提示词库
    SEED_FILE=/app/data/seed/prompts.jsonl.gz

COPY --from=build /app /app
COPY data/seed /app/data/seed
# 分词用户词典必须一起打包，否则检索链路会退化甚至起不来
COPY data/userdict.txt /app/data/userdict.txt

RUN mkdir -p /data/indexes /data/generated/images

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"

# 必须单 worker：限流器、生图任务、配额都在进程内存里。
CMD ["uvicorn", "prompt_search_agent.webapp:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

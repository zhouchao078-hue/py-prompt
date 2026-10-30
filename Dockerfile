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
    PYTHONUTF8=1 \
    DATA_DIR=/data

COPY --from=build /app /app
COPY data/seed /app/data/seed

RUN mkdir -p /data/indexes /data/generated/images

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"

# 必须单 worker：限流器、生图任务、配额都在进程内存里。
CMD ["uvicorn", "prompt_search_agent.webapp:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

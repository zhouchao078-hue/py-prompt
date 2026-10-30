"""压测专用应用：把上游换成固定延迟的假服务。

这样并发行为可控、可重复，也不消耗真实 token：
    uvicorn loadtest_app:app --app-dir scripts --port 8030

环境变量：
    LOADTEST_DELAY     每次生成的模拟耗时（秒）
    LOADTEST_CAPACITY  并发槽位
    LOADTEST_QUEUE     排队上限
    RATE_LIMIT_PER_IP_PER_HOUR / DAILY_REQUEST_CAP  限流配额
"""

import os
import time
from uuid import uuid4

from prompt_search_agent.config import Settings
from prompt_search_agent.services.prompt_service import PromptServiceResult
from prompt_search_agent.storage import initialize_database
from prompt_search_agent.webapp import create_app

DELAY = float(os.getenv("LOADTEST_DELAY", "0.3"))


class SlowFakeService:
    """固定延迟的假服务，用来模拟真实 LLM 的阻塞时间。"""

    def generate(
        self,
        user_query: str,
        thread_id: str | None = None,
        on_stage=None,
        on_token=None,
    ) -> PromptServiceResult:
        if on_stage is not None:
            on_stage("intent")

        time.sleep(DELAY)

        if on_stage is not None:
            on_stage("retrieval")

        return PromptServiceResult(
            final_prompt=f"load test for {user_query}",
            cached=False,
            thread_id=thread_id or str(uuid4()),
        )


settings = Settings(
    max_concurrent_generations=int(os.getenv("LOADTEST_CAPACITY", "8")),
    max_generation_queue=int(os.getenv("LOADTEST_QUEUE", "16")),
    rate_limit_per_ip_per_hour=int(
        os.getenv("RATE_LIMIT_PER_IP_PER_HOUR", "10000")
    ),
    daily_request_cap=int(os.getenv("DAILY_REQUEST_CAP", "100000")),
)

app = create_app(lambda: SlowFakeService(), app_settings=settings)

# 注入假服务不会走 _bootstrap_service，这里手动建库，
# 否则 /api/health 会一直报 db down，压测数据看着像故障。
initialize_database(settings.prompt_db_path, settings.sqlite_busy_timeout_ms)

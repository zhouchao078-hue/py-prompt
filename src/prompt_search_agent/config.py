"""Application configuration.

所有数据路径都从 ``DATA_DIR`` 派生，避免安装成 wheel 后 ``PROJECT_ROOT``
指向 site-packages 的父目录、把数据库写进虚拟环境里。
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_THREAD_SECRET = "dev-only-change-me"


def _default_data_dir() -> Path:
    """DATA_DIR 必须是真实环境变量，pydantic-settings 读 .env 不会污染 os.environ。"""
    raw = os.getenv("DATA_DIR", "").strip()
    return Path(raw) if raw else PROJECT_ROOT / "data"


DATA_DIR = _default_data_dir()


class Settings(BaseSettings):
    # 密钥允许缺省：由 validate_runtime() 给出中文诊断，而不是启动即崩。
    deepseek_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_api_base: str = "https://api.deepseek.com"

    # 数据路径统一从 DATA_DIR 派生，容器里挂一个卷即可。
    data_dir: Path = DATA_DIR
    prompt_db_path: Path = DATA_DIR / "indexes" / "prompt_index.sqlite3"
    image_output_dir: Path = DATA_DIR / "generated" / "images"
    seed_file: Path = DATA_DIR / "seed" / "prompts.jsonl.gz"
    agent_checkpoint_path: Path = DATA_DIR / "agent" / "checkpoints.sqlite3"
    agent_max_steps: int = 8

    # 公网运行约束。
    public_mode: bool = False
    demo_access_code: SecretStr | None = None
    thread_secret: SecretStr = SecretStr(DEFAULT_THREAD_SECRET)
    rate_limit_per_ip_per_hour: int = 20
    daily_request_cap: int = 500
    demo_readonly_library: bool = False
    # 同时进行的生成任务上限，超出的请求排队而不是把线程池打满。
    max_concurrent_generations: int = 8
    # 单轮生成的总预算；超过后不再发起新的上游调用。
    generation_deadline_seconds: float = 45.0
    # 连续失败多少次后熔断，以及冷却时长。
    upstream_failure_threshold: int = 5
    upstream_cooldown_seconds: float = 30.0
    # 请求体上限，4000 字的消息用 256KB 绰绰有余。
    max_request_body_bytes: int = 2_500_000
    # 生成排队上限，超过直接 503 而不是无限等待。
    max_generation_queue: int = 16

    # 磁盘巡检与数据保留策略。对话只留 7 天，演示场景不需要更久。
    janitor_interval_seconds: float = 3600.0
    cache_retention_days: int = 30
    conversation_retention_days: int = 7
    min_free_disk_gb: float = 2.0

    # 会话 cookie：身份存在服务端，浏览器只拿一个 HttpOnly cookie。
    session_cookie_name: str = "atelier_session"
    session_cookie_days: int = 180

    # 数据库快照：每小时一份，保留最近 N 份（24 份 ≈ 一天）
    backup_keep: int = 24

    # 图片生成配额：小时总量按 IP 计，同时在飞的张数按进程计。
    image_per_hour: int = 6
    image_max_in_flight: int = 4
    image_max_workers: int = 4

    # 成本记账单价（USD）。默认 0 = 只记用量不折算金额。
    llm_input_price_per_million: float = 0.0
    llm_output_price_per_million: float = 0.0
    image_price_per_image: float = 0.0

    sqlite_busy_timeout_ms: int = 5000
    conversation_recent_messages: int = 8
    conversation_compress_after_messages: int = 12
    conversation_summary_max_chars: int = 800
    tavily_max_results: int = 5
    tavily_fetch_max_urls: int = 3
    tavily_max_chars: int = 2500
    # 单次 Tavily 调用的硬超时；不设的话一次抓取能跑十几秒。
    tavily_timeout_seconds: float = 12.0
    tavily_search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = (
        "basic"
    )
    # on_demand：只有用户明确要查资料才联网（默认，避免 20s 慢路径）
    # always / never：强制开关
    web_research_mode: str = "on_demand"
    web_research_budget_seconds: float = 8.0
    image_api_key: SecretStr | None = None
    image_api_base: str = "https://api.openai.com/v1"
    image_model: str | None = None
    image_response_format: str | None = None
    # 让中转直接返回 webp：体积约为 PNG 的 1/5，但需要上游支持 output_format。
    image_output_format: str | None = None
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

    @model_validator(mode="after")
    def _apply_data_dir(self) -> "Settings":
        """DATA_DIR 一旦显式设置就是权威路径。

        否则 .env 里遗留的 PROMPT_DB_PATH（例如 Windows 绝对路径）会压过 DATA_DIR，
        在容器里直接指向一个不存在的盘符，启动即失败。
        """
        explicit = os.getenv("DATA_DIR", "").strip()

        if not explicit:
            return self

        self.data_dir = Path(explicit)
        self.prompt_db_path = (
            self.data_dir / "indexes" / "prompt_index.sqlite3"
        )
        self.image_output_dir = self.data_dir / "generated" / "images"
        self.agent_checkpoint_path = (
            self.data_dir / "agent" / "checkpoints.sqlite3"
        )

        if not os.getenv("SEED_FILE", "").strip():
            self.seed_file = self.data_dir / "seed" / "prompts.jsonl.gz"

        return self

    @property
    def is_public_mode(self) -> bool:
        """配置了访问口令即视为公网部署。"""
        return self.public_mode or _filled(self.demo_access_code)

    @property
    def thread_secret_value(self) -> str:
        return self.thread_secret.get_secret_value()

    def validate_runtime(self) -> list[str]:
        """返回非致命配置问题列表，启动时打日志，不阻断进程。"""
        problems: list[str] = []

        if not _filled(self.deepseek_api_key):
            problems.append("DEEPSEEK_API_KEY 未配置 → 提示词生成不可用")
        if self.public_mode and not _filled(self.demo_access_code):
            problems.append(
                "PUBLIC_MODE=true 但 DEMO_ACCESS_CODE 未配置"
            )
        if (
            self.is_public_mode
            and self.thread_secret_value == DEFAULT_THREAD_SECRET
        ):
            problems.append("公网模式必须更换 THREAD_SECRET")
        if self.is_public_mode and not self.demo_readonly_library:
            problems.append(
                "已开启访问口令但 DEMO_READONLY_LIBRARY=false "
                "→ 公网用户可写入提示词库"
            )
        if not _filled(self.tavily_api_key):
            problems.append("TAVILY_API_KEY 未配置 → 本地无匹配时不会联网补全")

        return problems

    def assert_runtime_safe(self) -> None:
        """公网模式采用 fail-closed，避免误部署为无鉴权服务。"""
        if not self.is_public_mode:
            return

        errors: list[str] = []

        if not _filled(self.demo_access_code):
            errors.append("PUBLIC_MODE=true 时必须配置 DEMO_ACCESS_CODE")

        if self.thread_secret_value == DEFAULT_THREAD_SECRET:
            errors.append("公网模式必须配置随机的 THREAD_SECRET")

        if errors:
            raise RuntimeError("；".join(errors))


def _filled(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())

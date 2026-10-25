"""Application configuration.

TODO: Implement settings loading with pydantic-settings.
"""
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
class Settings(BaseSettings):
    deepseek_api_key: SecretStr
    tavily_api_key: SecretStr | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_api_base: str = "https://api.deepseek.com"
    prompt_db_path: Path = (
            PROJECT_ROOT / "data" / "indexes" / "prompt_index.sqlite3"
    )
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
    image_output_dir: Path = (
        PROJECT_ROOT / "data" / "generated" / "images"
    )
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


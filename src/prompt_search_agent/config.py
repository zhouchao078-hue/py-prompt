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
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


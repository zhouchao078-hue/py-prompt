"""指标端点、schema 迁移与生图输出格式。"""

import base64
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.images import (
    ImageGenerationRequest,
    OpenAIImageProvider,
)
from prompt_search_agent.services.prompt_service import PromptServiceResult
from prompt_search_agent.storage import initialize_database, read_schema_version
from prompt_search_agent.storage.migrations import LATEST_VERSION
from prompt_search_agent.webapp import create_app

LEGACY_QUERY_CACHE = """
CREATE TABLE query_cache (
    cache_key TEXT PRIMARY KEY,
    normalized_query TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    index_version TEXT NOT NULL,
    request_json TEXT,
    candidate_ids_json TEXT,
    final_prompt TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class FakeService:
    def generate(self, user_query, thread_id=None, on_stage=None, on_token=None):
        return PromptServiceResult(
            final_prompt="a snowy cat",
            cached=False,
            thread_id=thread_id or "metrics-thread",
        )


def test_metrics_endpoint_exposes_counters(tmp_path: Path) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "metrics.sqlite3",
        data_dir=tmp_path,
    )
    app = create_app(lambda: FakeService(), app_settings=settings)

    with TestClient(app) as client:
        client.get("/api/health")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "prompt_atelier_requests_total" in response.text
    assert "prompt_atelier_request_seconds_bucket" in response.text
    assert "prompt_atelier_generation_waiting" in response.text
    assert "prompt_atelier_disk_free_bytes" in response.text


def test_metrics_records_generation_failures() -> None:
    from prompt_search_agent.services.prompt_service import PromptServiceError

    class BoomService:
        def generate(self, user_query, thread_id=None, on_stage=None, on_token=None):
            raise PromptServiceError("boom")

    app = create_app(lambda: BoomService())

    with TestClient(app) as client:
        client.post("/api/prompt", json={"message": "雪夜白猫"})
        response = client.get("/metrics")

    assert "prompt_atelier_upstream_failures_total" in response.text


def test_migrations_set_and_keep_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "schema.sqlite3"

    initialize_database(db_path)
    assert read_schema_version(db_path) == LATEST_VERSION

    initialize_database(db_path)
    assert read_schema_version(db_path) == LATEST_VERSION


def test_migration_adds_missing_sources_json(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(LEGACY_QUERY_CACHE)
    connection.commit()
    connection.close()

    initialize_database(db_path)

    connection = sqlite3.connect(db_path)
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(query_cache)")
    }
    connection.close()

    assert "sources_json" in columns
    assert read_schema_version(db_path) == LATEST_VERSION


def test_schema_has_conversation_message_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "schema.sqlite3"
    initialize_database(db_path)

    connection = sqlite3.connect(db_path)
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(conversation_messages)"
        )
    }
    connection.close()

    assert "metadata_json" in columns


def test_version_reports_schema_version(tmp_path: Path) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        prompt_db_path=tmp_path / "schema.sqlite3",
        data_dir=tmp_path,
    )
    initialize_database(settings.prompt_db_path)
    app = create_app(lambda: FakeService(), app_settings=settings)

    with TestClient(app) as client:
        data = client.get("/api/version").json()

    assert data["schema_version"] == LATEST_VERSION


def test_output_format_is_forwarded_to_provider(tmp_path: Path) -> None:
    calls: list[dict] = []
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 16

    class Images:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(png).decode(),
                        url=None,
                    )
                ]
            )

    class Client:
        def __init__(self) -> None:
            self.images = Images()

    provider = OpenAIImageProvider(
        api_key="k",
        api_base="http://relay.invalid/v1",
        model="m",
        output_dir=tmp_path,
        output_format="webp",
        client=Client(),
    )

    result = provider.generate(
        ImageGenerationRequest(prompt="a cat", size="1024x1024")
    )

    assert calls[0]["output_format"] == "webp"
    assert result.file_name.endswith(".png")

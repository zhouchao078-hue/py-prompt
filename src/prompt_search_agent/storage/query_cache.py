"""Persistent cache for exact prompt-generation queries."""

import hashlib
from contextlib import closing
from pathlib import Path

from prompt_search_agent.storage.database import connect_database


def sha256_text(value: str) -> str:
    """Return the hexadecimal SHA-256 digest for text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_prompt_version(*prompt_texts: str) -> str:
    """Fingerprint the prompt templates that affect generated results."""

    if not prompt_texts:
        raise ValueError("At least one prompt text is required")

    return sha256_text("\0".join(prompt_texts))[:16]


def build_cache_key(
    normalized_query: str,
    model_name: str,
    prompt_version: str,
    index_version: str,
    context_key: str = "",
) -> str:
    """Build a key that invalidates when inputs or dependencies change."""

    return sha256_text(
        f"{normalized_query}\x00{model_name}\x00{prompt_version}\x00"
        f"{index_version}\x00{context_key}"
    )


def get_prompt_index_version(
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> str:
    """Return a stable O(1) version maintained by SQLite triggers."""

    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        row = connection.execute(
            """
            SELECT prompt_count, max_prompt_id, revision
            FROM prompt_index_state
            WHERE id = 1
            """
        ).fetchone()

    if row is None:
        return "0:0:0"

    return (
        f"{row['prompt_count']}:"
        f"{row['max_prompt_id']}:"
        f"{row['revision']}"
    )


def get_cached_prompt(
    db_path: Path,
    cache_key: str,
    busy_timeout_ms: int = 5000,
) -> str | None:
    """Return a cached final prompt for an exact cache key."""

    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        row = connection.execute(
            """
            SELECT final_prompt
            FROM query_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

    if row is None:
        return None

    return str(row["final_prompt"])


def get_cached_sources_json(
    db_path: Path,
    cache_key: str,
    busy_timeout_ms: int = 5000,
) -> str | None:
    """Return serialized web sources for a cached prompt."""

    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        row = connection.execute(
            """
            SELECT sources_json
            FROM query_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

    if row is None or row["sources_json"] is None:
        return None

    return str(row["sources_json"])


def save_cached_prompt(
    db_path: Path,
    cache_key: str,
    normalized_query: str,
    model_name: str,
    prompt_version: str,
    index_version: str,
    final_prompt: str,
    request_json: str | None = None,
    candidate_ids_json: str | None = None,
    sources_json: str | None = None,
    busy_timeout_ms: int = 5000,
) -> None:
    """Insert or replace an exact-query cache entry."""

    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        connection.execute(
            """
            INSERT INTO query_cache (
                cache_key,
                normalized_query,
                model_name,
                prompt_version,
                index_version,
                request_json,
                candidate_ids_json,
                sources_json,
                final_prompt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                normalized_query = excluded.normalized_query,
                model_name = excluded.model_name,
                prompt_version = excluded.prompt_version,
                index_version = excluded.index_version,
                request_json = excluded.request_json,
                candidate_ids_json = excluded.candidate_ids_json,
                sources_json = excluded.sources_json,
                final_prompt = excluded.final_prompt,
                created_at = CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                normalized_query,
                model_name,
                prompt_version,
                index_version,
                request_json,
                candidate_ids_json,
                sources_json,
                final_prompt,
            ),
        )
        connection.commit()


def delete_cached_prompt(
    db_path: Path,
    cache_key: str,
    busy_timeout_ms: int = 5000,
) -> bool:
    """Delete an exact cache entry and report whether it existed."""

    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        cursor = connection.execute(
            "DELETE FROM query_cache WHERE cache_key = ?",
            (cache_key,),
        )
        connection.commit()

    return cursor.rowcount > 0

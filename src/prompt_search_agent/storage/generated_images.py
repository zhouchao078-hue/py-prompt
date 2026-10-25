"""Persistence and exact-match caching for generated images."""

import hashlib
from contextlib import closing
from pathlib import Path

from prompt_search_agent.images.base import ImageGenerationResult
from prompt_search_agent.storage.database import connect_database


def build_generated_image_cache_key(
    prompt: str,
    provider: str,
    model: str,
    size: str,
) -> str:
    value = f"{prompt}\x00{provider}\x00{model}\x00{size}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_cached_generated_image(
    db_path: Path,
    cache_key: str,
    busy_timeout_ms: int = 5000,
) -> ImageGenerationResult | None:
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        row = connection.execute(
            """
            SELECT
                image_id,
                prompt_text,
                revised_prompt,
                provider,
                model,
                size,
                file_path
            FROM generated_images
            WHERE cache_key = ?
              AND expires_at > CURRENT_TIMESTAMP
            """,
            (cache_key,),
        ).fetchone()

    if row is None:
        return None

    return ImageGenerationResult(
        image_id=str(row["image_id"]),
        file_name=Path(row["file_path"]).name,
        file_path=Path(row["file_path"]),
        prompt=str(row["prompt_text"]),
        revised_prompt=(
            str(row["revised_prompt"])
            if row["revised_prompt"] is not None
            else None
        ),
        provider=str(row["provider"]),
        model=str(row["model"]),
        size=str(row["size"]),
        cached=True,
    )


def save_generated_image(
    db_path: Path,
    cache_key: str,
    result: ImageGenerationResult,
    retention_days: int,
    busy_timeout_ms: int = 5000,
) -> Path | None:
    prompt_hash = hashlib.sha256(
        result.prompt.encode("utf-8")
    ).hexdigest()
    retention = f"+{max(1, retention_days)} days"

    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        previous = connection.execute(
            """
            SELECT file_path
            FROM generated_images
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO generated_images (
                cache_key,
                image_id,
                prompt_hash,
                prompt_text,
                revised_prompt,
                provider,
                model,
                size,
                file_path,
                expires_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                datetime('now', ?)
            )
            ON CONFLICT(cache_key) DO UPDATE SET
                image_id = excluded.image_id,
                prompt_hash = excluded.prompt_hash,
                prompt_text = excluded.prompt_text,
                revised_prompt = excluded.revised_prompt,
                provider = excluded.provider,
                model = excluded.model,
                size = excluded.size,
                file_path = excluded.file_path,
                created_at = CURRENT_TIMESTAMP,
                expires_at = excluded.expires_at
            """,
            (
                cache_key,
                result.image_id,
                prompt_hash,
                result.prompt,
                result.revised_prompt,
                result.provider,
                result.model,
                result.size,
                str(result.file_path),
                retention,
            ),
        )
        connection.commit()

    if previous is None:
        return None

    previous_path = Path(previous["file_path"])
    return previous_path if previous_path != result.file_path else None


def delete_generated_image_record(
    db_path: Path,
    cache_key: str,
    busy_timeout_ms: int = 5000,
) -> None:
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        connection.execute(
            "DELETE FROM generated_images WHERE cache_key = ?",
            (cache_key,),
        )
        connection.commit()


def purge_expired_generated_images(
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> list[Path]:
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        rows = connection.execute(
            """
            SELECT file_path
            FROM generated_images
            WHERE expires_at <= CURRENT_TIMESTAMP
            """
        ).fetchall()
        connection.execute(
            """
            DELETE FROM generated_images
            WHERE expires_at <= CURRENT_TIMESTAMP
            """
        )
        connection.commit()

    return [Path(row["file_path"]) for row in rows]

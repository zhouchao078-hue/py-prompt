import sqlite3
from contextlib import closing
from pathlib import Path

from prompt_search_agent.storage.migrations import (
    apply_migrations,
    get_schema_version,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id TEXT NOT NULL UNIQUE,
    prompt_text TEXT NOT NULL,
    search_tokens TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    category TEXT,
    source_file TEXT NOT NULL,
    source_sheet TEXT,
    source_row INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS prompts_fts USING fts5(
    search_tokens,
    content='prompts',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS prompt_index_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    prompt_count INTEGER NOT NULL DEFAULT 0,
    max_prompt_id INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS query_cache (
    cache_key TEXT PRIMARY KEY,
    normalized_query TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    index_version TEXT NOT NULL,
    request_json TEXT,
    candidate_ids_json TEXT,
    sources_json TEXT,
    final_prompt TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generated_images (
    cache_key TEXT PRIMARY KEY,
    image_id TEXT NOT NULL UNIQUE,
    prompt_hash TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    revised_prompt TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    size TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generated_images_expires_at
ON generated_images(expires_at);

CREATE TABLE IF NOT EXISTS conversations (
    thread_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    summarized_until_message_id INTEGER NOT NULL DEFAULT 0,
    prompt_spec_json TEXT,
    previous_prompt TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thread_id)
        REFERENCES conversations(thread_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread
ON conversation_messages(thread_id, id);

-- 会话身份：浏览器只持有 cookie，恢复码存在这里（只存哈希）
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    token_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_token
ON sessions(token_hash);

-- 会话 → 多条目对话的映射；一个会话每个工具可以有多条历史
CREATE TABLE IF NOT EXISTS session_conversations (
    thread_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id)
        REFERENCES sessions(session_id)
        ON DELETE CASCADE,
    FOREIGN KEY (thread_id)
        REFERENCES conversations(thread_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_conversations_lookup
ON session_conversations(session_id, tool, updated_at DESC);
CREATE TRIGGER IF NOT EXISTS prompts_ai
AFTER INSERT ON prompts
BEGIN
    INSERT INTO prompts_fts(rowid, search_tokens)
    VALUES (new.id, new.search_tokens);

    UPDATE prompt_index_state
    SET prompt_count = prompt_count + 1,
        max_prompt_id = MAX(max_prompt_id, new.id),
        revision = revision + 1
    WHERE id = 1;
END;

CREATE TRIGGER IF NOT EXISTS prompts_ad
AFTER DELETE ON prompts
BEGIN
    INSERT INTO prompts_fts(prompts_fts, rowid, search_tokens)
    VALUES ('delete', old.id, old.search_tokens);

    UPDATE prompt_index_state
    SET prompt_count = MAX(prompt_count - 1, 0),
        max_prompt_id = COALESCE(
            (SELECT MAX(id) FROM prompts),
            0
        ),
        revision = revision + 1
    WHERE id = 1;
END;

CREATE TRIGGER IF NOT EXISTS prompts_au
AFTER UPDATE ON prompts
BEGIN
    INSERT INTO prompts_fts(prompts_fts, rowid, search_tokens)
    VALUES ('delete', old.id, old.search_tokens);

    INSERT INTO prompts_fts(rowid, search_tokens)
    VALUES (new.id, new.search_tokens);

    UPDATE prompt_index_state
    SET max_prompt_id = MAX(max_prompt_id, new.id),
        revision = revision + 1
    WHERE id = 1;
END;

"""


def connect_database(
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        f"PRAGMA busy_timeout = {int(busy_timeout_ms)}"
    )

    return connection
def _ensure_auto_vacuum(connection: sqlite3.Connection) -> None:
    """开启增量回收，否则 DELETE 之后文件不会变小。"""
    mode = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])

    if mode == 2:  # INCREMENTAL
        return

    has_tables = int(
        connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
    )
    connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
    connection.commit()

    if has_tables:
        # 已有库要一次全量 VACUUM 才能切换模式。
        connection.execute("VACUUM")


def reclaim_database(
    db_path: Path,
    busy_timeout_ms: int = 5000,
    pages: int = 1000,
) -> None:
    """把已删除页真正还给文件系统，并顺手 optimize 索引。"""
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        connection.execute(f"PRAGMA incremental_vacuum({int(pages)})")
        connection.execute("PRAGMA optimize")
        connection.commit()


def read_schema_version(
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> int:
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        return get_schema_version(connection)


def initialize_database(
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> None:
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        _ensure_auto_vacuum(connection)
        connection.executescript(SCHEMA_SQL)
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO prompt_index_state (
                id,
                prompt_count,
                max_prompt_id,
                revision
            )
            SELECT
                1,
                COUNT(*),
                COALESCE(MAX(id), 0),
                0
            FROM prompts
            WHERE TRUE
            ON CONFLICT(id) DO UPDATE SET
                prompt_count = excluded.prompt_count,
                max_prompt_id = excluded.max_prompt_id
            """
        )
        connection.commit()


def optimize_database(
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> None:
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        connection.execute("PRAGMA optimize")

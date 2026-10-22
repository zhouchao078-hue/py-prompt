import sqlite3
from contextlib import closing
from pathlib import Path

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
CREATE TRIGGER IF NOT EXISTS prompts_ai
AFTER INSERT ON prompts
BEGIN
    INSERT INTO prompts_fts(rowid, search_tokens)
    VALUES (new.id, new.search_tokens);
END;

CREATE TRIGGER IF NOT EXISTS prompts_ad
AFTER DELETE ON prompts
BEGIN
    INSERT INTO prompts_fts(prompts_fts, rowid, search_tokens)
    VALUES ('delete', old.id, old.search_tokens);
END;

CREATE TRIGGER IF NOT EXISTS prompts_au
AFTER UPDATE ON prompts
BEGIN
    INSERT INTO prompts_fts(prompts_fts, rowid, search_tokens)
    VALUES ('delete', old.id, old.search_tokens);

    INSERT INTO prompts_fts(rowid, search_tokens)
    VALUES (new.id, new.search_tokens);
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
def initialize_database(
    db_path: Path,
    busy_timeout_ms: int = 5000,
) -> None:
    with closing(
        connect_database(db_path, busy_timeout_ms)
    ) as connection:
        connection.executescript(SCHEMA_SQL)
        cache_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(query_cache)"
            ).fetchall()
        }
        if "sources_json" not in cache_columns:
            connection.execute(
                "ALTER TABLE query_cache ADD COLUMN sources_json TEXT"
            )
        connection.commit()

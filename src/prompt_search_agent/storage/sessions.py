"""会话身份与"一个会话多条对话"的映射。

浏览器只拿一个 HttpOnly cookie；恢复码在这里只存 sha256，
所以即使库被读走也拿不到可用的恢复码。
"""

import hashlib
import hmac
import secrets
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from prompt_search_agent.storage.conversation import ConversationRepository
from prompt_search_agent.storage.database import connect_database

CODE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
CODE_LENGTH = 16


@dataclass(frozen=True)
class Session:
    session_id: str
    created_at: str
    last_seen_at: str


@dataclass(frozen=True)
class ConversationEntry:
    thread_id: str
    tool: str
    title: str
    updated_at: str
    message_count: int


def generate_recovery_code() -> str:
    """16 位、去掉易混字符（0/o/1/l/i）的恢复码。"""
    return "".join(
        secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH)
    )


def hash_recovery_code(code: str) -> str:
    normalized = "".join(code.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_code(code: str) -> str:
    return "".join(code.split()).casefold()


class SessionRepository:
    def __init__(self, db_path: Path, busy_timeout_ms: int = 5000) -> None:
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms

    def _connect(self):
        return connect_database(self.db_path, self.busy_timeout_ms)

    def create(self, session_id: str) -> Session:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO sessions(session_id)
                VALUES (?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id,),
            )
            connection.commit()

        session = self.get(session_id)

        if session is None:  # pragma: no cover - 只可能被并发删除
            raise RuntimeError("创建会话失败")

        return session

    def get(self, session_id: str) -> Session | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT session_id, created_at, last_seen_at
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        if row is None:
            return None

        return Session(
            session_id=row["session_id"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
        )

    def touch(self, session_id: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE sessions
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (session_id,),
            )
            connection.commit()

    def set_recovery_code(self, session_id: str, code: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE sessions SET token_hash = ? WHERE session_id = ?",
                (hash_recovery_code(code), session_id),
            )
            connection.commit()

    def has_recovery_code(self, session_id: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT token_hash FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        return bool(row and row["token_hash"])

    def find_by_code(self, code: str) -> str | None:
        digest = hash_recovery_code(code)

        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT session_id, token_hash FROM sessions "
                "WHERE token_hash = ?",
                (digest,),
            ).fetchone()

        if row is None:
            return None

        if not hmac.compare_digest(str(row["token_hash"]), digest):
            return None

        return str(row["session_id"])

    # —— 会话与对话的映射 ——

    def latest_thread(self, session_id: str, tool: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT thread_id
                FROM session_conversations
                WHERE session_id = ? AND tool = ?
                ORDER BY updated_at DESC, rowid DESC
                LIMIT 1
                """,
                (session_id, tool),
            ).fetchone()

        return str(row["thread_id"]) if row else None

    def create_conversation(
        self,
        session_id: str,
        tool: str,
        title: str = "",
    ) -> str:
        thread_id = secrets.token_hex(16)

        ConversationRepository(
            self.db_path,
            self.busy_timeout_ms,
        ).ensure_conversation(thread_id)

        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO session_conversations(
                    thread_id, session_id, tool, title
                )
                VALUES (?, ?, ?, ?)
                """,
                (thread_id, session_id, tool, title[:120]),
            )
            connection.commit()

        return thread_id

    def resolve_thread(
        self,
        session_id: str,
        tool: str,
        requested: str | None,
        title: str = "",
    ) -> str:
        """有指定且属于本会话就用它；否则接着最近一条；没有就新建。"""
        if requested:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT thread_id FROM session_conversations
                    WHERE session_id = ? AND thread_id = ?
                    """,
                    (session_id, requested),
                ).fetchone()

            if row is not None:
                if title:
                    self.touch_conversation(requested, title)
                return str(row["thread_id"])

        latest = self.latest_thread(session_id, tool)

        if latest is not None:
            return latest

        return self.create_conversation(session_id, tool, title or "新对话")

    def owns_thread(self, session_id: str, thread_id: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM session_conversations
                WHERE session_id = ? AND thread_id = ?
                """,
                (session_id, thread_id),
            ).fetchone()

        return row is not None

    def touch_conversation(
        self,
        thread_id: str,
        title: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            if title:
                connection.execute(
                    """
                    UPDATE session_conversations
                    SET updated_at = CURRENT_TIMESTAMP,
                        title = CASE WHEN title = '' THEN ? ELSE title END
                    WHERE thread_id = ?
                    """,
                    (title[:120], thread_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE session_conversations
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE thread_id = ?
                    """,
                    (thread_id,),
                )
            connection.commit()

    def list_conversations(
        self,
        session_id: str,
        tool: str,
        limit: int = 50,
    ) -> list[ConversationEntry]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    sc.thread_id,
                    sc.tool,
                    sc.title,
                    sc.updated_at,
                    (
                        SELECT COUNT(*)
                        FROM conversation_messages m
                        WHERE m.thread_id = sc.thread_id
                    ) AS message_count
                FROM session_conversations sc
                WHERE sc.session_id = ? AND sc.tool = ?
                ORDER BY sc.updated_at DESC, sc.rowid DESC
                LIMIT ?
                """,
                (session_id, tool, max(1, min(limit, 200))),
            ).fetchall()

        return [
            ConversationEntry(
                thread_id=row["thread_id"],
                tool=row["tool"],
                title=row["title"],
                updated_at=row["updated_at"],
                message_count=int(row["message_count"]),
            )
            for row in rows
        ]

    def delete_conversation(self, session_id: str, thread_id: str) -> int:
        """删除本会话下的某条对话，返回删除的消息条数。"""
        if not self.owns_thread(session_id, thread_id):
            return 0

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM conversation_messages WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
            total = int(row["total"]) if row is not None else 0

            # 外键级联会带走映射与消息
            connection.execute(
                "DELETE FROM conversations WHERE thread_id = ?",
                (thread_id,),
            )
            connection.commit()

        return total

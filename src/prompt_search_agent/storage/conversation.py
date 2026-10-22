"""SQLite-backed task-scoped conversation memory."""

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from prompt_search_agent.storage.database import connect_database


@dataclass(frozen=True)
class ConversationMessage:
    id: int
    role: str
    content: str


@dataclass(frozen=True)
class ConversationSnapshot:
    thread_id: str
    summary: str
    prompt_spec_json: str | None
    previous_prompt: str | None
    recent_messages: list[ConversationMessage]

    def render_context(self) -> str:
        sections: list[str] = []

        if self.summary:
            sections.append(f"较早对话摘要：\n{self.summary[:800]}")

        if self.prompt_spec_json:
            sections.append(
                f"当前结构化约束：\n{self.prompt_spec_json[:1600]}"
            )

        if self.previous_prompt:
            sections.append(
                f"上一版提示词：\n{self.previous_prompt[:1000]}"
            )

        if self.recent_messages:
            role_names = {
                "user": "用户",
                "assistant": "助手",
            }
            recent_text = "\n".join(
                f"{role_names.get(message.role, message.role)}："
                f"{message.content[:700]}"
                for message in self.recent_messages
            )
            sections.append(f"最近对话：\n{recent_text}")

        return "\n\n".join(sections)


@dataclass(frozen=True)
class CompressionBatch:
    existing_summary: str
    messages: list[ConversationMessage]
    cutoff_message_id: int


class ConversationRepository:
    def __init__(
        self,
        db_path: Path,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms

    def ensure_conversation(self, thread_id: str) -> None:
        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            connection.execute(
                """
                INSERT INTO conversations(thread_id)
                VALUES (?)
                ON CONFLICT(thread_id) DO NOTHING
                """,
                (thread_id,),
            )
            connection.commit()

    def append_message(
        self,
        thread_id: str,
        role: str,
        content: str,
    ) -> int:
        self.ensure_conversation(thread_id)

        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            cursor = connection.execute(
                """
                INSERT INTO conversation_messages(
                    thread_id,
                    role,
                    content
                )
                VALUES (?, ?, ?)
                """,
                (thread_id, role, content),
            )
            connection.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to append conversation message")
            return int(cursor.lastrowid)

    def load_snapshot(
        self,
        thread_id: str,
        recent_message_limit: int = 8,
    ) -> ConversationSnapshot:
        self.ensure_conversation(thread_id)

        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            conversation = connection.execute(
                """
                SELECT summary, prompt_spec_json, previous_prompt
                FROM conversations
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT id, role, content
                FROM conversation_messages
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, recent_message_limit),
            ).fetchall()

        recent_messages = [
            ConversationMessage(
                id=int(row["id"]),
                role=str(row["role"]),
                content=str(row["content"]),
            )
            for row in reversed(rows)
        ]

        return ConversationSnapshot(
            thread_id=thread_id,
            summary=str(conversation["summary"] or ""),
            prompt_spec_json=conversation["prompt_spec_json"],
            previous_prompt=conversation["previous_prompt"],
            recent_messages=recent_messages,
        )

    def update_after_turn(
        self,
        thread_id: str,
        prompt_spec_json: str | None,
        previous_prompt: str,
    ) -> None:
        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            connection.execute(
                """
                UPDATE conversations
                SET prompt_spec_json = ?,
                    previous_prompt = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = ?
                """,
                (prompt_spec_json, previous_prompt, thread_id),
            )
            connection.commit()

    def touch_conversation(self, thread_id: str) -> None:
        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = ?
                """,
                (thread_id,),
            )
            connection.commit()

    def get_compression_batch(
        self,
        thread_id: str,
        recent_message_limit: int = 8,
        compress_after_message_limit: int = 12,
    ) -> CompressionBatch | None:
        self.ensure_conversation(thread_id)

        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            conversation = connection.execute(
                """
                SELECT summary, summarized_until_message_id
                FROM conversations
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT id, role, content
                FROM conversation_messages
                WHERE thread_id = ?
                  AND id > ?
                ORDER BY id
                """,
                (
                    thread_id,
                    int(conversation["summarized_until_message_id"]),
                ),
            ).fetchall()

        if len(rows) <= compress_after_message_limit:
            return None

        evicted_rows = rows[:-recent_message_limit]
        messages = [
            ConversationMessage(
                id=int(row["id"]),
                role=str(row["role"]),
                content=str(row["content"]),
            )
            for row in evicted_rows
        ]

        return CompressionBatch(
            existing_summary=str(conversation["summary"] or ""),
            messages=messages,
            cutoff_message_id=messages[-1].id,
        )

    def update_summary(
        self,
        thread_id: str,
        summary: str,
        cutoff_message_id: int,
    ) -> None:
        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            connection.execute(
                """
                UPDATE conversations
                SET summary = ?,
                    summarized_until_message_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = ?
                """,
                (summary, cutoff_message_id, thread_id),
            )
            connection.commit()

    def delete_conversation(self, thread_id: str) -> None:
        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            connection.execute(
                "DELETE FROM conversations WHERE thread_id = ?",
                (thread_id,),
            )
            connection.commit()

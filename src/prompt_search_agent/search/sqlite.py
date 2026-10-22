import sqlite3
from contextlib import closing
from pathlib import Path

from prompt_search_agent.models import PromptCandidate, SearchRequest
from prompt_search_agent.search.tokenizer import extract_search_token
from prompt_search_agent.storage import connect_database


class SqlitePromptSearchBackend:
    def __init__(
        self,
        db_path: Path,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms

    @staticmethod
    def _build_query_variants(
        request: SearchRequest,
    ) -> list[list[str]]:
        query_texts = [
            " ".join(
                value
                for value in [
                    request.subject,
                    request.scene,
                    request.style,
                    request.camera,
                    request.mood,
                    *request.keywords,
                ]
                if value
            ),
            *request.query_variants,
        ]

        variants: list[list[str]] = []
        seen_texts: set[str] = set()

        for query_text in query_texts:
            normalized_text = query_text.strip().casefold()

            if not normalized_text or normalized_text in seen_texts:
                continue

            query_tokens = extract_search_token(normalized_text)

            if not query_tokens:
                continue

            seen_texts.add(normalized_text)
            variants.append(list(dict.fromkeys(query_tokens)))

        return variants

    def search(
        self,
        request: SearchRequest,
        top_k: int = 5,
    ) -> list[PromptCandidate]:
        if top_k <= 0:
            return []

        variants = self._build_query_variants(request)

        if not variants:
            return []

        retrieval_limit = max(top_k * 4, 20)
        all_query_tokens = list(
            dict.fromkeys(
                token
                for tokens in variants
                for token in tokens
            )
        )
        sql = """
        SELECT
            p.prompt_id,
            p.prompt_text,
            p.search_tokens,
            p.category,
            p.source_file,
            p.source_sheet,
            p.source_row,
            bm25(prompts_fts) AS rank
        FROM prompts_fts
        JOIN prompts AS p ON p.id = prompts_fts.rowid
        WHERE prompts_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """

        rows_by_id: dict[str, sqlite3.Row] = {}
        matched_by_id: dict[str, set[str]] = {}
        score_by_id: dict[str, float] = {}
        rank_by_id: dict[str, float] = {}

        with closing(
            connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            for tokens in variants:
                fts_query = " OR ".join(
                    f'"{token}"'
                    for token in tokens
                )
                rows = connection.execute(
                    sql,
                    (fts_query, retrieval_limit),
                ).fetchall()

                for row in rows:
                    prompt_id = str(row["prompt_id"])
                    search_tokens = set(
                        (row["search_tokens"] or "").split()
                    )
                    matched_terms = [
                        token
                        for token in tokens
                        if token in search_tokens
                    ]

                    if not matched_terms:
                        continue

                    coverage = len(matched_terms) / len(tokens)
                    rank = float(row["rank"])

                    rows_by_id[prompt_id] = row
                    matched_by_id.setdefault(prompt_id, set()).update(
                        matched_terms
                    )
                    score_by_id[prompt_id] = max(
                        score_by_id.get(prompt_id, 0.0),
                        coverage,
                    )
                    rank_by_id[prompt_id] = min(
                        rank_by_id.get(prompt_id, rank),
                        rank,
                    )

        candidates: list[PromptCandidate] = []

        for prompt_id, row in rows_by_id.items():
            matched_terms = [
                token
                for token in all_query_tokens
                if token in matched_by_id[prompt_id]
            ]

            candidates.append(
                PromptCandidate(
                    prompt_id=prompt_id,
                    prompt_text=row["prompt_text"],
                    category=row["category"],
                    source_file=row["source_file"],
                    source_sheet=row["source_sheet"],
                    source_row=row["source_row"],
                    relevance_score=score_by_id[prompt_id],
                    matched_terms=matched_terms,
                )
            )

        candidates.sort(
            key=lambda candidate: (
                -candidate.relevance_score,
                rank_by_id[candidate.prompt_id],
                candidate.prompt_id,
            )
        )
        return candidates[:top_k]

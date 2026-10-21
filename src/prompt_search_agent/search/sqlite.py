from contextlib import closing
from pathlib import Path

from prompt_search_agent.models import PromptCandidate, SearchRequest
from prompt_search_agent.search.tokenizer import extract_search_token
from prompt_search_agent.storage import connect_database


class SqlitePromptSearchBackend:
    def __init__(self,db_path: Path,busy_timeout_ms: int = 5000,) -> None:
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms


        
    def search(self,request: SearchRequest,top_k: int = 5,) -> list[PromptCandidate]:
        PCS : list[PromptCandidate] = []
        query_text = " ".join(
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
        )

        query_tokens = extract_search_token(query_text)
        if not query_tokens :
            return []
        fts_query = " OR ".join(
            f'"{token}"'
            for token in query_tokens
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

        with closing(
                connect_database(self.db_path, self.busy_timeout_ms)
        ) as connection:
            rows = connection.execute(
                sql,
                (fts_query, top_k),
            ).fetchall()
            for row in rows:
                search_tokens = set(
                    (row["search_tokens"] or "").split()
                )
                matched_terms =   [
                    token
                    for token in query_tokens
                    if token in search_tokens
                ]
                if not matched_terms:
                    continue
                PC = PromptCandidate(
                    prompt_id=row["prompt_id"],
                    prompt_text=row["prompt_text"],
                    category=row["category"],
                    source_file=row["source_file"],
                    source_sheet=row["source_sheet"],
                    source_row=row["source_row"],
                    relevance_score=(
                            len(matched_terms) / len(query_tokens)
                    ),
                    matched_terms=matched_terms,
                )

                PCS.append(PC)
        return PCS
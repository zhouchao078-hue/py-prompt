import hashlib

from prompt_search_agent.ingest.records import (
    PreparedPromptRecord,
    RawPromptRecord,
)
from prompt_search_agent.search.tokenizer import (
    build_search_token,
    normalize_text,
)


def sha256_str(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

def prepare_prompt_records(raw_records: list[RawPromptRecord]) -> list[PreparedPromptRecord]:
    PPRS: list[PreparedPromptRecord] = []
    prepared_by_hash: set[str] = set()
    for raw_record in raw_records:
        if raw_record is None:
            continue
        prompt_text = raw_record.prompt_text
        SH = normalize_text(prompt_text)
        if not SH:
            continue
        content_hash = sha256_str(SH)
        if content_hash in prepared_by_hash:
            continue
        tokens = build_search_token(SH)
        if not tokens:
            continue
        prompt_id = content_hash[:16]

        PPR = PreparedPromptRecord(
            prompt_id = prompt_id,
            prompt_text = SH ,
            search_tokens = " ".join(tokens),
            content_hash=content_hash,
            category=raw_record.category,
            source_file=raw_record.source_file,
            source_sheet=raw_record.source_sheet,
            source_row=raw_record.source_row,
        )
        prepared_by_hash.add(content_hash)
        PPRS.append(PPR)
    return PPRS



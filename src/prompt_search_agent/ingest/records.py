from pydantic import BaseModel


class RawPromptRecord(BaseModel):
    prompt_text: str
    category: str | None = None
    source_file: str
    source_sheet: str
    source_row: int
    
class PreparedPromptRecord(BaseModel):
    prompt_id: str
    prompt_text: str
    search_tokens: str
    content_hash: str
    category: str | None = None
    source_file: str
    source_sheet: str | None = None
    source_row: int | None = None
class ImportResult(BaseModel):
    raw_count: int
    prepared_count: int
    inserted_count: int
    duplicate_count: int

class ImportFailure(BaseModel):
    source_file: str
    error: str


class BatchImportResult(BaseModel):
    file_count: int
    successful_files: int
    failed_files: int
    raw_count: int
    prepared_count: int
    inserted_count: int
    duplicate_count: int
    failures: list[ImportFailure]
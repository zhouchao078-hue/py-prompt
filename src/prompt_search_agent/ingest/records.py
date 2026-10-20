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
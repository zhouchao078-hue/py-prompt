from pathlib import Path
from typing import Protocol

from prompt_search_agent.ingest.records import RawPromptRecord


class PromptExtractor(Protocol):
    def extract(self, path: Path) -> list[RawPromptRecord]:
       ...



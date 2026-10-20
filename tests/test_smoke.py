"""Initial project smoke tests."""

from pathlib import Path

import prompt_search_agent
from prompt_search_agent.search.fake import load_prompt_records


def test_package_imports() -> None:
    assert prompt_search_agent.__version__ == "0.1.0"


def test_load_prompt_records() -> None:
    fixture = Path(__file__).parent / "fixtures" / "prompts.jsonl"

    records = load_prompt_records(fixture)

    assert len(records) == 5
    assert records[0].prompt_id == "p001"

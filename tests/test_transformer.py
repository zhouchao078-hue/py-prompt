from prompt_search_agent.ingest.records import RawPromptRecord
from prompt_search_agent.ingest.transformer import (
    prepare_prompt_records,
)


def test_prepare_prompt_records() -> None:
    records = [
        RawPromptRecord(
            prompt_text="赛博朋克\u200b电影感，低机位",
            category="人物",
            source_file="a.xlsx",
            source_sheet="Sheet1",
            source_row=2,
        ),
        RawPromptRecord(
            prompt_text="赛博朋克电影感，低机位",
            category="人物",
            source_file="b.xlsx",
            source_sheet="Sheet1",
            source_row=3,
        ),
    ]

    prepared = prepare_prompt_records(records)

    assert len(prepared) == 1
    assert "\u200b" not in prepared[0].prompt_text
    assert prepared[0].prompt_id == prepared[0].content_hash[:16]
    assert "赛博朋克" in prepared[0].search_tokens
    assert "电影感" in prepared[0].search_tokens
    assert prepared[0].source_file == "a.xlsx"
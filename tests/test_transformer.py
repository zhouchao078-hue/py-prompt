from prompt_search_agent.ingest.records import RawPromptRecord
from prompt_search_agent.ingest.transformer import (
    build_search_tokens,
    normalize_category,
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


def test_category_is_stripped_of_numbering() -> None:
    assert normalize_category("2.爆款关键词") == "爆款关键词"
    assert normalize_category("汉服_婚纱") == "汉服 婚纱"
    assert normalize_category("人物_ 动物（铠甲") == "人物 动物 铠甲"
    assert normalize_category(None) == ""


def test_category_terms_enter_search_tokens() -> None:
    """分类里的词以前搜不到：库里有 35 条「汉服」全都检索不到。"""
    tokens = build_search_tokens("a beautiful woman in snow", "汉服_婚纱")

    assert "汉服" in tokens
    assert "婚纱" in tokens


def test_generic_category_words_are_filtered() -> None:
    tokens = build_search_tokens("cute cat", "2.爆款关键词")

    assert "爆款" not in tokens
    assert "关键词" not in tokens
    assert "爆款关键词" not in tokens
    assert "cute" in tokens
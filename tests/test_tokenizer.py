from prompt_search_agent.search.tokenizer import (
    build_search_token,
    extract_search_token,
    normalize_text,
)


def test_normalize_text() -> None:
    text = "汉服\u200b   少女\r\n雪夜"
    expected = "汉服 少女\n雪夜"
    assert normalize_text(text) == expected


def test_chinese_search_token() -> None:
    tokens = build_search_token("北京市朝阳区的雪夜街头")
    assert "朝阳" in tokens


def test_aigc_terms() -> None:
    tokens = build_search_token("赛博朋克电影感，低机位")
    assert "赛博朋克" in tokens
    assert "电影感" in tokens
    assert "低机位" in tokens


def test_query_tokens_are_deduplicated() -> None:
    tokens = extract_search_token("汉服少女汉服")
    assert tokens.count("汉服") == 1


def test_empty_input() -> None:
    assert build_search_token("") == []
    assert build_search_token("   ") == []
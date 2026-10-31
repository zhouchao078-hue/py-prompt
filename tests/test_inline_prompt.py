from prompt_search_agent.services.prompt_service import extract_inline_prompt


def test_extracts_after_colon() -> None:
    assert (
        extract_inline_prompt("把这句话改写成更专业的摄影提示词：一只猫在雪地里")
        == "一只猫在雪地里"
    )


def test_extracts_from_quotes() -> None:
    assert extract_inline_prompt("把「一只狗在公园里奔跑」翻译成英文") == (
        "一只狗在公园里奔跑"
    )
    assert extract_inline_prompt('把"雪山白猫，电影感"精简一下') == (
        "雪山白猫，电影感"
    )


def test_bare_instruction_has_no_inline_prompt() -> None:
    """没有引用标记就返回空串：让调用方去追问，而不是瞎猜。"""
    for query in [
        "把围巾从蓝色改成红色",
        "改成不违规的版本",
        "帮我润色一下",
        "注意：别太暗",
    ]:
        assert extract_inline_prompt(query) == "", query


def test_short_tail_is_not_a_prompt() -> None:
    assert extract_inline_prompt("改成：红") == ""

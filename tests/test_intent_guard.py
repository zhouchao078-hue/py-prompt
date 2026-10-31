from prompt_search_agent.models import IntentResult
from prompt_search_agent.services.prompt_service import PromptService


def make_intent(intent: str) -> IntentResult:
    return IntentResult(
        intent=intent,  # type: ignore[arg-type]
        confidence=0.9,
        reason="测试",
        assistant_reply="说明文字",
    )


def test_process_question_is_not_flipped_to_modify() -> None:
    """问"怎么改的/用什么方法"时句子里带"修改"，但那是在问流程。

    曾经这个守卫会把 question 强改成 modify，用户问一句就被塞一个提示词。
    """
    queries = [
        "上面的那个提示词你是用什么方法修改的",
        "你刚才是怎么改的",
        "这个提示词为什么会违规",
        "你是怎么做到的",
    ]

    for query in queries:
        result = PromptService._apply_intent_guard(query, make_intent("question"))

        assert result is not None
        assert result.intent == "question", query


def test_explicit_modify_request_still_guarded() -> None:
    """真正的修改指令仍然要被纠正成 modify，别把这条护栏拆了。"""
    queries = [
        "帮我修改一下这个提示词",
        "把这个提示词润色一下",
        "这段提示词需要改写",
    ]

    for query in queries:
        result = PromptService._apply_intent_guard(query, make_intent("question"))

        assert result is not None
        assert result.intent == "modify", query


def test_create_with_modify_word_is_corrected() -> None:
    result = PromptService._apply_intent_guard(
        "帮我改写这段描述",
        make_intent("create"),
    )

    assert result is not None
    assert result.intent == "modify"


def test_negated_modify_is_left_alone() -> None:
    result = PromptService._apply_intent_guard(
        "不要修改，保持原样",
        make_intent("question"),
    )

    assert result is not None
    assert result.intent == "question"

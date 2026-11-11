from prompt_search_agent.log_utils import log_value


def test_log_value_truncates_long_multiline_output() -> None:
    rendered = log_value("line one\nline two" + "x" * 50, max_chars=20)

    assert "\n" not in rendered
    assert rendered.endswith("...<truncated>")
    assert len(rendered) < 60


def test_log_value_serializes_structured_output() -> None:
    assert log_value({"ok": True, "count": 2}) == '{"ok":true,"count":2}'

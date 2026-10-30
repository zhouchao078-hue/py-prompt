"""评测集自身的测试：格式、覆盖矩阵、规则断言。"""

from pathlib import Path

import pytest

from prompt_search_agent.evaluation import (
    BUCKETS,
    EvalCase,
    Expect,
    check_case,
    check_gates,
    load_cases,
    summarize,
    validate_cases,
)

CASES_PATH = Path(__file__).resolve().parents[1] / "data" / "eval" / "cases.jsonl"


def build_case(**overrides) -> EvalCase:
    payload: dict = {
        "id": "x001",
        "bucket": "compose",
        "query": "一只白猫",
        "expect": {"route": "compose", "include": [["白猫", "白色"]], "exclude": []},
    }
    payload.update(overrides)
    return EvalCase.model_validate(payload)


def test_cases_file_is_valid() -> None:
    cases = load_cases(CASES_PATH)

    assert len(cases) >= 18
    assert validate_cases(cases) == []


def test_every_bucket_has_enough_cases() -> None:
    cases = load_cases(CASES_PATH)

    for bucket in BUCKETS:
        assert sum(1 for case in cases if case.bucket == bucket) >= 3


def test_holdout_ratio_is_sane() -> None:
    cases = load_cases(CASES_PATH)
    ratio = sum(1 for case in cases if case.holdout) / len(cases)

    assert 0.15 <= ratio <= 0.40


def test_include_matches_any_synonym() -> None:
    case = build_case(expect=Expect(include=[["白猫", "白色", "白"]]))

    outcome = check_case(
        case,
        final_prompt="一只雪白的猫",
        reply=None,
        response_type="prompt",
        intent="create",
        generated_from_brief=False,
        web_sources=0,
        latency_seconds=1.0,
    )

    assert outcome.include_hits == 1
    assert outcome.missing == []


def test_missing_group_is_reported() -> None:
    case = build_case(expect=Expect(include=[["白猫"], ["围巾"]]))

    outcome = check_case(
        case,
        final_prompt="一只白猫在雪地里",
        reply=None,
        response_type="prompt",
        intent="create",
        generated_from_brief=False,
        web_sources=0,
        latency_seconds=1.0,
    )

    assert outcome.include_hits == 1
    assert outcome.missing == [["围巾"]]


def test_exclude_violation_is_reported() -> None:
    case = build_case(expect=Expect(exclude=["森林"]))

    outcome = check_case(
        case,
        final_prompt="一只白猫走进森林",
        reply=None,
        response_type="prompt",
        intent="create",
        generated_from_brief=False,
        web_sources=0,
        latency_seconds=1.0,
    )

    assert outcome.violations == ["森林"]


def test_aspect_ratio_is_checked() -> None:
    case = build_case(expect=Expect(aspect="2:3"))

    kept = check_case(
        case,
        final_prompt="一只白猫，画幅 2:3",
        reply=None,
        response_type="prompt",
        intent="create",
        generated_from_brief=False,
        web_sources=0,
        latency_seconds=1.0,
    )
    dropped = check_case(
        case,
        final_prompt="一只白猫",
        reply=None,
        response_type="prompt",
        intent="create",
        generated_from_brief=False,
        web_sources=0,
        latency_seconds=1.0,
    )

    assert kept.aspect_ok is True
    assert dropped.aspect_ok is False


@pytest.mark.parametrize(
    ("route", "response_type", "intent", "from_brief", "web"),
    [
        ("compose", "prompt", "create", False, 0),
        ("generate_from_brief", "prompt", "create", True, 0),
        ("web", "prompt", "create", False, 1),
        ("modify", "prompt", "modify", False, 0),
        ("message", "message", "chat", False, 0),
        ("clarification", "clarification", "vague_feedback", False, 0),
        ("any", "not_found", "create", False, 0),
    ],
)
def test_route_expectations(
    route: str,
    response_type: str,
    intent: str,
    from_brief: bool,
    web: int,
) -> None:
    case = build_case(expect=Expect(route=route))  # type: ignore[arg-type]

    outcome = check_case(
        case,
        final_prompt="一只白猫",
        reply=None,
        response_type=response_type,
        intent=intent,
        generated_from_brief=from_brief,
        web_sources=web,
        latency_seconds=1.0,
    )

    assert outcome.route_ok is True


def test_wrong_route_is_detected() -> None:
    case = build_case(expect=Expect(route="web"))

    outcome = check_case(
        case,
        final_prompt="一只白猫",
        reply=None,
        response_type="prompt",
        intent="create",
        generated_from_brief=False,
        web_sources=0,
        latency_seconds=1.0,
    )

    assert outcome.route_ok is False


def test_summary_aggregates_by_bucket() -> None:
    cases = [
        build_case(id="a1", bucket="compose"),
        build_case(id="a2", bucket="compose"),
        build_case(id="a3", bucket="aspect"),
    ]
    outcomes = [
        check_case(
            case,
            final_prompt="一只白猫",
            reply=None,
            response_type="prompt",
            intent="create",
            generated_from_brief=False,
            web_sources=0,
            latency_seconds=1.0 + index,
        )
        for index, case in enumerate(cases)
    ]

    summary = summarize(outcomes)

    assert summary["cases"] == 3
    assert summary["include_recall"] == 1.0
    assert summary["by_bucket"]["compose"]["cases"] == 2
    assert summary["latency_p95"] >= summary["latency_p50"]


def test_gates_flag_regressions() -> None:
    good = {
        "include_recall": 1.0,
        "exclude_violations": 0,
        "aspect_pass_rate": 1.0,
        "route_accuracy": 1.0,
    }
    assert check_gates(good) == []

    bad = dict(good, include_recall=0.5, exclude_violations=2)
    failures = check_gates(bad)

    assert len(failures) == 2


def test_validate_cases_catches_duplicate_and_missing_bucket() -> None:
    cases = [build_case(id="dup", bucket="compose")] * 2

    problems = validate_cases(cases)

    assert any("重复 id" in problem for problem in problems)
    assert any("桶 aspect 只有 0 条" in problem for problem in problems)


def test_validate_cases_catches_conflicting_terms() -> None:
    case = build_case(
        expect=Expect(include=[["森林"]], exclude=["森林"]),
    )

    problems = validate_cases([case])

    assert any("既必含又禁用" in problem for problem in problems)

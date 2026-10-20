from typing import Any

from prompt_search_agent.graph.workflow import build_workflow
from prompt_search_agent.models import PromptCandidate, SearchRequest


class FakeParseChain:
    def __init__(self, parsed: SearchRequest | None) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, str]] = []

    def invoke(
        self,
        input_: dict[str, str],
        config: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(input_)

        if self.parsed is None:
            return {
                "raw": None,
                "parsed": None,
                "parsing_error": None,
            }

        return {
            "raw": None,
            "parsed": self.parsed,
            "parsing_error": None,
        }


class FakeSearchBackend:
    def __init__(self, candidates: list[PromptCandidate]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[SearchRequest, int]] = []

    def search(
        self,
        request: SearchRequest,
        top_k: int = 5,
    ) -> list[PromptCandidate]:
        self.calls.append((request, top_k))
        return self.candidates


class FakeComposeChain:
    def __init__(self, output: str = "最终组装提示词") -> None:
        self.output = output
        self.calls: list[dict[str, str]] = []

    def invoke(
        self,
        input_: dict[str, str],
        config: Any = None,
        **kwargs: Any,
    ) -> str:
        self.calls.append(input_)
        return self.output


def make_candidate(number: int) -> PromptCandidate:
    return PromptCandidate(
        prompt_id=f"p{number:03d}",
        prompt_text=f"候选提示词 {number}",
        category="人物",
        source_file=f"sample{number}.xlsx",
        source_sheet="Sheet1",
        source_row=number,
        relevance_score=1.0 - number * 0.1,
        matched_terms=["少女"],
    )


def test_workflow_success() -> None:
    request = SearchRequest(
        subject="少女",
        scene="雪夜故宫",
        style="电影感",
    )
    candidates = [
        make_candidate(1),
        make_candidate(2),
    ]

    parse_chain = FakeParseChain(request)
    search_backend = FakeSearchBackend(candidates)
    compose_chain = FakeComposeChain("电影感少女站在雪夜故宫中")

    workflow = build_workflow(
        parse_chain,
        search_backend,
        compose_chain,
    )

    result = workflow.invoke(
        {"user_query": "雪夜故宫里的电影感少女"}
    )

    assert result["request"] == request
    assert result["candidates"] == candidates
    assert result["final_prompt"] == "电影感少女站在雪夜故宫中"
    assert search_backend.calls[0][1] == 5
    assert "候选提示词 1" in compose_chain.calls[0]["candidates_text"]


def test_workflow_stops_when_parse_fails() -> None:
    parse_chain = FakeParseChain(None)
    search_backend = FakeSearchBackend([])
    compose_chain = FakeComposeChain()

    workflow = build_workflow(
        parse_chain,
        search_backend,
        compose_chain,
    )

    result = workflow.invoke({"user_query": "无法解析的请求"})

    assert "request" not in result
    assert "candidates" not in result
    assert "final_prompt" not in result
    assert "error" in result

    # analysis_user_input 默认最多重试三次
    assert len(parse_chain.calls) == 3
    assert search_backend.calls == []
    assert compose_chain.calls == []


def test_workflow_returns_error_when_search_has_no_candidates() -> None:
    request = SearchRequest(subject="不存在的角色")
    parse_chain = FakeParseChain(request)
    search_backend = FakeSearchBackend([])
    compose_chain = FakeComposeChain()

    workflow = build_workflow(
        parse_chain,
        search_backend,
        compose_chain,
    )

    result = workflow.invoke({"user_query": "搜索不存在的角色"})

    assert result["request"] == request
    assert result["candidates"] == []
    assert "final_prompt" not in result
    assert result["error"] == "No matching prompt"
    assert compose_chain.calls == []


def test_compose_uses_only_first_three_candidates() -> None:
    request = SearchRequest(subject="少女")
    candidates = [make_candidate(number) for number in range(1, 5)]

    parse_chain = FakeParseChain(request)
    search_backend = FakeSearchBackend(candidates)
    compose_chain = FakeComposeChain("最终提示词")

    workflow = build_workflow(
        parse_chain,
        search_backend,
        compose_chain,
    )

    workflow.invoke({"user_query": "测试前三条候选"})

    candidates_text = compose_chain.calls[0]["candidates_text"]

    assert "候选提示词 1" in candidates_text
    assert "候选提示词 2" in candidates_text
    assert "候选提示词 3" in candidates_text
    assert "候选提示词 4" not in candidates_text
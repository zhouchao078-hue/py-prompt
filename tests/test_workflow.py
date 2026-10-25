from typing import Any

from prompt_search_agent.graph.state import NO_MATCHING_PROMPT
from prompt_search_agent.graph.workflow import build_workflow
from prompt_search_agent.models import (
    PromptCandidate,
    RerankedCandidate,
    RerankResult,
    SearchRequest,
)


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
        return self.candidates[:top_k]


class FakeRerankChain:
    def __init__(
        self,
        selected_ids: list[str],
        needs_generation: bool = False,
        parsed: RerankResult | None = None,
    ) -> None:
        self.selected_ids = selected_ids
        self.needs_generation = needs_generation
        self.parsed = parsed
        self.calls: list[dict[str, str]] = []

    def invoke(
        self,
        input_: dict[str, str],
        config: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(input_)
        result = self.parsed or RerankResult(
            selected=[
                RerankedCandidate(
                    prompt_id=prompt_id,
                    relevance_score=0.9,
                    reason="test",
                )
                for prompt_id in self.selected_ids
            ],
            needs_generation=self.needs_generation,
        )
        return {
            "raw": None,
            "parsed": result,
            "parsing_error": None,
        }


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


class FakeGenerateChain:
    def __init__(self, output: str = "直接生成提示词") -> None:
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


class FakeWebSearchTool:
    def invoke(self, input_: dict[str, str]) -> dict[str, Any]:
        return {
            "results": [
                {
                    "title": "Visual reference",
                    "url": "https://example.com/reference",
                    "content": "A detailed visual reference.",
                }
            ]
        }


class FakeWebFetchTool:
    def invoke(self, input_: dict[str, Any]) -> dict[str, Any]:
        return {
            "results": [
                {
                    "title": "Visual reference",
                    "url": "https://example.com/reference",
                    "raw_content": "Useful visual details from the web.",
                }
            ]
        }


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
        make_candidate(3),
    ]

    parse_chain = FakeParseChain(request)
    search_backend = FakeSearchBackend(candidates)
    rerank_chain = FakeRerankChain(
        selected_ids=["p002", "p001"],
    )
    compose_chain = FakeComposeChain(
        "电影感少女站在雪夜故宫中"
    )
    generate_chain = FakeGenerateChain()

    workflow = build_workflow(
        parse_chain,
        search_backend,
        rerank_chain,
        compose_chain,
        generate_chain,
    )
    result = workflow.invoke(
        {"user_query": "雪夜故宫里的电影感少女"}
    )

    assert result["request"] == request
    assert result["candidates"] == candidates
    assert result["reranked_candidates"] == [
        candidates[1],
        candidates[0],
    ]
    assert result["final_prompt"] == "电影感少女站在雪夜故宫中"
    assert search_backend.calls[0][1] == 20
    assert "候选提示词 2" in compose_chain.calls[0]["candidates_text"]
    assert compose_chain.calls[0]["user_query"] == "雪夜故宫里的电影感少女"
    assert generate_chain.calls == []


def test_rerank_filters_unknown_ids_and_limits_to_three() -> None:
    request = SearchRequest(subject="少女")
    candidates = [
        make_candidate(number)
        for number in range(1, 6)
    ]
    rerank_chain = FakeRerankChain(
        selected_ids=[
            "unknown",
            "p004",
            "p003",
            "p002",
            "p001",
        ],
    )
    compose_chain = FakeComposeChain()
    generate_chain = FakeGenerateChain()
    workflow = build_workflow(
        FakeParseChain(request),
        FakeSearchBackend(candidates),
        rerank_chain,
        compose_chain,
        generate_chain,
    )

    result = workflow.invoke({"user_query": "测试重排"})

    assert [
        candidate.prompt_id
        for candidate in result["reranked_candidates"]
    ] == ["p004", "p003", "p002"]
    assert "候选提示词 1" not in compose_chain.calls[0]["candidates_text"]


def test_workflow_stops_when_parse_fails() -> None:
    parse_chain = FakeParseChain(None)
    search_backend = FakeSearchBackend([])
    rerank_chain = FakeRerankChain([])
    compose_chain = FakeComposeChain()
    generate_chain = FakeGenerateChain()

    workflow = build_workflow(
        parse_chain,
        search_backend,
        rerank_chain,
        compose_chain,
        generate_chain,
    )
    result = workflow.invoke({"user_query": "无法解析的请求"})

    assert "request" not in result
    assert "candidates" not in result
    assert "final_prompt" not in result
    assert "error" in result
    assert len(parse_chain.calls) == 3
    assert search_backend.calls == []
    assert rerank_chain.calls == []
    assert compose_chain.calls == []
    assert generate_chain.calls == []


def test_workflow_returns_not_found_when_no_candidates() -> None:
    request = SearchRequest(subject="不存在的角色")
    rerank_chain = FakeRerankChain(
        selected_ids=[],
        needs_generation=True,
    )
    compose_chain = FakeComposeChain()
    generate_chain = FakeGenerateChain("直接生成的雪山小猫提示词")
    workflow = build_workflow(
        FakeParseChain(request),
        FakeSearchBackend([]),
        rerank_chain,
        compose_chain,
        generate_chain,
    )

    result = workflow.invoke({"user_query": "搜索不存在的角色"})

    assert result["candidates"] == []
    assert result["reranked_candidates"] == []
    assert result["needs_generation"] is False
    assert result["error"] == NO_MATCHING_PROMPT
    assert "final_prompt" not in result
    assert compose_chain.calls == []
    assert generate_chain.calls == []


def test_workflow_uses_web_research_before_not_found() -> None:
    request = SearchRequest(subject="rare visual subject")
    rerank_chain = FakeRerankChain(
        selected_ids=[],
        needs_generation=True,
    )
    compose_chain = FakeComposeChain("web informed final prompt")
    generate_chain = FakeGenerateChain()
    workflow = build_workflow(
        FakeParseChain(request),
        FakeSearchBackend([]),
        rerank_chain,
        compose_chain,
        generate_chain,
        web_search_tool=FakeWebSearchTool(),
        web_fetch_tool=FakeWebFetchTool(),
    )

    result = workflow.invoke(
        {"user_query": "rare visual subject"}
    )

    assert result["final_prompt"] == "web informed final prompt"
    assert len(result["web_sources"]) == 1
    assert "Useful visual details" in compose_chain.calls[0]["web_context"]
    assert generate_chain.calls == []

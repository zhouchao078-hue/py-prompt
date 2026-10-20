from prompt_search_agent.models import PromptCandidate, SearchRequest
from prompt_search_agent.tools import build_search_prompts_tool


class FakeSearchBackend:
    def __init__(self, candidates: list[PromptCandidate]) -> None:
        self.candidates = candidates
        self.last_request: SearchRequest | None = None
        self.last_top_k: int | None = None

    def search(
        self,
        request: SearchRequest,
        top_k: int = 5,
    ) -> list[PromptCandidate]:
        self.last_request = request
        self.last_top_k = top_k
        return self.candidates[:top_k]


def test_search_prompts_tool_returns_serializable_candidates() -> None:
    candidate = PromptCandidate(
        prompt_id="p001",
        prompt_text="雪夜故宫中的汉服少女",
        category="人物",
        source_file="sample.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        relevance_score=1.0,
        matched_terms=["汉服", "雪夜"],
    )
    backend = FakeSearchBackend([candidate])
    tool = build_search_prompts_tool(backend)

    result = tool.invoke(
        {
            "request": {
                "subject": "少女",
                "scene": "雪夜故宫",
            },
            "top_k": 1,
        }
    )

    assert tool.name == "search_prompts"
    assert result == [candidate.model_dump(mode="json")]
    assert backend.last_request is not None
    assert backend.last_request.subject == "少女"
    assert backend.last_top_k == 1

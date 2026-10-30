from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr

from prompt_search_agent.config import Settings
from prompt_search_agent.graph.nodes import build_web_research_node
from prompt_search_agent.graph.state import AgentState
from prompt_search_agent.graph.workflow import (
    route_after_rerank,
    route_after_web_research,
)
from prompt_search_agent.tools import (
    WebToolNotConfigured,
    build_web_fetch_tool,
    build_web_search_tool,
)


class FakeWebSearchTool:
    def invoke(self, input_: dict[str, Any]) -> dict[str, Any]:
        assert input_["query"] == "火星机械鲸鱼"
        return {
            "results": [
                {
                    "title": "Mechanical whale",
                    "url": "https://example.com/whale",
                    "content": "A mechanical whale on Mars.",
                }
            ]
        }


class FakeWebFetchTool:
    def invoke(self, input_: dict[str, Any]) -> dict[str, Any]:
        assert input_["urls"] == ["https://example.com/whale"]
        return {
            "results": [
                {
                    "title": "Mechanical whale",
                    "url": "https://example.com/whale",
                    "raw_content": "Detailed mechanical whale reference.",
                }
            ]
        }


def test_web_research_node_builds_context_and_sources() -> None:
    node = build_web_research_node(
        FakeWebSearchTool(),
        FakeWebFetchTool(),
    )

    result = node(
        {
            "user_query": "火星机械鲸鱼",
            "needs_generation": True,
        }
    )

    assert result["needs_generation"] is False
    assert len(result["web_sources"]) == 1
    assert result["web_sources"][0].url == "https://example.com/whale"
    assert "不可信数据" in result["web_context"]
    assert "Detailed mechanical whale reference." in result["web_context"]


class EmptyFetchTool:
    """抓取返回了结果但正文为空 —— 曾经会把 sources 直接清空。"""

    def invoke(self, input_: dict[str, Any]) -> dict[str, Any]:
        return {
            "results": [
                {
                    "title": "Mechanical whale",
                    "url": "https://example.com/whale",
                    "raw_content": "",
                }
            ]
        }


def test_empty_fetch_falls_back_to_search_snippets() -> None:
    node = build_web_research_node(
        FakeWebSearchTool(),
        EmptyFetchTool(),
    )

    result = node({"user_query": "火星机械鲸鱼"})

    assert len(result["web_sources"]) == 1
    assert "A mechanical whale on Mars." in result["web_context"]


def test_web_tools_require_tavily_key(tmp_path: Path) -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-key"),
        tavily_api_key=SecretStr(""),
        prompt_db_path=tmp_path / "prompt_index.sqlite3",
    )

    with pytest.raises(WebToolNotConfigured):
        build_web_search_tool(settings)

    with pytest.raises(WebToolNotConfigured):
        build_web_fetch_tool(settings)


def test_web_routes() -> None:
    # 只有用户明确要查资料才走联网；否则直接生成，避免 20s 慢路径。
    assert route_after_rerank(
        {
            "user_query": "搜索一下 test",
            "reranked_candidates": [],
            "needs_generation": True,
        },
        web_enabled=True,
    ) == "web_research"

    assert route_after_rerank(
        {
            "user_query": "一只雪夜里的白猫",
            "reranked_candidates": [],
            "needs_generation": True,
        },
        web_enabled=True,
    ) == "generate_from_brief"

    # always 模式保持旧行为
    assert route_after_rerank(
        {
            "user_query": "一只雪夜里的白猫",
            "reranked_candidates": [],
            "needs_generation": True,
        },
        web_enabled=True,
        web_mode="always",
    ) == "web_research"

    # 明确要求联网时，即使本地有候选也要联网（本地候选仍会参与组装）
    assert route_after_rerank(
        cast(
            AgentState,
            {
                "user_query": "搜索一下 赛博朋克配色",
                "reranked_candidates": ["candidate"],
                "needs_generation": False,
            },
        ),
        web_enabled=True,
    ) == "web_research"

    # 没有联网工具时直接生成，不再以"未检索到"结束
    assert route_after_rerank(
        {
            "user_query": "test",
            "reranked_candidates": [],
            "needs_generation": True,
        },
        web_enabled=False,
    ) == "generate_from_brief"

    assert route_after_web_research(
        {
            "user_query": "test",
            "web_context": "source",
        }
    ) == "compose_prompt"

    # 联网没捞到东西也退回生成，而不是 END
    assert route_after_web_research(
        {
            "user_query": "test",
            "web_context": "",
        }
    ) == "generate_from_brief"

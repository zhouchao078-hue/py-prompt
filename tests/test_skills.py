from typing import Any

from prompt_search_agent.skills.prompt_generation import (
    PromptGenerationSkill,
)


class FakeWorkflow:
    def __init__(self) -> None:
        self.input_state: dict[str, Any] | None = None
        self.config: dict[str, Any] | None = None

    def invoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.input_state = state
        self.config = config
        return {
            "user_query": state["user_query"],
            "final_prompt": "最终提示词",
        }


def test_prompt_generation_skill_invokes_workflow() -> None:
    workflow = FakeWorkflow()
    skill = PromptGenerationSkill(workflow)

    result = skill.invoke("雪夜故宫里的汉服少女")

    assert workflow.input_state == {
        "user_query": "雪夜故宫里的汉服少女",
        "conversation_context": "",
    }
    assert result["final_prompt"] == "最终提示词"

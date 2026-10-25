from prompt_search_agent.skills import ChatSkill


class FakeChatChain:
    def __init__(self) -> None:
        self.input_: dict[str, str] = {}

    def invoke(self, input_: dict[str, str]) -> str:
        self.input_ = input_
        return "你好，我在。"


def test_chat_skill_passes_context() -> None:
    chain = FakeChatChain()
    skill = ChatSkill(chain)

    reply = skill.invoke(
        user_query="你好",
        intent="chat",
        conversation_context="用户想生成雪山白猫",
        current_prompt="",
    )

    assert reply
    assert chain.input_["current_prompt"] == "暂无"
    assert chain.input_["intent"] == "chat"

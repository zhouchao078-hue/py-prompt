"""Classify the current user turn before the prompt workflow."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.models import IntentResult

INTENT_SYSTEM_PROMPT = """你是 AIGC 创作对话的意图分类器。

结合最近对话，判断用户当前消息属于以下哪一种意图：

- create：用户给出了新的画面生成需求
- modify：用户要求修改当前或上一版提示词，且修改方向可以理解
- vague_feedback：用户表达不满意，但没有给出具体可执行修改，例如“不太好”“不行”“不是我想要的”
- other：问题、寒暄、取消、闲聊或无法归入以上类型

规则：
- 使用对话上下文理解“这个”“它”“再改一下”等指代
- 不要在本步骤生成或修改提示词
- vague_feedback 必须给出一个简短的 clarification_question
- clarification_question 应提供 3～5 个可回答的方向，例如主体、颜色、场景、风格、镜头或画幅
- 显式修改例如“把围巾改成红色”属于 modify，不属于 vague_feedback
- confidence 表示分类置信度
"""


def create_intent_chain(model: ChatDeepSeek):
    """Build the structured conversation-intent chain."""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", INTENT_SYSTEM_PROMPT),
            (
                "human",
                (
                    "对话上下文：\n{conversation_context}\n\n"
                    "用户当前消息：\n{user_query}"
                ),
            ),
        ]
    )
    structured_model = model.with_structured_output(
        IntentResult,
        method="function_calling",
        include_raw=True,
    )
    return prompt | structured_model

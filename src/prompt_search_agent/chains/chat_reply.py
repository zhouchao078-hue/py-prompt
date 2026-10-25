from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.chains.context_rules import CONVERSATION_HISTORY_RULES

CHAT_SYSTEM_PROMPT = """你是 AIGC 创作助手。
你负责自然聊天、回答当前提示词相关问题，以及确认取消或暂停操作。

规则：
- 使用最近对话理解和回答
- 不要编造用户没有提供的画面内容
- 用户询问当前提示词时，只解释已有信息
- 不要在本聊天链中生成或修改提示词
- 回复自然、简短，不超过 200 个中文字符
- 不输出 Markdown 标题、列表或分析过程
- 用户取消或暂停时，直接确认
"""
CHAT_SYSTEM_PROMPT += "\n\n" + CONVERSATION_HISTORY_RULES


def create_chat_reply_chain(model: ChatDeepSeek):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_SYSTEM_PROMPT),
            (
                "human",
                (
                    "意图：{intent}\n\n"
                    "对话上下文：\n{conversation_context}\n\n"
                    "当前提示词：\n{current_prompt}\n\n"
                    "用户消息：\n{user_query}"
                ),
            ),
        ]
    )
    return prompt | model | StrOutputParser()

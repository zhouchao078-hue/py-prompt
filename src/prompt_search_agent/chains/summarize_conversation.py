"""Compress older conversation turns into a task-scoped summary."""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.chains.context_rules import CONVERSATION_HISTORY_RULES

SUMMARY_SYSTEM_PROMPT = """你是 AIGC 创作会话的上下文压缩器。

把较早的对话压缩成任务型摘要，只保留继续创作所需的信息。

必须保留：
- 用户最终创作目标
- 已确认的主体、颜色、动作、场景、风格、镜头、画幅和否定约束
- 用户已经做出的关键修改
- 尚未解决的问题
- 上一版提示词中仍然有效的重要约束

必须删除：
- 寒暄和重复表达
- 已完成的中间步骤
- 工具调用细节
- 大段候选提示词原文

不得添加用户没有表达的新事实。
新旧约束冲突时，保留最新明确指令。
输出不超过 800 个中文字符，只输出摘要正文。
"""
SUMMARY_SYSTEM_PROMPT += "\n\n" + CONVERSATION_HISTORY_RULES


def create_summary_chain(model: ChatDeepSeek):
    """Build the rolling conversation-summary chain."""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                (
                    "已有摘要：\n{existing_summary}\n\n"
                    "需要压缩的较早对话：\n{messages_text}"
                ),
            ),
        ]
    )
    return prompt | model | StrOutputParser()

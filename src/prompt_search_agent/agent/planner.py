"""Structured planner for the bounded ReAct agent."""

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.agent.state import (
    AgentDecision,
    AgentToolObservation,
)
from prompt_search_agent.agent.tools import AgentToolRegistry

AGENT_PLANNER_PROMPT = """你是本地 AIGC 创作 Agent 的规划器。

根据用户目标、对话历史和工具执行结果，决定下一步。

可用工具：
{tool_descriptions}

规则：
- 每轮只选择一个动作，不要一次规划多个工具
- action=call_tool 时必须填写 tool_name 和符合工具参数的 tool_input
- 没有最终提示词时，不要直接调用生图
- 用户明确要求生成图片时，先获得最终提示词，再调用 generate_image
- 用户明确要求修改现有提示词时，优先调用 rewrite_prompt
- 用户明确要求写入提示词库时，才调用 add_prompt
- 不要重复执行完全相同且已经成功的工具调用
- 工具失败时，根据错误是否可重试决定重试、改用其他工具或结束
- 信息不足且无法继续时，使用 ask_user 提出一个简短、具体的问题
- 任务已经完成时，使用 finish
- finish 的 final_response 只用于普通文本回复；如果已有提示词或图片产物，可以留空
- 不输出完整思维链，reason_summary 只保留一句简短决策理由
- 最多执行 {max_steps} 个规划步骤
"""


def create_agent_planner_chain(model: ChatDeepSeek):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", AGENT_PLANNER_PROMPT),
            (
                "human",
                (
                    "用户目标：\n{user_goal}\n\n"
                    "对话上下文：\n{conversation_context}\n\n"
                    "当前提示词：\n{current_prompt}\n\n"
                    "已执行步骤：{step_count}/{max_steps}\n\n"
                    "工具观察记录：\n{observations_json}"
                ),
            ),
        ]
    )
    structured_model = model.with_structured_output(
        AgentDecision,
        method="function_calling",
        include_raw=True,
    )
    return prompt | structured_model


def format_observations(
    observations: list[AgentToolObservation],
) -> str:
    if not observations:
        return "[]"

    return json.dumps(
        [item.model_dump() for item in observations],
        ensure_ascii=False,
        indent=2,
    )


def tool_descriptions(registry: AgentToolRegistry) -> str:
    return registry.descriptions()

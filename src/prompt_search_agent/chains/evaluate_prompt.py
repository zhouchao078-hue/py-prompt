"""Offline LLM judge for final prompt quality."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.models import PromptQualityResult

QUALITY_SYSTEM_PROMPT = """你是 AIGC 提示词质量评估器。

比较用户原始需求和最终提示词，只评估需求遵守程度。

评分规则：
- 明确主体、颜色、动作、场景、风格、镜头和画幅必须完整保留
- 缺失任何明确要求都要扣分并写入 missing_requirements
- 出现互相矛盾的属性要写入 contradictions
- 引入无关主体或无关场景要写入 irrelevant_content
- 合理的补充细节不扣分，但不能覆盖或削弱用户要求
- 只评估，不重写提示词
- 输出必须符合给定结构
"""


def create_prompt_quality_chain(model: ChatDeepSeek):
    """Build the structured offline prompt-quality judge."""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", QUALITY_SYSTEM_PROMPT),
            (
                "human",
                (
                    "用户原始需求：\n{user_query}\n\n"
                    "最终提示词：\n{final_prompt}"
                ),
            ),
        ]
    )
    structured_model = model.with_structured_output(
        PromptQualityResult,
        method="function_calling",
        include_raw=True,
    )
    return prompt | structured_model

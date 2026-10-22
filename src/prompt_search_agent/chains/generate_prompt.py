"""Generate a prompt directly from a structured user brief."""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

GENERATE_SYSTEM_PROMPT = """你是 AIGC 提示词生成器。

根据用户原始需求和结构化检索条件，生成一段可以直接用于图片或视频生成的提示词。

规则：
- 必须保留用户明确提出的人物、颜色、动作、场景、风格、镜头和画幅要求
- 可以补充有助于画面表达但不与用户要求冲突的视觉细节
- 不要引入无关的新主体
- 按主体、动作、场景、光影、镜头、风格、质量、画幅的顺序组织内容
- 避免重复近义词和模板化质量词堆砌
- 如果存在画幅要求，将画幅放在提示词末尾
- 不要输出解释、标题、Markdown、候选来源或分析过程
- 只输出一段完整、连贯、可直接复制使用的提示词
- 用户原始需求优先于结构化字段
"""


def create_generate_prompt_chain(model: ChatDeepSeek):
    """Build the direct prompt-generation chain."""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", GENERATE_SYSTEM_PROMPT),
            (
                "human",
                (
                    "用户原始需求：\n{user_query}\n\n"
                    "结构化检索条件：\n{request_json}"
                ),
            ),
        ]
    )
    return prompt | model | StrOutputParser()

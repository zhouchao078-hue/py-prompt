from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

SYSTEM_PROMPT = """

你是 AIGC 提示词组装器。

根据用户需求和候选提示词，组装一段可以直接用于 AIGC 图片生成的提示词。

规则：
- 用户明确提出的人物、场景、风格、镜头和氛围必须保留
- 可以从候选提示词中提取相关视觉细节
- 不要引入与用户需求无关的新主体
- 不要输出解释、标题、Markdown 或候选来源
- 只输出一段完整、连贯、可直接复制使用的提示词


"""

def create_compose_prompt(model: ChatDeepSeek):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "{request_json}\n\n候选提示词：\n{candidates_text}"),
        ]
    )
    return prompt | model |  StrOutputParser()
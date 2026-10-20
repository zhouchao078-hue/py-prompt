"""Parse natural-language input into a structured search request.

TODO: Implement this LangChain chain with ChatDeepSeek structured output.
"""
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.config import Settings
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.models import SearchRequest

SYSTEM_PROMPT = ("""你是 AIGC 提示词检索需求解析器。
把用户输入转换为结构化检索条件。

字段规则：
- subject：人物、动物或物品的主体
- scene：地点、时间或环境
- style：艺术、摄影或视觉风格
- camera：镜头、机位、构图或视角
- mood：情绪和氛围
- keywords：服装、颜色、灯光、画质等其他视觉要素

只提取用户明确表达或可以合理推断的视觉信息。
不要把一句话完整复制到字段中，每个字段应使用简短词组。
不要编造用户没有表达的主体或场景。
缺失的字符串字段返回 null，缺失的关键词返回空列表。
不要回答用户，只输出结构化结果。""")
def create_parse_request_chain(model: ChatDeepSeek):

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "{query}"),
        ]
    )
    structured_model = model.with_structured_output(
        SearchRequest,
        method="function_calling",
    )
    return prompt | structured_model



if __name__ == "__main__":
    settings = Settings() # pyright: ignore[reportCallIssue]
    model = create_chat_model(settings)
    chain = create_parse_request_chain(model)

    query = "故宫雪夜里，一个穿汉服的少女，电影感，低机位，冷色调"
    raw_result = chain.invoke({"query": query})
    result = SearchRequest.model_validate(raw_result)
    print(result.model_dump_json(indent=2))
"""DeepSeek chat model construction."""

from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.config import Settings
from prompt_search_agent.cost import UsageCallback


class MissingAPIKeyError(RuntimeError):
    """Raised when the DeepSeek credential is absent."""


def create_chat_model(settings: Settings) -> ChatDeepSeek:
    api_key = settings.deepseek_api_key

    if api_key is None or not api_key.get_secret_value().strip():
        raise MissingAPIKeyError("DEEPSEEK_API_KEY 未配置")

    return ChatDeepSeek(
        model=settings.deepseek_model,
        api_key=api_key,
        base_url=settings.deepseek_api_base,
        temperature=0,
        # 单次调用 20s、重试 1 次：一轮最多 4~5 次调用，别让一次上游抖动
        # 把并发槽位锁死几分钟。
        timeout=20,
        max_retries=1,
        # 全局回调只做总量统计，不区分请求；按请求归属需要用户体系。
        callbacks=[UsageCallback()],
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )


if __name__ == "__main__":
    settings = Settings()
    model = create_chat_model(settings)
    response = model.invoke("只回复：DeepSeek connection ok")
    print(response.content)

"""DeepSeek chat model construction.

TODO: Implement create_chat_model() and a minimal connection smoke test.
"""
from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.config import Settings


def create_chat_model(settings: Settings) -> ChatDeepSeek:
    model = ChatDeepSeek(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_api_base,
        temperature=0,
        timeout=60,
        max_retries=2,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        },
    )
    return model


if __name__ == "__main__":
    # Required fields are populated from .env at runtime by pydantic-settings.
    settings = Settings()  # pyright: ignore[reportCallIssue]
    model = create_chat_model(settings)
    response = model.invoke("只回复：DeepSeek connection ok")
    print(response.content)

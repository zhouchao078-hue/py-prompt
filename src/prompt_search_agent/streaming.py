"""把链式调用的 token 流转发给回调。

链上最后一环是 StrOutputParser，所以 ``chain.stream()`` 直接产出字符串片段。
"""

from collections.abc import Callable
from typing import Any, cast

TokenSink = Callable[[str], None]


def invoke_with_tokens(
    chain: Any,
    inputs: dict[str, Any],
    on_token: TokenSink | None,
) -> str:
    if on_token is None:
        return str(chain.invoke(inputs) or "")

    parts: list[str] = []

    for chunk in chain.stream(inputs):
        text = chunk if isinstance(chunk, str) else getattr(chunk, "content", "")

        if text:
            parts.append(str(text))
            on_token(str(text))

    return "".join(parts)


def token_sink(config: Any) -> TokenSink | None:
    """从 LangGraph 的 config 里取出 token 回调。"""
    if not config:
        return None

    configurable = config.get("configurable") or {}
    sink: Any = configurable.get("on_token")

    if callable(sink):
        return cast(TokenSink, sink)

    return None

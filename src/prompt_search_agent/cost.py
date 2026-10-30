"""成本记账：按请求累计 token 与图片消耗。

只记总量（进程级），不做按用户归属——那需要引入用户体系，demo 阶段不值得。
单价默认 0，填了才算钱，避免用假价格糊弄人。
"""

import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class UsageMeter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._input_tokens = 0
        self._output_tokens = 0
        self._llm_calls = 0
        self._images = 0

    def record_llm(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self._llm_calls += 1
            self._input_tokens += max(int(input_tokens), 0)
            self._output_tokens += max(int(output_tokens), 0)

    def record_image(self) -> None:
        with self._lock:
            self._images += 1

    def reset(self) -> None:
        with self._lock:
            self._input_tokens = 0
            self._output_tokens = 0
            self._llm_calls = 0
            self._images = 0

    def snapshot(self, settings: Any = None) -> dict[str, Any]:
        with self._lock:
            input_tokens = self._input_tokens
            output_tokens = self._output_tokens
            llm_calls = self._llm_calls
            images = self._images

        input_price = float(getattr(settings, "llm_input_price_per_million", 0.0) or 0.0)
        output_price = float(getattr(settings, "llm_output_price_per_million", 0.0) or 0.0)
        image_price = float(getattr(settings, "image_price_per_image", 0.0) or 0.0)

        llm_cost = (
            input_tokens / 1_000_000 * input_price
            + output_tokens / 1_000_000 * output_price
        )
        image_cost = images * image_price

        return {
            "llm_calls": llm_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "images": images,
            "estimated_cost": round(llm_cost + image_cost, 4),
            # 单价没配的话这个字段会是 0，此时 cost 也是 0，不要误读成"免费"。
            "pricing_configured": bool(input_price or output_price or image_price),
        }


USAGE = UsageMeter()


class UsageCallback(BaseCallbackHandler):
    """从每次 LLM 调用里抓 usage_metadata，累计到全局计量器。"""

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = _extract_usage(response)

        if usage is not None:
            USAGE.record_llm(usage[0], usage[1])


def _extract_usage(response: Any) -> tuple[int, int] | None:
    for generations in getattr(response, "generations", []) or []:
        for generation in generations:
            message = getattr(generation, "message", None)
            usage = (
                getattr(message, "usage_metadata", None)
                if message is not None
                else None
            )

            if isinstance(usage, dict) and usage:
                return (
                    int(usage.get("input_tokens") or 0),
                    int(usage.get("output_tokens") or 0),
                )

    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or {}

    if token_usage:
        return (
            int(token_usage.get("prompt_tokens") or 0),
            int(token_usage.get("completion_tokens") or 0),
        )

    return None

import json
from typing import Any, cast

from prompt_search_agent.chains.evaluate_prompt import (
    create_prompt_quality_chain,
)
from prompt_search_agent.config import PROJECT_ROOT, Settings
from prompt_search_agent.llm import create_chat_model
from prompt_search_agent.services.prompt_service import build_prompt_service

CASES = [
    "雪山上戴红围巾的白色短腿小猫，电影感",
    "火星上的紫色机械鲸鱼，赛博朋克，电影感，超广角，--ar 16:9",
    (
        "我要一只在雪山上滑雪的白色短腿胖小猫，"
        "电影感真实摄影，超广角，8k，--ar 2:3"
    ),
]


def main() -> int:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    prompt_service = build_prompt_service(settings)
    quality_chain = create_prompt_quality_chain(
        create_chat_model(settings)
    )

    report: list[dict[str, Any]] = []

    for user_query in CASES:
        prompt_result = prompt_service.generate(user_query)
        raw_quality = cast(
            dict[str, Any],
            quality_chain.invoke(
                {
                    "user_query": user_query,
                    "final_prompt": prompt_result.final_prompt,
                }
            ),
        )
        quality_result = raw_quality["parsed"]

        if quality_result is None:
            report.append(
                {
                    "user_query": user_query,
                    "final_prompt": prompt_result.final_prompt,
                    "error": str(raw_quality["parsing_error"]),
                }
            )
            continue

        report.append(
            {
                "user_query": user_query,
                "final_prompt": prompt_result.final_prompt,
                "cached": prompt_result.cached,
                "quality": quality_result.model_dump(),
            }
        )
        print(
            f"{quality_result.score:>3}  "
            f"{'PASS' if quality_result.passed else 'FAIL'}  "
            f"{user_query}"
        )

    output_path = (
        PROJECT_ROOT
        / "data"
        / "eval"
        / "prompt_quality_report.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Probe the configured OpenAI-compatible image endpoint."""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from prompt_search_agent.config import Settings
from prompt_search_agent.images import ImageGenerationError
from prompt_search_agent.skills.image_generation import (
    build_image_generation_skill,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt",
        default="一只橘猫坐在雪山上，电影感摄影",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="1:1",
        choices=["1:1", "16:9", "2:3", "9:16"],
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    settings = Settings()  # pyright: ignore[reportCallIssue]
    skill = build_image_generation_skill(settings)

    if skill is None:
        print(
            "Image generation is not configured. "
            "Set IMAGE_API_KEY and IMAGE_MODEL in .env."
        )
        return 2

    try:
        result = skill.invoke(args.prompt, args.aspect_ratio)
    except ImageGenerationError as exc:
        print(f"Image generation failed: {exc}")
        return 1

    print(f"Provider: {result.provider}")
    print(f"Model: {result.model}")
    print(f"Size: {result.size}")
    print(f"File: {result.file_path.resolve()}")
    print(f"Exists: {Path(result.file_path).is_file()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

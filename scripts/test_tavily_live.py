import argparse
import json

from prompt_search_agent.config import Settings
from prompt_search_agent.tools import (
    WebToolNotConfigured,
    build_web_fetch_tool,
    build_web_search_tool,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a live Tavily search and extract test",
    )
    parser.add_argument("query", nargs="+")
    args = parser.parse_args()
    query = " ".join(args.query)
    settings = Settings()  # pyright: ignore[reportCallIssue]

    try:
        search_tool = build_web_search_tool(settings)
        fetch_tool = build_web_fetch_tool(settings)
    except WebToolNotConfigured as exc:
        print(str(exc))
        return 1

    search_result = search_tool.invoke({"query": query})

    if isinstance(search_result, dict) and search_result.get("error"):
        print(f"Tavily search failed: {search_result['error']}")
        return 1

    results = search_result.get("results") or []
    print(
        json.dumps(
            [result.get("url") for result in results],
            ensure_ascii=False,
            indent=2,
        )
    )

    if not results:
        return 1

    first_url = results[0].get("url")

    if not first_url:
        return 1

    fetch_result = fetch_tool.invoke(
        {
            "urls": [first_url],
            "query": query,
        }
    )
    print(
        json.dumps(
            fetch_result,
            ensure_ascii=False,
            indent=2,
        )[:3000]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

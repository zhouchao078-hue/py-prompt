"""L2 全量评测：真跑每个用例，出报告并与基线对比。

    python scripts/eval/run_eval.py                 # 跑全部
    python scripts/eval/run_eval.py --limit 5       # 只跑前 5 条（省时间）
    python scripts/eval/run_eval.py --judge         # 追加 LLM 判分
    python scripts/eval/run_eval.py --update-baseline

退出码 1 表示有指标跌破门槛，可以直接挂到 CI 上。
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from prompt_search_agent.config import Settings
from prompt_search_agent.evaluation import (
    CaseOutcome,
    check_case,
    check_gates,
    load_cases,
    mean_judge_score,
    summarize,
    validate_cases,
)
from prompt_search_agent.services.prompt_service import (
    build_prompt_service,
)
from prompt_search_agent.storage import get_prompt_index_version

CASES_PATH = PROJECT_ROOT / "data" / "eval" / "cases.jsonl"
BASELINE_PATH = PROJECT_ROOT / "data" / "eval" / "baseline.json"
REPORT_DIR = PROJECT_ROOT / "data" / "eval" / "reports"


def git_sha() -> str:
    env_sha = __import__("os").environ.get("GIT_COMMIT", "").strip()

    if env_sha:
        return env_sha

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def run_cases(
    service: Any,
    cases: list[Any],
    tavily_ready: bool,
) -> tuple[list[CaseOutcome], list[str]]:
    outcomes: list[CaseOutcome] = []
    skipped: list[str] = []

    for index, case in enumerate(cases, start=1):
        if case.expect.route == "web" and not tavily_ready:
            skipped.append(f"{case.id} 跳过：未配置 TAVILY_API_KEY")
            continue

        started = time.perf_counter()

        try:
            # 绕过缓存：命中缓存一律报 compose，会把真实路由抹平。
            result = service.generate(case.query, use_cache=False)
            latency = time.perf_counter() - started
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{case.id} 生成失败：{type(exc).__name__}: {exc}")
            continue

        outcome = check_case(
            case,
            final_prompt=result.final_prompt,
            reply=result.reply,
            response_type=result.response_type,
            intent=result.intent,
            generated_from_brief=result.generated_from_brief,
            web_sources=len(result.web_sources),
            latency_seconds=latency,
        )
        outcomes.append(outcome)
        flag = "ok  " if outcome.route_ok else "ROUTE"
        print(
            f"[{index:>2}/{len(cases)}] {case.id} {case.bucket:<9} "
            f"{flag} include {outcome.include_hits}/{outcome.include_total} "
            f"{latency:.1f}s"
        )

    return outcomes, skipped


def judge_scores(
    outcomes: list[CaseOutcome],
    cases: list[Any],
    settings: Settings,
) -> list[float]:
    from prompt_search_agent.chains.evaluate_prompt import (
        create_prompt_quality_chain,
    )
    from prompt_search_agent.llm import create_chat_model

    chain = create_prompt_quality_chain(create_chat_model(settings))
    by_id = {case.id: case for case in cases}
    scores: list[float] = []

    for outcome in outcomes:
        case = by_id.get(outcome.id)

        if case is None or not outcome.final_prompt:
            continue

        raw = cast(
            dict[str, Any],
            chain.invoke(
                {
                    "user_query": case.query,
                    "final_prompt": outcome.final_prompt,
                }
            ),
        )
        parsed = raw.get("parsed")

        if parsed is not None:
            scores.append(float(parsed.score))

    return scores


def load_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.is_file():
        return None

    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def diff_with_baseline(
    summary: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> dict[str, float]:
    if not baseline:
        return {}

    keys = (
        "include_recall",
        "aspect_pass_rate",
        "route_accuracy",
        "latency_p95",
    )
    return {
        key: round(summary[key] - baseline[key], 3)
        for key in keys
        if key in baseline
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="全量评测")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--bucket", default="")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    cases = load_cases(CASES_PATH)
    problems = validate_cases(cases)

    if problems:
        for problem in problems:
            print(f"FAIL  {problem}")
        return 1

    if args.bucket:
        cases = [case for case in cases if case.bucket == args.bucket]

    if args.limit:
        cases = cases[: args.limit]

    settings = Settings()
    tavily_ready = settings.tavily_api_key is not None
    service = build_prompt_service(settings)

    outcomes, skipped = run_cases(service, cases, tavily_ready)
    summary = summarize(outcomes)

    if args.judge:
        scores = judge_scores(outcomes, cases, settings)
        summary["judge_mean"] = mean_judge_score(scores)

    baseline = load_baseline()
    deltas = diff_with_baseline(summary, baseline)
    failures = check_gates(summary)

    report = {
        "meta": {
            "git_sha": git_sha(),
            "prompt_version": getattr(service, "prompt_version", "unknown"),
            "index_version": get_prompt_index_version(
                settings.prompt_db_path,
                settings.sqlite_busy_timeout_ms,
            ),
            "model": settings.deepseek_model,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "summary": summary,
        "baseline_delta": deltas,
        "skipped": skipped,
        "outcomes": [item.model_dump() for item in outcomes],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIR / f"{stamp}-{report['meta']['git_sha']}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"用例 {summary['cases']} 条, 跳过 {len(skipped)} 条")
    print(f"include_recall      {summary['include_recall']}")
    print(f"exclude_violations  {summary['exclude_violations']}")
    print(f"aspect_pass_rate    {summary['aspect_pass_rate']}")
    print(f"route_accuracy      {summary['route_accuracy']}")
    print(f"latency p50/p95     {summary['latency_p50']}s / {summary['latency_p95']}s")

    if "judge_mean" in summary:
        print(f"judge_mean          {summary['judge_mean']}")

    if deltas:
        print("相对基线: " + ", ".join(
            f"{key} {value:+.3f}" for key, value in deltas.items()
        ))

    if args.update_baseline:
        BASELINE_PATH.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"基线已更新: {BASELINE_PATH}")

    print(f"报告: {report_path}")

    if failures:
        print()
        for failure in failures:
            print(f"FAIL  {failure}")
        return 1

    print()
    print("PASS  所有门槛通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

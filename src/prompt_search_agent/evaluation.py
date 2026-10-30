"""离线评测：数据结构、规则断言与指标汇总。

设计要点：
* 每个用例自带期望（必含同义词组、禁用词、画幅、期望路由），
  judge 只作为辅助信号 —— 模型自评普遍给高分，区分度太低。
* 规则断言全部可离线跑，不依赖 LLM，能进 CI。
"""

import json
import statistics
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from prompt_search_agent.search.tokenizer import normalize_text

RouteExpectation = Literal[
    "any",
    "compose",
    "generate_from_brief",
    "web",
    "modify",
    "message",
    "clarification",
]

BUCKETS = (
    "compose",
    "aspect",
    "longtail",
    "modify",
    "web",
    "intent",
)

MIN_CASES_PER_BUCKET = 3
HOLDOUT_RATIO_RANGE = (0.15, 0.40)

# 上线门槛：硬要求零容忍，judge 允许小幅波动。
GATES = {
    "include_recall": 0.95,
    "exclude_violations": 0,
    "aspect_pass_rate": 1.0,
    "route_accuracy": 0.90,
}


class Expect(BaseModel):
    route: RouteExpectation = "any"
    # 每个元素是一组同义词，命中任意一个即算满足。
    include: list[list[str]] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    aspect: str | None = None
    max_chars: int | None = None


class EvalCase(BaseModel):
    id: str
    bucket: str
    query: str
    expect: Expect
    holdout: bool = False
    notes: str = ""


class CaseOutcome(BaseModel):
    id: str
    bucket: str
    holdout: bool
    query: str
    final_prompt: str
    response_type: str
    intent: str
    generated_from_brief: bool
    web_sources: int
    latency_seconds: float
    include_hits: int
    include_total: int
    missing: list[list[str]]
    violations: list[str]
    aspect_ok: bool | None
    route_ok: bool
    too_long: bool


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []

    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = line.strip()

        if not stripped or stripped.startswith("//"):
            continue

        try:
            cases.append(EvalCase.model_validate(json.loads(stripped)))
        except Exception as exc:
            raise ValueError(f"{path}:{line_no} 解析失败: {exc}") from exc

    return cases


def _contains(haystack: str, needle: str) -> bool:
    return normalize_text(needle).casefold() in haystack


def _route_matches(
    expected: RouteExpectation,
    response_type: str,
    intent: str,
    generated_from_brief: bool,
    web_sources: int,
) -> bool:
    if expected == "any":
        return True

    if expected == "web":
        return web_sources > 0

    if expected == "compose":
        return response_type == "prompt" and not generated_from_brief

    if expected == "generate_from_brief":
        return response_type == "prompt" and generated_from_brief

    if expected == "modify":
        return intent == "modify"

    return response_type == expected


def check_case(
    case: EvalCase,
    *,
    final_prompt: str | None,
    reply: str | None,
    response_type: str,
    intent: str,
    generated_from_brief: bool,
    web_sources: int,
    latency_seconds: float,
) -> CaseOutcome:
    text = normalize_text(final_prompt or reply or "")
    folded = text.casefold()

    hits = 0
    missing: list[list[str]] = []

    for group in case.expect.include:
        if any(_contains(folded, term) for term in group):
            hits += 1
        else:
            missing.append(group)

    violations = [
        term for term in case.expect.exclude if _contains(folded, term)
    ]

    aspect_ok: bool | None = None

    if case.expect.aspect is not None:
        aspect_ok = case.expect.aspect in text

    too_long = (
        case.expect.max_chars is not None
        and len(text) > case.expect.max_chars
    )

    return CaseOutcome(
        id=case.id,
        bucket=case.bucket,
        holdout=case.holdout,
        query=case.query,
        final_prompt=final_prompt or reply or "",
        response_type=response_type,
        intent=intent,
        generated_from_brief=generated_from_brief,
        web_sources=web_sources,
        latency_seconds=round(latency_seconds, 3),
        include_hits=hits,
        include_total=len(case.expect.include),
        missing=missing,
        violations=violations,
        aspect_ok=aspect_ok,
        route_ok=_route_matches(
            case.expect.route,
            response_type,
            intent,
            generated_from_brief,
            web_sources,
        ),
        too_long=too_long,
    )


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = min(int(len(ordered) * ratio), len(ordered) - 1)
    return round(ordered[index], 2)


def summarize(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    total_groups = sum(item.include_total for item in outcomes)
    total_hits = sum(item.include_hits for item in outcomes)

    aspect_cases = [
        item for item in outcomes if item.aspect_ok is not None
    ]
    latencies = [item.latency_seconds for item in outcomes]

    by_bucket: dict[str, dict[str, Any]] = {}

    for bucket in sorted({item.bucket for item in outcomes}):
        rows = [item for item in outcomes if item.bucket == bucket]
        groups = sum(item.include_total for item in rows)
        hits = sum(item.include_hits for item in rows)

        by_bucket[bucket] = {
            "cases": len(rows),
            "include_recall": round(hits / groups, 3) if groups else 1.0,
            "route_accuracy": round(
                sum(1 for item in rows if item.route_ok) / len(rows),
                3,
            ),
        }

    return {
        "cases": len(outcomes),
        "include_recall": (
            round(total_hits / total_groups, 3) if total_groups else 1.0
        ),
        "exclude_violations": sum(
            1 for item in outcomes if item.violations
        ),
        "aspect_pass_rate": (
            round(
                sum(1 for item in aspect_cases if item.aspect_ok)
                / len(aspect_cases),
                3,
            )
            if aspect_cases
            else 1.0
        ),
        "route_accuracy": round(
            sum(1 for item in outcomes if item.route_ok) / len(outcomes),
            3,
        ),
        "over_length": sum(1 for item in outcomes if item.too_long),
        "latency_p50": _percentile(latencies, 0.5),
        "latency_p95": _percentile(latencies, 0.95),
        "by_bucket": by_bucket,
    }


def check_gates(summary: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    if summary["include_recall"] < GATES["include_recall"]:
        failures.append(
            f"include_recall {summary['include_recall']} "
            f"< {GATES['include_recall']}"
        )

    if summary["exclude_violations"] > GATES["exclude_violations"]:
        failures.append(
            f"exclude_violations {summary['exclude_violations']} "
            f"> {GATES['exclude_violations']}"
        )

    if summary["aspect_pass_rate"] < GATES["aspect_pass_rate"]:
        failures.append(
            f"aspect_pass_rate {summary['aspect_pass_rate']} "
            f"< {GATES['aspect_pass_rate']}"
        )

    if summary["route_accuracy"] < GATES["route_accuracy"]:
        failures.append(
            f"route_accuracy {summary['route_accuracy']} "
            f"< {GATES['route_accuracy']}"
        )

    return failures


def validate_cases(cases: list[EvalCase]) -> list[str]:
    """静态校验：格式、唯一性、覆盖矩阵、盲测比例。"""
    problems: list[str] = []
    seen: set[str] = set()

    for case in cases:
        if case.id in seen:
            problems.append(f"重复 id: {case.id}")
        seen.add(case.id)

        if case.bucket not in BUCKETS:
            problems.append(f"{case.id} 未知桶: {case.bucket}")

        if not case.query.strip():
            problems.append(f"{case.id} query 为空")

        for group in case.expect.include:
            if not group:
                problems.append(f"{case.id} 存在空的同义词组")
            elif any(not term.strip() for term in group):
                problems.append(f"{case.id} 同义词组里有空串")

        flat_include = {term for group in case.expect.include for term in group}

        for term in case.expect.exclude:
            if term in flat_include:
                problems.append(f"{case.id} 同一词既必含又禁用: {term}")

    for bucket in BUCKETS:
        count = sum(1 for case in cases if case.bucket == bucket)
        if count < MIN_CASES_PER_BUCKET:
            problems.append(
                f"桶 {bucket} 只有 {count} 条，至少要 {MIN_CASES_PER_BUCKET} 条"
            )

    if cases:
        ratio = sum(1 for case in cases if case.holdout) / len(cases)
        low, high = HOLDOUT_RATIO_RANGE

        if not low <= ratio <= high:
            problems.append(
                f"盲测比例 {ratio:.2f} 不在 {low}~{high} 之间"
            )

    return problems


def mean_judge_score(scores: list[float]) -> float:
    return round(statistics.fmean(scores), 2) if scores else 0.0

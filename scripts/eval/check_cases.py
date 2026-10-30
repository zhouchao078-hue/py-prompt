"""L1 静态校验：评测集格式与覆盖矩阵。

不花钱、秒级，适合放进 CI。真正的全量评测在 run_eval.py。

    python scripts/eval/check_cases.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from prompt_search_agent.evaluation import (
    BUCKETS,
    load_cases,
    validate_cases,
)

CASES_PATH = PROJECT_ROOT / "data" / "eval" / "cases.jsonl"


def main() -> int:
    if not CASES_PATH.is_file():
        print(f"评测集不存在: {CASES_PATH}")
        return 1

    cases = load_cases(CASES_PATH)
    print(f"用例总数: {len(cases)}")

    for bucket in BUCKETS:
        count = sum(1 for case in cases if case.bucket == bucket)
        print(f"  {bucket:<12} {count}")

    holdout = sum(1 for case in cases if case.holdout)
    print(f"盲测用例: {holdout} ({holdout / len(cases):.0%})")

    problems = validate_cases(cases)

    if problems:
        print()
        for problem in problems:
            print(f"FAIL  {problem}")
        return 1

    print()
    print("PASS  格式与覆盖矩阵校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

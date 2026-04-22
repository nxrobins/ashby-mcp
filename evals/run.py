"""Eval CLI — `uv run python -m evals.run [case_glob]`.

Reads YAML cases from `evals/cases/`, runs each through the Anthropic
tool-use loop against the fake Ashby, grades the results, and prints a
summary table.

Env vars:
  ANTHROPIC_API_KEY       — required (for both the runner and the judge)
  ASHBY_EVAL_MODEL        — default `claude-sonnet-4-6`
  ASHBY_EVAL_JUDGE_MODEL  — default `claude-haiku-4-5-20251001`

Exit code is 0 if every case passed, 1 otherwise — so this slots into CI.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import logging
import os
import pathlib
import sys

import yaml

from .grader import grade
from .runner import DEFAULT_MODEL, run_case

logging.basicConfig(
    level=os.getenv("ASHBY_EVAL_LOG", "WARNING").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

CASES_DIR = pathlib.Path(__file__).parent / "cases"


def _load_cases(pattern: str | None) -> list[dict]:
    paths = sorted(CASES_DIR.glob(pattern or "*.yaml"))
    cases = []
    for p in paths:
        with p.open() as f:
            data = yaml.safe_load(f)
        data["_path"] = str(p.relative_to(CASES_DIR.parent))
        cases.append(data)
    return cases


def _fmt_check(c) -> str:
    mark = "✓" if c.passed else "✗"
    return f"  {mark} {c.name}" + (f" — {c.detail}" if c.detail and not c.passed else "")


def _print_case(case: dict, result, g) -> None:
    print(f"\n── {case['name']} ({case['_path']}) ──")
    print(f"  turns={result.turns}  tools={len(result.tool_calls)}  "
          f"stop={result.stop_reason}  "
          f"in_tok={result.usage.get('input_tokens', 0)}  "
          f"out_tok={result.usage.get('output_tokens', 0)}")
    if result.error:
        print(f"  ERROR: {result.error}")
        return
    for c in g.checks:
        print(_fmt_check(c))
    if g.judge_score is not None:
        mark = "✓" if g.judge_score >= 3 else "✗"
        print(f"  {mark} judge: {g.judge_score}/5 — {g.judge_reasoning}")
    if os.getenv("ASHBY_EVAL_VERBOSE"):
        print("  tool calls:", [tc.name for tc in result.tool_calls])
        print("  final:", result.final_text[:400].replace("\n", " "))


def _print_summary(passed: int, total: int, total_tokens: dict[str, int]) -> None:
    print("\n" + "=" * 60)
    print(f"Result: {passed}/{total} cases passed "
          f"({total_tokens.get('input_tokens', 0)} in / "
          f"{total_tokens.get('output_tokens', 0)} out tokens)")


async def _main_async(pattern: str | None, model: str, dump: str | None) -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    cases = _load_cases(pattern)
    if not cases:
        print(f"no cases matched {pattern or '*.yaml'}", file=sys.stderr)
        return 2

    print(f"Running {len(cases)} case{'s' if len(cases) != 1 else ''} against {model}")

    passed = 0
    totals = {"input_tokens": 0, "output_tokens": 0}
    trace = []
    for case in cases:
        result = await run_case(case, model=model)
        g = grade(case, result)
        _print_case(case, result, g)
        if g.overall_pass:
            passed += 1
        totals["input_tokens"] += result.usage.get("input_tokens", 0)
        totals["output_tokens"] += result.usage.get("output_tokens", 0)
        trace.append({
            "case": case["name"],
            "pass": g.overall_pass,
            "turns": result.turns,
            "tool_calls": [{"name": tc.name, "input": tc.input} for tc in result.tool_calls],
            "final_text": result.final_text,
            "checks": [{"name": c.name, "pass": c.passed, "detail": c.detail} for c in g.checks],
            "judge_score": g.judge_score,
            "judge_reasoning": g.judge_reasoning,
            "usage": result.usage,
        })

    _print_summary(passed, len(cases), totals)

    if dump:
        with open(dump, "w") as f:
            json.dump(trace, f, indent=2)
        print(f"Trace written to {dump}")

    return 0 if passed == len(cases) else 1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("pattern", nargs="?", default=None,
                   help="glob pattern within evals/cases/ (default: *.yaml)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="model id (default: %(default)s)")
    p.add_argument("--dump", default=None, help="write a JSON trace to this path")
    args = p.parse_args()
    sys.exit(asyncio.run(_main_async(args.pattern, args.model, args.dump)))


if __name__ == "__main__":
    main()

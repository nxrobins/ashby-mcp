"""Grading — structural checks plus optional LLM-as-judge.

Structural checks are deterministic and cheap:
  - tools_called: tool names that must appear in the trace (order-free)
  - must_include: substrings that must appear in the final answer
  - must_exclude: substrings that must NOT appear in the final answer

The LLM judge is a separate, lighter-weight Claude call (Haiku by
default) that scores the final answer 1-5 against a rubric. We pass the
case's original prompt, the final answer, and the rubric; we ask for
structured JSON back. The judge is expensive enough ($ + time) that
we only invoke it when a case declares a `judge:` block.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .runner import CaseResult

JUDGE_MODEL = os.getenv("ASHBY_EVAL_JUDGE_MODEL", "claude-haiku-4-5-20251001")
JUDGE_PASS_THRESHOLD = 3  # score >= 3 out of 5 counts as a pass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Grade:
    case_name: str
    checks: list[CheckResult] = field(default_factory=list)
    judge_score: int | None = None
    judge_reasoning: str = ""

    @property
    def overall_pass(self) -> bool:
        if any(not c.passed for c in self.checks):
            return False
        if self.judge_score is not None and self.judge_score < JUDGE_PASS_THRESHOLD:
            return False
        return True


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------


def _check_tools_called(expected: list[str], result: CaseResult) -> CheckResult:
    seen = {tc.name for tc in result.tool_calls}
    missing = [t for t in expected if t not in seen]
    return CheckResult(
        name="tools_called",
        passed=not missing,
        detail=f"missing: {missing}" if missing else f"all {len(expected)} tools seen",
    )


def _check_contains(patterns: list[str], text: str, name: str, polarity: bool) -> CheckResult:
    """polarity=True → each pattern MUST appear; polarity=False → MUST NOT appear."""
    mismatched = []
    for p in patterns:
        found = p.lower() in text.lower()
        if found != polarity:
            mismatched.append(p)
    label = "missing" if polarity else "unexpected"
    return CheckResult(
        name=name,
        passed=not mismatched,
        detail=f"{label}: {mismatched}" if mismatched else "ok",
    )


def _run_structural(case: dict, result: CaseResult) -> list[CheckResult]:
    checks: list[CheckResult] = []
    s = case.get("structural_checks", {}) or {}
    if tools := s.get("tools_called"):
        checks.append(_check_tools_called(tools, result))
    if includes := s.get("must_include"):
        checks.append(_check_contains(includes, result.final_text, "must_include", True))
    if excludes := s.get("must_exclude"):
        checks.append(_check_contains(excludes, result.final_text, "must_exclude", False))
    return checks


# ---------------------------------------------------------------------------
# LLM-as-judge
# ---------------------------------------------------------------------------


JUDGE_INSTRUCTIONS = """\
You are grading an AI recruiting assistant's response to a user's question.

You will receive the user's prompt, the assistant's final answer, and a rubric.
Rate the answer 1-5 where:
  1 = useless (off-topic, empty, or actively wrong)
  2 = weak (some relevance but misses the core ask)
  3 = acceptable (answers the ask, minor gaps)
  4 = strong (thorough, specific, would save the recruiter time)
  5 = excellent (goes beyond the ask with appropriate rigor)

Respond with a single JSON object on one line:
  {"score": N, "reasoning": "one sentence"}
Nothing else.
"""


def _judge(case: dict, result: CaseResult) -> tuple[int | None, str]:
    """Return (score, reasoning), or (None, "") if no judge block on this case."""
    rubric = (case.get("judge") or {}).get("rubric")
    if not rubric:
        return None, ""

    client = anthropic.Anthropic()
    prompt = (
        f"## User prompt\n{case['prompt']}\n\n"
        f"## Assistant's final answer\n{result.final_text}\n\n"
        f"## Rubric\n{rubric}\n"
    )
    msg = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=256,
        system=JUDGE_INSTRUCTIONS,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    # Grab the first {...} block — models occasionally add stray prose.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None, f"could not parse judge output: {text[:200]}"
    try:
        data = json.loads(match.group(0))
        return int(data["score"]), str(data.get("reasoning", ""))
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return None, f"parse error: {e} — raw: {text[:200]}"


def grade(case: dict, result: CaseResult) -> Grade:
    g = Grade(case_name=case["name"])
    if result.error:
        g.checks.append(CheckResult(name="runner", passed=False, detail=result.error))
        return g
    g.checks = _run_structural(case, result)
    score, reasoning = _judge(case, result)
    g.judge_score = score
    g.judge_reasoning = reasoning
    return g

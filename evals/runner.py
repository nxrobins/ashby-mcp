"""Eval runner — drives Claude through a tool-use loop against the fake Ashby.

Given a case (prompt + expected behavior), this module:
  1. Installs the fake Ashby transport into the shared AshbyClient.
  2. Converts our MCP tool schemas to Anthropic tool-use format.
  3. Calls `anthropic.Anthropic().messages.create(...)` and handles the
     tool-use loop until the model returns `end_turn`.
  4. Returns a CaseResult with the tool-call trace and the final text.

The runner does NOT grade — `grader.py` owns that. Separating keeps the
runner's output reproducible (same trace regardless of rubric changes).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import anthropic

from ashby.client import ashby_client
from ashby.handlers import dispatch
from ashby.tools import all_tools

from .fake_server import install as install_fake

logger = logging.getLogger("ashby.evals.runner")

DEFAULT_MODEL = os.getenv("ASHBY_EVAL_MODEL", "claude-sonnet-4-6")
MAX_TURNS = 20
MAX_TOKENS = 4096

SYSTEM_PROMPT = (
    "You are an AI recruiting assistant with access to the Ashby ATS via "
    "MCP tools. The current date is 2026-04-22. When asked to find or "
    "analyze candidates, use the provided tools to gather evidence before "
    "answering. Cite specific candidate and job IDs in your final answer "
    "so the user can act on it. Be concise."
)


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: str  # text content returned to the model


@dataclass
class CaseResult:
    case_name: str
    prompt: str
    final_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    turns: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def _anthropic_tools() -> list[dict]:
    """Convert our MCP Tool objects to Anthropic tool-use schemas."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.inputSchema,
        }
        for t in all_tools()
    ]


def _first_text(blocks: list) -> str:
    for b in blocks:
        if getattr(b, "type", None) == "text":
            return b.text
    return ""


async def run_case(case: dict, model: str = DEFAULT_MODEL) -> CaseResult:
    """Run a single eval case. Returns a CaseResult (never raises — errors captured)."""
    result = CaseResult(case_name=case["name"], prompt=case["prompt"], final_text="")

    # Plumb the fake Ashby into the shared client.
    install_fake(ashby_client)

    # Also run with markdown output so we test what real users see.
    os.environ["ASHBY_OUTPUT"] = "markdown"

    client = anthropic.Anthropic()
    tools = _anthropic_tools()
    messages: list[dict] = [{"role": "user", "content": case["prompt"]}]

    try:
        for turn in range(MAX_TURNS):
            result.turns = turn + 1
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )

            # Accumulate token usage across turns.
            u = getattr(response, "usage", None)
            if u is not None:
                result.usage["input_tokens"] = result.usage.get("input_tokens", 0) + u.input_tokens
                result.usage["output_tokens"] = result.usage.get("output_tokens", 0) + u.output_tokens

            if response.stop_reason == "end_turn":
                result.final_text = _first_text(response.content)
                result.stop_reason = "end_turn"
                return result

            if response.stop_reason != "tool_use":
                result.final_text = _first_text(response.content)
                result.stop_reason = response.stop_reason
                return result

            # Pass the assistant message (including tool_use blocks) back verbatim.
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_output = await dispatch(block.name, dict(block.input))
                text = tool_output[0].text if tool_output else ""
                result.tool_calls.append(
                    ToolCall(name=block.name, input=dict(block.input), output=text)
                )
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": text}
                )
            messages.append({"role": "user", "content": tool_results})

        result.stop_reason = "max_turns_exceeded"
    except Exception as e:
        logger.exception("eval case %s crashed", case["name"])
        result.error = f"{type(e).__name__}: {e}"
        result.stop_reason = "error"

    return result

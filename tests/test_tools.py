"""Tests for the tool registry — schema/handler consistency and the
handful of `required` lists that must mirror Ashby's OpenAPI spec.
"""

import pathlib
import re

from ashby.handlers import _SIMPLE, _SPECIAL
from ashby.tools import all_tools

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _tools_by_name() -> dict:
    return {t.name: t for t in all_tools()}


def test_every_tool_is_routed_and_every_route_is_a_tool():
    """A schema without a handler is an unusable tool; a handler without a
    schema is dead code. Keep the two tables in lockstep."""
    advertised = set(_tools_by_name())
    routed = set(_SIMPLE) | set(_SPECIAL)
    assert advertised == routed, (
        f"unrouted tools: {sorted(advertised - routed)}; "
        f"routes without a schema: {sorted(routed - advertised)}"
    )


def test_readme_tool_count_matches_registry():
    readme = (REPO_ROOT / "README.md").read_text()
    match = re.search(r"(\d+) tools across", readme)
    assert match, "README 'What's included' should state the tool count"
    assert int(match.group(1)) == len(all_tools()), (
        "README tool count is stale — update the 'What's included' section"
    )


def test_required_fields_mirror_ashby_spec():
    """Pinned against openapi.json: these endpoints reject calls missing
    any of the listed fields, so the schema should say so up front."""
    tools = _tools_by_name()
    assert tools["create_job"].inputSchema["required"] == ["title", "teamId", "locationId"]
    assert tools["transfer_application"].inputSchema["required"] == [
        "applicationId",
        "jobId",
        "interviewPlanId",
        "interviewStageId",
    ]


def test_search_jobs_only_accepts_title():
    """/job.search takes a single `title` filter; phantom filters would be
    silently ignored by Ashby and mislead the model."""
    schema = _tools_by_name()["search_jobs"].inputSchema
    assert list(schema["properties"]) == ["title"]
    assert schema["required"] == ["title"]

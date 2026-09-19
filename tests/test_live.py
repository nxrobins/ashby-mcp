"""Live smoke tests against the real Ashby API.

These hit only **read-only** endpoints so the tests can never corrupt
workspace data. They exist to catch contract drift — if Ashby changes
a field name or a pagination shape, these tests fail before anyone
sees a silently-broken tool.

Opt-in only:  `uv run pytest -m live`
Skipped if `ASHBY_API_KEY` looks like the dummy unit-test key.
"""

import os
import re

import pytest

pytestmark = [pytest.mark.live]


def _has_real_key() -> bool:
    key = os.environ.get("ASHBY_API_KEY", "")
    return bool(key) and key != "test-key-not-real"


_skip_reason = "ASHBY_API_KEY not set to a real value — live suite skipped"


def _assert_ok_or_skip_on_403(result, tool_name: str) -> dict:
    """Live tests run against a real API key whose permissions we don't
    control, and Ashby occasionally returns transient 5xx. Skip rather
    than fail in both cases — the code is correct either way."""
    if isinstance(result, str):
        if "403" in result:
            pytest.skip(f"{tool_name}: API key lacks permission ({result})")
        if "5" in result and "Server Error" in result:
            pytest.skip(f"{tool_name}: transient upstream error ({result})")
    assert isinstance(result, dict), f"{tool_name} returned unexpected type: {type(result)} ({result!r})"
    assert result.get("success") is True, f"{tool_name} returned {result}"
    return result


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_list_candidates(call_tool):
    result = await call_tool("list_candidates", {"limit": 1})
    res = _assert_ok_or_skip_on_403(result, "list_candidates")
    assert isinstance(res.get("results"), list)


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_list_jobs(call_tool):
    res = _assert_ok_or_skip_on_403(await call_tool("list_jobs", {"limit": 1}), "list_jobs")
    assert isinstance(res.get("results"), list)


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_list_projects(call_tool):
    res = _assert_ok_or_skip_on_403(await call_tool("list_projects", {"limit": 1}), "list_projects")
    assert isinstance(res.get("results"), list)


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_list_custom_fields_candidate_filter(call_tool):
    """Verifies both the endpoint and the client-side objectType filter."""
    res = _assert_ok_or_skip_on_403(
        await call_tool("list_custom_fields", {"objectType": "Candidate", "limit": 100}),
        "list_custom_fields",
    )
    for field in res.get("results", []):
        assert field.get("objectType") == "Candidate"


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_list_candidate_tags(call_tool):
    _assert_ok_or_skip_on_403(await call_tool("list_candidate_tags", {"limit": 5}), "list_candidate_tags")


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_list_interviews(call_tool):
    _assert_ok_or_skip_on_403(await call_tool("list_interviews", {"limit": 1}), "list_interviews")


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_list_interview_plans(call_tool):
    _assert_ok_or_skip_on_403(await call_tool("list_interview_plans", {}), "list_interview_plans")


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
async def test_live_get_candidate_roundtrip(call_tool):
    """List → info: ensure list results can actually be fed back into info."""
    listing = await call_tool("list_candidates", {"limit": 1})
    if isinstance(listing, str) and "403" in listing:
        pytest.skip(f"list_candidates lacks permission: {listing}")
    results = listing.get("results") or []
    if not results:
        pytest.skip("Workspace has no candidates to round-trip")
    candidate_id = results[0]["id"]
    detail = _assert_ok_or_skip_on_403(await call_tool("get_candidate", {"id": candidate_id}), "get_candidate")
    assert detail.get("results", {}).get("id") == candidate_id


def _table_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Split a rendered markdown table into (header columns, row cells)."""
    lines = [l for l in text.splitlines() if l.startswith("| ")]
    header = [c.strip() for c in re.split(r"(?<!\\)\|", lines[0].strip("|"))]
    rows = [[c.strip() for c in re.split(r"(?<!\\)\|", l.strip("|"))] for l in lines[1:]]
    return header, rows


@pytest.mark.skipif(not _has_real_key(), reason=_skip_reason)
@pytest.mark.parametrize(
    "tool, args, required_columns",
    [
        # Columns whose source field the spec marks as required — if the
        # field map named an invented field, these would all render `—`.
        ("list_candidates", {"limit": 5}, ["name"]),
        ("list_jobs", {"limit": 5, "status": ["Open", "Closed"]}, ["status", "updated"]),
        ("list_applications", {"limit": 5}, ["candidate", "stage", "status", "created"]),
    ],
)
async def test_live_markdown_tables_show_real_values(monkeypatch, tool, args, required_columns):
    """Formatting contract: in the default markdown mode the columns the
    field maps read must be populated by the *current* API, not just by
    the checked-in openapi.json snapshot."""
    from ashby.handlers import ToolError, dispatch

    monkeypatch.setenv("ASHBY_OUTPUT", "markdown")
    try:
        text = (await dispatch(tool, args))[0].text
    except ToolError as e:
        if "403" in str(e):
            pytest.skip(f"{tool}: API key lacks permission ({e})")
        raise
    if "_(no results)_" in text:
        pytest.skip(f"{tool}: workspace returned no rows")
    header, rows = _table_rows(text)
    assert rows, text
    for column in required_columns:
        idx = header.index(column)
        blank = [row for row in rows if row[idx] == "—"]
        assert not blank, f"{tool}: column {column!r} rendered as — for {len(blank)} row(s):\n{text}"

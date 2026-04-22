"""Tests for the markdown formatter.

Two layers:
1. Pure tests of `formatting.format_list` / `format_record` / `get_value`.
2. End-to-end tests that run the dispatcher in markdown mode and assert
   on the rendered table — proving the per-tool column configs line up
   with realistic Ashby response shapes.
"""

import json

import pytest

from ashby.formatting import (
    format_list,
    format_record,
    get_value,
    table,
)

BASE = "https://api.ashbyhq.com"


# ---------------------------------------------------------------------------
# Pure formatter tests
# ---------------------------------------------------------------------------


def test_get_value_dotted_path():
    obj = {"a": {"b": {"c": 7}}}
    assert get_value(obj, "a.b.c") == 7
    assert get_value(obj, "a.b.missing") == "—"
    assert get_value(obj, "missing") == "—"


def test_get_value_list_index():
    obj = {"locations": [{"locationName": "SF"}, {"locationName": "NYC"}]}
    assert get_value(obj, "locations.0.locationName") == "SF"
    assert get_value(obj, "locations.1.locationName") == "NYC"
    assert get_value(obj, "locations.5.locationName") == "—"


def test_get_value_callable():
    obj = {"city": "SF", "country": "US"}
    assert get_value(obj, lambda r: f"{r['city']}, {r['country']}") == "SF, US"


def test_get_value_defaults_for_empty():
    assert get_value({"a": None}, "a") == "—"
    assert get_value({"a": ""}, "a") == "—"
    assert get_value(None, "a") == "—"


def test_table_empty_gives_placeholder():
    assert table([], [("id", "id")]) == "_(no results)_"


def test_table_shape():
    rows = [
        {"id": "c1", "name": "Ada"},
        {"id": "c2", "name": "Alan"},
    ]
    out = table(rows, [("id", "id"), ("name", "name")])
    lines = out.splitlines()
    assert lines[0] == "| id | name |"
    assert "---" in lines[1]
    assert lines[2] == "| c1 | Ada |"
    assert lines[3] == "| c2 | Alan |"


def test_table_escapes_pipes_and_truncates():
    rows = [{"note": "a|b"}, {"note": "x" * 80}]
    out = table(rows, [("note", "note")])
    assert r"a\|b" in out
    assert "…" in out  # long cell was truncated


def test_format_list_includes_count_and_cursor():
    response = {
        "success": True,
        "results": [{"id": "c1", "name": "Ada"}],
        "moreDataAvailable": True,
        "nextCursor": "abc",
    }
    out = format_list(response, "Candidates", [("id", "id"), ("name", "name")])
    assert "## Candidates (1, more available)" in out
    assert "| c1 | Ada |" in out
    assert "Next cursor: `abc`" in out


def test_format_record_basic():
    record = {
        "id": "c1",
        "name": "Ada Lovelace",
        "primaryEmailAddress": {"value": "ada@example.com"},
    }
    out = format_record(record, "name", [("email", "primaryEmailAddress.value")])
    assert out.startswith("## Ada Lovelace (`c1`)")
    assert "- **email**: ada@example.com" in out


# ---------------------------------------------------------------------------
# End-to-end tests — dispatcher in markdown mode
# ---------------------------------------------------------------------------


@pytest.fixture
def markdown_mode(monkeypatch):
    monkeypatch.setenv("ASHBY_OUTPUT", "markdown")


async def _call_raw(name: str, arguments: dict | None = None) -> str:
    """Invoke dispatch and return the raw text (not JSON-parsed)."""
    from ashby.handlers import dispatch  # import fresh after env is set
    result = await dispatch(name, arguments or {})
    assert len(result) == 1
    return result[0].text


async def test_list_candidates_renders_table(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.list",
        json={
            "success": True,
            "results": [
                {
                    "id": "c1",
                    "name": "Ada Lovelace",
                    "primaryEmailAddress": {"value": "ada@example.com"},
                    "source": {"title": "LinkedIn"},
                    "createdAt": "2024-12-01T10:00:00Z",
                },
                {
                    "id": "c2",
                    "name": "Alan Turing",
                    "primaryEmailAddress": {"value": "alan@example.com"},
                    "source": {"title": "Referral"},
                    "createdAt": "2024-11-28T09:00:00Z",
                },
            ],
            "moreDataAvailable": False,
        },
    )
    text = await _call_raw("list_candidates", {"limit": 2})
    assert "## Candidates (2)" in text
    assert "| id | name | email | source | created |" in text
    assert "| c1 | Ada Lovelace | ada@example.com | LinkedIn |" in text
    assert "| c2 | Alan Turing | alan@example.com | Referral |" in text
    # Make sure the verbose raw JSON envelope is NOT in the output.
    assert '"success": true' not in text


async def test_list_sources_table_uses_source_type(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/source.list",
        json={
            "success": True,
            "results": [
                {"id": "s1", "title": "LinkedIn", "isArchived": False,
                 "sourceType": {"title": "Job Board"}},
            ],
        },
    )
    text = await _call_raw("list_sources", {})
    assert "## Sources (1)" in text
    assert "| s1 | LinkedIn | Job Board | no |" in text


async def test_get_candidate_renders_record(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.info",
        json={
            "success": True,
            "results": {
                "id": "c1",
                "name": "Ada Lovelace",
                "primaryEmailAddress": {"value": "ada@example.com"},
                "primaryPhoneNumber": {"value": "555-0100"},
                "source": {"title": "LinkedIn"},
                "tags": ["referral", "ex-google"],
                "createdAt": "2024-12-01T10:00:00Z",
            },
        },
    )
    text = await _call_raw("get_candidate", {"id": "c1"})
    assert text.startswith("Candidate: ")
    assert "## Ada Lovelace (`c1`)" in text
    assert "- **email**: ada@example.com" in text
    assert "- **phone**: 555-0100" in text
    assert "- **source**: LinkedIn" in text
    assert "- **tags**: referral, ex-google" in text


async def test_unformatted_tool_falls_back_to_json(httpx_mock, markdown_mode):
    """Tools without a format config (e.g. create_candidate) return raw JSON."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.create",
        json={"success": True, "results": {"id": "c_new"}},
    )
    text = await _call_raw("create_candidate", {"name": "New Person"})
    assert text.startswith("Created candidate: ")
    # JSON fallback
    assert '"id": "c_new"' in text

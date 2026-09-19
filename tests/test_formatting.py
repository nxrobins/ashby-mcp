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
from ashby.handlers import ToolError, dispatch

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
                    "position": "Engineer",
                    "company": "Analytical Engines Ltd",
                    "school": "Cambridge",
                    "socialLinks": [{"type": "LinkedIn", "url": "https://linkedin.com/in/ada"}],
                    "primaryEmailAddress": {"value": "ada@example.com"},
                    "source": {"title": "LinkedIn"},
                    "createdAt": "2024-12-01T10:00:00Z",
                },
                {
                    # No position/company/school/socialLinks — those cells
                    # must render as the "—" placeholder, not blow up.
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
    assert (
        "| id | name | position | company | school | linkedin | email | source | created |" in text
    )
    assert (
        "| c1 | Ada Lovelace | Engineer | Analytical Engines Ltd | Cambridge "
        "| https://linkedin.com/in/ada | ada@example.com | LinkedIn |"
    ) in text
    # Fields the record lacks render as the `—` placeholder, not as blanks.
    assert "| c2 | Alan Turing | — | — | — | — | alan@example.com | Referral |" in text
    # Make sure the verbose raw JSON envelope is NOT in the output.
    assert '"success": true' not in text


async def test_list_all_candidates_truncation_is_called_out(httpx_mock, markdown_mode, monkeypatch):
    """Hitting the page cap with data remaining must be visible in the
    rendered markdown, not just in the JSON envelope."""
    import ashby.handlers as handlers

    monkeypatch.setattr(handlers, "_LIST_ALL_MAX_PAGES", 1)
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.list",
        json={
            "success": True,
            "results": [{"id": "c1", "name": "Ada Lovelace"}],
            "moreDataAvailable": True,
            "nextCursor": "cursor-2",
        },
    )
    text = await _call_raw("list_all_candidates", {})
    assert "## All candidates (1, more available)" in text
    assert "Next cursor: `cursor-2`" in text
    assert "Truncated at 1 results" in text


async def test_list_all_candidates_complete_walk_has_no_truncation_note(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.list",
        json={
            "success": True,
            "results": [{"id": "c1", "name": "Ada Lovelace"}],
            "moreDataAvailable": False,
            "syncToken": "sync-abc",
        },
    )
    text = await _call_raw("list_all_candidates", {})
    assert "## All candidates (1)" in text
    assert "Truncated" not in text
    assert "Sync token: `sync-abc`" in text


async def test_list_sources_table_uses_source_type(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/source.list",
        json={
            "success": True,
            "results": [
                {
                    "id": "s1",
                    "title": "LinkedIn",
                    "isArchived": False,
                    "sourceType": {"title": "Job Board"},
                },
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
                "socialLinks": [{"type": "LinkedIn", "url": "https://linkedin.com/in/ada"}],
                "primaryLocation": {"id": "pl1", "locationSummary": "London, UK"},
                "source": {"title": "LinkedIn"},
                "tags": [
                    {"id": "t1", "title": "referral", "isArchived": False},
                    {"id": "t2", "title": "ex-google", "isArchived": False},
                ],
                "applicationIds": ["a1", "a2"],
                "customFields": [{"id": "cf1", "title": "Referred By", "value": "Bob"}],
                "fileHandles": [{"id": "f1", "name": "cv.pdf", "handle": "h1"}],
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
    assert "- **linkedin**: https://linkedin.com/in/ada" in text
    assert "- **location**: London, UK" in text
    assert "- **applications**: a1, a2" in text
    assert "- **custom_fields**: Referred By: Bob" in text
    # Keys outside the field map are appended under their raw name, so
    # nothing in the record is silently dropped.
    assert '- **fileHandles**: {"id":"f1","name":"cv.pdf","handle":"h1"}' in text


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


# ---------------------------------------------------------------------------
# Error envelopes — Ashby reports validation/permission failures as HTTP 200
# with `success: false`. The formatters must never swallow those.
# ---------------------------------------------------------------------------


async def test_list_error_envelope_is_not_rendered_as_empty_table(httpx_mock, markdown_mode):
    """Before: `format_list` rendered this as "## Applications (0)" over a
    "(no results)" placeholder and the error text was lost entirely."""
    envelope = {
        "success": False,
        "errors": ["invalid_input"],
        "errorInfo": {"code": "INVALID_ARGUMENT", "message": "jobId must be a UUID"},
    }
    httpx_mock.add_response(method="POST", url=f"{BASE}/application.list", json=envelope)
    with pytest.raises(ToolError) as exc_info:
        await dispatch("list_applications", {"jobId": "not-a-uuid"})
    text = str(exc_info.value)
    assert text.startswith("Ashby returned an error for list_applications: ")
    assert "invalid_input" in text
    assert "jobId must be a UUID" in text
    assert "(no results)" not in text
    assert "## Applications" not in text
    # The envelope is passed through verbatim, as JSON, despite markdown mode.
    assert json.loads(text.partition(": ")[2]) == envelope


async def test_record_error_envelope_is_not_rendered_as_blank_record(httpx_mock, markdown_mode):
    """Before: `format_record` rendered this as a "## Record" block whose
    every field was `—`, indistinguishable from a real but empty record."""
    envelope = {
        "success": False,
        "errors": ["not_found"],
        "errorInfo": {"code": "NOT_FOUND", "message": "Candidate not found"},
    }
    httpx_mock.add_response(method="POST", url=f"{BASE}/candidate.info", json=envelope)
    with pytest.raises(ToolError) as exc_info:
        await dispatch("get_candidate", {"id": "c_missing"})
    text = str(exc_info.value)
    assert text.startswith("Ashby returned an error for get_candidate: ")
    assert "not_found" in text
    assert "Candidate not found" in text
    assert "## Record" not in text
    assert "- **email**: —" not in text
    assert json.loads(text.partition(": ")[2]) == envelope


# ---------------------------------------------------------------------------
# Column maps follow Ashby's real response shapes (see test_spec_alignment.py)
# ---------------------------------------------------------------------------


async def test_list_applications_reads_ashby_shapes(httpx_mock, markdown_mode):
    """Application.candidate is a summary and archiveReason uses `text`."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/application.list",
        json={
            "success": True,
            "results": [
                {
                    "id": "a1",
                    "candidate": {
                        "id": "c1",
                        "name": "Priya Raman",
                        "primaryEmailAddress": {"value": "priya@example.com"},
                    },
                    "job": {"id": "j1", "title": "Account Executive"},
                    "currentInterviewStage": {"id": "s1", "title": "Archived"},
                    "status": "Archived",
                    "archiveReason": {
                        "id": "ar1",
                        "text": "Timing (not right now)",
                        "reasonType": "RejectedByCandidate",
                    },
                    "source": {"title": "LinkedIn"},
                    "createdAt": "2025-03-01T10:00:00Z",
                }
            ],
        },
    )
    text = await _call_raw("list_applications", {"status": "Archived"})
    assert (
        "| id | candidate_id | candidate | email | job | stage | status | archive_reason "
        "| source | created |"
    ) in text
    assert (
        "| a1 | c1 | Priya Raman | priya@example.com | Account Executive | Archived | Archived "
        "| Timing (not right now) | LinkedIn |"
    ) in text


async def test_candidate_notes_show_full_content_and_author(httpx_mock, markdown_mode):
    note = ("Strong discovery skills; closed a $2M pipeline. " * 5).strip()  # past the 60-char cap
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.listNotes",
        json={
            "success": True,
            "results": [
                {
                    "id": "n1",
                    "content": note,
                    "createdAt": "2025-01-01T00:00:00Z",
                    "author": {
                        "id": "u1",
                        "firstName": "Hana",
                        "lastName": "Morales",
                        "email": "hm@example.com",
                    },
                }
            ],
            "moreDataAvailable": False,
        },
    )
    text = await _call_raw("list_candidate_notes", {"candidateId": "c1"})
    assert "| hm@example.com |" in text
    assert note in text


async def test_jobs_location_uses_expanded_name_or_falls_back_to_id(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/job.list",
        json={
            "success": True,
            "results": [
                {
                    "id": "j1",
                    "title": "SWE",
                    "status": "Open",
                    "employmentType": "FullTime",
                    "locationId": "loc_1",
                    "departmentId": "d_1",
                    "location": {"id": "loc_1", "name": "San Francisco"},
                    "updatedAt": "2025-01-01T00:00:00Z",
                },
                {
                    "id": "j2",
                    "title": "AE",
                    "status": "Open",
                    "employmentType": "FullTime",
                    "locationId": "loc_2",
                    "departmentId": "d_2",
                    "updatedAt": "2025-01-01T00:00:00Z",
                },
            ],
        },
    )
    text = await _call_raw("list_jobs", {"expand": ["location"]})
    assert "| j1 | SWE | Open | FullTime | San Francisco | d_1 |" in text
    assert "| j2 | AE | Open | FullTime | loc_2 | d_2 |" in text


async def test_custom_fields_table_lists_selectable_values(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/customField.list",
        json={
            "success": True,
            "results": [
                {
                    "id": "f1",
                    "title": "Level",
                    "fieldType": "ValueSelect",
                    "objectType": "Candidate",
                    "isArchived": False,
                    "selectableValues": [
                        {"label": "Junior", "value": "junior"},
                        {"label": "Senior", "value": "senior"},
                    ],
                }
            ],
        },
    )
    text = await _call_raw("list_custom_fields", {})
    assert "| f1 | Level | ValueSelect | Candidate | Junior, Senior | no |" in text


async def test_record_view_keeps_expanded_objects_and_hides_noise(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/application.info",
        json={
            "success": True,
            "results": {
                "id": "a1",
                "candidate": {
                    "id": "c1",
                    "name": "Priya Raman",
                    "primaryEmailAddress": {"value": "priya@example.com"},
                },
                "job": {"id": "j1", "title": "Account Executive"},
                "currentInterviewStage": {"id": "s1", "title": "Onsite"},
                "status": "Active",
                "openings": [{"id": "op1", "openingState": "Open"}],
                "submitterClientIp": "203.0.113.5",
                "createdAt": "2025-03-01T10:00:00Z",
            },
        },
    )
    text = await _call_raw("get_application", {"applicationId": "a1", "expand": ["openings"]})
    assert "## Priya Raman (`a1`)" in text
    assert "- **email**: priya@example.com" in text
    assert '- **openings**: {"id":"op1","openingState":"Open"}' in text
    assert "203.0.113.5" not in text

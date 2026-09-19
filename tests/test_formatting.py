"""Tests for the markdown formatter.

Two layers:
1. Pure tests of `formatting.format_list` / `format_record` / `get_value`
   and the `Derived` accessor factories.
2. End-to-end tests that run the dispatcher in markdown mode and assert
   on the rendered output. Every fixture below follows the response
   shapes in `openapi.json` (see `tests/test_spec_alignment.py` for the
   check that the field maps do too) — so these prove the per-tool
   column configs line up with what Ashby actually returns, not with an
   invented shape that happens to match the map.
"""

import json

import pytest

from ashby.formatting import (
    WIDE,
    accessor_paths,
    custom_fields,
    fmt,
    format_list,
    format_record,
    get_value,
    items_of,
    select_options,
    social_link,
    table,
    titles_of,
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
    obj = {"socialLinks": [{"type": "LinkedIn", "url": "li"}, {"type": "GitHub", "url": "gh"}]}
    assert get_value(obj, "socialLinks.0.url") == "li"
    assert get_value(obj, "socialLinks.1.url") == "gh"
    assert get_value(obj, "socialLinks.5.url") == "—"


def test_get_value_callable():
    obj = {"city": "SF", "country": "US"}
    assert get_value(obj, lambda r: f"{r['city']}, {r['country']}") == "SF, US"


def test_get_value_defaults_for_empty():
    assert get_value({"a": None}, "a") == "—"
    assert get_value({"a": ""}, "a") == "—"
    assert get_value(None, "a") == "—"


def test_social_link_picks_matching_type():
    cand = {"socialLinks": [{"type": "GitHub", "url": "gh"}, {"type": "LinkedIn", "url": "li"}]}
    assert get_value(cand, social_link("LinkedIn")) == "li"
    assert get_value(cand, social_link("Twitter")) == "—"
    assert get_value({"socialLinks": []}, social_link("LinkedIn")) == "—"
    assert get_value({}, social_link("LinkedIn")) == "—"
    # The declared paths are what the spec-alignment test validates.
    assert accessor_paths(social_link("LinkedIn")) == ("socialLinks.0.type", "socialLinks.0.url")


def test_titles_of_maps_objects_to_titles():
    cand = {"tags": [{"id": "t1", "title": "referral", "isArchived": False},
                     {"id": "t2", "title": "ex-google", "isArchived": False}]}
    assert get_value(cand, titles_of("tags")) == ["referral", "ex-google"]
    assert accessor_paths(titles_of("tags")) == ("tags.0.title",)


def test_custom_fields_render_title_value_pairs():
    rec = {"customFields": [
        {"id": "1", "title": "Willing to relocate", "value": True},
        {"id": "2", "title": "Skills", "value": ["python", "rust"]},
        {"id": "3", "title": "Band", "value": {"type": "number-range", "minValue": 1, "maxValue": 2}},
        {"id": "4", "title": "Referred by", "value": "Ada"},
    ]}
    assert get_value(rec, custom_fields()) == [
        "Willing to relocate: yes",
        'Skills: ["python","rust"]',
        'Band: {"type":"number-range","minValue":1,"maxValue":2}',
        "Referred by: Ada",
    ]


def test_items_of_and_fmt_templates():
    rec = {
        "author": {"firstName": "Hana", "lastName": "Moreno"},
        "hiringTeam": [{"firstName": "Hal", "lastName": "M", "role": "Hiring Manager"}],
        "referrals": [{"user": {"firstName": "R", "lastName": "C", "email": "r@x"}, "referredAt": "2026-01-01"}],
    }
    assert get_value(rec, fmt("{author.firstName} {author.lastName}")) == "Hana Moreno"
    assert get_value(rec, items_of("hiringTeam", "{firstName} {lastName} ({role})")) == ["Hal M (Hiring Manager)"]
    nested = items_of("referrals", "{user.firstName} {user.lastName} ({user.email}) @ {referredAt}")
    assert get_value(rec, nested) == ["R C (r@x) @ 2026-01-01"]
    assert accessor_paths(nested) == (
        "referrals.0.user.firstName", "referrals.0.user.lastName",
        "referrals.0.user.email", "referrals.0.referredAt",
    )
    # Nothing resolvable → the standard empty marker, not "— —".
    assert get_value({}, fmt("{author.firstName} {author.lastName}")) == "—"


def test_select_options_shows_value_when_it_differs_from_label():
    field = {"selectableValues": [
        {"label": "Employee", "value": "employee", "isArchived": False},
        {"label": "Agency", "value": "Agency", "isArchived": True},
    ]}
    assert get_value(field, select_options()) == ["Employee (employee)", "Agency [archived]"]


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


def test_table_escapes_pipes_inside_lists():
    out = table([{"tags": ["a|b", "c"]}], [("tags", "tags")])
    assert r"a\|b, c" in out


def test_table_column_can_widen_its_cell_budget():
    rows = [{"values": [f"option-{i}" for i in range(10)]}]
    narrow = table(rows, [("values", "values")])
    wide = table(rows, [("values", "values", WIDE)])
    assert "option-9" not in narrow and "…" in narrow
    assert "option-9" in wide and "…" not in wide


def test_cell_renders_dicts_as_compact_json_not_python_repr():
    out = table([{"v": {"type": "number-range", "minValue": 1}}], [("v", "v")])
    assert '{"type":"number-range","minValue":1}' in out
    assert "'type'" not in out


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
    assert "Other fields" not in out  # everything was covered


def test_format_record_appends_uncovered_keys_as_json():
    """Keys the field map doesn't read (e.g. `expand` sub-objects) are not
    silently dropped — they are appended verbatim as compact JSON."""
    record = {
        "id": "a1",
        "candidate": {"name": "Ada"},
        "status": "Active",
        "applicationFormSubmissions": [{"id": "fs1", "submittedValues": {"why": "Love it"}}],
        "emptyList": [],
        "nothing": None,
    }
    out = format_record(record, "candidate.name", [("status", "status")])
    assert "- **status**: Active" in out
    assert "Other fields (raw JSON):" in out
    tail = out.split("```json\n", 1)[1].split("\n```")[0]
    assert json.loads(tail) == {
        "applicationFormSubmissions": [{"id": "fs1", "submittedValues": {"why": "Love it"}}]
    }
    # Empty values and keys read by the map (candidate, status, id) are not repeated.
    assert "emptyList" not in out and "nothing" not in out


def test_format_record_omit_drops_keys_from_tail():
    record = {"id": "iv1", "title": "Screen", "instructionsPlain": "Ask.", "instructionsHtml": "<p>Ask.</p>"}
    out = format_record(record, "title", [("instructions", "instructionsPlain")], omit=("instructionsHtml",))
    assert "instructionsHtml" not in out
    assert "Other fields" not in out


# ---------------------------------------------------------------------------
# End-to-end tests — dispatcher in markdown mode, spec-shaped payloads
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


def _candidate(cid: str, name: str, email: str, **extra) -> dict:
    """A Candidate as /candidate.list and /candidate.info return it."""
    return {
        "id": cid,
        "name": name,
        "createdAt": "2024-12-01T10:00:00Z",
        "updatedAt": "2024-12-02T10:00:00Z",
        "primaryEmailAddress": {"value": email, "type": "Personal", "isPrimary": True},
        "emailAddresses": [{"value": email, "type": "Personal", "isPrimary": True}],
        "primaryPhoneNumber": {"value": "555-0100", "type": "Personal", "isPrimary": True},
        "phoneNumbers": [{"value": "555-0100", "type": "Personal", "isPrimary": True}],
        "socialLinks": [{"type": "GitHub", "url": f"https://github.com/{cid}"},
                        {"type": "LinkedIn", "url": f"https://linkedin.com/in/{cid}"}],
        "tags": [],
        "applicationIds": [],
        "fileHandles": [],
        "customFields": [],
        "profileUrl": f"https://app.ashbyhq.com/candidates/{cid}",
        "source": {"id": "s1", "title": "LinkedIn", "isArchived": False},
        "primaryLocation": {"id": "pl1", "locationSummary": "London, United Kingdom",
                            "locationComponents": [{"type": "City", "name": "London"}]},
        **extra,
    }


async def test_list_candidates_renders_table(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.list",
        json={
            "success": True,
            "results": [
                _candidate("c1", "Ada Lovelace", "ada@example.com",
                           position="Staff Engineer", company="Analytical Engines", school="Cambridge"),
                _candidate("c2", "Alan Turing", "alan@example.com",
                           source={"id": "s2", "title": "Referral", "isArchived": False}),
            ],
            "moreDataAvailable": False,
        },
    )
    text = await _call_raw("list_candidates", {"limit": 2})
    assert "## Candidates (2)" in text
    assert "| id | name | position | company | school | linkedin | email | location | source | created |" in text
    assert ("| c1 | Ada Lovelace | Staff Engineer | Analytical Engines | Cambridge | "
            "https://linkedin.com/in/c1 | ada@example.com | London, United Kingdom | LinkedIn |") in text
    assert "| c2 | Alan Turing | — | — | — | https://linkedin.com/in/c2 | alan@example.com | London, United Kingdom | Referral |" in text
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
                 "sourceType": {"id": "st1", "title": "Job Board", "isArchived": False}},
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
            "results": _candidate(
                "c1", "Ada Lovelace", "ada@example.com",
                tags=[{"id": "t1", "title": "referral", "isArchived": False},
                      {"id": "t2", "title": "ex-google", "isArchived": False}],
                applicationIds=["a_01", "a_02"],
                customFields=[{"id": "cf1", "title": "Willing to relocate", "value": True},
                              {"id": "cf2", "title": "Skills", "value": ["python", "rust"]}],
                resumeFileHandle={"id": "f1", "name": "ada.pdf", "handle": "h1"},
                timezone="Europe/London",
            ),
        },
    )
    text = await _call_raw("get_candidate", {"id": "c1"})
    assert text.startswith("Candidate: ")
    assert "## Ada Lovelace (`c1`)" in text
    assert "- **linkedin**: https://linkedin.com/in/c1" in text
    assert "- **links**: GitHub: https://github.com/c1, LinkedIn: https://linkedin.com/in/c1" in text
    assert "- **email**: ada@example.com" in text
    assert "- **phone**: 555-0100" in text
    assert "- **location**: London, United Kingdom" in text
    assert "- **source**: LinkedIn" in text
    assert "- **tags**: referral, ex-google" in text  # titles, not dict reprs
    assert "- **applications**: a_01, a_02" in text
    assert '- **custom_fields**: Willing to relocate: yes, Skills: ["python","rust"]' in text
    assert "- **resume_name**: ada.pdf" in text
    assert "'title'" not in text  # no Python dict reprs anywhere
    assert "Other fields" not in text  # the map covers the whole Candidate object


def _application(aid: str, **extra) -> dict:
    """An Application as /application.list and /application.info return it."""
    return {
        "id": aid,
        "createdAt": "2025-03-01T10:00:00.000Z",
        "updatedAt": "2025-04-01T10:00:00.000Z",
        "status": "Archived",
        "customFields": [],
        "candidate": {
            "id": "c_sales_01", "name": "Priya Raman",
            "primaryEmailAddress": {"value": "priya@example.com", "type": "Personal", "isPrimary": True},
            "primaryPhoneNumber": {"value": "+1-555-0100", "type": "Personal", "isPrimary": True},
        },
        "currentInterviewStage": {"id": "is_archived", "title": "Archived", "type": "Archived",
                                  "orderInInterviewPlan": 99, "interviewPlanId": "ip_1"},
        "source": {"id": "s1", "title": "LinkedIn", "isArchived": False},
        "archiveReason": {"id": "ar_timing", "text": "Timing (not right now)",
                          "reasonType": "RejectedByCandidate", "isArchived": False},
        "archivedAt": "2025-04-01T10:00:00.000Z",
        "job": {"id": "j_sales_ae_closed", "title": "Account Executive",
                "locationId": "loc_nyc", "departmentId": "d_sales"},
        "creditedToUser": {"id": "u1", "firstName": "Rae", "lastName": "Cole", "email": "rae@example.com",
                           "globalRole": "Limited Access", "isEnabled": True, "updatedAt": "2025-01-01T00:00:00Z"},
        "hiringTeam": [{"email": "hm@example.com", "firstName": "Hana", "lastName": "Moreno",
                        "role": "Hiring Manager", "userId": "u2"}],
        **extra,
    }


async def test_list_applications_renders_real_values(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/application.list",
        json={"success": True, "results": [_application("a_01")], "moreDataAvailable": False},
    )
    text = await _call_raw("list_applications", {"status": "Archived"})
    assert "## Applications (1)" in text
    assert ("| id | candidate_id | candidate | email | job | job_id | stage | status | "
            "archive_reason | archived_at | source | created | openings |") in text
    assert ("| a_01 | c_sales_01 | Priya Raman | priya@example.com | Account Executive | j_sales_ae_closed | "
            "Archived | Archived | Timing (not right now) | 2025-04-01T10:00:00.000Z | LinkedIn | "
            "2025-03-01T10:00:00.000Z | — |") in text


async def test_get_application_renders_archive_team_custom_fields_and_expansions(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/application.info",
        json={"success": True, "results": _application(
            "a_01",
            customFields=[{"id": "cf1", "title": "Offer Amount",
                           "value": {"type": "number-range", "minValue": 180000, "maxValue": 220000}}],
            applicationHistory=[{"id": "h1", "stageId": "is_lead", "title": "Lead",
                                 "enteredStageAt": "2025-03-01T10:00:00.000Z", "stageNumber": 0, "allowedActions": []}],
            openings=[{"id": "op1", "openingState": "Open", "isArchived": False}],
            referrals=[{"user": {"id": "u3", "firstName": "Ref", "lastName": "Errer", "email": "ref@example.com",
                                 "globalRole": "Limited Access", "isEnabled": True, "updatedAt": "x"},
                        "referredAt": "2025-02-01T00:00:00Z"}],
            applicationFormSubmissions=[{"id": "fs1", "formDefinition": {"sections": []},
                                         "submittedValues": {"why": "Love the product"}}],
        )},
    )
    text = await _call_raw("get_application", {"applicationId": "a_01", "expand": ["openings", "referrals", "applicationFormSubmissions"]})
    assert "## Priya Raman (`a_01`)" in text
    assert "- **email**: priya@example.com" in text
    assert "- **job**: Account Executive" in text
    assert "- **archive_reason**: Timing (not right now)" in text
    assert "- **archived_at**: 2025-04-01T10:00:00.000Z" in text
    assert "- **credited_to**: rae@example.com" in text
    assert "- **hiring_team**: Hana Moreno (Hiring Manager)" in text
    assert '- **custom_fields**: Offer Amount: {"type":"number-range","minValue":180000,"maxValue":220000}' in text
    assert "- **history**: Lead @ 2025-03-01T10:00:00.000Z" in text
    assert "- **openings**: op1 (Open)" in text
    assert "- **referrals**: Ref Errer (ref@example.com) @ 2025-02-01T00:00:00Z" in text
    # Free-form form submissions are not flattened, but they are not lost either.
    assert "Other fields (raw JSON):" in text
    assert '"applicationFormSubmissions":[{"id":"fs1"' in text
    assert '"why":"Love the product"' in text


async def test_list_candidate_notes_renders_content_and_author(httpx_mock, markdown_mode):
    long_note = "Strong discovery skills; closed $2M pipeline at Segment. " * 3
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.listNotes",
        json={"success": True, "moreDataAvailable": False, "results": [
            {"id": "n1", "createdAt": "2025-01-01T00:00:00Z", "content": long_note,
             "author": {"id": "u1", "firstName": "Hana", "lastName": "Moreno", "email": "hm@example.com"}},
        ]},
    )
    text = await _call_raw("list_candidate_notes", {"candidateId": "c1"})
    assert "| id | createdAt | author | author_name | note |" in text
    assert "| n1 | 2025-01-01T00:00:00Z | hm@example.com | Hana Moreno | " in text
    # Note text is the point of this tool — it must not be cut at 60 chars.
    assert long_note.strip() in text


def _job(jid: str, title: str, **extra) -> dict:
    return {
        "id": jid, "title": title, "confidential": False, "status": "Open", "employmentType": "FullTime",
        "locationId": "loc_sf", "departmentId": "d_eng", "defaultInterviewPlanId": "ip_1",
        "interviewPlanIds": ["ip_1"], "customFields": [], "jobPostingIds": [], "hiringTeam": [],
        "createdAt": "2025-01-01T00:00:00Z", "updatedAt": "2025-02-01T00:00:00Z",
        **extra,
    }


async def test_list_jobs_renders_expanded_location_and_ids(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/job.list",
        json={"success": True, "moreDataAvailable": False, "results": [
            _job("j1", "Senior Software Engineer",
                 location={"id": "loc_sf", "name": "San Francisco", "isArchived": False,
                           "isRemote": False, "workplaceType": "Hybrid", "type": "Location"}),
            _job("j2", "Unexpanded Role"),
        ]},
    )
    text = await _call_raw("list_jobs", {})
    # The handler asks Ashby to expand `location` by default.
    assert json.loads(httpx_mock.get_request().content) == {"status": ["Open"], "expand": ["location"]}
    assert "| id | title | status | location | location_id | department_id | employment | openings | updated |" in text
    assert "| j1 | Senior Software Engineer | Open | San Francisco | loc_sf | d_eng | FullTime | — | 2025-02-01T00:00:00Z |" in text
    assert "| j2 | Unexpanded Role | Open | — | loc_sf | d_eng | FullTime | — |" in text


async def test_get_job_renders_expanded_location_and_openings(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/job.info",
        json={"success": True, "results": _job(
            "j1", "Senior Software Engineer",
            location={"id": "loc_sf", "name": "San Francisco", "isArchived": False},
            openings=[{"id": "op1", "openingState": "Open", "isArchived": False,
                       "latestVersion": {"id": "v1", "identifier": "ENG-42"}}],
            hiringTeam=[{"email": "hm@example.com", "firstName": "Hana", "lastName": "Moreno",
                         "role": "Hiring Manager", "userId": "u2"}],
            compensation={"compensationTiers": []},
        )},
    )
    text = await _call_raw("get_job", {"id": "j1", "expand": ["location", "openings"]})
    assert json.loads(httpx_mock.get_request().content) == {"id": "j1", "expand": ["location", "openings"]}
    assert "## Senior Software Engineer (`j1`)" in text
    assert "- **location**: San Francisco" in text
    assert "- **location_id**: loc_sf" in text
    assert "- **department_id**: d_eng" in text
    assert "- **hiring_team**: Hana Moreno (Hiring Manager)" in text
    assert "- **openings**: op1 ENG-42 (Open)" in text
    # Small leftovers land in the JSON tail rather than vanishing.
    assert '"interviewPlanIds":["ip_1"]' in text


async def test_list_custom_fields_renders_selectable_values(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/customField.list",
        json={"success": True, "moreDataAvailable": False, "results": [
            {"id": "cf1", "title": "Referral Source", "objectType": "Candidate", "isArchived": False,
             "fieldType": "ValueSelect",
             "selectableValues": [{"label": f"Option {i}", "value": f"opt_{i}", "isArchived": False}
                                  for i in range(8)]},
            {"id": "cf2", "title": "Offer Amount", "objectType": "Application", "isArchived": False,
             "fieldType": "Number"},
        ]},
    )
    text = await _call_raw("list_custom_fields", {})
    assert "| id | title | type | object | archived | values |" in text
    # All eight options are visible (WIDE budget), with the API value alongside the label.
    assert "Option 0 (opt_0)" in text and "Option 7 (opt_7)" in text
    assert "| cf2 | Offer Amount | Number | Application | no | — |" in text


async def test_get_custom_field_renders_selectable_values(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/customField.info",
        json={"success": True, "results": {
            "id": "cf1", "title": "Referral Source", "objectType": "Candidate", "isArchived": False,
            "isPrivate": False, "fieldType": "ValueSelect",
            "selectableValues": [{"label": "Employee", "value": "Employee", "isArchived": False},
                                 {"label": "Agency", "value": "Agency", "isArchived": False}],
        }},
    )
    text = await _call_raw("get_custom_field", {"customFieldId": "cf1"})
    assert "## Referral Source (`cf1`)" in text
    assert "- **type**: ValueSelect" in text
    assert "- **values**: Employee, Agency" in text


async def test_list_interview_schedules_and_events(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/interviewSchedule.list",
        json={"success": True, "moreDataAvailable": False, "results": [
            {"id": "sch1", "status": "Scheduled", "applicationId": "a_01", "interviewStageId": "is_onsite",
             "interviewEvents": [{"id": "ev1", "interviewId": "iv1", "interviewScheduleId": "sch1",
                                  "interviewerUserIds": ["u1"], "createdAt": "2026-04-01T00:00:00Z",
                                  "startTime": "2026-05-01T15:00:00Z", "endTime": "2026-05-01T16:00:00Z",
                                  "feedbackLink": "https://x", "hasSubmittedFeedback": False}]},
        ]},
    )
    text = await _call_raw("list_interview_schedules", {"applicationId": "a_01"})
    assert "| sch1 | a_01 | is_onsite | Scheduled | 1 | 2026-05-01T15:00:00Z |" in text

    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/interviewEvent.list",
        json={"success": True, "results": [
            {"id": "ev1", "interviewId": "iv1", "interviewScheduleId": "sch1", "interviewerUserIds": ["u1", "u2"],
             "createdAt": "2026-04-01T00:00:00Z", "startTime": "2026-05-01T15:00:00Z",
             "endTime": "2026-05-01T16:00:00Z", "feedbackLink": "https://x", "hasSubmittedFeedback": True,
             "meetingLink": "https://meet/1", "location": "Room 4",
             "interview": {"id": "iv1", "title": "Tech Screen", "isArchived": False, "feedbackFormDefinitionId": "ff1"}},
        ]},
    )
    text = await _call_raw("list_interview_events", {"interviewScheduleId": "sch1", "expand": ["interview"]})
    assert "| ev1 | Tech Screen | iv1 | 2026-05-01T15:00:00Z | 2026-05-01T16:00:00Z | u1, u2 | yes | https://meet/1 | Room 4 |" in text


async def test_list_interview_stage_groups_uses_order_and_stage_type(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/interviewStageGroup.list",
        json={"success": True, "results": [{"id": "g1", "title": "Onsite", "order": 2, "stageType": "Active"}]},
    )
    text = await _call_raw("list_interview_stage_groups", {"interviewPlanId": "ip_1"})
    assert "| g1 | Onsite | 2 | Active |" in text


async def test_get_project_renders_spec_fields(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/project.info",
        json={"success": True, "results": {
            "id": "p1", "title": "BizOps", "description": "Ops hires", "isArchived": False,
            "confidential": True, "authorId": "u1", "createdAt": "2025-01-01T00:00:00Z",
            "customFieldEntries": [{"id": "x", "title": "Region", "value": "EMEA"}],
        }},
    )
    text = await _call_raw("get_project", {"projectId": "p1"})
    assert "## BizOps (`p1`)" in text
    assert "- **description**: Ops hires" in text
    assert "- **confidential**: yes" in text
    assert "- **custom_fields**: Region: EMEA" in text


async def test_get_interview_omits_html_duplicate(httpx_mock, markdown_mode):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/interview.info",
        json={"success": True, "results": {
            "id": "iv1", "title": "Tech Screen", "isArchived": False, "isDebrief": False, "jobId": "j1",
            "feedbackFormDefinitionId": "ff1", "instructionsPlain": "Ask about systems.",
            "instructionsHtml": "<p>Ask about systems.</p>",
        }},
    )
    text = await _call_raw("get_interview", {"id": "iv1"})
    assert "- **instructions**: Ask about systems." in text
    assert "- **feedback_form_id**: ff1" in text
    assert "<p>" not in text and "Other fields" not in text


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

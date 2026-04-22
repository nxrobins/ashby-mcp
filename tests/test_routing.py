"""Unit tests — verify every MCP tool dispatches to the correct Ashby
endpoint and forwards its arguments faithfully.

No network calls are made. `pytest-httpx` intercepts every outbound HTTP
request. Each test asserts:
  1. the correct URL was hit,
  2. the JSON body matches what the caller passed in (or the expected
     transformation, for the few tools that mutate the payload).
"""

import json

import pytest

BASE = "https://api.ashbyhq.com"


def _ok(httpx_mock, endpoint: str, body: dict | None = None, json_body: dict | None = None):
    """Register a happy-path POST mock."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}{endpoint}",
        json=json_body or {"success": True, "results": body or {}},
    )


def _sent_body(httpx_mock) -> dict:
    """Decode the JSON body that was sent to the registered mock."""
    return json.loads(httpx_mock.get_request().content)


# ---------------------------------------------------------------------------
# Candidate tools
# ---------------------------------------------------------------------------


async def test_create_candidate_uses_camelcase(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.create")
    args = {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phoneNumber": "555-0100",
        "linkedInUrl": "https://linkedin.com/in/ada",
    }
    await call_tool("create_candidate", args)
    assert _sent_body(httpx_mock) == args


async def test_search_candidates(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.search")
    await call_tool("search_candidates", {"name": "Ada"})
    assert _sent_body(httpx_mock) == {"name": "Ada"}


async def test_list_candidates_uses_cursor_pagination(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.list")
    await call_tool("list_candidates", {"limit": 25, "cursor": "abc"})
    assert _sent_body(httpx_mock) == {"limit": 25, "cursor": "abc"}


async def test_get_candidate(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.info")
    await call_tool("get_candidate", {"id": "cand-123"})
    assert _sent_body(httpx_mock) == {"id": "cand-123"}


async def test_update_candidate(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.update")
    args = {"candidateId": "cand-123", "email": "new@example.com"}
    await call_tool("update_candidate", args)
    assert _sent_body(httpx_mock) == args


async def test_add_candidate_tag(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.addTag")
    await call_tool("add_candidate_tag", {"candidateId": "c1", "tagId": "t1"})
    assert _sent_body(httpx_mock) == {"candidateId": "c1", "tagId": "t1"}


async def test_list_candidate_tags(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidateTag.list")
    await call_tool("list_candidate_tags", {"includeArchived": True})
    assert _sent_body(httpx_mock) == {"includeArchived": True}


async def test_add_candidate_to_project(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.addProject")
    await call_tool("add_candidate_to_project", {"candidateId": "c1", "projectId": "p1"})
    assert _sent_body(httpx_mock) == {"candidateId": "c1", "projectId": "p1"}


async def test_create_candidate_note(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.createNote")
    await call_tool("create_candidate_note", {"candidateId": "c1", "note": "hello"})
    assert _sent_body(httpx_mock) == {"candidateId": "c1", "note": "hello"}


async def test_list_candidate_notes(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.listNotes")
    await call_tool("list_candidate_notes", {"candidateId": "c1"})
    assert _sent_body(httpx_mock) == {"candidateId": "c1"}


async def test_list_candidate_client_info(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.listClientInfo")
    await call_tool("list_candidate_client_info", {"candidateId": "c1"})
    assert _sent_body(httpx_mock) == {"candidateId": "c1"}


async def test_anonymize_candidate(httpx_mock, call_tool):
    _ok(httpx_mock, "/candidate.anonymize")
    await call_tool("anonymize_candidate", {"candidateId": "c1"})
    assert _sent_body(httpx_mock) == {"candidateId": "c1"}


# ---------------------------------------------------------------------------
# File upload tools — multipart/form-data
# ---------------------------------------------------------------------------


async def test_upload_candidate_resume(httpx_mock, call_tool, tmp_path):
    _ok(httpx_mock, "/candidate.uploadResume")
    f = tmp_path / "resume.pdf"
    f.write_bytes(b"%PDF-1.4 dummy")
    await call_tool("upload_candidate_resume", {"candidateId": "c1", "file_path": str(f)})
    req = httpx_mock.get_request()
    # Multipart body carries both the candidateId form field and the resume part.
    assert b'name="candidateId"' in req.content
    assert b"c1" in req.content
    assert b'name="resume"' in req.content
    assert b"%PDF-1.4 dummy" in req.content
    # Crucial: no JSON content-type leaked from the default client headers.
    assert req.headers["content-type"].startswith("multipart/form-data")


async def test_upload_candidate_file(httpx_mock, call_tool, tmp_path):
    _ok(httpx_mock, "/candidate.uploadFile")
    f = tmp_path / "doc.txt"
    f.write_bytes(b"hello")
    await call_tool("upload_candidate_file", {"candidateId": "c1", "file_path": str(f)})
    req = httpx_mock.get_request()
    assert b'name="file"' in req.content
    assert b"hello" in req.content


# ---------------------------------------------------------------------------
# Project tools
# ---------------------------------------------------------------------------


async def test_get_project(httpx_mock, call_tool):
    _ok(httpx_mock, "/project.info")
    await call_tool("get_project", {"projectId": "p1"})
    assert _sent_body(httpx_mock) == {"projectId": "p1"}


async def test_list_projects(httpx_mock, call_tool):
    _ok(httpx_mock, "/project.list")
    await call_tool("list_projects", {"limit": 10})
    assert _sent_body(httpx_mock) == {"limit": 10}


async def test_search_projects(httpx_mock, call_tool):
    _ok(httpx_mock, "/project.search")
    await call_tool("search_projects", {"title": "BizOps"})
    assert _sent_body(httpx_mock) == {"title": "BizOps"}


# ---------------------------------------------------------------------------
# Custom field tools
# ---------------------------------------------------------------------------


async def test_list_custom_fields_strips_client_side_filter(httpx_mock, call_tool):
    """objectType is a client-side filter and must NOT be sent to Ashby."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/customField.list",
        json={
            "success": True,
            "results": [
                {"id": "f1", "objectType": "Candidate", "title": "Referred By"},
                {"id": "f2", "objectType": "Application", "title": "Offer Amount"},
                {"id": "f3", "objectType": "Candidate", "title": "Source Detail"},
            ],
        },
    )
    result = await call_tool("list_custom_fields", {"objectType": "Candidate", "limit": 100})
    # objectType is applied locally
    assert "objectType" not in _sent_body(httpx_mock)
    assert _sent_body(httpx_mock) == {"limit": 100}
    # The response is filtered to just Candidate fields.
    assert [r["id"] for r in result["results"]] == ["f1", "f3"]


async def test_list_custom_fields_no_filter_passes_all(httpx_mock, call_tool):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/customField.list",
        json={
            "success": True,
            "results": [
                {"id": "f1", "objectType": "Candidate"},
                {"id": "f2", "objectType": "Job"},
            ],
        },
    )
    result = await call_tool("list_custom_fields", {})
    assert _sent_body(httpx_mock) == {}
    assert len(result["results"]) == 2


async def test_get_custom_field(httpx_mock, call_tool):
    _ok(httpx_mock, "/customField.info")
    await call_tool("get_custom_field", {"customFieldId": "cf-1"})
    assert _sent_body(httpx_mock) == {"customFieldId": "cf-1"}


async def test_create_custom_field(httpx_mock, call_tool):
    _ok(httpx_mock, "/customField.create")
    args = {"title": "Referral Source", "fieldType": "String", "objectType": "Candidate"}
    await call_tool("create_custom_field", args)
    assert _sent_body(httpx_mock) == args


async def test_set_custom_field_value_string(httpx_mock, call_tool):
    _ok(httpx_mock, "/customField.setValue")
    args = {"objectId": "c1", "objectType": "Candidate", "fieldId": "f1", "fieldValue": "Alice"}
    await call_tool("set_custom_field_value", args)
    assert _sent_body(httpx_mock) == args


async def test_set_custom_field_value_number_range(httpx_mock, call_tool):
    _ok(httpx_mock, "/customField.setValue")
    args = {
        "objectId": "j1",
        "objectType": "Job",
        "fieldId": "f-salary",
        "fieldValue": {"type": "number-range", "minValue": 100000, "maxValue": 150000},
    }
    await call_tool("set_custom_field_value", args)
    assert _sent_body(httpx_mock) == args


# ---------------------------------------------------------------------------
# Job tools
# ---------------------------------------------------------------------------


async def test_create_job_uses_camelcase(httpx_mock, call_tool):
    _ok(httpx_mock, "/job.create")
    args = {"title": "SWE", "teamId": "t1", "locationId": "l1"}
    await call_tool("create_job", args)
    assert _sent_body(httpx_mock) == args


async def test_search_jobs(httpx_mock, call_tool):
    _ok(httpx_mock, "/job.search")
    await call_tool("search_jobs", {"title": "Engineer"})
    assert _sent_body(httpx_mock) == {"title": "Engineer"}


async def test_list_jobs_defaults_status_to_open(httpx_mock, call_tool):
    """The handler injects status=['Open'] when the caller omits it."""
    _ok(httpx_mock, "/job.list")
    await call_tool("list_jobs", {})
    assert _sent_body(httpx_mock) == {"status": ["Open"]}


async def test_list_jobs_respects_explicit_status(httpx_mock, call_tool):
    _ok(httpx_mock, "/job.list")
    await call_tool("list_jobs", {"status": ["Closed", "Archived"]})
    assert _sent_body(httpx_mock) == {"status": ["Closed", "Archived"]}


async def test_get_job(httpx_mock, call_tool):
    _ok(httpx_mock, "/job.info")
    await call_tool("get_job", {"id": "j1"})
    assert _sent_body(httpx_mock) == {"id": "j1"}


async def test_update_job(httpx_mock, call_tool):
    _ok(httpx_mock, "/job.update")
    await call_tool("update_job", {"jobId": "j1", "title": "New title"})
    assert _sent_body(httpx_mock) == {"jobId": "j1", "title": "New title"}


async def test_set_job_status(httpx_mock, call_tool):
    _ok(httpx_mock, "/job.setStatus")
    await call_tool("set_job_status", {"jobId": "j1", "status": "Closed"})
    assert _sent_body(httpx_mock) == {"jobId": "j1", "status": "Closed"}


# ---------------------------------------------------------------------------
# Application tools
# ---------------------------------------------------------------------------


async def test_create_application_uses_camelcase(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.create")
    args = {"candidateId": "c1", "jobId": "j1", "sourceId": "s1"}
    await call_tool("create_application", args)
    assert _sent_body(httpx_mock) == args


async def test_list_applications_cursor_pagination(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.list")
    await call_tool("list_applications", {"status": "Active", "limit": 50})
    assert _sent_body(httpx_mock) == {"status": "Active", "limit": 50}


async def test_get_application(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.info")
    await call_tool("get_application", {"applicationId": "a1", "expand": ["openings"]})
    assert _sent_body(httpx_mock) == {"applicationId": "a1", "expand": ["openings"]}


async def test_update_application(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.update")
    await call_tool("update_application", {"applicationId": "a1", "sourceId": "s2"})
    assert _sent_body(httpx_mock) == {"applicationId": "a1", "sourceId": "s2"}


async def test_change_application_stage(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.change_stage")
    await call_tool("change_application_stage", {"applicationId": "a1", "interviewStageId": "st1"})
    assert _sent_body(httpx_mock) == {"applicationId": "a1", "interviewStageId": "st1"}


async def test_change_application_source(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.change_source")
    await call_tool("change_application_source", {"applicationId": "a1", "sourceId": "s1"})
    assert _sent_body(httpx_mock) == {"applicationId": "a1", "sourceId": "s1"}


async def test_transfer_application(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.transfer")
    await call_tool("transfer_application", {"applicationId": "a1", "jobId": "j2"})
    assert _sent_body(httpx_mock) == {"applicationId": "a1", "jobId": "j2"}


async def test_add_application_hiring_team_member(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.addHiringTeamMember")
    args = {"applicationId": "a1", "teamMemberId": "u1", "roleId": "r1"}
    await call_tool("add_application_hiring_team_member", args)
    assert _sent_body(httpx_mock) == args


async def test_remove_application_hiring_team_member(httpx_mock, call_tool):
    _ok(httpx_mock, "/application.removeHiringTeamMember")
    args = {"applicationId": "a1", "teamMemberId": "u1", "roleId": "r1"}
    await call_tool("remove_application_hiring_team_member", args)
    assert _sent_body(httpx_mock) == args


# ---------------------------------------------------------------------------
# Interview tools
# ---------------------------------------------------------------------------


async def test_get_interview(httpx_mock, call_tool):
    _ok(httpx_mock, "/interview.info")
    await call_tool("get_interview", {"id": "iv1"})
    assert _sent_body(httpx_mock) == {"id": "iv1"}


async def test_list_interviews(httpx_mock, call_tool):
    _ok(httpx_mock, "/interview.list")
    await call_tool("list_interviews", {"includeArchived": False})
    assert _sent_body(httpx_mock) == {"includeArchived": False}


async def test_create_interview_schedule(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewSchedule.create")
    args = {
        "applicationId": "a1",
        "interviewEvents": [
            {
                "startTime": "2026-05-01T15:00:00.000Z",
                "endTime": "2026-05-01T16:00:00.000Z",
                "interviewers": [{"email": "bob@example.com"}],
            }
        ],
    }
    await call_tool("create_interview_schedule", args)
    assert _sent_body(httpx_mock) == args


async def test_list_interview_schedules(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewSchedule.list")
    await call_tool("list_interview_schedules", {"applicationId": "a1"})
    assert _sent_body(httpx_mock) == {"applicationId": "a1"}


async def test_update_interview_schedule(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewSchedule.update")
    args = {
        "interviewScheduleId": "sch-1",
        "interviewEvent": {
            "interviewEventId": "ev-1",
            "startTime": "2026-05-01T17:00:00.000Z",
            "endTime": "2026-05-01T18:00:00.000Z",
            "interviewers": [{"email": "bob@example.com"}],
        },
    }
    await call_tool("update_interview_schedule", args)
    assert _sent_body(httpx_mock) == args


async def test_cancel_interview_schedule(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewSchedule.cancel")
    await call_tool("cancel_interview_schedule", {"id": "sch-1", "allowReschedule": True})
    assert _sent_body(httpx_mock) == {"id": "sch-1", "allowReschedule": True}


async def test_list_interview_events(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewEvent.list")
    await call_tool("list_interview_events", {"interviewScheduleId": "sch-1", "expand": ["interview"]})
    assert _sent_body(httpx_mock) == {"interviewScheduleId": "sch-1", "expand": ["interview"]}


async def test_list_interview_plans(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewPlan.list")
    await call_tool("list_interview_plans", {"includeArchived": True})
    assert _sent_body(httpx_mock) == {"includeArchived": True}


async def test_list_interview_stages(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewStage.list")
    await call_tool("list_interview_stages", {"interviewPlanId": "plan-1"})
    assert _sent_body(httpx_mock) == {"interviewPlanId": "plan-1"}


async def test_get_interview_stage(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewStage.info")
    await call_tool("get_interview_stage", {"interviewStageId": "st-1"})
    assert _sent_body(httpx_mock) == {"interviewStageId": "st-1"}


async def test_list_interview_stage_groups(httpx_mock, call_tool):
    _ok(httpx_mock, "/interviewStageGroup.list")
    await call_tool("list_interview_stage_groups", {"interviewPlanId": "plan-1"})
    assert _sent_body(httpx_mock) == {"interviewPlanId": "plan-1"}


# ---------------------------------------------------------------------------
# New tools: list_sources, list_all_candidates
# ---------------------------------------------------------------------------


async def test_list_sources_default(httpx_mock, call_tool):
    _ok(httpx_mock, "/source.list", json_body={"success": True, "results": [
        {"id": "s1", "title": "LinkedIn", "isArchived": False, "sourceType": {"id": "st1", "title": "Job Board", "isArchived": False}},
    ]})
    await call_tool("list_sources", {})
    assert _sent_body(httpx_mock) == {"includeArchived": False}


async def test_list_sources_include_archived(httpx_mock, call_tool):
    _ok(httpx_mock, "/source.list")
    await call_tool("list_sources", {"includeArchived": True})
    assert _sent_body(httpx_mock) == {"includeArchived": True}


async def test_list_all_candidates_single_page(httpx_mock, call_tool):
    """When moreDataAvailable is false, only one call is made."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.list",
        json={"success": True, "results": [{"id": "c1"}, {"id": "c2"}], "moreDataAvailable": False},
    )
    result = await call_tool("list_all_candidates", {})
    assert result["total"] == 2
    assert len(result["results"]) == 2


async def test_list_all_candidates_auto_paginates(httpx_mock, call_tool):
    """Auto-paginator follows cursors until moreDataAvailable is false."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.list",
        json={"success": True, "results": [{"id": "c1"}], "moreDataAvailable": True, "nextCursor": "cursor-2"},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.list",
        json={"success": True, "results": [{"id": "c2"}], "moreDataAvailable": False},
    )
    result = await call_tool("list_all_candidates", {})
    assert result["total"] == 2
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    # Second request must carry the cursor from the first response.
    second_body = json.loads(requests[1].content)
    assert second_body["cursor"] == "cursor-2"


# ---------------------------------------------------------------------------
# Behaviour — error paths and auth
# ---------------------------------------------------------------------------


async def test_auth_uses_http_basic(httpx_mock, call_tool, ashby_client):
    """Every request must carry HTTP Basic auth built from the loaded
    API key — regardless of what value that key actually has, the
    shape must be `Basic base64(api_key:)`."""
    import base64

    _ok(httpx_mock, "/candidate.search")
    await call_tool("search_candidates", {"name": "x"})
    sent_auth = httpx_mock.get_request().headers["authorization"]
    expected = "Basic " + base64.b64encode(f"{ashby_client.api_key}:".encode()).decode()
    assert sent_auth == expected


async def test_error_response_surfaced_to_caller(httpx_mock, call_tool):
    """Ashby's own error envelopes should flow through verbatim."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.search",
        json={"success": False, "errors": ["invalid_input"]},
        status_code=200,
    )
    result = await call_tool("search_candidates", {"name": ""})
    assert result == {"success": False, "errors": ["invalid_input"]}


async def test_unknown_tool_returns_error_text(call_tool):
    """Dispatcher catches unknown names and returns an error string,
    not a crash."""
    result = await call_tool("definitely_not_a_tool", {})
    assert isinstance(result, str)
    assert "Unknown tool" in result

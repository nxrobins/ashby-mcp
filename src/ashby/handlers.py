"""Tool dispatcher — routes a tool name + arguments to the Ashby API.

Most tools are a straight POST of the caller's arguments to one Ashby
endpoint, formatted as a text response with a short prefix. Those tools
live in `_SIMPLE` below. Tools that mutate the payload, post-process the
response, or call multiple endpoints (file uploads, auto-pagination,
client-side filtering) have their own async function in `_SPECIAL`.

Adding a vanilla tool is a one-line addition to `_SIMPLE`. Adding a
quirky tool is a function in the Special Handlers section plus one
entry in `_SPECIAL`.

Failures — an unknown tool, an HTTP error, an Ashby `success: false`
envelope, an unexpected exception — raise `ToolError` out of `dispatch`
rather than coming back as ordinary text content. The class docstring
explains why that is what makes them real MCP errors.
"""

import json
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import mcp.types as types

from . import policy
from .client import ashby_client, truncate_for_log
from .formatting import (
    RECORD_FIELD_CHARS,
    Accessor,
    Column,
    format_json,
    format_list,
    format_record,
    output_format,
    reads,
)
from .tools import tool_blocked_reason

logger = logging.getLogger("ashby.handlers")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """A tool invocation failed; `str(exc)` is the text the caller sees.

    `dispatch` raises this for every failure instead of returning the
    message as content. Propagating it out of the `@server.call_tool()`
    handler is what makes the failure a real MCP error: every mcp 1.x
    release turns an exception raised there into
    `CallToolResult(isError=True, content=[TextContent(text=str(exc))])`,
    so the human-readable message still reaches the model and it can
    recover. (Returning a `CallToolResult` from the handler instead only
    works on newer 1.x releases — mcp 1.1.2, the locked version, mangles
    it into a pydantic validation error.)
    """


def _raise_if_ashby_error(tool_name: str, payload: Any) -> None:
    """Surface Ashby's HTTP-200 error envelope verbatim, in any output mode.

    Validation and permission failures come back as a 200 with
    `{"success": false, "errors": [...], "errorInfo": {...}}`. Fed to the
    markdown formatters, that renders as an empty table or a record of
    `—` fields with the error text lost — so it is raised as an error
    carrying the envelope as JSON (never a table) instead.
    """
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ToolError(f"Ashby returned an error for {tool_name}: {json.dumps(payload)}")


# ---------------------------------------------------------------------------
# Simple tools: tool_name → (endpoint, response_text_prefix)
# The dispatcher POSTs `arguments` as-is and returns `"<prefix>: <json>"`.
# ---------------------------------------------------------------------------

_SIMPLE: dict[str, tuple[str, str]] = {
    # Candidates
    "create_candidate": ("/candidate.create", "Created candidate"),
    "search_candidates": ("/candidate.search", "Search results"),
    "list_candidates": ("/candidate.list", "Candidate list"),
    "get_candidate": ("/candidate.info", "Candidate"),
    "update_candidate": ("/candidate.update", "Updated candidate"),
    "add_candidate_tag": ("/candidate.addTag", "Tag added"),
    "list_candidate_tags": ("/candidateTag.list", "Candidate tags"),
    "add_candidate_to_project": ("/candidate.addProject", "Project added"),
    "create_candidate_note": ("/candidate.createNote", "Note created"),
    "list_candidate_notes": ("/candidate.listNotes", "Candidate notes"),
    "list_candidate_client_info": ("/candidate.listClientInfo", "Candidate client info"),
    "anonymize_candidate": ("/candidate.anonymize", "Anonymized"),
    # Projects
    "get_project": ("/project.info", "Project"),
    "list_projects": ("/project.list", "Projects"),
    "search_projects": ("/project.search", "Project search results"),
    # Custom fields
    "get_custom_field": ("/customField.info", "Custom field"),
    "create_custom_field": ("/customField.create", "Custom field created"),
    "set_custom_field_value": ("/customField.setValue", "Custom field value set"),
    # Jobs
    "create_job": ("/job.create", "Created job"),
    "search_jobs": ("/job.search", "Job search results"),
    "get_job": ("/job.info", "Job"),
    "update_job": ("/job.update", "Job updated"),
    "set_job_status": ("/job.setStatus", "Job status set"),
    # Applications
    "create_application": ("/application.create", "Created application"),
    "list_applications": ("/application.list", "Applications"),
    "get_application": ("/application.info", "Application"),
    "update_application": ("/application.update", "Application updated"),
    "change_application_stage": ("/application.change_stage", "Stage changed"),
    "change_application_source": ("/application.change_source", "Source changed"),
    "transfer_application": ("/application.transfer", "Application transferred"),
    "add_application_hiring_team_member": (
        "/application.addHiringTeamMember",
        "Hiring team member added",
    ),
    "remove_application_hiring_team_member": (
        "/application.removeHiringTeamMember",
        "Hiring team member removed",
    ),
    # Interviews
    "get_interview": ("/interview.info", "Interview"),
    "list_interviews": ("/interview.list", "Interviews"),
    "create_interview_schedule": ("/interviewSchedule.create", "Interview scheduled"),
    "list_interview_schedules": ("/interviewSchedule.list", "Interview schedules"),
    "update_interview_schedule": ("/interviewSchedule.update", "Interview schedule updated"),
    "cancel_interview_schedule": ("/interviewSchedule.cancel", "Interview schedule cancelled"),
    "list_interview_events": ("/interviewEvent.list", "Interview events"),
    "list_interview_plans": ("/interviewPlan.list", "Interview plans"),
    "list_interview_stages": ("/interviewStage.list", "Interview stages"),
    "get_interview_stage": ("/interviewStage.info", "Interview stage"),
    "list_interview_stage_groups": ("/interviewStageGroup.list", "Interview stage groups"),
    "list_application_feedback": ("/applicationFeedback.list", "Application feedback"),
}


# ---------------------------------------------------------------------------
# Output formatting — per-tool column maps feed formatting.py to turn
# verbose Ashby JSON into compact markdown tables (for lists) or labeled
# sections (for single records). Tools without a map fall back to JSON.
# Set ASHBY_OUTPUT=json to disable formatting entirely.
#
# Every dotted path below is checked against openapi.json by
# tests/test_spec_alignment.py; callables declare what they read with
# @reads so the same test covers them.
# ---------------------------------------------------------------------------


@reads("socialLinks")
def _linkedin(record: dict) -> str | None:
    """LinkedIn lives in `socialLinks[]`; Ashby has no top-level LinkedIn field on responses."""
    for link in record.get("socialLinks") or []:
        if str(link.get("type", "")).lower() == "linkedin":
            return link.get("url")
    return None


@reads("socialLinks")
def _social_links(record: dict) -> list[str]:
    return [f"{link.get('type')}: {link.get('url')}" for link in record.get("socialLinks") or []]


@reads("tags")
def _tag_titles(record: dict) -> list[str]:
    """Tags are `{id, title, isArchived}` objects; show the titles."""
    return [
        t.get("title") or t.get("id") if isinstance(t, dict) else str(t)
        for t in record.get("tags") or []
    ]


@reads("emailAddresses")
def _emails(record: dict) -> list[str]:
    return [e.get("value") for e in record.get("emailAddresses") or []]


@reads("phoneNumbers")
def _phones(record: dict) -> list[str]:
    return [p.get("value") for p in record.get("phoneNumbers") or []]


def _custom_field_lines(key: str) -> Callable[[dict], list[str]]:
    """`title: value` per custom field entry under `key` (customFields /
    customFieldEntries); structured values are rendered as compact JSON."""

    @reads(key)
    def entries(record: dict) -> list[str]:
        out = []
        for field in record.get(key) or []:
            value = field.get("value")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, separators=(",", ":"), default=str)
            out.append(f"{field.get('title')}: {value}")
        return out

    return entries


_custom_fields = _custom_field_lines("customFields")
_custom_field_entries = _custom_field_lines("customFieldEntries")


@reads("selectableValues")
def _selectable_values(record: dict) -> list[str]:
    return [v.get("label") or v.get("value") for v in record.get("selectableValues") or []]


@reads("hiringTeam")
def _hiring_team(record: dict) -> list[str]:
    return [
        f"{m.get('email') or m.get('userId')} ({m.get('role')})"
        for m in record.get("hiringTeam") or []
    ]


@reads("location", "locationId")
def _job_location(record: dict) -> str | None:
    """Jobs carry `locationId`; the `location` object only arrives with expand=["location"]."""
    return (record.get("location") or {}).get("name") or record.get("locationId")


@reads("interviewEvents")
def _event_count(record: dict) -> int:
    return len(record.get("interviewEvents") or [])


@reads("interviewerUserIds")
def _interviewer_count(record: dict) -> int:
    return len(record.get("interviewerUserIds") or [])


_CANDIDATE_COLS: Sequence[Column] = [
    ("id", "id"),
    ("name", "name"),
    ("position", "position"),
    ("company", "company"),
    ("school", "school"),
    ("linkedin", _linkedin),
    ("email", "primaryEmailAddress.value"),
    ("source", "source.title"),
    ("created", "createdAt"),
]

_JOB_COLS: Sequence[Column] = [
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    ("employment", "employmentType"),
    ("location", _job_location),
    ("department_id", "departmentId"),
    ("updated", "updatedAt"),
]

# /job.search has no `expand`, so the location object never appears there.
_JOB_SEARCH_COLS: Sequence[Column] = [
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    ("employment", "employmentType"),
    ("location_id", "locationId"),
    ("department_id", "departmentId"),
    ("updated", "updatedAt"),
]

_PROJECT_COLS: Sequence[Column] = [
    ("id", "id"),
    ("title", "title"),
    ("archived", "isArchived"),
    ("confidential", "confidential"),
]

_LIST_FORMATS: dict[str, tuple[str, Sequence[Column]]] = {
    "list_candidates": ("Candidates", _CANDIDATE_COLS),
    "list_all_candidates": ("All candidates", _CANDIDATE_COLS),
    "search_candidates": ("Candidate search results", _CANDIDATE_COLS),
    "list_jobs": ("Jobs", _JOB_COLS),
    "search_jobs": ("Job search results", _JOB_SEARCH_COLS),
    "list_applications": (
        "Applications",
        [
            ("id", "id"),
            ("candidate_id", "candidate.id"),
            ("candidate", "candidate.name"),
            # Application.candidate is a summary (id, name, primary email /
            # phone) — position, company and school need get_candidate.
            ("email", "candidate.primaryEmailAddress.value"),
            ("job", "job.title"),
            ("stage", "currentInterviewStage.title"),
            ("status", "status"),
            ("archive_reason", "archiveReason.text"),
            ("source", "source.title"),
            ("created", "createdAt"),
        ],
    ),
    "list_projects": ("Projects", _PROJECT_COLS),
    "search_projects": ("Project search results", _PROJECT_COLS),
    "list_sources": (
        "Sources",
        [
            ("id", "id"),
            ("title", "title"),
            ("type", "sourceType.title"),
            ("archived", "isArchived"),
        ],
    ),
    "list_candidate_tags": (
        "Candidate tags",
        [
            ("id", "id"),
            ("title", "title"),
            ("archived", "isArchived"),
        ],
    ),
    "list_custom_fields": (
        "Custom fields",
        [
            ("id", "id"),
            ("title", "title"),
            ("type", "fieldType"),
            ("object", "objectType"),
            # The allowed values set_custom_field_value needs for select fields.
            ("values", _selectable_values, 160),
            ("archived", "isArchived"),
        ],
    ),
    "list_interviews": (
        "Interviews",
        [
            ("id", "id"),
            ("title", "title"),
            ("debrief", "isDebrief"),
            ("job_id", "jobId"),
            ("archived", "isArchived"),
        ],
    ),
    "list_interview_plans": (
        "Interview plans",
        [
            ("id", "id"),
            ("title", "title"),
            ("archived", "isArchived"),
        ],
    ),
    "list_interview_stages": (
        "Interview stages",
        [
            ("id", "id"),
            ("title", "title"),
            ("type", "type"),
            ("order", "orderInInterviewPlan"),
        ],
    ),
    "list_interview_stage_groups": (
        "Interview stage groups",
        [
            ("id", "id"),
            ("title", "title"),
            ("order", "order"),
            ("stage_type", "stageType"),
        ],
    ),
    "list_interview_schedules": (
        "Interview schedules",
        [
            ("id", "id"),
            ("application_id", "applicationId"),
            ("stage_id", "interviewStageId"),
            ("status", "status"),
            ("events", _event_count),
        ],
    ),
    "list_interview_events": (
        "Interview events",
        [
            ("id", "id"),
            ("interview", "interview.title"),
            ("start", "startTime"),
            ("end", "endTime"),
            ("interviewers", _interviewer_count),
            ("feedback_submitted", "hasSubmittedFeedback"),
            ("meeting", "meetingLink"),
        ],
    ),
    "list_candidate_notes": (
        "Candidate notes",
        [
            ("id", "id"),
            ("created", "createdAt"),
            ("author", "author.email"),
            # The note text is the point of this tool — never cut it to a table cell.
            ("note", "content", RECORD_FIELD_CHARS),
        ],
    ),
}


@dataclass(frozen=True)
class RecordFormat:
    """How a single-object response is rendered: title, labeled fields, and
    top-level keys to leave out. Anything else in the record is appended
    under its raw key (see formatting.format_record)."""

    title: Accessor
    fields: Sequence[Column]
    hide: Sequence[str] = ()


_RECORD_FORMATS: dict[str, RecordFormat] = {
    "get_candidate": RecordFormat(
        "name",
        [
            # Profile signals first so they're visible at a glance.
            ("position", "position"),
            ("company", "company"),
            ("school", "school"),
            ("linkedin", _linkedin),
            ("social_links", _social_links),
            ("profile_url", "profileUrl"),
            ("resume_id", "resumeFileHandle.id"),
            ("resume_name", "resumeFileHandle.name"),
            ("email", "primaryEmailAddress.value"),
            ("emails", _emails),
            ("phone", "primaryPhoneNumber.value"),
            ("phones", _phones),
            ("location", "primaryLocation.locationSummary"),
            ("timezone", "timezone"),
            ("source", "source.title"),
            ("credited_to", "creditedToUser.email"),
            ("tags", _tag_titles),
            ("applications", "applicationIds"),
            ("custom_fields", _custom_fields),
            ("created", "createdAt"),
            ("updated", "updatedAt"),
        ],
    ),
    "get_job": RecordFormat(
        "title",
        [
            ("status", "status"),
            ("employment", "employmentType"),
            ("confidential", "confidential"),
            ("location", _job_location),
            ("department_id", "departmentId"),
            ("interview_plan_id", "defaultInterviewPlanId"),
            ("requisition", "customRequisitionId"),
            ("hiring_team", _hiring_team),
            ("custom_fields", _custom_fields),
            ("job_posting_ids", "jobPostingIds"),
            ("opened", "openedAt"),
            ("closed", "closedAt"),
            ("created", "createdAt"),
            ("updated", "updatedAt"),
        ],
    ),
    "get_application": RecordFormat(
        "candidate.name",
        [
            ("candidate_id", "candidate.id"),
            ("email", "candidate.primaryEmailAddress.value"),
            ("phone", "candidate.primaryPhoneNumber.value"),
            ("job", "job.title"),
            ("job_id", "job.id"),
            ("stage", "currentInterviewStage.title"),
            ("stage_id", "currentInterviewStage.id"),
            ("status", "status"),
            ("archive_reason", "archiveReason.text"),
            ("archived_at", "archivedAt"),
            ("source", "source.title"),
            ("credited_to", "creditedToUser.email"),
            ("hiring_team", _hiring_team),
            ("custom_fields", _custom_fields),
            ("created", "createdAt"),
            ("updated", "updatedAt"),
        ],
        hide=("submitterClientIp", "submitterUserAgent"),
    ),
    "get_project": RecordFormat(
        "title",
        [
            ("description", "description"),
            ("archived", "isArchived"),
            ("confidential", "confidential"),
            ("author_id", "authorId"),
            ("custom_fields", _custom_field_entries),
            ("created", "createdAt"),
        ],
    ),
    "get_custom_field": RecordFormat(
        "title",
        [
            ("type", "fieldType"),
            ("object", "objectType"),
            ("private", "isPrivate"),
            ("archived", "isArchived"),
            ("values", _selectable_values),
        ],
    ),
    "get_interview_stage": RecordFormat(
        "title",
        [
            ("type", "type"),
            ("order", "orderInInterviewPlan"),
            ("plan_id", "interviewPlanId"),
            ("group_id", "interviewStageGroupId"),
        ],
    ),
    "get_interview": RecordFormat(
        "title",
        [
            ("debrief", "isDebrief"),
            ("job_id", "jobId"),
            ("archived", "isArchived"),
            ("feedback_form_id", "feedbackFormDefinitionId"),
            ("instructions", "instructionsPlain"),
        ],
    ),
}


def _render(tool_name: str, payload: Any) -> str:
    """Render an Ashby response for LLM consumption (markdown or JSON)."""
    if output_format() == "json":
        return format_json(payload)
    if fmt := _LIST_FORMATS.get(tool_name):
        title, columns = fmt
        return format_list(payload, title, columns)
    if fmt := _RECORD_FORMATS.get(tool_name):
        # Ashby wraps single-object responses as {success, results: {...}}.
        # Unwrap so the configured accessors see the record directly.
        record = (
            payload.get("results")
            if isinstance(payload, dict) and isinstance(payload.get("results"), dict)
            else payload
        )
        return format_record(record, fmt.title, fmt.fields, hide=fmt.hide)
    return format_json(payload)


def _text(tool_name: str, prefix: str, payload: Any) -> list[types.TextContent]:
    _raise_if_ashby_error(tool_name, payload)
    return [types.TextContent(type="text", text=f"{prefix}: {_render(tool_name, payload)}")]


# ---------------------------------------------------------------------------
# Special handlers — tools that need custom payload/response logic.
# ---------------------------------------------------------------------------


async def _list_jobs(arguments: dict) -> list[types.TextContent]:
    """Defaults status filter to Open when the caller omits it."""
    payload = dict(arguments) if arguments else {}
    payload.setdefault("status", ["Open"])
    response = await ashby_client._make_request("/job.list", method="POST", data=payload)
    return _text("list_jobs", "Job list", response)


async def _list_custom_fields(arguments: dict) -> list[types.TextContent]:
    """`objectType` is a client-side filter — strip it from the outbound
    payload and apply it to the response."""
    payload = {k: v for k, v in (arguments or {}).items() if k != "objectType"}
    response = await ashby_client._make_request("/customField.list", method="POST", data=payload)
    obj_type = (arguments or {}).get("objectType")
    if obj_type and isinstance(response, dict) and isinstance(response.get("results"), list):
        filtered = [f for f in response["results"] if f.get("objectType") == obj_type]
        response = {**response, "results": filtered, "filteredBy": {"objectType": obj_type}}
    return _text("list_custom_fields", "Custom fields", response)


async def _upload_candidate_resume(arguments: dict) -> list[types.TextContent]:
    # resolve_upload_path confines the path to ASHBY_UPLOAD_DIR (and refuses
    # it outright over HTTP without one) — the model chooses `file_path`.
    path = policy.resolve_upload_path(arguments["file_path"])
    with open(path, "rb") as f:
        response = await ashby_client._make_multipart_request(
            "/candidate.uploadResume",
            data={"candidateId": arguments["candidateId"]},
            files={"resume": (os.path.basename(arguments["file_path"]), f)},
        )
    return _text("upload_candidate_resume", "Resume uploaded", response)


async def _upload_candidate_file(arguments: dict) -> list[types.TextContent]:
    path = policy.resolve_upload_path(arguments["file_path"])
    with open(path, "rb") as f:
        response = await ashby_client._make_multipart_request(
            "/candidate.uploadFile",
            data={"candidateId": arguments["candidateId"]},
            files={"file": (os.path.basename(arguments["file_path"]), f)},
        )
    return _text("upload_candidate_file", "File uploaded", response)


# Upper bound on pages fetched by one list_all_candidates call. At Ashby's
# page size of 100 this is 5,000 candidates — enough for most workspaces
# while keeping a single tool call bounded in time and response size.
_LIST_ALL_MAX_PAGES = 50
_LIST_ALL_PAGE_SIZE = 100


async def _list_all_candidates(arguments: dict) -> list[types.TextContent]:
    """Auto-paginate /candidate.list until exhausted or the page cap is hit.

    When the cap stops the walk with data still remaining, the response is
    marked `truncated: true` and carries `moreDataAvailable` / `nextCursor`
    so the caller can continue with `list_candidates` from where this
    stopped. A completed walk passes through Ashby's final `syncToken`.
    """
    all_results: list = []
    payload: dict = {"limit": _LIST_ALL_PAGE_SIZE}
    if arguments and "syncToken" in arguments:
        payload["syncToken"] = arguments["syncToken"]

    truncated = False
    next_cursor = None
    sync_token = None
    for _ in range(_LIST_ALL_MAX_PAGES):
        page = await ashby_client._make_request("/candidate.list", method="POST", data=payload)
        # An error page carries no `results`/`moreDataAvailable`, so without
        # this it would read as an empty last page and end the loop with a
        # silently truncated (or empty) list.
        _raise_if_ashby_error("list_all_candidates", page)
        all_results.extend(page.get("results", []))
        sync_token = page.get("syncToken")
        if not page.get("moreDataAvailable") or not page.get("nextCursor"):
            break
        payload["cursor"] = page["nextCursor"]
    else:
        # Loop ran out of pages without hitting the end of the data.
        truncated = True
        next_cursor = payload.get("cursor")

    response: dict = {"results": all_results, "total": len(all_results), "truncated": truncated}
    if truncated:
        response["moreDataAvailable"] = True
        response["nextCursor"] = next_cursor
    elif sync_token:
        response["syncToken"] = sync_token
    return _text("list_all_candidates", "All candidates", response)


async def _list_sources(arguments: dict) -> list[types.TextContent]:
    payload = {"includeArchived": (arguments or {}).get("includeArchived", False)}
    response = await ashby_client._make_request("/source.list", method="POST", data=payload)
    return _text("list_sources", "Sources", response)


_SPECIAL: dict[str, Callable[[dict], Awaitable[list[types.TextContent]]]] = {
    "list_jobs": _list_jobs,
    "list_custom_fields": _list_custom_fields,
    "upload_candidate_resume": _upload_candidate_resume,
    "upload_candidate_file": _upload_candidate_file,
    "list_all_candidates": _list_all_candidates,
    "list_sources": _list_sources,
}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def dispatch(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Route a tool invocation to its handler (table-lookup + fallback).

    The policy check runs first so a tool hidden from tools/list (read-only
    mode, uploads over HTTP) is also refused if a client calls it anyway.

    Raises `ToolError` on any failure. Its message is the human-readable
    explanation for the model; the exception type is how callers (the MCP
    server, the eval runner, the tests) tell a failure from content.
    """
    logger.info("dispatch %s", name)
    if reason := tool_blocked_reason(name):
        logger.warning("tool %s rejected by policy: %s", name, reason)
        raise ToolError(f"Error executing {name}: {reason}")
    try:
        if handler := _SPECIAL.get(name):
            return await handler(arguments)
        if route := _SIMPLE.get(name):
            endpoint, prefix = route
            response = await ashby_client._make_request(endpoint, method="POST", data=arguments)
            return _text(name, prefix, response)
        raise ValueError(f"Unknown tool: {name}")
    except ToolError as e:
        logger.warning("tool %s failed: %s", name, truncate_for_log(str(e)))
        raise
    except Exception as e:
        logger.warning("tool %s failed: %s", name, truncate_for_log(str(e)))
        raise ToolError(f"Error executing {name}: {e}") from e

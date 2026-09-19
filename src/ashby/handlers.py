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
from typing import Any, Awaitable, Callable, Sequence

import mcp.types as types

from .client import ashby_client
from .formatting import (
    FULL_TEXT,
    WIDE,
    Column,
    count_of,
    custom_fields,
    fmt,
    format_json,
    format_list,
    format_record,
    items_of,
    output_format,
    select_options,
    social_link,
    titles_of,
)

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
    "create_candidate":           ("/candidate.create",           "Created candidate"),
    "search_candidates":          ("/candidate.search",           "Search results"),
    "list_candidates":            ("/candidate.list",             "Candidate list"),
    "get_candidate":              ("/candidate.info",             "Candidate"),
    "update_candidate":           ("/candidate.update",           "Updated candidate"),
    "add_candidate_tag":          ("/candidate.addTag",           "Tag added"),
    "list_candidate_tags":        ("/candidateTag.list",          "Candidate tags"),
    "add_candidate_to_project":   ("/candidate.addProject",       "Project added"),
    "create_candidate_note":      ("/candidate.createNote",       "Note created"),
    "list_candidate_notes":       ("/candidate.listNotes",        "Candidate notes"),
    "list_candidate_client_info": ("/candidate.listClientInfo",   "Candidate client info"),
    "anonymize_candidate":        ("/candidate.anonymize",        "Anonymized"),
    # Projects
    "get_project":                ("/project.info",               "Project"),
    "list_projects":              ("/project.list",               "Projects"),
    "search_projects":            ("/project.search",             "Project search results"),
    # Custom fields
    "get_custom_field":           ("/customField.info",           "Custom field"),
    "create_custom_field":        ("/customField.create",         "Custom field created"),
    "set_custom_field_value":     ("/customField.setValue",       "Custom field value set"),
    # Jobs
    "create_job":                 ("/job.create",                 "Created job"),
    "search_jobs":                ("/job.search",                 "Job search results"),
    "update_job":                 ("/job.update",                 "Job updated"),
    "set_job_status":             ("/job.setStatus",              "Job status set"),
    # Applications
    "create_application":         ("/application.create",         "Created application"),
    "list_applications":          ("/application.list",           "Applications"),
    "get_application":            ("/application.info",           "Application"),
    "update_application":         ("/application.update",         "Application updated"),
    "change_application_stage":   ("/application.change_stage",   "Stage changed"),
    "change_application_source":  ("/application.change_source",  "Source changed"),
    "transfer_application":       ("/application.transfer",       "Application transferred"),
    "add_application_hiring_team_member":    ("/application.addHiringTeamMember",    "Hiring team member added"),
    "remove_application_hiring_team_member": ("/application.removeHiringTeamMember", "Hiring team member removed"),
    # Interviews
    "get_interview":              ("/interview.info",             "Interview"),
    "list_interviews":            ("/interview.list",             "Interviews"),
    "create_interview_schedule":  ("/interviewSchedule.create",   "Interview scheduled"),
    "list_interview_schedules":   ("/interviewSchedule.list",     "Interview schedules"),
    "update_interview_schedule":  ("/interviewSchedule.update",   "Interview schedule updated"),
    "cancel_interview_schedule":  ("/interviewSchedule.cancel",   "Interview schedule cancelled"),
    "list_interview_events":      ("/interviewEvent.list",        "Interview events"),
    "list_interview_plans":       ("/interviewPlan.list",         "Interview plans"),
    "list_interview_stages":      ("/interviewStage.list",        "Interview stages"),
    "get_interview_stage":        ("/interviewStage.info",        "Interview stage"),
    "list_interview_stage_groups": ("/interviewStageGroup.list",  "Interview stage groups"),
    "list_application_feedback":  ("/applicationFeedback.list",   "Application feedback"),
}


# ---------------------------------------------------------------------------
# Output formatting — per-tool column maps feed formatting.py to turn
# verbose Ashby JSON into compact markdown tables (for lists) or labeled
# sections (for single records). Tools without a map fall back to JSON.
# Set ASHBY_OUTPUT=json to disable formatting entirely.
#
# Every accessor below names a field from the endpoint's 200-response
# schema in openapi.json — `tests/test_spec_alignment.py` fails if one
# doesn't resolve, so a typo or an invented field can't silently render
# as `—`. Callable accessors come from formatting.py factories that
# declare the paths they read (see `Derived`).
# ---------------------------------------------------------------------------

_CANDIDATE_COLS: Sequence[Column] = [
    ("id", "id"),
    ("name", "name"),
    ("position", "position"),
    ("company", "company"),
    ("school", "school"),
    # Candidate has no `linkedInUrl`; links live in `socialLinks: [{type, url}]`.
    ("linkedin", social_link("LinkedIn")),
    ("email", "primaryEmailAddress.value"),
    ("location", "primaryLocation.locationSummary"),
    ("source", "source.title"),
    ("created", "createdAt"),
]

_JOB_COLS: Sequence[Column] = [
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    # Job carries only `locationId` / `departmentId`. `location` is the
    # expanded object (`expand: ["location"]`, which list_jobs / get_job
    # request by default); there is no department expansion in the API.
    ("location", "location.name"),
    ("location_id", "locationId"),
    ("department_id", "departmentId"),
    ("employment", "employmentType"),
    ("openings", items_of("openings", "{id} ({openingState})")),
    ("updated", "updatedAt"),
]

_PROJECT_COLS: Sequence[Column] = [
    ("id", "id"),
    ("title", "title"),
    ("description", "description"),
    ("archived", "isArchived"),
    ("confidential", "confidential"),
]

_CUSTOM_FIELD_COLS: Sequence[Column] = [
    ("id", "id"),
    ("title", "title"),
    ("type", "fieldType"),
    ("object", "objectType"),
    ("archived", "isArchived"),
    # Allowed values for ValueSelect / MultiValueSelect — needed by
    # set_custom_field_value, so give the column a generous budget.
    ("values", select_options(), WIDE),
]

_LIST_FORMATS: dict[str, tuple[str, Sequence[Column]]] = {
    "list_candidates":      ("Candidates", _CANDIDATE_COLS),
    "list_all_candidates":  ("All candidates", _CANDIDATE_COLS),
    "search_candidates":    ("Candidate search results", _CANDIDATE_COLS),
    "list_jobs":            ("Jobs", _JOB_COLS),
    "search_jobs": ("Job search results", [
        # job.search has no `expand`, so no location name — ids only.
        ("id", "id"),
        ("title", "title"),
        ("status", "status"),
        ("location_id", "locationId"),
        ("department_id", "departmentId"),
        ("employment", "employmentType"),
    ]),
    "list_applications": ("Applications", [
        ("id", "id"),
        ("candidate_id", "candidate.id"),
        ("candidate", "candidate.name"),
        # Application.candidate is a summary ({id, name, primaryEmailAddress,
        # primaryPhoneNumber}); position/company/school/links need get_candidate.
        ("email", "candidate.primaryEmailAddress.value"),
        ("job", "job.title"),
        ("job_id", "job.id"),
        ("stage", "currentInterviewStage.title"),
        ("status", "status"),
        ("archive_reason", "archiveReason.text"),
        ("archived_at", "archivedAt"),
        ("source", "source.title"),
        ("created", "createdAt"),
        ("openings", items_of("openings", "{id} ({openingState})")),  # expand: ["openings"]
    ]),
    "list_projects":   ("Projects", _PROJECT_COLS),
    "search_projects": ("Project search results", _PROJECT_COLS),
    "list_sources": ("Sources", [
        ("id", "id"),
        ("title", "title"),
        ("type", "sourceType.title"),
        ("archived", "isArchived"),
    ]),
    "list_candidate_tags": ("Candidate tags", [
        ("id", "id"),
        ("title", "title"),
        ("archived", "isArchived"),
    ]),
    "list_custom_fields": ("Custom fields", _CUSTOM_FIELD_COLS),
    "list_interviews": ("Interviews", [
        ("id", "id"),
        ("title", "title"),
        ("archived", "isArchived"),
        ("debrief", "isDebrief"),
        ("job_id", "jobId"),
    ]),
    "list_interview_plans": ("Interview plans", [
        ("id", "id"),
        ("title", "title"),
        ("archived", "isArchived"),
    ]),
    "list_interview_stages": ("Interview stages", [
        ("id", "id"),
        ("title", "title"),
        ("type", "type"),
        ("order", "orderInInterviewPlan"),
        ("group_id", "interviewStageGroupId"),
    ]),
    "list_interview_stage_groups": ("Interview stage groups", [
        ("id", "id"),
        ("title", "title"),
        ("order", "order"),
        ("stage_type", "stageType"),
    ]),
    "list_interview_schedules": ("Interview schedules", [
        ("id", "id"),
        ("applicationId", "applicationId"),
        ("stage_id", "interviewStageId"),
        ("status", "status"),
        ("events", count_of("interviewEvents")),
        ("first_start", "interviewEvents.0.startTime"),
    ]),
    "list_interview_events": ("Interview events", [
        ("id", "id"),
        ("interview", "interview.title"),  # expand: ["interview"]
        ("interview_id", "interviewId"),
        ("start", "startTime"),
        ("end", "endTime"),
        ("interviewers", "interviewerUserIds"),
        ("feedback_submitted", "hasSubmittedFeedback"),
        ("meeting_link", "meetingLink"),
        ("location", "location"),
    ]),
    "list_candidate_notes": ("Candidate notes", [
        ("id", "id"),
        ("createdAt", "createdAt"),
        ("author", "author.email"),
        ("author_name", fmt("{author.firstName} {author.lastName}")),
        # Notes are the point of this list — don't truncate them to 60 chars.
        ("note", "content", FULL_TEXT),
    ]),
}

_RECORD_FORMATS: dict[str, tuple[Any, Sequence[Column]]] = {
    "get_candidate": ("name", [
        # Scoring signals first so a heuristic finds them at a glance.
        ("position",     "position"),
        ("company",      "company"),
        ("school",       "school"),
        ("linkedin",     social_link("LinkedIn")),
        ("links",        items_of("socialLinks", "{type}: {url}")),
        ("profile_url",  "profileUrl"),
        ("resume_id",    "resumeFileHandle.id"),
        ("resume_name",  "resumeFileHandle.name"),
        ("email",        "primaryEmailAddress.value"),
        ("emails",       items_of("emailAddresses", "{value} ({type})")),
        ("phone",        "primaryPhoneNumber.value"),
        ("phones",       items_of("phoneNumbers", "{value} ({type})")),
        ("location",     "primaryLocation.locationSummary"),
        ("timezone",     "timezone"),
        ("source",       "source.title"),
        ("credited_to",  "creditedToUser.email"),
        ("tags",         titles_of("tags")),
        ("applications", "applicationIds"),
        ("custom_fields", custom_fields()),
        ("files",        items_of("fileHandles", "{name} ({id})")),
        ("created",      "createdAt"),
        ("updated",      "updatedAt"),
    ]),
    "get_job": ("title", [
        ("status",         "status"),
        ("location",       "location.name"),  # expand: ["location"] (default)
        ("location_id",    "locationId"),
        ("department_id",  "departmentId"),
        ("employment",     "employmentType"),
        ("confidential",   "confidential"),
        ("interview_plan", "defaultInterviewPlanId"),
        ("hiring_team",    items_of("hiringTeam", "{firstName} {lastName} ({role})")),
        ("openings",       items_of("openings", "{id} {latestVersion.identifier} ({openingState})")),
        ("custom_fields",  custom_fields()),
        ("created",        "createdAt"),
        ("opened",         "openedAt"),
        ("closed",         "closedAt"),
        ("updated",        "updatedAt"),
    ]),
    "get_application": ("candidate.name", [
        ("candidate_id",   "candidate.id"),
        ("email",          "candidate.primaryEmailAddress.value"),
        ("phone",          "candidate.primaryPhoneNumber.value"),
        ("job",            "job.title"),
        ("job_id",         "job.id"),
        ("stage",          "currentInterviewStage.title"),
        ("stage_id",       "currentInterviewStage.id"),
        ("status",         "status"),
        ("archive_reason", "archiveReason.text"),
        ("archived_at",    "archivedAt"),
        ("source",         "source.title"),
        ("credited_to",    "creditedToUser.email"),
        ("hiring_team",    items_of("hiringTeam", "{firstName} {lastName} ({role})")),
        ("custom_fields",  custom_fields()),
        ("history",        items_of("applicationHistory", "{title} @ {enteredStageAt}")),
        # expand: ["openings", "referrals"]. `applicationFormSubmissions` is
        # free-form, so it is left to the raw-JSON tail rather than flattened.
        ("openings",       items_of("openings", "{id} ({openingState})")),
        ("referrals",      items_of("referrals", "{user.firstName} {user.lastName} ({user.email}) @ {referredAt}")),
        ("created",        "createdAt"),
        ("updated",        "updatedAt"),
    ]),
    "get_project": ("title", [
        ("description",  "description"),
        ("archived",     "isArchived"),
        ("confidential", "confidential"),
        ("author_id",    "authorId"),
        ("custom_fields", custom_fields("customFieldEntries")),
        ("created",      "createdAt"),
    ]),
    "get_custom_field": ("title", [
        ("type",     "fieldType"),
        ("object",   "objectType"),
        ("archived", "isArchived"),
        ("private",  "isPrivate"),
        ("values",   select_options()),
    ]),
    "get_interview_stage": ("title", [
        ("type",     "type"),
        ("order",    "orderInInterviewPlan"),
        ("group_id", "interviewStageGroupId"),
        ("plan_id",  "interviewPlanId"),
    ]),
    "get_interview": ("title", [
        ("archived",         "isArchived"),
        ("debrief",          "isDebrief"),
        ("job_id",           "jobId"),
        ("feedback_form_id", "feedbackFormDefinitionId"),
        ("instructions",     "instructionsPlain"),
    ]),
}

# Record keys deliberately left out of the raw-JSON tail (duplicates of a
# field already rendered in another form).
_RECORD_OMIT: dict[str, Sequence[str]] = {
    "get_interview": ("instructionsHtml",),
}


def _render(tool_name: str, payload: Any) -> str:
    """Render an Ashby response for LLM consumption (markdown or JSON)."""
    if output_format() == "json":
        return format_json(payload)
    if spec := _LIST_FORMATS.get(tool_name):
        title, columns = spec
        return format_list(payload, title, columns)
    if spec := _RECORD_FORMATS.get(tool_name):
        title_acc, fields = spec
        # Ashby wraps single-object responses as {success, results: {...}}.
        # Unwrap so the configured accessors see the record directly.
        record = payload.get("results") if isinstance(payload, dict) and isinstance(payload.get("results"), dict) else payload
        return format_record(record, title_acc, fields, omit=_RECORD_OMIT.get(tool_name, ()))
    return format_json(payload)


def _text(tool_name: str, prefix: str, payload: Any) -> list[types.TextContent]:
    _raise_if_ashby_error(tool_name, payload)
    return [types.TextContent(type="text", text=f"{prefix}: {_render(tool_name, payload)}")]


# ---------------------------------------------------------------------------
# Special handlers — tools that need custom payload/response logic.
# ---------------------------------------------------------------------------


async def _list_jobs(arguments: dict) -> list[types.TextContent]:
    """Defaults status filter to Open and expands `location` when the
    caller omits them. A Job only carries `locationId`; the expansion is
    what lets the table show a location *name*."""
    payload = dict(arguments) if arguments else {}
    payload.setdefault("status", ["Open"])
    payload.setdefault("expand", ["location"])
    response = await ashby_client._make_request("/job.list", method="POST", data=payload)
    return _text("list_jobs", "Job list", response)


async def _get_job(arguments: dict) -> list[types.TextContent]:
    """Expands `location` unless the caller chose their own `expand`."""
    payload = dict(arguments) if arguments else {}
    payload.setdefault("expand", ["location"])
    response = await ashby_client._make_request("/job.info", method="POST", data=payload)
    return _text("get_job", "Job", response)


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
    path = arguments["file_path"]
    with open(path, "rb") as f:
        response = await ashby_client._make_multipart_request(
            "/candidate.uploadResume",
            data={"candidateId": arguments["candidateId"]},
            files={"resume": (os.path.basename(path), f)},
        )
    return _text("upload_candidate_resume", "Resume uploaded", response)


async def _upload_candidate_file(arguments: dict) -> list[types.TextContent]:
    path = arguments["file_path"]
    with open(path, "rb") as f:
        response = await ashby_client._make_multipart_request(
            "/candidate.uploadFile",
            data={"candidateId": arguments["candidateId"]},
            files={"file": (os.path.basename(path), f)},
        )
    return _text("upload_candidate_file", "File uploaded", response)


async def _list_all_candidates(arguments: dict) -> list[types.TextContent]:
    """Auto-paginate /candidate.list until exhausted (cap 50 pages = 5k candidates)."""
    all_results: list = []
    payload: dict = {"limit": 100}
    if arguments and "syncToken" in arguments:
        payload["syncToken"] = arguments["syncToken"]
    for _ in range(50):
        page = await ashby_client._make_request("/candidate.list", method="POST", data=payload)
        # An error page carries no `results`/`moreDataAvailable`, so without
        # this it would read as an empty last page and end the loop with a
        # silently truncated (or empty) list.
        _raise_if_ashby_error("list_all_candidates", page)
        all_results.extend(page.get("results", []))
        if not page.get("moreDataAvailable") or not page.get("nextCursor"):
            break
        payload["cursor"] = page["nextCursor"]
    return _text("list_all_candidates", "All candidates", {"results": all_results, "total": len(all_results)})


async def _list_sources(arguments: dict) -> list[types.TextContent]:
    payload = {"includeArchived": (arguments or {}).get("includeArchived", False)}
    response = await ashby_client._make_request("/source.list", method="POST", data=payload)
    return _text("list_sources", "Sources", response)


_SPECIAL: dict[str, Callable[[dict], Awaitable[list[types.TextContent]]]] = {
    "list_jobs":                _list_jobs,
    "get_job":                  _get_job,
    "list_custom_fields":       _list_custom_fields,
    "upload_candidate_resume":  _upload_candidate_resume,
    "upload_candidate_file":    _upload_candidate_file,
    "list_all_candidates":      _list_all_candidates,
    "list_sources":             _list_sources,
}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def dispatch(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Route a tool invocation to its handler (table-lookup + fallback).

    Raises `ToolError` on any failure. Its message is the human-readable
    explanation for the model; the exception type is how callers (the MCP
    server, the eval runner, the tests) tell a failure from content.
    """
    logger.info("dispatch %s", name)
    try:
        if handler := _SPECIAL.get(name):
            return await handler(arguments)
        if route := _SIMPLE.get(name):
            endpoint, prefix = route
            response = await ashby_client._make_request(endpoint, method="POST", data=arguments)
            return _text(name, prefix, response)
        raise ValueError(f"Unknown tool: {name}")
    except ToolError as e:
        logger.warning("tool %s failed: %s", name, e)
        raise
    except Exception as e:
        logger.warning("tool %s failed: %s", name, e)
        raise ToolError(f"Error executing {name}: {e}") from e

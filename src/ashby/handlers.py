"""Tool dispatcher — routes a tool name + arguments to the Ashby API.

Most tools are a straight POST of the caller's arguments to one Ashby
endpoint, formatted as a text response with a short prefix. Those tools
live in `_SIMPLE` below. Tools that mutate the payload, post-process the
response, or call multiple endpoints (file uploads, auto-pagination,
client-side filtering) have their own async function in `_SPECIAL`.

Adding a vanilla tool is a one-line addition to `_SIMPLE`. Adding a
quirky tool is a function in the Special Handlers section plus one
entry in `_SPECIAL`.
"""

import json
import logging
import os
from typing import Any, Awaitable, Callable

import mcp.types as types

from .client import ashby_client

logger = logging.getLogger("ashby.handlers")


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
    "get_job":                    ("/job.info",                   "Job"),
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
}


def _text(prefix: str, payload: Any) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=f"{prefix}: {json.dumps(payload, indent=2)}")]


# ---------------------------------------------------------------------------
# Special handlers — tools that need custom payload/response logic.
# ---------------------------------------------------------------------------


async def _list_jobs(arguments: dict) -> list[types.TextContent]:
    """Defaults status filter to Open when the caller omits it."""
    payload = dict(arguments) if arguments else {}
    payload.setdefault("status", ["Open"])
    response = await ashby_client._make_request("/job.list", method="POST", data=payload)
    return _text("Job list", response)


async def _list_custom_fields(arguments: dict) -> list[types.TextContent]:
    """`objectType` is a client-side filter — strip it from the outbound
    payload and apply it to the response."""
    payload = {k: v for k, v in (arguments or {}).items() if k != "objectType"}
    response = await ashby_client._make_request("/customField.list", method="POST", data=payload)
    obj_type = (arguments or {}).get("objectType")
    if obj_type and isinstance(response, dict) and isinstance(response.get("results"), list):
        filtered = [f for f in response["results"] if f.get("objectType") == obj_type]
        response = {**response, "results": filtered, "filteredBy": {"objectType": obj_type}}
    return _text("Custom fields", response)


async def _upload_candidate_resume(arguments: dict) -> list[types.TextContent]:
    path = arguments["file_path"]
    with open(path, "rb") as f:
        response = await ashby_client._make_multipart_request(
            "/candidate.uploadResume",
            data={"candidateId": arguments["candidateId"]},
            files={"resume": (os.path.basename(path), f)},
        )
    return _text("Resume uploaded", response)


async def _upload_candidate_file(arguments: dict) -> list[types.TextContent]:
    path = arguments["file_path"]
    with open(path, "rb") as f:
        response = await ashby_client._make_multipart_request(
            "/candidate.uploadFile",
            data={"candidateId": arguments["candidateId"]},
            files={"file": (os.path.basename(path), f)},
        )
    return _text("File uploaded", response)


async def _list_all_candidates(arguments: dict) -> list[types.TextContent]:
    """Auto-paginate /candidate.list until exhausted (cap 50 pages = 5k candidates)."""
    all_results: list = []
    payload: dict = {"limit": 100}
    if arguments and "syncToken" in arguments:
        payload["syncToken"] = arguments["syncToken"]
    for _ in range(50):
        page = await ashby_client._make_request("/candidate.list", method="POST", data=payload)
        all_results.extend(page.get("results", []))
        if not page.get("moreDataAvailable") or not page.get("nextCursor"):
            break
        payload["cursor"] = page["nextCursor"]
    return _text("All candidates", {"results": all_results, "total": len(all_results)})


async def _list_sources(arguments: dict) -> list[types.TextContent]:
    payload = {"includeArchived": (arguments or {}).get("includeArchived", False)}
    response = await ashby_client._make_request("/source.list", method="POST", data=payload)
    return _text("Sources", response)


_SPECIAL: dict[str, Callable[[dict], Awaitable[list[types.TextContent]]]] = {
    "list_jobs":                _list_jobs,
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
    """Route a tool invocation to its handler (table-lookup + fallback)."""
    logger.info("dispatch %s", name)
    try:
        if handler := _SPECIAL.get(name):
            return await handler(arguments)
        if route := _SIMPLE.get(name):
            endpoint, prefix = route
            response = await ashby_client._make_request(endpoint, method="POST", data=arguments)
            return _text(prefix, response)
        raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.warning("tool %s failed: %s", name, e)
        return [types.TextContent(type="text", text=f"Error executing {name}: {str(e)}")]

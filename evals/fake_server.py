"""Fake Ashby HTTP server backed by the synthetic workspace.

Implements the endpoints the eval cases exercise. Designed to be
plugged into `httpx.MockTransport` so the real AshbyClient routes
through it without any other changes.

Coverage is deliberately partial — only endpoints the cases touch are
implemented. Anything else returns 404 with a message pointing at this
file, so when a new case hits an unhandled endpoint it fails loudly
rather than silently returning empty data.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx

from .workspace import (
    APPLICATIONS,
    ARCHIVE_REASONS,
    CANDIDATE_NOTES,
    CANDIDATES,
    INTERVIEW_STAGES,
    JOBS,
    SOURCES,
)

logger = logging.getLogger("ashby.evals.fake_server")


def _ok(results: Any, **extra: Any) -> dict:
    return {"success": True, "results": results, **extra}


def _not_found() -> dict:
    return {"success": False, "errors": ["not_found"]}


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------


def _paginate(items: list, body: dict) -> tuple[list, bool, str | None]:
    limit = int(body.get("limit", 100))
    offset = int(body.get("cursor", "0"))
    page = items[offset : offset + limit]
    has_more = offset + limit < len(items)
    next_cursor = str(offset + limit) if has_more else None
    return page, has_more, next_cursor


def candidate_list(body: dict) -> dict:
    page, more, cursor = _paginate(CANDIDATES, body)
    return _ok(page, moreDataAvailable=more, nextCursor=cursor)


def candidate_info(body: dict) -> dict:
    cid = body.get("id")
    cand = next((c for c in CANDIDATES if c["id"] == cid), None)
    return _ok(cand) if cand else _not_found()


def candidate_search(body: dict) -> dict:
    q_email = (body.get("email") or "").lower()
    q_name = (body.get("name") or "").lower()
    hits = []
    for c in CANDIDATES:
        email = (c.get("primaryEmailAddress") or {}).get("value", "").lower()
        name = c.get("name", "").lower()
        if q_email and q_email in email:
            hits.append(c)
        elif q_name and q_name in name:
            hits.append(c)
    return _ok(hits)


def candidate_list_notes(body: dict) -> dict:
    cid = body.get("candidateId")
    notes = CANDIDATE_NOTES.get(cid, [])
    return _ok(notes, moreDataAvailable=False)


def job_list(body: dict) -> dict:
    statuses = body.get("status") or ["Open"]
    items = [j for j in JOBS if j["status"] in statuses]
    page, more, cursor = _paginate(items, body)
    return _ok(page, moreDataAvailable=more, nextCursor=cursor)


def job_info(body: dict) -> dict:
    jid = body.get("id")
    job = next((j for j in JOBS if j["id"] == jid), None)
    return _ok(job) if job else _not_found()


def job_search(body: dict) -> dict:
    q = (body.get("title") or "").lower()
    hits = [j for j in JOBS if q in j["title"].lower()]
    return _ok(hits)


def application_list(body: dict) -> dict:
    items = list(APPLICATIONS)
    if status := body.get("status"):
        items = [a for a in items if a["status"] == status]
    if job_id := body.get("jobId"):
        items = [a for a in items if a["job"]["id"] == job_id]
    page, more, cursor = _paginate(items, body)
    return _ok(page, moreDataAvailable=more, nextCursor=cursor)


def application_info(body: dict) -> dict:
    aid = body.get("applicationId") or body.get("id")
    app = next((a for a in APPLICATIONS if a["id"] == aid), None)
    return _ok(app) if app else _not_found()


def source_list(body: dict) -> dict:
    items = SOURCES
    if not body.get("includeArchived", False):
        items = [s for s in items if not s.get("isArchived")]
    return _ok(items)


def interview_stage_list(body: dict) -> dict:
    return _ok(INTERVIEW_STAGES)


def interview_plan_list(body: dict) -> dict:
    # The synthetic workspace only has one implicit plan — return a
    # minimal entry so the agent's discovery calls don't fail.
    return _ok([{"id": "ip_default", "title": "Default Interview Plan", "isArchived": False}])


def archive_reason_list(body: dict) -> dict:
    # Surface in the shape `list_custom_fields` etc. use — flat list with ids.
    return _ok(ARCHIVE_REASONS)


ROUTES: dict[str, Callable[[dict], dict]] = {
    "/candidate.list":       candidate_list,
    "/candidate.info":       candidate_info,
    "/candidate.search":     candidate_search,
    "/candidate.listNotes":  candidate_list_notes,
    "/job.list":             job_list,
    "/job.info":             job_info,
    "/job.search":           job_search,
    "/application.list":     application_list,
    "/application.info":     application_info,
    "/source.list":          source_list,
    "/interviewStage.list":  interview_stage_list,
    "/interviewPlan.list":   interview_plan_list,
    "/archiveReason.list":   archive_reason_list,
}


# ---------------------------------------------------------------------------
# httpx handler
# ---------------------------------------------------------------------------


def handler(request: httpx.Request) -> httpx.Response:
    """httpx.MockTransport callback — dispatches by URL path."""
    path = request.url.path
    try:
        body = json.loads(request.content) if request.content else {}
    except json.JSONDecodeError:
        body = {}
    logger.debug("fake %s %s body=%s", request.method, path, body)

    route = ROUTES.get(path)
    if route is None:
        return httpx.Response(
            404,
            json={
                "success": False,
                "errors": ["not_implemented"],
                "hint": f"No fake handler for {path}. Add one in evals/fake_server.py.",
            },
        )
    return httpx.Response(200, json=route(body))


def install(ashby_client) -> None:
    """Replace the client's real AsyncClient with one backed by the fake.

    Call this before any tool dispatch in an eval run. Idempotent; if the
    client has no key configured, injects a dummy one so `connect()` passes.
    """
    if ashby_client.api_key is None:
        ashby_client.api_key = "eval-dummy-key"
        ashby_client.headers = {"Content-Type": "application/json"}
    ashby_client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

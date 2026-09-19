"""Tests for the runtime tool policy — read-only mode, upload confinement,
and the MCP tool annotations that classify every tool.

Policy is env-driven and uncached, so each test sets exactly the knobs it
needs; conftest resets them all to the permissive stdio defaults first.
"""

import pytest

from ashby import policy
from ashby.tools import (
    _HINTS,
    ALL_TOOL_NAMES,
    LOCAL_FILE_TOOLS,
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
    all_tools,
    tool_blocked_reason,
)

BASE = "https://api.ashbyhq.com"


# ---------------------------------------------------------------------------
# Catalog classification + annotations
# ---------------------------------------------------------------------------


def test_every_tool_is_classified_and_nothing_is_stale():
    assert set(_HINTS) == ALL_TOOL_NAMES
    assert LOCAL_FILE_TOOLS <= WRITE_TOOLS
    assert READ_ONLY_TOOLS | WRITE_TOOLS == ALL_TOOL_NAMES


def test_read_only_classification_matches_tool_naming():
    """Read-only tools are exactly the list_/get_/search_ ones — a write
    tool slipping into READ_ONLY (or the reverse) fails here."""
    for name in ALL_TOOL_NAMES:
        expected = name.startswith(("list_", "get_", "search_"))
        assert (name in READ_ONLY_TOOLS) is expected, name


def test_annotations_are_published_on_every_tool():
    """The hints must survive serialisation on whichever mcp is installed —
    a typed field on mcp >= 1.6, an extra field on older releases."""
    for tool in all_tools():
        hints = tool.model_dump(by_alias=True, exclude_none=True)["annotations"]
        assert {"readOnlyHint", "destructiveHint", "idempotentHint"} <= set(hints), tool.name
        assert hints["readOnlyHint"] is (tool.name in READ_ONLY_TOOLS), tool.name
        if hints["readOnlyHint"]:
            assert hints["destructiveHint"] is False, tool.name


@pytest.mark.parametrize(
    "name",
    [
        "anonymize_candidate",
        "set_job_status",
        "cancel_interview_schedule",
        "change_application_stage",
        "transfer_application",
    ],
)
def test_irreversible_tools_are_flagged_destructive(name):
    assert _HINTS[name].read_only is False
    assert _HINTS[name].destructive is True


# ---------------------------------------------------------------------------
# Defaults — stdio, everything on
# ---------------------------------------------------------------------------


def test_default_policy_exposes_everything():
    assert {t.name for t in all_tools()} == ALL_TOOL_NAMES
    assert all(tool_blocked_reason(name) is None for name in ALL_TOOL_NAMES)


def test_unknown_tool_is_not_a_policy_matter():
    assert tool_blocked_reason("definitely_not_a_tool") is None


# ---------------------------------------------------------------------------
# ASHBY_READ_ONLY
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_read_only_truthy_values(monkeypatch, value):
    monkeypatch.setenv("ASHBY_READ_ONLY", value)
    assert policy.read_only_mode() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_read_only_falsy_values(monkeypatch, value):
    monkeypatch.setenv("ASHBY_READ_ONLY", value)
    assert policy.read_only_mode() is False


def test_read_only_mode_hides_write_tools(monkeypatch):
    monkeypatch.setenv("ASHBY_READ_ONLY", "1")
    exposed = {t.name for t in all_tools()}
    assert exposed == READ_ONLY_TOOLS
    assert not exposed & WRITE_TOOLS


@pytest.mark.parametrize(
    "name,args",
    [
        ("anonymize_candidate", {"candidateId": "c1"}),
        ("set_job_status", {"jobId": "j1", "status": "Archived"}),
        ("cancel_interview_schedule", {"id": "s1"}),
        ("change_application_stage", {"applicationId": "a1", "interviewStageId": "st1"}),
        ("transfer_application", {"applicationId": "a1", "jobId": "j2"}),
        ("create_candidate", {"name": "Ada"}),
        ("upload_candidate_file", {"candidateId": "c1", "file_path": "/etc/passwd"}),
    ],
)
async def test_read_only_mode_rejects_write_tools_in_dispatch(monkeypatch, httpx_mock, call_tool, name, args):
    monkeypatch.setenv("ASHBY_READ_ONLY", "1")
    result = await call_tool(name, args)
    assert isinstance(result, str), result
    assert "read-only" in result
    assert httpx_mock.get_requests() == []  # nothing left the process


async def test_read_only_mode_still_serves_reads(monkeypatch, httpx_mock, call_tool):
    monkeypatch.setenv("ASHBY_READ_ONLY", "1")
    httpx_mock.add_response(method="POST", url=f"{BASE}/job.list", json={"success": True, "results": []})
    assert await call_tool("list_jobs", {}) == {"success": True, "results": []}


# ---------------------------------------------------------------------------
# Uploads over the HTTP transport
# ---------------------------------------------------------------------------


def test_http_transport_hides_upload_tools(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    exposed = {t.name for t in all_tools()}
    assert exposed == ALL_TOOL_NAMES - LOCAL_FILE_TOOLS


@pytest.mark.parametrize("name", sorted(LOCAL_FILE_TOOLS))
async def test_http_transport_rejects_uploads_before_touching_the_file(
    monkeypatch, httpx_mock, call_tool, tmp_path, name
):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    secret = tmp_path / "environ"
    secret.write_text("ASHBY_API_KEY=hunter2")
    result = await call_tool(name, {"candidateId": "c1", "file_path": str(secret)})
    assert isinstance(result, str), result
    assert "ASHBY_UPLOAD_DIR" in result
    assert httpx_mock.get_requests() == []


def test_http_transport_with_upload_dir_exposes_upload_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("ASHBY_UPLOAD_DIR", str(tmp_path))
    assert LOCAL_FILE_TOOLS <= {t.name for t in all_tools()}


def test_read_only_wins_over_upload_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("ASHBY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("ASHBY_READ_ONLY", "1")
    assert {t.name for t in all_tools()} == READ_ONLY_TOOLS


# ---------------------------------------------------------------------------
# ASHBY_UPLOAD_DIR confinement
# ---------------------------------------------------------------------------


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "resume.pdf").write_bytes(b"%PDF-1.4 inside")
    (tmp_path / "secret.txt").write_text("outside")
    monkeypatch.setenv("ASHBY_UPLOAD_DIR", str(root))
    return root


def test_resolve_upload_path_accepts_files_inside(upload_dir):
    inside = str((upload_dir / "resume.pdf").resolve())
    assert policy.resolve_upload_path(str(upload_dir / "resume.pdf")) == inside
    # Relative paths resolve inside the directory, `..` included as long as it stays inside.
    assert policy.resolve_upload_path("resume.pdf") == inside
    assert policy.resolve_upload_path("./sub/../resume.pdf") == inside


@pytest.mark.parametrize(
    "path",
    [
        "{outside}",  # absolute path elsewhere
        "../secret.txt",  # traversal
        "/etc/passwd",
        "/proc/self/environ",
        "{root}-other/x.pdf",  # string-prefix collision: uploads-other is not inside uploads
    ],
)
def test_resolve_upload_path_refuses_escapes(upload_dir, tmp_path, path):
    path = path.format(outside=tmp_path / "secret.txt", root=upload_dir)
    with pytest.raises(PermissionError):
        policy.resolve_upload_path(path)


def test_resolve_upload_path_refuses_symlink_escape(upload_dir, tmp_path):
    (upload_dir / "link.txt").symlink_to(tmp_path / "secret.txt")
    with pytest.raises(PermissionError):
        policy.resolve_upload_path(str(upload_dir / "link.txt"))
    with pytest.raises(PermissionError):
        policy.resolve_upload_path("link.txt")


async def test_confined_upload_goes_through(upload_dir, monkeypatch, httpx_mock, call_tool):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    httpx_mock.add_response(
        method="POST", url=f"{BASE}/candidate.uploadResume", json={"success": True, "results": {}}
    )
    await call_tool("upload_candidate_resume", {"candidateId": "c1", "file_path": "resume.pdf"})
    req = httpx_mock.get_request()
    assert b"%PDF-1.4 inside" in req.content
    assert b'filename="resume.pdf"' in req.content


async def test_upload_dir_confines_stdio_too(upload_dir, tmp_path, httpx_mock, call_tool):
    result = await call_tool(
        "upload_candidate_file", {"candidateId": "c1", "file_path": str(tmp_path / "secret.txt")}
    )
    assert isinstance(result, str), result
    assert "ASHBY_UPLOAD_DIR" in result
    assert httpx_mock.get_requests() == []


def test_stdio_without_upload_dir_is_unconfined(tmp_path):
    """The user's own machine — the intended design for the stdio transport."""
    anywhere = tmp_path / "anywhere.pdf"
    assert policy.resolve_upload_path(str(anywhere)) == str(anywhere)

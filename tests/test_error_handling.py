"""Tests for error surfacing, logging, and connection-lifecycle behavior.

These tests pin the debuggability contract we want from the server:
- When Ashby returns an HTTP error, the response body should be surfaced
  to the caller (not lost in a generic "400 Bad Request" string).
- When a tool is invoked without a configured API key, the caller gets
  a clean error message rather than a crash.
- Successful calls are logged at INFO level so operators can see
  activity; failures are logged at ERROR with enough context to debug.
- At the MCP layer, a failure is a real error result (`isError: true`)
  with the readable message as its content — not content that a client
  or agent loop would take for a successful result.
"""

import logging
from contextlib import asynccontextmanager

import pytest
from tenacity import wait_none

BASE = "https://api.ashbyhq.com"


def _ok(httpx_mock, endpoint: str):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}{endpoint}",
        json={"success": True, "results": {}},
    )


@pytest.fixture
def no_retry_backoff(ashby_client, monkeypatch):
    """Zero out tenacity's exponential backoff for the duration of one test.

    `_make_request` is wrapped by `@retry(wait=wait_exponential(...))`.
    tenacity exposes that policy as `.retry` on the wrapped function and
    copies it on every call, so swapping `wait` here takes effect on the
    next request and monkeypatch restores the real backoff afterwards.
    Without this, a test that exhausts all 4 attempts sleeps ~7 s of
    real time (1 + 2 + 4 s) for no extra coverage.
    """
    monkeypatch.setattr(ashby_client._make_request.retry, "wait", wait_none())


# ---------------------------------------------------------------------------
# HTTP error body preservation
# ---------------------------------------------------------------------------


async def test_http_400_body_preserved(httpx_mock, call_tool):
    """A 4xx response with a structured error body should have that body
    surfaced to the caller, not flattened to the HTTPStatusError repr."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.search",
        status_code=400,
        json={"success": False, "errors": ["bad_input"], "errorInfo": {"reason": "name_too_short"}},
    )
    result = await call_tool("search_candidates", {"name": ""})
    # The caller sees a string (error path). The body's error detail must appear in it.
    assert isinstance(result, str), f"expected error string, got {type(result).__name__}"
    assert "bad_input" in result or "name_too_short" in result, (
        f"structured error body was not surfaced. Got: {result!r}"
    )


async def test_http_500_body_preserved_after_retries(httpx_mock, call_tool, no_retry_backoff):
    """After retries are exhausted, a 5xx body should still be surfaced."""
    # Tenacity retries up to 4 attempts total on 5xx.
    for _ in range(4):
        httpx_mock.add_response(
            method="POST",
            url=f"{BASE}/candidate.search",
            status_code=503,
            json={"success": False, "errors": ["service_unavailable"]},
        )
    result = await call_tool("search_candidates", {"name": "x"})
    assert isinstance(result, str)
    assert "service_unavailable" in result or "503" in result
    # All four attempts were actually made (not short-circuited by the patch).
    assert len(httpx_mock.get_requests()) == 4


# ---------------------------------------------------------------------------
# Missing / unconfigured API key
# ---------------------------------------------------------------------------


async def test_missing_api_key_returns_clean_error(call_tool, ashby_client, monkeypatch):
    """If the client has no api_key (user forgot to set ASHBY_API_KEY),
    the caller should see a helpful error — not a traceback.

    Because connect() now runs lazily on first use, we clear both the
    env var AND the cached key to simulate the 'never configured' state.
    """
    monkeypatch.delenv("ASHBY_API_KEY", raising=False)
    original = ashby_client.api_key
    ashby_client.api_key = None
    try:
        result = await call_tool("search_candidates", {"name": "x"})
        assert isinstance(result, str)
        lowered = result.lower()
        assert "api" in lowered or "connect" in lowered or "key" in lowered, (
            f"error text should mention the missing key/connection. Got: {result!r}"
        )
    finally:
        ashby_client.api_key = original


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


async def test_successful_call_is_logged(httpx_mock, call_tool, caplog):
    """Every tool invocation should leave an INFO-level breadcrumb under
    the `ashby` logger so operators can trace activity on Render."""
    _ok(httpx_mock, "/candidate.search")
    with caplog.at_level(logging.INFO, logger="ashby"):
        await call_tool("search_candidates", {"name": "Ada"})
    messages = [r.getMessage() for r in caplog.records if r.name.startswith("ashby")]
    assert any("candidate.search" in m or "search_candidates" in m for m in messages), (
        f"expected an INFO log mentioning the endpoint or tool. Got: {messages!r}"
    )


async def test_failure_is_logged_with_detail(httpx_mock, call_tool, caplog):
    """When a call fails, the logger should capture enough detail to
    debug — status code and/or response body."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.search",
        status_code=400,
        json={"success": False, "errors": ["bad_input"]},
    )
    with caplog.at_level(logging.WARNING, logger="ashby"):
        await call_tool("search_candidates", {"name": ""})
    records = [r for r in caplog.records if r.name.startswith("ashby")]
    assert records, "expected at least one warning/error log for the 400 response"
    combined = " ".join(r.getMessage() for r in records)
    assert "400" in combined or "bad_input" in combined, (
        f"expected failure log to mention status or error body. Got: {combined!r}"
    )


# ---------------------------------------------------------------------------
# MCP layer — failures must arrive as `isError: true` results
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _mcp_session():
    """A real `ClientSession` connected to the ashby server over in-memory
    streams — the same initialize/call_tool handshake a stdio or SSE client
    performs, minus the transport.

    A plain context manager rather than an async fixture: the anyio task
    group inside must be entered and exited from the same task, which
    pytest-asyncio does not guarantee for generator fixtures.
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    from ashby.server import server

    async with create_connected_server_and_client_session(server) as client:
        yield client


async def test_mcp_unknown_tool_is_error_result():
    """`dispatch` used to catch everything and return "Error executing …"
    as ordinary content, so the CallToolResult said `isError: false` and
    agent loops treated the failure as a success."""
    async with _mcp_session() as client:
        result = await client.call_tool("definitely_not_a_tool", {})
    assert result.isError is True
    assert "Unknown tool" in result.content[0].text


async def test_mcp_http_4xx_is_error_result(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.search",
        status_code=403,
        json={
            "success": False,
            "errors": ["forbidden"],
            "errorInfo": {"message": "missing scope: candidates:read"},
        },
    )
    async with _mcp_session() as client:
        result = await client.call_tool("search_candidates", {"name": "Ada"})
    assert result.isError is True
    text = result.content[0].text
    # The message stays human-readable so the model can recover from it.
    assert "403" in text
    assert "missing scope: candidates:read" in text


async def test_mcp_success_false_envelope_is_error_result(httpx_mock):
    """HTTP 200 + `success: false` is how Ashby reports validation and
    permission errors; it must be an MCP error too, not a successful result."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/candidate.search",
        status_code=200,
        json={"success": False, "errors": ["invalid_input"]},
    )
    async with _mcp_session() as client:
        result = await client.call_tool("search_candidates", {"name": ""})
    assert result.isError is True
    text = result.content[0].text
    assert text.startswith("Ashby returned an error")
    assert "invalid_input" in text


async def test_mcp_success_is_not_error_result(httpx_mock):
    """Control: a normal response still comes back with `isError: false`."""
    _ok(httpx_mock, "/candidate.search")
    async with _mcp_session() as client:
        result = await client.call_tool("search_candidates", {"name": "Ada"})
    assert result.isError is False
    assert result.content[0].text.startswith("Search results: ")

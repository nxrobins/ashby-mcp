"""Tests for error surfacing, logging, and connection-lifecycle behavior.

These tests pin the debuggability contract we want from the server:
- When Ashby returns an HTTP error, the response body should be surfaced
  to the caller (not lost in a generic "400 Bad Request" string).
- When a tool is invoked without a configured API key, the caller gets
  a clean error message rather than a crash.
- Successful calls are logged at INFO level so operators can see
  activity; failures are logged at ERROR with enough context to debug.
"""

import json
import logging

import pytest

BASE = "https://api.ashbyhq.com"


def _ok(httpx_mock, endpoint: str):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}{endpoint}",
        json={"success": True, "results": {}},
    )


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


async def test_http_500_body_preserved_after_retries(httpx_mock, call_tool):
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

"""Shared fixtures for the Ashby MCP test suite.

`pytest-httpx` intercepts outbound HTTP traffic — no real API calls
leave the process. A dummy ASHBY_API_KEY is set so the client's lazy
connect() succeeds; the value doesn't matter because the mock never
validates it. Live tests (marked `live`) pick up the real key from
the environment.
"""

import json
import os

import pytest

os.environ.setdefault("ASHBY_API_KEY", "test-key-not-real")
# Routing tests assert on structured JSON output. Formatter tests opt into
# markdown mode via `monkeypatch.setenv("ASHBY_OUTPUT", "markdown")`.
os.environ.setdefault("ASHBY_OUTPUT", "json")

from ashby.client import ashby_client as _module_client  # noqa: E402
from ashby.handlers import ToolError, dispatch  # noqa: E402


@pytest.fixture
def call_tool():
    """Async helper that invokes the tool dispatcher and returns the
    parsed JSON body of its text response.

    The dispatcher wraps every response as `[TextContent(text="<prefix>: <json>")]`
    and raises `ToolError` — whose message is `"<prefix>: <detail>"` — on
    failure. Either way we strip the prefix and return the decoded JSON so
    tests can assert on shape; a detail that isn't JSON (HTTP errors,
    unknown tools) comes back as the full error text. Tests about the
    error/success distinction itself call `dispatch` directly under
    `pytest.raises(ToolError)`.
    """

    async def _call(name: str, arguments: dict | None = None) -> dict | str:
        try:
            result = await dispatch(name, arguments or {})
        except ToolError as e:
            text = str(e)
        else:
            assert len(result) == 1
            text = result[0].text
        _, _, body = text.partition(": ")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            # Error text that isn't a JSON envelope; surface it directly.
            return text

    return _call


@pytest.fixture
def ashby_client():
    """The module-level AshbyClient — re-used so tests can inspect it."""
    return _module_client

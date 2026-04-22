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

from ashby.client import ashby_client as _module_client  # noqa: E402
from ashby.handlers import dispatch  # noqa: E402


@pytest.fixture
def call_tool():
    """Async helper that invokes the tool dispatcher and returns the
    parsed JSON body of its text response.

    The dispatcher wraps every response as `[TextContent(text="<prefix>: <json>")]`.
    We strip the prefix and return the decoded JSON so tests can assert on shape.
    """

    async def _call(name: str, arguments: dict | None = None) -> dict | str:
        result = await dispatch(name, arguments or {})
        assert len(result) == 1
        text = result[0].text
        _, _, body = text.partition(": ")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            # Error branch returns plain text; surface it directly.
            return text

    return _call


@pytest.fixture
def ashby_client():
    """The module-level AshbyClient — re-used so tests can inspect it."""
    return _module_client

"""Tests for the HTTP+SSE transport — bearer auth, fail-closed startup, health.

The app comes from build_http_app() and is driven with starlette's
TestClient, so nothing binds a port. A valid token on `/sse` would open a
never-ending event stream, so "the gate lets a valid token through" is
asserted on `/messages/`, where the SSE transport answers 400 (no
session_id) as soon as auth has passed.
"""

from importlib.metadata import PackageNotFoundError, version

import pytest
from mcp.server import Server
from starlette.testclient import TestClient

from ashby import transport
from ashby.transport import (
    bearer_authorized,
    build_http_app,
    is_loopback_host,
    resolve_bearer_token,
    run_http,
)

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_http_app(Server("ashby-test"), TOKEN))


@pytest.fixture
def open_client() -> TestClient:
    """Open mode — what resolve_bearer_token() hands out on a loopback bind."""
    return TestClient(build_http_app(Server("ashby-test"), None))


@pytest.fixture
def no_auth_env(monkeypatch):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


def test_healthz_is_public_and_reports_auth(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "auth_required": True}


def test_healthz_reports_open_mode(open_client):
    assert open_client.get("/healthz").json() == {"ok": True, "auth_required": False}


# ---------------------------------------------------------------------------
# /sse
# ---------------------------------------------------------------------------


def test_sse_without_token_is_401(client):
    r = client.get("/sse")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": f"Bearer {TOKEN[:-1]}"},  # one char short
        {"Authorization": f"Bearer {TOKEN}x"},  # one char long
        {"Authorization": f"Basic {TOKEN}"},  # wrong scheme
        {"Authorization": TOKEN},  # no scheme
        {"X-Api-Key": TOKEN},  # wrong header
    ],
)
def test_sse_with_bad_credentials_is_401(client, headers):
    assert client.get("/sse", headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# /messages/
# ---------------------------------------------------------------------------


def test_messages_without_token_is_401(client):
    r = client.post("/messages/?session_id=" + "0" * 32, json={})
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}
    assert r.headers["www-authenticate"] == "Bearer"


def test_messages_with_wrong_token_is_401(client):
    r = client.post("/messages/", headers=_bearer("wrong-token"), json={})
    assert r.status_code == 401


def test_messages_with_valid_token_reaches_sse_transport(client):
    """Once auth passes, the SSE transport itself answers (400: no session_id)."""
    r = client.post("/messages/", headers=_bearer(TOKEN), json={})
    assert r.status_code == 400
    assert b"session_id" in r.content


def test_open_mode_lets_messages_through(open_client):
    assert open_client.post("/messages/", json={}).status_code == 400


# ---------------------------------------------------------------------------
# bearer_authorized — the comparison behind both routes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,ok",
    [
        (f"Bearer {TOKEN}", True),
        (f"bearer {TOKEN}", True),  # scheme is case-insensitive (RFC 7235)
        (f"  Bearer {TOKEN}  ", True),
        (f"Bearer {TOKEN[:-1]}", False),
        (f"Bearer {TOKEN}x", False),
        ("Bearer wrong", False),
        (f"Basic {TOKEN}", False),
        (TOKEN, False),
        ("Bearer ", False),
        ("", False),
        (None, False),
    ],
)
def test_bearer_authorized(header, ok):
    assert bearer_authorized(header, TOKEN) is ok


def test_bearer_authorized_never_accepts_an_empty_expected_token():
    assert bearer_authorized("Bearer ", "") is False
    assert bearer_authorized("Bearer x", "") is False


# ---------------------------------------------------------------------------
# Fail-closed startup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host,loopback",
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("::1", True),
        ("[::1]", True),
        ("0.0.0.0", False),
        ("::", False),
        ("10.0.0.5", False),
        ("ashby-mcp.internal", False),
        ("", False),
    ],
)
def test_is_loopback_host(host, loopback):
    assert is_loopback_host(host) is loopback


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.0.0.5", "ashby-mcp.internal"])
def test_no_token_on_public_bind_refuses_to_start(no_auth_env, host):
    with pytest.raises(SystemExit) as exc:
        resolve_bearer_token(host)
    assert "MCP_BEARER_TOKEN" in str(exc.value)
    assert exc.value.code  # non-zero exit status


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_blank_token_counts_as_unset(no_auth_env, monkeypatch, value):
    monkeypatch.setenv("MCP_BEARER_TOKEN", value)
    with pytest.raises(SystemExit):
        resolve_bearer_token("0.0.0.0")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_no_token_on_loopback_runs_open(no_auth_env, host):
    assert resolve_bearer_token(host) is None


def test_allow_insecure_is_the_only_escape_hatch(no_auth_env, monkeypatch):
    monkeypatch.setenv("MCP_ALLOW_INSECURE", "1")
    assert resolve_bearer_token("0.0.0.0") is None
    monkeypatch.setenv("MCP_ALLOW_INSECURE", "0")
    with pytest.raises(SystemExit):
        resolve_bearer_token("0.0.0.0")


def test_configured_token_is_returned_stripped(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", f"  {TOKEN}\n")
    assert resolve_bearer_token("0.0.0.0") == TOKEN


async def test_run_http_refuses_public_bind_without_token(no_auth_env):
    """End to end: run_http() bails before it builds the app or binds a port."""
    with pytest.raises(SystemExit) as exc:
        await run_http(Server("ashby-test"), "0.0.0.0", 8000)
    assert "MCP_BEARER_TOKEN" in str(exc.value)


# ---------------------------------------------------------------------------
# Server metadata advertised during `initialize` (from PR #11)
# ---------------------------------------------------------------------------


def test_server_version_matches_installed_distribution():
    assert transport.server_version() == version("mcp-ashby-connector")
    assert transport.server_version() != transport._DEV_VERSION


def test_server_version_falls_back_when_not_installed(monkeypatch):
    def _missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(transport, "version", _missing)
    assert transport.server_version() == "0.0.0+dev"


def test_init_options_advertise_name_and_version():
    opts = transport._init_options(Server("test"))
    assert opts.server_name == "ashby-mcp"
    assert opts.server_version == transport.server_version()

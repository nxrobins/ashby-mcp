"""Transport layer — stdio (for Claude Code) and HTTP+SSE (for Claude Cowork / Render)."""

import hmac
import ipaddress
import logging
import os
from importlib.metadata import PackageNotFoundError, version

import mcp.server.stdio
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from . import policy

logger = logging.getLogger("ashby.transport")

_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
# Distribution name from pyproject.toml `[project] name`.
_DIST_NAME = "mcp-ashby-connector"
_DEV_VERSION = "0.0.0+dev"


def server_version() -> str:
    """The version advertised to MCP clients during `initialize`.

    Read from the installed distribution's metadata so it tracks
    `pyproject.toml` automatically. Falls back to a dev marker when the
    package isn't installed (e.g. running straight from a checkout with
    `src/` on PYTHONPATH).
    """
    try:
        return version(_DIST_NAME)
    except PackageNotFoundError:
        return _DEV_VERSION


def _init_options(server: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name="ashby-mcp",
        server_version=server_version(),
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


async def run_stdio(server: Server) -> None:
    """Run the MCP server over stdio — for Claude Code and other local clients."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, _init_options(server))


# ---------------------------------------------------------------------------
# HTTP+SSE — auth
# ---------------------------------------------------------------------------


def is_loopback_host(host: str) -> bool:
    """True only for binds that cannot be reached from another machine.

    Anything that is not provably loopback (0.0.0.0, ::, a LAN address, a
    hostname we can't resolve here) counts as public, so the caller fails
    closed.
    """
    host = host.strip().strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_bearer_token(host: str) -> str | None:
    """Return the bearer token the HTTP transport must enforce.

    Fails closed: with no token configured the server only starts on a
    loopback bind, or when MCP_ALLOW_INSECURE=1 says the operator really
    wants an open server (local testing). Either way it then runs open and
    returns None. Any other bind without a token raises SystemExit with a
    clear message, so a deploy that forgot MCP_BEARER_TOKEN never comes up
    on the public internet with a live Ashby key.

    An empty or whitespace-only MCP_BEARER_TOKEN counts as unset.
    """
    token = (os.getenv("MCP_BEARER_TOKEN") or "").strip()
    if token:
        return token
    if is_loopback_host(host) or policy.env_flag("MCP_ALLOW_INSECURE"):
        return None
    raise SystemExit(
        f"ashby-mcp: refusing to start the HTTP transport on {host!r} without MCP_BEARER_TOKEN. "
        "Set MCP_BEARER_TOKEN to a long random secret (e.g. `openssl rand -hex 24`), "
        "bind to 127.0.0.1 instead, or set MCP_ALLOW_INSECURE=1 to run without auth "
        "for local testing."
    )


def bearer_authorized(authorization: str | None, expected_token: str) -> bool:
    """Constant-time check of an `Authorization: Bearer <token>` header value."""
    if not authorization or not expected_token:
        return False
    scheme, _, credential = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(credential.strip().encode("utf-8"), expected_token.encode("utf-8"))


# ---------------------------------------------------------------------------
# HTTP+SSE — app
# ---------------------------------------------------------------------------


def build_http_app(server: Server, bearer_token: str | None):
    """Build the Starlette app for the HTTP+SSE transport.

    `bearer_token` is the secret every `/sse` and `/messages/` request must
    present; `None` means open mode, which only resolve_bearer_token() is
    allowed to decide. `/healthz` is always unauthenticated and reports
    whether auth is on. Split out of run_http() so tests can drive the app
    with starlette's TestClient without binding a port.
    """
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.datastructures import Headers
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route

    sse = SseServerTransport("/messages/")
    auth_required = bearer_token is not None

    def _authorized(authorization: str | None) -> bool:
        if not auth_required:
            return True
        return bearer_authorized(authorization, bearer_token)

    def _unauthorized() -> Response:
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def handle_sse(request: Request) -> Response:
        if not _authorized(request.headers.get("authorization")):
            return _unauthorized()
        # connect_sse owns the response lifecycle.
        async with sse.connect_sse(request.scope, request.receive, request._send) as (
            read_stream,
            write_stream,
        ):
            await server.run(read_stream, write_stream, _init_options(server))
        return Response()

    async def handle_messages(scope, receive, send) -> None:
        # Mount hands us raw ASGI rather than a Request.
        if not _authorized(Headers(scope=scope).get("authorization")):
            await _unauthorized()(scope, receive, send)
            return
        await sse.handle_post_message(scope, receive, send)

    async def healthz(_request: Request) -> Response:
        return JSONResponse({"ok": True, "auth_required": auth_required})

    return Starlette(
        routes=[
            Route("/healthz", endpoint=healthz),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=handle_messages),
        ]
    )


async def run_http(server: Server, host: str, port: int) -> None:
    """Run the MCP server over HTTP+SSE — for Claude Cowork and other
    remote clients.

    Auth: every request to `/sse` and `/messages/` must carry
    `Authorization: Bearer <MCP_BEARER_TOKEN>`. Without a token the server
    refuses to start unless bound to loopback or MCP_ALLOW_INSECURE=1 is
    set (see resolve_bearer_token). Tool exposure over HTTP is further
    restricted by policy.py (uploads off unless ASHBY_UPLOAD_DIR, writes
    off under ASHBY_READ_ONLY).
    """
    import uvicorn

    bearer_token = resolve_bearer_token(host)
    if bearer_token is None:
        logger.warning(
            "MCP_BEARER_TOKEN is not set — serving %s:%d WITHOUT authentication "
            "(only acceptable for local testing)",
            host,
            port,
        )
    app = build_http_app(server, bearer_token)

    # access_log=False: uvicorn's access lines would print every request
    # target, and the MCP client's POSTs carry `?session_id=...`, which is
    # enough to inject messages into a live session. Tool activity is
    # still logged by the dispatcher.
    config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    await uvicorn.Server(config).serve()

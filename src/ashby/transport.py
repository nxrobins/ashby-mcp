"""Transport layer — stdio (for Claude Code) and HTTP+SSE (for Claude Cowork / Render)."""

import os

import mcp.server.stdio
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions


def _init_options(server: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name="ashby-mcp",
        server_version="0.1.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


async def run_stdio(server: Server) -> None:
    """Run the MCP server over stdio — for Claude Code and other local clients."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, _init_options(server))


async def run_http(server: Server, host: str, port: int) -> None:
    """Run the MCP server over HTTP+SSE — for Claude Cowork and other
    remote clients.

    Auth: if `MCP_BEARER_TOKEN` is set, every request must include
    `Authorization: Bearer <token>`. If unset, the server runs open —
    only do that for local testing.
    """
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route
    import uvicorn

    sse = SseServerTransport("/messages/")
    expected_token = os.getenv("MCP_BEARER_TOKEN")

    def _unauthorized() -> Response:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    def _check_auth(request: Request) -> Response | None:
        if not expected_token:
            return None  # auth disabled
        header = request.headers.get("authorization", "")
        if header != f"Bearer {expected_token}":
            return _unauthorized()
        return None

    async def handle_sse(request: Request) -> Response:
        if (err := _check_auth(request)) is not None:
            return err
        # connect_sse owns the response lifecycle.
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, _init_options(server))
        return Response()

    async def handle_messages(scope, receive, send) -> None:
        # Manual auth check — Mount gives us raw ASGI, not a Request.
        if expected_token:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if headers.get("authorization", "") != f"Bearer {expected_token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await sse.handle_post_message(scope, receive, send)

    async def healthz(_request: Request) -> Response:
        return JSONResponse({"ok": True, "auth_required": bool(expected_token)})

    app = Starlette(
        routes=[
            Route("/healthz", endpoint=healthz),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=handle_messages),
        ]
    )

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    await uvicorn.Server(config).serve()

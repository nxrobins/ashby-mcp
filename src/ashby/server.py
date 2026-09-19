"""MCP server wiring — creates the Server instance, registers the tool
list and the tool dispatcher, and dispatches run() to the right transport.

Entry point is `ashby.main` (the `ashby-mcp` console script), which calls
`run()` below. This module uses relative imports and is not runnable as a
standalone script.

The heavy lifting lives in sibling modules:
  - tools.py      — tool schemas (what LLMs see)
  - handlers.py   — tool dispatcher (what runs)
  - client.py     — Ashby HTTP client
  - transport.py  — stdio / HTTP+SSE transports
"""

import os

from dotenv import load_dotenv
from mcp.server import Server

from . import policy
from .handlers import dispatch
from .tools import all_tools
from .transport import run_http, run_stdio

load_dotenv()

server = Server("ashby-mcp")


@server.list_tools()
async def handle_list_tools():
    return all_tools()


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    # A failed call raises `ToolError` out of this handler on purpose. The
    # SDK (every mcp 1.x release) turns an exception raised here into
    # `CallToolResult(isError=True)` carrying `str(exc)`; catching it and
    # returning the message as content would make the failure look like a
    # success to the client (`isError: false`).
    return await dispatch(name, arguments)


async def run() -> None:
    """Dispatch to stdio (default) or http transport based on MCP_TRANSPORT.

    Port selection for HTTP mode tries MCP_PORT first, then PORT (the
    convention used by Render, Heroku, Fly, Railway, etc.), then 8000.
    """
    if policy.is_http_transport():
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT") or os.getenv("PORT") or "8000")
        await run_http(server, host, port)
    else:
        await run_stdio(server)

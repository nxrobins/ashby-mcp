# /// script
# dependencies = [
#   "mcp",
#   "httpx",
#   "tenacity",
#   "python-dotenv"
# ]
# ///
"""MCP server wiring — creates the Server instance, registers the tool
list and the tool dispatcher, and dispatches run() to the right transport.

The heavy lifting lives in sibling modules:
  - tools.py      — tool schemas (what LLMs see)
  - handlers.py   — tool dispatcher (what runs)
  - client.py     — Ashby HTTP client
  - transport.py  — stdio / HTTP+SSE transports
"""

import asyncio
import os

from dotenv import load_dotenv
from mcp.server import Server

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
    return await dispatch(name, arguments)


async def run() -> None:
    """Dispatch to stdio (default) or http transport based on MCP_TRANSPORT.

    Port selection for HTTP mode tries MCP_PORT first, then PORT (the
    convention used by Render, Heroku, Fly, Railway, etc.), then 8000.
    """
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT") or os.getenv("PORT") or "8000")
        await run_http(server, host, port)
    else:
        await run_stdio(server)


if __name__ == "__main__":
    asyncio.run(run())

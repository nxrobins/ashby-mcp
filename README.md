# Ashby MCP Server

> Forked from [thnico/MCP-Ashby](https://github.com/thz/MCP-Ashby) — thanks to Nicolas Thouzeau for the original implementation.

A Model Context Protocol (MCP) server that exposes Ashby ATS operations to Claude. Point Claude Code (or any MCP-compatible client) at this server and you can manage candidates, jobs, applications, interviews, projects, and custom fields in natural language.

## What's included

42 tools across six areas:

- **Candidates** — create, search, list, get, update, notes, tags, projects, client info, anonymize, resume + file upload
- **Jobs** — create, search, list, get, update, set status (Open/Closed/Archived/Draft)
- **Applications** — create, list, get, update, change stage, change source, transfer, add/remove hiring team members
- **Interviews** — list interview-type definitions, schedule interview events, list/update/cancel schedules
- **Projects** — get, list, search (useful for attaching candidates)
- **Custom fields** — list (with client-side objectType filter), get, create, setValue (polymorphic by field type)

## Team setup (2 commands)

Each teammate does this once. No git, Python, or build tooling experience needed.

**Step 1 — install `uv`** (skip if already installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Step 2 — register the MCP server**, pasting the team Ashby API key where shown:

```bash
claude mcp add ashby -s user \
  -e ASHBY_API_KEY=PASTE_TEAM_KEY_HERE \
  -- uvx --from git+https://github.com/nxrobins/ashby-mcp ashby
```

That's it. Restart Claude Code, then run `claude mcp list` — you should see `ashby: ✓ Connected`. The Ashby tools will be available in every Claude Code session, not just one project.

`uvx` handles everything automatically: cloning the repo, creating a virtual env, installing dependencies, and running the server. On updates, teammates just restart Claude Code — `uvx` re-fetches on the next run if changes are available.

### Using it

In any Claude Code session, ask things like:
- *"List open jobs in Ashby"*
- *"Find all candidates tagged as referrals"*
- *"Show me the Candidate custom fields"*
- *"Move application `<id>` to the Offer stage"*
- *"Schedule an interview for application `<id>` tomorrow at 2pm with bob@company.com"*

### Permissions note

The shared team API key must have the right scopes in Ashby for the tools you use. At minimum the team key needs: candidates read + write, jobs read, projects read, and hiring-process metadata read (for custom fields). Interview tools additionally need "read interviews" — if you see a `403 Forbidden` from an interview tool, have an Ashby admin grant that scope on the team key.

## Using from Claude Cowork (browser)

Cowork runs in the browser and can't spawn local processes, so the stdio server above doesn't work there. The same code also runs as an HTTP/SSE server; you host it, teammates add it as a custom connector in Cowork.

### Deploy the server to Render (one-time, ~5 minutes)

A [`render.yaml`](render.yaml) blueprint is checked in — Render reads it and provisions everything automatically.

1. Sign up / log in at [render.com](https://render.com). The **free tier is sufficient** (the service sleeps after 15 min idle, cold-starts in ~30s on next use).
2. **Dashboard → New + → Blueprint → Connect a repository → pick `nxrobins/ashby-mcp`**.
3. Render shows the blueprint. Click **Apply**. It'll prompt for the two secret values:
   - `ASHBY_API_KEY` — your shared Ashby team API key
   - `MCP_BEARER_TOKEN` — a long random token (generate with `openssl rand -hex 24`) that teammates will paste into their Cowork connector config
4. Wait ~2 minutes for the first build to finish. Render gives you a URL like `https://ashby-mcp.onrender.com`.
5. Verify:

   ```bash
   curl https://ashby-mcp.onrender.com/healthz
   # → {"ok":true,"auth_required":true}
   ```

### Per-teammate setup in Cowork

1. In Cowork: **Customize → Connectors → Add custom connector**
2. **Name:** `Ashby`
3. **URL:** `https://ashby-mcp.onrender.com/sse` (note the `/sse` path)
4. **Authorization Token:** the `MCP_BEARER_TOKEN` value
5. Save. Ashby tools now appear in Cowork alongside the built-in ones.

### Security note

The bearer token is the only thing standing between the public internet and your Ashby workspace. Treat it like a password:
- Share via 1Password / Slack DM, not email or git.
- Rotate by changing `MCP_BEARER_TOKEN` in Render's dashboard → teammates update their Cowork connector config.
- Never log it, commit it, or put it in a docs page.

### Why not a free Cloudflare quick tunnel?

Quick tunnels buffer small SSE chunks, which breaks the MCP handshake (the initial `event: endpoint` never reaches the client). A **named** Cloudflare Tunnel with a custom domain works, but Render is simpler and equally free.

## Development

### Run the test suite

```bash
uv sync --group dev
uv run pytest                 # unit tests (mocked HTTP, no network)
uv run pytest -m live         # live smoke tests (requires ASHBY_API_KEY)
```

Unit tests cover every tool's routing and request shape. Live tests hit only read-only endpoints (`list_*`, `get_*`, `search_*`) so they can't corrupt workspace data; they exist to catch contract drift.

### Project layout

```
src/ashby/
  __init__.py       # entry point
  server.py         # AshbyClient + MCP tool definitions + dispatcher
tests/
  conftest.py       # shared fixtures
  test_routing.py   # unit tests (one per tool)
  test_live.py      # opt-in live smoke tests
openapi.json        # Ashby's full OpenAPI spec (reference for adding new tools)
```

## Adding a new tool

1. Find the endpoint in `openapi.json` (search by `/` prefix)
2. Add a `types.Tool(name=..., inputSchema=...)` entry in `handle_list_tools` in `server.py`
3. Add a matching `elif name == "..."` branch in `handle_call_tool`
4. Add a routing test in `tests/test_routing.py`
5. Restart Claude Code to reload the MCP subprocess

## Troubleshooting

- **`✗ Failed to connect` from `claude mcp list`** — usually means the shared folder path is wrong or `uv` isn't on your PATH. Run `uv --directory <SHARED_PATH> run ashby` manually; the error will tell you which.
- **`401 Unauthorized` on every tool** — the API key isn't being passed. Double-check the `-e ASHBY_API_KEY=...` flag in your registration.
- **`403 Forbidden` on specific tools** — permissions gap on the team key; ask an Ashby admin.
- **New tools aren't showing up** — MCP loads tools once at session start. Restart Claude Code.

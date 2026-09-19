# Ashby MCP Server

> Forked from [thnico/MCP-Ashby](https://github.com/thz/MCP-Ashby) — thanks to Nicolas Thouzeau for the original implementation.

A Model Context Protocol (MCP) server that exposes Ashby ATS operations to Claude. Point Claude Code (or any MCP-compatible client) at this server and you can manage candidates, jobs, applications, interviews, projects, sources, and custom fields in natural language.

## What's included

50 tools across seven areas:

- **Candidates** (15) — create, search, list, list all (auto-paginated up to 5,000, with a `truncated` marker and cursor when there are more), get, update, notes (create/list), tags (add/list), add to project, client info, anonymize, resume + file upload
- **Jobs** (6) — create, search, list, get, update, set status (Open/Closed/Archived/Draft)
- **Applications** (10) — create, list, get, update, change stage, change source, transfer, add/remove hiring team members, list interview feedback submissions
- **Interviews** (11) — list/get interview-type definitions, list interview plans, list/get interview stages, list stage groups, create a schedule, list/update/cancel schedules, list the events on a schedule
- **Projects** (3) — get, list, search (useful for attaching candidates)
- **Sources** (1) — list (discover sourceIds for `create_candidate` and `change_application_source`)
- **Custom fields** (4) — list (with client-side objectType filter), get, create, setValue (polymorphic by field type)

Tool inputs mirror Ashby's OpenAPI spec (`openapi.json`): fields Ashby requires are marked required, and parameters the endpoint doesn't accept aren't offered.

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
  -- uvx --from git+https://github.com/nxrobins/ashby-mcp ashby-mcp
```

That's it. Restart Claude Code, then run `claude mcp list` — you should see `ashby: ✓ Connected`. The Ashby tools will be available in every Claude Code session, not just one project.

`uvx` handles everything automatically: cloning the repo, creating a virtual env, installing dependencies, and running the server. On updates, teammates just restart Claude Code — `uvx` re-fetches on the next run if changes are available.

### Using it

The point of plugging Ashby into an LLM isn't the CRUD — it's the kind of workflows a recruiter can't reasonably do in the Ashby UI. A few things this is actually good for:

**Re-engagement campaigns**
- *"Find every candidate who reached onsite for any Engineering role in the last 18 months and was archived with reason 'timing', then group them by the role they were closest to fit for."*
- *"Pull silver-medalists from closed Sales roles in the last 12 months — I want to reconsider them for the new AE opening."*

**Detailed reports with full context**
- *"Build me a funnel report for Q1: apps → screens → onsites → offers → hires, broken down by source and by role. Include stage-to-stage conversion rates and flag any sources with <5% screen-to-onsite."*
- *"For every Engineering offer in the last 6 months, give me days-in-each-stage, source, and whether there's a referral relationship."*

**Narrative building on historical pipelines**
- *"Walk me through how the Head of Product search actually played out — who we saw, where each drop-off happened, what the hiring team's written feedback looks like stage-to-stage, and where the eventual hire entered the process."*
- *"Summarize the last three Design Lead searches as a case study — what was the source mix, how long did each take, what were the common archive reasons?"*

**Personalized outreach**
- *"Draft a re-engagement email for candidate `<id>` — reference their last application, the role they almost landed, and anything in the notes from the hiring manager that would ring true to them. Keep it to 120 words."*
- *"Pull the top 10 archived-silver candidates for the Staff Eng role and draft a tailored outreach for each based on their notes, resume highlights, and stage they reached."*

**Everyday operational asks** also work:
- *"List open jobs in Ashby"*, *"Show me the Candidate custom fields"*, *"Move application `<id>` to the Offer stage"*, *"Schedule an interview for application `<id>` tomorrow at 2pm with bob@company.com"*

### Permissions note

The shared team API key must have the right scopes in Ashby for the tools you use. At minimum the team key needs: candidates read + write, jobs read, projects read, and hiring-process metadata read (for custom fields). Interview tools additionally need "read interviews" — if you see a `403 Forbidden` from an interview tool, have an Ashby admin grant that scope on the team key.

## Configuration

Everything is configured through environment variables. In Claude Code, pass them as `-e KEY=VALUE` flags on `claude mcp add`; on Render, set them on the service.

| Variable | Default | Purpose |
|---|---|---|
| `ASHBY_API_KEY` | — | **Required.** Ashby API key, sent as HTTP Basic auth. |
| `ASHBY_OUTPUT` | `markdown` | Tool output format. `markdown` renders list results as compact tables and single records as labeled sections — fewer tokens, easier to scan in a transcript. Set `json` to get Ashby's raw JSON envelope instead, e.g. for programmatic consumers or when you need a field the tables leave out. |
| `MCP_TRANSPORT` | `stdio` | `stdio` for local clients such as Claude Code; `http` for the HTTP/SSE server used by Cowork / Render. |
| `MCP_HOST`, `MCP_PORT` | `127.0.0.1`, `8000` | Bind address for the HTTP transport. `PORT` is honored as a fallback for `MCP_PORT` (the Render / Heroku / Fly convention). |
| `MCP_BEARER_TOKEN` | unset | HTTP transport only. When set, every request must carry `Authorization: Bearer <token>`; leave unset only for local testing. |

For example, to register the server in Claude Code with raw JSON output:

```bash
claude mcp add ashby -s user \
  -e ASHBY_API_KEY=PASTE_TEAM_KEY_HERE \
  -e ASHBY_OUTPUT=json \
  -- uvx --from git+https://github.com/nxrobins/ashby-mcp ashby-mcp
```

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
uv sync --group dev           # installs `ashby` in editable mode plus the test deps
uv run pytest                 # unit tests (mocked HTTP, no network)
uv run pytest -m live         # live smoke tests (requires ASHBY_API_KEY)
uv run ruff check             # lint
uv run ruff format --check    # formatting (drop --check to apply)
```

`uv sync` installs the package itself (editable, from `src/ashby`), so `import ashby` works in the project venv and the tests exercise the same package layout users install. Unit tests cover every tool's routing and request shape, the markdown formatters, error surfacing, and a few guards that keep the tool registry, this README, and Ashby's spec in sync. Live tests hit only read-only endpoints (`list_*`, `get_*`, `search_*`) so they can't corrupt workspace data; they exist to catch contract drift.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the same lint, format and test steps on every push to `main` and every pull request, checks that `uv.lock` is in sync with `pyproject.toml`, and runs `pip-audit` against the locked dependency set.

### Dependencies

`uv.lock` is the source of truth for what runs everywhere: the test suite, CI, and the Render deployment (`render.yaml` installs with `uv sync --frozen`). To pick up new upstream releases:

```bash
uv lock --upgrade             # re-resolve within the constraints in pyproject.toml
uv sync --group dev && uv run pytest
```

Commit the updated `uv.lock` with the change; CI's `pip-audit` step will flag any pinned version with a published advisory.

### Project layout

```
src/ashby/
  __init__.py            # main() — the `ashby-mcp` console script
  server.py              # MCP Server wiring: registers tool list + dispatcher, picks a transport
  tools.py               # tool schemas — the names, descriptions and inputSchemas clients see
  handlers.py            # dispatcher: tool name → Ashby endpoint (_SIMPLE) or custom handler (_SPECIAL)
  client.py              # AshbyClient — httpx, HTTP Basic auth, tenacity retries on 429/5xx
  formatting.py          # markdown tables / records for LLM-friendly output (see ASHBY_OUTPUT)
  transport.py           # stdio and HTTP+SSE transports, bearer auth, /healthz
tests/
  conftest.py            # shared fixtures: mocked HTTP, dummy API key, JSON output mode
  test_routing.py        # one test per tool — endpoint hit and body sent
  test_formatting.py     # formatter unit tests + end-to-end markdown rendering
  test_error_handling.py # error bodies surfaced to the caller, missing key, logging
  test_tools.py          # registry ↔ handler consistency, README tool count, spec-required fields
  test_transport.py      # advertised server name/version
  test_live.py           # opt-in live smoke tests
evals/                   # LLM-in-the-loop evals against a fake Ashby (see evals/README.md)
openapi.json             # Ashby's full OpenAPI spec (reference for adding new tools)
render.yaml              # Render blueprint for the HTTP/SSE deployment
```

## Adding a new tool

1. Find the endpoint in `openapi.json` (search for its path, e.g. `"/candidate.list"`) and note which request fields are `required`.
2. Add a `types.Tool(name=..., description=..., inputSchema=...)` entry to `all_tools()` in `src/ashby/tools.py`. Mirror the spec's `required` list and don't offer parameters the endpoint doesn't accept.
3. Route it in `src/ashby/handlers.py`:
   - a plain POST of the arguments → one line in `_SIMPLE`: `"tool_name": ("/endpoint", "Response prefix")`
   - anything that reshapes the payload or response (client-side filters, auto-pagination, multipart uploads) → an async function plus an entry in `_SPECIAL`
4. Optionally add a `_LIST_FORMATS` / `_RECORD_FORMATS` entry in `handlers.py` so markdown mode renders a compact table or record instead of raw JSON.
5. Add a routing test in `tests/test_routing.py` asserting the endpoint hit and the body sent.
6. Update the tool count and area list under "What's included" above — `tests/test_tools.py` fails until the count matches and the tool is routed.
7. Restart Claude Code to reload the MCP subprocess.

## Troubleshooting

- **`✗ Failed to connect` from `claude mcp list`** — usually `uv` isn't on your PATH, or the `uvx` fetch failed. Run the registered command by hand: `uvx --from git+https://github.com/nxrobins/ashby-mcp ashby-mcp`. A healthy server sits silently waiting on stdin (Ctrl-C to exit); otherwise the error is printed. From a checkout, `uv run ashby-mcp` does the same.
- **`401 Unauthorized` on every tool** — the API key isn't being passed. Double-check the `-e ASHBY_API_KEY=...` flag in your registration.
- **`403 Forbidden` on specific tools** — permissions gap on the team key; ask an Ashby admin.
- **New tools aren't showing up** — MCP loads tools once at session start. Restart Claude Code.

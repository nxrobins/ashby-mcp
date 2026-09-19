# Ashby MCP Server

> Forked from [thnico/MCP-Ashby](https://github.com/thz/MCP-Ashby) — thanks to Nicolas Thouzeau for the original implementation.

A Model Context Protocol (MCP) server that exposes Ashby ATS operations to Claude. Point Claude Code (or any MCP-compatible client) at this server and you can manage candidates, jobs, applications, interviews, projects, sources, and custom fields in natural language.

## What's included

50 tools across seven areas:

- **Candidates** — create, search, list, list all (auto-paginated), get, update, notes, tags, projects, client info, anonymize, resume + file upload
- **Jobs** — create, search, list, get, update, set status (Open/Closed/Archived/Draft)
- **Applications** — create, list, get, update, change stage, change source, transfer, add/remove hiring team members
- **Interviews** — list interview-type definitions, schedule interview events, list/update/cancel schedules
- **Projects** — get, list, search (useful for attaching candidates)
- **Sources** — list (discover sourceIds for `create_candidate` and `change_application_source`)
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

   If the service never becomes healthy, check its logs: without `MCP_BEARER_TOKEN` the server deliberately refuses to start (see [Security note](#security-note)). Consider adding `ASHBY_READ_ONLY=1` to the service's environment if teammates only need reporting.

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

The HTTP transport **fails closed**: if `MCP_BEARER_TOKEN` is unset or blank while `MCP_HOST` is anything other than loopback (`127.0.0.1`, `localhost`, `::1`), the server refuses to start with a clear error and exit code 1. A Render deploy that skipped the token therefore fails its health check instead of coming up open on the internet with a live Ashby key — look for `refusing to start the HTTP transport` in the service logs. Tokens are compared in constant time, and `/healthz` reports `"auth_required": true` whenever a token is enforced.

Hardening knobs, all read from the environment:

| Variable | Effect |
|---|---|
| `MCP_BEARER_TOKEN` | Required on any non-loopback bind (see above). Every `/sse` and `/messages/` request must send `Authorization: Bearer <token>`. |
| `MCP_ALLOW_INSECURE=1` | Escape hatch: start without a token on a public bind anyway. Local testing only — never set it on Render. |
| `ASHBY_READ_ONLY=1` | Removes every tool that writes to Ashby (create/update, `anonymize_candidate`, `set_job_status`, `change_application_stage`, `transfer_application`, `cancel_interview_schedule`, uploads, …) from the tool list, and rejects them if a client calls one anyway. Recommended for a shared Cowork deployment that only needs reporting. |
| `ASHBY_UPLOAD_DIR` | Over HTTP the two upload tools are **off by default**: their `file_path` argument would otherwise let any token holder — or a prompt injection carried in a candidate's notes or resume — read arbitrary files from the server container (for example `/proc/self/environ`, which holds the Ashby key) and store them in Ashby. Setting this to a directory re-enables the upload tools and confines `file_path` to it; symlinks and `..` are resolved before the check. Over stdio (your own machine) uploads stay unrestricted unless you set it, in which case the same confinement applies. |

Every tool also carries MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`), so clients that honour them can ask before running a write and flag irreversible ones.

Logging: uvicorn's per-request access log is disabled (each line would include the `?session_id=...` of a live MCP session), and Ashby error bodies are truncated to 500 characters in log lines because they can echo candidate data. The full error still reaches the caller.

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
  server.py         # MCP Server wiring — registers tools + dispatcher, picks a transport
  tools.py          # tool schemas + read-only/destructive classification (MCP annotations)
  handlers.py       # tool dispatcher → Ashby API
  client.py         # Ashby HTTP client (auth, retries, error surfacing)
  policy.py         # ASHBY_READ_ONLY / ASHBY_UPLOAD_DIR / transport-aware tool policy
  transport.py      # stdio and HTTP+SSE transports (bearer auth, fail-closed startup)
  formatting.py     # markdown rendering of Ashby responses
tests/
  conftest.py       # shared fixtures
  test_routing.py   # unit tests (one per tool)
  test_policy.py    # read-only mode, upload confinement, tool annotations
  test_transport.py # HTTP auth + fail-closed startup
  test_live.py      # opt-in live smoke tests
openapi.json        # Ashby's full OpenAPI spec (reference for adding new tools)
```

## Adding a new tool

1. Find the endpoint in `openapi.json` (search by `/` prefix)
2. Add a `_tool(name=..., description=..., inputSchema=...)` entry in `_catalog()` in `src/ashby/tools.py`, and classify it in `_HINTS` in the same file (`READ_ONLY`, `ADDITIVE`, `DESTRUCTIVE_IDEMPOTENT`, …) — the module fails to import until you do, because the classification is what `ASHBY_READ_ONLY` keys off
3. Route it in `src/ashby/handlers.py`: one line in `_SIMPLE` for a plain POST, or a handler function plus an entry in `_SPECIAL`
4. Add a routing test in `tests/test_routing.py`
5. Restart Claude Code to reload the MCP subprocess

## Troubleshooting

- **`✗ Failed to connect` from `claude mcp list`** — usually means the shared folder path is wrong or `uv` isn't on your PATH. Run `uv --directory <SHARED_PATH> run ashby` manually; the error will tell you which.
- **`401 Unauthorized` on every tool** — the API key isn't being passed. Double-check the `-e ASHBY_API_KEY=...` flag in your registration.
- **`403 Forbidden` on specific tools** — permissions gap on the team key; ask an Ashby admin.
- **New tools aren't showing up** — MCP loads tools once at session start. Restart Claude Code.

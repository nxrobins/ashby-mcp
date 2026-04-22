# Evals

End-to-end tests that measure whether Claude + this MCP server actually completes realistic recruiter tasks. Different from unit tests (which verify tool plumbing) — evals check that the *tools in the hands of an LLM* produce a useful answer.

## Quick start

```bash
# One-time: install eval extras (anthropic SDK, pyyaml)
uv sync --group evals

# One-time: copy the env template and paste your Anthropic key
cp .env.example .env
# then edit .env and fill in ANTHROPIC_API_KEY

# Run every case against the default model (claude-sonnet-4-6)
uv run python -m evals.run

# Run a subset
uv run python -m evals.run '001_*.yaml'

# Override the model (e.g. try Opus)
uv run python -m evals.run --model claude-opus-4-7

# Save a full JSON trace for debugging
uv run python -m evals.run --dump trace.json

# Verbose per-case output (tool-call list + answer preview)
ASHBY_EVAL_VERBOSE=1 uv run python -m evals.run
```

Exit code is `0` iff every case passed, so this slots into CI.

## How it works

```
┌─────────────┐     tool-use loop      ┌──────────────┐
│  Anthropic  │ ─────────────────────> │   runner.py  │
│   Claude    │ <─ tool_result         │  (this pkg)  │
└─────────────┘                         └──────┬───────┘
                                               │ dispatch()
                                               ▼
                                        ┌──────────────┐
                                        │  ashby.*     │
                                        │  (MCP tools) │
                                        └──────┬───────┘
                                               │ httpx
                                               ▼
                                        ┌──────────────┐
                                        │ fake_server  │
                                        │  (workspace) │
                                        └──────────────┘
```

The runner installs an `httpx.MockTransport` into `ashby_client._http_client` that routes every `api.ashbyhq.com` call to [`fake_server.py`](fake_server.py), which serves synthetic data from [`workspace.py`](workspace.py). No real Ashby API calls are made.

`ASHBY_OUTPUT=markdown` is forced so evals exercise the table/record formatters users actually see.

## Cost

A typical full run (3 cases, Sonnet 4.6 + Haiku 4.5 judge) is roughly **$0.10–$0.30 per run**. Token usage is printed in the summary.

## Writing a new case

Cases are YAML under [`cases/`](cases/). Minimum viable shape:

```yaml
name: "Short description"
prompt: |
  The user's actual request, multiline.

structural_checks:
  tools_called:    # tool names that MUST appear in the trace (any order)
    - list_candidates
  must_include:    # substrings that MUST appear in the final answer
    - c_sales_01
  must_exclude:    # substrings that MUST NOT appear
    - c_sales_04

judge:             # optional — invokes the LLM judge
  rubric: |
    - Did the answer do X?
    - Does it avoid Y?
```

Tips:
- Cite candidate/job IDs from `workspace.py` in `must_include` so checks are unambiguous.
- Use `must_exclude` as a contamination guard — it's often as informative as `must_include`.
- Keep the judge rubric to 3-5 bullet questions. Shorter rubrics → more consistent judges.

## Current coverage

| Case | What it tests |
|---|---|
| [001_reengagement_sales](cases/001_reengagement_sales.yaml) | Silver-medal identification, archive-reason filtering |
| [002_design_lead_narrative](cases/002_design_lead_narrative.yaml) | Pipeline storytelling for a closed search |
| [003_outreach_personalized](cases/003_outreach_personalized.yaml) | Personalized drafting grounded in candidate notes |

Next likely additions: funnel-report generation, adversarial/ambiguous prompts, honeypot cases where the agent should push back rather than guess.

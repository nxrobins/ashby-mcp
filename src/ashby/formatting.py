"""LLM-friendly output formatting.

Ashby's JSON responses are verbose — lots of metadata the LLM doesn't
need for most decisions. These helpers render results as compact
markdown tables (for lists) or labeled sections (for single records)
that cost fewer tokens and read more naturally in a chat transcript.

Set `ASHBY_OUTPUT=json` to opt back into raw JSON (useful for tests or
programmatic consumers).
"""

import json
import os
from typing import Any, Callable, Sequence, Union

Accessor = Union[str, Callable[[Any], Any]]
Column = tuple[str, Accessor]  # (header, accessor)


def output_format() -> str:
    """Current output mode — 'markdown' (default) or 'json'."""
    return os.getenv("ASHBY_OUTPUT", "markdown").lower()


def get_value(obj: Any, accessor: Accessor, default: Any = "—") -> Any:
    """Read a nested value from `obj` via a dotted path or callable.

    `"a.b.0.c"` walks dicts by key and lists by index. Missing keys,
    out-of-range indices, and None values all return `default`.
    """
    if obj is None:
        return default
    if callable(accessor):
        try:
            v = accessor(obj)
        except Exception:
            return default
        return default if v is None or v == "" else v
    cur: Any = obj
    for part in accessor.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError, TypeError):
                return default
        else:
            return default
        if cur is None:
            return default
    return default if cur is None or cur == "" else cur


def _cell(v: Any) -> str:
    """Render a Python value as a single markdown-table cell."""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        if not v:
            return "—"
        items = [str(x) for x in v[:3]]
        head = ", ".join(items)
        return head + ("…" if len(v) > 3 else "")
    s = str(v).replace("|", "\\|").replace("\n", " ").strip()
    return s if len(s) <= 60 else s[:57] + "…"


def table(rows: Sequence[Any], columns: Sequence[Column]) -> str:
    """Render a list of records as a markdown table. Empty → '(no results)'."""
    if not rows:
        return "_(no results)_"
    header = "| " + " | ".join(c[0] for c in columns) + " |"
    sep = "|" + "|".join(" --- " for _ in columns) + "|"
    body_lines = [
        "| " + " | ".join(_cell(get_value(r, acc)) for _, acc in columns) + " |"
        for r in rows
    ]
    return "\n".join([header, sep, *body_lines])


def format_list(response: Any, title: str, columns: Sequence[Column]) -> str:
    """Format an Ashby list response `{results, moreDataAvailable, nextCursor, ...}`.

    Accepts arbitrary payloads; non-dict inputs fall back to the raw JSON
    representation so the caller never gets an empty section."""
    if not isinstance(response, dict):
        return json.dumps(response, indent=2)
    results = response.get("results", [])
    total = response.get("total")
    more = bool(response.get("moreDataAvailable"))
    count = str(total) if total is not None else str(len(results))
    if more:
        count += ", more available"
    lines = [f"## {title} ({count})", "", table(results, columns)]

    meta: list[str] = []
    if cursor := response.get("nextCursor"):
        meta.append(f"Next cursor: `{cursor}`")
    if sync := response.get("syncToken"):
        meta.append(f"Sync token: `{sync}`")
    if meta:
        lines += ["", " · ".join(meta)]
    return "\n".join(lines)


def format_record(record: Any, title_accessor: Accessor, fields: Sequence[Column]) -> str:
    """Format a single Ashby record as a labeled markdown section."""
    if not isinstance(record, dict):
        return json.dumps(record, indent=2)
    title = get_value(record, title_accessor, default=str(record.get("id", "Record")))
    rid = record.get("id", "")
    heading = f"## {title}"
    if rid and str(rid) != str(title):
        heading += f" (`{rid}`)"
    lines = [heading, ""]
    for label, acc in fields:
        lines.append(f"- **{label}**: {_cell(get_value(record, acc))}")
    return "\n".join(lines)


def format_json(data: Any) -> str:
    """Raw JSON fallback."""
    return json.dumps(data, indent=2)

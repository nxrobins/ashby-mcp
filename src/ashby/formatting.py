"""LLM-friendly output formatting.

Ashby's JSON responses are verbose — lots of metadata the LLM doesn't
need for most decisions. These helpers render results as compact
markdown tables (for lists) or labeled sections (for single records)
that cost fewer tokens and read more naturally in a chat transcript.

Accessors are dotted paths into Ashby's response objects, or callables
decorated with `@reads(...)` naming the paths they touch. Both kinds are
checked against `openapi.json` by tests/test_spec_alignment.py, so a
column can't quietly point at a field Ashby never returns.

Set `ASHBY_OUTPUT=json` to opt back into raw JSON (useful for tests or
programmatic consumers).
"""

import json
import os
from collections.abc import Callable, Sequence
from typing import Any

Accessor = str | Callable[[Any], Any]
# (header, accessor) or (header, accessor, max_cell_chars). The optional
# width lets long-form columns such as note text escape the table cap.
Column = tuple[str, Accessor] | tuple[str, Accessor, int]

TABLE_CELL_CHARS = 60
RECORD_FIELD_CHARS = 1200
RECORD_LIST_ITEMS = 20


def reads(*paths: str) -> Callable[[Callable[[Any], Any]], Callable[[Any], Any]]:
    """Declare the response paths a callable accessor reads.

    Callables combine or reshape fields (pick the LinkedIn entry out of
    `socialLinks`, count `interviewEvents`); the declaration is what lets
    the spec-alignment test verify them like plain dotted paths.
    """

    def decorate(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        fn.reads = paths  # type: ignore[attr-defined]
        return fn

    return decorate


def accessor_paths(accessor: Accessor) -> tuple[str, ...]:
    """The dotted paths an accessor touches (declared via @reads for callables)."""
    if callable(accessor):
        return tuple(getattr(accessor, "reads", ()))
    return (accessor,)


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


def _scalar(v: Any) -> str:
    """One value as text: booleans as yes/no, containers as compact JSON."""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), default=str, ensure_ascii=False)
    return str(v)


def _cell(v: Any, max_len: int = TABLE_CELL_CHARS, max_list_items: int = 3) -> str:
    """Render a Python value as a single markdown cell.

    `max_len` caps the output. Tables pass the default 60 (a cell that
    wraps into multiple visual lines is harder to scan than one that gets
    a `…` truncation). Records pass a much larger value because long-form
    fields (notes, summaries, multi-name lists) are the point of a record
    view. Lists show the first `max_list_items` entries.
    """
    if isinstance(v, list):
        if not v:
            return "—"
        s = ", ".join(_scalar(x) for x in v[:max_list_items])
        if len(v) > max_list_items:
            s += "…"
    else:
        s = _scalar(v)
    s = s.replace("|", "\\|").replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 3)] + "…"


def _column(column: Column) -> tuple[str, Accessor, int]:
    header, accessor = column[0], column[1]
    width = column[2] if len(column) > 2 else TABLE_CELL_CHARS
    return header, accessor, width


def table(rows: Sequence[Any], columns: Sequence[Column]) -> str:
    """Render a list of records as a markdown table. Empty → '(no results)'."""
    if not rows:
        return "_(no results)_"
    cols = [_column(c) for c in columns]
    header = "| " + " | ".join(h for h, _, _ in cols) + " |"
    sep = "|" + "|".join(" --- " for _ in cols) + "|"
    body_lines = [
        "| " + " | ".join(_cell(get_value(r, acc), max_len=w) for _, acc, w in cols) + " |"
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
    if response.get("truncated"):
        # Set by auto-paginating tools that hit their page cap before the
        # data ran out — make the incompleteness impossible to miss.
        lines += [
            "",
            f"_Truncated at {len(results)} results — more exist. "
            "Continue from the cursor above with a paginated list call._",
        ]
    return "\n".join(lines)


def _record_cell(v: Any) -> str:
    return _cell(v, max_len=RECORD_FIELD_CHARS, max_list_items=RECORD_LIST_ITEMS)


def format_record(
    record: Any,
    title_accessor: Accessor,
    fields: Sequence[Column],
    *,
    hide: Sequence[str] = (),
) -> str:
    """Format a single Ashby record as a labeled markdown section.

    The configured `fields` come first, with friendly labels. Every other
    top-level key of the record follows under its raw name as compact
    JSON, so expanded sub-objects (`openings`, `applicationFormSubmissions`,
    `location`) and fields added to the API later are never silently
    dropped. `hide` names keys that are pure noise for the caller.

    Records get a much larger per-field budget than table cells (1200
    chars, 20 list items) — they're used to inspect ONE entity in depth.
    """
    if not isinstance(record, dict):
        return json.dumps(record, indent=2)
    title = get_value(record, title_accessor, default=str(record.get("id", "Record")))
    rid = record.get("id", "")
    heading = f"## {title}"
    if rid and str(rid) != str(title):
        heading += f" (`{rid}`)"
    lines = [heading, ""]
    consumed: set[str] = {"id", *hide}
    for path in accessor_paths(title_accessor):
        consumed.add(path.split(".")[0])
    for column in fields:
        label, acc, _ = _column(column)
        lines.append(f"- **{label}**: {_record_cell(get_value(record, acc))}")
        for path in accessor_paths(acc):
            consumed.add(path.split(".")[0])
    for key in sorted(k for k in record if k not in consumed):
        value = record[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        lines.append(f"- **{key}**: {_record_cell(value)}")
    return "\n".join(lines)


def format_json(data: Any) -> str:
    """Raw JSON fallback."""
    return json.dumps(data, indent=2)

"""LLM-friendly output formatting.

Ashby's JSON responses are verbose — lots of metadata the LLM doesn't
need for most decisions. These helpers render results as compact
markdown tables (for lists) or labeled sections (for single records)
that cost fewer tokens and read more naturally in a chat transcript.

Accessors come in two flavours:

- a dotted path string (`"archiveReason.text"`, `"socialLinks.0.url"`)
  that walks dicts by key and lists by index;
- a `Derived` callable built by one of the factories below
  (`social_link`, `items_of`, `fmt`, ...) that computes a value from the
  record AND declares the dotted paths it reads.

Both are checked against `openapi.json` by `tests/test_spec_alignment.py`,
so a field map can only reference fields Ashby actually returns.

Set `ASHBY_OUTPUT=json` to opt back into raw JSON (useful for tests or
programmatic consumers).
"""

import json
import os
import re
from typing import Any, Callable, Optional, Sequence, Union

Accessor = Union[str, Callable[[Any], Any]]
CellOpts = dict  # keyword overrides for `_cell` (max_len, max_list_items)
Column = Union[tuple[str, Accessor], tuple[str, Accessor, CellOpts]]

# Per-column budget for table cells that must not be truncated to be
# useful (e.g. the allowed values of a select field, or note text).
WIDE: CellOpts = {"max_len": 400, "max_list_items": 40}
FULL_TEXT: CellOpts = {"max_len": 2000}


def output_format() -> str:
    """Current output mode — 'markdown' (default) or 'json'."""
    return os.getenv("ASHBY_OUTPUT", "markdown").lower()


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


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


class Derived:
    """A callable accessor that declares the dotted paths it reads.

    `paths` use the same syntax as string accessors (`"tags.0.title"`,
    with `0` standing for "each element of the array"), so they can be
    validated against the OpenAPI spec exactly like plain string
    accessors, and `format_record` can tell which top-level keys of a
    record the field map already covers.
    """

    __slots__ = ("fn", "paths")

    def __init__(self, fn: Callable[[Any], Any], paths: Sequence[str]) -> None:
        self.fn = fn
        self.paths = tuple(paths)

    def __call__(self, obj: Any) -> Any:
        return self.fn(obj)

    def __repr__(self) -> str:
        return f"Derived({', '.join(self.paths)})"


def accessor_paths(accessor: Accessor) -> tuple[str, ...]:
    """Dotted paths an accessor reads (empty for opaque callables)."""
    if isinstance(accessor, str):
        return (accessor,)
    if isinstance(accessor, Derived):
        return accessor.paths
    return ()


_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.]+)\}")


def _scalar(v: Any, missing: str = "—") -> str:
    """Render one value as text: bools as yes/no, containers as compact JSON."""
    if v is None:
        return missing
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False, default=str)
    return str(v)


def _fill(template: str, obj: Any) -> Optional[str]:
    """Substitute `{dotted.path}` placeholders in `template` from `obj`.

    Missing values render as `—`; returns None when *nothing* resolved so
    the caller can fall back to the standard empty marker.
    """
    resolved = False

    def sub(m: "re.Match[str]") -> str:
        nonlocal resolved
        v = get_value(obj, m.group(1), default=None)
        if v is None or v == "":
            return "—"
        resolved = True
        return _scalar(v)

    s = _PLACEHOLDER.sub(sub, template).strip()
    return s if resolved else None


def fmt(template: str) -> Derived:
    """Record-level template accessor.

    `fmt("{author.firstName} {author.lastName}")` renders one string from
    the record. Placeholders are dotted paths.
    """
    return Derived(lambda r: _fill(template, r), _PLACEHOLDER.findall(template))


def items_of(key: str, template: str = "{title}") -> Derived:
    """List accessor: render each element of `record[key]` via `template`.

    `items_of("tags")` → `["referral", "ex-google"]`;
    `items_of("hiringTeam", "{firstName} {lastName} ({role})")` etc.
    Non-dict elements are rendered as-is.
    """
    placeholders = _PLACEHOLDER.findall(template)

    def fn(r: Any) -> list:
        v = r.get(key) if isinstance(r, dict) else None
        if v is None:
            return []
        items = v if isinstance(v, list) else [v]
        out = []
        for it in items:
            if isinstance(it, dict):
                s = _fill(template, it)
                out.append(s if s is not None else _scalar(it))
            else:
                out.append(_scalar(it))
        return out

    return Derived(fn, [f"{key}.0.{p}" for p in placeholders])


def titles_of(key: str) -> Derived:
    """`[{id, title, ...}, ...]` → list of titles (tags, stages, ...)."""
    return items_of(key, "{title}")


def custom_fields(key: str = "customFields") -> Derived:
    """`[{id, title, value}, ...]` → `["Title: value", ...]`.

    Object values (NumberRange, CompensationRange, Currency) render as
    compact JSON; MultiValueSelect renders as a JSON array.
    """
    return items_of(key, "{title}: {value}")


def count_of(key: str) -> Derived:
    """Number of elements in `record[key]` (None when it is not a list)."""

    def fn(r: Any) -> Optional[int]:
        v = r.get(key) if isinstance(r, dict) else None
        return len(v) if isinstance(v, list) else None

    return Derived(fn, (key,))


def social_link(kind: str, key: str = "socialLinks") -> Derived:
    """URL of the first `socialLinks` entry whose `type` is `kind`
    (LinkedIn, GitHub, Twitter, Medium, StackOverflow, Website)."""

    def fn(r: Any) -> Optional[str]:
        for link in (r.get(key) if isinstance(r, dict) else None) or []:
            if isinstance(link, dict) and str(link.get("type", "")).lower() == kind.lower():
                return link.get("url")
        return None

    return Derived(fn, (f"{key}.0.type", f"{key}.0.url"))


def select_options(key: str = "selectableValues") -> Derived:
    """Allowed options of a ValueSelect / MultiValueSelect custom field.

    Renders the label, with the API `value` in parentheses when it differs
    (that `value` is what `set_custom_field_value` expects), and flags
    archived options.
    """

    def fn(r: Any) -> list:
        out = []
        for opt in (r.get(key) if isinstance(r, dict) else None) or []:
            if not isinstance(opt, dict):
                out.append(_scalar(opt))
                continue
            label, value = opt.get("label"), opt.get("value")
            s = _scalar(label if label is not None else value)
            if value is not None and value != label:
                s += f" ({value})"
            if opt.get("isArchived"):
                s += " [archived]"
            out.append(s)
        return out

    return Derived(fn, (f"{key}.0.label", f"{key}.0.value", f"{key}.0.isArchived"))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _cell(v: Any, max_len: int = 60, max_list_items: int = 3) -> str:
    """Render a Python value as a single markdown cell.

    `max_len` caps the output. Tables pass the default 60 (a cell that
    wraps into multiple visual lines is harder to scan than one that
    gets a `…` truncation). Records pass a much larger value because
    long-form fields (notes, summaries, multi-name lists) are the whole
    point of a record view. Dicts render as compact JSON, not Python reprs.
    """
    if isinstance(v, bool):
        return "yes" if v else "no"
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


def _column(col: Column) -> tuple[str, Accessor, CellOpts]:
    """Normalise a 2- or 3-tuple column spec to (label, accessor, opts)."""
    label, accessor = col[0], col[1]
    opts = col[2] if len(col) > 2 else {}
    return label, accessor, opts


def _roots(accessor: Accessor) -> set[str]:
    """Top-level record keys an accessor reads."""
    return {p.split(".")[0] for p in accessor_paths(accessor)}


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def table(rows: Sequence[Any], columns: Sequence[Column]) -> str:
    """Render a list of records as a markdown table. Empty → '(no results)'."""
    if not rows:
        return "_(no results)_"
    cols = [_column(c) for c in columns]
    header = "| " + " | ".join(label for label, _, _ in cols) + " |"
    sep = "|" + "|".join(" --- " for _ in cols) + "|"
    body_lines = [
        "| " + " | ".join(_cell(get_value(r, acc), **opts) for _, acc, opts in cols) + " |"
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


def format_record(
    record: Any,
    title_accessor: Accessor,
    fields: Sequence[Column],
    omit: Sequence[str] = (),
) -> str:
    """Format a single Ashby record as a labeled markdown section.

    Records get a much larger per-field budget than table cells (1200 chars,
    20 list items) — they're typically used to inspect ONE entity in depth,
    where notes / summaries / skill-lists are the point.

    Any top-level key the field map does not read (e.g. sub-objects pulled
    in via `expand`) is appended verbatim as compact JSON under
    "Other fields", so nothing in the response is silently dropped. Keys
    listed in `omit` are dropped deliberately (e.g. an HTML duplicate of a
    plain-text field).
    """
    if not isinstance(record, dict):
        return json.dumps(record, indent=2)
    title = get_value(record, title_accessor, default=str(record.get("id", "Record")))
    rid = record.get("id", "")
    heading = f"## {title}"
    if rid and str(rid) != str(title):
        heading += f" (`{rid}`)"
    lines = [heading, ""]
    for col in fields:
        label, acc, opts = _column(col)
        cell_opts = {"max_len": 1200, "max_list_items": 20, **opts}
        lines.append(f"- **{label}**: {_cell(get_value(record, acc), **cell_opts)}")

    covered = {"id"} | _roots(title_accessor) | {k.split(".")[0] for k in omit}
    for col in fields:
        covered |= _roots(col[1])
    rest = {k: v for k, v in record.items() if k not in covered and not _is_empty(v)}
    if rest:
        lines += [
            "",
            "Other fields (raw JSON):",
            "```json",
            json.dumps(rest, separators=(",", ":"), ensure_ascii=False, default=str),
            "```",
        ]
    return "\n".join(lines)


def format_json(data: Any) -> str:
    """Raw JSON fallback."""
    return json.dumps(data, indent=2)

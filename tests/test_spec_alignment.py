"""The field maps in handlers.py must name fields Ashby actually returns.

Loads the checked-in `openapi.json` (Ashby's own spec), resolves each
formatted tool's 200-response `results` schema, and asserts that every
dotted accessor path in `_LIST_FORMATS` / `_RECORD_FORMATS` — plain
string accessors and the paths declared by `Derived` callables — resolves
against it.

This is the test that catches a field map written against an invented
response shape. Such a map fails nothing else: in markdown mode every row
just renders `—`, and the JSON-mode routing tests never look at columns.

Resolution rules mirror `formatting.get_value`: a segment walks dict
`properties` by name, and a numeric segment (`0`) walks into an array's
`items`. `$ref`s are resolved generically as local JSON pointers (the spec
inlines its schemas and points into `#/paths/...`), and allOf/oneOf/anyOf
are flattened so a property found in any branch counts.
"""

import json
import pathlib
from typing import Any, Iterator

import pytest

from ashby.formatting import accessor_paths
from ashby.handlers import _LIST_FORMATS, _RECORD_FORMATS, _RECORD_OMIT, _SIMPLE

SPEC_PATH = pathlib.Path(__file__).resolve().parent.parent / "openapi.json"

# Tools served by a special handler (not in `_SIMPLE`) → the endpoint whose
# response they format.
_SPECIAL_ENDPOINTS = {
    "list_jobs": "/job.list",
    "get_job": "/job.info",
    "list_custom_fields": "/customField.list",
    "list_all_candidates": "/candidate.list",
    "list_sources": "/source.list",
}


# ---------------------------------------------------------------------------
# Generic schema walking
# ---------------------------------------------------------------------------


def _pointer(spec: dict, ref: str) -> Any:
    """Resolve a local JSON pointer such as
    `#/paths/~1job.info/post/responses/200/content/application~1json/schema`."""
    assert ref.startswith("#/"), f"only local $refs are supported, got {ref!r}"
    node: Any = spec
    for raw in ref[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _deref(spec: dict, node: Any) -> Any:
    """Follow `$ref` chains until a concrete object is reached."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 50:
        node = _pointer(spec, node["$ref"])
        seen += 1
    return node


def _variants(spec: dict, schema: Any, depth: int = 0) -> Iterator[dict]:
    """Yield every concrete schema object `schema` may denote.

    Follows `$ref`s and flattens allOf / oneOf / anyOf so a property lookup
    can consult each branch (the 200 response is `oneOf[success, error]`,
    and most objects are `allOf[base, extension]`).
    """
    if depth > 40 or not isinstance(schema, dict):
        return
    schema = _deref(spec, schema)
    if not isinstance(schema, dict):
        return
    yield schema
    for combo in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(combo, []):
            yield from _variants(spec, sub, depth + 1)


def resolves(spec: dict, schema: Any, path: str) -> bool:
    """True if dotted `path` can be walked from `schema`."""
    return _resolves(spec, schema, path.split("."))


def _resolves(spec: dict, schema: Any, segments: list[str]) -> bool:
    if not segments:
        return True
    seg, rest = segments[0], segments[1:]
    for node in _variants(spec, schema):
        if seg.isdigit():
            if "items" in node and _resolves(spec, node["items"], rest):
                return True
        else:
            props = node.get("properties") or {}
            if seg in props and _resolves(spec, props[seg], rest):
                return True
    return False


def response_schema(spec: dict, endpoint: str) -> Any:
    """The JSON schema of `endpoint`'s 200 response body."""
    op = spec["paths"][endpoint]["post"]
    resp = _deref(spec, op["responses"]["200"])
    return resp["content"]["application/json"]["schema"]


def _endpoint_for(tool: str) -> str:
    if tool in _SPECIAL_ENDPOINTS:
        return _SPECIAL_ENDPOINTS[tool]
    assert tool in _SIMPLE, f"{tool}: no endpoint known — add it to _SPECIAL_ENDPOINTS"
    return _SIMPLE[tool][0]


def _column_paths(columns) -> list[tuple[str, str]]:
    """(label, dotted path) for every path a column set reads."""
    return [(col[0], p) for col in columns for p in accessor_paths(col[1])]


@pytest.fixture(scope="module")
def spec() -> dict:
    with SPEC_PATH.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Every formatted tool's accessors resolve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(_LIST_FORMATS))
def test_list_format_accessors_exist_in_spec(spec, tool):
    endpoint = _endpoint_for(tool)
    schema = response_schema(spec, endpoint)
    assert resolves(spec, schema, "results.0"), f"{endpoint}: 200 response has no results[]"

    _, columns = _LIST_FORMATS[tool]
    missing = [
        f"{label} -> {path}"
        for label, path in _column_paths(columns)
        if not resolves(spec, schema, f"results.0.{path}")
    ]
    assert not missing, f"{tool} ({endpoint}): accessors not in the spec: {missing}"


@pytest.mark.parametrize("tool", sorted(_RECORD_FORMATS))
def test_record_format_accessors_exist_in_spec(spec, tool):
    endpoint = _endpoint_for(tool)
    schema = response_schema(spec, endpoint)
    assert resolves(spec, schema, "results"), f"{endpoint}: 200 response has no results"

    title_accessor, fields = _RECORD_FORMATS[tool]
    paths = [("<title>", p) for p in accessor_paths(title_accessor)]
    paths += _column_paths(fields)
    paths += [("<omit>", p) for p in _RECORD_OMIT.get(tool, ())]
    missing = [
        f"{label} -> {path}"
        for label, path in paths
        if not resolves(spec, schema, f"results.{path}")
    ]
    assert not missing, f"{tool} ({endpoint}): accessors not in the spec: {missing}"


def test_every_accessor_is_checkable():
    """No opaque lambdas: every column must be a string path or a `Derived`
    callable that declares its paths, otherwise the checks above can't see it."""
    opaque = []
    for tool, (_, columns) in {**_LIST_FORMATS, **_RECORD_FORMATS}.items():
        for col in columns:
            if not accessor_paths(col[1]):
                opaque.append(f"{tool}.{col[0]}")
    assert not opaque, f"columns with un-checkable accessors: {opaque}"


# ---------------------------------------------------------------------------
# The resolver is not vacuous: the shapes the old maps assumed must FAIL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint, prefix, bogus_path",
    [
        ("/application.list", "results.0", "archiveReason.title"),
        ("/application.list", "results.0", "candidate.position"),
        ("/application.list", "results.0", "candidate.linkedInUrl"),
        ("/application.info", "results", "candidate.resumeFileHandle.id"),
        ("/candidate.listNotes", "results.0", "note"),
        ("/candidate.listNotes", "results.0", "createdByUser.email"),
        ("/job.list", "results.0", "locations.0.locationName"),
        ("/job.list", "results.0", "department.name"),
        ("/job.search", "results.0", "location.name"),  # no expand on search
        ("/candidate.list", "results.0", "linkedInUrl"),
        ("/candidate.info", "results", "location.city"),
        ("/interview.list", "results.0", "type"),
        ("/interview.info", "results", "duration"),
        ("/interviewSchedule.list", "results.0", "interviewStage.title"),
        ("/interviewEvent.list", "results.0", "status"),
        ("/interviewStageGroup.list", "results.0", "orderInInterviewPlan"),
        ("/project.info", "results", "associatedJobIds"),
    ],
)
def test_invented_paths_do_not_resolve(spec, endpoint, prefix, bogus_path):
    schema = response_schema(spec, endpoint)
    assert not resolves(spec, schema, f"{prefix}.{bogus_path}")


@pytest.mark.parametrize(
    "endpoint, prefix, path",
    [
        ("/application.list", "results.0", "archiveReason.text"),
        ("/application.info", "results", "applicationFormSubmissions.0.submittedValues"),
        ("/candidate.listNotes", "results.0", "author.email"),
        ("/job.list", "results.0", "location.name"),
        ("/candidate.info", "results", "socialLinks.0.url"),
        ("/candidate.info", "results", "primaryLocation.locationSummary"),
        ("/customField.list", "results.0", "selectableValues.0.label"),
        ("/interviewStageGroup.list", "results.0", "order"),
    ],
)
def test_real_paths_resolve(spec, endpoint, prefix, path):
    schema = response_schema(spec, endpoint)
    assert resolves(spec, schema, f"{prefix}.{path}")

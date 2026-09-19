"""Every markdown accessor must resolve against Ashby's OpenAPI spec.

The column maps in handlers.py were once written against invented
response shapes (`archiveReason.title`, `candidate.linkedInUrl`,
`department.name`, `note`), so in production those cells rendered as
"—" while the eval fake, built from the same guesses, passed. This test
walks every dotted path (and every path a callable declares with
@reads) through the endpoint's 200 `results` schema in openapi.json.
"""

import json
import pathlib

import pytest

from ashby.formatting import accessor_paths
from ashby.handlers import _LIST_FORMATS, _RECORD_FORMATS, _SIMPLE

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = json.loads((REPO_ROOT / "openapi.json").read_text())

# Endpoints read by the formatted tools whose handler lives in _SPECIAL.
SPECIAL_ENDPOINTS = {
    "list_jobs": "/job.list",
    "list_custom_fields": "/customField.list",
    "list_all_candidates": "/candidate.list",
    "list_sources": "/source.list",
}


def _deref(node):
    """Follow $ref, keeping sibling keys: the spec nests `properties` beside a $ref."""
    hops = 0
    while isinstance(node, dict) and "$ref" in node and hops < 20:
        target = SPEC
        for part in node["$ref"][2:].split("/"):
            part = part.replace("~1", "/")
            target = target[int(part)] if isinstance(target, list) else target[part]
        merged = dict(target) if isinstance(target, dict) else target
        if isinstance(merged, dict):
            for key, value in node.items():
                if key == "$ref":
                    continue
                if key == "properties" and isinstance(merged.get("properties"), dict):
                    merged["properties"] = {**merged["properties"], **value}
                else:
                    merged[key] = value
        node = merged
        hops += 1
    return node


def _properties(schema, acc=None, depth=0):
    """Union of `properties` across allOf / oneOf / anyOf branches."""
    acc = {} if acc is None else acc
    schema = _deref(schema)
    if not isinstance(schema, dict) or depth > 8:
        return acc
    for key, value in (schema.get("properties") or {}).items():
        acc.setdefault(key, value)
    for combinator in ("allOf", "oneOf", "anyOf"):
        for branch in schema.get(combinator, []):
            _properties(branch, acc, depth + 1)
    return acc


def _items(schema, depth=0):
    schema = _deref(schema)
    if not isinstance(schema, dict) or depth > 8:
        return None
    if "items" in schema:
        return schema["items"]
    for combinator in ("allOf", "oneOf", "anyOf"):
        for branch in schema.get(combinator, []):
            found = _items(branch, depth + 1)
            if found is not None:
                return found
    return None


def _results_schema(endpoint):
    response = SPEC["paths"][endpoint]["post"]["responses"]["200"]
    props = _properties(response["content"]["application/json"]["schema"])
    assert "results" in props, f"{endpoint}: no `results` in the 200 response schema"
    return props["results"]


def _resolves(schema, path):
    node = schema
    for part in path.split("."):
        node = _deref(node)
        if not isinstance(node, dict):
            return False
        if part.isdigit():
            items = _items(node)
            if items is None:
                return False
            node = items
            continue
        props = _properties(node)
        if part in props:
            node = props[part]
            continue
        # A free-form object (no declared properties) may hold anything.
        return not props and node.get("additionalProperties") is not False and "items" not in node
    return True


def _endpoint(tool):
    return _SIMPLE[tool][0] if tool in _SIMPLE else SPECIAL_ENDPOINTS[tool]


def _cases():
    for tool, (_title, columns) in _LIST_FORMATS.items():
        item = _items(_results_schema(_endpoint(tool)))
        assert item is not None, f"{tool}: results is not an array in the spec"
        for column in columns:
            for path in accessor_paths(column[1]):
                yield pytest.param(item, path, id=f"{tool}:{column[0]}={path}")
    for tool, fmt in _RECORD_FORMATS.items():
        record = _results_schema(_endpoint(tool))
        for path in accessor_paths(fmt.title):
            yield pytest.param(record, path, id=f"{tool}:<title>={path}")
        for column in fmt.fields:
            for path in accessor_paths(column[1]):
                yield pytest.param(record, path, id=f"{tool}:{column[0]}={path}")


@pytest.mark.parametrize("schema,path", list(_cases()))
def test_accessor_path_exists_in_spec(schema, path):
    assert _resolves(schema, path), f"{path!r} is not in the endpoint's response schema"


def test_every_callable_accessor_declares_what_it_reads():
    undeclared = []
    for tool, (_title, columns) in _LIST_FORMATS.items():
        undeclared += [
            f"{tool}:{c[0]}" for c in columns if callable(c[1]) and not accessor_paths(c[1])
        ]
    for tool, fmt in _RECORD_FORMATS.items():
        undeclared += [
            f"{tool}:{c[0]}" for c in fmt.fields if callable(c[1]) and not accessor_paths(c[1])
        ]
    assert not undeclared, f"callable accessors without @reads: {undeclared}"

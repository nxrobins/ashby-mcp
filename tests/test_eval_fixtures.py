"""The synthetic eval workspace must carry every field the formatter reads,
in the shapes Ashby actually returns. Otherwise evals pass on data that
production never produces, which is exactly how the markdown columns
drifted in the first place.

workspace.py is loaded by path so the check doesn't import the evals
package (whose __init__ loads `.env`).
"""

import importlib.util
import pathlib

import pytest

from ashby.formatting import get_value
from ashby.handlers import _CANDIDATE_COLS, _JOB_COLS, _LIST_FORMATS, _RECORD_FORMATS

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_workspace():
    path = REPO_ROOT / "evals" / "workspace.py"
    spec = importlib.util.spec_from_file_location("eval_workspace", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WS = _load_workspace()

DATASETS = {
    "candidates": (WS.CANDIDATES, [*_CANDIDATE_COLS, *_RECORD_FORMATS["get_candidate"].fields]),
    "jobs": (WS.JOBS, [*_JOB_COLS, *_RECORD_FORMATS["get_job"].fields]),
    "applications": (
        WS.APPLICATIONS,
        [*_LIST_FORMATS["list_applications"][1], *_RECORD_FORMATS["get_application"].fields],
    ),
    "notes": (
        [note for notes in WS.CANDIDATE_NOTES.values() for note in notes],
        _LIST_FORMATS["list_candidate_notes"][1],
    ),
    "sources": (WS.SOURCES, _LIST_FORMATS["list_sources"][1]),
    "interview_stages": (WS.INTERVIEW_STAGES, _LIST_FORMATS["list_interview_stages"][1]),
}

# Optional Ashby fields the fixture deliberately leaves empty everywhere
# (no eval case needs them). Everything else must be populated in at least
# one record so the formatter's reads are exercised against real shapes.
ALLOWED_EMPTY = {
    "candidates": {"resume_id", "resume_name", "credited_to", "custom_fields"},
    "jobs": {
        "interview_plan_id",
        "requisition",
        "hiring_team",
        "custom_fields",
        "job_posting_ids",
        "opened",
        "closed",
    },
    "applications": {"credited_to", "hiring_team", "custom_fields"},
}


def _populated(value) -> bool:
    if isinstance(value, bool):
        return True
    return value is not None and value != "" and value != [] and value != {}


def _cases():
    for name, (records, columns) in DATASETS.items():
        seen = set()
        for column in columns:
            if column[0] in seen:
                continue
            seen.add(column[0])
            yield pytest.param(name, records, column, id=f"{name}:{column[0]}")


@pytest.mark.parametrize("name,records,column", list(_cases()))
def test_fixture_populates_field(name, records, column):
    label, accessor = column[0], column[1]
    if label in ALLOWED_EMPTY.get(name, set()):
        pytest.skip("optional in Ashby; intentionally empty in the fixture")
    assert any(_populated(get_value(r, accessor, default=None)) for r in records), (
        f"no {name} record populates {label!r}: the eval fake no longer matches "
        "the shape the formatter reads"
    )

"""Evals package — see README.md.

Does two bits of startup plumbing so `python -m evals.run` works
anywhere in the repo:
  1. Adds `src/` to `sys.path` so `ashby.*` resolves (pytest handles
     this separately via `[tool.pytest.ini_options].pythonpath`).
  2. Loads `.env` from the repo root so `ANTHROPIC_API_KEY` (and any
     eval-related overrides) come through without needing `export`.
"""

import pathlib
import sys

from dotenv import load_dotenv

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# `.env` at the repo root — gitignored, see `.env.example` for the template.
# `override=True` so an empty `ANTHROPIC_API_KEY=""` in the parent shell
# doesn't shadow the real key in `.env`.
load_dotenv(_REPO_ROOT / ".env", override=True)

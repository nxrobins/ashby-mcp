"""Evals package — see README.md.

Loads `.env` from the repo root so `ANTHROPIC_API_KEY` (and any
eval-related overrides) come through without needing `export`.

The `ashby` package itself resolves through the project's editable
install — `uv sync` (or `uv run`) puts `src/ashby` on the path, so no
`sys.path` manipulation is needed here.
"""

import pathlib

from dotenv import load_dotenv

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# `.env` at the repo root — gitignored, see `.env.example` for the template.
# `override=True` so an empty `ANTHROPIC_API_KEY=""` in the parent shell
# doesn't shadow the real key in `.env`.
load_dotenv(_REPO_ROOT / ".env", override=True)

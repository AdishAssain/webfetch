---
name: check
description: Run the webfetch verification chain — ruff format+lint, vulture dead-code, and pytest. Use before committing or when asked to verify the repo is green.
---

Run each step and report results. All must pass before the work is done:

1. `uv run ruff format .`
2. `uv run ruff check .`
3. `uv run vulture`
4. `uv run pytest`

If any step fails, fix the cause and re-run the whole chain.

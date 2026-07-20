# AGENTS.md

Guidance for coding agents (and humans) working in this repo. Tool-agnostic;
Claude Code, Codex, Cursor, etc. all read this.

## What this is

`webfetch` — a thin, tiered web fetch + discovery toolkit for data-science
scraping. `fetch()` auto-routes: data file → pandas; cache → httpx → Playwright.
`discover()` searches (Exa, else Tavily). `login()` saves a Playwright session
for gated sites. See `README.md` for usage.

## Tooling (use these, not older equivalents)

- **uv** for everything: `uv sync`, `uv run <cmd>`. Do not use bare `pip`/`venv`.
- **ruff** for lint + format: `uv run ruff check --fix` / `uv run ruff format`.
- **pytest** for tests: `uv run pytest`.
- **vulture** for dead code: `uv run vulture` (scoped to `webfetch/`, must stay clean).
- **1Password (`op`)** for secrets — `op://` refs in `.env`, resolved at runtime.
  Never hardcode or print keys.

## Security invariants — do not weaken

- **SSRF guard (`webfetch/_safeurl.py`)** gates every network fetch. Keep the
  scheme allowlist (`http`/`https` only) and the private/loopback/link-local/
  metadata (169.254.169.254) blocks. Re-validate on every redirect hop. If you
  add a new fetch path, route it through `_safeurl.guard`.
- **Bounded reads:** keep the size caps (`_http.MAX_BYTES`) and streaming
  downloads. Never buffer an unbounded response.
- **Secrets:** never log, print, or commit keys or `storage_state.json`. Auth'd
  pages must never be written to the on-disk cache.
- Every one of these has a regression test under `tests/` — keep them green.

## Conventions

- Small, direct functions; no narrative comments or speculative abstraction.
- New behavior needs a test. Security-relevant behavior needs a security test
  (see `tests/test_safeurl.py`, `test_http.py`, `test_properties.py`).
- Run `uv run ruff check`, `uv run vulture`, and `uv run pytest` before committing.
  Pre-commit hooks and CI enforce this — don't bypass them.

## Never commit

`.env`, `*storage_state*.json`, `.venv/`, `.cache/`, or anything under the
tooling-cache dirs. These are git-ignored and agent-ignored — keep them so.

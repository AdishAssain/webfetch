---
name: webfetch
description: Use when fetching web pages, scraping sites, downloading datasets or files, or searching the web for data to analyze. Provides the webfetch toolkit — SSRF-guarded fetch(), discover() search, and login() session reuse — with pandas-ready output. Prefer over ad-hoc requests/httpx/urllib or raw Playwright.
---

# webfetch

Tiered, SSRF-guarded web fetching for data work. `fetch()` auto-routes:
data file → pandas; cache → httpx → Playwright.

## Install (once, in the target project)

    uv add "webfetch @ git+https://github.com/AdishAssain/webfetch.git"
    uv run playwright install chromium   # only if you need JS / auth rendering

Secrets via 1Password refs in `.env` (e.g. `EXA_API_KEY=op://Private/Exa/credential`).

## Use

```python
from webfetch import fetch, discover, download, login

discover("India TB district data 2024")            # -> [{url, title, text}]
fetch("https://example.gov/report")                 # auto: httpx -> Playwright
fetch("https://example.gov/data.csv").dataframe     # data files -> pandas
fetch("https://spa.example/dashboard", render=True, wait="table.results")
download("https://site/report.pdf", "data/report.pdf")
```

Gated sites (e.g. Nikshay): run `webfetch login <url>` once to save a session,
then `fetch(url, auth=True)`.

## Rules

- Don't bypass the SSRF guard or size caps; don't fetch internal hosts unless
  the user sets `WEBFETCH_ALLOW_PRIVATE=1`.
- Prefer plain `fetch()` (auto-routing) — only pass `render=True` for JS-heavy
  or login-gated pages.
- Prefer official APIs / direct downloads for bulk data; `fetch()` already sends
  `.csv/.xlsx/.parquet/.json` straight to pandas.
- Never print or commit API keys or `storage_state.json`.

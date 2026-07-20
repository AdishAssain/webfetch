# webfetch

A thin, universal toolkit for data-science scraping. Solves the two real
bottlenecks — **discoverability** (find the right pages) and **access** (get the
bytes past JS/auth) — and stays out of the way for the easy cases.

It routes each request to the cheapest tool that works:

```
data file (.csv/.xlsx/…) ─► pandas
cached ──────────────────► disk
server-rendered HTML ────► httpx + selectolax / pandas.read_html
JS / login-gated ────────► Playwright (reuses a saved login session)
(optional) ──────────────► Firecrawl managed API
```

Discovery is a separate axis, handled by one search API (Exa or Tavily).

## Install

```bash
uv sync                              # creates .venv from pyproject/uv.lock
uv run playwright install chromium
cp .env.example .env                 # point EXA_API_KEY at your 1Password ref
```

Optional extra: `uv sync --extra parquet` (adds pyarrow for `.parquet` files).
Run anything in the env with `uv run …` (e.g. `uv run webfetch discover "…"`).

## Secrets

Put your keys in `.env` (git-ignored). A raw key is all you need:

```env
EXA_API_KEY=your-exa-key
```

**Optional — 1Password:** if you use `op`, you can store an `op://` reference
instead of the raw value and webfetch resolves it via the `op` CLI at runtime
(right-click the field in the 1Password app -> **Copy Secret Reference**):

```env
EXA_API_KEY=op://Private/Exa/credential
```

Either form works. With an `op://` ref, run under `op run --env-file=.env -- <cmd>`
or let it auto-resolve on use (needs `op` signed in). The example MCP configs use
`${EXA_API_KEY}` expansion so nothing is embedded either way.

## Use — in code

```python
from webfetch import fetch, discover, download, login

# discoverability
for hit in discover("India TB district-level notification data 2024"):
    print(hit["title"], hit["url"])

# access — auto-routed
r = fetch("https://example.gov/report")   # httpx if it can, browser if it must
r.dataframe            # first HTML table as a DataFrame
r.tables               # all tables
r.text                 # clean text
r.engine               # which path was used: cache/httpx/playwright/firecrawl/pandas

fetch("https://data.gov/x.csv").dataframe  # data files load straight to pandas
download("https://site/report.pdf", "data/report.pdf")

# JS-heavy page
fetch("https://portal/dashboard", render=True, wait="table.results")
```

## Use — gated sites (e.g. Nikshay)

Log in once by hand; the session is saved and reused. Credentials never enter
code or the agent.

```bash
webfetch login https://reports.nikshay.in    # opens a browser; log in, press Enter
```
```python
fetch("https://reports.nikshay.in/private/page", auth=True)   # reuses the session
```

The saved `storage_state.json` is git-ignored — it's effectively a credential.
Prefer public dashboards / official aggregates (WHO TB DB, India TB Report,
data.gov.in) when they answer the question.

## Use — CLI

```bash
uv run webfetch get https://example.com --render
uv run webfetch discover "open TB datasets India" -n 15
uv run webfetch login https://portal.example.gov
```

## Make it universal across Claude Code + Codex

The `webfetch` package covers *code*. For the *agents*, register the matching
MCP servers once, at global scope, so every project in both tools inherits them:

```bash
./scripts/setup.sh        # registers Exa + Playwright in Claude Code, prints Codex steps
```

- Claude Code: `~/.claude.json` (or `claude mcp add … -s user`) — see `configs/claude-mcp.example.json`
- Codex: `~/.codex/config.toml` — see `configs/codex-config.example.toml`

Both use the same stdio (`npx`) servers, so the setup is portable.

## Dev

```bash
op run --env-file=.env -- ./scripts/smoketest.sh   # verify the Exa key (curl)
uv run ruff check --fix                            # lint
uv run ruff format                                 # format
uv run vulture                                     # dead-code check
uv run pytest                                      # tests
```

Install the git hooks once — `uvx pre-commit install` — to run ruff + vulture on
every commit and pytest on push. CI runs the same chain on every push and PR.

## Rate limiting & proxies

All off/default via env — set only what you need:

- `WEBFETCH_MIN_INTERVAL=1.0` — minimum seconds between requests to the same host
  (politeness; default 0 = off).
- Retries with exponential backoff on `429`/`5xx` are **on by default**
  (`WEBFETCH_MAX_RETRIES=3`, `WEBFETCH_RETRY_BACKOFF=0.5`); `Retry-After` is honored.

Proxies / IP masking (both the HTTP and Playwright paths use them):

- `WEBFETCH_PROXY=http://user:pass@host:port` — route everything through one proxy.
  **For rotating IPs, point this at a rotating-gateway provider** — the provider
  rotates the exit IP per request, which is the simplest and most reliable method.
- `WEBFETCH_PROXIES=http://p1:port,http://p2:port` — a pool rotated round-robin per
  request (and per retry), for when you hold a list of static proxies.
- `WEBFETCH_PROXY_HOSTS=data.gov.in,nikshay.in` — route **only** these hosts (and
  their subdomains) through the proxy; everything else goes direct. This is the
  "only if required" switch.

**Region-locked sites (e.g. India-only):** point `WEBFETCH_PROXY` at a proxy whose
exit IP is in the right country, and scope it with `WEBFETCH_PROXY_HOSTS` so only
those sites use it. Get an in-country exit from either a residential provider with
country targeting (Bright Data / Oxylabs / SOAX / IPRoyal, `country=IN`) or your own
box — e.g. an AWS Mumbai (`ap-south-1`) instance running a small HTTP proxy, or an
`ssh -D 1080 mumbai-box` SOCKS tunnel (`WEBFETCH_PROXY=socks5://localhost:1080`,
`uv sync --extra socks`).

With a proxy set, the destination is guarded at the URL level (the proxy resolves
it, so it isn't IP-pinned like the direct path). Treat a configured proxy as
trusted infrastructure: webfetch guards the target URL, but the proxy does the
actual DNS and egress, so it — not webfetch — is the enforcement point for what
the proxy itself can reach.

## Security

- **SSRF-guarded fetches:** only `http`/`https`; blocks private, loopback,
  link-local and cloud-metadata (169.254.169.254) addresses; re-validates every
  redirect hop; and **pins the connection to the validated IP**, so a rebinding
  DNS server can't swap in an internal address after the check. It fails closed
  if that transport can't be installed. The Playwright path applies the same
  resolver guard to every browser request (best-effort: Chromium does its own
  DNS, so it isn't IP-pinned like the HTTP path). Set `WEBFETCH_ALLOW_PRIVATE=1`
  only if you deliberately need localhost/intranet.
- **Bounded reads:** the socket read is size-capped and downloads stream to disk,
  so an unbounded or chunked response can't exhaust memory. The cap is on wire
  bytes; the decoded size of a *compressed* response isn't separately bounded, so
  treat untrusted servers with care.
- **Secret hygiene:** `.env` and saved sessions are git-ignored, `storage_state.json`
  is written `0600`, and authenticated pages are never written to the on-disk cache.
  Keys can optionally live in 1Password (`op://` refs) instead of plaintext.
- **Safe parsing:** data files are fetched through the guarded client and parsed
  from memory (URLs never handed straight to pandas); the cache stores raw HTML,
  never pickled objects.
- **Pin MCP servers for production:** replace `npx -y exa-mcp-server` with a
  pinned version (e.g. `exa-mcp-server@1.2.3`) to reduce supply-chain risk.

## Notes

- **Jupyter:** the httpx path works everywhere. Playwright's *sync* API can't run
  inside a notebook's event loop — do render/auth fetches via the `webfetch` CLI
  or a script (results land in the cache), then read them from the notebook.
- **No lock-in.** The clean-content layer is swappable — Playwright by default,
  or Firecrawl via `WEBFETCH_ENGINE=firecrawl`. Choose on auth handling, cost,
  and reliability for your targets, not output format.
- Be a good citizen: the on-disk cache avoids re-fetching; add delays and respect
  robots.txt / terms on slow public infrastructure.

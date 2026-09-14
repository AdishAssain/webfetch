# Contributing

Thanks for looking. This is a small personal project. Please open an issue
before a large change. It may not fit the direction, and that is cheaper to
find out first.

## Setup

```bash
uv sync --all-extras
uv run playwright install chromium
uv run pytest
```

`uv run webfetch doctor` reports what is installed and what is missing.

## Before opening a pull request

```bash
uv run pytest          # all tests
uv run ruff check .    # lint
uv run ruff format .   # format
```

`pre-commit install` runs the same checks on each commit.

## Tests

New behaviour needs a test, and the test should fail before the fix. A test
written afterwards passes on its first run. That proves only that it agrees
with the code you just wrote, not that it can catch the bug.

Name what the test asserts, not the function it calls. `test_an_empty_file_does
_not_pass` says what breaks if it regresses; `test_session_state` does not.

## The guards

`_safeurl.py` and `_browser.py` hold the SSRF checks. Two rules apply there:

- A change must fail closed. An unfamiliar scheme, an unresolvable host, or an
  unexpected payload shape stays blocked.
- A check that cannot fail is not a check. If a test cannot make it report a
  problem, the test is not exercising it.

See [SECURITY.md](SECURITY.md) for reporting a vulnerability. Do not open a
public issue for one.

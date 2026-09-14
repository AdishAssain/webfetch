#!/usr/bin/env python3
"""Refuse to commit anything that should not be in a public repository.

Deterministic on purpose. This repository was pushed to while being believed
private, and every control in the way at that moment was a judgement call —
someone deciding a file looked fine. One of those judgements was wrong. A
pattern either matches or it does not, and this exits non-zero either way.

Four categories:

  secrets           key- and token-shaped values, and private key blocks
  credential files  names that are a credential by definition, such as .env
  internal refs     hosts and addresses belonging to a specific organisation
  home paths        absolute /Users/<name> paths, which leak an account name

Usage: guard_public.py FILE [FILE ...]     (pre-commit passes staged files)

Exit 0 means every file passed. Exit 1 lists what matched and where.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SELF = Path(__file__).resolve()

# The guard and its test necessarily contain the patterns they search for, so
# scanning them would fail on their own definitions. This is the only exemption
# and it is deliberately two named files, not a directory or a glob — widening
# it would be the obvious way to smuggle something past this.
EXEMPT = {SELF, (SELF.parents[1] / "tests" / "test_public_guard.py").resolve()}

SECRETS = [
    ("OpenAI-style key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}")),
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key block", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
    (
        "inline credential",
        # A long opaque value assigned to a credential-shaped name. An empty
        # placeholder and an op:// reference both fail to match, which keeps
        # .env.example committable.
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*"
            r"[\"']?[A-Za-z0-9/+_-]{16,}"
        ),
    ),
]

# Names that are a credential whatever they contain.
CREDENTIAL_NAMES = [
    re.compile(r"^\.env$"),
    re.compile(r"^\.env\.(?!example$).+"),
    re.compile(r".*storage_state.*\.json$"),
    re.compile(r".*\.(pem|p12|pfx|key)$"),
    re.compile(r"^(credentials|secrets)\.json$"),
    re.compile(r".*service-account.*\.json$"),
]

# Organisation-specific references. Public examples belong in documentation
# instead; example.com and example.org exist for exactly this.
INTERNAL_REFS = [
    re.compile(r"(?i)\bnikshay\.in\b"),
    re.compile(r"(?i)\bartpark\.in\b"),
    re.compile(r"(?i)\breports\.nikshay\b"),
]

# /Users/runner and /home/runner are GitHub's CI checkout paths, not a person.
HOME_PATH = re.compile(r"/(?:Users|home)/(?!runner\b)[A-Za-z0-9._-]+/")

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".hypothesis", ".ruff_cache"}

# Domains whose address should not appear as a commit author on a public repo.
# Held here rather than in the hook config because the config is scanned, and a
# literal domain there trips the internal-reference rule above.
WORK_DOMAINS = ("artpark.in",)


def check_author() -> int:
    """Refuse a commit authored from a work address.

    The work address already in this repository's history cannot be removed
    from a public repo with any confidence: forks keep the objects and GitHub
    serves old commit SHAs until a support-requested collection. So the control
    that is worth having prevents the next one instead of undoing the last.
    """
    email = os.environ.get("GIT_AUTHOR_EMAIL_OVERRIDE")  # tests inject here
    if email is None:
        result = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True)
        email = result.stdout.strip()
    if not email:
        print("No git user.email is set. Set one before committing.")
        return 1
    if email.lower().endswith(WORK_DOMAINS):
        print(f"Commit email {email} is a work address. Use your public one:")
        print("  git config user.email <you>@users.noreply.github.com")
        return 1
    return 0


def scan(path: Path) -> list[str]:
    findings: list[str] = []
    resolved = path.resolve()
    if resolved in EXEMPT:
        return findings
    if set(resolved.parts) & SKIP_DIRS:
        return findings

    for pattern in CREDENTIAL_NAMES:
        if pattern.match(path.name):
            findings.append(
                f"{path}: credential file — a file named {path.name} must never be committed"
            )
            return findings  # no point reading it

    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return findings  # deleted, binary, or unreadable: nothing to judge

    for lineno, line in enumerate(text.splitlines(), 1):
        for label, pattern in SECRETS:
            if pattern.search(line):
                findings.append(f"{path}:{lineno}: secret — {label}")
        for pattern in INTERNAL_REFS:
            if pattern.search(line):
                findings.append(
                    f"{path}:{lineno}: internal reference — use an example.com placeholder"
                )
        if HOME_PATH.search(line):
            findings.append(f"{path}:{lineno}: home path — leaks an account name; use ~/ instead")
    return findings


def main(argv: list[str]) -> int:
    if "--check-author" in argv:
        return check_author()

    findings: list[str] = []
    for name in argv:
        path = Path(name)
        if path.is_file():
            findings.extend(scan(path))

    if not findings:
        return 0

    print("Refusing to commit — content that does not belong in a public repository:\n")
    for finding in findings:
        print(f"  {finding}")
    print(
        "\nFix the line, or if this is a deliberate example, rephrase it so the "
        "pattern does not match.\nOverriding with --no-verify defeats the point: "
        "CI runs this same check on the pull request."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

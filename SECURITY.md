# Security policy

## Reporting a vulnerability

Please report security issues privately, not as a public issue.

Use GitHub's [private vulnerability reporting](https://github.com/AdishAssain/webfetch/security/advisories/new)
for this repository. If that is unavailable, open an issue asking for a contact
address. Say only that you have a security report. Do not put details in it.

Please include what you have: affected version or commit, a minimal
reproduction, and what an attacker gains. A proof of concept helps, but a clear
description of the mechanism is enough to start.

Expect an acknowledgement within a week. This is a personal project with no
paid support, so please treat that as a good-faith target rather than an SLA.

## What is in scope

webfetch fetches untrusted remote content on behalf of a caller, so the
interesting boundaries are:

- **SSRF.** `_safeurl.guard()` resolves a host and rejects non-public
  addresses; `_browser.guarded_context()` applies the same check to every
  browser subrequest and redirect. Any route to loopback, link-local, RFC1918
  or carrier-grade NAT space is in scope. That includes DNS rebinding, a
  redirect chain, and a subresource.
- **Session handling.** `storage_state.json` is a credential. Anything that
  widens its permissions, writes it somewhere unintended, or leaks its contents
  into logs or output is in scope.
- **Local file access.** The browser guard blocks `file:` deliberately. A route
  that reads local disk through a rendered page is in scope.
- **Command and path injection** through URLs, selectors, or configuration.

## What is out of scope

- Rate limiting or blocking by a target site.
- Anything that requires `WEBFETCH_ALLOW_PRIVATE=1`. That flag exists to
  disable the SSRF guard for local development and is documented as doing so.
- Denial of service against your own machine by fetching very large pages.
- Findings from automated scanners without a working reproduction.

## Supported versions

The `main` branch only. There are no maintained release branches.

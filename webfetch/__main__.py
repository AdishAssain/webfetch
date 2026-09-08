import argparse
import sys

from .auth import login
from .client import fetch
from .search import discover


def main() -> None:
    parser = argparse.ArgumentParser(prog="webfetch")
    sub = parser.add_subparsers(dest="cmd", required=True)

    get = sub.add_parser("get", help="fetch a page or data file")
    get.add_argument("url")
    get.add_argument("--render", action="store_true", help="force browser render")
    get.add_argument("--auth", action="store_true", help="reuse saved login session")
    get.add_argument("--wait", metavar="SELECTOR", help="render and wait for a CSS selector")
    get.add_argument("--refresh", action="store_true", help="bypass cached content")
    get.add_argument(
        "--archive", action="store_true", help="fall back to an existing Wayback snapshot"
    )

    dis = sub.add_parser("discover", help="search for candidate URLs")
    dis.add_argument("query")
    dis.add_argument("-n", type=int, default=10)

    log = sub.add_parser("login", help="save a login session for a gated site")
    log.add_argument("url")

    doc = sub.add_parser("doctor", help="check the install and report what is broken")
    doc.add_argument("--live", action="store_true", help="also make one request per engine")
    doc.add_argument("--json", action="store_true", help="machine-readable output")

    args = parser.parse_args()
    if args.cmd == "get":
        r = fetch(
            args.url,
            render=args.render,
            auth=args.auth,
            wait=args.wait,
            refresh=args.refresh,
            archive=args.archive,
        )
        print(f"[{r.engine}] status={r.status} tables={len(r.tables)} url={r.url}")
        if r.fallback_reason:
            print(f"fallback: {r.fallback_reason}", file=sys.stderr)
        if r.archive_url:
            print(f"archived: {r.archive_timestamp} {r.archive_url}", file=sys.stderr)
        if r.dataframe is not None:
            print(r.dataframe.head())
        else:
            print((r.text or r.markdown)[:2000])
        if r.error or r.status >= 400:
            print(f"error: {r.error or f'HTTP {r.status}'}", file=sys.stderr)
            sys.exit(1)
    elif args.cmd == "discover":
        for item in discover(args.query, n=args.n):
            print(f"- {item['title']}\n  {item['url']}")
    elif args.cmd == "login":
        print(f"Saved session -> {login(args.url)}")
    elif args.cmd == "doctor":
        from .doctor import report, run

        # Exit code carries the verdict so a caller can branch on it.
        sys.exit(report(run(live=args.live), as_json=args.json))


if __name__ == "__main__":
    main()

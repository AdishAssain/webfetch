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
        r = fetch(args.url, render=args.render, auth=args.auth)
        print(f"[{r.engine}] status={r.status} tables={len(r.tables)} url={r.url}")
        if r.dataframe is not None:
            print(r.dataframe.head())
        else:
            print(r.text[:2000])
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

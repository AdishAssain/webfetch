import argparse

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


if __name__ == "__main__":
    main()

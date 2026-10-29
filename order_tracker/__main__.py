"""Command line, for syncing on a schedule without the app open.

    python -m order_tracker sync               # every user who connected Gmail, every source
    python -m order_tracker sync --user you@gmail.com --days 30 --sources careem meezan
    python -m order_tracker sync --since 2023-01-01 --until 2024-02-15 --sources stmt:meezan
    python -m order_tracker export ledger.csv --user you@gmail.com

Each user is synced with the Gmail permission they granted in the app, and
their own banks and wallets.
"""

import argparse
import datetime as dt
import sys

from google.auth.exceptions import RefreshError

from . import auth
from .config import load_google_config, token_key
from .gmail_client import GmailClient
from .institutions import source_key
from .ledger import build_ledger
from .storage import OrderStore
from .sync import available_sources, sync_gmail
from .users import all_user_dirs, load_profile


def _matches(directory, email: str | None) -> bool:
    if not email:
        return True
    profile = load_profile(directory)
    return profile is not None and profile.email.lower() == email.lower()


def cmd_sync(args) -> int:
    config = load_google_config()
    if config is None:
        print("Google isn't configured. See the README.", file=sys.stderr)
        return 1
    encryption_key = token_key()
    synced = 0
    for directory in all_user_dirs():
        if not _matches(directory, args.user):
            continue
        tokens = auth.GmailTokenStore(directory, encryption_key)
        saved = tokens.load()
        if saved is None:
            continue
        try:
            creds = auth.build_credentials(config, saved["refresh_token"])
        except RefreshError:
            tokens.delete()
            print(f"{saved['account']}: Gmail access was withdrawn; they need to reconnect in the app.")
            continue

        store = OrderStore(directory / "orders.db")
        sources = available_sources(store)
        names = args.sources or list(sources)
        chosen = [sources[k] for k in (n if n in sources else source_key(n) for n in names) if k in sources]
        results = sync_gmail(GmailClient(creds), store, chosen, args.days, saved["account"],
                             since=args.since, until=args.until)
        print(saved["account"])
        for key, stats in results.items():
            print(
                f"  {sources[key].name:<20} checked {stats.checked:>4}  added {stats.added:>4}"
                f"  skipped {stats.skipped:>4}  errors {stats.errors:>3}"
            )
        store.close()
        synced += 1

    if not synced:
        print("No users with Gmail connected" + (f" matching {args.user}" if args.user else "") + ".")
    return 0


def cmd_export(args) -> int:
    matches = [d for d in all_user_dirs() if _matches(d, args.user)]
    if len(matches) != 1:
        print("Pass --user with the email of exactly one user.", file=sys.stderr)
        return 2
    store = OrderStore(matches[0] / "orders.db")
    build_ledger(store).to_csv(args.path, index=False)
    store.close()
    print(f"Wrote {args.path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m order_tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="fetch new orders and transactions from Gmail")
    sync.add_argument("--user", metavar="EMAIL", help="only this user (default: everyone who connected Gmail)")
    sync.add_argument("--days", type=int, default=365, help="how far back to search (default 365)")
    sync.add_argument(
        "--sources", nargs="+", metavar="SOURCE",
        help="delivery services (foodpanda, careem, indrive, kravemart), bank or wallet keys for their "
             "alerts (meezan), and stmt:<key> for their statements (stmt:meezan); default all",
    )
    sync.add_argument("--since", type=dt.date.fromisoformat, metavar="YYYY-MM-DD",
                      help="read an older period starting here, instead of the last --days")
    sync.add_argument("--until", type=dt.date.fromisoformat, metavar="YYYY-MM-DD",
                      help="end of that period (default: now)")
    sync.set_defaults(func=cmd_sync)

    export = sub.add_parser("export", help="write one user's orders and transactions to a CSV file")
    export.add_argument("path")
    export.add_argument("--user", metavar="EMAIL", help="whose data (required when there are several users)")
    export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

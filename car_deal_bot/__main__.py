from __future__ import annotations

import argparse

from car_deal_bot.run import run_once
from car_deal_bot.scheduler import run_scheduler


def main() -> None:
    parser = argparse.ArgumentParser(description="Car deal notification bot.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run-once", help="Fetch listings once and send notification.")
    sub.add_parser("schedule", help="Run daily at the time configured in config.yaml.")

    args = parser.parse_args()
    if args.command == "run-once":
        run_once()
    elif args.command == "schedule":
        run_scheduler()


if __name__ == "__main__":
    main()

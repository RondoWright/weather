from __future__ import annotations

import argparse
import json
import os
import time

from bot.config import load_config
from bot.core.engine import run_scan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket weather signal bot")
    parser.add_argument(
        "--config",
        default=os.getenv("BOT_CONFIG_PATH", "config/config.yaml"),
        help="Config YAML path (optional)",
    )
    parser.add_argument(
        "--mode",
        choices=("scan", "alert", "paper"),
        default=os.getenv("BOT_MODE", "alert"),
    )
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    interval = int(cfg["bot"]["scan_interval_seconds"])

    run_once = args.once or os.getenv("BOT_RUN_ONCE", "").lower() in {"1", "true", "yes"}
    while True:
        payload = run_scan(cfg, mode=args.mode)
        print(json.dumps(payload), flush=True)
        if args.mode == "scan" or run_once:
            return 0
        time.sleep(max(5, interval))


if __name__ == "__main__":
    raise SystemExit(main())

"""
collector.py — Intraday snapshot collector for 3D surface time evolution.
Runs during market hours, saves a parquet snapshot every INTERVAL seconds.
Snapshots land in ./snapshots/ and are consumed by the dashboard Time Evolution tab.

Usage:
    python3 collector.py                  # runs until market close
    python3 collector.py --interval 60    # snapshot every 60s
"""
import os
import time
import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import scanner
import config

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("collector.log")],
)
log = logging.getLogger(__name__)

TZ_ET = ZoneInfo("America/New_York")
SNAPSHOT_DIR = "snapshots"


def is_market_open() -> bool:
    now = datetime.now(TZ_ET)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


def save_snapshot(df: pd.DataFrame, spot: float) -> str:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    ts = datetime.now(TZ_ET).strftime("%Y%m%d_%H%M%S")
    df = df.copy()
    df["timestamp"] = datetime.now(TZ_ET).strftime("%H:%M:%S")
    df["spot"] = spot
    path = os.path.join(SNAPSHOT_DIR, f"snapshot_{ts}.parquet")
    df.to_parquet(path, index=False)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=30, help="Seconds between snapshots")
    parser.add_argument("--force", action="store_true", help="Run even outside market hours")
    args = parser.parse_args()

    log.info("Collector started | interval=%ds | expiry=%s", args.interval, config.EXPIRY)

    if not args.force and not is_market_open():
        log.warning("Market is closed. Use --force to run anyway.")
        return

    snapshots_taken = 0
    while True:
        if not args.force and not is_market_open():
            log.info("Market closed. Collector stopping. Snapshots taken: %d", snapshots_taken)
            break

        try:
            df, spot = scanner.run_scan()
            if df.empty:
                log.warning("Empty scan result, skipping snapshot.")
            else:
                path = save_snapshot(df, spot)
                snapshots_taken += 1
                log.info("Snapshot #%d saved → %s | contracts=%d spot=$%s",
                         snapshots_taken, path, len(df), spot)
        except Exception as exc:
            log.error("Scan failed: %s", exc)

        time.sleep(args.interval)


if __name__ == "__main__":
    main()

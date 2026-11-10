"""Cold backfill planner. HEAD metadata only; never reads archive bodies."""
import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone

import httpx


TYPES = {"trade", "orderbook", "klines", "funding", "openinterest", "longshortratio"}
INTERVALS = {"1m": 1, "5m": 5, "15m": 15}
API = "https://api.bybit.com/v5/market/"


def plan(start, end, symbols, types, intervals, client):
    """Return one deterministic output per UTC day/series, with archive HEAD sizes."""
    if start > end or end >= datetime.now(timezone.utc).date():
        raise ValueError("Require an ordered range of closed UTC days")
    if not symbols or any(not re.fullmatch(r"[A-Z0-9]+USDT", s) for s in symbols):
        raise ValueError("Require linear USDT symbols")
    if not types or not set(types) <= TYPES:
        raise ValueError("Unknown or empty data types")
    if not intervals or not set(intervals) <= INTERVALS.keys():
        raise ValueError("Supported intervals: 1m,5m,15m")
    jobs = []
    day = start
    while day <= end:
        for symbol in sorted(set(symbols)):
            for kind in sorted(set(types)):
                for interval in sorted(set(intervals)) if kind == "klines" else [None]:
                    job = {"day": day.isoformat(), "symbol": symbol, "type": kind,
                           "interval": interval, "timezone": "UTC", "expected_bytes": None}
                    if kind == "trade":
                        filename = f"{symbol}{day}.csv.gz"
                        job.update(source="archive", url=f"https://public.bybit.com/trading/{symbol}/{filename}",
                                   path=f"historical/trade/contract/{symbol}/{filename}")
                    elif kind == "orderbook":
                        filename = f"{day}_{symbol}_ob200.data.zip"
                        job.update(source="archive",
                                   url=f"https://quote-saver.bycsi.com/orderbook/linear/{symbol}/{filename}",
                                   path=f"historical/orderbook/contract/{symbol}/{filename}")
                    else:
                        endpoint = {"klines": "kline", "funding": "funding/history",
                                    "openinterest": "open-interest", "longshortratio": "account-ratio"}[kind]
                        folder = (f"historical/klines/linear/{symbol}/{interval}" if kind == "klines"
                                  else f"market_metrics/{kind}/{symbol}")
                        job.update(source="api", url=API + endpoint, path=f"{folder}/{day}.json")
                    if job["source"] == "archive":
                        response = client.head(job["url"])
                        response.raise_for_status()
                        size = int(response.headers.get("Content-Length", "0"))
                        if size <= 0:
                            raise ValueError(f"Missing archive size: {job['path']}")
                        job["expected_bytes"] = size
                    jobs.append(job)
        day += timedelta(days=1)
    return jobs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--types", default="trade,orderbook,klines,funding,openinterest,longshortratio")
    parser.add_argument("--intervals", default="1m,5m,15m")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("This planner requires --dry-run; execution is delivered separately")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        jobs = plan(args.start_date, args.end_date, args.symbols.split(","),
                    args.types.split(","), args.intervals.split(","), client)
    print(json.dumps({"days": (args.end_date - args.start_date).days + 1,
                      "files": len(jobs), "archive_bytes": sum(j["expected_bytes"] or 0 for j in jobs),
                      "api_files_unknown_bytes": sum(j["source"] == "api" for j in jobs),
                      "data_root": args.data_root, "jobs": jobs}, indent=2))


if __name__ == "__main__":
    main()

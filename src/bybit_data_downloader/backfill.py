"""Cold backfill; --dry-run uses HEAD metadata without reading archive bodies."""
import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from .backfill_retry import RetryPolicy
from .backfill_execute import BackfillDataError, execute, record_failure, run_stats, write_run_log


TYPES = {"trade", "orderbook", "klines", "funding", "openinterest", "longshortratio"}
INTERVALS = {"1m": 1, "5m": 5, "15m": 15}
API = "https://api.bybit.com/v5/market/"


def plan(start, end, symbols, types, intervals, client, *, active_job=None, retry=RetryPolicy(), on_retry=None):
    """Return one deterministic output per UTC day/series, with archive HEAD sizes."""
    if start > end or end >= datetime.now(timezone.utc).date():
        raise BackfillDataError("Require an ordered range of closed UTC days")
    if not symbols or any(not re.fullmatch(r"[A-Z0-9]+USDT", s) for s in symbols):
        raise BackfillDataError("Require linear USDT symbols")
    if not types or not set(types) <= TYPES:
        raise BackfillDataError("Unknown or empty data types")
    if not intervals or not set(intervals) <= INTERVALS.keys():
        raise BackfillDataError("Supported intervals: 1m,5m,15m")
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
                        if active_job is not None:
                            active_job.update(job)
                        def head():
                            response = client.head(job["url"])
                            response.raise_for_status()
                            return response
                        response = retry.run(head, job["path"], on_retry=on_retry)
                        try:
                            size = int(response.headers.get("Content-Length", "0"))
                        except ValueError:
                            raise BackfillDataError("Invalid archive size metadata") from None
                        if size <= 0:
                            raise BackfillDataError("Missing archive size metadata")
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
    parser.add_argument("--retry-attempts", type=int, default=RetryPolicy.attempts)
    parser.add_argument("--retry-base-delay", type=float, default=RetryPolicy.base_delay)
    parser.add_argument("--retry-max-delay", type=float, default=RetryPolicy.max_delay)
    args = parser.parse_args(argv)
    retry = RetryPolicy(args.retry_attempts, args.retry_base_delay, args.retry_max_delay)
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        active_job = {}
        planning = run_stats([])
        planning.update(phase="planning", start_date=args.start_date.isoformat(), end_date=args.end_date.isoformat())
        try:
            jobs = plan(args.start_date, args.end_date, args.symbols.split(","),
                        args.types.split(","), args.intervals.split(","), client, active_job=active_job, retry=retry,
                        on_retry=lambda _: planning.update(retries=planning["retries"] + 1))
        except Exception as error:
            record_failure(planning, error, active_job)
            write_run_log(planning, None if args.dry_run else args.data_root)
            raise
        if not args.dry_run:
            execute(jobs, args.data_root, client, retry=retry, planning_retries=planning["retries"])
            return
    print(json.dumps({"days": (args.end_date - args.start_date).days + 1,
                      "files": len(jobs), "archive_bytes": sum(j["expected_bytes"] or 0 for j in jobs),
                      "api_files_unknown_bytes": sum(j["source"] == "api" for j in jobs),
                      "data_root": args.data_root, "jobs": jobs, "retries": planning["retries"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Planning/execution already emitted the complete summary, even if JSONL failed.
        # Suppress tracebacks without duplicating that run in the scheduler journal.
        raise SystemExit(1)

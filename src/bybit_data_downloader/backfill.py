"""Cold backfill; --dry-run uses HEAD metadata without reading archive bodies."""
import argparse
import json
import sys
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, ValidationError

from .backfill_retry import RetryPolicy
from scripts.cold_deploy import emit
from .backfill_execute import (DAY, ORDERBOOK_TAIL_MAX_MS, BackfillDataError, execute, manifest_schema,
                               record_failure, run_stats, write_run_log)


TYPES = {"trade", "orderbook", "klines", "funding", "openinterest", "longshortratio"}
INTERVALS = {"1m": 1, "5m": 5, "15m": 15}
API = "https://api.bybit.com/v5/market/"


def selection(symbols, types, intervals):
    """Validate the request and return its series as (symbol, type, interval) triples."""
    if not symbols or any(not re.fullmatch(r"[A-Z0-9]+USDT", s) for s in symbols):
        raise BackfillDataError("Require linear USDT symbols")
    if not types or not set(types) <= TYPES:
        raise BackfillDataError("Unknown or empty data types")
    if not intervals or not set(intervals) <= INTERVALS.keys():
        raise BackfillDataError("Supported intervals: 1m,5m,15m")
    return [(symbol, kind, interval) for symbol in sorted(set(symbols)) for kind in sorted(set(types))
            for interval in (sorted(set(intervals)) if kind == "klines" else [None])]


def job_for(day, symbol, kind, interval):
    """Source and cold path of one UTC series day, without network metadata."""
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
    return job


def complete_days(root, symbol, kind, interval):
    """Days whose closed manifest matches the series layout and whose file still exists."""
    days = set()
    folder = (root / job_for(date.min, symbol, kind, interval)["path"]).parent
    for manifest in folder.glob("*.manifest.json"):
        try:
            saved = json.loads(manifest.read_text())
            job = job_for(date.fromisoformat(saved["day"]), symbol, kind, interval)
            target = root / job["path"]
            schema = manifest_schema(job)
            # HEAD sizes are not fetched here; execution re-verifies size, SHA256 and records.
            schema["properties"]["expected_bytes"] = ({"type": "integer", "minimum": 1}
                                                      if job["source"] == "archive" else {"const": None})
            Draft202012Validator(schema).validate(saved)
            if manifest == target.with_suffix(target.suffix + ".manifest.json") and target.is_file():
                days.add(date.fromisoformat(job["day"]))
        except (ValueError, TypeError, KeyError, OSError, ValidationError):
            continue  # Unverifiable manifests never count as complete days.
    return days


def first_incomplete(root, end, series):
    """Earliest day to fetch: per series, the first gap after its first complete day, else `end`."""
    start = end
    for symbol, kind, interval in series:
        days = complete_days(Path(root), symbol, kind, interval)
        day = min(days, default=end)
        while day < start and day in days:
            day += timedelta(days=1)
        start = min(start, day)
    return start


def plan(start, end, symbols, types, intervals, client, *, active_job=None, retry=RetryPolicy(), on_retry=None, emission_state=None):
    """Return one deterministic output per UTC day/series, with archive HEAD sizes."""
    if start > end or end >= datetime.now(timezone.utc).date():
        raise BackfillDataError("Require an ordered range of closed UTC days")
    series = selection(symbols, types, intervals)
    jobs = []
    day = start
    while day <= end:
        for symbol, kind, interval in series:
            job = job_for(day, symbol, kind, interval)
            if job["source"] == "archive":
                if active_job is not None:
                    active_job.update(job)
                def head():
                    response = client.head(job["url"])
                    response.raise_for_status()
                    return response
                response = retry.run(head, job["path"], on_retry=on_retry, emission_state=emission_state)
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
    first = parser.add_mutually_exclusive_group(required=True)
    first.add_argument("--start-date", type=date.fromisoformat)
    first.add_argument("--from-last-complete", action="store_true",
                       help="Start at the earliest series day after its last verified manifest")
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--types", default="trade,orderbook,klines,funding,openinterest,longshortratio")
    parser.add_argument("--intervals", default="1m,5m,15m")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--orderbook-tail-max-ms", type=int, default=ORDERBOOK_TAIL_MAX_MS,
                        help="Maximum final orderbook tail offset past UTC midnight (default: 60000 ms)")
    parser.add_argument("--retry-attempts", type=int, default=RetryPolicy.attempts)
    parser.add_argument("--retry-base-delay", type=float, default=RetryPolicy.base_delay)
    parser.add_argument("--retry-max-delay", type=float, default=RetryPolicy.max_delay)
    args = parser.parse_args(argv)
    if not 1 <= args.orderbook_tail_max_ms < DAY:
        parser.error(f"--orderbook-tail-max-ms must be an integer between 1 and {DAY - 1}")
    retry = RetryPolicy(args.retry_attempts, args.retry_base_delay, args.retry_max_delay)
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        active_job = {}
        planning = run_stats([])
        planning.update(phase="planning", end_date=args.end_date.isoformat())
        try:
            if args.from_last_complete:
                args.start_date = first_incomplete(args.data_root, args.end_date, selection(
                    args.symbols.split(","), args.types.split(","), args.intervals.split(",")))
            planning["start_date"] = args.start_date.isoformat()
            jobs = plan(args.start_date, args.end_date, args.symbols.split(","),
                        args.types.split(","), args.intervals.split(","), client, active_job=active_job, retry=retry,
                        on_retry=lambda _: planning.update(retries=planning["retries"] + 1), emission_state=planning)
        except Exception as error:
            record_failure(planning, error, active_job)
            write_run_log(planning, None if args.dry_run else args.data_root)
            raise
        if not args.dry_run:
            execute(jobs, args.data_root, client, retry=retry, planning_retries=planning["retries"],
                    orderbook_tail_max_ms=args.orderbook_tail_max_ms,
                    planning_emission={k: planning[k] for k in ("log_error", "events_not_written") if k in planning})
            return
    result = {"days": (args.end_date - args.start_date).days + 1,
                      "files": len(jobs), "archive_bytes": sum(j["expected_bytes"] or 0 for j in jobs),
                      "api_files_unknown_bytes": sum(j["source"] == "api" for j in jobs),
                      "data_root": args.data_root, "jobs": jobs, "retries": planning["retries"],
                      "events_not_written": planning["events_not_written"], "outcome": "success"}
    if planning.get("log_error"):
        result.update(outcome="failure", log_error=planning["log_error"])
    emit(result, result, stream=sys.stdout)
    if result.get("log_error"):
        raise OSError("Log emission failed")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Planning/execution already emitted the complete summary, even if JSONL failed.
        # Suppress tracebacks without duplicating that run in the scheduler journal.
        raise SystemExit(1)

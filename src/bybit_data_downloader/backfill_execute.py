"""Verified cold files: streaming containers, UTC grids, atomic per-series days."""
import csv
import fcntl
import gzip
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
import zlib
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from itertools import islice
from pathlib import Path
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator, ValidationError

from .backfill_retry import RetryPolicy
from scripts.cold_deploy import emit

DAY = 86400000
ORDERBOOK_TAIL_MAX_MS = 60000
TRADE_V1_FIELDS = "timestamp symbol side size price tickDirection trdMatchID grossValue homeNotional foreignNotional".split()
TRADE_V2_FIELDS = TRADE_V1_FIELDS + ["RPI"]
NUMBER = {"type": "string", "pattern": r"^-?[0-9]+(?:\.[0-9]+)?$"}


class BackfillDataError(ValueError):
    """Validation failures whose messages contain only backfill-owned text."""


def object_schema(properties, required=None):
    return {"type": "object", "properties": properties, "required": required or list(properties),
            "additionalProperties": False}


def bounds(job):
    start = int(datetime.fromisoformat(job["day"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
    return start, start + DAY


def positive(value, zero=False):
    number = Decimal(value)
    if not number.is_finite() or number < 0 or (not zero and number == 0):
        raise BackfillDataError("Invalid numeric value")


def validate(path, job):
    count, _ = scan(path, job)
    return count


def scan(path, job, *, allow_orderbook_tail=False, orderbook_tail_max_ms=ORDERBOOK_TAIL_MAX_MS):
    try:
        return _validate(path, job, allow_orderbook_tail, orderbook_tail_max_ms)
    except (DecimalException, csv.Error, zlib.error) as error:
        raise BackfillDataError("Invalid archive record or compressed stream") from error


def _validate(path, job, allow_orderbook_tail, orderbook_tail_max_ms):
    start, end = bounds(job)
    if job["source"] == "api":
        rows = json.loads(path.read_text())
        kind = job["type"]
        if kind == "klines":
            schema = {"type": "array", "minItems": 7, "maxItems": 7, "items": NUMBER}
            step = {"1m": 60000, "5m": 300000, "15m": 900000}[job["interval"]]
        else:
            fields = {"funding": ["symbol", "fundingRate", "fundingRateTimestamp"],
                      "openinterest": ["openInterest", "timestamp"],
                      "longshortratio": ["symbol", "buyRatio", "sellRatio", "timestamp"]}[kind]
            properties = {key: ({"const": job["symbol"]} if key == "symbol" else NUMBER) for key in fields}
            if kind == "openinterest": properties["singleOpenInterest"] = NUMBER
            schema = object_schema(properties, fields)
            if kind == "funding" and job["symbol"] not in {"BTCUSDT", "ETHUSDT"}:
                raise BackfillDataError("No verified historical funding grid for this symbol")
            step = 28800000 if kind == "funding" else DAY
        Draft202012Validator({"type": "array", "items": schema}).validate(rows)
        times = [int(row[0] if kind == "klines" else row[
            "fundingRateTimestamp" if kind == "funding" else "timestamp"]) for row in rows]
        if sorted(times) != list(range(start, end, step)):
            raise BackfillDataError("Incomplete or duplicate UTC grid")
        for row in rows:
            values = row[1:] if kind == "klines" else [v for k, v in row.items() if k not in {"symbol", "timestamp", "fundingRateTimestamp"}]
            for value in values:
                if kind != "funding": positive(value, zero=True)
            if kind == "longshortratio" and abs(Decimal(row["buyRatio"]) + Decimal(row["sellRatio"]) - 1) > Decimal("0.000001"):
                raise BackfillDataError("Invalid account ratio sum")
            if kind == "klines":
                for value in row[1:5]: positive(value)
            if kind == "klines" and not (Decimal(row[3]) <= min(Decimal(row[1]), Decimal(row[4])) <= max(Decimal(row[1]), Decimal(row[4])) <= Decimal(row[2])):
                raise BackfillDataError("Invalid candle range")
        return len(rows), 0
    # SQLite bounds memory for millions of trade IDs; this database is disposable.
    with tempfile.TemporaryDirectory(dir=path.parent) as scratch, sqlite3.connect(Path(scratch) / "ids") as ids:
        ids.execute("CREATE TABLE seen (id TEXT PRIMARY KEY)")
        minutes, previous, count, discarded = set(), start, 0, 0
        tail_allowed = allow_orderbook_tail and job["type"] == "orderbook"
        max_offset, tail_start = 0, None
        def accept(timestamp, identity):
            nonlocal previous, count, discarded, max_offset, tail_start
            position = count + discarded + 1
            tail_rows = discarded
            if timestamp >= end:
                max_offset = max(max_offset, timestamp - end)
                tail_start = tail_start or position
                tail_rows += 1
            if (timestamp < start or timestamp >= end + DAY or timestamp < previous
                    or (timestamp < end and discarded)
                    or (timestamp >= end and (not tail_allowed or max_offset > orderbook_tail_max_ms))):
                raise BackfillDataError(
                    f"Record outside ordered UTC day: position={position}, rows_seen={position}, "
                    f"tail_start={tail_start}, tail_rows={tail_rows}, max_offset_ms={max_offset}, "
                    f"limit_ms={orderbook_tail_max_ms if tail_allowed else 0}")
            try: ids.execute("INSERT INTO seen VALUES (?)", (identity,))
            except sqlite3.IntegrityError: raise BackfillDataError("Duplicate record ID") from None
            if timestamp < end:
                minutes.add(int((timestamp - start) // 60000))
                count += 1
            else:
                discarded += 1
            previous = timestamp
        if job["type"] == "trade":
            with gzip.open(path, "rt", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                fields = reader.fieldnames
                if fields not in (TRADE_V1_FIELDS, TRADE_V2_FIELDS):
                    raise BackfillDataError("Unexpected trade schema")
                for row in reader:
                    if set(row) != set(fields) or any(value is None for value in row.values()): raise BackfillDataError("Malformed CSV row")
                    if fields == TRADE_V2_FIELDS and row["RPI"] not in {"0", "1"}:
                        raise BackfillDataError("Invalid trade RPI")
                    if row["symbol"] != job["symbol"] or row["side"] not in {"Buy", "Sell"} or not row["trdMatchID"]:
                        raise BackfillDataError("Invalid trade identity")
                    if row["tickDirection"] not in {"PlusTick", "ZeroPlusTick", "MinusTick", "ZeroMinusTick"}: raise BackfillDataError("Invalid tick direction")
                    for key in ["size", "price", "grossValue", "homeNotional", "foreignNotional"]: positive(row[key])
                    accept(Decimal(row["timestamp"]) * 1000, row["trdMatchID"])
        else:
            pair = {"type": "array", "minItems": 2, "maxItems": 2, "items": NUMBER}
            data = object_schema({"s": {"const": job["symbol"]}, "b": {"type": "array", "items": pair},
                                  "a": {"type": "array", "items": pair}, "u": {"type": "integer"}, "seq": {"type": "integer"}})
            schema = object_schema({"type": {"enum": ["snapshot", "delta"]}, "ts": {"type": "integer"},
                                    "data": data, "cts": {"type": "integer"}, "topic": {"type": "string"}}, ["type", "ts", "data"])
            validator = Draft202012Validator(schema)
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if len(names) != 1 or not names[0].endswith(".data"): raise BackfillDataError("Unexpected ZIP members")
                with archive.open(names[0]) as stream:
                    for line in io.TextIOWrapper(stream):
                        row = json.loads(line)
                        validator.validate(row)
                        if count == 0 and row["type"] != "snapshot": raise BackfillDataError("Missing initial snapshot")
                        for price, size in row["data"]["b"] + row["data"]["a"]:
                            positive(price); positive(size, zero=True)
                        accept(row["ts"], f"{row['ts']}:{row['data']['u']}:{row['data']['seq']}")
        if minutes != set(range(1440)): raise BackfillDataError("Incomplete archive UTC minute coverage")
        return count, discarded


def publish_orderbook_day(staging, target, count, job):
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as filtered:
        path = Path(filtered.name)
        try:
            with zipfile.ZipFile(staging) as source, zipfile.ZipFile(filtered, "w", zipfile.ZIP_DEFLATED) as output:
                member = source.namelist()[0]
                with source.open(member) as records, output.open(member, "w", force_zip64=True) as day:
                    # Match the scanner's universal newline segmentation, preserving record bytes.
                    with io.TextIOWrapper(records, newline="") as lines:
                        day.writelines(line.encode("utf-8") for line in islice(lines, count))
            filtered.flush()
            os.fsync(filtered.fileno())
            if validate(path, job) != count:
                raise BackfillDataError("Record count mismatch")
            path.replace(target)
        finally:
            path.unlink(missing_ok=True)


def api_rows(client, job):
    start, end = bounds(job)
    kind, rows = job["type"], []
    params = {"category": "linear", "symbol": job["symbol"], "limit": 200}
    params.update({"start": start, "end": end - 1, "interval": str({"1m": 1, "5m": 5, "15m": 15}[job["interval"]]), "limit": 1000}
                  if kind == "klines" else {"startTime": start, "endTime": end - 1})
    if kind == "openinterest": params["intervalTime"] = "1d"
    if kind == "longshortratio": params["period"] = "1d"
    cursors = set()
    while True:
        response = client.get(job["url"], params=params)
        response.raise_for_status()
        body = response.json()
        result_schema = object_schema({"category": {"const": "linear"}, "symbol": {"const": job["symbol"]},
            "list": {"type": "array"}, "nextPageCursor": {"type": "string"}}, ["list"])
        Draft202012Validator(object_schema({"retCode": {"const": 0}, "retMsg": {"type": "string"},
            "result": result_schema, "retExtInfo": object_schema({}, []), "time": {"type": "integer"}},
            ["retCode", "result"])).validate(body)
        result = body["result"]
        if result.get("symbol", job["symbol"]) != job["symbol"]: raise BackfillDataError("API symbol mismatch")
        page = result["list"]
        rows.extend(page)
        cursor = result.get("nextPageCursor")
        if cursor:
            if cursor in cursors: raise BackfillDataError("Repeated API cursor")
            cursors.add(cursor); params["cursor"] = cursor
        elif kind in {"klines", "funding"} and len(page) == params["limit"]:
            oldest = min(int(row[0] if kind == "klines" else row["fundingRateTimestamp"]) for row in page)
            key = "end" if kind == "klines" else "endTime"
            if oldest <= start: break
            if oldest > params[key]: raise BackfillDataError("API pagination did not progress")
            params[key] = oldest - 1
        else: break
    return rows


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): result.update(chunk)
    return result.hexdigest()


def run_stats(jobs):
    return dict(outcome="failure", downloaded=0, skipped=0, records=0, quarantined=[], files=len(jobs), timezone="UTC",
                discarded_orderbook_tail=0, retries=0, events_not_written=0,
                started_at=datetime.now(timezone.utc).isoformat(), days=sorted({job["day"] for job in jobs}))


def record_failure(stats, error, job):
    # Third-party exception strings can include URLs, response bodies or file paths.
    if isinstance(error, BackfillDataError):
        message = str(error)
    elif isinstance(error, httpx.HTTPStatusError):
        message = f"HTTP status {error.response.status_code}"
    elif isinstance(error, ValidationError):
        schema_path = "/".join(map(str, error.absolute_schema_path))
        message = f"Schema validation failed at {schema_path}"
    elif isinstance(error, json.JSONDecodeError):
        message = f"Invalid JSON at line {error.lineno}, column {error.colno}"
    elif isinstance(error, gzip.BadGzipFile):
        message = "Invalid gzip archive"
    elif isinstance(error, zipfile.BadZipFile):
        message = "Invalid ZIP archive"
    elif isinstance(error, EOFError):
        message = "Unexpected end of archive"
    elif isinstance(error, OSError) and error.errno is not None:
        message = os.strerror(error.errno)
    else:
        message = f"{stats['phase'].capitalize()} failed ({type(error).__name__})"
    stats.update(outcome="failure", error="ValueError" if isinstance(error, BackfillDataError) else type(error).__name__,
                 error_message=message,
                 error_type=job.get("type"), error_day=job.get("day"),
                 error_symbol=job.get("symbol"), error_target=job.get("path"))


def write_run_log(stats, root):
    """Journal survives unavailable cold storage; persistence errors still fail the run."""
    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    if stats.get("log_error"):
        stats["outcome"] = "failure"
    emit(stats, stats, stream=sys.stdout, log=None if root is None else Path(root) / "logs/backfill.jsonl")
    if stats.get("log_error"):
        raise OSError("Log emission failed")


def download_file(client, job, target, *, orderbook_tail_max_ms=ORDERBOOK_TAIL_MAX_MS):
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
        staging = Path(stream.name)
        try:
            if job["source"] == "archive":
                with client.stream("GET", job["url"], headers={"Accept-Encoding": "identity"}) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes(): stream.write(chunk)
            else: stream.write(json.dumps(api_rows(client, job)).encode())
            stream.flush(); os.fsync(stream.fileno())
            if job["expected_bytes"] is not None and staging.stat().st_size != job["expected_bytes"]: raise BackfillDataError("Archive size mismatch")
            count, discarded = scan(staging, job, allow_orderbook_tail=True,
                                    orderbook_tail_max_ms=orderbook_tail_max_ms)
            if discarded:
                publish_orderbook_day(staging, target, count, job)
            else:
                staging.replace(target)
        finally: staging.unlink(missing_ok=True)
    return count, discarded


def execute(jobs, root, client, *, retry=RetryPolicy(), planning_retries=0, planning_emission=None,
            orderbook_tail_max_ms=ORDERBOOK_TAIL_MAX_MS):
    stats = run_stats(jobs)
    stats.update(phase="execution", retries=planning_retries, **(planning_emission or {}))
    job = {}
    try:
        Draft202012Validator({"type": "integer", "minimum": 1, "maximum": DAY - 1}).validate(orderbook_tail_max_ms)
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        with (root / ".backfill.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for job in jobs:
                target = root / job["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                manifest = target.with_suffix(target.suffix + ".manifest.json")
                count = None
                discarded = 0
                if target.exists() or manifest.exists():
                    reason = "missing-or-inconsistent-manifest"
                    try:
                        saved = json.loads(manifest.read_text())
                        fields = {key: {"const": value} for key, value in job.items()}
                        fields.update(complete={"const": True}, records={"type": "integer", "minimum": 1},
                                      sha256={"type": "string", "pattern": "^[0-9a-f]{64}$"},
                                      integrity={"const": ("container-crc-and-schema" if job["source"] == "archive" else "json-schema-and-grid") + "; sha256-local-not-upstream"})
                        required = list(fields)
                        if job["type"] == "orderbook":
                            fields["discarded_orderbook_tail_v1"] = {"type": "integer", "minimum": 1}
                        Draft202012Validator(object_schema(fields, required)).validate(saved)
                        reason = "sha256-mismatch"
                        if digest(target) != saved["sha256"]: raise BackfillDataError("SHA256 mismatch")
                        reason = "invalid-cached-records"
                        discarded = saved.get("discarded_orderbook_tail_v1", 0)
                        if not discarded and job["expected_bytes"] is not None and target.stat().st_size != job["expected_bytes"]:
                            raise BackfillDataError("Size mismatch")
                        count = validate(target, job)
                        if count != saved["records"]: raise BackfillDataError("Record count mismatch")
                    except (ValueError, OSError, EOFError, zipfile.BadZipFile, ValidationError) as error:
                        count = None
                        suffix = ".quarantine." + uuid4().hex
                        for rejected in (target, manifest):
                            if rejected.exists(): rejected.rename(rejected.with_name(rejected.name + suffix))
                        stats["quarantined"].append(dict(path=job["path"], reason=reason, error="ValueError" if isinstance(error, BackfillDataError)
                                                        else type(error).__name__))
                if count is None:
                    count, discarded = retry.run(
                        lambda: download_file(client, job, target, orderbook_tail_max_ms=orderbook_tail_max_ms),
                        job["path"], on_retry=lambda _: stats.update(retries=stats["retries"] + 1),
                        emission_state=stats)
                    stats["discarded_orderbook_tail"] += discarded
                    stats["downloaded"] += 1
                else: stats["skipped"] += 1
                data = dict(job, complete=True, records=count, sha256=digest(target),
                            integrity=("container-crc-and-schema" if job["source"] == "archive" else "json-schema-and-grid") + "; sha256-local-not-upstream")
                if discarded:
                    data["discarded_orderbook_tail_v1"] = discarded
                with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
                        temporary.replace(manifest)
                    finally: temporary.unlink(missing_ok=True)
                stats["records"] += count
            stats["outcome"] = "success"
    except Exception as error:
        record_failure(stats, error, job)
        raise
    finally:
        write_run_log(stats, root)

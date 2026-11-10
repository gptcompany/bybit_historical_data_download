"""Verified cold files: streaming containers, UTC grids, atomic per-series days."""
import csv
import fcntl
import gzip
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import zipfile
import zlib
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError

DAY = 86400000
NUMBER = {"type": "string", "pattern": r"^-?[0-9]+(?:\.[0-9]+)?$"}


def object_schema(properties, required=None):
    return {"type": "object", "properties": properties, "required": required or list(properties),
            "additionalProperties": False}


def bounds(job):
    start = int(datetime.fromisoformat(job["day"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
    return start, start + DAY


def positive(value, zero=False):
    number = Decimal(value)
    if not number.is_finite() or number < 0 or (not zero and number == 0):
        raise ValueError("Invalid numeric value")


def validate(path, job):
    try:
        return _validate(path, job)
    except (DecimalException, csv.Error, zlib.error) as error:
        raise ValueError("Invalid archive record or compressed stream") from error


def _validate(path, job):
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
                raise ValueError("No verified historical funding grid for this symbol")
            step = 28800000 if kind == "funding" else DAY
        Draft202012Validator({"type": "array", "items": schema}).validate(rows)
        times = [int(row[0] if kind == "klines" else row[
            "fundingRateTimestamp" if kind == "funding" else "timestamp"]) for row in rows]
        if sorted(times) != list(range(start, end, step)):
            raise ValueError("Incomplete or duplicate UTC grid")
        for row in rows:
            values = row[1:] if kind == "klines" else [v for k, v in row.items() if k not in {"symbol", "timestamp", "fundingRateTimestamp"}]
            for value in values:
                if kind != "funding": positive(value, zero=True)
            if kind == "longshortratio" and abs(Decimal(row["buyRatio"]) + Decimal(row["sellRatio"]) - 1) > Decimal("0.000001"):
                raise ValueError("Invalid account ratio sum")
            if kind == "klines":
                for value in row[1:5]: positive(value)
            if kind == "klines" and not (Decimal(row[3]) <= min(Decimal(row[1]), Decimal(row[4])) <= max(Decimal(row[1]), Decimal(row[4])) <= Decimal(row[2])):
                raise ValueError("Invalid candle range")
        return len(rows)
    # SQLite bounds memory for millions of trade IDs; this database is disposable.
    with tempfile.TemporaryDirectory(dir=path.parent) as scratch, sqlite3.connect(Path(scratch) / "ids") as ids:
        ids.execute("CREATE TABLE seen (id TEXT PRIMARY KEY)")
        minutes, previous, count = set(), start, 0
        def accept(timestamp, identity):
            nonlocal previous, count
            if not start <= timestamp < end or timestamp < previous:
                raise ValueError("Record outside ordered UTC day")
            try: ids.execute("INSERT INTO seen VALUES (?)", (identity,))
            except sqlite3.IntegrityError: raise ValueError("Duplicate record ID") from None
            minutes.add(int((timestamp - start) // 60000))
            previous, count = timestamp, count + 1
        if job["type"] == "trade":
            with gzip.open(path, "rt", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                fields = "timestamp symbol side size price tickDirection trdMatchID grossValue homeNotional foreignNotional".split()
                if reader.fieldnames != fields: raise ValueError("Unexpected trade schema")
                for row in reader:
                    if set(row) != set(fields) or any(value is None for value in row.values()): raise ValueError("Malformed CSV row")
                    if row["symbol"] != job["symbol"] or row["side"] not in {"Buy", "Sell"} or not row["trdMatchID"]:
                        raise ValueError("Invalid trade identity")
                    if row["tickDirection"] not in {"PlusTick", "ZeroPlusTick", "MinusTick", "ZeroMinusTick"}: raise ValueError("Invalid tick direction")
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
                if len(names) != 1 or not names[0].endswith(".data"): raise ValueError("Unexpected ZIP members")
                with archive.open(names[0]) as stream:
                    for line in io.TextIOWrapper(stream):
                        row = json.loads(line)
                        validator.validate(row)
                        if count == 0 and row["type"] != "snapshot": raise ValueError("Missing initial snapshot")
                        for price, size in row["data"]["b"] + row["data"]["a"]:
                            positive(price); positive(size, zero=True)
                        accept(row["ts"], f"{row['ts']}:{row['data']['u']}:{row['data']['seq']}")
        if minutes != set(range(1440)): raise ValueError("Incomplete archive UTC minute coverage")
        return count


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
        if result.get("symbol", job["symbol"]) != job["symbol"]: raise ValueError("API symbol mismatch")
        page = result["list"]
        rows.extend(page)
        cursor = result.get("nextPageCursor")
        if cursor:
            if cursor in cursors: raise ValueError("Repeated API cursor")
            cursors.add(cursor); params["cursor"] = cursor
        elif kind in {"klines", "funding"} and len(page) == params["limit"]:
            oldest = min(int(row[0] if kind == "klines" else row["fundingRateTimestamp"]) for row in page)
            key = "end" if kind == "klines" else "endTime"
            if oldest <= start: break
            if oldest > params[key]: raise ValueError("API pagination did not progress")
            params[key] = oldest - 1
        else: break
    return rows


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): result.update(chunk)
    return result.hexdigest()


def execute(jobs, root, client):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stats = dict(outcome="failure", downloaded=0, skipped=0, records=0, quarantined=[], files=len(jobs), timezone="UTC",
                 started_at=datetime.now(timezone.utc).isoformat(), days=sorted({job["day"] for job in jobs}))
    with (root / ".backfill.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for job in jobs:
                target = root / job["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                manifest = target.with_suffix(target.suffix + ".manifest.json")
                count = None
                if target.exists() or manifest.exists():
                    reason = "missing-or-inconsistent-manifest"
                    try:
                        saved = json.loads(manifest.read_text())
                        fields = {key: {"const": value} for key, value in job.items()}
                        fields.update(complete={"const": True}, records={"type": "integer", "minimum": 1},
                                      sha256={"type": "string", "pattern": "^[0-9a-f]{64}$"},
                                      integrity={"const": ("container-crc-and-schema" if job["source"] == "archive" else "json-schema-and-grid") + "; sha256-local-not-upstream"})
                        Draft202012Validator(object_schema(fields)).validate(saved)
                        reason = "sha256-mismatch"
                        if digest(target) != saved["sha256"]: raise ValueError("SHA256 mismatch")
                        reason = "invalid-cached-records"
                        if job["expected_bytes"] is not None and target.stat().st_size != job["expected_bytes"]: raise ValueError("Size mismatch")
                        count = validate(target, job)
                        if count != saved["records"]: raise ValueError("Record count mismatch")
                    except (ValueError, OSError, EOFError, zipfile.BadZipFile, ValidationError) as error:
                        count = None
                        suffix = ".quarantine." + uuid4().hex
                        for rejected in (target, manifest):
                            if rejected.exists(): rejected.rename(rejected.with_name(rejected.name + suffix))
                        stats["quarantined"].append(dict(path=job["path"], reason=reason, error=type(error).__name__))
                if count is None:
                    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
                        staging = Path(stream.name)
                        try:
                            if job["source"] == "archive":
                                with client.stream("GET", job["url"], headers={"Accept-Encoding": "identity"}) as response:
                                    response.raise_for_status()
                                    for chunk in response.iter_bytes(): stream.write(chunk)
                            else: stream.write(json.dumps(api_rows(client, job)).encode())
                            stream.flush(); os.fsync(stream.fileno())
                            if job["expected_bytes"] is not None and staging.stat().st_size != job["expected_bytes"]: raise ValueError("Archive size mismatch")
                            count = validate(staging, job)
                            staging.replace(target)
                        finally: staging.unlink(missing_ok=True)
                    stats["downloaded"] += 1
                else: stats["skipped"] += 1
                data = dict(job, complete=True, records=count, sha256=digest(target),
                            integrity=("container-crc-and-schema" if job["source"] == "archive" else "json-schema-and-grid") + "; sha256-local-not-upstream")
                with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
                        temporary.replace(manifest)
                    finally: temporary.unlink(missing_ok=True)
                stats["records"] += count
            stats["outcome"] = "success"
        finally:
            stats["finished_at"] = datetime.now(timezone.utc).isoformat()
            (root / "logs").mkdir(exist_ok=True)
            with (root / "logs/backfill.jsonl").open("a") as stream:
                stream.write(json.dumps(stats) + "\n"); stream.flush(); os.fsync(stream.fileno())

import csv
import gzip
import io
import hashlib
import json
import zipfile
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone

import httpx
import pytest

from bybit_data_downloader.backfill_execute import api_rows, execute, validate


START = int(datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp() * 1000)


def archive(tmp_path, kind="trade"):
    job = dict(day="2026-11-09", symbol="BTCUSDT", type=kind, interval=None,
               source="archive", path="historical/day.gz", url="https://example.test/day")
    path = tmp_path / "fixture"
    if kind == "trade":
        rows = ["timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional"]
        rows += [f"{(START + i * 60000) / 1000},BTCUSDT,Buy,1,2,PlusTick,{i},2,1,2" for i in range(1440)]
        path.write_bytes(gzip.compress(("\n".join(rows) + "\n").encode()))
    else:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("day.data", "\n".join(json.dumps(dict(type="snapshot", ts=START + i * 60000,
                data=dict(s="BTCUSDT", b=[["1", "1"]], a=[["2", "1"]], u=i, seq=i))) for i in range(1440)))
    job["expected_bytes"] = path.stat().st_size
    return job, path


@pytest.mark.parametrize("kind", ["trade", "orderbook"])
def test_container_validation_and_corruption(tmp_path, kind):
    job, path = archive(tmp_path, kind)
    assert validate(path, job) == 1440
    path.write_bytes(path.read_bytes()[:-8])
    with pytest.raises((ValueError, EOFError, OSError, zipfile.BadZipFile)):
        validate(path, job)


@pytest.mark.parametrize(("day", "change", "error"), [
    ("2025-04-02", None, None),
    ("2025-04-03", None, None),
    ("2025-04-03", "invalid-value", "Invalid trade RPI"),
    ("2025-04-03", "missing-value", "Malformed CSV row"),
    ("2025-04-03", "renamed-header", "Unexpected trade schema"),
    ("2025-04-03", "reordered-header", "Unexpected trade schema"),
    ("2025-04-03", "extra-header", "Unexpected trade schema"),
])
def test_versioned_trade_headers(tmp_path, day, change, error):
    fixture = Path(__file__).parent / "fixtures" / f"btc-trades-{day}.csv"
    with fixture.open(newline="") as stream:
        fields, sample = csv.reader(stream)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if change == "renamed-header":
        fields[-1] = "rpi"
    elif change == "reordered-header":
        fields[-2:] = reversed(fields[-2:])
    elif change == "extra-header":
        fields.append("extra")
    writer.writerow(fields)
    writer.writerow(sample)
    for minute in range(1, 1440):
        row = sample.copy()
        row[0] = str(Decimal(sample[0]) + 60 * minute)
        row[6] = str(minute)
        if day == "2025-04-03":
            row[-1] = str(minute % 2)
        if minute == 1439 and change == "invalid-value":
            row[-1] = "2"
        if minute == 1439 and change == "missing-value":
            row.pop()
        writer.writerow(row)
    path = tmp_path / "trade.csv.gz"
    path.write_bytes(gzip.compress(output.getvalue().encode()))
    job = dict(day=day, symbol="BTCUSDT", type="trade", source="archive")
    if error:
        with pytest.raises(ValueError, match=error):
            validate(path, job)
    else:
        assert validate(path, job) == 1440


@pytest.mark.parametrize("defect", ["day", "symbol", "duplicate", "gap", "number", "price-text", "timestamp-text"])
def test_trade_counterexamples(tmp_path, defect):
    job, path = archive(tmp_path)
    rows = gzip.decompress(path.read_bytes()).decode().splitlines()
    if defect == "day": rows[-1] = rows[-1].replace(str((START + 1439 * 60000) / 1000), str((START + 86400000) / 1000))
    if defect == "symbol": rows[-1] = rows[-1].replace("BTCUSDT", "ETHUSDT")
    if defect == "duplicate": rows[-1] = rows[-1].replace(",1439,", ",0,")
    if defect == "gap": rows.pop(50)
    if defect == "number": rows[-1] = rows[-1].replace(",Buy,1,2,", ",Buy,NaN,2,")
    if defect == "price-text": rows[-1] = rows[-1].replace(",Buy,1,2,", ",Buy,1,x,")
    if defect == "timestamp-text": rows[-1] = "x" + rows[-1][1:]
    path.write_bytes(gzip.compress(("\n".join(rows) + "\n").encode()))
    with pytest.raises(ValueError): validate(path, job)


def test_atomic_idempotent_manifest_and_run_log(tmp_path):
    job, path = archive(tmp_path)
    calls = []
    def respond(request):
        calls.append(request.method)
        return httpx.Response(200, content=path.read_bytes())
    root = tmp_path / "cold"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        execute([job], root, client)
        execute([job], root, client)
    assert calls == ["GET"]
    target = root / job["path"]
    manifest = json.loads(target.with_suffix(target.suffix + ".manifest.json").read_text())
    assert manifest["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert manifest["integrity"] == "container-crc-and-schema; sha256-local-not-upstream"
    assert manifest["records"] == 1440 and manifest["complete"] is True
    logs = [json.loads(line) for line in (root / "logs/backfill.jsonl").read_text().splitlines()]
    assert [log["downloaded"] for log in logs] == [1, 0]
    assert logs[-1]["skipped"] == 1 and logs[-1]["outcome"] == "success"
    target.write_bytes(b"corrupt")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        execute([job], root, client)
    assert calls == ["GET", "GET"]


def test_failed_day_is_never_published(tmp_path):
    job, _ = archive(tmp_path)
    root = tmp_path / "cold"
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"bad"))) as client:
        with pytest.raises(Exception): execute([job], root, client)
    assert not (root / job["path"]).exists()
    assert not list(root.rglob("*.manifest.json"))
    assert json.loads((root / "logs/backfill.jsonl").read_text())["outcome"] == "failure"


@pytest.mark.parametrize("kind", ["klines", "funding", "openinterest", "longshortratio"])
def test_api_grids_and_pagination(tmp_path, kind):
    job = dict(day="2026-11-09", symbol="BTCUSDT", type=kind, interval="1m",
               source="api", path="api/day.json", url="https://example.test/api", expected_bytes=None)
    if kind == "klines": rows = [[str(START + i * 60000), "2", "3", "1", "2", "0", "0"] for i in range(1440)]
    elif kind == "funding": rows = [dict(symbol="BTCUSDT", fundingRate="-0.001", fundingRateTimestamp=str(START + i * 28800000)) for i in range(3)]
    elif kind == "openinterest": rows = [dict(openInterest="1", timestamp=str(START))]
    else: rows = [dict(symbol="BTCUSDT", buyRatio="0.4", sellRatio="0.6", timestamp=str(START))]
    calls = []
    def respond(request):
        calls.append(request.url.params)
        page = [row for row in rows if int(row[0]) <= int(request.url.params["end"])][-1000:] if kind == "klines" else rows
        return httpx.Response(200, json=dict(retCode=0, result=dict(symbol="BTCUSDT", list=list(reversed(page)))))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        received = api_rows(client, job)
    path = tmp_path / "api.json"
    path.write_text(json.dumps(received))
    assert validate(path, job) == len(rows)
    assert len(calls) == (2 if kind == "klines" else 1)
    for bad in [received + received[:1], [], received[:-1]]:
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError): validate(path, job)


@pytest.mark.parametrize("defect", ["valid-alteration", "klines-shape", "oi-shape", "missing-manifest", "invalid-manifest"])
def test_untrusted_cache_is_quarantined_and_recovered(tmp_path, defect):
    kind = "openinterest" if defect == "oi-shape" else "klines"
    rows = ([dict(openInterest="1", timestamp=str(START))] if kind == "openinterest" else
            [[str(START + i * 60000), "2", "3", "1", "2", "0", "0"] for i in range(1440)])
    job = dict(day="2026-11-09", symbol="BTCUSDT", type=kind, interval="1m", source="api",
               path="api/day.json", url="https://example.test/api", expected_bytes=None)
    calls = []
    def respond(request):
        calls.append(request)
        page = [r for r in rows if int(r[0]) <= int(request.url.params["end"])][-1000:] if kind == "klines" else rows
        return httpx.Response(200, json=dict(retCode=0, result=dict(symbol="BTCUSDT", list=list(reversed(page)))))
    root = tmp_path / "cold"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        execute([job], root, client)
        target = root / job["path"]
        manifest = target.with_suffix(".json.manifest.json")
        original = target.read_bytes()
        if defect == "valid-alteration": target.write_bytes(original.replace(b'"0"', b'"1"', 1))
        if defect in {"klines-shape", "oi-shape"}:
            target.write_text('[[]]' if kind == "klines" else '[{"openInterest":"1"}]')
            data = json.loads(manifest.read_text())
            data["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(data))
        if defect == "missing-manifest": manifest.unlink()
        if defect == "invalid-manifest": manifest.write_text('[]')
        rejected = target.read_bytes()
        before = len(calls)
        execute([job], root, client)
    assert len(calls) > before and target.read_bytes() == original
    assert any(p.read_bytes() == rejected for p in target.parent.glob("day.json.quarantine.*"))
    logs = [json.loads(line) for line in (root / "logs/backfill.jsonl").read_text().splitlines()]
    assert logs[-1]["skipped"] == 0 and logs[-1]["downloaded"] == 1
    assert logs[-1]["quarantined"][0]["reason"]


@pytest.mark.parametrize("field", ["price", "timestamp", "csv", "deflate"])
def test_parse_failure_quarantines_coherent_archive_cache(tmp_path, field):
    job, fixture = archive(tmp_path)
    original = fixture.read_bytes()
    rows = gzip.decompress(original).decode().splitlines()
    malformed = None
    for index in range(1, len(rows)):
        changed = rows.copy()
        changed[index] = (changed[index].replace(",Buy,1,2,", ",Buy,1,x,") if field == "price"
                          else "x" + changed[index][1:])
        if field == "csv": changed[index] = '"' + rows[index][1:]
        candidate = gzip.compress(("\n".join(changed) + "\n").encode(), mtime=0)
        if field == "deflate": candidate = original[:10] + b"\x07" + original[11:]
        if len(candidate) == len(original):
            malformed = candidate
            break
    assert malformed is not None, "Fixture must reach parsing with matching archive size"
    calls = []
    def respond(request):
        calls.append(request.method)
        return httpx.Response(200, content=original)
    root = tmp_path / "cold"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        execute([job], root, client)
        target = root / job["path"]
        manifest = target.with_suffix(target.suffix + ".manifest.json")
        target.write_bytes(malformed)
        saved = json.loads(manifest.read_text())
        saved["sha256"] = hashlib.sha256(malformed).hexdigest()
        manifest.write_text(json.dumps(saved))
        rejected_manifest = manifest.read_bytes()
        execute([job], root, client)
    assert calls == ["GET", "GET"] and target.read_bytes() == original
    assert any(p.read_bytes() == malformed for p in target.parent.glob("day.gz.quarantine.*"))
    assert any(p.read_bytes() == rejected_manifest for p in target.parent.glob("*.manifest.json.quarantine.*"))
    log = json.loads((root / "logs/backfill.jsonl").read_text().splitlines()[-1])
    assert (log["outcome"], log["downloaded"], log["skipped"], log["records"]) == ("success", 1, 0, 1440)
    assert log["quarantined"][0]["reason"] == "invalid-cached-records"
    assert log["quarantined"][0]["error"] == "ValueError"


@pytest.mark.parametrize(("defect", "separator"), [
    (None, "\n"), (None, "\r\n"), (None, "\r"), (None, "mixed"),
    ("early", "\n"), ("nonterminal", "\n"), ("late", "\n"), ("missing-minute", "\n"),
])
def test_orderbook_midnight_tail(tmp_path, defect, separator):
    fixture = Path(__file__).parent / "fixtures/btc-ob200-2026-06-29.jsonl"
    first, last, *tail = map(json.loads, fixture.read_text().splitlines())
    start = 1782691200000
    rows = [first] + [dict(first, ts=start + minute * 60000) for minute in range(1, 1439)]
    if defect != "missing-minute":
        rows.append(last)
    if defect == "early":
        first["ts"] = start - 1
    if defect == "late":
        tail[-1]["ts"] = start + 86400000 + 60001
    if defect == "nonterminal":
        rows.insert(-1, tail.pop(0))
    path = tmp_path / "fixture.zip"
    member = "2026-06-29_BTCUSDT_ob200.data"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr(member, "".join(
            json.dumps(row) + ("\r" if index == len(rows) - 1 else "\n")
            if separator == "mixed" else json.dumps(row) + separator
            for index, row in enumerate(rows + tail)))
    job = dict(day="2026-06-29", symbol="BTCUSDT", type="orderbook", source="archive",
               path="historical/orderbook/day.zip", url="https://example.test/day",
               expected_bytes=path.stat().st_size)
    calls = []

    def respond(request):
        calls.append(request.method)
        return httpx.Response(200, content=path.read_bytes())

    root = tmp_path / "cold"
    target = root / job["path"]
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if defect:
            reason = "Incomplete archive UTC minute coverage" if defect == "missing-minute" else "Record outside ordered UTC day"
            with pytest.raises(ValueError, match=reason):
                execute([job], root, client)
            assert not target.exists()
            return
        execute([job], root, client)
        execute([job], root, client)
    assert calls == ["GET"]
    with zipfile.ZipFile(target) as stream:
        assert list(map(json.loads, stream.read(member).splitlines())) == rows
    assert validate(target, job) == 1440
    logs = [json.loads(line) for line in (root / "logs/backfill.jsonl").read_text().splitlines()]
    assert [log["discarded_orderbook_tail"] for log in logs] == [8, 0]
    assert [log["records"] for log in logs] == [1440, 1440]
    assert logs[1]["skipped"] == 1


@pytest.mark.parametrize("failure", ["invalid-records", "count-mismatch"])
def test_orderbook_rewrite_validated_before_publication(tmp_path, monkeypatch, failure):
    from bybit_data_downloader import backfill_execute as module

    job, path = archive(tmp_path, "orderbook")
    with zipfile.ZipFile(path) as stream:
        records = stream.read("day.data")
    tail = dict(type="delta", ts=START + 86400000, data=dict(
        s="BTCUSDT", b=[], a=[], u=1440, seq=1440))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr("day.data", records + b"\n" + json.dumps(tail).encode())
    job["expected_bytes"] = path.stat().st_size
    checked = []

    def reject_rewrite(candidate, candidate_job):
        checked.append(candidate)
        assert candidate_job == job
        assert not (root / job["path"]).exists()
        assert validate(candidate, candidate_job) == 1440
        if failure == "invalid-records":
            raise module.BackfillDataError("Rejected rewritten archive")
        return 1439

    monkeypatch.setattr(module, "validate", reject_rewrite)
    root = tmp_path / "cold"
    reason = "Rejected rewritten archive" if failure == "invalid-records" else "Record count mismatch"
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=path.read_bytes()))) as client:
        with pytest.raises(ValueError, match=reason):
            execute([job], root, client)
    assert len(checked) == 1
    assert not checked[0].exists()
    assert not (root / job["path"]).exists()
    assert not list(root.rglob("*.manifest.json"))
    assert not list(root.rglob("*.part"))


@pytest.mark.parametrize("defect", [None, "late", "nonterminal", "early"])
def test_orderbook_structural_eth_tail(tmp_path, defect):
    # Synthetic minute grid plus the eleven observed ETH tail offsets; no real archive.
    job, path = archive(tmp_path, "orderbook")
    with zipfile.ZipFile(path) as stream:
        rows = list(map(json.loads, stream.read("day.data").splitlines()))
    offsets = [50, 150, 250, 350, 450, 550, 650, 750, 850, 950, 1051]
    tail = [dict(rows[-1], ts=START + 86400000 + offset,
                 data=dict(rows[-1]["data"], u=1440 + i, seq=1440 + i))
            for i, offset in enumerate(offsets)]
    if defect == "late":
        tail[-1]["ts"] = START + 86400000 + 60001
    if defect == "nonterminal":
        rows.append(tail.pop(0))
    if defect == "early":
        rows[0]["ts"] = START - 1
    if defect == "nonterminal":
        rows.append(dict(rows[0], ts=START + 86399999))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr("day.data", "\n".join(map(json.dumps, rows + tail)))
    job["expected_bytes"] = path.stat().st_size
    root = tmp_path / "cold"
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=path.read_bytes()))) as client:
        if defect:
            with pytest.raises(ValueError, match="Record outside ordered UTC day") as error:
                execute([job], root, client)
            expected = {
                "late": (1451, 11, 60001, 1441),
                "nonterminal": (1442, 1, 50, 1441),
                "early": (1, 0, 0, None),
            }[defect]
            position, tail_rows, maximum, first_tail = expected
            for field in (f"position={position}", f"rows_seen={position}",
                          f"tail_rows={tail_rows}", f"max_offset_ms={maximum}",
                          f"tail_start={first_tail}", "limit_ms=60000"):
                assert field in str(error.value)
            assert not (root / job["path"]).exists()
            assert not list(root.rglob("*.manifest.json"))
            assert not list(root.rglob("*.part"))
            return
        execute([job], root, client)
    assert validate(root / job["path"], job) == 1440
    log = json.loads((root / "logs/backfill.jsonl").read_text())
    assert log["discarded_orderbook_tail"] == 11
    manifest = json.loads((root / job["path"]).with_suffix(".gz.manifest.json").read_text())
    assert manifest["discarded_orderbook_tail_v1"] == 11


@pytest.mark.parametrize("limit,offsets,accepted", [
    (1050, [50, 1051], False), (1051, [50, 1051], True),
    (60000, [50, 60000], True), (60000, [50, 60001], False),
    (60000, [1051, 50], False),
])
def test_orderbook_configured_tail_limit(tmp_path, limit, offsets, accepted):
    from bybit_data_downloader.backfill_execute import scan

    job, path = archive(tmp_path, "orderbook")
    with zipfile.ZipFile(path) as stream:
        records = stream.read("day.data")
    tail = [dict(type="delta", ts=START + 86400000 + offset,
                 data=dict(s="BTCUSDT", b=[], a=[], u=1440 + i, seq=1440 + i))
            for i, offset in enumerate(offsets)]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr("day.data", records + b"\n" + "\n".join(map(json.dumps, tail)).encode())
    if accepted:
        assert scan(path, job, allow_orderbook_tail=True, orderbook_tail_max_ms=limit) == (1440, 2)
        # A published/cached file must remain strictly within the requested day.
        with pytest.raises(ValueError, match="Record outside ordered UTC day"):
            validate(path, job)
    else:
        with pytest.raises(ValueError, match="Record outside ordered UTC day"):
            scan(path, job, allow_orderbook_tail=True, orderbook_tail_max_ms=limit)

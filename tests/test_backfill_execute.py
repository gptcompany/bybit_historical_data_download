import gzip
import hashlib
import json
import zipfile
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


@pytest.mark.parametrize("defect", ["day", "symbol", "duplicate", "gap", "number"])
def test_trade_counterexamples(tmp_path, defect):
    job, path = archive(tmp_path)
    rows = gzip.decompress(path.read_bytes()).decode().splitlines()
    if defect == "day": rows[-1] = rows[-1].replace(str((START + 1439 * 60000) / 1000), str((START + 86400000) / 1000))
    if defect == "symbol": rows[-1] = rows[-1].replace("BTCUSDT", "ETHUSDT")
    if defect == "duplicate": rows[-1] = rows[-1].replace(",1439,", ",0,")
    if defect == "gap": rows.pop(50)
    if defect == "number": rows[-1] = rows[-1].replace(",Buy,1,2,", ",Buy,NaN,2,")
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

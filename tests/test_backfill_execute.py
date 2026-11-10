import gzip
import hashlib
import json
import zipfile
from datetime import datetime, timezone

import httpx
import pytest

from bybit_data_downloader.backfill_execute import execute, validate


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

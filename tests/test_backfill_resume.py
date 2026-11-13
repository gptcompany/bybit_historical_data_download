"""Timer resume: each series restarts after its verified manifests in a fake cold, offline."""
import gzip
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from bybit_data_downloader import backfill
from bybit_data_downloader.backfill import first_incomplete, job_for

END = datetime.now(timezone.utc).date() - timedelta(days=1)
TRADE = [("BTCUSDT", "trade", None)]


def trade_day(day):
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    rows = ["timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional"]
    rows += [f"{(start + i * 60000) / 1000},BTCUSDT,Buy,1,2,PlusTick,{i},2,1,2" for i in range(1440)]
    return gzip.compress(("\n".join(rows) + "\n").encode())


@pytest.fixture
def cold(tmp_path, monkeypatch, capsys):
    bodies = {job_for(END - timedelta(days=n), "BTCUSDT", "trade", None)["url"]: trade_day(END - timedelta(days=n))
              for n in range(6)}
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"Content-Length": str(len(bodies[str(request.url)]))}, content=bodies[str(request.url)]))
    client = httpx.Client
    # Each backfill run closes its client; give every run a fresh offline one.
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=transport))
    root = tmp_path / "cold"

    def run(*first):
        backfill.main([*first, "--end-date", (END if first[0] == "--from-last-complete" else END - timedelta(days=2))
                       .isoformat(), "--symbols", "BTCUSDT", "--types", "trade", "--data-root", str(root)])
        return json.loads(capsys.readouterr().out.splitlines()[-1])

    run("--start-date", (END - timedelta(days=3)).isoformat())  # Today is D; last complete day D-3.
    return root, run


def manifest(root, day):
    target = root / job_for(day, "BTCUSDT", "trade", None)["path"]
    return target.with_suffix(target.suffix + ".manifest.json")


def test_resume_covers_days_after_last_complete_then_is_idempotent(cold):
    root, run = cold
    assert first_incomplete(root, END, TRADE) == END - timedelta(days=1)
    first = run("--from-last-complete")
    assert first["days"] == [(END - timedelta(days=n)).isoformat() for n in (1, 0)]
    assert (first["outcome"], first["downloaded"], first["skipped"]) == ("success", 2, 0)
    second = run("--from-last-complete")
    assert (second["outcome"], second["downloaded"], second["skipped"]) == ("success", 0, 1)
    assert second["days"] == [END.isoformat()]  # Cold up to yesterday: re-verified and skipped only.


@pytest.mark.parametrize("hole", ["missing", "quarantined", "unverifiable", "file-missing"])
def test_hole_in_the_middle_is_detected_and_recovered(cold, hole):
    root, run = cold
    run("--from-last-complete")
    gap = END - timedelta(days=1)  # Complete days on both sides.
    path = manifest(root, gap)
    if hole == "missing":
        path.unlink()
    elif hole == "quarantined":
        path.rename(path.with_name(path.name + ".quarantine.0"))
    elif hole == "unverifiable":
        path.write_text(json.dumps(dict(json.loads(path.read_text()), complete=False)))
    else:
        (root / job_for(gap, "BTCUSDT", "trade", None)["path"]).unlink()
    assert first_incomplete(root, END, TRADE) == gap
    recovered = run("--from-last-complete")
    assert recovered["outcome"] == "success" and recovered["days"][0] == gap.isoformat()
    assert first_incomplete(root, END, TRADE) == END


def test_series_without_complete_days_is_limited_to_end(tmp_path):
    assert first_incomplete(tmp_path / "empty", END, TRADE + [("ETHUSDT", "klines", "1m")]) == END


def test_earliest_series_gap_sets_the_shared_start(cold):
    root, _ = cold
    # ETHUSDT has no manifests (limited to END); BTCUSDT resumes after D-3.
    assert first_incomplete(root, END, TRADE + [("ETHUSDT", "trade", None)]) == END - timedelta(days=1)


def test_start_date_and_resume_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        backfill.main(["--start-date", END.isoformat(), "--from-last-complete", "--end-date", END.isoformat(),
                       "--data-root", "/unused"])

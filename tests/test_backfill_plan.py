"""Offline acceptance fixtures: planning must never fetch archive bodies."""
import json
from datetime import date

import httpx
import pytest

from bybit_data_downloader.backfill import main, plan


def test_two_days_all_series_and_sizes():
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"Content-Length": "123"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        jobs = plan(date(2026, 6, 29), date(2026, 6, 30),
                    ["BTCUSDT", "ETHUSDT"],
                    ["trade", "orderbook", "klines", "funding", "openinterest", "longshortratio"],
                    ["1m", "5m", "15m"], client)
    assert len(jobs) == 32
    assert len(calls) == 8
    assert sum(j["expected_bytes"] or 0 for j in jobs) == 984
    assert all(j["timezone"] == "UTC" for j in jobs)
    assert len({j["path"] for j in jobs}) == 32
    assert any(j["url"].endswith("2026-06-29_BTCUSDT_ob200.data.zip") for j in jobs)
    assert any(j["path"] == "historical/trade/contract/BTCUSDT/BTCUSDT2026-06-29.csv.gz" for j in jobs)
    assert all(j["expected_bytes"] is None for j in jobs if j["source"] == "api")


@pytest.mark.parametrize("headers,status", [({}, 200), ({"Content-Length": "-1"}, 200),
                                           ({"Content-Length": "100"}, 404)])
def test_unavailable_archive_never_has_invented_size(headers, status):
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, headers=headers))) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            plan(date(2026, 6, 29), date(2026, 6, 29), ["BTCUSDT"], ["trade"], ["1m"], client)


@pytest.mark.parametrize("start,end,symbols,types,intervals", [
    (date(2026, 7, 1), date(2026, 6, 29), ["BTCUSDT"], ["trade"], ["1m"]),
    (date(2026, 6, 29), date(2026, 6, 29), ["../BTC"], ["trade"], ["1m"]),
    (date(2026, 6, 29), date(2026, 6, 29), ["BTCUSDT"], ["unknown"], ["1m"]),
    (date(2026, 6, 29), date(2026, 6, 29), ["BTCUSDT"], ["klines"], ["2m"]),
])
def test_reject_invalid_plan_before_network(start, end, symbols, types, intervals):
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("network"))) as client:
        with pytest.raises(ValueError):
            plan(start, end, symbols, types, intervals, client)


def test_dry_run_prints_plan_without_creating_data(tmp_path, capsys):
    root = tmp_path / "must-not-exist"
    main(["--start-date", "2026-06-29", "--end-date", "2026-06-30",
          "--symbols", "BTCUSDT", "--types", "klines", "--intervals", "5m",
          "--data-root", str(root), "--dry-run"])
    result = json.loads(capsys.readouterr().out)
    assert result["days"] == 2
    assert result["files"] == 2
    assert result["api_files_unknown_bytes"] == 2
    assert not root.exists()

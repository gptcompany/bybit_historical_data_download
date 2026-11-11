"""Offline transport regressions for planning and atomic cold downloads."""
import json
from datetime import date

import httpx
import pytest

from bybit_data_downloader import backfill
from bybit_data_downloader.backfill_execute import execute
from test_backfill_execute import archive


@pytest.mark.parametrize("phase", ["planning", "execution"])
def test_404_is_immediate(phase, tmp_path, capsys):
    job, _ = archive(tmp_path)
    calls = []
    def respond(request):
        calls.append(request.method)
        return httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            if phase == "planning":
                backfill.plan(date(2026, 11, 9), date(2026, 11, 9), ["BTCUSDT"], ["trade"], ["1m"], client)
            else:
                execute([job], tmp_path, client)
    assert calls == (["HEAD"] if phase == "planning" else ["GET"])
    assert not (tmp_path / job["path"]).exists()
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("phase", ["planning", "execution"])
@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, 429, 503])
@pytest.mark.parametrize("persistent", [False, True])
def test_transient_budget(phase, failure, persistent, tmp_path, monkeypatch, capsys):
    job, fixture = archive(tmp_path)
    payload = fixture.read_bytes()
    calls, waits = [], []
    monkeypatch.setattr("time.sleep", waits.append)
    monkeypatch.setattr("random.uniform", lambda low, high: high)
    def respond(request):
        calls.append(request.method)
        if persistent or len(calls) == 1:
            if isinstance(failure, int):
                return httpx.Response(failure, headers={"Retry-After": "7"} if failure == 429 else {})
            raise failure("untrusted upstream text", request=request)
        return httpx.Response(200, headers={"Content-Length": str(len(payload))}, content=payload)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(backfill.httpx, "Client", lambda **kwargs: client)
    args = ["--start-date", job["day"], "--end-date", job["day"], "--symbols", "BTCUSDT",
            "--types", "trade", "--data-root", str(tmp_path)]
    def run():
        if phase == "planning":
            backfill.main(args + ["--dry-run"])
        else:
            execute([job], tmp_path, client)
    if persistent:
        with pytest.raises(httpx.HTTPError): run()
        captured = capsys.readouterr()
        summary = json.loads(captured.out)
        assert summary["outcome"] == "failure" and summary["error_target"]
        assert summary["downloaded"] == summary["skipped"] == 0
        assert len(calls) == 3
        assert not list(tmp_path.rglob("*.manifest.json"))
    else:
        run()
        captured = capsys.readouterr()
        assert len(calls) == 2
        if phase == "execution":
            assert (tmp_path / job["path"]).read_bytes() == payload
    assert len(waits) == (2 if persistent else 1)
    if failure == 429: assert all(wait >= 7 for wait in waits)
    records = [json.loads(line) for line in captured.err.splitlines()]
    assert len(records) == len(waits)
    assert all(r["event"] == "retry" and r["target"] and r["exception"] for r in records)
    assert [r["attempt"] for r in records] == list(range(1, len(waits) + 1))
    assert [r["wait_seconds"] for r in records] == waits
    assert "untrusted upstream text" not in json.dumps(records)
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("persistent", [False, True])
def test_partial_stream_restarts_clean(persistent, tmp_path, monkeypatch):
    job, fixture = archive(tmp_path)
    payload, calls = fixture.read_bytes(), []
    monkeypatch.setattr("time.sleep", lambda delay: None)
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.RemoteProtocolError("disconnected")
    def respond(request):
        calls.append(request.method)
        assert not (tmp_path / job["path"]).exists()
        assert not list(tmp_path.rglob("*.manifest.json"))
        return httpx.Response(200, stream=Broken()) if persistent or len(calls) == 1 else httpx.Response(200, content=payload)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if persistent:
            with pytest.raises(httpx.RemoteProtocolError): execute([job], tmp_path, client)
        else:
            execute([job], tmp_path, client)
            assert (tmp_path / job["path"]).read_bytes() == payload
    assert len(calls) == (3 if persistent else 2)
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("header,minimum", [("Wed, 11 Nov 2026 00:00:07 GMT", 7), ("invalid", 0), ("inf", 0)])
def test_retry_after_date_and_invalid_header(header, minimum, monkeypatch):
    from bybit_data_downloader.backfill_retry import RetryPolicy
    waits, calls = [], []
    monkeypatch.setattr("time.time", lambda: 1794355200)
    monkeypatch.setattr("time.sleep", waits.append)
    monkeypatch.setattr("random.uniform", lambda low, high: low)
    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header}) if len(calls) == 1 else httpx.Response(200)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        RetryPolicy().run(lambda: client.get("https://example.test/list").raise_for_status(), "list")
    assert waits == [minimum]


def test_configurable_budget_and_capped_jitter(monkeypatch):
    from bybit_data_downloader.backfill_retry import RetryPolicy
    waits, ceilings = [], []
    monkeypatch.setattr("time.sleep", waits.append)
    def jitter(low, high):
        assert low == 0
        ceilings.append(high)
        return high / 2
    monkeypatch.setattr("random.uniform", jitter)
    def fail(): raise httpx.ReadTimeout("timeout")
    with pytest.raises(httpx.ReadTimeout): RetryPolicy(5, 2, 3).run(fail, "target")
    assert ceilings == [2, 3, 3, 3] and waits == [1, 1.5, 1.5, 1.5]
    for values in [(0, 1, 30), (3, -1, 30), (3, 1, float("inf"))]:
        with pytest.raises(ValueError): RetryPolicy(*values)


def test_api_list_restarts_without_duplicate_rows(tmp_path, monkeypatch):
    from test_backfill_execute import START
    waits, calls = [], []
    monkeypatch.setattr("time.sleep", waits.append)
    job = dict(day="2026-11-09", symbol="BTCUSDT", type="funding", source="api",
               path="funding/day.json", url="https://example.test/list", expected_bytes=None)
    rows = [dict(symbol="BTCUSDT", fundingRate="0.001", fundingRateTimestamp=str(START + i * 28800000)) for i in range(3)]
    def respond(request):
        calls.append(request)
        if len(calls) == 2: raise httpx.ConnectError("interrupted page")
        page = [rows[0]] if "cursor" not in request.url.params else rows[1:]
        result = dict(list=page)
        if len(page) == 1: result["nextPageCursor"] = "next"
        return httpx.Response(200, json=dict(retCode=0, result=result))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        execute([job], tmp_path, client)
    assert json.loads((tmp_path / job["path"]).read_text()) == rows
    assert len(calls) == 4 and len(waits) == 1

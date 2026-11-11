"""Run failures before download must remain observable without archive access."""
import errno
import fcntl
import json
import runpy
import sys
import zipfile

import httpx
import pytest

from bybit_data_downloader import backfill
from bybit_data_downloader.backfill_execute import execute


def failure_record(capsys):
    record = json.loads(capsys.readouterr().out)
    assert record["outcome"] == "failure"
    assert record["timezone"] == "UTC"
    assert all(record[field] == 0 for field in ("downloaded", "skipped", "records"))
    assert record["finished_at"] >= record["started_at"]
    return record


def test_planning_failure_logs_counts_without_get(tmp_path, monkeypatch, capsys):
    calls = []
    def respond(request):
        calls.append(request.method)
        return httpx.Response(404)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(backfill.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(httpx.HTTPStatusError):
        backfill.main(["--start-date", "2026-11-09", "--end-date", "2026-11-09",
                       "--symbols", "BTCUSDT", "--types", "trade", "--data-root", str(tmp_path)])
    record = failure_record(capsys)
    assert record["phase"] == "planning" and record["error"] == "HTTPStatusError"
    assert record["error_message"] == "HTTP status 404"
    assert (record["error_type"], record["error_day"], record["error_symbol"], record["error_target"]) == (
        "trade", "2026-11-09", "BTCUSDT", "historical/trade/contract/BTCUSDT/BTCUSDT2026-11-09.csv.gz",
    )
    assert calls == ["HEAD"]
    assert json.loads((tmp_path / "logs/backfill.jsonl").read_text()) == record


def test_busy_lock_logs_failure(tmp_path, capsys):
    with (tmp_path / ".backfill.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP"))) as client:
            with pytest.raises(BlockingIOError): execute([], tmp_path, client)
    record = failure_record(capsys)
    assert record["error"] == "BlockingIOError"
    assert "temporarily unavailable" in record["error_message"].lower()
    assert all(record[key] is None for key in ("error_type", "error_day", "error_symbol", "error_target"))
    assert json.loads((tmp_path / "logs/backfill.jsonl").read_text()) == record


def test_unwritable_root_still_reports_to_journal(tmp_path, capsys):
    root = tmp_path / "file"
    root.write_text("untouched")
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP"))) as client:
        with pytest.raises(OSError): execute([], root, client)
    failure_record(capsys)
    assert root.read_text() == "untouched"


def test_success_counts_are_available_to_journal(tmp_path, capsys):
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP"))) as client:
        execute([], tmp_path, client)
    record = json.loads(capsys.readouterr().out)
    assert record["outcome"] == "success" and record["files"] == 0
    assert json.loads((tmp_path / "logs/backfill.jsonl").read_text()) == record


@pytest.mark.parametrize("scenario", ["head404", "lock", "validation", "root"])
def test_module_emits_one_complete_failure(scenario, tmp_path, monkeypatch, capsys):
    """Exercise the documented -m entry point, including its exception handler."""
    def respond(request):
        if scenario == "head404":
            return httpx.Response(404)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Length": "3"})
        return httpx.Response(200, content=b"bad")
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    root = tmp_path / "cold"
    root.mkdir()
    if scenario == "root":
        blocker = tmp_path / "file"
        blocker.write_text("untouched")
        root = blocker / "absent"
    kind = "trade" if scenario in ("head404", "validation") else "klines"
    monkeypatch.setattr(sys, "argv", ["backfill", "--start-date", "2026-11-09",
                        "--end-date", "2026-11-09", "--symbols", "BTCUSDT",
                        "--types", kind, "--data-root", str(root)])
    with (tmp_path / "cold/.backfill.lock").open("a") as lock:
        if scenario == "lock":
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as stopped:
            runpy.run_module("bybit_data_downloader.backfill", run_name="__main__")
    assert stopped.value.code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    lines = captured.out.splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["outcome"] == "failure" and record["timezone"] == "UTC"
    assert all(record[field] == 0 for field in ("downloaded", "skipped", "records"))
    assert record["finished_at"] >= record["started_at"]
    assert record["phase"] == ("planning" if scenario == "head404" else "execution")
    if scenario != "root":
        assert json.loads((root / "logs/backfill.jsonl").read_text()) == record
    else:
        assert not root.exists() and blocker.read_text() == "untouched"


@pytest.mark.parametrize("scenario", ["head404", "reversed"])
def test_dry_run_failure_reports_reason_without_writes(scenario, tmp_path, monkeypatch, capsys):
    calls = []
    def respond(request):
        calls.append(request.method)
        return httpx.Response(404)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    root = tmp_path / "absent"
    monkeypatch.setattr(sys, "argv", ["backfill", "--start-date", "2026-11-09",
                        "--end-date", "2026-11-08" if scenario == "reversed" else "2026-11-09",
                        "--symbols", "BTCUSDT", "--types", "trade", "--data-root", str(root), "--dry-run"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("bybit_data_downloader.backfill", run_name="__main__")
    assert stopped.value.code == 1
    record = failure_record(capsys)
    assert record["phase"] == "planning"
    assert record["error"] == ("ValueError" if scenario == "reversed" else "HTTPStatusError")
    assert not root.exists()
    assert calls == ([] if scenario == "reversed" else ["HEAD"])


def test_execution_failure_reports_failed_job_without_upstream_values(tmp_path, capsys):
    job = dict(day="2026-11-09", symbol="BTCUSDT", type="funding", source="api",
               path="market_metrics/funding/BTCUSDT/2026-11-09.json",
               url="https://example.test/api?credential=fixture-secret", expected_bytes=None)
    response = dict(retCode=0, result=dict(list=[dict(
        symbol="BTCUSDT", fundingRate="fixture-secret", fundingRateTimestamp="1794182400000",
    )]))
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))) as client:
        with pytest.raises(Exception):
            execute([job], tmp_path, client)
    record = failure_record(capsys)
    assert record["error"] == "ValidationError"
    assert "pattern" in record["error_message"] and "fundingRate" in record["error_message"]
    assert (record["error_type"], record["error_day"], record["error_symbol"], record["error_target"]) == (
        job["type"], job["day"], job["symbol"], job["path"],
    )
    assert "fixture-secret" not in json.dumps(record)
    assert json.loads((tmp_path / "logs/backfill.jsonl").read_text()) == record


@pytest.mark.parametrize(("error", "message"), [
    (json.JSONDecodeError("fixture-secret", "fixture-secret", 0), "Invalid JSON at line 1, column 1"),
    (zipfile.BadZipFile("fixture-secret"), "Invalid ZIP archive"),
    (EOFError("fixture-secret"), "Unexpected end of archive"),
    (ValueError("fixture-secret"), "Execution failed (ValueError)"),
])
def test_untrusted_exception_text_is_omitted(tmp_path, capsys, error, message):
    job = dict(day="2026-11-09", symbol="BTCUSDT", type="trade", source="archive",
               path="historical/day.gz", url="https://example.test/day", expected_bytes=None)

    def respond(request):
        raise error

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(type(error)):
            execute([job], tmp_path, client)
    record = failure_record(capsys)
    assert record["error_message"] == message
    assert "fixture-secret" not in json.dumps(record)
    assert json.loads((tmp_path / "logs/backfill.jsonl").read_text()) == record


def test_logging_failure_reports_when_no_job_failed(tmp_path, monkeypatch, capsys):
    def failed_sync(fd):
        raise OSError(errno.ENOSPC, "fixture-secret")

    monkeypatch.setattr("bybit_data_downloader.backfill_execute.os.fsync", failed_sync)
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP"))) as client:
        with pytest.raises(OSError):
            execute([], tmp_path, client)
    record = failure_record(capsys)
    assert record["log_error"] == "OSError"
    assert "space" in record["error_message"].lower()
    assert record["error_target"] is None
    assert "fixture-secret" not in json.dumps(record)

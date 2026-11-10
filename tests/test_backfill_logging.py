"""Run failures before download must remain observable without archive access."""
import fcntl
import json

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
    assert calls == ["HEAD"]
    assert json.loads((tmp_path / "logs/backfill.jsonl").read_text()) == record


def test_busy_lock_logs_failure(tmp_path, capsys):
    with (tmp_path / ".backfill.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No HTTP"))) as client:
            with pytest.raises(BlockingIOError): execute([], tmp_path, client)
    record = failure_record(capsys)
    assert record["error"] == "BlockingIOError"
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

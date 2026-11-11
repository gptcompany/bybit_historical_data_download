"""Exercise emitted child JSON against the runner's closed schemas, offline in CI."""
import errno
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from bybit_data_downloader import backfill
from scripts import cold_deploy as deploy
from test_backfill_execute import archive as trade_archive


@pytest.mark.parametrize("scenario", ["success", "get404", "head404", "invalid", "log", "plan"])
def test_child_output_contract(scenario, tmp_path, monkeypatch, capsys):
    _, archive_path = trade_archive(tmp_path)
    archive = archive_path.read_bytes()

    def respond(request):
        if scenario == "head404" or (scenario == "get404" and request.method == "GET"):
            return httpx.Response(404)
        return httpx.Response(200, headers={"Content-Length": str(len(archive))}, content=archive)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    if scenario == "log":
        # Fail only the log persistence, after the archive and manifest are committed.
        original_open = Path.open

        def open_path(path, *args, **kwargs):
            if path.name == "backfill.jsonl":
                raise OSError(errno.ENOSPC, "No space left on device")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_path)
    arguments = ["--start-date", "2026-11-09", "--end-date", "2026-11-09",
                 "--symbols", "BTCUSDT", "--types", "invalid" if scenario == "invalid" else "trade",
                 "--data-root", str(tmp_path)]
    if scenario == "plan":
        arguments.append("--dry-run")
    failed = scenario not in {"success", "plan"}
    if failed:
        with pytest.raises(Exception):
            backfill.main(arguments)
    else:
        backfill.main(arguments)
    output = capsys.readouterr().out
    record = json.loads(output)
    model = deploy.PlanSummary if scenario == "plan" else deploy.RunSummary
    model.model_validate_json(output)
    assert model.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(dict(record, unexpected="rejected")))
    assert model.model_config["strict"] is True

    # Also exercise the runner boundary, including exit status and planning failures.
    monkeypatch.setattr(deploy, "drift", lambda *args: {"outcome": "success"})
    monkeypatch.setattr(deploy, "load_release", lambda *args: {"image": "fixture", "image_source_sha": "b" * 40})
    monkeypatch.setattr(deploy, "docker_command", lambda *args: ["offline-child"])
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=int(failed), stdout=output))
    from datetime import date
    result = deploy.run_backfill(tmp_path, date(2026, 11, 9), date(2026, 11, 9), scenario == "plan")
    for key, value in record.items():
        assert result[key] == value
    assert result["outcome"] == ("failure" if failed else "success")


@pytest.mark.parametrize(("field", "value"), [
    ("retries", -1), ("retries", "1"), ("retries", True),
    ("discarded_orderbook_tail", -1), ("discarded_orderbook_tail", "0"),
    ("discarded_orderbook_tail", True), ("error_message", 123),
    ("error_type", "unknown"), ("error_day", "invalid"),
    ("error_symbol", 123), ("error_target", 123),
])
def test_new_summary_fields_reject_invalid_values(field, value):
    record = json.loads((Path(__file__).parent / "fixtures/dell-trade-run-summary.json").read_text())
    with pytest.raises(ValidationError):
        deploy.RunSummary.model_validate_json(json.dumps(dict(record, **{field: value})))


@pytest.mark.parametrize("scenario", ["success", "plan", "head_failure", "get_failure"])
def test_retry_events_cross_runner_boundary(scenario, tmp_path, monkeypatch, capsys):
    from datetime import date
    from bybit_data_downloader import backfill_retry

    _, archive_path = trade_archive(tmp_path)
    archive = archive_path.read_bytes()
    calls = {"HEAD": 0, "GET": 0}

    def respond(request):
        calls[request.method] += 1
        if calls[request.method] == 1 or scenario == request.method.lower() + "_failure":
            raise httpx.ReadTimeout("untrusted upstream detail", request=request)
        return httpx.Response(200, headers={"Content-Length": str(len(archive))}, content=archive)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(backfill_retry.time, "sleep", lambda _: None)
    arguments = ["--start-date", "2026-11-09", "--end-date", "2026-11-09", "--symbols", "BTCUSDT",
                 "--types", "trade", "--data-root", str(tmp_path)]
    if scenario == "plan":
        arguments.append("--dry-run")
    failed = scenario.endswith("failure")
    if failed:
        with pytest.raises(httpx.ReadTimeout):
            backfill.main(arguments)
    else:
        backfill.main(arguments)
    child = capsys.readouterr()
    events = [json.loads(line) for line in child.err.splitlines()]
    expected = 1 if scenario == "plan" else 3 if scenario == "get_failure" else 2
    assert json.loads(child.out)["retries"] == len(events) == expected
    monkeypatch.setattr(deploy, "drift", lambda *args: {"outcome": "success"})
    monkeypatch.setattr(deploy, "load_release", lambda *args:
                        {"image": "fixture", "image_source_sha": "b" * 40, "cold_root": str(tmp_path)})
    monkeypatch.setattr(deploy, "docker_command", lambda *args: ["offline-child"])
    noise = '\n'.join(["untrusted upstream detail", json.dumps(dict(events[0], extra="reject")),
                        json.dumps(dict(events[0], wait_seconds=-1)),
                        json.dumps(dict(events[0], exception="arbitrary text"))])
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=int(failed), stdout=child.out, stderr=child.err + noise))
    result = deploy.run_backfill(tmp_path, date(2026, 11, 9), date(2026, 11, 9), scenario == "plan")
    assert result["retries"] == expected
    assert result["outcome"] == ("failure" if failed else "success")
    assert [json.loads(line) for line in capsys.readouterr().err.splitlines()] == events
    log = tmp_path / "logs/backfill.jsonl"
    if scenario == "plan":
        assert not log.exists()
    else:
        records = [json.loads(line) for line in log.read_text().splitlines()]
        assert [row for row in records if row.get("event") == "retry"] == events


def test_runner_forwards_retry_from_existing_summary(tmp_path, monkeypatch, capsys):
    from datetime import date

    output = (Path(__file__).parent / "fixtures/dell-trade-run-summary.json").read_text()
    event = dict(event="retry", target="historical/trade/contract/BTCUSDT/file.csv.gz",
                 attempt=1, exception="ReadTimeout", wait_seconds=1.0)
    monkeypatch.setattr(deploy, "drift", lambda *args: {"outcome": "success"})
    monkeypatch.setattr(deploy, "load_release", lambda *args:
                        {"image": "fixture", "image_source_sha": "b" * 40, "cold_root": str(tmp_path)})
    monkeypatch.setattr(deploy, "docker_command", lambda *args: ["offline-child"])
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=output, stderr=json.dumps(event) + "\nnoise"))
    result = deploy.run_backfill(tmp_path, date(2026, 11, 9), date(2026, 11, 9))
    assert result["outcome"] == "success"
    assert json.loads(capsys.readouterr().err) == event
    assert json.loads((tmp_path / "logs/backfill.jsonl").read_text()) == event


@pytest.fixture
def retry_child(tmp_path, monkeypatch):
    events = [dict(event="retry", target="historical/trade/contract/BTCUSDT/file.csv.gz",
                   attempt=attempt, exception="ReadTimeout", wait_seconds=1.0) for attempt in (1, 2)]
    child = SimpleNamespace(returncode=0, stdout="", stderr="\n".join(map(json.dumps, events)))
    monkeypatch.setattr(deploy, "drift", lambda *args: {"outcome": "success"})
    monkeypatch.setattr(deploy, "load_release", lambda *args:
                        {"image": "fixture", "image_source_sha": "b" * 40, "cold_root": str(tmp_path)})
    monkeypatch.setattr(deploy, "docker_command", lambda *args: ["offline-child"])
    monkeypatch.setattr(deploy.subprocess, "run", lambda *args, **kwargs: child)
    return child, events


@pytest.mark.parametrize("operation", ["mkdir", "open", "write", "flush", "fsync"])
@pytest.mark.parametrize("child_failed", [False, True])
def test_host_retry_log_failure_preserves_child(retry_child, tmp_path, monkeypatch, capsys,
                                                operation, child_failed):
    from unittest.mock import MagicMock

    child, events = retry_child
    summary = json.loads((Path(__file__).parent / "fixtures/dell-trade-run-summary.json").read_text())
    summary.update(retries=2, files=2, skipped=1)
    if child_failed:
        summary.update(outcome="failure", log_error="OSError", error="ReadTimeout")
        child.returncode = 1
    child.stdout = json.dumps(summary)
    failure = OSError(errno.ENOSPC, "No space left on device")
    stream = MagicMock()
    stream.__enter__.return_value = stream
    if operation in {"write", "flush"}:
        getattr(stream, operation).side_effect = failure
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: stream)
    if operation in {"mkdir", "open"}:
        def fail(*args, **kwargs):
            raise failure
        monkeypatch.setattr(Path, operation, fail)
    monkeypatch.setattr(deploy.os, "fsync", MagicMock(side_effect=failure if operation == "fsync" else None))

    assert deploy.main(["backfill", str(tmp_path), "--start-date", "2026-11-09",
                        "--end-date", "2026-11-09"]) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["phase"] == "execution"
    for field in ("downloaded", "skipped", "records", "retries", "started_at", "finished_at"):
        assert result[field] == summary[field]
    assert result["outcome"] == "failure"
    assert result["log_error"] == "OSError"
    assert result["counts_status"] == "reported"
    assert result["returncode"] == child.returncode
    assert result["image"] == "fixture" and result["image_source_sha"] == "b" * 40
    if child_failed:
        assert result["error"] == "ReadTimeout"
    assert [json.loads(line) for line in captured.err.splitlines()] == events


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("output", [b"", b"not JSON", b'{"unexpected": true}'])
def test_interrupted_child_keeps_valid_retry_events(retry_child, tmp_path, capsys, dry_run, output):
    child, events = retry_child
    child.returncode, child.stdout = 137, output
    child.stderr = (child.stderr + "\nnoise\n" + json.dumps(dict(events[0], extra="reject"))).encode()
    args = ["backfill", str(tmp_path), "--start-date", "2026-11-09", "--end-date", "2026-11-09"]
    assert deploy.main(args + (["--dry-run"] if dry_run else [])) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["error"] == "InvalidRunSummary" and result["counts_status"] == "unknown"
    assert result["phase"] == "container" and result["returncode"] == 137
    assert all(result[field] is None for field in ("downloaded", "skipped", "records"))
    assert [json.loads(line) for line in captured.err.splitlines()] == events
    log = tmp_path / "logs/backfill.jsonl"
    if dry_run:
        assert not log.exists()
    else:
        assert [json.loads(line) for line in log.read_text().splitlines()] == events

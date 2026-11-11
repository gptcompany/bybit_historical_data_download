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

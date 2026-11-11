"""Exercise emitted child JSON against the runner's closed schemas, offline in CI."""
import errno
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from bybit_data_downloader import backfill
from scripts import cold_deploy as deploy


@pytest.mark.parametrize("scenario", ["success", "get404", "head404", "invalid", "log", "plan"])
def test_child_output_contract(scenario, tmp_path, monkeypatch, capsys):
    archive = gzip.compress((Path(__file__).parent / "fixtures/btc-trades-2025-04-02.csv").read_bytes())

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
    arguments = ["--start-date", "2025-04-02", "--end-date", "2025-04-02",
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
    result = deploy.run_backfill(tmp_path, date(2025, 4, 2), date(2025, 4, 2), scenario == "plan")
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

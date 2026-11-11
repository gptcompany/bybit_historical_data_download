"""Cold log faults must preserve results; CI-only offline regression matrix."""
import ast
import errno
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from bybit_data_downloader import backfill, backfill_retry
from bybit_data_downloader.backfill_execute import run_stats, write_run_log
from scripts import cold_deploy as deploy
from test_cold_summary_contract import retry_child


MODULES = ["scripts/cold_deploy.py"] + [
    "src/bybit_data_downloader/" + name + ".py"
    for name in ("backfill", "backfill_execute", "backfill_retry")]
# Data, manifest, lock and unit I/O are outside the logging contract.
DATA_IO = {"_install", "_validate", "digest", "download_file", "execute", "publish_orderbook_day", "scan"}
OUTPUT = {"print", "open", "write", "write_text", "write_bytes", "flush", "fsync", "mkdir"}


def direct_output(tree):
    violations = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function.name == "emit":
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name in OUTPUT and (name == "print" or function.name not in DATA_IO):
                violations.append((function.name, node.lineno, name))
    return violations


@pytest.mark.parametrize("module", MODULES)
def test_cold_output_only_through_emitter(module):
    tree = ast.parse((Path(__file__).parents[1] / module).read_text())
    assert direct_output(tree) == []


@pytest.mark.parametrize("statement", ["print(event)", "sys.stderr.write(event)",
                                       "log.open('a')", "stream.flush()", "os.fsync(fd)"])
def test_ast_gate_rejects_direct_output(statement):
    assert direct_output(ast.parse("def new_cold_step():\n    " + statement))


@pytest.mark.parametrize("operation", ["mkdir", "open", "write", "flush", "fsync", "close"])
def test_container_log_fault_preserves_summary(operation, tmp_path, monkeypatch, capsys):
    stats = run_stats([])
    stats.update(outcome="success", phase="execution", files=2, downloaded=1, skipped=1, records=17, retries=2)
    stream = MagicMock()
    stream.__enter__.return_value = stream
    failure = OSError(errno.ENOSPC, "untrusted detail")
    if operation in {"write", "flush"}:
        getattr(stream, operation).side_effect = failure
    if operation == "close":
        stream.__exit__.side_effect = failure
    monkeypatch.setattr(Path, "open", MagicMock(side_effect=failure if operation == "open" else None,
                                               return_value=stream))
    monkeypatch.setattr(Path, "mkdir", MagicMock(side_effect=failure if operation == "mkdir" else None))
    monkeypatch.setattr(deploy.os, "fsync", MagicMock(side_effect=failure if operation == "fsync" else None))
    with pytest.raises(OSError):
        write_run_log(stats, tmp_path)
    result = json.loads(capsys.readouterr().out)
    assert result["log_error"] == "OSError" and result["events_not_written"] == 0
    assert (result["phase"], result["downloaded"], result["skipped"], result["records"], result["retries"]) == (
        "execution", 1, 1, 17, 2)
    assert "untrusted detail" not in json.dumps(result)


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize("error_type", [OSError, BrokenPipeError])
@pytest.mark.parametrize("side", ["container", "host", "plan"])
def test_final_stdout_fault_keeps_result(side, operation, error_type, tmp_path, monkeypatch):
    stream = MagicMock()
    getattr(stream, operation).side_effect = error_type(errno.EIO, "untrusted detail")
    monkeypatch.setattr(sys, "stdout", stream)
    stats = run_stats([])
    stats.update(outcome="success", phase="execution", files=1, downloaded=1, records=17, retries=2)
    if side == "container":
        with pytest.raises(OSError):
            write_run_log(stats, tmp_path)
        saved = json.loads((tmp_path / "logs/backfill.jsonl").read_text())
        assert saved["records"] == 17 and saved["retries"] == 2
    elif side == "host":
        monkeypatch.setattr(deploy, "run_backfill", lambda *args: stats)
        assert deploy.main(["backfill", str(tmp_path)]) == 1
    else:
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
        with pytest.raises(OSError):
            backfill.main(["--start-date", "2026-11-09", "--end-date", "2026-11-09", "--types", "klines",
                           "--data-root", str(tmp_path / "absent"), "--dry-run"])
        assert not (tmp_path / "absent").exists()
        attempted = json.loads(stream.write.call_args_list[0].args[0])
        assert attempted["events_not_written"] == 0 and attempted["retries"] == 0
        return
    assert stats["log_error"] == error_type.__name__
    assert stats["phase"] == "execution" and stats["records"] == 17 and stats["retries"] == 2


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize("phase", ["planning", "execution", "dry_run"])
def test_retry_stderr_fault_does_not_stop_work(phase, operation, tmp_path, monkeypatch, capsys):
    stream = MagicMock()
    getattr(stream, operation).side_effect = OSError(errno.EIO, "untrusted detail")
    monkeypatch.setattr(sys, "stderr", stream)
    calls = []
    def respond(request):
        calls.append(request.method)
        if len(calls) == 1:
            raise httpx.ReadTimeout("untrusted detail", request=request)
        return httpx.Response(200, headers={"Content-Length": "1"}, content=b"x")
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(backfill_retry.time, "sleep", lambda _: None)
    # Planning retry is followed by real execution; an empty API plan tests execution separately.
    if phase == "execution":
        from bybit_data_downloader import backfill_execute
        def download(*args):
            if not calls:
                calls.append("GET")
                raise httpx.ReadTimeout("untrusted detail")
            raise ValueError("stop after retry")
        monkeypatch.setattr(backfill_execute, "download_file", download)
    args = ["--start-date", "2026-11-09", "--end-date", "2026-11-09", "--symbols", "BTCUSDT",
            "--types", "klines" if phase == "execution" else "trade", "--data-root", str(tmp_path)]
    with pytest.raises(Exception):
        backfill.main(args + (["--dry-run"] if phase == "dry_run" else []))
    result = json.loads(capsys.readouterr().out)
    assert result["retries"] == 1 and result["log_error"] == "OSError"
    assert result["events_not_written"] == 1
    assert len(calls) >= (1 if phase == "execution" else 2)


@pytest.mark.parametrize("operation", ["mkdir", "open", "write", "flush", "fsync", "close"])
def test_host_both_channels_count_lost_events(operation, retry_child, tmp_path, monkeypatch):
    from datetime import date
    child, events = retry_child
    failure = OSError(errno.ENOSPC, "untrusted detail")
    stream = MagicMock()
    stream.write.side_effect = BrokenPipeError(errno.EPIPE, "closed pipe")
    monkeypatch.setattr(sys, "stderr", stream)
    log = MagicMock()
    log.__enter__.return_value = log
    if operation in {"write", "flush"}:
        getattr(log, operation).side_effect = failure
    if operation == "close":
        log.__exit__.side_effect = failure
    monkeypatch.setattr(Path, "open", MagicMock(side_effect=failure if operation == "open" else None,
                                               return_value=log))
    monkeypatch.setattr(Path, "mkdir", MagicMock(side_effect=failure if operation == "mkdir" else None))
    monkeypatch.setattr(deploy.os, "fsync", MagicMock(side_effect=failure if operation == "fsync" else None))
    result = deploy.run_backfill(tmp_path, date(2026, 11, 9), date(2026, 11, 9))
    assert result["events_not_written"] == len(events)
    assert result["log_error"] == "OSError"  # File is attempted before stderr; first error survives.
    assert result["phase"] == "container" and result["counts_status"] == "unknown"
    assert stream.write.call_count >= len(events)

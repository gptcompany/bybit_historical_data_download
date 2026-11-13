"""Offline scheduler entrypoints: UTC day, drift gate and pinned container argv."""
from datetime import datetime, timezone
import json
import sys
from subprocess import run as run_child
from types import SimpleNamespace

import pytest

from scripts import cold_deploy as deploy


CONFIG = dict(image="ghcr.io/gptcompany/bybit-downloader@sha256:" + "a" * 64,
              image_source_sha="b" * 40, user="sam", uid=1000, gid=1000,
              dns=['1.1.1.1', '9.9.9.9'], cold_root="/data/cold/12TB/bybit_data_downloader/data")


def container():
    return "bybit-cold-" + deploy.os.environ["INVOCATION_ID"]


@pytest.fixture
def docker_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy, "load_release", lambda release: CONFIG)
    monkeypatch.setattr(deploy, "drift", lambda release, units: dict(outcome="success", mismatches=[]))
    def run(command, **kwargs):
        assert command[0] == "/usr/bin/docker"
        assert not kwargs.get("shell", False)
        calls.append(command)
        output = dict(days=134, files=0, archive_bytes=0, api_files_unknown_bytes=0,
                      data_root='/data', jobs=[]) if '--dry-run' in command else CHILD
        return SimpleNamespace(returncode=0, stdout=json.dumps(output), stderr='')
    monkeypatch.setattr(deploy.subprocess, "run", run)
    return calls


def test_daily_entrypoint_uses_yesterday_utc(docker_calls, monkeypatch, capsys):
    class Clock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2026, 11, 10, 0, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(deploy, "datetime", Clock)
    assert deploy.main(["run", "/release"]) == 0
    command = docker_calls[0]
    assert command[command.index("--start-date") + 1] == "2026-11-09"
    assert command[command.index("--end-date") + 1] == "2026-11-09"
    assert CONFIG["image"] in command and "--pull=never" in command
    assert command[command.index("--name") + 1] == container()
    assert json.loads(capsys.readouterr().out)["outcome"] == "success"


@pytest.mark.parametrize("invocation", [None, "", "not-a-systemd-id"])
def test_runner_outside_systemd_never_starts_a_session_bound_container(docker_calls, monkeypatch, capsys,
                                                                       invocation):
    if invocation is None:
        monkeypatch.delenv("INVOCATION_ID")
    else:
        monkeypatch.setenv("INVOCATION_ID", invocation)
    assert deploy.main(["run", "/release"]) == 1
    assert docker_calls == []
    assert json.loads(capsys.readouterr().out)["phase"] == "preflight"


@pytest.mark.parametrize("listed", ["", "4f2a\n"])
def test_stop_post_stops_only_this_invocation_container(monkeypatch, capsys, listed):
    calls = []
    def docker(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=listed if command[1] == "ps" else "", stderr="")
    monkeypatch.setattr(deploy.subprocess, "run", docker)
    assert deploy.main(["reap", "/release"]) == 0
    name = container()
    assert calls[0] == ["/usr/bin/docker", "ps", "--all", "--quiet", "--filter", "name=" + name]
    assert calls[1:] == ([["/usr/bin/docker", "stop", name]] if listed else [])
    assert json.loads(capsys.readouterr().out) == dict(outcome="success", finding="F-649", timezone="UTC",
                                                       container=name, stopped=int(bool(listed)))


def test_stop_post_fails_loudly_when_docker_cannot_list(monkeypatch, capsys):
    def unavailable(command, **kwargs):
        raise deploy.subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(deploy.subprocess, "run", unavailable)
    assert deploy.main(["reap", "/release"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "CalledProcessError"


def test_backfill_forwards_explicit_selection_and_dry_run(docker_calls, capsys):
    assert deploy.main(["backfill", "/release", "--start-date", "2026-06-29", "--end-date", "2026-11-09",
                        "--symbols", "BTCUSDT,ETHUSDT", "--types", "trade,orderbook",
                        "--intervals", "1m,5m,15m", "--dry-run"]) == 0
    command = docker_calls[0]
    for flag, value in [("--start-date", "2026-06-29"), ("--end-date", "2026-11-09"),
                        ("--symbols", "BTCUSDT,ETHUSDT"), ("--types", "trade,orderbook"),
                        ("--intervals", "1m,5m,15m")]:
        assert command[command.index(flag) + 1] == value
    assert "--dry-run" in command
    assert "--entrypoint" in command and "bash" not in command


def test_drift_blocks_container(docker_calls, monkeypatch, capsys):
    monkeypatch.setattr(deploy, "drift", lambda release, units: dict(outcome="failure", mismatches=["bybit-cold.timer"]))
    assert deploy.main(["run", "/release"]) == 1
    assert docker_calls == []
    result = json.loads(capsys.readouterr().out)
    assert result["finding"] == "F-649" and result["phase"] == "preflight"
    assert result["downloaded"] == result["skipped"] == result["records"] == 0


def test_container_failure_is_not_success(docker_calls, monkeypatch, capsys):
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs:
                        SimpleNamespace(returncode=1, stdout=json.dumps(dict(CHILD, outcome='failure', error='ValueError')), stderr=''))
    assert deploy.main(["run", "/release"]) == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "failure"


@pytest.mark.parametrize("arguments", [[], ["--start-date", "2026-11-09", "--end-date", "2026-06-29"]])
def test_missing_or_reversed_range_never_launches(docker_calls, arguments, capsys):
    assert deploy.main(["backfill", "/release", *arguments]) == 1
    assert docker_calls == []


CHILD = dict(outcome="success", downloaded=1, skipped=0, records=1440, quarantined=[],
             files=1, timezone="UTC", started_at="2026-11-10T03:15:00+00:00",
             finished_at="2026-11-10T03:16:00+00:00", days=["2026-11-09"], phase="execution")


@pytest.mark.parametrize("failed", [False, True])
def test_single_enriched_child_summary(docker_calls, monkeypatch, capsys, failed):
    child = dict(CHILD, outcome="failure" if failed else "success")
    if failed: child["error"] = "ValueError"
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs:
                        SimpleNamespace(returncode=int(failed), stdout=json.dumps(child), stderr=""))
    assert deploy.main(["run", "/release"]) == int(failed)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    for field, value in child.items(): assert result[field] == value
    assert result["image"] == CONFIG["image"] and result["image_source_sha"] == CONFIG["image_source_sha"]
    assert result["counts_status"] == "reported"


@pytest.mark.parametrize("code", [125, 126, 127])
def test_container_not_started_is_explicit(docker_calls, monkeypatch, capsys, code):
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs:
                        SimpleNamespace(returncode=code, stdout="", stderr="unavailable"))
    assert deploy.main(["run", "/release"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["counts_status"] == "not_started"
    assert all(result[key] is None for key in ("downloaded", "skipped", "records"))
    assert result["error"] == "ContainerNotStarted" and result["timezone"] == "UTC"


@pytest.mark.parametrize("output", ["", "invalid", json.dumps(dict(CHILD, unexpected="rejected")),
                                    json.dumps(dict(CHILD, records="1440")),
                                    json.dumps(dict(CHILD, started_at="2026-11-10T03:15:00"))])
def test_missing_or_invalid_child_summary_fails_closed(docker_calls, monkeypatch, capsys, output):
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs:
                        SimpleNamespace(returncode=0, stdout=output, stderr="rejected"))
    assert deploy.main(["run", "/release"]) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["counts_status"] == "unknown" and result["error"] == "InvalidRunSummary"
    assert all(result[key] is None for key in ("downloaded", "skipped", "records"))
    assert "rejected" not in captured.out + captured.err


def test_missing_docker_binary_is_not_zero_progress(docker_calls, monkeypatch, capsys):
    def unavailable(command, **kwargs):
        raise FileNotFoundError('docker')
    monkeypatch.setattr(deploy.subprocess, 'run', unavailable)
    assert deploy.main(['run', '/release']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['counts_status'] == 'not_started' and result['error'] == 'ContainerNotStarted'
    assert result['image'] == CONFIG['image']
    assert all(result[key] is None for key in ('downloaded', 'skipped', 'records'))


@pytest.mark.parametrize("valid_stdout", [False, True])
def test_non_utf8_container_streams_preserve_progress(docker_calls, monkeypatch, capsys, valid_stdout):
    output = json.dumps(CHILD).encode() if valid_stdout else b"\xff"
    def run(command, **kwargs):
        # A real stdlib child exercises subprocess decoding, never Docker or HTTP.
        code = f"import sys;sys.stdout.buffer.write({output!r});sys.stderr.buffer.write(b'\\xff')"
        return run_child([sys.executable, "-c", code], **kwargs)
    monkeypatch.setattr(deploy.subprocess, "run", run)
    assert deploy.main(["run", "/release"]) == (0 if valid_stdout else 1)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["image"] == CONFIG["image"] and result["image_source_sha"] == CONFIG["image_source_sha"]
    if valid_stdout:
        assert result["counts_status"] == "reported" and result["records"] == 1440
    else:
        assert result["counts_status"] == "unknown" and result["phase"] == "container"
        assert all(result[key] is None for key in ("downloaded", "skipped", "records"))


def test_dell_trade_summary_preserves_observed_progress(docker_calls, monkeypatch, capsys):
    # Dell bbbd0c6, 2026-11-11 02:21 UTC: observed counts/day; timestamps reconstructed.
    from pathlib import Path
    child = json.loads((Path(__file__).parent / "fixtures/dell-trade-run-summary.json").read_text())
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs:
                        SimpleNamespace(returncode=0, stdout=json.dumps(child), stderr=""))
    assert deploy.main(["backfill", "/release", "--start-date", "2026-06-30",
                        "--end-date", "2026-06-30", "--symbols", "BTCUSDT", "--types", "trade"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts_status"] == "reported"
    for key, value in child.items():
        assert result[key] == value
